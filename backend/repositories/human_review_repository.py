from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent_run import AgentRun
from backend.models.enums import HumanReviewAction, HumanReviewStatus
from backend.models.human_review import HumanReview


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


class HumanReviewRepository:
    async def create_pending_review(
        self,
        session: AsyncSession,
        run_id: int,
        review_round: int,
        draft_report_snapshot: Any,
        checkpoint_id: str | None = None,
    ) -> HumanReview:
        pending = await self.get_pending_review(session, run_id)
        if pending is not None:
            return pending
        same_round = await session.scalar(
            select(HumanReview).where(
                HumanReview.run_id == run_id,
                HumanReview.review_round == review_round,
            )
        )
        if same_round is not None:
            raise ValueError("review_round already exists for this run")
        review = HumanReview(
            run_id=run_id,
            review_round=review_round,
            status=HumanReviewStatus.PENDING.value,
            draft_report_snapshot=draft_report_snapshot,
            checkpoint_id=checkpoint_id,
            requested_at=datetime.utcnow(),
        )
        try:
            async with session.begin_nested():
                session.add(review)
                await session.flush()
        except IntegrityError:
            # A concurrent interrupt may have inserted the same round.  The
            # savepoint keeps the caller's transaction usable for the lookup.
            pending = await self.get_pending_review(session, run_id)
            if pending is not None:
                return pending
            raise
        return review

    async def get_pending_review(
        self, session: AsyncSession, run_id: int
    ) -> HumanReview | None:
        return await session.scalar(
            select(HumanReview)
            .where(
                HumanReview.run_id == run_id,
                HumanReview.status == HumanReviewStatus.PENDING.value,
            )
            .order_by(HumanReview.review_round.desc())
        )

    async def get_review_for_user(
        self,
        session: AsyncSession,
        review_id: int,
        run_id: int,
        user_id: int,
    ) -> HumanReview | None:
        return await session.scalar(
            select(HumanReview)
            .join(AgentRun, AgentRun.id == HumanReview.run_id)
            .where(
                HumanReview.id == review_id,
                HumanReview.run_id == run_id,
                AgentRun.user_id == user_id,
            )
        )

    async def submit_review(
        self,
        session: AsyncSession,
        run_id: int,
        review_id: int,
        reviewer_user_id: int,
        action: str | HumanReviewAction,
        feedback: str | None = None,
        edited_report: Any | None = None,
        idempotency_key: str | None = None,
    ) -> HumanReview | None:
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        existing = await session.scalar(
            select(HumanReview).where(HumanReview.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.run_id != run_id or existing.id != review_id:
                raise ValueError("idempotency_key belongs to another review")
            return existing

        review = await session.scalar(
            select(HumanReview).where(
                HumanReview.id == review_id,
                HumanReview.run_id == run_id,
            ).with_for_update()
        )
        if review is None:
            return None
        action_value = _value(action)
        if review.status != HumanReviewStatus.PENDING.value:
            if review.action != action_value:
                raise ValueError("review already processed with another action")
            return review

        if action_value == HumanReviewAction.APPROVE.value:
            status = HumanReviewStatus.APPROVED.value
        elif action_value == HumanReviewAction.EDIT.value:
            if edited_report is None:
                raise ValueError("edited_report is required for edit")
            status = HumanReviewStatus.EDITED.value
        elif action_value == HumanReviewAction.REJECT.value:
            if not feedback:
                raise ValueError("feedback is required for reject")
            status = HumanReviewStatus.REJECTED.value
        else:
            raise ValueError("action must be approve, edit, or reject")

        now = datetime.utcnow()
        review.status = status
        review.action = action_value
        review.feedback = feedback
        review.edited_report = edited_report
        review.reviewer_user_id = reviewer_user_id
        review.idempotency_key = idempotency_key
        review.answered_at = now
        review.updated_at = now
        await session.flush()
        return review

    async def list_reviews_for_run(
        self,
        session: AsyncSession,
        run_id: int,
        offset: int = 0,
        limit: int = 100,
    ) -> list[HumanReview]:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be non-negative and limit must be positive")
        result = await session.execute(
            select(HumanReview)
            .where(HumanReview.run_id == run_id)
            .order_by(HumanReview.review_round.asc(), HumanReview.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())
