import json
import logging
import re
from dataclasses import dataclass

from langchain_openai import ChatOpenAI

from backend.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMStreamResult:
    text: str
    token_usage: dict | None = None


def get_llm(model: str | None = None, temperature: float = 0.3) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or settings.LLM_MODEL,
        openai_api_base=settings.LLM_API_BASE,
        openai_api_key=settings.LLM_API_KEY,
        temperature=temperature,
    )


def _normalize_usage_metadata(usage: dict | None) -> dict | None:
    if not usage:
        return None

    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
    total_tokens = usage.get("total_tokens", input_tokens + output_tokens) or 0
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


async def astream_llm_with_usage(
    messages: list,
    model: str | None = None,
    temperature: float = 0.3,
) -> LLMStreamResult:
    """Stream LLM response and return assembled text plus provider token usage."""
    llm = get_llm(model=model, temperature=temperature)
    full_text = ""
    token_usage = None
    async for chunk in llm.astream(messages, stream_usage=True):
        content = chunk.content if hasattr(chunk, "content") else str(chunk)
        if content:
            full_text += content
        usage = getattr(chunk, "usage_metadata", None)
        if usage:
            token_usage = _normalize_usage_metadata(dict(usage))
    return LLMStreamResult(text=full_text, token_usage=token_usage)


async def astream_llm_text(
    messages: list,
    model: str | None = None,
    temperature: float = 0.3,
) -> str:
    """Stream LLM response and return the assembled full text.

    Uses llm.astream() so that LangGraph's astream_events() emits
    on_chat_model_stream events for each token chunk.
    """
    result = await astream_llm_with_usage(messages, model=model, temperature=temperature)
    return result.text


def parse_json_from_response(text: str) -> dict:
    """从 LLM 文本响应中提取 JSON，兼容 markdown 代码块包裹。"""
    # 优先匹配 ```json ... ``` 或 ``` ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1)

    # 尝试提取首个 JSON 对象
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # 最后尝试直接解析全文
    return json.loads(text)
