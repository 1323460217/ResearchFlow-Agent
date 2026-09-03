from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent_run import AgentRun
from backend.models.enums import AgentRunStatus


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


class AgentRunRepository:
    """CRUD and conditional state updates for :class:`AgentRun`."""

    async def create_agent_run(
        self,
        session: AsyncSession,
        user_id: int,
        query: str,
        conversation_id: int | None = None,
        request_snapshot: Any | None = None,
        max_iterations: int = 3,
        max_human_reviews: int = 3,
        client_request_id: str | None = None,
    ) -> AgentRun:
        if client_request_id:
            existing = await session.scalar(
                select(AgentRun).where(
                    AgentRun.user_id == user_id,
                    AgentRun.client_request_id == client_request_id,
                )
            )
            if existing is not None:
                return existing

        # ``id`` is an autoincrement integer.  A temporary unique value is
        # required for the first flush; it is replaced with the stable id.
        run = AgentRun(
            user_id=user_id,
            conversation_id=conversation_id,
            thread_id=f"pending-{uuid4().hex}",
            status=AgentRunStatus.PENDING.value,
            query=query,
            request_snapshot=request_snapshot,
            max_iterations=max_iterations,
            max_human_reviews=max_human_reviews,
            client_request_id=client_request_id,
            status_version=1,
        )
        session.add(run)
        await session.flush()
        run.thread_id = str(run.id)
        await session.flush()
        return run

    async def get_by_id(self, session: AsyncSession, run_id: int) -> AgentRun | None:
        return await session.scalar(select(AgentRun).where(AgentRun.id == run_id))

    async def get_by_id_for_user(
        self, session: AsyncSession, run_id: int, user_id: int
    ) -> AgentRun | None:
        return await session.scalar(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
        )

    async def update_status(
        self,
        session: AsyncSession,
        run_id: int,
        status: str | AgentRunStatus,
        current_node: str | None = None,
        current_task_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        failed_at: datetime | None = None,
    ) -> AgentRun | None:
        run = await self.get_by_id(session, run_id)
        if run is None:
            return None

        now = datetime.utcnow()
        status_value = _value(status)
        run.status = status_value
        run.status_version += 1
        run.updated_at = now
        if current_node is not None:
            run.current_node = current_node
        if current_task_id is not None:
            run.current_task_id = current_task_id
        if error_code is not None:
            run.error_code = error_code
        if error_message is not None:
            run.error_message = error_message

        if started_at is not None:
            run.started_at = started_at
        elif status_value in {
            AgentRunStatus.STARTED.value,
            AgentRunStatus.RUNNING.value,
            AgentRunStatus.RESUMED.value,
        } and run.started_at is None:
            run.started_at = now
        if completed_at is not None:
            run.completed_at = completed_at
        elif status_value == AgentRunStatus.SUCCESS.value:
            run.completed_at = now
        if failed_at is not None:
            run.failed_at = failed_at
        elif status_value == AgentRunStatus.FAILURE.value:
            run.failed_at = now

        await session.flush()
        return run

    async def compare_and_set_status(
        self,
        session: AsyncSession,
        run_id: int,
        expected_status: str | AgentRunStatus | None = None,
        expected_statuses: Iterable[str | AgentRunStatus] | None = None,
        new_status: str | AgentRunStatus = AgentRunStatus.RUNNING,
        current_node: str | None = None,
        current_task_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AgentRun | None:
        if isinstance(expected_statuses, (str, AgentRunStatus)):
            expected = [expected_statuses]
        else:
            expected = list(expected_statuses or [])
        if expected_status is not None:
            expected.append(expected_status)
        if not expected:
            raise ValueError("expected_status or expected_statuses is required")

        now = datetime.utcnow()
        new_status_value = _value(new_status)
        values: dict[str, Any] = {
            "status": new_status_value,
            "status_version": AgentRun.status_version + 1,
            "updated_at": now,
        }
        if new_status_value in {
            AgentRunStatus.STARTED.value,
            AgentRunStatus.RUNNING.value,
            AgentRunStatus.RESUMED.value,
        }:
            values["started_at"] = now
        if current_node is not None:
            values["current_node"] = current_node
        if current_task_id is not None:
            values["current_task_id"] = current_task_id
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message

        result = await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status.in_([_value(item) for item in expected]),
            )
            .values(**values)
        )
        if result.rowcount != 1:
            return None
        await session.flush()
        return await self.get_by_id(session, run_id)

    async def mark_resume_queued(
        self,
        session: AsyncSession,
        run_id: int,
        user_id: int,
        current_review_id: int | None = None,
        current_task_id: str | None = None,
    ) -> AgentRun | None:
        # AgentRun currently has no current_review_id column.  The review is
        # linked through HumanReview.run_id; the argument is accepted so the
        # service boundary is ready for a future explicit trace field.
        del current_review_id
        values: dict[str, Any] = {
            "status": AgentRunStatus.RESUME_QUEUED.value,
            "status_version": AgentRun.status_version + 1,
            "updated_at": datetime.utcnow(),
            # The start task id must not be reported as the resume task id.
            "current_task_id": None,
        }
        if current_task_id is not None:
            values["current_task_id"] = current_task_id
        result = await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.user_id == user_id,
                AgentRun.status == AgentRunStatus.WAITING_HUMAN.value,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            return None
        await session.flush()
        return await self.get_by_id(session, run_id)

    async def claim_task_id(
        self,
        session: AsyncSession,
        run_id: int,
        user_id: int,
        task_id: str,
        expected_status: str | AgentRunStatus,
    ) -> AgentRun | None:
        """Claim the enqueue slot without overwriting another publisher."""
        result = await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.user_id == user_id,
                AgentRun.status == _value(expected_status),
                AgentRun.current_task_id.is_(None),
            )
            .values(
                current_task_id=task_id,
                status_version=AgentRun.status_version + 1,
                updated_at=datetime.utcnow(),
            )
        )
        if result.rowcount != 1:
            return None
        await session.flush()
        return await self.get_by_id(session, run_id)

    async def list_runs_for_user(
        self,
        session: AsyncSession,
        user_id: int,
        status: str | AgentRunStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[AgentRun]:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be non-negative and limit must be positive")
        query = select(AgentRun).where(AgentRun.user_id == user_id)
        if status is not None:
            query = query.where(AgentRun.status == _value(status))
        result = await session.execute(
            query.order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())
