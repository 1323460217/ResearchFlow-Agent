import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from celery import shared_task
from sqlalchemy import delete, select

from backend.database.session import async_session_factory
from backend.models.agent_execution import AgentExecution
from backend.models.document import Document

logger = logging.getLogger(__name__)


def _run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@shared_task(bind=True, name="cleanup_expired")
def cleanup_expired_task(self):
    """Periodic cleanup: remove expired agent executions, failed documents, and orphaned files."""
    tz = timezone(timedelta(hours=8))  # Asia/Shanghai
    now = datetime.now(tz)
    deleted_executions = 0
    deleted_documents = 0
    deleted_files = 0

    async def _cleanup():
        nonlocal deleted_executions, deleted_documents, deleted_files

        async with async_session_factory() as db:
            # 1. Delete agent executions older than 30 days
            cutoff_executions = now - timedelta(days=30)
            result = await db.execute(
                delete(AgentExecution).where(AgentExecution.created_at < cutoff_executions)
            )
            deleted_executions = result.rowcount
            if deleted_executions:
                logger.info("cleanup: removed %d old agent_executions", deleted_executions)

            # 2. Delete failed document records older than 7 days
            cutoff_docs = now - timedelta(days=7)
            failed_docs = await db.execute(
                select(Document).where(
                    Document.ingestion_status == "failed",
                    Document.created_at < cutoff_docs,
                )
            )
            docs_to_delete = failed_docs.scalars().all()

            for doc in docs_to_delete:
                # Remove the physical file
                if doc.file_path and os.path.exists(doc.file_path):
                    try:
                        os.remove(doc.file_path)
                        deleted_files += 1
                    except OSError as exc:
                        logger.warning("cleanup: failed to remove file %s: %s", doc.file_path, exc)

                await db.delete(doc)
                deleted_documents += 1

            await db.commit()

        # 3. Clean up empty upload directories
        upload_root = Path("./data/uploads")
        if upload_root.exists():
            for user_dir in upload_root.iterdir():
                if user_dir.is_dir():
                    try:
                        if not any(user_dir.iterdir()):
                            user_dir.rmdir()
                    except OSError:
                        pass

    try:
        _run_async(_cleanup())
        return {
            "deleted_executions": deleted_executions,
            "deleted_documents": deleted_documents,
            "deleted_files": deleted_files,
        }
    except Exception as exc:
        logger.error("cleanup_expired task failed: %s", exc)
        raise
