import logging
from typing import Optional

from backend.tools.base import BaseTool, ToolDefinition
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_default_registry: Optional[ToolRegistry] = None


def get_default_registry() -> ToolRegistry:
    """获取模块级 ToolRegistry 单例，首次调用时自动注册全部 7 个内置工具。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()

        from backend.tools.arxiv_search import ArxivSearchTool
        from backend.tools.calculator import CalculatorTool
        from backend.tools.pdf_parser import PdfParserTool
        from backend.tools.python_executor import PythonExecutorTool
        from backend.tools.rag_retriever import RagRetrieverTool
        from backend.tools.report_generator import ReportGeneratorTool
        from backend.tools.web_search import WebSearchTool

        _default_registry.register(ArxivSearchTool())
        _default_registry.register(CalculatorTool())
        _default_registry.register(PdfParserTool())
        _default_registry.register(PythonExecutorTool())
        _default_registry.register(RagRetrieverTool())
        _default_registry.register(ReportGeneratorTool())
        _default_registry.register(WebSearchTool())

        logger.info("Default ToolRegistry initialized with %d tools", len(_default_registry.get_all()))
    return _default_registry


def reset_registry() -> None:
    """重置单例注册表（测试用）。"""
    global _default_registry
    _default_registry = None


__all__ = [
    "BaseTool",
    "ToolDefinition",
    "ToolRegistry",
    "get_default_registry",
    "reset_registry",
    "ArxivSearchTool",
    "CalculatorTool",
    "PdfParserTool",
    "PythonExecutorTool",
    "RagRetrieverTool",
    "ReportGeneratorTool",
    "WebSearchTool",
]
