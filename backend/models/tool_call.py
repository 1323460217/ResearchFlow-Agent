from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base
from backend.models.enums import ToolCallStatus


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tool_calls_run_started_at", "run_id", "started_at"),
        Index("ix_tool_calls_run_tool_name", "run_id", "tool_name"),
        Index("ix_tool_calls_run_status", "run_id", "status"),
        Index("ix_tool_calls_step_id", "step_id"),
        UniqueConstraint(
            "run_id", "idempotency_key",
            name="uq_tool_calls_run_idempotency_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("agent_run_steps.id", ondelete="SET NULL")
    )
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(30), default=ToolCallStatus.STARTED.value, server_default=ToolCallStatus.STARTED.value, nullable=False
    )
    request_summary: Mapped[Optional[Any]] = mapped_column(JSONB)
    response_summary: Mapped[Optional[Any]] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(100))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255))
    trace_id: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    run = relationship("AgentRun", back_populates="tool_calls")
    step = relationship("AgentRunStep", back_populates="tool_calls")
