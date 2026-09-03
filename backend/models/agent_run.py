from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base
from backend.models.enums import AgentRunStatus


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_user_created_at", "user_id", "created_at"),
        Index("ix_agent_runs_user_status", "user_id", "status"),
        Index("ix_agent_runs_conversation_id", "conversation_id"),
        Index("uq_agent_runs_user_client_request_id", "user_id", "client_request_id", unique=True),
        UniqueConstraint("thread_id", name="uq_agent_runs_thread_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=AgentRunStatus.PENDING.value, server_default=AgentRunStatus.PENDING.value, nullable=False
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    request_snapshot: Mapped[Optional[Any]] = mapped_column(JSONB)
    current_node: Mapped[Optional[str]] = mapped_column(String(100))
    iteration_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    human_review_round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_human_reviews: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    current_task_id: Mapped[Optional[str]] = mapped_column(String(255))
    client_request_id: Mapped[Optional[str]] = mapped_column(String(255))
    error_code: Mapped[Optional[str]] = mapped_column(String(100))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    status_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User")
    conversation = relationship("Conversation")
    steps = relationship("AgentRunStep", back_populates="run", passive_deletes=True)
    human_reviews = relationship("HumanReview", back_populates="run", passive_deletes=True)
    evidence = relationship("Evidence", back_populates="run", passive_deletes=True)
    tool_calls = relationship("ToolCall", back_populates="run", passive_deletes=True)
    research_report = relationship("ResearchReport", back_populates="agent_run", uselist=False)
