"""
ECS 回收工具 - ITSM 触发的一键回收流程
包含：查询 → 保护校验 → 停机 → 打快照 → 退订/释放 → 审计日志
"""
import json
import os
from datetime import datetime

from .mcp_manager import MCPManager
from . import safe_tools
from . import billing_tools

# 多账号 AccessKey（复用 billing_tools 的配置，快照/磁盘查询走 ECS SDK）
_ECS_ACCOUNTS = {
    "openclaw": {
        "access_key": os.environ.get("ALIYUN_AK_OPENCLAW", ""),
        "secret_key": os.environ.get("ALIYUN_SK_OPENCLAW", ""),
    },
    "production": {
        "access_key": os.environ.get("ALIYUN_AK_PRODUCTION", ""),
        "secret_key": os.environ.get("ALIYUN_SK_PRODUCTION", ""),
    },
}


def _get_ecs_client(account: str, region_id: str):
    """获取 ECS SDK 客户端"""
    try:
        from alibabacloud_ecs20140526.client import Client
        from alibabacloud_tea_openapi.models import Config
    except ImportError:
        return None

    account_key = billing_tools.BILLING_ACCOUNTS.get(account)
    if not account_key:
        # 尝试别名解析
        for k, v in billing_tools.BILLING_ACCOUNTS.items():
            if account.lower() in [k] + [a.lower() for a in v.get("aliases", [])]:
                account_key = v
                break
    if not account_key or not account_key.get("access_key"):
        return None

    config = Config(
        access_key_id=account_key["access_key"],
        access_key_secret=account_key["secret_key"],
        endpoint=f"ecs.{region_id}.aliyuncs.com",
    )
    return Client(config)


def _audit_log(action: str, detail: dict):
    log_dir = os.path.join(os.path.dirname(__file__), "..", "audit_logs")
    os.makedirs(log_dir, exist_ok=True)
    entry = {"time": datetime.now().isoformat(), "action": action, **detail}
    filepath = os.path.join(log_dir, f"audit_{datetime.now():%Y%m%d}.jsonl")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def recycle_ecs(instance_id: str, account: str, region_id: str, ticket_id: str = "") -> dict:
    """一键回收 ECS 实例。ITSM 工单审批通过后调用此工具，自动完成：查询→保护校验→停机→打快照→退订/释放。

    Args:
        instance_id: ECS实例ID，如 i-wz96fsimhadx7bv6qovk
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID，如 cn-shenzhen
        ticket_id: ITSM 工单号（可选，用于审计关联）

    Returns:
        回收结果（结构化 JSON）
    """
    ctx = {"instance_id": instance_id, "account": account, "region_id": region_id,
           "ticket_id": ticket_id}
    steps = []

    # ---- Step 1: 查询实例 ----
    try:
        data = MCPManager.call(account, "ECS_DescribeInstances",
                               {"RegionId": region_id, "InstanceIds": [instance_id]}, timeout=35)
    except ValueError as e:
        return {"success": False, "error": str(e), "steps": steps, **ctx}

    if not data:
        steps.append({"step": "query", "status": "error", "reason": "MCP 查询无响应"})
        return {"success": False, "error": "查询无响应，请检查 MCP 连接", "steps": steps, **ctx}

    instances = data.get("body", {}).get("Instances", {}).get("Instance", [])
    if not instances:
        steps.append({"step": "query", "status": "error", "reason": f"实例 {instance_id} 不存在"})
        return {"success": False, "error": f"实例 {instance_id} 不存在", "steps": steps, **ctx}

    inst = instances[0]
    inst_name = inst.get("InstanceName", "")
    status = inst.get("Status", "")
    charge_type = inst.get("InstanceChargeType", "PostPaid")
    steps.append({"step": "query", "status": "ok", "instance_name": inst_name,
                  "instance_status": status, "charge_type": charge_type})

    # ---- Step 2: 保护规则校验 ----
    protected = safe_tools._check_protection(inst_name)
    if protected:
        steps.append({"step": "protection", "status": "blocked", "reason": f"匹配保护规则: {protected}"})
        _audit_log("recycle_blocked", {**ctx, "instance_name": inst_name, "reason": f"protected: {protected}"})
        return {"success": False, "blocked": True,
                "error": f"实例 [{inst_name}] 匹配保护规则 [{protected}]，禁止回收", "steps": steps, **ctx}

    steps.append({"step": "protection", "status": "ok"})

    # ---- Step 3: 停机（如果 Running） ----
    if status == "Running":
        try:
            stop_data = MCPManager.call(account, "OOS_StopInstances",
                                        {"RegionId": region_id, "InstanceIds": [instance_id]}, timeout=35)
            if stop_data:
                steps.append({"step": "stop", "status": "ok"})
                _audit_log("recycle_stop", {**ctx, "instance_name": inst_name})
            else:
                steps.append({"step": "stop", "status": "warn", "reason": "停机指令无响应，继续执行"})
        except Exception as e:
            steps.append({"step": "stop", "status": "warn", "reason": str(e)})
    else:
        steps.append({"step": "stop", "status": "skipped", "reason": f"当前状态: {status}"})

    # ---- Step 4: 打快照 ----
    snapshot_ids = _create_snapshots(account, region_id, instance_id, inst_name)
    if snapshot_ids:
        steps.append({"step": "snapshot", "status": "ok", "snapshot_ids": snapshot_ids})
        _audit_log("recycle_snapshot", {**ctx, "instance_name": inst_name, "snapshot_ids": snapshot_ids})
    else:
        steps.append({"step": "snapshot", "status": "skipped", "reason": "无可用磁盘或 SDK 未配置"})

    # ---- Step 5: 退订/释放 ----
    if charge_type == "PrePaid":
        refund_result = billing_tools.refund_instance(account=account, instance_id=instance_id)
        route = "bss_refund"
        if refund_result.get("success"):
            steps.append({"step": "release", "status": "ok", "route": route,
                          "order_id": refund_result.get("order_id", "")})
        else:
            steps.append({"step": "release", "status": "error", "route": route,
                          "error": refund_result.get("message", refund_result.get("error", ""))})
        _audit_log("recycle_release", {**ctx, "instance_name": inst_name, "route": route, "result": refund_result})
        release_ok = refund_result.get("success", False)
    else:
        try:
            del_data = MCPManager.call(account, "ECS_DeleteInstances", {
                "RegionId": region_id, "InstanceId": [instance_id], "Force": True,
            }, timeout=35)
            route = "mcp_delete"
            if del_data and del_data.get("statusCode") == 200:
                steps.append({"step": "release", "status": "ok", "route": route})
                release_ok = True
            elif del_data:
                error_msg = del_data.get("body", {}).get("Message", "")
                steps.append({"step": "release", "status": "error", "route": route, "error": error_msg})
                release_ok = False
            else:
                steps.append({"step": "release", "status": "error", "route": route, "error": "释放无响应"})
                release_ok = False
            _audit_log("recycle_release", {**ctx, "instance_name": inst_name, "route": route})
        except ValueError as e:
            steps.append({"step": "release", "status": "error", "route": "mcp_delete", "error": str(e)})
            release_ok = False

    return {"success": release_ok, "instance_id": instance_id, "instance_name": inst_name,
            "account": account, "region_id": region_id, "ticket_id": ticket_id,
            "charge_type": charge_type, "steps": steps}


def _create_snapshots(account: str, region_id: str, instance_id: str, instance_name: str) -> list[str]:
    """查询实例磁盘并创建快照，返回快照 ID 列表"""
    client = _get_ecs_client(account, region_id)
    if not client:
        return []

    try:
        from alibabacloud_ecs20140526 import models as ecs_models
    except ImportError:
        return []

    # 查询磁盘
    try:
        disk_resp = client.describe_disks(ecs_models.DescribeDisksRequest(
            region_id=region_id, instance_id=instance_id, page_size=20,
        ))
        disks = disk_resp.body.disks.disk if disk_resp.body and disk_resp.body.disks else []
    except Exception:
        return []

    if not disks:
        return []

    # 逐盘创建快照
    snapshot_ids = []
    ts = datetime.now().strftime("%Y%m%d%H%M")
    for disk in disks:
        disk_id = disk.disk_id
        snapshot_name = f"recycle-{instance_name[:20]}-{disk_id[-6:]}-{ts}"
        try:
            snap_resp = client.create_snapshot(ecs_models.CreateSnapshotRequest(
                disk_id=disk_id,
                snapshot_name=snapshot_name,
                description=f"Recycle snapshot for {instance_id}, ticket auto-created",
            ))
            if snap_resp.body and snap_resp.body.snapshot_id:
                snapshot_ids.append(snap_resp.body.snapshot_id)
        except Exception:
            pass

    return snapshot_ids
