"""
火山云安全操作工具 - 停机/启动/重启/释放
直接调用火山云 ECS OpenAPI（通过 SDK）
"""
from ..audit import audit_log
from ..protection import check_protection
from .query_tools import _get_ecs_service, _call


def volc_stop_instances(account: str, region_id: str, instance_ids: list[str]) -> dict:
    """停止火山云 ECS 实例。

    Args:
        account: 火山云账号名称，如 volc_production
        region_id: 地域ID，如 cn-beijing
        instance_ids: 实例ID列表

    Returns:
        操作结果
    """
    try:
        svc = _get_ecs_service(account, region_id)
        args = {"Region": region_id}
        for idx, iid in enumerate(instance_ids, 1):
            args[f"InstanceIds.{idx}"] = iid
        resp = _call(svc, "StopInstances", args)
        audit_log("volc_stop", {"account": account, "region": region_id, "instances": instance_ids})
        return {"success": True, "message": f"已发送停止指令: {instance_ids}", "response": resp}
    except Exception as e:
        return {"error": str(e)}


def volc_start_instances(account: str, region_id: str, instance_ids: list[str]) -> dict:
    """启动火山云 ECS 实例。

    Args:
        account: 火山云账号名称
        region_id: 地域ID
        instance_ids: 实例ID列表

    Returns:
        操作结果
    """
    try:
        svc = _get_ecs_service(account, region_id)
        args = {"Region": region_id}
        for idx, iid in enumerate(instance_ids, 1):
            args[f"InstanceIds.{idx}"] = iid
        resp = _call(svc, "StartInstances", args)
        audit_log("volc_start", {"account": account, "region": region_id, "instances": instance_ids})
        return {"success": True, "message": f"已发送启动指令: {instance_ids}", "response": resp}
    except Exception as e:
        return {"error": str(e)}


def volc_reboot_instances(account: str, region_id: str, instance_ids: list[str]) -> dict:
    """重启火山云 ECS 实例。

    Args:
        account: 火山云账号名称
        region_id: 地域ID
        instance_ids: 实例ID列表

    Returns:
        操作结果
    """
    try:
        svc = _get_ecs_service(account, region_id)
        args = {"Region": region_id}
        for idx, iid in enumerate(instance_ids, 1):
            args[f"InstanceIds.{idx}"] = iid
        resp = _call(svc, "RebootInstances", args)
        audit_log("volc_reboot", {"account": account, "region": region_id, "instances": instance_ids})
        return {"success": True, "message": f"已发送重启指令: {instance_ids}", "response": resp}
    except Exception as e:
        return {"error": str(e)}


def volc_delete_instance(account: str, region_id: str, instance_id: str,
                         instance_name: str = "", charge_type: str = "") -> dict:
    """释放/退订火山云 ECS 实例。按量付费走 DeleteInstance，包年包月走 UnsubscribeInstance。

    Args:
        account: 火山云账号名称
        region_id: 地域ID
        instance_id: 实例ID
        instance_name: 实例名称（用于保护规则校验）
        charge_type: 计费类型，来自查询结果的 charge 字段。PrePaid=包年包月，PostPaid=按量付费

    Returns:
        操作结果
    """
    from . import billing_tools
    result = {"account": account, "instance_id": instance_id, "region": region_id,
              "instance_name": instance_name, "charge_type": charge_type}

    if instance_name:
        protected = check_protection(instance_name)
        if protected:
            audit_log("volc_delete_blocked", {**result, "reason": f"protected: {protected}"})
            return {**result, "blocked": True, "error": f"实例 [{instance_name}] 匹配保护规则 [{protected}]，禁止释放"}

    if charge_type.lower() in ("prepaid", "subscription", "包年包月"):
        refund_result = billing_tools.volc_refund_instance(account, instance_id)
        return {**result, "route": "refund", **refund_result}

    try:
        svc = _get_ecs_service(account, region_id)
        resp = _call(svc, "DeleteInstance", {
            "Region": region_id, "InstanceId": instance_id,
        })
        audit_log("volc_delete", result)
        return {**result, "route": "delete", "success": True,
                "message": f"实例 {instance_name or instance_id} 已释放", "response": resp}
    except Exception as e:
        audit_log("volc_delete_error", {**result, "error": str(e)})
        return {**result, "error": str(e)}
