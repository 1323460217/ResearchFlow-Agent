from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base


class ResearchReport(Base):
    __tablename__ = "research_reports"
    __table_args__ = (
        UniqueConstraint("agent_run_id", name="uq_research_reports_agent_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sections: Mapped[Optional[Any]] = mapped_column(JSONB)
    sources: Mapped[Optional[Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    agent_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    generation_status: Mapped[Optional[str]] = mapped_column(String(30))
    report_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    review_action: Mapped[Optional[str]] = mapped_column(String(20))
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="research_reports")
    agent_run = relationship("AgentRun", back_populates="research_report")
