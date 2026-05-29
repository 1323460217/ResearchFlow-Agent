"""检索管线 — 多路召回 + RRF 融合 + Rerank。

完整管线：
  Query → [Query Rewrite] → Dense(top-20) + BM25(top-20)
  → RRF 融合(top-25) → Rerank(top-8) → 结果

支持：
  - HyDE: 用假设文档向量检索
  - Parent-Child Retrieval: 子 chunk 召回 → 父 chunk 返回
  - Self-Query: 元数据过滤
"""

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.core.config import settings
from backend.rag.chroma_client import get_or_create_collection
from backend.rag.embeddings import embed_query

logger = logging.getLogger(__name__)


# ── 全局 BM25 缓存 ──────────────────────────────────────

# {collection_name: {"corpus": [...], "tokenized_corpus": [...], "doc_ids": [...]}}
_bm25_cache: Dict[str, Any] = {}

# 正则：提取中文字和英文/数字单词
_TOKEN_RE = re.compile(r"[一-鿿]+|[a-zA-Z0-9]+")


def _jieba_tokenize(text: str) -> List[str]:
    """使用 jieba 分词，兼顾中英文。"""
    try:
        import jieba
    except ImportError:
        return _TOKEN_RE.findall(text)

    tokens = []
    # 先按非中文字符分段，中文段用 jieba，其他用正则
    seg_pattern = re.compile(r"([一-鿿]+)")
    parts = seg_pattern.split(text)
    for part in parts:
        if not part.strip():
            continue
        if seg_pattern.match(part):
            tokens.extend(jieba.lcut(part))
        else:
            tokens.extend(_TOKEN_RE.findall(part))
    return [t.lower() for t in tokens if t.strip()]


def _build_bm25_index(collection_name: str) -> Optional[Any]:
    """为指定 collection 构建 BM25 索引，结果缓存到 _bm25_cache。

    如果 collection 为空或 rank_bm25 不可用，返回 None。
    """
    global _bm25_cache

    cached = _bm25_cache.get(collection_name)
    if cached is not None:
        return cached

    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        logger.warning("rank_bm25 not installed, BM25 retrieval disabled")
        return None

    collection = get_or_create_collection(collection_name)

    try:
        result = collection.get(include=["documents", "metadatas"])
    except Exception as exc:
        logger.error("Failed to load collection %s for BM25: %s", collection_name, exc)
        return None

    if not result or not result["ids"]:
        logger.debug("Collection %s is empty, skipping BM25 index", collection_name)
        _bm25_cache[collection_name] = None
        return None

    doc_texts: List[str] = result["documents"] or []
    doc_ids: List[str] = result["ids"] or []
    metadatas: List[dict] = result["metadatas"] or []

    if not doc_texts:
        _bm25_cache[collection_name] = None
        return None

    tokenized = [_jieba_tokenize(text) for text in doc_texts]
    bm25 = BM25Okapi(tokenized)

    cached = {
        "bm25": bm25,
        "corpus": doc_texts,
        "doc_ids": doc_ids,
        "metadatas": metadatas,
    }
    _bm25_cache[collection_name] = cached
    logger.info("BM25 index built for %s: %d docs", collection_name, len(doc_texts))
    return cached


def _invalidate_bm25_cache(collection_name: str) -> None:
    """使指定 collection 的 BM25 缓存失效（文档增删后调用）。"""
    _bm25_cache.pop(collection_name, None)
    logger.debug("BM25 cache invalidated for %s", collection_name)


# ── 数据结构 ────────────────────────────────────────────


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: int
    chunk_index: int = 0
    content: str = ""
    score: float = 0.0
    source: str = ""          # "dense" | "bm25" | "rrf"
    kb_id: int = 0
    filename: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Dense Retrieval ─────────────────────────────────────


async def dense_retrieval(
    query_embedding: List[float],
    collection_name: str,
    top_k: int = 20,
    filter_metadata: Optional[Dict[str, Any]] = None,
) -> List[RetrievedChunk]:
    """向量相似度检索（Dense Retrieval）。

    Args:
        query_embedding: 查询向量
        collection_name: ChromaDB collection 名称
        top_k: 返回数量
        filter_metadata: ChromaDB where 过滤条件

    Returns:
        RetrievedChunk 列表
    """
    collection = get_or_create_collection(collection_name)

    kwargs: Dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if filter_metadata:
        kwargs["where"] = filter_metadata

    try:
        result = collection.query(**kwargs)
    except Exception as exc:
        logger.error("Dense retrieval failed for %s: %s", collection_name, exc)
        return []

    if not result or not result["ids"] or not result["ids"][0]:
        return []

    chunks = []
    ids_list = result["ids"][0]
    docs_list = result["documents"][0] if result["documents"] else [""] * len(ids_list)
    metas_list = result["metadatas"][0] if result["metadatas"] else [{}] * len(ids_list)
    distances = result["distances"][0] if result["distances"] else [0] * len(ids_list)

    for i, chunk_id in enumerate(ids_list):
        meta = metas_list[i] if i < len(metas_list) else {}
        # ChromaDB 返回 distance，转换为相似度分数 (cosine distance → similarity)
        dist = distances[i] if i < len(distances) else 0
        score = 1.0 - min(dist, 2.0) / 2.0  # 归一化到 [0, 1]

        chunks.append(RetrievedChunk(
            chunk_id=chunk_id,
            document_id=meta.get("document_id", 0),
            chunk_index=meta.get("chunk_index", 0),
            content=docs_list[i] if i < len(docs_list) else "",
            score=round(score, 6),
            source="dense",
            kb_id=meta.get("kb_id", 0),
            filename=meta.get("source", ""),
            metadata=meta,
        ))

    return chunks


# ── BM25 Sparse Retrieval ───────────────────────────────


async def bm25_retrieval(
    query: str,
    collection_name: str,
    top_k: int = 20,
) -> List[RetrievedChunk]:
    """BM25 关键词检索（Sparse Retrieval）。

    Args:
        query: 查询文本
        collection_name: ChromaDB collection 名称
        top_k: 返回数量

    Returns:
        RetrievedChunk 列表
    """
    cached = _build_bm25_index(collection_name)
    if cached is None:
        return []

    bm25 = cached["bm25"]
    doc_ids = cached["doc_ids"]
    corpus = cached["corpus"]
    metadatas = cached.get("metadatas", [{}] * len(doc_ids))

    tokenized_query = _jieba_tokenize(query)
    if not tokenized_query:
        return []

    try:
        scores = bm25.get_scores(tokenized_query)
    except Exception as exc:
        logger.error("BM25 scoring failed: %s", exc)
        return []

    # 取 top_k
    indexed_scores = list(enumerate(scores))
    indexed_scores.sort(key=lambda x: x[1], reverse=True)
    top_indices = indexed_scores[:top_k]

    # 归一化 BM25 分数到 [0, 1]
    max_score = top_indices[0][1] if top_indices else 1.0

    chunks = []
    for idx, raw_score in top_indices:
        if raw_score <= 0:
            continue
        meta = metadatas[idx] if idx < len(metadatas) else {}
        chunks.append(RetrievedChunk(
            chunk_id=doc_ids[idx],
            document_id=meta.get("document_id", 0),
            chunk_index=meta.get("chunk_index", 0),
            content=corpus[idx] if idx < len(corpus) else "",
            score=round(raw_score / max(max_score, 0.001), 6),
            source="bm25",
            kb_id=meta.get("kb_id", 0),
            filename=meta.get("source", ""),
            metadata=meta,
        ))

    return chunks


# ── RRF Fusion ──────────────────────────────────────────


def rrf_fusion(
    result_groups: List[List[RetrievedChunk]],
    k: int = 60,
    top_k: int = 25,
) -> List[RetrievedChunk]:
    """RRF (Reciprocal Rank Fusion) 融合多路检索结果。

    RRF score = sum(1 / (k + rank_i)) for each result group.

    Args:
        result_groups: 多组检索结果
        k: RRF 平滑常数
        top_k: 融合后保留的数量

    Returns:
        去重融合后的 RetrievedChunk 列表
    """
    rrf_scores: Dict[str, Tuple[RetrievedChunk, float]] = {}

    for group in result_groups:
        for rank, chunk in enumerate(group):
            rrf_score = 1.0 / (k + rank + 1)  # rank 从 1 开始
            if chunk.chunk_id in rrf_scores:
                existing, existing_score = rrf_scores[chunk.chunk_id]
                rrf_scores[chunk.chunk_id] = (existing, existing_score + rrf_score)
            else:
                rrf_scores[chunk.chunk_id] = (chunk, rrf_score)

    # 按 RRF 分数排序
    fused = sorted(rrf_scores.values(), key=lambda x: x[1], reverse=True)
    top = fused[:top_k]

    # 更新分数和来源标记
    results = []
    for chunk, rrf_score in top:
        chunk.score = round(rrf_score, 6)
        chunk.source = "rrf"
        results.append(chunk)

    return results


# ── Hybrid Retrieval ────────────────────────────────────


async def hybrid_retrieval(
    query: str,
    collection_name: str,
    dense_top_k: int = 20,
    bm25_top_k: int = 20,
    rrf_top_k: int = 25,
    rerank_top_k: int = 8,
    use_rerank: bool = True,
    filter_metadata: Optional[Dict[str, Any]] = None,
) -> List[RetrievedChunk]:
    """混合检索完整管线：Dense + BM25 → RRF → Rerank。

    Args:
        query: 查询文本
        collection_name: ChromaDB collection 名称
        dense_top_k: Dense 检索候选数
        bm25_top_k: BM25 检索候选数
        rrf_top_k: RRF 融合后保留数
        rerank_top_k: Rerank 后保留数
        use_rerank: 是否启用 Rerank
        filter_metadata: 元数据过滤条件

    Returns:
        RetrievedChunk 列表，按分数降序
    """
    # 1. 向量化查询
    query_embedding = await embed_query(query)

    # 2. 并行 Dense + BM25 检索
    dense_results = await dense_retrieval(
        query_embedding, collection_name, dense_top_k, filter_metadata,
    )
    bm25_results = await bm25_retrieval(query, collection_name, bm25_top_k)

    logger.debug(
        "Hybrid retrieval: dense=%d, bm25=%d",
        len(dense_results), len(bm25_results),
    )

    # 3. RRF 融合
    fused = rrf_fusion([dense_results, bm25_results], top_k=rrf_top_k)

    if not fused:
        # 如果 RRF 结果为空，回退到单独使用 dense 结果
        fused = dense_results[:rrf_top_k]

    # 4. Rerank
    if use_rerank and len(fused) > 1:
        from backend.rag.reranker import get_reranker

        reranker = get_reranker()
        doc_texts = [c.content for c in fused]
        ranked = await reranker.rerank(query, doc_texts, top_k=rerank_top_k)

        results = []
        for idx, score in ranked:
            if idx < len(fused):
                fused[idx].score = score
                fused[idx].source = "rerank"
                results.append(fused[idx])
        return results

    return fused[:rerank_top_k]


# ── Parent-Child Retrieval ──────────────────────────────


async def parent_child_retrieval(
    query: str,
    collection_name: str,
    child_top_k: int = 20,
    rerank_top_k: int = 8,
) -> List[RetrievedChunk]:
    """Parent-Child 检索：子 chunk 精准召回 → 父 chunk 上下文。

    适用于长论文场景：用 512-token 子 chunk 做检索，
    命中后返回其父 chunk（或前后拼接的上下文窗口）。

    Args:
        query: 查询文本
        collection_name: ChromaDB collection 名称
        child_top_k: 子 chunk 检索候选数
        rerank_top_k: 最终返回数

    Returns:
        拼接了相邻 chunk 上下文的 RetrievedChunk 列表
    """
    query_embedding = await embed_query(query)

    # 1. 子 chunk 精确检索
    child_results = await dense_retrieval(query_embedding, collection_name, child_top_k)

    if not child_results:
        return []

    # 2. 收集命中的 document_id
    doc_ids = set(c.chunk_id for c in child_results)

    # 3. 从 ChromaDB 获取相邻 chunk（前后各 2 个）拼成父 chunk
    collection = get_or_create_collection(collection_name)

    expanded = []
    for child in child_results:
        doc_id = child.metadata.get("document_id", 0)
        chunk_idx = child.metadata.get("chunk_index", 0)

        # 获取该文档的所有 chunks
        try:
            all_chunks = collection.get(
                where={"document_id": doc_id},
                include=["documents", "metadatas"],
            )
        except Exception:
            continue

        if not all_chunks or not all_chunks["ids"]:
            continue

        # 按 chunk_index 排序
        indexed = sorted(
            zip(all_chunks["ids"], all_chunks["documents"] or [], all_chunks["metadatas"] or []),
            key=lambda x: x[2].get("chunk_index", 0),
        )

        # 找到当前 chunk 的位置，拼接前后各 2 个
        current_pos = next(
            (i for i, item in enumerate(indexed) if item[2].get("chunk_index") == chunk_idx),
            -1,
        )
        if current_pos < 0:
            continue

        start = max(0, current_pos - 2)
        end = min(len(indexed), current_pos + 3)

        parent_content = "\n\n".join(item[1] for item in indexed[start:end])
        child.content = parent_content
        expanded.append(child)

    # 4. Rerank 去重
    if len(expanded) > rerank_top_k:
        from backend.rag.reranker import get_reranker

        reranker = get_reranker()
        # 去重（按 content）
        seen = set()
        unique = []
        for c in expanded:
            key = c.content[:100]
            if key not in seen:
                seen.add(key)
                unique.append(c)

        doc_texts = [c.content for c in unique]
        ranked = await reranker.rerank(query, doc_texts, top_k=rerank_top_k)

        results = []
        for idx, score in ranked:
            if idx < len(unique):
                unique[idx].score = score
                unique[idx].source = "parent_child"
                results.append(unique[idx])
        return results

    return expanded[:rerank_top_k]


# ── 知识库统一检索入口 ──────────────────────────────────


async def retrieve_from_kb(
    query: str,
    collection_name: str,
    top_k: int = 8,
    strategy: str = "hybrid",
    use_rerank: bool = True,
    use_hyde: bool = False,
    filter_metadata: Optional[Dict[str, Any]] = None,
) -> List[RetrievedChunk]:
    """知识库统一检索入口。

    Args:
        query: 查询文本
        collection_name: 知识库对应的 ChromaDB collection 名称
        top_k: 返回结果数
        strategy: 检索策略 — "hybrid" | "dense" | "bm25" | "parent_child"
        use_rerank: 是否启用 Rerank（仅 hybrid 策略）
        use_hyde: 是否启用 HyDE
        filter_metadata: 元数据过滤条件

    Returns:
        RetrievedChunk 列表
    """
    # HyDE: 用假设文档向量替代原始查询向量
    if use_hyde:
        from backend.rag.query_rewrite import hyde_embed

        hyde_vec = await hyde_embed(query)
        # 对于 HyDE，直接用 dense 检索
        results = await dense_retrieval(hyde_vec, collection_name, top_k=top_k * 3, filter_metadata=filter_metadata)

        if use_rerank and len(results) > 1:
            from backend.rag.reranker import get_reranker

            reranker = get_reranker()
            doc_texts = [c.content for c in results]
            ranked = await reranker.rerank(query, doc_texts, top_k=top_k)
            final = []
            for idx, score in ranked:
                if idx < len(results):
                    results[idx].score = score
                    final.append(results[idx])
            return final
        return results[:top_k]

    if strategy == "dense":
        q_emb = await embed_query(query)
        return await dense_retrieval(q_emb, collection_name, top_k=top_k, filter_metadata=filter_metadata)

    if strategy == "bm25":
        return await bm25_retrieval(query, collection_name, top_k=top_k)

    if strategy == "parent_child":
        return await parent_child_retrieval(query, collection_name, rerank_top_k=top_k)

    # 默认: hybrid
    return await hybrid_retrieval(
        query=query,
        collection_name=collection_name,
        rerank_top_k=top_k,
        use_rerank=use_rerank,
        filter_metadata=filter_metadata,
    )


# ── 多查询融合检索 ──────────────────────────────────────


async def retrieve_with_rewrite(
    query: str,
    collection_name: str,
    top_k: int = 8,
    num_rewrites: int = 3,
    use_rerank: bool = True,
    use_hyde: bool = False,
) -> Tuple[List[RetrievedChunk], List[str]]:
    """Query Rewrite + 多查询检索融合。

    对原始查询和改写后的每个查询分别检索，结果合并 RRF 融合。

    Args:
        query: 用户原始查询
        collection_name: ChromaDB collection 名称
        top_k: 最终返回数
        num_rewrites: 改写查询数量
        use_rerank: 是否启用 Rerank
        use_hyde: 是否对每个改写查询启用 HyDE

    Returns:
        (检索结果列表, 改写后的查询列表)
    """
    from backend.rag.query_rewrite import rewrite_query

    rewrites = await rewrite_query(query, num_queries=num_rewrites)

    # 并行检索所有查询
    all_result_groups = []
    for q in rewrites:
        results = await retrieve_from_kb(
            q, collection_name, top_k=top_k * 2,
            strategy="hybrid", use_rerank=False, use_hyde=use_hyde,
        )
        all_result_groups.append(results)

    # RRF 融合所有结果
    fused = rrf_fusion(all_result_groups, top_k=top_k * 3)

    # Rerank
    if use_rerank and len(fused) > 1:
        from backend.rag.reranker import get_reranker

        reranker = get_reranker()
        doc_texts = [c.content for c in fused]
        ranked = await reranker.rerank(query, doc_texts, top_k=top_k)

        results = []
        for idx, score in ranked:
            if idx < len(fused):
                fused[idx].score = score
                results.append(fused[idx])
        return results, rewrites

    return fused[:top_k], rewrites


# ── 索引管理 ────────────────────────────────────────────


def invalidate_cache(collection_name: str) -> None:
    """使指定 collection 的所有缓存失效。"""
    _invalidate_bm25_cache(collection_name)


def rebuild_bm25_index(collection_name: str) -> bool:
    """强制重建 BM25 索引。"""
    _invalidate_bm25_cache(collection_name)
    result = _build_bm25_index(collection_name)
    return result is not None
