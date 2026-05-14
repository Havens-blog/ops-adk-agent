"""
阿里云费用/退订工具
直接调用阿里云 BSS OpenAPI（通过 SDK）
"""
from datetime import datetime

from ..audit import audit_log
from ..accounts import SDK_CREDENTIALS


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
    alias_map = {"oc": "openclaw", "生产": "production", "prod": "production",
                 "嘉立创openclaw": "openclaw", "嘉立创生产": "production"}
    account_key = alias_map.get(account_lower, account_lower)

    if account_key not in SDK_CREDENTIALS:
        available = ", ".join(f"{v['name']}({k})" for k, v in SDK_CREDENTIALS.items())
        raise ValueError(f"未知账号: {account}。可用: {available}")

    cfg = SDK_CREDENTIALS[account_key]
    if not cfg["access_key"] or not cfg["secret_key"]:
        raise RuntimeError(
            f"账号 {cfg['name']} 的 AccessKey 未配置。"
            f"请在 .env 中设置对应的环境变量"
        )

    config = Config(
        access_key_id=cfg["access_key"],
        access_key_secret=cfg["secret_key"],
        endpoint="business.aliyuncs.com",
    )
    return Client(config), cfg["name"]


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
        immediately_release="0",
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
        audit_log("refund_instance", result)

        if body and body.success:
            return {**result, "message": f"✅ 实例 {instance_id} 退订成功，退款订单号: {result['order_id']}"}
        else:
            return {**result, "message": f"❌ 退订失败: {result['message']}"}

    except Exception as e:
        error_result = {"account": account_name, "instance_id": instance_id, "error": str(e)}
        audit_log("refund_error", error_result)
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
