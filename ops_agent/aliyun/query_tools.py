"""
阿里云查询工具 - 通过 MCP 调用
"""
from ..mcp_manager import MCPManager


def _fmt_instances(data):
    instances = data.get("body", {}).get("Instances", {}).get("Instance", [])
    result = []
    for i in instances:
        priv = i.get("VpcAttributes", {}).get("PrivateIpAddress", {}).get("IpAddress", [])
        pub = i.get("PublicIpAddress", {}).get("IpAddress", [])
        eip = i.get("EipAddress", {}).get("IpAddress", "")
        result.append({
            "name": i.get("InstanceName", ""), "id": i.get("InstanceId", ""),
            "status": i.get("Status", ""), "type": i.get("InstanceType", ""),
            "cpu": i.get("Cpu", 0), "memory_gb": round(i.get("Memory", 0) / 1024),
            "os": i.get("OSName", ""), "zone": i.get("ZoneId", ""),
            "private_ip": ", ".join(priv), "public_ip": ", ".join(pub) if pub else eip,
            "charge": i.get("InstanceChargeType", ""), "created": i.get("CreationTime", ""),
        })
    return result


def list_accounts() -> dict:
    """列出所有可用的阿里云账号。

    Returns:
        账号列表，包含名称和别名
    """
    return {"accounts": MCPManager.list_accounts()}


def query_ecs_instances(account: str, region_id: str, max_total: int = 500) -> dict:
    """查询指定账号和地域的 ECS 实例列表（自动翻页）。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID，如 cn-shenzhen, cn-hangzhou, cn-beijing
        max_total: 最大返回实例数，默认500，避免一次返回过多数据

    Returns:
        实例列表
    """
    try:
        all_instances = []
        next_token = None
        while len(all_instances) < max_total:
            args = {"RegionId": region_id, "MaxResults": 100}
            if next_token:
                args["NextToken"] = next_token
            data = MCPManager.call(account, "ECS_DescribeInstances", args, timeout=35)
            if not data:
                break
            instances = _fmt_instances(data)
            all_instances.extend(instances)
            next_token = data.get("body", {}).get("NextToken")
            if not next_token or not instances:
                break
        if not all_instances:
            return {"error": "查询无响应或无实例", "account": account, "region": region_id}
        return {"account": account, "region": region_id, "total": len(all_instances), "instances": all_instances}
    except ValueError as e:
        return {"error": str(e)}


COMMON_REGIONS = ["cn-shenzhen", "cn-hangzhou", "cn-beijing", "cn-shanghai",
                  "cn-guangzhou", "cn-hongkong", "ap-southeast-1", "eu-central-1"]


def _enrich_instance(data):
    instances = _fmt_instances(data)
    if not instances:
        return None
    inst = instances[0]
    raw = data.get("body", {}).get("Instances", {}).get("Instance", [{}])[0]
    inst["expired"] = raw.get("ExpiredTime", "")
    inst["deletion_protection"] = raw.get("DeletionProtection", False)
    inst["tags"] = {t["TagKey"]: t["TagValue"] for t in raw.get("Tags", {}).get("Tag", [])}
    inst["security_groups"] = raw.get("SecurityGroupIds", {}).get("SecurityGroupId", [])
    return inst


def query_ecs_by_id(instance_id: str, account: str = "", region_id: str = "") -> dict:
    """根据实例ID查询 ECS 实例详情。支持只传 instance_id，自动跨账号跨地域搜索。

    Args:
        instance_id: ECS实例ID，如 i-wz96fsimhadx7bv6qovk
        account: 阿里云账号名称（可选，不传则搜索所有账号）
        region_id: 地域ID（可选，不传则搜索常用地域）

    Returns:
        实例详情
    """
    accounts = [account] if account else [a["key"] for a in MCPManager.list_accounts()]
    regions = [region_id] if region_id else COMMON_REGIONS

    for acct in accounts:
        for reg in regions:
            try:
                data = MCPManager.call(acct, "ECS_DescribeInstances",
                                       {"RegionId": reg, "InstanceIds": [instance_id]}, timeout=35)
            except ValueError:
                continue
            if not data:
                continue
            inst = _enrich_instance(data)
            if inst:
                return {"account": acct, "region": reg, **inst}

    return {"error": f"所有账号和地域均未找到实例 {instance_id}"}


def query_ecs_by_ip(account: str, region_id: str, ip: str) -> dict:
    """根据内网IP查询 ECS 实例。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID
        ip: 实例内网IP

    Returns:
        实例详情
    """
    try:
        data = MCPManager.call(account, "ECS_DescribeInstances", {"RegionId": region_id, "PrivateIpAddresses": [ip]})
    except ValueError as e:
        return {"error": str(e)}
    if not data:
        return {"error": "查询无响应"}
    instances = _fmt_instances(data)
    if not instances:
        return {"error": f"未找到 IP={ip} 的实例", "account": account, "region": region_id}
    return {"account": account, **instances[0]}


def query_vpcs(account: str, region_id: str) -> dict:
    """查询指定账号和地域的 VPC 列表。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID

    Returns:
        VPC 列表
    """
    try:
        data = MCPManager.call(account, "VPC_DescribeVpcs", {"RegionId": region_id})
    except ValueError as e:
        return {"error": str(e)}
    if not data:
        return {"error": "查询无响应"}
    vpcs = data.get("body", {}).get("Vpcs", {}).get("Vpc", [])
    return {"account": account, "region": region_id, "total": len(vpcs), "vpcs": [
        {"name": v.get("VpcName", ""), "id": v.get("VpcId", ""),
         "cidr": v.get("CidrBlock", ""), "status": v.get("Status", "")}
        for v in vpcs
    ]}


def query_security_groups(account: str, region_id: str) -> dict:
    """查询指定账号和地域的安全组列表。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID

    Returns:
        安全组列表
    """
    try:
        data = MCPManager.call(account, "ECS_DescribeSecurityGroups", {"RegionId": region_id})
    except ValueError as e:
        return {"error": str(e)}
    if not data:
        return {"error": "查询无响应"}
    sgs = data.get("body", {}).get("SecurityGroups", {}).get("SecurityGroup", [])
    return {"account": account, "region": region_id, "total": len(sgs), "security_groups": [
        {"name": sg.get("SecurityGroupName", ""), "id": sg.get("SecurityGroupId", ""),
         "vpc_id": sg.get("VpcId", "")}
        for sg in sgs
    ]}


def query_rds_instances(account: str, region_id: str) -> dict:
    """查询指定账号和地域的 RDS 数据库实例。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID

    Returns:
        RDS 实例列表
    """
    try:
        data = MCPManager.call(account, "RDS_DescribeDBInstances", {"RegionId": region_id})
    except ValueError as e:
        return {"error": str(e)}
    if not data:
        return {"error": "查询无响应"}
    items = data.get("body", {}).get("Items", {}).get("DBInstance", [])
    return {"account": account, "region": region_id, "total": len(items), "instances": [
        {"id": d.get("DBInstanceId", ""), "description": d.get("DBInstanceDescription", ""),
         "engine": d.get("Engine", ""), "version": d.get("EngineVersion", ""),
         "status": d.get("DBInstanceStatus", "")}
        for d in items
    ]}


def get_cpu_usage(account: str, region_id: str, instance_ids: list[str]) -> dict:
    """查询 ECS 实例的 CPU 使用率。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID
        instance_ids: 实例ID列表

    Returns:
        CPU 使用率数据
    """
    try:
        return MCPManager.call(account, "CMS_GetCpuUsageData", {"RegionId": region_id, "InstanceIds": instance_ids})
    except ValueError as e:
        return {"error": str(e)}


def get_memory_usage(account: str, region_id: str, instance_ids: list[str]) -> dict:
    """查询 ECS 实例的内存使用率。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        region_id: 地域ID
        instance_ids: 实例ID列表

    Returns:
        内存使用率数据
    """
    try:
        return MCPManager.call(account, "CMS_GetMemUsageData", {"RegionId": region_id, "InstanceIds": instance_ids})
    except ValueError as e:
        return {"error": str(e)}
