from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_run_id", "run_id"),
        Index("ix_evidence_report_id", "report_id"),
        Index("ix_evidence_document_page", "document_id", "page_number"),
        Index("ix_evidence_content_hash", "content_hash"),
        UniqueConstraint(
            "run_id", "content_hash", "locator",
            name="uq_evidence_run_content_locator",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("research_reports.id", ondelete="SET NULL")
    )
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_uri: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(String(500))
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String(255))
    chunk_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL")
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[Optional[str]] = mapped_column(String(255))
    relevance_score: Mapped[Optional[float]] = mapped_column(Float)
    citation_key: Mapped[Optional[str]] = mapped_column(String(255))
    metadata_: Mapped[Optional[Any]] = mapped_column("metadata", JSONB)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    run = relationship("AgentRun", back_populates="evidence")
    report = relationship("ResearchReport")
    document = relationship("Document")
    chunk = relationship("DocumentChunk")
