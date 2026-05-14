"""
保护规则 - 关键基础设施的删除/回收保护
"""

PROTECTED_PATTERNS = [
    "jumpserver", "堡垒机", "bastion",
    "eureka", "nacos", "consul",
    "master", "etcd", "apiserver",
    "gateway", "网关",
]

HIGH_RISK_PATTERNS = [
    "prod", "生产", "production",
    "db", "database", "数据库", "mysql", "redis", "mongo",
    "k8s", "worker", "node",
    "mq", "kafka", "rabbitmq",
]


def check_protection(name: str) -> str | None:
    """检查实例名是否匹配保护规则，返回匹配的模式或 None"""
    name_lower = name.lower()
    for p in PROTECTED_PATTERNS:
        if p.lower() in name_lower:
            return p
    return None


def assess_risk(name: str, charge: str, status: str) -> list[str]:
    """评估操作风险等级"""
    risks = []
    name_lower = name.lower()
    for p in HIGH_RISK_PATTERNS:
        if p.lower() in name_lower:
            risks.append(f"名称含高风险关键词: {p}")
    if charge == "PrePaid":
        risks.append("包年包月实例，将走退订流程")
    if status == "Running":
        risks.append("实例正在运行中")
    return risks
