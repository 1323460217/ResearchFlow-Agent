"""Query Rewrite / HyDE — 查询改写与假设文档嵌入。

Query Rewrite: 将用户原始问题改写为多条不同角度的搜索查询。
HyDE: 让 LLM 生成"理想回答"的假设文档，用假设文档的向量去检索。
"""

import logging
import re
from typing import List, Optional

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from backend.core.config import settings
from backend.rag.embeddings import embed_query as _embed_query

logger = logging.getLogger(__name__)

QUERY_REWRITE_PROMPT = """You are a research assistant helping to improve search queries for academic paper retrieval.

Given a user's research question, generate {num_queries} different search queries that cover various aspects and phrasings of the topic.

Rules:
- Each query should be on a new line starting with "- "
- Include both English and Chinese versions when appropriate
- Include technical synonyms and alternative phrasings
- For English queries, include key technical terms
- Do not number the queries, just use bullet points

User question: {query}

Search queries:"""


HYDE_PROMPT = """You are a research assistant. Write a short academic passage (150-300 words) that answers the following question as if you were writing a textbook or survey paper. Include key technical terms, methodologies, and findings. Do not mention that this is hypothetical.

Question: {query}

Passage:"""


def _parse_rewrites(text: str) -> List[str]:
    """从 LLM 输出中提取改写后的查询列表。"""
    queries: List[str] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        # 匹配 "- query" 或 "1. query" 或 "query" 格式
        match = re.match(r"^(?:[-*]\s+|(?:\d+[.)]\s*))?(.+)", line)
        if match:
            q = match.group(1).strip()
            if q and len(q) > 3:
                queries.append(q)
    return queries if queries else [text.strip()]


async def rewrite_query(
    query: str,
    num_queries: int = 3,
    model: Optional[str] = None,
) -> List[str]:
    """使用 LLM 将用户查询改写为多条搜索查询。

    Args:
        query: 用户原始查询
        num_queries: 生成的查询数量
        model: 模型名称，默认使用 settings.LLM_MODEL

    Returns:
        改写后的查询列表，至少包含原始查询
    """
    llm = ChatOpenAI(
        model=model or settings.LLM_MODEL,
        openai_api_base=settings.LLM_API_BASE,
        openai_api_key=settings.LLM_API_KEY,
        temperature=0.3,
    )

    prompt = QUERY_REWRITE_PROMPT.format(num_queries=num_queries, query=query)
    try:
        response = await llm.ainvoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        rewrites = _parse_rewrites(text)

        # 确保原始查询始终在列表中
        if query not in rewrites:
            rewrites.insert(0, query)

        logger.debug("Query rewrite: %d queries generated", len(rewrites))
        return rewrites[:num_queries + 1]  # +1 for original
    except Exception as exc:
        logger.warning("Query rewrite failed, returning original: %s", exc)
        return [query]


async def hyde_generate(query: str, model: Optional[str] = None) -> str:
    """生成假设文档（HyDE: Hypothetical Document Embeddings）。

    Args:
        query: 用户查询
        model: 模型名称

    Returns:
        生成的假设文档文本
    """
    llm = ChatOpenAI(
        model=model or settings.LLM_MODEL,
        openai_api_base=settings.LLM_API_BASE,
        openai_api_key=settings.LLM_API_KEY,
        temperature=0.3,
    )

    prompt = HYDE_PROMPT.format(query=query)
    try:
        response = await llm.ainvoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        logger.debug("HyDE document generated: %d chars", len(text))
        return text.strip()
    except Exception as exc:
        logger.warning("HyDE generation failed: %s", exc)
        return query


async def hyde_embed(query: str, model: Optional[str] = None) -> List[float]:
    """HyDE 完整流程：生成假设文档 → 向量化 → 返回向量。

    Args:
        query: 用户查询
        model: 模型名称

    Returns:
        假设文档的 embedding 向量（3072 维）
    """
    hypothetical_doc = await hyde_generate(query, model=model)
    embedding = await _embed_query(hypothetical_doc)
    return embedding
