import asyncio
import json
import logging
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.config import settings
from backend.tools.base import BaseTool, ToolDefinition

logger = logging.getLogger(__name__)


# ── Circuit Breaker ──────────────────────────────────


class CircuitBreaker:
    """熔断器：连续失败 N 次后打开，等待 recovery_timeout 秒后半开试探。"""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: float = 0.0
        self.state: str = "closed"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold and self.state != "open":
            self.state = "open"
            logger.warning("Circuit breaker OPEN after %d consecutive failures", self.failure_count)

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "closed"

    def allow_request(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.monotonic() - self.last_failure_time > self.recovery_timeout:
                self.state = "half_open"
                logger.info("Circuit breaker HALF-OPEN — probing")
                return True
            return False
        return True  # half_open: allow one probe


# ── MCPTool wrapper ──────────────────────────────────


class MCPTool(BaseTool):
    """MCP 远程工具的本地包装器，实现 BaseTool 接口。

    execute() 委托给 MCPClient.call_tool()，对上层 Store / Agent 透明。
    """

    def __init__(
        self,
        tool_name: str,
        description: str,
        parameters_schema: Dict[str, Any],
        server_name: str,
        client: "MCPClient",
    ):
        self._tool_name = tool_name
        self._description = description
        self._parameters_schema = parameters_schema or {"type": "object", "properties": {}}
        self.server_name = server_name
        self._client = client

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._tool_name,
            description=self._description,
            parameters_schema=self._parameters_schema,
            category="execute",
            timeout_seconds=60,
        )

    async def execute(self, **kwargs) -> str:
        return await self._client.call_tool(self.server_name, self._tool_name, kwargs)


# ── MCPClient ────────────────────────────────────────


class MCPClient:
    """MCP 客户端容错层。

    * 从 mcp_servers.json 加载配置
    * 工具发现（懒加载，首次 list_tools 时连接）
    * 调用容错：retry (3x, exp backoff) + circuit breaker + timeout (60s)
    * 降级：所有容错耗尽后返回错误字符串，不抛异常

    Usage::

        client = get_mcp_client()
        tools = await client.list_tools()
        result = await client.call_tool("filesystem", "read_file", {"path": "/tmp/x"})
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = Path(config_path or settings.MCP_SERVER_CONFIG)
        self._tools: Dict[str, MCPTool] = {}
        self._sessions: Dict[str, Any] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._exit_stack: AsyncExitStack | None = None
        self._connected = False

    # ── Config ───────────────────────────────────────

    def _load_config(self) -> dict:
        if not self._config_path.exists():
            logger.warning("MCP config file not found: %s", self._config_path)
            return {}
        with open(self._config_path, encoding="utf-8") as f:
            return json.load(f)

    # ── Connection management ────────────────────────

    async def connect_all(self) -> None:
        """连接所有 mcp_servers.json 中配置的 Server。幂等（重复调用无副作用）。"""
        if self._connected:
            return

        self._exit_stack = AsyncExitStack()

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client

        config = self._load_config()
        servers: Dict[str, dict] = config.get("servers", {})

        if not servers:
            logger.info("No MCP servers configured — MCPClient is idle")
            self._connected = True
            return

        for server_name, cfg in servers.items():
            transport = cfg.get("transport", "stdio")

            # Ensure circuit breaker exists even if connect fails
            if server_name not in self._circuit_breakers:
                self._circuit_breakers[server_name] = CircuitBreaker()

            try:
                if transport == "stdio":
                    params = StdioServerParameters(
                        command=cfg["command"],
                        args=cfg.get("args", []),
                        env=cfg.get("env") if cfg.get("env") else None,
                    )
                    read, write = await self._exit_stack.enter_async_context(stdio_client(params))
                elif transport == "http":
                    url = cfg["url"]
                    headers: dict | None = cfg.get("headers")
                    read, write = await self._exit_stack.enter_async_context(sse_client(url, headers=headers))
                else:
                    logger.warning("Unknown transport %r for server %r — skipped", transport, server_name)
                    continue

                session = await self._exit_stack.enter_async_context(ClientSession(read, write))
                await asyncio.wait_for(session.initialize(), timeout=30)

                self._sessions[server_name] = session
                self._circuit_breakers[server_name].record_success()
                logger.info("Connected to MCP server %r via %s", server_name, transport)

            except asyncio.TimeoutError:
                logger.error("MCP server %r connection timeout", server_name)
                self._circuit_breakers[server_name].record_failure()
            except Exception as exc:
                logger.error("Failed to connect to MCP server %r: %s", server_name, exc)
                self._circuit_breakers[server_name].record_failure()

        self._connected = True

    # ── Tool discovery ───────────────────────────────

    async def _discover_tools(self) -> None:
        """从所有已连接 Server 拉取工具列表（热加载，可重复调用）。"""
        for server_name, session in list(self._sessions.items()):
            result = None
            try:
                result = await asyncio.wait_for(session.list_tools(), timeout=30)
            except Exception as exc:
                logger.error("list_tools failed for %r: %s", server_name, exc)
                self._circuit_breakers[server_name].record_failure()
                continue

            for tool in result.tools:
                name = tool.name
                try:
                    params_schema = tool.inputSchema
                except AttributeError:
                    params_schema = {"type": "object", "properties": {}}

                self._tools[name] = MCPTool(
                    tool_name=name,
                    description=getattr(tool, "description", "") or "",
                    parameters_schema=params_schema,
                    server_name=server_name,
                    client=self,
                )
                logger.debug("Discovered MCP tool: %s::%s", server_name, name)

            self._circuit_breakers[server_name].record_success()

    async def list_tools(self) -> List[BaseTool]:
        """返回所有已发现的 MCP 外部工具列表。

        首次调用自动触发 connect_all + discover，后续使用缓存。
        """
        if not self._connected:
            await self.connect_all()

        if not self._tools:
            await self._discover_tools()

        return list(self._tools.values())

    # ── Tool call ────────────────────────────────────

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        args: Dict[str, Any],
        retries: int = 3,
        timeout: float = 60.0,
    ) -> str:
        """调用 MCP 工具，含完整容错链路。

        Parameters
        ----------
        server_name : 目标 MCP Server 名称（如 "filesystem"）
        tool_name : 工具名称（如 "read_file"）
        args : 工具参数字典
        retries : 最大重试次数（含首次调用）
        timeout : 单次调用超时秒数
        """
        cb = self._circuit_breakers.get(server_name)
        if cb is None:
            return f"Error: MCP server {server_name!r} not configured"

        if not cb.allow_request():
            return f"Error: Tool {tool_name!r} unavailable — circuit breaker open for {server_name!r}"

        session = self._sessions.get(server_name)
        if session is None:
            cb.record_failure()
            return f"Error: MCP server {server_name!r} is not connected"

        last_error: str = ""
        for attempt in range(retries):
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, args),
                    timeout=timeout,
                )
                cb.record_success()
                return _extract_text(result)

            except asyncio.TimeoutError:
                last_error = f"timeout after {timeout:.0f}s"
                logger.warning(
                    "MCP call %s::%s timeout (attempt %d/%d)", server_name, tool_name, attempt + 1, retries
                )
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "MCP call %s::%s failed (attempt %d/%d): %s",
                    server_name, tool_name, attempt + 1, retries, exc,
                )

            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)  # 1s → 2s → 4s

        cb.record_failure()
        return f"Error: Tool {tool_name!r} failed after {retries} retries — {last_error}"

    # ── Cleanup ──────────────────────────────────────

    async def disconnect_all(self) -> None:
        """断开所有 MCP Server 连接并释放资源。"""
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
        self._sessions.clear()
        self._tools.clear()
        self._exit_stack = None
        self._connected = False
        logger.info("MCPClient disconnected from all servers")


# ── Helpers ──────────────────────────────────────────


def _extract_text(result: Any) -> str:
    """从 MCP CallToolResult 中提取文本内容。"""
    try:
        contents = result.content
    except AttributeError:
        return str(result)

    texts: List[str] = []
    for item in contents:
        if hasattr(item, "text"):
            texts.append(item.text)
        else:
            texts.append(str(item))
    return "\n".join(texts) if texts else str(result)


# ── Singleton ────────────────────────────────────────


_mcp_client: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    """获取模块级 MCPClient 单例。"""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client


def reset_mcp_client() -> None:
    """重置 MCPClient 单例（测试用）。"""
    global _mcp_client
    _mcp_client = None
