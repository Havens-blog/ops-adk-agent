"""
火山云费用/退订工具
直接调用火山云 Billing OpenAPI（通过 SDK）
"""
import json

from volcengine.ApiInfo import ApiInfo
from volcengine.Credentials import Credentials
from volcengine.base.Service import Service
from volcengine.ServiceInfo import ServiceInfo

from ..audit import audit_log
from ..accounts import SDK_CREDENTIALS

_BILLING_APIS = {
    "UnsubscribeInstance": ApiInfo("POST", "/", {"Action": "UnsubscribeInstance", "Version": "2022-01-01"}, {}, {}),
    "ListBillDetail": ApiInfo("POST", "/", {"Action": "ListBillDetail", "Version": "2022-01-01"}, {}, {}),
}


def _get_billing_service(account: str) -> Service:
    cfg = SDK_CREDENTIALS.get(account)
    if not cfg or not cfg["access_key"]:
        raise ValueError(f"火山云账号 {account} 未配置 AK/SK")
    svc_info = ServiceInfo(
        "billing.volcengineapi.com", {"Accept": "application/json"},
        Credentials(cfg["access_key"], cfg["secret_key"], "billing", "cn-north-1"), 10, 10,
    )
    svc = Service(svc_info, _BILLING_APIS)
    return svc


def _json_call(svc, api: str, body: dict) -> dict:
    """用 json() 方法调用 SDK API（Content-Type: application/json）"""
    resp = svc.json(api, {}, json.dumps(body))
    if isinstance(resp, dict):
        return resp
    if isinstance(resp, bytes):
        return json.loads(resp.decode("utf-8"))
    if isinstance(resp, str):
        return json.loads(resp)
    return {}


def _parse_api_error(resp: dict) -> str | None:
    """从火山云 API 响应中提取错误信息"""
    metadata = resp.get("ResponseMetadata", {})
    error = metadata.get("Error", {})
    if error:
        return error.get("Message", str(error))
    return None


def volc_refund_instance(account: str, instance_id: str, product_code: str = "ecs") -> dict:
    """退订火山云包年包月 ECS 实例。

    调用费用中心 UnsubscribeInstance 接口。仅支持符合退订规则的包年包月实例。

    Args:
        account: 火山云账号名称，如 volc_production
        instance_id: 实例ID
        product_code: 产品代码，默认 ecs

    Returns:
        退订结果
    """
    ctx = {"account": account, "instance_id": instance_id}
    try:
        svc = _get_billing_service(account)
        resp = _json_call(svc, "UnsubscribeInstance", {
            "InstanceIDs": [instance_id],
            "ProductCode": product_code,
        })
        audit_log("volc_refund", {**ctx, "response": resp})

        err_msg = _parse_api_error(resp)
        if err_msg:
            audit_log("volc_refund_api_error", {**ctx, "error": err_msg})
            return {"success": False, "error": f"退订失败: {err_msg}", **ctx}

        return {"success": True, "instance_id": instance_id, "account": account,
                "message": f"退订请求已发送: {instance_id}", "response": resp}
    except Exception as e:
        err_str = e.args[0].decode("utf-8") if isinstance(e.args[0], bytes) else str(e)
        audit_log("volc_refund_error", {**ctx, "error": err_str})
        return {"success": False, "error": err_str, **ctx}


def volc_query_bill(account: str, start_period: str = "", end_period: str = "",
                    page_num: int = 1, page_size: int = 20) -> dict:
    """查询火山云账单明细。

    Args:
        account: 火山云账号名称
        start_period: 账单开始月份，如 2025-01
        end_period: 账单结束月份，如 2025-06
        page_num: 页码
        page_size: 每页条数

    Returns:
        账单明细
    """
    try:
        svc = _get_billing_service(account)
        body = {"Limit": page_size, "Offset": (page_num - 1) * page_size}
        if start_period:
            body["BillPeriod"] = start_period
        if end_period:
            body["BillPeriodEnd"] = end_period
        resp = _json_call(svc, "ListBillDetail", body)
        return {"account": account, "data": resp}
    except Exception as e:
        err_str = e.args[0].decode("utf-8") if isinstance(e.args[0], bytes) else str(e)
        audit_log("volc_query_bill_error", {"account": account, "error": err_str})
        return {"error": err_str, "account": account}
