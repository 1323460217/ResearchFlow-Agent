"""JSON serialization utilities for LangChain message types."""

from langchain_core.messages import AIMessage, BaseMessage


def sanitize_for_json(obj):
    """递归转换对象为 JSON 可序列化格式，处理 LangChain message 类型。"""
    if isinstance(obj, BaseMessage):
        result = {"type": obj.__class__.__name__, "content": str(obj.content)}
        if hasattr(obj, "name") and obj.name:
            result["name"] = obj.name
        if hasattr(obj, "tool_call_id") and obj.tool_call_id:
            result["tool_call_id"] = obj.tool_call_id
        if isinstance(obj, AIMessage) and hasattr(obj, "tool_calls") and obj.tool_calls:
            result["tool_calls"] = [
                {"name": tc.get("name", ""), "args": tc.get("args", {})}
                for tc in obj.tool_calls
            ]
        return result
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(item) for item in obj]
    if hasattr(obj, "model_dump"):
        return sanitize_for_json(obj.model_dump())
    if hasattr(obj, "__dict__"):
        return str(obj)
    return obj
