import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.schemas import (
    ApiResponse,
    ReportCreateRequest,
    ReportDetail,
    ReportListItem,
    ReportUpdateRequest,
)
from backend.core.exceptions import NotFoundError
from backend.database.session import get_db
from backend.models.research_report import ResearchReport
from backend.models.user import User

router = APIRouter(prefix="/api/reports", tags=["reports"])
logger = logging.getLogger(__name__)


@router.post("", response_model=ApiResponse)
async def create_report(
    body: ReportCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = ResearchReport(
        user_id=user.id,
        conversation_id=body.conversation_id,
        title=body.title,
        content=body.content,
        sections=body.sections,
        sources=body.sources,
        status=body.status,
    )
    db.add(report)
    await db.flush()
    return ApiResponse(
        data={
            "id": report.id,
            "title": report.title,
            "status": report.status,
            "created_at": report.created_at,
        },
        message="报告创建成功",
    )


@router.get("", response_model=ApiResponse)
async def list_reports(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    offset = (page - 1) * page_size
    result = await db.execute(
        select(ResearchReport)
        .where(ResearchReport.user_id == user.id)
        .order_by(ResearchReport.updated_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = [ReportListItem.model_validate(r) for r in result.scalars().all()]
    return ApiResponse(data={"items": [i.model_dump() for i in items]})


@router.get("/{report_id}", response_model=ApiResponse)
async def get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ResearchReport).where(
            ResearchReport.id == report_id,
            ResearchReport.user_id == user.id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError("报告")
    return ApiResponse(data=ReportDetail.model_validate(report))


@router.put("/{report_id}", response_model=ApiResponse)
async def update_report(
    report_id: int,
    body: ReportUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ResearchReport).where(
            ResearchReport.id == report_id,
            ResearchReport.user_id == user.id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError("报告")

    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(report, key, value)

    await db.flush()
    return ApiResponse(data=ReportDetail.model_validate(report), message="报告更新成功")


@router.delete("/{report_id}", response_model=ApiResponse)
async def delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ResearchReport).where(
            ResearchReport.id == report_id,
            ResearchReport.user_id == user.id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError("报告")
    await db.delete(report)
    return ApiResponse(message="报告已删除")
