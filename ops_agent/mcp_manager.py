"""
多云 MCP 客户端管理器
支持阿里云、火山云等多个云厂商，每个账号独立的 MCP 连接
"""
import json
import requests
import time
import threading

from .accounts import MCP_ACCOUNTS as ACCOUNTS


# ============================================================
# 单个 MCP 连接
# ============================================================
class _MCPConnection:
    def __init__(self, api_key: str, mcp_url: str):
        self.api_key = api_key
        self.mcp_url = mcp_url
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.events = []
        self.session_id = None
        self._connected = False
        self._counter = 100
        self._lock = threading.Lock()
        self._listen_alive = False

    def _reset(self):
        """重置连接状态，准备重连"""
        self.events = []
        self.session_id = None
        self._connected = False
        self._listen_alive = False

    def connect(self):
        if self._connected and self._listen_alive:
            return
        self._reset()
        t = threading.Thread(target=self._listen, daemon=True)
        t.start()
        for _ in range(30):
            if self.session_id:
                break
            time.sleep(0.5)
        if not self.session_id:
            raise RuntimeError("MCP connect failed")
        self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                "clientInfo": {"name": "ops-adk-multi", "version": "1.0"}}})
        time.sleep(4)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        time.sleep(1)
        self._connected = True

    def call(self, tool, args, timeout=25):
        self.connect()
        with self._lock:
            self._counter += 1
            cid = self._counter
            scan_start = len(self.events)
        self._post({"jsonrpc": "2.0", "id": cid, "method": "tools/call",
                     "params": {"name": tool, "arguments": args}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(1)
            for ev in self.events[scan_start:]:
                for line in ev.split("\n"):
                    if line.startswith("data:"):
                        try:
                            obj = json.loads(line[5:])
                            if obj.get("id") == cid and "result" in obj:
                                for item in obj["result"].get("content", []):
                                    if item.get("type") == "text":
                                        return json.loads(item["text"])
                        except (json.JSONDecodeError, KeyError):
                            pass
        # 超时：SSE 可能已断线，标记为需要重连
        self._connected = False
        return None

    def _listen(self):
        self._listen_alive = True
        try:
            r = requests.get(f"{self.mcp_url}sse",
                             headers={**self.headers, "Accept": "text/event-stream"},
                             stream=True, timeout=(5, 300))
            buf = ""
            for chunk in r.iter_content(chunk_size=4096, decode_unicode=True):
                if chunk:
                    buf += chunk
                    while "\n\n" in buf:
                        ev, buf = buf.split("\n\n", 1)
                        ev = ev.strip()
                        if ev:
                            self.events.append(ev)
                            if "sessionId=" in ev and not self.session_id:
                                for l in ev.split("\n"):
                                    if l.startswith("data:") and "sessionId=" in l:
                                        self.session_id = l.split("sessionId=")[1].strip()
        except Exception:
            pass
        finally:
            self._listen_alive = False

    def _post(self, payload):
        return requests.post(
            f"{self.mcp_url}message?sessionId={self.session_id}",
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload, timeout=10)


# ============================================================
# 多账号管理器
# ============================================================
class MCPManager:
    _connections: dict[str, _MCPConnection] = {}

    @classmethod
    def get_connection(cls, account: str) -> _MCPConnection:
        """根据账号名获取 MCP 连接"""
        account_key = cls._resolve_account(account)
        if account_key not in cls._connections:
            cfg = ACCOUNTS[account_key]
            cls._connections[account_key] = _MCPConnection(cfg["api_key"], cfg["mcp_url"])
        return cls._connections[account_key]

    @classmethod
    def call(cls, account: str, tool: str, args: dict, timeout=25):
        """调用指定账号的 MCP 工具"""
        conn = cls.get_connection(account)
        return conn.call(tool, args, timeout)

    @classmethod
    def list_accounts(cls) -> list[dict]:
        """列出所有可用账号"""
        return [{"key": k, "name": v["name"], "provider": v["provider"], "aliases": v["aliases"]}
                for k, v in ACCOUNTS.items()]

    @classmethod
    def _resolve_account(cls, account: str) -> str:
        """将用户输入的账号名解析为内部 key"""
        account_lower = account.lower().strip()
        # 精确匹配 key
        if account_lower in ACCOUNTS:
            return account_lower
        # 别名匹配
        for key, cfg in ACCOUNTS.items():
            for alias in cfg["aliases"]:
                if alias.lower() == account_lower:
                    return key
        raise ValueError(
            f"未知账号: {account}。可用账号: "
            + ", ".join(f"{v['name']}({k})" for k, v in ACCOUNTS.items())
        )
