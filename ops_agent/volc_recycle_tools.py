"""
火山云 ECS 回收工具 - ITSM 触发的一键回收流程
直接调用火山云 ECS OpenAPI（通过 SDK）
流程：查询 → 保护校验 → 停机 → 打快照 → 释放 → 审计日志
"""
import json
import os
from datetime import datetime

from . import safe_tools
from .volc_query_tools import _get_ecs_service, _fmt_volc_instances, VOLC_ACCOUNTS


def _audit_log(action: str, detail: dict):
    log_dir = os.path.join(os.path.dirname(__file__), "..", "audit_logs")
    os.makedirs(log_dir, exist_ok=True)
    entry = {"time": datetime.now().isoformat(), "action": action, **detail}
    filepath = os.path.join(log_dir, f"audit_{datetime.now():%Y%m%d}.jsonl")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def volc_recycle_ecs(instance_id: str, account: str, region_id: str = "cn-beijing",
                     ticket_id: str = "") -> dict:
    """一键回收火山云 ECS 实例。ITSM 工单审批通过后调用，自动完成：查询→保护校验→停机→打快照→释放。

    Args:
        instance_id: 实例ID
        account: 火山云账号名称，如 volc_production
        region_id: 地域ID，如 cn-beijing
        ticket_id: ITSM 工单号（可选，用于审计关联）

    Returns:
        回收结果（结构化 JSON）
    """
    ctx = {"instance_id": instance_id, "account": account, "region_id": region_id, "ticket_id": ticket_id}
    steps = []

    # ---- Step 1: 查询实例 ----
    try:
        svc = _get_ecs_service(account, region_id)
        resp = svc.get("DescribeInstances", {
            "Region": region_id, "InstanceIds.1": instance_id,
        })
        result = resp.get("Result", {}) if isinstance(resp, dict) else {}
        instances = _fmt_volc_instances(result)
    except Exception as e:
        return {"success": False, "error": str(e), "steps": steps, **ctx}

    if not instances:
        steps.append({"step": "query", "status": "error", "reason": f"实例 {instance_id} 不存在"})
        return {"success": False, "error": f"实例 {instance_id} 不存在", "steps": steps, **ctx}

    inst = instances[0]
    inst_name = inst["name"]
    status = inst["status"]
    charge_type = inst["charge"]
    steps.append({"step": "query", "status": "ok", "instance_name": inst_name,
                  "instance_status": status, "charge_type": charge_type})

    # ---- Step 2: 保护规则校验 ----
    protected = safe_tools._check_protection(inst_name)
    if protected:
        steps.append({"step": "protection", "status": "blocked", "reason": f"匹配保护规则: {protected}"})
        _audit_log("volc_recycle_blocked", {**ctx, "instance_name": inst_name, "reason": f"protected: {protected}"})
        return {"success": False, "blocked": True,
                "error": f"实例 [{inst_name}] 匹配保护规则 [{protected}]，禁止回收", "steps": steps, **ctx}
    steps.append({"step": "protection", "status": "ok"})

    # ---- Step 3: 停机（如果 Running） ----
    if status.upper() == "RUNNING":
        try:
            svc.get("StopInstances", {"Region": region_id, "InstanceIds.1": instance_id})
            steps.append({"step": "stop", "status": "ok"})
            _audit_log("volc_recycle_stop", {**ctx, "instance_name": inst_name})
        except Exception as e:
            steps.append({"step": "stop", "status": "warn", "reason": str(e)})
    else:
        steps.append({"step": "stop", "status": "skipped", "reason": f"当前状态: {status}"})

    # ---- Step 4: 打快照 ----
    snapshot_ids = _create_snapshots(account, region_id, instance_id, inst_name)
    if snapshot_ids:
        steps.append({"step": "snapshot", "status": "ok", "snapshot_ids": snapshot_ids})
        _audit_log("volc_recycle_snapshot", {**ctx, "instance_name": inst_name, "snapshot_ids": snapshot_ids})
    else:
        steps.append({"step": "snapshot", "status": "skipped", "reason": "无可用磁盘或 SDK 未配置"})

    # ---- Step 5: 释放（包年包月→退订，按量→DeleteInstance） ----
    from . import volc_billing_tools
    if charge_type.lower() in ("prepaid", "subscription", "包年包月"):
        try:
            refund_result = volc_billing_tools.volc_refund_instance(account, instance_id)
            if refund_result.get("success"):
                steps.append({"step": "release", "status": "ok", "route": "billing_refund"})
                _audit_log("volc_recycle_refund", {**ctx, "instance_name": inst_name})
                release_ok = True
            else:
                steps.append({"step": "release", "status": "error", "route": "billing_refund",
                              "error": refund_result.get("error", "unknown")})
                _audit_log("volc_recycle_refund_error", {**ctx, "instance_name": inst_name,
                            "error": refund_result.get("error", "")})
                release_ok = False
        except Exception as e:
            steps.append({"step": "release", "status": "error", "route": "billing_refund", "error": str(e)})
            release_ok = False
    else:
        try:
            svc.get("DeleteInstance", {"Region": region_id, "InstanceId": instance_id})
            steps.append({"step": "release", "status": "ok", "route": "sdk_delete"})
            _audit_log("volc_recycle_release", {**ctx, "instance_name": inst_name})
            release_ok = True
        except Exception as e:
            steps.append({"step": "release", "status": "error", "route": "sdk_delete", "error": str(e)})
            _audit_log("volc_recycle_release_error", {**ctx, "instance_name": inst_name, "error": str(e)})
            release_ok = False

    return {"success": release_ok, "instance_id": instance_id, "instance_name": inst_name,
            "account": account, "region_id": region_id, "ticket_id": ticket_id,
            "charge_type": charge_type, "steps": steps}


def _create_snapshots(account: str, region_id: str, instance_id: str, instance_name: str) -> list[str]:
    """查询实例云盘并创建快照"""
    try:
        svc = _get_ecs_service(account, region_id)
        vol_resp = svc.get("DescribeVolumes", {
            "Region": region_id, "InstanceId": instance_id, "PageSize": 20,
        })
        result = vol_resp.get("Result", {}) if isinstance(vol_resp, dict) else {}
        volumes = result.get("Volumes", [])
    except Exception:
        return []

    if not volumes:
        return []

    snapshot_ids = []
    ts = datetime.now().strftime("%Y%m%d%H%M")
    for vol in volumes:
        vol_id = vol.get("VolumeId", "")
        if not vol_id:
            continue
        snap_name = f"recycle-{instance_name[:20]}-{vol_id[-6:]}-{ts}"
        try:
            snap_resp = svc.get("CreateSnapshot", {
                "Region": region_id, "VolumeId": vol_id, "SnapshotName": snap_name,
                "Description": f"Recycle snapshot for {instance_id}",
            })
            snap_id = ""
            snap_result = snap_resp.get("Result", {}) if isinstance(snap_resp, dict) else {}
            snap_id = snap_result.get("SnapshotId", "")
            if snap_id:
                snapshot_ids.append(snap_id)
        except Exception:
            pass

    return snapshot_ids
