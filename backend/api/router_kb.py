import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.schemas import (
    ApiResponse,
    ChunkResult,
    DocumentItem,
    KBCreateRequest,
    KBCreateResponse,
    KBListItem,
    SearchRequest,
    SearchResponse,
)
from backend.core.exceptions import NotFoundError, ValidationError
from backend.database.session import get_db
from backend.models.document import Document
from backend.models.document_chunk import DocumentChunk
from backend.models.knowledge_base import KnowledgeBase
from backend.models.user import User
from backend.rag.chroma_client import delete_collection
from backend.rag.ingestion import ingest_document
from backend.rag.retrieval import invalidate_cache, retrieve_from_kb, retrieve_with_rewrite

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-base"])
logger = logging.getLogger(__name__)


@router.post("", response_model=ApiResponse)
async def create_kb(
    body: KBCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = KnowledgeBase(
        user_id=user.id,
        name=body.name,
        description=body.description,
        collection_name=f"temp_{uuid.uuid4().hex}",  # replaced after flush
    )
    db.add(kb)
    await db.flush()
    kb.collection_name = f"kb_{kb.id}"
    await db.flush()
    return ApiResponse(data=KBCreateResponse.model_validate(kb))


@router.get("", response_model=ApiResponse)
async def list_kbs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.user_id == user.id)
        .order_by(KnowledgeBase.updated_at.desc())
    )
    items = [KBListItem.model_validate(kb) for kb in result.scalars().all()]
    return ApiResponse(data={"items": [i.model_dump() for i in items]})


@router.get("/{kb_id}", response_model=ApiResponse)
async def get_kb(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("知识库")
    return ApiResponse(data=KBListItem.model_validate(kb))


@router.delete("/{kb_id}", response_model=ApiResponse)
async def delete_kb(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("知识库")
    collection_name = kb.collection_name
    await db.delete(kb)
    await db.flush()
    delete_collection(collection_name)
    return ApiResponse(message="知识库已删除")


@router.post("/{kb_id}/rebuild", response_model=ApiResponse)
async def rebuild_kb_index(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重建知识库的 BM25 索引和向量索引。"""
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = kb_result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("知识库")

    docs_result = await db.execute(
        select(Document).where(
            Document.knowledge_base_id == kb_id,
            Document.ingestion_status == "done",
        )
    )
    docs = docs_result.scalars().all()

    # Rebuild ChromaDB collection from scratch
    delete_collection(kb.collection_name)
    invalidate_cache(kb.collection_name)

    reindexed = 0
    errors = []
    for doc in docs:
        try:
            await ingest_document(document_id=doc.id, db=db)
            reindexed += 1
        except Exception as exc:
            errors.append({"doc_id": doc.id, "error": str(exc)})
            logger.warning("Rebuild: doc %d failed: %s", doc.id, exc)

    await db.flush()

    return ApiResponse(
        message=f"已重建索引: {reindexed} 篇文档",
        data={"reindexed": reindexed, "total": len(docs), "errors": errors},
    )


@router.get("/{kb_id}/docs", response_model=ApiResponse)
async def list_documents(
    kb_id: int,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Verify KB belongs to user
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    if not kb_result.scalar_one_or_none():
        raise NotFoundError("知识库")

    offset = (page - 1) * page_size
    docs_result = await db.execute(
        select(Document)
        .where(Document.knowledge_base_id == kb_id)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = [DocumentItem.model_validate(d) for d in docs_result.scalars().all()]
    return ApiResponse(data={"items": [i.model_dump() for i in items]})


@router.delete("/{kb_id}/docs/{doc_id}", response_model=ApiResponse)
async def delete_document(
    kb_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = kb_result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("知识库")

    doc_result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.knowledge_base_id == kb_id,
        )
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("文档")

    from backend.rag.ingestion import remove_document_from_chroma

    # Count chunks before cascade delete
    chunk_count_result = await db.execute(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    )
    removed_chunks = chunk_count_result.scalar() or 0

    remove_document_from_chroma(doc_id, kb.collection_name)
    kb.doc_count = max(0, kb.doc_count - 1)
    kb.chunk_count = max(0, kb.chunk_count - removed_chunks)
    await db.delete(doc)
    await db.flush()
    invalidate_cache(kb.collection_name)

    return ApiResponse(message="文档已删除")


@router.post("/{kb_id}/search", response_model=ApiResponse)
async def search_kb(
    kb_id: int,
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """在知识库中检索文档片段。

    支持策略：
    - hybrid: Dense + BM25 → RRF → Rerank
    - dense: 仅向量检索
    - bm25: 仅关键词检索
    - parent_child: 子 chunk 召回 → 父 chunk 上下文
    """
    # Verify KB belongs to user
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = kb_result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("知识库")

    if not kb.collection_name:
        raise ValidationError(detail={"kb_id": "知识库尚未完成初始化"})

    # 执行检索
    if body.use_rewrite:
        chunks, rewrites = await retrieve_with_rewrite(
            query=body.query,
            collection_name=kb.collection_name,
            top_k=body.top_k,
            num_rewrites=body.num_rewrites,
            use_rerank=body.use_rerank,
        )
    else:
        chunks = await retrieve_from_kb(
            query=body.query,
            collection_name=kb.collection_name,
            top_k=body.top_k,
            strategy=body.strategy,
            use_rerank=body.use_rerank,
            use_hyde=body.use_hyde,
            filter_metadata=body.filter_metadata,
        )
        rewrites = []

    chunk_results = [
        ChunkResult(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            chunk_index=c.chunk_index,
            content=c.content,
            score=c.score,
            source=c.source,
            filename=c.filename,
        )
        for c in chunks
    ]

    return ApiResponse(
        data=SearchResponse(
            query=body.query,
            rewrites=rewrites,
            chunks=chunk_results,
            total_hits=len(chunk_results),
        ).model_dump()
    )
