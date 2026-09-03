from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent_run_step import AgentRunStep
from backend.models.agent_run import AgentRun
from backend.models.enums import AgentRunStepStatus


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _duration_ms(started_at: datetime | None, ended_at: datetime) -> int:
    if started_at is None:
        return 0
    return max(0, int((ended_at - started_at).total_seconds() * 1000))


class AgentRunStepRepository:
    async def create_step_started(
        self,
        session: AsyncSession,
        run_id: int,
        node_name: str,
        celery_task_id: str | None = None,
        input_summary: Any | None = None,
        checkpoint_id: str | None = None,
        trace_id: str | None = None,
    ) -> AgentRunStep:
        run = await session.scalar(
            select(AgentRun).where(AgentRun.id == run_id).with_for_update()
        )
        if run is None:
            raise LookupError("agent run does not exist")
        next_sequence = await session.scalar(
            select(func.coalesce(func.max(AgentRunStep.sequence), 0) + 1).where(
                AgentRunStep.run_id == run_id
            )
        )
        step = AgentRunStep(
            run_id=run_id,
            sequence=int(next_sequence or 1),
            node_name=node_name,
            status=AgentRunStepStatus.STARTED.value,
            attempt=1,
            celery_task_id=celery_task_id,
            input_summary=input_summary,
            checkpoint_id=checkpoint_id,
            trace_id=trace_id,
            started_at=datetime.utcnow(),
        )
        session.add(step)
        await session.flush()
        return step

    async def get_by_id(
        self, session: AsyncSession, step_id: int
    ) -> AgentRunStep | None:
        return await session.scalar(select(AgentRunStep).where(AgentRunStep.id == step_id))

    async def mark_step_success(
        self,
        session: AsyncSession,
        step_id: int,
        output_summary: Any | None = None,
        checkpoint_id: str | None = None,
        trace_id: str | None = None,
    ) -> AgentRunStep | None:
        step = await self.get_by_id(session, step_id)
        if step is None:
            return None
        ended_at = datetime.utcnow()
        step.status = AgentRunStepStatus.SUCCESS.value
        step.ended_at = ended_at
        step.duration_ms = _duration_ms(step.started_at, ended_at)
        if output_summary is not None:
            step.output_summary = output_summary
        if checkpoint_id is not None:
            step.checkpoint_id = checkpoint_id
        if trace_id is not None:
            step.trace_id = trace_id
        step.updated_at = ended_at
        await session.flush()
        return step

    async def mark_step_failure(
        self,
        session: AsyncSession,
        step_id: int,
        error_message: str,
        error_code: str | None = None,
        output_summary: Any | None = None,
    ) -> AgentRunStep | None:
        if not error_message:
            raise ValueError("error_message is required")
        step = await self.get_by_id(session, step_id)
        if step is None:
            return None
        ended_at = datetime.utcnow()
        step.status = AgentRunStepStatus.FAILURE.value
        step.ended_at = ended_at
        step.duration_ms = _duration_ms(step.started_at, ended_at)
        step.error_code = error_code
        step.error_message = error_message
        if output_summary is not None:
            step.output_summary = output_summary
        step.updated_at = ended_at
        await session.flush()
        return step

    async def mark_step_interrupted(
        self,
        session: AsyncSession,
        step_id: int,
        output_summary: Any | None = None,
    ) -> AgentRunStep | None:
        step = await self.get_by_id(session, step_id)
        if step is None:
            return None
        ended_at = datetime.utcnow()
        step.status = AgentRunStepStatus.INTERRUPTED.value
        step.ended_at = ended_at
        step.duration_ms = _duration_ms(step.started_at, ended_at)
        if output_summary is not None:
            step.output_summary = output_summary
        step.updated_at = ended_at
        await session.flush()
        return step

    async def list_steps(
        self,
        session: AsyncSession,
        run_id: int,
        offset: int = 0,
        limit: int = 100,
        node_name: str | None = None,
        status: str | AgentRunStepStatus | None = None,
    ) -> list[AgentRunStep]:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be non-negative and limit must be positive")
        query = select(AgentRunStep).where(AgentRunStep.run_id == run_id)
        if node_name is not None:
            query = query.where(AgentRunStep.node_name == node_name)
        if status is not None:
            query = query.where(AgentRunStep.status == _value(status))
        result = await session.execute(
            query.order_by(AgentRunStep.sequence.asc(), AgentRunStep.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())
