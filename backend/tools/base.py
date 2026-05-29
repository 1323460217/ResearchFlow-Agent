from abc import ABC, abstractmethod
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    """工具的元信息注册模型，包含 OpenAI Function Call 所需的 JSON Schema。"""

    name: str
    description: str
    parameters_schema: Dict[str, Any]
    category: Literal["search", "parse", "generate", "execute"]
    timeout_seconds: int = 30
    requires_confirmation: bool = False


class BaseTool(ABC):
    """所有工具的抽象基类。

    Parameters
    ----------
    definition : 返回工具的元信息 (名称、描述、参数 schema、分类)
    execute : 异步执行工具，接受 keyword arguments，返回字符串结果
    """

    @abstractmethod
    def definition(self) -> ToolDefinition:
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        ...
