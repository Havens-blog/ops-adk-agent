"""
火山云费用/退订工具
直接调用火山云 Billing OpenAPI（通过 SDK）
火山云包年包月退订走 UnsubscribeInstance，和阿里云 BSS 的 RefundInstance 不同
"""
import json
import os
from datetime import datetime

from volcengine.ApiInfo import ApiInfo
from volcengine.Credentials import Credentials
from volcengine.base.Service import Service
from volcengine.ServiceInfo import ServiceInfo

from .volc_query_tools import VOLC_ACCOUNTS

_BILLING_APIS = {
    "UnsubscribeInstance": ApiInfo("POST", "/", {"Action": "UnsubscribeInstance", "Version": "2022-01-01"}, {}, {}),
    "ListBillDetail": ApiInfo("POST", "/", {"Action": "ListBillDetail", "Version": "2022-01-01"}, {}, {}),
}


def _get_billing_service(account: str) -> Service:
    cfg = VOLC_ACCOUNTS.get(account)
    if not cfg or not cfg["access_key"]:
        raise ValueError(f"火山云账号 {account} 未配置 AK/SK")
    svc_info = ServiceInfo(
        "billing.volcengineapi.com", {"Accept": "application/json"},
        Credentials(cfg["access_key"], cfg["secret_key"], "billing", "cn-north-1"), 10, 10,
    )
    svc = Service(svc_info, _BILLING_APIS)
    return svc


def _audit_log(action: str, detail: dict):
    log_dir = os.path.join(os.path.dirname(__file__), "..", "audit_logs")
    os.makedirs(log_dir, exist_ok=True)
    entry = {"time": datetime.now().isoformat(), "action": action, **detail}
    filepath = os.path.join(log_dir, f"audit_{datetime.now():%Y%m%d}.jsonl")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def volc_refund_instance(account: str, instance_id: str) -> dict:
    """退订火山云包年包月 ECS 实例。

    调用费用中心 UnsubscribeInstance 接口。仅支持符合退订规则的包年包月实例。

    Args:
        account: 火山云账号名称，如 volc_production
        instance_id: 实例ID

    Returns:
        退订结果
    """
    ctx = {"account": account, "instance_id": instance_id}
    try:
        svc = _get_billing_service(account)
        body = json.dumps({"InstanceIDs": [instance_id]})
        resp = svc.post("UnsubscribeInstance", {}, body)
        _audit_log("volc_refund", {**ctx, "response": str(resp)})
        return {"success": True, "instance_id": instance_id, "account": account, "message": f"退订请求已发送: {instance_id}", "response": resp}
    except Exception as e:
        _audit_log("volc_refund_error", {**ctx, "error": str(e)})
        return {"success": False, "error": str(e), **ctx}


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
        body_dict = {"Limit": page_size, "Offset": (page_num - 1) * page_size}
        if start_period:
            body_dict["BillPeriod"] = start_period
        if end_period:
            body_dict["BillPeriodEnd"] = end_period
        body = json.dumps(body_dict)
        resp = svc.post("ListBillDetail", {}, body)
        return {"account": account, "data": resp}
    except Exception as e:
        return {"error": str(e), "account": account}
