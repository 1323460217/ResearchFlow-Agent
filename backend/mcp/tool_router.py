import logging
from typing import List, Optional

from langchain_core.tools import StructuredTool

from backend.tools.base import BaseTool
from backend.tools.langchain_adapter import tools_to_langchain
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolRouter:
    """Route tool lookup across local function-calling tools and MCP tools."""

    def __init__(self, registry: ToolRegistry, mcp_client):
        self._registry = registry
        self._mcp_client = mcp_client

    async def get_tool(self, name: str) -> BaseTool:
        try:
            return self._registry.get_tool(name)
        except KeyError:
            pass

        for tool in await self._mcp_client.list_tools():
            if tool.definition().name == name:
                return tool

        raise KeyError(f"Tool {name!r} not found in ToolRegistry or MCPClient")

    async def get_all_tools(self) -> List[BaseTool]:
        fc_tools = self._registry.get_all()
        mcp_tools = await self._mcp_client.list_tools()
        return fc_tools + mcp_tools

    async def to_langchain_tools(self) -> List[StructuredTool]:
        return tools_to_langchain(await self.get_all_tools())


_router: Optional[ToolRouter] = None


async def get_tool_router() -> ToolRouter:
    global _router
    if _router is None:
        from backend.mcp.client import get_mcp_client
        from backend.tools import get_default_registry

        _router = ToolRouter(
            registry=get_default_registry(),
            mcp_client=get_mcp_client(),
        )
        logger.info("ToolRouter initialized")
    return _router


def reset_tool_router() -> None:
    global _router
    _router = None
