"""
审计日志 - 所有操作的统一审计记录
"""
import json
import os
from datetime import datetime

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "audit_logs")


def audit_log(action: str, detail: dict):
    os.makedirs(_LOG_DIR, exist_ok=True)
    entry = {"time": datetime.now().isoformat(), "action": action, **detail}
    filepath = os.path.join(_LOG_DIR, f"audit_{datetime.now():%Y%m%d}.jsonl")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
