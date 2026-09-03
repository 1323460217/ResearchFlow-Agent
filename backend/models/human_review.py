from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base
from backend.models.enums import HumanReviewStatus


class HumanReview(Base):
    __tablename__ = "human_reviews"
    __table_args__ = (
        Index("ix_human_reviews_run_status", "run_id", "status"),
        Index("ix_human_reviews_reviewer_created_at", "reviewer_user_id", "created_at"),
        Index(
            "uq_human_reviews_run_pending",
            "run_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        UniqueConstraint("run_id", "review_round", name="uq_human_reviews_run_round"),
        UniqueConstraint("idempotency_key", name="uq_human_reviews_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    review_round: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=HumanReviewStatus.PENDING.value, server_default=HumanReviewStatus.PENDING.value, nullable=False
    )
    action: Mapped[Optional[str]] = mapped_column(String(20))
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    edited_report: Mapped[Optional[Any]] = mapped_column(JSONB)
    draft_report_snapshot: Mapped[Optional[Any]] = mapped_column(JSONB)
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    reviewer_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resume_task_id: Mapped[Optional[str]] = mapped_column(String(255))
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255))
    checkpoint_id: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    run = relationship("AgentRun", back_populates="human_reviews")
    reviewer = relationship("User")
