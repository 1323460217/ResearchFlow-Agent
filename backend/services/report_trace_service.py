from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent_run import AgentRun
from backend.models.agent_run_step import AgentRunStep
from backend.models.enums import AgentRunStepStatus
from backend.repositories.agent_run_repository import AgentRunRepository
from backend.repositories.agent_run_step_repository import AgentRunStepRepository
from backend.repositories.tool_call_repository import sanitize_summary
from backend.services._utils import step_to_dict


class ReportTraceService:
    def __init__(
        self,
        agent_run_repository: AgentRunRepository | None = None,
        step_repository: AgentRunStepRepository | None = None,
    ):
        self.agent_runs = agent_run_repository or AgentRunRepository()
        self.steps = step_repository or AgentRunStepRepository()

    async def _owned_step(
        self, session: AsyncSession, step_id: int, user_id: int
    ) -> AgentRunStep | None:
        return await session.scalar(
            select(AgentRunStep)
            .join(AgentRun, AgentRun.id == AgentRunStep.run_id)
            .where(AgentRunStep.id == step_id, AgentRun.user_id == user_id)
        )

    async def start_step(
        self,
        session: AsyncSession,
        user_id: int,
        run_id: int,
        node_name: str,
        celery_task_id: str | None = None,
        input_summary: Any | None = None,
        checkpoint_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if await self.agent_runs.get_by_id_for_user(session, run_id, user_id) is None:
            raise LookupError("agent run does not exist for this user")
        step = await self.steps.create_step_started(
            session=session,
            run_id=run_id,
            node_name=node_name,
            celery_task_id=celery_task_id,
            input_summary=sanitize_summary(input_summary),
            checkpoint_id=checkpoint_id,
            trace_id=trace_id,
        )
        return step_to_dict(step)

    async def finish_step_success(
        self,
        session: AsyncSession,
        user_id: int,
        step_id: int,
        output_summary: Any | None = None,
        checkpoint_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if await self._owned_step(session, step_id, user_id) is None:
            raise LookupError("step does not exist for this user")
        step = await self.steps.mark_step_success(
            session=session,
            step_id=step_id,
            output_summary=sanitize_summary(output_summary),
            checkpoint_id=checkpoint_id,
            trace_id=trace_id,
        )
        return step_to_dict(step)

    async def finish_step_failure(
        self,
        session: AsyncSession,
        user_id: int,
        step_id: int,
        error_message: str,
        error_code: str | None = None,
        output_summary: Any | None = None,
    ) -> dict[str, Any]:
        if await self._owned_step(session, step_id, user_id) is None:
            raise LookupError("step does not exist for this user")
        step = await self.steps.mark_step_failure(
            session=session,
            step_id=step_id,
            error_message=error_message,
            error_code=error_code,
            output_summary=sanitize_summary(output_summary),
        )
        return step_to_dict(step)

    async def mark_step_interrupted(
        self,
        session: AsyncSession,
        user_id: int,
        step_id: int,
        output_summary: Any | None = None,
    ) -> dict[str, Any]:
        if await self._owned_step(session, step_id, user_id) is None:
            raise LookupError("step does not exist for this user")
        step = await self.steps.mark_step_interrupted(
            session=session,
            step_id=step_id,
            output_summary=sanitize_summary(output_summary),
        )
        return step_to_dict(step)

    async def list_steps_for_user(
        self,
        session: AsyncSession,
        run_id: int,
        user_id: int,
        offset: int = 0,
        limit: int = 100,
        node_name: str | None = None,
        status: str | AgentRunStepStatus | None = None,
    ) -> list[dict[str, Any]]:
        if await self.agent_runs.get_by_id_for_user(session, run_id, user_id) is None:
            raise LookupError("agent run does not exist for this user")
        steps = await self.steps.list_steps(
            session=session,
            run_id=run_id,
            offset=offset,
            limit=limit,
            node_name=node_name,
            status=status,
        )
        return [step_to_dict(step) for step in steps]
