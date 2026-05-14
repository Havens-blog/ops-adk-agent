"""
火山云查询工具
直接调用火山云 ECS OpenAPI（通过 SDK），不走百炼 MCP
"""
import json

from volcengine.ApiInfo import ApiInfo
from volcengine.Credentials import Credentials
from volcengine.base.Service import Service
from volcengine.ServiceInfo import ServiceInfo

from ..accounts import SDK_CREDENTIALS

_ECS_APIS = {
    "DescribeInstances": ApiInfo("GET", "/", {"Action": "DescribeInstances", "Version": "2020-04-01"}, {}, {}),
    "DescribeRegions": ApiInfo("GET", "/", {"Action": "DescribeRegions", "Version": "2020-04-01"}, {}, {}),
    "StopInstances": ApiInfo("GET", "/", {"Action": "StopInstances", "Version": "2020-04-01"}, {}, {}),
    "StartInstances": ApiInfo("GET", "/", {"Action": "StartInstances", "Version": "2020-04-01"}, {}, {}),
    "RebootInstances": ApiInfo("GET", "/", {"Action": "RebootInstances", "Version": "2020-04-01"}, {}, {}),
    "DeleteInstance": ApiInfo("GET", "/", {"Action": "DeleteInstance", "Version": "2020-04-01"}, {}, {}),
    "DescribeVolumes": ApiInfo("GET", "/", {"Action": "DescribeVolumes", "Version": "2020-04-01"}, {}, {}),
    "CreateSnapshot": ApiInfo("GET", "/", {"Action": "CreateSnapshot", "Version": "2020-04-01"}, {}, {}),
}


def _get_ecs_service(account: str, region_id: str = "cn-beijing") -> Service:
    cfg = SDK_CREDENTIALS.get(account)
    if not cfg or not cfg["access_key"]:
        raise ValueError(f"火山云账号 {account} 未配置 AK/SK，请设置 VOLC_AK_PRODUCTION 和 VOLC_SK_PRODUCTION")
    svc_info = ServiceInfo(
        "open.volcengineapi.com", {"Accept": "application/json"},
        Credentials(cfg["access_key"], cfg["secret_key"], "ecs", region_id), 10, 10,
    )
    svc = Service(svc_info, _ECS_APIS)
    return svc


def _call(svc, api: str, params: dict) -> dict:
    """调用 SDK API 并解析 JSON 字符串响应"""
    resp = svc.get(api, params)
    if isinstance(resp, dict):
        return resp
    if isinstance(resp, str):
        return json.loads(resp)
    return {}


def _fmt_volc_instances(result: dict) -> list[dict]:
    instances = result.get("Instances", [])
    out = []
    for i in instances:
        nics = i.get("NetworkInterfaces", [])
        private_ip = nics[0].get("PrimaryIpAddress", "") if nics else ""
        eip = i.get("EipAddress")
        public_ip = eip.get("IpAddress", "") if isinstance(eip, dict) else ""
        out.append({
            "name": i.get("InstanceName", ""),
            "id": i.get("InstanceId", ""),
            "status": i.get("Status", ""),
            "type": i.get("InstanceTypeId", ""),
            "cpu": i.get("Cpus", ""),
            "memory_mb": i.get("MemorySize", ""),
            "os": i.get("OsName", ""),
            "zone": i.get("ZoneId", ""),
            "private_ip": private_ip,
            "public_ip": public_ip,
            "charge": i.get("InstanceChargeType", ""),
            "created": i.get("CreatedAt", ""),
            "expired": i.get("ExpiredAt", ""),
            "tags": {t["Key"]: t["Value"] for t in i.get("Tags", [])},
            "deletion_protection": i.get("DeletionProtection", False),
        })
    return out


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
        svc = _get_ecs_service(account, region_id)
        all_instances = []
        page = 1
        page_size = 100
        while len(all_instances) < max_total:
            resp = _call(svc, "DescribeInstances", {
                "Region": region_id, "PageSize": page_size, "PageNumber": page,
            })
            result = resp.get("Result", {})
            instances = _fmt_volc_instances(result)
            all_instances.extend(instances)
            if not instances or len(instances) < page_size:
                break
            page += 1
        if not all_instances:
            return {"error": "查询无响应或无实例", "account": account, "region": region_id}
        return {"account": account, "region": region_id, "total": len(all_instances), "instances": all_instances}
    except Exception as e:
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
        svc = _get_ecs_service(account, region_id)
        resp = _call(svc, "DescribeInstances", {
            "Region": region_id, "InstanceIds.1": instance_id,
        })
        result = resp.get("Result", {})
        instances = _fmt_volc_instances(result)
        if not instances:
            return {"error": f"未找到实例 {instance_id}", "account": account, "region": region_id}
        return {"account": account, "region": region_id, **instances[0]}
    except Exception as e:
        return {"error": str(e)}


VOLC_REGIONS = ["cn-beijing", "cn-beijing2", "cn-shanghai", "cn-guangzhou",
                "cn-hongkong", "ap-southeast-1", "ap-southeast-3"]


def volc_query_ecs_by_ip(account: str, ip: str, region_id: str = "") -> dict:
    """根据 IP 查询火山云 ECS 实例。支持内网 IP 和公网 IP。

    不指定 region_id 时自动搜索所有常用地域。

    Args:
        account: 火山云账号名称
        ip: IP 地址（内网或公网）
        region_id: 地域ID（可选，不传则搜索所有地域）

    Returns:
        实例详情
    """
    regions = [region_id] if region_id else VOLC_REGIONS
    for reg in regions:
        try:
            svc = _get_ecs_service(account, reg)
            page = 1
            while True:
                resp = _call(svc, "DescribeInstances", {
                    "Region": reg, "PageSize": 100, "PageNumber": page,
                })
                result = resp.get("Result", {})
                instances = _fmt_volc_instances(result)
                for inst in instances:
                    if inst.get("private_ip") == ip or inst.get("public_ip") == ip:
                        return {"account": account, "region": reg, **inst}
                if not instances or len(instances) < 100:
                    break
                page += 1
        except Exception:
            continue

    return {"error": f"所有地域均未找到 IP={ip} 的实例", "account": account}


def volc_describe_regions(account: str) -> dict:
    """查询火山云 ECS 支持的地域列表。

    Args:
        account: 火山云账号名称

    Returns:
        地域列表
    """
    try:
        svc = _get_ecs_service(account)
        resp = _call(svc, "DescribeRegions", {})
        return {"account": account, "data": resp}
    except Exception as e:
        return {"error": str(e)}
