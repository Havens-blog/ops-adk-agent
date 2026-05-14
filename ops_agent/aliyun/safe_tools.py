"""
阿里云安全操作工具 - 危险操作，带保护规则、审计日志
"""
from ..mcp_manager import MCPManager
from ..audit import audit_log
from ..protection import check_protection


def safe_delete_ecs(account: str, region_id: str, instance_id: str,
                    instance_name: str = "", charge_type: str = "PostPaid") -> dict:
    """直接删除/退订 ECS 实例。不会再查询实例信息，请确保调用前已用查询工具确认过实例。

    调用前 Agent 必须：
    1. 先用查询工具获取实例信息并展示给用户
    2. 获得用户明确确认
    3. 将实例名称传入 instance_name 参数用于安全校验
    4. 根据查询结果中的 charge 字段传入 charge_type

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID
        instance_id: 要删除的实例ID
        instance_name: 实例名称（用于保护规则校验，从之前的查询结果中获取）
        charge_type: 计费类型，可选值：PostPaid(按量付费)、PrePaid(包年包月)。
                     查询结果中的 charge 字段值即为此参数，直接传入即可。

    Returns:
        操作结果
    """
    from . import billing_tools

    result = {"account": account, "instance_id": instance_id, "region": region_id,
              "instance_name": instance_name, "charge_type": charge_type}

    if instance_name:
        protected = check_protection(instance_name)
        if protected:
            audit_log("delete_blocked", {**result, "reason": f"protected: {protected}"})
            return {**result, "blocked": True, "error": f"实例 [{instance_name}] 匹配保护规则 [{protected}]，禁止删除！"}

    if charge_type == "PrePaid":
        audit_log("delete_prepaid_route", result)
        refund_result = billing_tools.refund_instance(account=account, instance_id=instance_id)
        refund_result["route"] = "bss_refund"
        return refund_result

    try:
        del_data = MCPManager.call(account, "ECS_DeleteInstances", {
            "RegionId": region_id,
            "InstanceId": [instance_id],
            "Force": True,
        }, timeout=35)
    except ValueError as e:
        audit_log("delete_account_error", {**result, "error": str(e)})
        return {**result, "error": str(e)}

    if not del_data:
        audit_log("delete_no_response", result)
        return {**result, "error": "删除请求已发送但未收到响应，请到阿里云控制台确认实例状态"}

    status_code = del_data.get("statusCode", "unknown")
    req_id = del_data.get("body", {}).get("RequestId", "")
    error_msg = del_data.get("body", {}).get("Message", "")

    audit_log("delete_executed", {**result, "status_code": status_code, "request_id": req_id, "error_msg": error_msg})

    if status_code == 200:
        return {**result, "success": True, "route": "mcp_delete",
                "message": f"实例 {instance_name or instance_id} 已成功删除", "request_id": req_id}
    else:
        return {**result, "success": False, "route": "mcp_delete",
                "message": f"失败: status={status_code}, {error_msg}", "request_id": req_id}


def safe_stop_ecs(account: str, region_id: str, instance_ids: list[str], force: bool = False) -> dict:
    """安全停止 ECS 实例。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID
        instance_ids: 实例ID列表
        force: 是否强制停止

    Returns:
        操作结果
    """
    ctx = {"account": account, "region": region_id, "instances": instance_ids}
    try:
        data = MCPManager.call(account, "OOS_StopInstances",
                               {"RegionId": region_id, "InstanceIds": instance_ids, "ForeceStop": force})
    except ValueError as e:
        audit_log("stop_instances_error", {**ctx, "error": str(e)})
        return {"error": str(e)}
    if not data:
        audit_log("stop_instances_no_response", ctx)
        return {"error": "操作无响应"}
    audit_log("stop_instances", ctx)
    return {"success": True, "message": f"已发送停止指令: {instance_ids}"}


def safe_start_ecs(account: str, region_id: str, instance_ids: list[str]) -> dict:
    """启动 ECS 实例。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID
        instance_ids: 实例ID列表

    Returns:
        操作结果
    """
    ctx = {"account": account, "region": region_id, "instances": instance_ids}
    try:
        data = MCPManager.call(account, "OOS_StartInstances",
                               {"RegionId": region_id, "InstanceIds": instance_ids})
    except ValueError as e:
        audit_log("start_instances_error", {**ctx, "error": str(e)})
        return {"error": str(e)}
    if not data:
        audit_log("start_instances_no_response", ctx)
        return {"error": "操作无响应"}
    audit_log("start_instances", ctx)
    return {"success": True, "message": f"已发送启动指令: {instance_ids}"}


def safe_reboot_ecs(account: str, region_id: str, instance_ids: list[str], force: bool = False) -> dict:
    """重启 ECS 实例。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID
        instance_ids: 实例ID列表
        force: 是否强制重启

    Returns:
        操作结果
    """
    ctx = {"account": account, "region": region_id, "instances": instance_ids}
    try:
        data = MCPManager.call(account, "OOS_RebootInstances",
                               {"RegionId": region_id, "InstanceIds": instance_ids, "ForeceStop": force})
    except ValueError as e:
        audit_log("reboot_instances_error", {**ctx, "error": str(e)})
        return {"error": str(e)}
    if not data:
        audit_log("reboot_instances_no_response", ctx)
        return {"error": "操作无响应"}
    audit_log("reboot_instances", ctx)
    return {"success": True, "message": f"已发送重启指令: {instance_ids}"}
