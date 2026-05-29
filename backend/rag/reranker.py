"""Reranker — 对检索结果进行精排。

支持三种后端：
1. FlagReranker: bge-reranker-v2-m3（本地模型，需 FlagEmbedding）
2. LLMReranker: 使用 LLM API 进行打分排序（无需额外依赖）
3. NoopReranker: 透传，不做重排
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from backend.core.config import settings

logger = logging.getLogger(__name__)


class RerankerBase(ABC):
    """Reranker 抽象基类。"""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 8,
    ) -> List[Tuple[int, float]]:
        """对文档列表重新排序。

        Args:
            query: 用户查询
            documents: 文档文本列表
            top_k: 返回的最相关文档数量

        Returns:
            [(doc_index, score), ...] 按分数降序排列
        """
        ...


class NoopReranker(RerankerBase):
    """透传 Reranker：不改变原始顺序，分数统一为 1.0。"""

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 8,
    ) -> List[Tuple[int, float]]:
        n = min(top_k, len(documents))
        return [(i, 1.0) for i in range(n)]


class FlagReranker(RerankerBase):
    """基于 FlagEmbedding / bge-reranker-v2-m3 的 Reranker。"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        try:
            from FlagEmbedding import FlagReranker as _FlagReranker
        except ImportError:
            raise ImportError(
                "FlagEmbedding is not installed. "
                "Install it with: pip install FlagEmbedding"
            )

        self._model = _FlagReranker(model_name, use_fp16=True)
        logger.info("FlagReranker initialized: %s", model_name)

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 8,
    ) -> List[Tuple[int, float]]:
        if not documents:
            return []

        pairs = [[query, doc] for doc in documents]
        try:
            scores = self._model.compute_score(pairs)

            # compute_score may return a single float or a list
            if isinstance(scores, float):
                scores = [scores]

            # Normalize to 0-1 using softmax-like scaling
            ranked = sorted(
                enumerate(scores),
                key=lambda x: x[1],
                reverse=True,
            )
            return ranked[:top_k]
        except Exception as exc:
            logger.error("FlagReranker.rerank failed: %s", exc)
            # Fall back to noop
            n = min(top_k, len(documents))
            return [(i, 1.0) for i in range(n)]


class LLMReranker(RerankerBase):
    """使用 LLM API 进行重排序。

    将所有候选文档一次性发给 LLM，要求 LLM 按相关性排序并返回索引。
    """

    RERANK_PROMPT = """You are a search relevance expert. Rank the following document passages by their relevance to the query.

Query: {query}

Documents:
{documents}

Rank all {num_docs} documents from most relevant to least relevant.
Return ONLY a JSON array of indices ordered by relevance, like: [3, 0, 7, 1, ...]
Do not include any explanation or additional text."""

    def __init__(self, model: Optional[str] = None):
        self._model_name = model or settings.LLM_MODEL

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 8,
    ) -> List[Tuple[int, float]]:
        if not documents:
            return []

        from langchain_openai import ChatOpenAI
        import json

        # 截断过长文档，避免超出 token 限制
        truncated = []
        for i, doc in enumerate(documents):
            if len(doc) > 800:
                truncated.append(f"[{i}] {doc[:800]}...")
            else:
                truncated.append(f"[{i}] {doc}")

        doc_text = "\n\n".join(truncated)
        prompt = self.RERANK_PROMPT.format(
            query=query,
            documents=doc_text,
            num_docs=len(documents),
        )

        llm = ChatOpenAI(
            model=self._model_name,
            openai_api_base=settings.LLM_API_BASE,
            openai_api_key=settings.LLM_API_KEY,
            temperature=0,
        )

        try:
            response = await llm.ainvoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)

            # 提取 JSON 数组
            import re
            match = re.search(r"\[[\d,\s]+\]", text)
            if match:
                indices = json.loads(match.group())
            else:
                indices = json.loads(text.strip())

            # 生成分数：排名越高分数越高
            n = len(indices)
            results = []
            for rank, idx in enumerate(indices):
                if isinstance(idx, int) and 0 <= idx < len(documents):
                    score = 1.0 - (rank / max(n, 1))  # 1.0 → 0.0
                    results.append((idx, round(score, 4)))

            return results[:top_k]
        except Exception as exc:
            logger.error("LLMReranker.rerank failed: %s", exc)
            n = min(top_k, len(documents))
            return [(i, 1.0) for i in range(n)]


_reranker: Optional[RerankerBase] = None


def get_reranker(prefer: str = "auto") -> RerankerBase:
    """获取 Reranker 实例（单例）。

    Args:
        prefer: "auto" | "flag" | "llm" | "noop"

    Returns:
        RerankerBase 实例
    """
    global _reranker

    if _reranker is not None:
        return _reranker

    if prefer == "noop":
        _reranker = NoopReranker()
    elif prefer == "llm":
        _reranker = LLMReranker()
    elif prefer == "flag":
        _reranker = FlagReranker()
    else:  # auto
        try:
            _reranker = FlagReranker()
        except (ImportError, Exception) as exc:
            logger.info("FlagReranker unavailable (%s), trying LLMReranker", exc)
            try:
                _reranker = LLMReranker()
            except Exception:
                logger.warning("LLMReranker also unavailable, using NoopReranker")
                _reranker = NoopReranker()

    return _reranker


def reset_reranker() -> None:
    """重置 Reranker 单例（用于测试或配置变更）。"""
    global _reranker
    _reranker = None
