import logging
from typing import Dict, List

from langchain_core.tools import StructuredTool

from backend.tools.base import BaseTool, ToolDefinition
from backend.tools.langchain_adapter import tools_to_langchain

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Tool registration and discovery for built-in function-calling tools."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        name = tool.definition().name
        if name in self._tools:
            logger.warning("Tool %r is already registered, overwriting", name)
        self._tools[name] = tool
        logger.debug("Registered tool: %s", name)

    def get_tool(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"Tool {name!r} not found in registry")
        return self._tools[name]

    def get_definitions(self) -> List[Dict]:
        results = []
        for name, tool in self._tools.items():
            defn = tool.definition()
            results.append({
                "name": name,
                "description": defn.description,
                "parameters": defn.parameters_schema,
            })
        return results

    def get_by_category(self, category: str) -> List[BaseTool]:
        return [t for t in self._tools.values() if t.definition().category == category]

    def get_all(self) -> List[BaseTool]:
        return list(self._tools.values())

    def to_langchain_tools(self) -> List[StructuredTool]:
        return tools_to_langchain(self.get_all())
