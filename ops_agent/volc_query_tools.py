"""
火山云查询工具
调用火山云 ECS MCP（describe_instances 等工具）
工具名和参数格式与阿里云完全不同
"""
from .mcp_manager import MCPManager


def _fmt_volc_instances(data):
    """格式化火山云 describe_instances 响应"""
    content = data.get("content", {})
    instances = content.get("instances", []) if isinstance(content, dict) else []
    if not instances:
        # 尝试直接从 data 取（不同 MCP 可能返回格式不同）
        instances = data.get("instances", [])
    result = []
    for i in instances:
        result.append({
            "name": i.get("instanceName", ""),
            "id": i.get("instanceId", ""),
            "status": i.get("status", ""),
            "type": i.get("instanceTypeId", ""),
            "cpu": i.get("cpu", ""),
            "memory_gb": i.get("memory", ""),
            "os": i.get("imageId", ""),
            "zone": i.get("zoneId", ""),
            "private_ip": ", ".join(i.get("networkInterfaces", [{}])[0].get("primaryIp", {}).get("ip", []) if i.get("networkInterfaces") else []),
            "public_ip": ", ".join(i.get("eipAddress", {}).get("ip", []) if isinstance(i.get("eipAddress"), dict) else []),
            "charge": i.get("instanceChargeType", ""),
            "created": i.get("createdAt", ""),
            "expired": i.get("expiredAt", ""),
        })
    return result


def _extract_page_info(data):
    """从火山云响应中提取分页信息"""
    content = data.get("content", {}) if isinstance(data.get("content"), dict) else {}
    total_count = content.get("totalCount", 0)
    page_num = content.get("pageNumber", 1)
    page_size = content.get("pageSize", 20)
    return total_count, page_num, page_size


def volc_query_ecs(account: str, region_id: str = "cn-beijing", max_total: int = 500) -> dict:
    """查询火山云 ECS 实例列表（自动分页）。

    Args:
        account: 火山云账号名称，如 volc_production(火山云生产)
        region_id: 地域ID，如 cn-beijing, cn-guangzhou, ap-southeast-1
        max_total: 最大返回实例数，默认500

    Returns:
        实例列表
    """
    try:
        all_instances = []
        page_num = 1
        page_size = 100
        while len(all_instances) < max_total:
            data = MCPManager.call(account, "describe_instances",
                                   {"region": region_id, "needNum": page_size},
                                   timeout=40)
            if not data:
                break
            instances = _fmt_volc_instances(data)
            all_instances.extend(instances)
            # 检查是否还有更多数据
            total_count, _, _ = _extract_page_info(data)
            if total_count <= len(all_instances) or not instances:
                break
            page_num += 1
        if not all_instances:
            return {"error": "查询无响应或无实例", "account": account, "region": region_id}
        return {"account": account, "region": region_id, "total": len(all_instances), "instances": all_instances}
    except ValueError as e:
        return {"error": str(e)}


def volc_query_ecs_by_id(account: str, instance_id: str, region_id: str = "cn-beijing") -> dict:
    """根据实例ID查询火山云 ECS 实例详情。

    Args:
        account: 火山云账号名称
        instance_id: 实例ID
        region_id: 地域ID

    Returns:
        实例详情
    """
    try:
        data = MCPManager.call(account, "describe_instances",
                               {"region": region_id, "instanceIds": [instance_id]}, timeout=40)
    except ValueError as e:
        return {"error": str(e)}
    if not data:
        return {"error": "查询无响应", "account": account, "region": region_id}
    instances = _fmt_volc_instances(data)
    if not instances:
        return {"error": f"未找到实例 {instance_id}", "account": account, "region": region_id}
    return {"account": account, "region": region_id, **instances[0]}


def volc_describe_regions(account: str) -> dict:
    """查询火山云 ECS 支持的地域列表。

    Args:
        account: 火山云账号名称

    Returns:
        地域列表
    """
    try:
        data = MCPManager.call(account, "describe_regions",
                               {"region": "cn-beijing"}, timeout=40)
    except ValueError as e:
        return {"error": str(e)}
    if not data:
        return {"error": "查询无响应"}
    return {"account": account, "data": data}
