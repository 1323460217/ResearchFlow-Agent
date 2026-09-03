import asyncio
import logging

from celery import shared_task
from sqlalchemy import select

from backend.database.session import get_worker_session_factory
from backend.models.document import Document
from backend.models.knowledge_base import KnowledgeBase
from backend.rag.ingestion import ingest_document
from backend.worker.runtime import run_worker_coroutine

logger = logging.getLogger(__name__)


def _run_async(coro):
    return asyncio.run(run_worker_coroutine(coro))


@shared_task(bind=True, name="parse_document", max_retries=3, default_retry_delay=30)
def parse_document_task(self, document_id: int, chunk_strategy: str = "auto"):
    """Async parse and ingest a single document into the RAG pipeline."""

    async def _run():
        async with get_worker_session_factory()() as db:
            await ingest_document(
                document_id=document_id,
                db=db,
                chunk_strategy=chunk_strategy,
            )
            await db.commit()

    try:
        self.update_state(state="PROGRESS", meta={"step": "parsing", "document_id": document_id})
        _run_async(_run())
        return {"document_id": document_id, "status": "done"}
    except Exception as exc:
        logger.error("parse_document task failed for doc %d: %s", document_id, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, name="build_index", max_retries=2, default_retry_delay=120)
def build_index_task(self, knowledge_base_id: int, user_id: int):
    """Rebuild the entire vector index for a knowledge base."""

    async def _run():
        async with get_worker_session_factory()() as db:
            result = await db.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.id == knowledge_base_id,
                    KnowledgeBase.user_id == user_id,
                )
            )
            kb = result.scalar_one_or_none()
            if not kb:
                raise ValueError(f"Knowledge base {knowledge_base_id} not found")

            docs_result = await db.execute(
                select(Document).where(
                    Document.knowledge_base_id == knowledge_base_id,
                    Document.ingestion_status == "done",
                )
            )
            docs = docs_result.scalars().all()

            total = len(docs)
            for i, doc in enumerate(docs):
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "step": "indexing",
                        "current": i + 1,
                        "total": total,
                        "document_id": doc.id,
                    },
                )
                doc.ingestion_status = "pending"
                await db.flush()
                await ingest_document(document_id=doc.id, db=db)
            await db.commit()
            return {"knowledge_base_id": knowledge_base_id, "indexed": total}

    try:
        return _run_async(_run())
    except Exception as exc:
        logger.error("build_index task failed for kb %d: %s", knowledge_base_id, exc)
        raise self.retry(exc=exc)
