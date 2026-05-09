"""
阿里云费用/退订工具
直接调用阿里云 OpenAPI（通过 SDK），不走 MCP
支持多账号
"""
import json
import os
from datetime import datetime

# 多账号 AccessKey 配置
# 注意：这里需要阿里云主账号或有 BSS 权限的 RAM 用户的 AK/SK
# 和百炼 MCP 的 API Key 不同
BILLING_ACCOUNTS = {
    "openclaw": {
        "name": "嘉立创openclaw",
        "access_key": os.environ.get("ALIYUN_AK_OPENCLAW", ""),
        "secret_key": os.environ.get("ALIYUN_SK_OPENCLAW", ""),
    },
    "production": {
        "name": "嘉立创生产",
        "access_key": os.environ.get("ALIYUN_AK_PRODUCTION", ""),
        "secret_key": os.environ.get("ALIYUN_SK_PRODUCTION", ""),
    },
}


def _get_bss_client(account: str):
    """获取 BSS OpenAPI 客户端"""
    try:
        from alibabacloud_bssopenapi20171214.client import Client
        from alibabacloud_tea_openapi.models import Config
    except ImportError:
        raise RuntimeError(
            "需要安装阿里云 BSS SDK: pip install alibabacloud_bssopenapi20171214"
        )

    account_lower = account.lower().strip()
    # 别名解析
    alias_map = {"oc": "openclaw", "生产": "production", "prod": "production",
                 "嘉立创openclaw": "openclaw", "嘉立创生产": "production"}
    account_key = alias_map.get(account_lower, account_lower)

    if account_key not in BILLING_ACCOUNTS:
        available = ", ".join(f"{v['name']}({k})" for k, v in BILLING_ACCOUNTS.items())
        raise ValueError(f"未知账号: {account}。可用: {available}")

    cfg = BILLING_ACCOUNTS[account_key]
    if not cfg["access_key"] or not cfg["secret_key"]:
        raise RuntimeError(
            f"账号 {cfg['name']} 的 AccessKey 未配置。"
            f"请在 .env 中设置 ALIYUN_AK_{account_key.upper()} 和 ALIYUN_SK_{account_key.upper()}"
        )

    config = Config(
        access_key_id=cfg["access_key"],
        access_key_secret=cfg["secret_key"],
        endpoint="business.aliyuncs.com",
    )
    return Client(config), cfg["name"]


def _audit_log(action: str, detail: dict):
    log_dir = os.path.join(os.path.dirname(__file__), "..", "audit_logs")
    os.makedirs(log_dir, exist_ok=True)
    entry = {"time": datetime.now().isoformat(), "action": action, **detail}
    filepath = os.path.join(log_dir, f"audit_{datetime.now():%Y%m%d}.jsonl")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ============================================================
# ADK 工具函数
# ============================================================

def refund_instance(account: str, instance_id: str, product_code: str = "ecs",
                    product_type: str = "") -> dict:
    """退订阿里云包年包月实例（ECS、RDS 等）。

    这是一个危险的财务操作，会产生退款。调用前请确保已向用户确认。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)
        instance_id: 要退订的实例ID，如 i-wz9xxxxx
        product_code: 产品代码，默认 ecs。其他值：rds, redis, slb, eip 等
        product_type: 产品类型，大部分情况留空即可

    Returns:
        退订结果
    """
    try:
        from alibabacloud_bssopenapi20171214.models import RefundInstanceRequest
    except ImportError:
        return {"error": "需要安装 SDK: pip install alibabacloud_bssopenapi20171214"}

    try:
        client, account_name = _get_bss_client(account)
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}

    request = RefundInstanceRequest(
        instance_id=instance_id,
        product_code=product_code,
        product_type=product_type if product_type else None,
        immediately_release="0",  # 1：标识立即释放。0：标识先停机
    )

    try:
        response = client.refund_instance(request)
        body = response.body
        result = {
            "account": account_name,
            "instance_id": instance_id,
            "product_code": product_code,
            "success": body.success if body else False,
            "code": body.code if body else "unknown",
            "message": body.message if body else "no response",
            "request_id": body.request_id if body else "",
            "order_id": str(body.data.order_id) if body and body.data else "",
        }
        _audit_log("refund_instance", result)

        if body and body.success:
            return {**result, "message": f"✅ 实例 {instance_id} 退订成功，退款订单号: {result['order_id']}"}
        else:
            return {**result, "message": f"❌ 退订失败: {result['message']}"}

    except Exception as e:
        error_result = {"account": account_name, "instance_id": instance_id, "error": str(e)}
        _audit_log("refund_error", error_result)
        return error_result


def query_available_instances(account: str, region: str = "",
                              product_code: str = "ecs") -> dict:
    """查询可退订的包年包月实例列表。

    Args:
        account: 阿里云账号名称
        region: 地域ID（可选，留空查所有地域）
        product_code: 产品代码，默认 ecs

    Returns:
        可退订实例列表
    """
    try:
        from alibabacloud_bssopenapi20171214.models import QueryAvailableInstancesRequest
    except ImportError:
        return {"error": "需要安装 SDK: pip install alibabacloud_bssopenapi20171214"}

    try:
        client, account_name = _get_bss_client(account)
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}

    request = QueryAvailableInstancesRequest(
        product_code=product_code,
        region=region if region else None,
        subscription_type="Subscription",
        page_num=1,
        page_size=100,
    )

    try:
        response = client.query_available_instances(request)
        body = response.body
        if not body or not body.success:
            return {"error": body.message if body else "no response", "account": account_name}

        instances = []
        if body.data and body.data.instance_list:
            for inst in body.data.instance_list:
                instances.append({
                    "instance_id": inst.instance_id,
                    "region": inst.region,
                    "status": inst.status,
                    "product_code": inst.product_code,
                    "product_type": inst.product_type,
                    "subscription_type": inst.subscription_type,
                    "end_time": inst.end_time,
                    "create_time": inst.create_time,
                    "renew_status": inst.renew_status,
                })

        return {"account": account_name, "total": len(instances), "instances": instances}

    except Exception as e:
        return {"error": str(e), "account": account_name}


def query_account_balance(account: str) -> dict:
    """查询阿里云账号余额。

    Args:
        account: 阿里云账号名称，可选值：openclaw(嘉立创openclaw), production(嘉立创生产)

    Returns:
        账号余额信息
    """
    try:
        from alibabacloud_bssopenapi20171214.models import QueryAccountBalanceRequest
    except ImportError:
        return {"error": "需要安装 SDK: pip install alibabacloud_bssopenapi20171214"}

    try:
        client, account_name = _get_bss_client(account)
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}

    try:
        response = client.query_account_balance(QueryAccountBalanceRequest())
        body = response.body
        if not body or not body.success:
            return {"error": body.message if body else "no response", "account": account_name}

        data = body.data
        return {
            "account": account_name,
            "available_amount": data.available_amount if data else "unknown",
            "available_cash_amount": data.available_cash_amount if data else "unknown",
            "credit_amount": data.credit_amount if data else "unknown",
            "currency": data.currency if data else "CNY",
        }

    except Exception as e:
        return {"error": str(e), "account": account_name}
