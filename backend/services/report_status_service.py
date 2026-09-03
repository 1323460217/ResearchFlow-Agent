import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import AgentRunStatus
from backend.repositories.agent_run_repository import AgentRunRepository
from backend.repositories.human_review_repository import HumanReviewRepository
from backend.memory.redis_task_status import (
    get_run_status_projection,
    repair_run_status_projection_from_run,
)
from backend.services._utils import run_to_dict

logger = logging.getLogger(__name__)


class ReportStatusService:
    def __init__(
        self,
        agent_run_repository: AgentRunRepository | None = None,
        human_review_repository: HumanReviewRepository | None = None,
    ):
        self.agent_runs = agent_run_repository or AgentRunRepository()
        self.reviews = human_review_repository or HumanReviewRepository()

    async def get_realtime_status(
        self, session: AsyncSession, run_id: int, user_id: int
    ) -> dict[str, Any]:
        """Return Redis status only after PostgreSQL ownership/version checks."""
        run = await self.agent_runs.get_by_id_for_user(session, run_id, user_id)
        if run is None:
            raise LookupError("agent run does not exist for this user")

        run_data = run_to_dict(run)
        if run.status == AgentRunStatus.WAITING_HUMAN.value:
            review = await self.reviews.get_pending_review(session, run_id)
            if review is not None:
                run_data["review_id"] = review.id

        try:
            projection = await get_run_status_projection(run_id)
        except Exception as exc:
            logger.warning("Redis status read failed for report run %s: %s", run_id, exc)
            projection = None

        postgres_version = run.status_version
        if (
            projection is not None
            and projection.get("status")
            and projection.get("status_version") is not None
            and projection["status_version"] >= postgres_version
        ):
            review_required = projection.get("review_required")
            if review_required is None:
                review_required = projection["status"] == AgentRunStatus.WAITING_HUMAN.value
            return {
                "run_id": run_id,
                "status": projection["status"],
                "current_node": projection.get("current_node"),
                "progress": projection.get("progress"),
                "review_required": bool(review_required),
                "review_id": projection.get("review_id"),
                "task_id": projection.get("task_id"),
                "status_version": projection["status_version"],
                "updated_at": projection.get("updated_at") or run.updated_at,
                "source": "redis",
            }

        run_data["progress"] = _progress_for_run(run.status)
        run_data["review_required"] = run.status == AgentRunStatus.WAITING_HUMAN.value
        try:
            await repair_run_status_projection_from_run(run_data)
        except Exception as exc:
            logger.warning("Redis status repair failed for report run %s: %s", run_id, exc)
        return {
            "run_id": run_id,
            "status": run_data["status"],
            "current_node": run_data["current_node"],
            "progress": run_data["progress"],
            "review_required": run_data["review_required"],
            "review_id": run_data.get("review_id"),
            "task_id": run_data.get("current_task_id"),
            "status_version": run_data["status_version"],
            "updated_at": run_data["updated_at"],
            "source": "postgresql",
        }

    async def get_run_detail(
        self, session: AsyncSession, run_id: int, user_id: int
    ) -> dict[str, Any]:
        run = await self.agent_runs.get_by_id_for_user(session, run_id, user_id)
        if run is None:
            raise LookupError("agent run does not exist for this user")
        return run_to_dict(run)

    async def list_user_runs(
        self,
        session: AsyncSession,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        status: str | AgentRunStatus | None = None,
    ) -> dict[str, Any]:
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be positive")
        runs = await self.agent_runs.list_runs_for_user(
            session=session,
            user_id=user_id,
            status=status,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return {
            "items": [run_to_dict(run) for run in runs],
            "page": page,
            "page_size": page_size,
        }

    async def get_realtime_status_placeholder(
        self, session: AsyncSession, run_id: int, user_id: int
    ) -> dict[str, Any]:
        run = await self.get_run_detail(session, run_id, user_id)
        return {
            "run": run,
            "source": "postgresql",
            "redis_projection": "not_connected",
        }


def _progress_for_run(status: str | None) -> int | None:
    return {
        AgentRunStatus.PENDING.value: 0,
        AgentRunStatus.STARTED.value: 10,
        AgentRunStatus.RUNNING.value: 25,
        AgentRunStatus.WAITING_HUMAN.value: 70,
        AgentRunStatus.RESUME_QUEUED.value: 75,
        AgentRunStatus.RESUMED.value: 80,
        AgentRunStatus.SUCCESS.value: 100,
        AgentRunStatus.FAILURE.value: 100,
        AgentRunStatus.CANCELLED.value: 100,
    }.get(status)
