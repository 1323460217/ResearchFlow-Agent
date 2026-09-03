import logging
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.redis_task_status import set_run_status_projection_if_newer
from backend.models.enums import AgentRunStatus
from backend.repositories.agent_run_repository import AgentRunRepository
from backend.repositories.tool_call_repository import sanitize_summary
from backend.services._utils import review_to_dict, run_to_dict

logger = logging.getLogger(__name__)


class ReportRunService:
    def __init__(self, agent_run_repository: AgentRunRepository | None = None):
        self.agent_runs = agent_run_repository or AgentRunRepository()

    async def create_report_run(
        self,
        session: AsyncSession,
        user_id: int,
        query: str,
        conversation_id: int | None = None,
        document_ids: list[int] | None = None,
        options: dict[str, Any] | None = None,
        client_request_id: str | None = None,
    ) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError('query is required')
        if document_ids is not None and len(document_ids) > 1000:
            raise ValueError('document_ids exceeds the supported limit')
        if options is not None and not isinstance(options, dict):
            raise ValueError('options must be a dictionary')
        request_snapshot = sanitize_summary({'document_ids': document_ids or [], 'options': options or {}})
        run = await self.agent_runs.create_agent_run(
            session=session, user_id=user_id, query=query.strip(),
            conversation_id=conversation_id, request_snapshot=request_snapshot,
            client_request_id=client_request_id,
        )
        # Server-default timestamps may still be expired after flush. Refresh
        # before serializing so async callers never trigger implicit IO.
        await session.refresh(run)
        if run.status == AgentRunStatus.PENDING.value:
            try:
                await set_run_status_projection_if_newer(
                    run_id=run.id, status=run.status, current_node='created', progress=0,
                    review_required=False, status_version=run.status_version,
                )
            except Exception as exc:
                logger.warning('Redis status projection write failed for report run %s: %s', run.id, exc)
        return run_to_dict(run)

    async def prepare_start(
        self,
        session: AsyncSession,
        run_id: int,
        new_status: str | AgentRunStatus = AgentRunStatus.STARTED,
        current_node: str | None = 'started',
        current_task_id: str | None = None,
    ) -> dict[str, Any]:
        if new_status not in (AgentRunStatus.STARTED, AgentRunStatus.RUNNING, 'STARTED', 'RUNNING'):
            raise ValueError('new_status must be STARTED or RUNNING')
        run = await self.agent_runs.compare_and_set_status(
            session=session, run_id=run_id, expected_status=AgentRunStatus.PENDING,
            new_status=new_status, current_node=current_node, current_task_id=current_task_id,
        )
        if run is None:
            raise ValueError('run is missing or is no longer PENDING')
        return run_to_dict(run)

    async def enqueue_start_report_run(
        self, session: AsyncSession, run_id: int, user_id: int
    ) -> dict[str, Any]:
        run = await self.agent_runs.get_by_id_for_user(session, run_id, user_id)
        if run is None:
            raise LookupError('agent run does not exist for this user')
        if run.status != AgentRunStatus.PENDING.value:
            raise ValueError('run is no longer pending')
        if run.current_task_id:
            return {'run': run_to_dict(run), 'task_id': run.current_task_id}

        from backend.worker.tasks_report import start_report_task

        task_id = str(uuid4())
        updated = await self.mark_task_enqueued(
            session=session, run_id=run_id, user_id=user_id, celery_task_id=task_id,
            expected_status=AgentRunStatus.PENDING,
        )
        start_report_task.apply_async(args=[run_id], task_id=task_id)
        try:
            await set_run_status_projection_if_newer(
                run_id=run_id, status=updated['status'],
                current_node=updated['current_node'] or 'created', progress=0,
                review_required=False, task_id=task_id,
                status_version=updated['status_version'],
            )
        except Exception as exc:
            logger.warning('Redis task id projection write failed for report run %s: %s', run_id, exc)
        return {'run': updated, 'task_id': task_id}

    async def enqueue_resume_report_run(
        self, session: AsyncSession, run_id: int, user_id: int
    ) -> dict[str, Any]:
        run = await self.agent_runs.get_by_id_for_user(session, run_id, user_id)
        if run is None:
            raise LookupError('agent run does not exist for this user')
        if run.status != AgentRunStatus.RESUME_QUEUED.value:
            raise ValueError('run is not queued for resume')

        from backend.worker.tasks_report import resume_report_task

        task_id = str(uuid4())
        updated = await self.mark_task_enqueued(
            session=session, run_id=run_id, user_id=user_id, celery_task_id=task_id,
            expected_status=AgentRunStatus.RESUME_QUEUED,
        )
        resume_report_task.apply_async(args=[run_id], task_id=task_id)
        try:
            await set_run_status_projection_if_newer(
                run_id=run_id, status=updated['status'],
                current_node=updated['current_node'] or 'human_review', progress=75,
                review_required=False, task_id=task_id,
                status_version=updated['status_version'],
            )
        except Exception as exc:
            logger.warning('Redis task id projection write failed for report run %s: %s', run_id, exc)
        return {'run': updated, 'task_id': task_id}

    async def prepare_resume(
        self,
        session: AsyncSession,
        run_id: int,
        user_id: int,
        review_id: int,
        action: str,
        feedback: str | None = None,
        edited_report: Any | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        from backend.services.human_review_service import HumanReviewService

        run = await self.agent_runs.get_by_id_for_user(session, run_id, user_id)
        if run is None:
            raise LookupError('agent run does not exist for this user')
        review_service = HumanReviewService()

        # Return the previously submitted review before checking the run state.
        # This makes retries safe even after a reject created a new pending review.
        if idempotency_key:
            existing_review = await review_service.reviews.get_review_for_user(
                session=session, review_id=review_id, run_id=run_id, user_id=user_id,
            )
            if (
                existing_review is not None
                and existing_review.idempotency_key == idempotency_key
                and existing_review.status != 'PENDING'
            ):
                return {
                    'run': run_to_dict(run),
                    'review': review_to_dict(existing_review),
                    'status': 'resume_queued',
                    'enqueue_required': False,
                }

        if run.status != AgentRunStatus.WAITING_HUMAN.value:
            raise ValueError('run is not waiting for human review')

        review = await review_service.submit_review_for_resume(
            session=session, run_id=run_id, user_id=user_id, review_id=review_id,
            action=action, feedback=feedback, edited_report=edited_report,
            idempotency_key=idempotency_key,
        )
        queued = await self.agent_runs.mark_resume_queued(
            session=session, run_id=run_id, user_id=user_id, current_review_id=review_id,
        )
        enqueue_required = queued is not None
        if queued is None:
            current = await self.agent_runs.get_by_id_for_user(session, run_id, user_id)
            if current is None or current.status not in {
                AgentRunStatus.RESUME_QUEUED.value, AgentRunStatus.RESUMED.value,
            }:
                raise ValueError('run could not be moved to RESUME_QUEUED')
            queued = current
        try:
            await set_run_status_projection_if_newer(
                run_id=queued.id, status=queued.status, current_node='human_review',
                progress=75, review_required=False, review_id=review_id,
                task_id=queued.current_task_id, status_version=queued.status_version,
            )
        except Exception as exc:
            logger.warning('Redis status projection write failed for report run %s: %s', run_id, exc)
        review_data = review if isinstance(review, dict) else review_to_dict(review)
        return {
            'run': run_to_dict(queued), 'review': review_data,
            'status': 'resume_queued', 'enqueue_required': enqueue_required,
        }

    async def mark_task_enqueued(
        self, session: AsyncSession, run_id: int, user_id: int, celery_task_id: str,
        expected_status: str | AgentRunStatus | None = None,
    ) -> dict[str, Any]:
        if not celery_task_id:
            raise ValueError('celery_task_id is required')
        run = await self.agent_runs.get_by_id_for_user(session, run_id, user_id)
        if run is None:
            raise LookupError('agent run does not exist for this user')
        try:
            await session.refresh(run)
        except (AttributeError, RuntimeError):
            pass
        if expected_status is not None:
            updated = await self.agent_runs.claim_task_id(
                session=session, run_id=run_id, user_id=user_id,
                task_id=celery_task_id, expected_status=expected_status,
            )
        else:
            updated = await self.agent_runs.update_status(
                session=session, run_id=run_id, status=run.status,
                current_task_id=celery_task_id,
            )
        if updated is None:
            current = await self.agent_runs.get_by_id_for_user(session, run_id, user_id)
            if current is not None and current.current_task_id:
                return run_to_dict(current)
            raise ValueError('run enqueue claim was lost')
        return run_to_dict(updated)
