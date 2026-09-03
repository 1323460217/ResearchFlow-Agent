"""add agent run core tables

Revision ID: c4e9a7b12d6f
Revises: b76ce1774f12
Create Date: 2026-09-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c4e9a7b12d6f"
down_revision: Union[str, None] = "b76ce1774f12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="PENDING", nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("request_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("current_node", sa.String(length=100), nullable=True),
        sa.Column("iteration_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_iterations", sa.Integer(), server_default="3", nullable=False),
        sa.Column("human_review_round", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_human_reviews", sa.Integer(), server_default="3", nullable=False),
        sa.Column("current_task_id", sa.String(length=255), nullable=True),
        sa.Column("client_request_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("status_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", name="uq_agent_runs_thread_id"),
    )
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_runs_user_created_at", "agent_runs", ["user_id", "created_at"])
    op.create_index("ix_agent_runs_user_status", "agent_runs", ["user_id", "status"])
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    # PostgreSQL permits multiple NULL values in this unique index, as required
    # for an optional client request id.
    op.create_index(
        "uq_agent_runs_user_client_request_id",
        "agent_runs",
        ["user_id", "client_request_id"],
        unique=True,
    )

    op.create_table(
        "agent_run_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="STARTED", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("checkpoint_id", sa.String(length=255), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", "attempt", name="uq_agent_run_steps_run_sequence_attempt"),
    )
    op.create_index("ix_agent_run_steps_run_sequence", "agent_run_steps", ["run_id", "sequence"])
    op.create_index("ix_agent_run_steps_run_node_name", "agent_run_steps", ["run_id", "node_name"])
    op.create_index("ix_agent_run_steps_run_status", "agent_run_steps", ["run_id", "status"])

    op.create_table(
        "human_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="PENDING", nullable=False),
        sa.Column("action", sa.String(length=20), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("edited_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("draft_report_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("requested_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
        sa.Column("resume_task_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("checkpoint_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "review_round", name="uq_human_reviews_run_round"),
        sa.UniqueConstraint("idempotency_key", name="uq_human_reviews_idempotency_key"),
    )
    op.create_index("ix_human_reviews_run_status", "human_reviews", ["run_id", "status"])
    op.create_index("ix_human_reviews_reviewer_created_at", "human_reviews", ["reviewer_user_id", "created_at"])
    op.create_index(
        "uq_human_reviews_run_pending",
        "human_reviews",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=255), nullable=True),
        sa.Column("chunk_id", sa.Integer(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("locator", sa.String(length=255), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("citation_key", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["report_id"], ["research_reports.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_run_id", "evidence", ["run_id"])
    op.create_index("ix_evidence_report_id", "evidence", ["report_id"])
    op.create_index("ix_evidence_document_page", "evidence", ["document_id", "page_number"])
    op.create_index("ix_evidence_content_hash", "evidence", ["content_hash"])
    op.create_index(
        "uq_evidence_run_content_locator",
        "evidence",
        ["run_id", "content_hash", "locator"],
        unique=True,
    )

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=True),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="STARTED", nullable=False),
        sa.Column("request_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["agent_run_steps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_calls_run_started_at", "tool_calls", ["run_id", "started_at"])
    op.create_index("ix_tool_calls_run_tool_name", "tool_calls", ["run_id", "tool_name"])
    op.create_index("ix_tool_calls_run_status", "tool_calls", ["run_id", "status"])
    op.create_index("ix_tool_calls_step_id", "tool_calls", ["step_id"])
    op.create_index(
        "uq_tool_calls_run_idempotency_key",
        "tool_calls",
        ["run_id", "idempotency_key"],
        unique=True,
    )

    op.add_column(
        "research_reports",
        sa.Column("agent_run_id", sa.Integer(), nullable=True),
    )
    op.add_column("research_reports", sa.Column("generation_status", sa.String(length=30), nullable=True))
    op.add_column(
        "research_reports",
        sa.Column("report_revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("research_reports", sa.Column("review_action", sa.String(length=20), nullable=True))
    op.add_column("research_reports", sa.Column("finalized_at", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        "fk_research_reports_agent_run_id",
        "research_reports",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_research_reports_agent_run_id",
        "research_reports",
        ["agent_run_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_research_reports_agent_run_id", "research_reports", type_="unique")
    op.drop_constraint("fk_research_reports_agent_run_id", "research_reports", type_="foreignkey")
    op.drop_column("research_reports", "finalized_at")
    op.drop_column("research_reports", "review_action")
    op.drop_column("research_reports", "report_revision")
    op.drop_column("research_reports", "generation_status")
    op.drop_column("research_reports", "agent_run_id")

    op.drop_index("uq_tool_calls_run_idempotency_key", table_name="tool_calls")
    op.drop_index("ix_tool_calls_step_id", table_name="tool_calls")
    op.drop_index("ix_tool_calls_run_status", table_name="tool_calls")
    op.drop_index("ix_tool_calls_run_tool_name", table_name="tool_calls")
    op.drop_index("ix_tool_calls_run_started_at", table_name="tool_calls")
    op.drop_table("tool_calls")

    op.drop_index("uq_evidence_run_content_locator", table_name="evidence")
    op.drop_index("ix_evidence_content_hash", table_name="evidence")
    op.drop_index("ix_evidence_document_page", table_name="evidence")
    op.drop_index("ix_evidence_report_id", table_name="evidence")
    op.drop_index("ix_evidence_run_id", table_name="evidence")
    op.drop_table("evidence")

    op.drop_index("uq_human_reviews_run_pending", table_name="human_reviews")
    op.drop_index("ix_human_reviews_reviewer_created_at", table_name="human_reviews")
    op.drop_index("ix_human_reviews_run_status", table_name="human_reviews")
    op.drop_table("human_reviews")

    op.drop_index("ix_agent_run_steps_run_status", table_name="agent_run_steps")
    op.drop_index("ix_agent_run_steps_run_node_name", table_name="agent_run_steps")
    op.drop_index("ix_agent_run_steps_run_sequence", table_name="agent_run_steps")
    op.drop_table("agent_run_steps")

    op.drop_index("uq_agent_runs_user_client_request_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_created_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_table("agent_runs")
