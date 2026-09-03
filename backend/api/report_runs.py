from typing import Any

from fastapi import APIRouter, Depends, Query, status as http_status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.schemas import ApiResponse
from backend.api.schemas_report_runs import (
    CreateReportRunRequest,
    PendingReviewResponse,
    ReportRunDetailResponse,
    ReportRunResponse,
    ReportRunStatusResponse,
    ReportRunStepResponse,
    ResumeReportRunRequest,
    ResumeReportRunResponse,
)
from backend.core.exceptions import InternalError, NotFoundError, ValidationError
from backend.database.session import get_db
from backend.models.user import User
from backend.services.human_review_service import HumanReviewService
from backend.services.report_run_service import ReportRunService
from backend.services.report_status_service import ReportStatusService
from backend.services.report_trace_service import ReportTraceService


router = APIRouter(prefix="/api/report-runs", tags=["report-runs"])

report_run_service = ReportRunService()
report_status_service = ReportStatusService()
report_trace_service = ReportTraceService()
human_review_service = HumanReviewService()


def _run_response(run: dict[str, Any]) -> dict[str, Any]:
    return ReportRunResponse(
        run_id=run["id"],
        thread_id=run["thread_id"],
        status=run["status"],
        current_node=run["current_node"],
        query=run["query"],
        created_at=run["created_at"],
        status_version=run["status_version"],
        celery_task_id=run.get("current_task_id"),
    ).model_dump()


def _run_detail_response(run: dict[str, Any]) -> dict[str, Any]:
    return ReportRunDetailResponse(
        run_id=run["id"],
        thread_id=run["thread_id"],
        status=run["status"],
        current_node=run["current_node"],
        query=run["query"],
        iteration_count=run["iteration_count"],
        max_iterations=run["max_iterations"],
        human_review_round=run["human_review_round"],
        max_human_reviews=run["max_human_reviews"],
        error_code=run["error_code"],
        error_message=run["error_message"],
        created_at=run["created_at"],
        started_at=run["started_at"],
        completed_at=run["completed_at"],
        failed_at=run["failed_at"],
        status_version=run["status_version"],
    ).model_dump()


def _step_response(step: dict[str, Any]) -> dict[str, Any]:
    return ReportRunStepResponse(
        step_id=step["id"],
        sequence=step["sequence"],
        node_name=step["node_name"],
        status=step["status"],
        started_at=step["started_at"],
        ended_at=step["ended_at"],
        duration_ms=step["duration_ms"],
        input_summary=step["input_summary"],
        output_summary=step["output_summary"],
        error_code=step["error_code"],
        error_message=step["error_message"],
    ).model_dump()


def _parse_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.isdigit():
        raise ValidationError(detail={"cursor": "cursor must be a non-negative integer"})
    return int(cursor)


@router.post("", response_model=ApiResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def create_report_run(
    body: CreateReportRunRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    options = dict(body.options)
    if body.title is not None:
        options.setdefault("title", body.title)
    try:
        run = await report_run_service.create_report_run(
            session=db,
            user_id=user.id,
            query=body.query,
            conversation_id=body.conversation_id,
            document_ids=body.document_ids,
            options=options,
            client_request_id=body.client_request_id,
        )
        await db.commit()
        queued = await report_run_service.enqueue_start_report_run(
            session=db, run_id=run["id"], user_id=user.id
        )
    except ValueError as exc:
        raise ValidationError(detail={"request": str(exc)}) from exc
    except SQLAlchemyError as exc:
        raise InternalError() from exc
    return ApiResponse(data=_run_response(queued["run"]), message="报告运行已排队")


@router.get("/{run_id}", response_model=ApiResponse)
async def get_report_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        run = await report_status_service.get_run_detail(db, run_id, user.id)
    except LookupError as exc:
        raise NotFoundError("报告运行") from exc
    except SQLAlchemyError as exc:
        raise InternalError() from exc
    return ApiResponse(data=_run_detail_response(run))


@router.get("/{run_id}/status", response_model=ApiResponse)
async def get_report_run_status(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        result = await report_status_service.get_realtime_status(db, run_id, user.id)
    except LookupError as exc:
        raise NotFoundError("报告运行") from exc
    except SQLAlchemyError as exc:
        raise InternalError() from exc
    data = ReportRunStatusResponse(
        run_id=result["run_id"],
        status=result["status"],
        current_node=result["current_node"],
        progress=result["progress"],
        review_required=result["review_required"],
        review_id=result["review_id"],
        task_id=result["task_id"],
        status_version=result["status_version"],
        updated_at=result["updated_at"],
        source=result["source"],
    )
    return ApiResponse(data=data.model_dump())


@router.get("/{run_id}/steps", response_model=ApiResponse)
async def list_report_run_steps(
    run_id: int,
    page_size: int = Query(default=100, ge=1, le=1000),
    cursor: str | None = None,
    node_name: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    offset = _parse_cursor(cursor)
    try:
        steps = await report_trace_service.list_steps_for_user(
            session=db,
            run_id=run_id,
            user_id=user.id,
            offset=offset,
            limit=page_size,
            node_name=node_name,
            status=status,
        )
    except LookupError as exc:
        raise NotFoundError("报告运行") from exc
    except ValueError as exc:
        raise ValidationError(detail={"request": str(exc)}) from exc
    except SQLAlchemyError as exc:
        raise InternalError() from exc
    next_cursor = str(offset + len(steps)) if len(steps) == page_size else None
    return ApiResponse(
        data={
            "items": [_step_response(step) for step in steps],
            "next_cursor": next_cursor,
        }
    )


@router.get("/{run_id}/pending-review", response_model=ApiResponse)
async def get_pending_review(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        review = await human_review_service.get_pending_review_for_user(db, run_id, user.id)
    except LookupError as exc:
        raise NotFoundError("报告运行") from exc
    except SQLAlchemyError as exc:
        raise InternalError() from exc
    data = PendingReviewResponse(run_id=run_id, pending=review is not None, review=review)
    return ApiResponse(data=data.model_dump())


@router.post(
    "/{run_id}/resume",
    response_model=ApiResponse,
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def resume_report_run(
    run_id: int,
    body: ResumeReportRunRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        result = await report_run_service.prepare_resume(
            session=db,
            run_id=run_id,
            user_id=user.id,
            review_id=body.review_id,
            action=body.action,
            feedback=body.feedback,
            edited_report=body.edited_report,
            idempotency_key=body.idempotency_key,
        )
    except LookupError as exc:
        if "review" in str(exc).lower():
            raise NotFoundError("待审核记录") from exc
        raise NotFoundError("报告运行") from exc
    except ValueError as exc:
        raise ValidationError(detail={"request": str(exc)}) from exc
    except SQLAlchemyError as exc:
        raise InternalError() from exc

    run = result["run"]
    review = result["review"]
    task_id = run.get("current_task_id")
    if result.get("enqueue_required", True):
        await db.commit()
        queued = await report_run_service.enqueue_resume_report_run(
            session=db, run_id=run_id, user_id=user.id
        )
        run = queued["run"]
        task_id = queued["task_id"]
    data = ResumeReportRunResponse(
        run_id=run["id"],
        thread_id=run["thread_id"],
        status=run["status"],
        review_id=review["id"],
        celery_task_id=task_id,
        message="人工审核已提交，运行已准备恢复",
    )
    return ApiResponse(data=data.model_dump(), message="恢复任务已排队")
