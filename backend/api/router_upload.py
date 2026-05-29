import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.schemas import ApiResponse, UploadResponse
from backend.core.exceptions import NotFoundError, ValidationError
from backend.database.session import get_db
from backend.models.document import Document
from backend.models.knowledge_base import KnowledgeBase
from backend.models.user import User
from backend.rag.ingestion import ingest_document

router = APIRouter(prefix="/api", tags=["upload"])
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"pdf", "docx", "md", "txt", "html"}


@router.post("/upload", response_model=ApiResponse)
async def upload_document(
    knowledge_base_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Validate knowledge base
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = kb_result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("知识库")

    # Validate file extension
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(detail={"file": f"不支持的文件格式: .{ext}"})

    # Save file to disk
    upload_dir = Path("./data/uploads") / str(user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = upload_dir / safe_name

    content = await file.read()
    file_path.write_bytes(content)

    # Create document record
    doc = Document(
        knowledge_base_id=knowledge_base_id,
        user_id=user.id,
        filename=file.filename,
        file_type=ext,
        file_size_bytes=len(content),
        file_path=str(file_path),
        ingestion_status="pending",
    )
    db.add(doc)
    await db.flush()

    kb.doc_count += 1
    await db.flush()

    # Inline ingestion to avoid multi-process ChromaDB SQLite corruption.
    # Previously dispatched via Celery, which caused worker + API to open
    # separate PersistentClient instances on the same SQLite file.
    try:
        await ingest_document(document_id=doc.id, db=db)
    except Exception as exc:
        logger.exception("Document %d ingestion failed", doc.id)
        return ApiResponse(
            data=UploadResponse(
                document_id=doc.id,
                task_id="sync",
                filename=file.filename,
                status="failed",
                message=f"文档处理失败: {exc}",
            )
        )

    return ApiResponse(
        data=UploadResponse(
            document_id=doc.id,
            task_id="sync",
            filename=file.filename,
            status="done",
            message="文档已上传并处理完成",
        )
    )
