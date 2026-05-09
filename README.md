# OPS Agent (Google ADK Python) - 混合模式

基于 Google Agent Development Kit 的多云运维 Agent。

## 架构（混合模式）

```
用户（Web UI / API / CLI）
    ↓
ADK Agent（LLM 推理 + 工具调度）
    ├── MCP 原生接入（查询类，自动发现）
    │   ├── 阿里云 MCP → ECS/VPC/RDS/OSS 查询
    │   └── 火山云 MCP → ECS 查询（待接入）
    │
    └── 安全管控工具（危险操作，手动封装）
        ├── safe_delete_ecs  → 保护规则 + 审计日志
        ├── safe_stop_ecs    → 审计日志
        ├── safe_start_ecs   → 审计日志
        └── safe_reboot_ecs  → 审计日志
```

## 部署

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置
cp .env.example .env
vi .env  # 填入 API Key 等

# 3. 启动方式（三选一）

# Web UI（开发调试，浏览器访问）
adk web ops_agent

# API Server（生产，REST API）
adk api_server ops_agent --port 8080

# CLI（命令行对话）
adk run ops_agent
```

## 对话示例

```
你：查一下深圳的ECS
Agent：[调用 ECS_DescribeInstances] → 返回实例列表

你：深圳有哪些VPC
Agent：[调用 VPC_DescribeVpcs] → 返回 VPC 列表

你：帮我删除 i-wz9xxxxx
Agent：先查询实例信息 → 展示详情 → 请你确认 → [调用 safe_delete_ecs]

你：查一下那台机器的CPU使用率
Agent：[调用 CMS_GetCpuUsageData] → 返回监控数据
```

## 安全机制

- 堡垒机/eureka/nacos/master/etcd 等关键实例禁止删除
- 生产/数据库/K8s 节点标记高风险
- 所有危险操作记录审计日志（audit_logs/）
- 包年包月实例删除额外警告
