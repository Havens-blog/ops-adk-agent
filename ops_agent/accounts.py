"""
统一账号/凭证管理
所有云厂商的账号配置集中在此，避免分散在多个工具文件
"""
import os

# MCP 账号（百炼 MCP 连接用）
MCP_ACCOUNTS = {
    "openclaw": {
        "name": "嘉立创openclaw",
        "aliases": ["openclaw", "嘉立创openclaw", "oc"],
        "provider": "aliyun",
        "mcp_url": os.environ.get("ALIYUN_MCP_URL", "https://dashscope.aliyuncs.com/api/v1/mcps/alibaba-cloud-ops"),
        "api_key": os.environ.get("DASHSCOPE_API_KEY_OPENCLAW", ""),
    },
    "production": {
        "name": "嘉立创生产",
        "aliases": ["production", "生产", "嘉立创生产", "prod"],
        "provider": "aliyun",
        "mcp_url": os.environ.get("ALIYUN_MCP_URL", "https://dashscope.aliyuncs.com/api/v1/mcps/alibaba-cloud-ops"),
        "api_key": os.environ.get("DASHSCOPE_API_KEY_PRODUCTION", ""),
    },
}

# 火山云不走 MCP，仅 SDK 直调（见下方 SDK_CREDENTIALS）

# SDK 凭证（直接调用云 API 用，不走 MCP）
SDK_CREDENTIALS = {
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
    "volc_production": {
        "name": "火山云生产",
        "access_key": os.environ.get("VOLC_AK_PRODUCTION", ""),
        "secret_key": os.environ.get("VOLC_SK_PRODUCTION", ""),
    },
}
