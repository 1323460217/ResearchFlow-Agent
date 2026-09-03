from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base
from backend.models.enums import AgentRunStepStatus


class AgentRunStep(Base):
    __tablename__ = "agent_run_steps"
    __table_args__ = (
        Index("ix_agent_run_steps_run_sequence", "run_id", "sequence"),
        Index("ix_agent_run_steps_run_node_name", "run_id", "node_name"),
        Index("ix_agent_run_steps_run_status", "run_id", "status"),
        UniqueConstraint(
            "run_id", "sequence", "attempt",
            name="uq_agent_run_steps_run_sequence_attempt",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=AgentRunStepStatus.STARTED.value, server_default=AgentRunStepStatus.STARTED.value, nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    input_summary: Mapped[Optional[Any]] = mapped_column(JSONB)
    output_summary: Mapped[Optional[Any]] = mapped_column(JSONB)
    checkpoint_id: Mapped[Optional[str]] = mapped_column(String(255))
    trace_id: Mapped[Optional[str]] = mapped_column(String(255))
    error_code: Mapped[Optional[str]] = mapped_column(String(100))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    run = relationship("AgentRun", back_populates="steps")
    tool_calls = relationship("ToolCall", back_populates="step", passive_deletes=True)
