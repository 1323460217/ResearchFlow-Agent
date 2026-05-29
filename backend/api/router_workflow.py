import logging

from celery.result import AsyncResult
from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.schemas import AgentExecutionItem, ApiResponse
from backend.database.session import get_db
from backend.models.agent_execution import AgentExecution
from backend.models.document import Document
from backend.models.user import User
from backend.worker.celery_app import celery_app

router = APIRouter(prefix="/api", tags=["workflow"])
logger = logging.getLogger(__name__)


CELERY_TO_API_STATUS = {
    "PENDING": "queued",
    "RECEIVED": "queued",
    "STARTED": "processing",
    "PROGRESS": "processing",
    "RETRY": "processing",
    "SUCCESS": "done",
    "FAILURE": "failed",
    "REVOKED": "cancelled",
}


DOCUMENT_STATUS_TO_TASK_STATUS = {
    "pending": "pending",
    "parsing": "processing",
    "embedding": "processing",
    "processing": "processing",
    "done": "completed",
    "failed": "failed",
}

DOCUMENT_STATUS_TO_PERCENT = {
    "pending": 0,
    "parsing": 30,
    "processing": 50,
    "embedding": 70,
    "done": 100,
    "failed": 100,
}


def _document_to_task_item(document: Document) -> dict:
    raw_status = document.ingestion_status or "pending"
    status = DOCUMENT_STATUS_TO_TASK_STATUS.get(raw_status, "processing")
    percent = DOCUMENT_STATUS_TO_PERCENT.get(raw_status, 50)

    if status == "failed":
        message = document.ingestion_error or f"{document.filename} 处理失败"
    elif status == "completed":
        message = f"{document.filename} 处理完成"
    elif status == "pending":
        message = f"{document.filename} 等待处理"
    else:
        message = f"正在处理 {document.filename}"

    return {
        "task_id": f"document:{document.id}",
        "task_type": "parse_document",
        "status": status,
        "progress": {
            "step": raw_status,
            "percent": percent,
            "message": message,
        },
        "created_at": document.created_at,
        "estimated_remaining_seconds": None,
    }


@router.get("/workflow/tasks", response_model=ApiResponse)
async def list_tasks(
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Document)
        .where(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = [_document_to_task_item(document) for document in result.scalars().all()]
    return ApiResponse(data={"items": items})


@router.get("/workflow/status/{task_id}", response_model=ApiResponse)
async def get_task_status(
    task_id: str,
    user: User = Depends(get_current_user),
):
    result = AsyncResult(task_id, app=celery_app)

    if result.state == "PENDING" and not result.info:
        return ApiResponse(
            data={
                "task_id": task_id,
                "task_type": "unknown",
                "status": "queued",
                "progress": {},
                "created_at": None,
                "estimated_remaining_seconds": None,
            }
        )

    progress = result.info if isinstance(result.info, dict) else {}
    api_status = CELERY_TO_API_STATUS.get(result.state, "processing")

    data = {
        "task_id": task_id,
        "task_type": result.name or "unknown",
        "status": api_status,
        "progress": progress,
        "created_at": None,
        "estimated_remaining_seconds": None,
    }

    if result.state == "FAILURE":
        data["progress"] = {"error": str(result.info) if result.info else "Unknown error"}

    return ApiResponse(data=data)


@router.get("/agent/executions", response_model=ApiResponse)
async def list_executions(
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    offset = (page - 1) * page_size
    result = await db.execute(
        select(AgentExecution)
        .where(AgentExecution.user_id == user.id)
        .order_by(AgentExecution.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = [AgentExecutionItem.model_validate(e) for e in result.scalars().all()]
    return ApiResponse(data={"items": [i.model_dump() for i in items]})


@router.delete("/agent/executions", response_model=ApiResponse)
async def clear_executions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        delete(AgentExecution).where(AgentExecution.user_id == user.id)
    )
    await db.flush()
    return ApiResponse(data={"deleted": result.rowcount or 0}, message="执行记录已清空")
