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


def _billing_call(svc, api: str, body: dict) -> dict:
    """调用 billing SDK API（JSON body）"""
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


_VOLC_PRODUCT_CODES = ["ECS", "ecs", "volc_ecs", "cloud_server"]


def volc_refund_instance(account: str, instance_id: str = "", instance_ids: list[str] = [],
                         product_code: str = "") -> dict:
    """退订火山云包年包月实例。支持 ECS 及关联资源（云盘等）。

    调用费用中心 UnsubscribeInstance 接口。不传 product_code 时自动尝试常见产品代码。
    注意：实例需要先停机，否则返回 StatusWrong。

    Args:
        account: 火山云账号名称，如 volc_production
        instance_id: 单个实例ID（和 instance_ids 二选一）
        instance_ids: 多个实例ID列表（包含 ECS 及关联云盘等）
        product_code: 产品代码（可选，不传自动尝试）

    Returns:
        退订结果
    """
    ids = instance_ids if instance_ids else ([instance_id] if instance_id else [])
    if not ids:
        return {"success": False, "error": "请提供 instance_id 或 instance_ids"}

    ctx = {"account": account, "instance_ids": ids}
    codes_to_try = [product_code] if product_code else _VOLC_PRODUCT_CODES
    results = []
    all_ok = True

    svc = _get_billing_service(account)

    for iid in ids:
        refunded = False
        for code in codes_to_try:
            try:
                resp = _billing_call(svc, "UnsubscribeInstance", {
                    "Product": code,
                    "InstanceID": iid,
                })

                err_msg = _parse_api_error(resp)
                if err_msg:
                    if "product code" in err_msg.lower() and code != codes_to_try[-1]:
                        continue
                    audit_log("volc_refund_api_error", {"account": account, "instance_id": iid,
                              "product_code": code, "error": err_msg})
                    results.append({"instance_id": iid, "success": False, "error": err_msg, "product_code": code})
                    all_ok = False
                    refunded = True
                    break

                audit_log("volc_refund", {"account": account, "instance_id": iid,
                          "product_code": code, "response": resp})
                results.append({"instance_id": iid, "success": True, "product_code": code})
                refunded = True
                break
            except Exception as e:
                err_str = e.args[0].decode("utf-8") if isinstance(e.args[0], bytes) else str(e)
                if "product code" in err_str.lower() and code != codes_to_try[-1]:
                    continue
                if "instancegroup" in err_str.lower() or "place orders together" in err_str.lower():
                    audit_log("volc_refund_instancegroup", {"account": account, "instance_id": iid, "error": err_str})
                    results.append({"instance_id": iid, "success": False, "product_code": code,
                                    "error": f"实例 {iid} 属于计费实例组，无法单独退订。请在火山云控制台（费用中心→退订管理）操作整组退订"})
                    all_ok = False
                    refunded = True
                    break
                audit_log("volc_refund_error", {"account": account, "instance_id": iid,
                          "product_code": code, "error": err_str})
                results.append({"instance_id": iid, "success": False, "error": err_str, "product_code": code})
                all_ok = False
                refunded = True
                break

        if not refunded:
            results.append({"instance_id": iid, "success": False, "error": "所有产品代码均不匹配"})
            all_ok = False

    return {"success": all_ok, "account": account, "results": results,
            "message": f"退订完成: {sum(1 for r in results if r['success'])}/{len(results)} 成功"}


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
        resp = _billing_call(svc, "ListBillDetail", body)
        return {"account": account, "data": resp}
    except Exception as e:
        err_str = e.args[0].decode("utf-8") if isinstance(e.args[0], bytes) else str(e)
        audit_log("volc_query_bill_error", {"account": account, "error": err_str})
        return {"error": err_str, "account": account}
