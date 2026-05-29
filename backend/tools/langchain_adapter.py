from typing import List

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

from backend.tools.base import BaseTool

_TYPE_MAP = {"string": str, "integer": int, "number": float, "boolean": bool}


def _make_executor(tool: BaseTool):
    async def _execute(**kwargs) -> str:
        return await tool.execute(**kwargs)

    return _execute


def tool_to_langchain(tool: BaseTool) -> StructuredTool:
    defn = tool.definition()
    fields = {}
    for prop_name, prop_def in defn.parameters_schema.get("properties", {}).items():
        field_type = _TYPE_MAP.get(prop_def.get("type", ""), str)
        desc = prop_def.get("description", "")
        default_val = prop_def.get("default")
        if default_val is not None:
            fields[prop_name] = (field_type, Field(default=default_val, description=desc))
        else:
            fields[prop_name] = (field_type, Field(description=desc))

    args_model = create_model(f"{defn.name}_args", **fields) if fields else None
    executor = _make_executor(tool)

    return StructuredTool.from_function(
        name=defn.name,
        description=defn.description,
        func=executor,
        coroutine=executor,
        args_schema=args_model,
    )


def tools_to_langchain(tools: List[BaseTool]) -> List[StructuredTool]:
    return [tool_to_langchain(tool) for tool in tools]
