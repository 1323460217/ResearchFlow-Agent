import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import AgentRunStatus, HumanReviewAction
from backend.memory.redis_task_status import set_run_status_projection_if_newer
from backend.repositories.agent_run_repository import AgentRunRepository
from backend.repositories.human_review_repository import HumanReviewRepository
from backend.services._utils import review_to_dict, run_to_dict

logger = logging.getLogger(__name__)


class HumanReviewService:
    def __init__(
        self,
        agent_run_repository: AgentRunRepository | None = None,
        human_review_repository: HumanReviewRepository | None = None,
    ):
        self.agent_runs = agent_run_repository or AgentRunRepository()
        self.reviews = human_review_repository or HumanReviewRepository()

    async def create_pending_review_for_run(
        self,
        session: AsyncSession,
        run_id: int,
        review_round: int,
        draft_report_snapshot: Any,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        if review_round < 1:
            raise ValueError("review_round must be positive")
        run = await self.agent_runs.get_by_id(session, run_id)
        if run is None:
            raise LookupError("agent run does not exist")
        if review_round > run.max_human_reviews:
            raise ValueError("review_round exceeds max_human_reviews")
        review = await self.reviews.create_pending_review(
            session=session,
            run_id=run_id,
            review_round=review_round,
            draft_report_snapshot=draft_report_snapshot,
            checkpoint_id=checkpoint_id,
        )
        run.human_review_round = max(run.human_review_round, review_round)
        if run.status != AgentRunStatus.WAITING_HUMAN.value:
            updated_run = await self.agent_runs.compare_and_set_status(
                session=session,
                run_id=run_id,
                expected_status=run.status,
                new_status=AgentRunStatus.WAITING_HUMAN,
                current_node="human_review",
            )
            if updated_run is None:
                updated_run = await self.agent_runs.get_by_id(session, run_id)
                if updated_run is None or updated_run.status != AgentRunStatus.WAITING_HUMAN.value:
                    raise ValueError("run could not be moved to WAITING_HUMAN")
        else:
            await session.flush()
            updated_run = run
        try:
            await set_run_status_projection_if_newer(
                run_id=updated_run.id,
                status=updated_run.status,
                current_node="human_review",
                progress=70,
                review_required=True,
                review_id=review.id,
                task_id=updated_run.current_task_id,
                status_version=updated_run.status_version,
            )
        except Exception as exc:
            logger.warning("Redis status projection write failed for report run %s: %s", run_id, exc)
        return {"run": run_to_dict(updated_run), "review": review_to_dict(review)}

    async def get_pending_review_for_user(
        self, session: AsyncSession, run_id: int, user_id: int
    ) -> dict[str, Any] | None:
        run = await self.agent_runs.get_by_id_for_user(session, run_id, user_id)
        if run is None:
            raise LookupError("agent run does not exist for this user")
        review = await self.reviews.get_pending_review(session, run_id)
        return review_to_dict(review) if review is not None else None

    async def submit_review_for_resume(
        self,
        session: AsyncSession,
        run_id: int,
        user_id: int,
        review_id: int,
        action: str | HumanReviewAction,
        feedback: str | None = None,
        edited_report: Any | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        run = await self.agent_runs.get_by_id_for_user(session, run_id, user_id)
        if run is None:
            raise LookupError("agent run does not exist for this user")
        if run.status != AgentRunStatus.WAITING_HUMAN.value:
            raise ValueError("run is not waiting for human review")
        action_value = action.value if hasattr(action, "value") else action
        if action_value == HumanReviewAction.EDIT.value and edited_report is None:
            raise ValueError("edited_report is required for edit")
        if action_value == HumanReviewAction.REJECT.value and not feedback:
            raise ValueError("feedback is required for reject")
        if action_value not in {
            HumanReviewAction.APPROVE.value,
            HumanReviewAction.EDIT.value,
            HumanReviewAction.REJECT.value,
        }:
            raise ValueError("action must be approve, edit, or reject")
        review = await self.reviews.get_review_for_user(
            session=session, review_id=review_id, run_id=run_id, user_id=user_id
        )
        if review is None:
            raise LookupError("review does not exist for this user")
        submitted = await self.reviews.submit_review(
            session=session,
            run_id=run_id,
            review_id=review_id,
            reviewer_user_id=user_id,
            action=action_value,
            feedback=feedback,
            edited_report=edited_report,
            idempotency_key=idempotency_key,
        )
        if submitted is None:
            raise LookupError("review does not exist")
        return review_to_dict(submitted)
