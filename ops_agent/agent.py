"""
OPS Agent - 多云运维 Agent（混合模式）

查询类操作 → 手动封装（精简返回数据，节省 Token）
危险操作     → 手动封装（保护规则 + 审计日志 + 风险评估）
"""
import os
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from . import query_tools
from . import safe_tools
from . import billing_tools
from . import recycle_tools
from . import volc_query_tools

# 加载环境变量
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ============================================================
# LLM 配置（通过 API 网关）
# ============================================================
model = LiteLlm(
    model=f"openai/{os.environ.get('OPENAI_MODEL', 'qwen3.5-plus')}",
    api_key=os.environ.get("OPENAI_API_KEY", ""),
    api_base=os.environ.get("OPENAI_BASE_URL", ""),
    extra_body={"drop_params": True},
)

# ============================================================
# Agent 定义
# ============================================================
root_agent = Agent(
    name="ops_agent",
    model=model,
    description="多云运维 Agent，支持阿里云和火山云资源查询和安全操作。",
    instruction="""你是一个专业的多云运维助手，负责管理阿里云和火山云的基础设施资源。

## 可用账号
- **openclaw** (嘉立创openclaw) — 别名: openclaw, oc
- **production** (嘉立创生产) — 别名: production, 生产, prod
- **volc_production** (火山云生产) — 别名: volc, 火山云

如果用户没有指定账号，请先询问要操作哪个账号。
可以用 list_accounts 工具查看所有可用账号。

## 可用工具

### 查询类（可直接使用）
- list_accounts: 列出所有可用账号
- query_ecs_instances(account, region_id, max_total=500): 查询 ECS 实例（自动翻页）
- query_ecs_by_id(instance_id, account?, region_id?): 根据实例ID查询详情，account/region_id 可选，不传则自动搜索
- query_ecs_by_ip(account, region_id, ip): 根据 IP 查询实例
- query_vpcs(account, region_id): 查询 VPC
- query_security_groups(account, region_id): 查询安全组
- query_rds_instances(account, region_id): 查询 RDS
- get_cpu_usage(account, region_id, instance_ids): CPU 使用率
- get_memory_usage(account, region_id, instance_ids): 内存使用率

### 火山云查询类（可直接使用）
- volc_query_ecs(account, region_id, max_total=500): 查询火山云 ECS 实例（自动分页）
- volc_query_ecs_by_id(account, instance_id, region_id): 根据ID查询火山云实例
- volc_describe_regions(account): 查询火山云支持的地域

### 费用/退订类（需用户确认）
- refund_instance(account, instance_id, product_code): 退订包年包月实例
- query_available_instances(account, region, product_code): 查询可退订实例
- query_account_balance(account): 查询账号余额

### 回收类（ITSM 触发，一键执行）
- recycle_ecs(instance_id, account, region_id, ticket_id?): 一键回收 ECS，自动完成查询→保护校验→停机→打快照→退订/释放，返回结构化 JSON 结果。ticket_id 为 ITSM 工单号。

### 操作类（需用户确认）
- safe_delete_ecs(account, region_id, instance_id, instance_name, charge_type): 安全删除/退订 ECS。charge_type 来自查询结果的 charge 字段
- safe_stop_ecs(account, region_id, instance_ids): 停止 ECS
- safe_start_ecs(account, region_id, instance_ids): 启动 ECS
- safe_reboot_ecs(account, region_id, instance_ids): 重启 ECS

## 工作原则
1. 每个工具都需要 account 参数，用户没指定时要问
2. 查询操作直接执行
3. 删除/停止/重启等危险操作，必须：
   a. 先用 query_ecs_by_id、query_ecs_instances 或 query_ecs_by_ip 查询实例信息
   b. 展示给用户确认
   c. 用户明确同意后，调用 safe_delete_ecs 并传入 instance_name 和 charge_type（来自查询结果的 charge 字段）
   d. 注意：查询和删除是两次独立的工具调用，不要在同一轮调用
4. blocked=True 的实例绝对不能删除

## 地域映射
- 深圳 = cn-shenzhen | 杭州 = cn-hangzhou | 上海 = cn-shanghai
- 北京 = cn-beijing | 广州 = cn-guangzhou | 香港 = cn-hongkong
- 新加坡 = ap-southeast-1 | 法兰克福 = eu-central-1

## 注意
- 用中文回复
- 关键基础设施（jumpserver/eureka/nacos/master/etcd）要警告
- 包年包月删除要提醒费用风险
""",
    tools=[
        # 账号管理
        query_tools.list_accounts,
        # 查询类
        query_tools.query_ecs_instances,
        query_tools.query_ecs_by_id,
        query_tools.query_ecs_by_ip,
        query_tools.query_vpcs,
        query_tools.query_security_groups,
        query_tools.query_rds_instances,
        query_tools.get_cpu_usage,
        query_tools.get_memory_usage,
        # 操作类（带安全管控）
        safe_tools.safe_delete_ecs,
        safe_tools.safe_stop_ecs,
        safe_tools.safe_start_ecs,
        safe_tools.safe_reboot_ecs,
        # 费用/退订类
        billing_tools.refund_instance,
        billing_tools.query_available_instances,
        billing_tools.query_account_balance,
        # 回收类（ITSM）
        recycle_tools.recycle_ecs,
        # 火山云查询类
        volc_query_tools.volc_query_ecs,
        volc_query_tools.volc_query_ecs_by_id,
        volc_query_tools.volc_describe_regions,
    ],
)
