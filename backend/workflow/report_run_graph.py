"""Report-runs-specific LangGraph graph with durable human review."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.workflow.agents.analyzer import analyzer_node
from backend.workflow.agents.critic import critic_node
from backend.workflow.agents.planner import planner_node
from backend.workflow.agents.reporter import _parse_report_sections, reporter_node
from backend.workflow.agents.retriever import retriever_node
from backend.workflow.edges import (
    ANALYZER,
    CRITIC,
    PLANNER,
    REPORTER,
    RETRIEVER,
    should_continue,
)
from backend.workflow.human_review_node import human_review_node
from backend.workflow.state import ResearchState

HUMAN_REVIEW = "human_review"
FINALIZE = "finalize"
REVIEW_LIMIT = "human_review_limit"
REWRITE_REPORTER = "rewrite_reporter"


def _edited_report_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("content", "final_report", "report", "answer", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    return None


def finalize_report_node(state: ResearchState) -> dict[str, Any]:
    """Apply an optional human edit and mark the report workflow complete."""

    report = _edited_report_text(state.get("edited_report")) or state.get("final_report") or ""
    return {
        "final_report": report,
        "report_sections": _parse_report_sections(report),
        "workflow_status": "completed",
    }


def prepare_reporter_revision_node(state: ResearchState) -> dict[str, Any]:
    """Feed bounded reject feedback back through the existing Reporter node."""

    feedback = (state.get("human_feedback") or "")[:4000]
    analysis = state.get("analysis_result") or ""
    feedback_block = f"\n\n人工审核修改要求（仅作为重写约束）:\n{feedback}"
    return {
        "analysis_result": f"{analysis[:12000]}{feedback_block}",
        "revision_feedback": feedback,
        "workflow_status": "running",
        "review_round": state.get("review_round", 1) + 1,
    }


def human_review_limit_node(state: ResearchState) -> dict[str, Any]:
    del state
    return {"workflow_status": "failed", "error_message": "maximum human review rounds exceeded"}


def route_after_human_review(state: ResearchState) -> str:
    """Route a resumed review without allowing an unbounded reject loop."""

    action = state.get("human_review_action")
    if action in {"approve", "edit"}:
        return FINALIZE
    if action == "reject":
        if state.get("review_round", 1) >= state.get("max_human_reviews", 3):
            return REVIEW_LIMIT
        return REWRITE_REPORTER
    return REVIEW_LIMIT


def build_report_run_graph(checkpointer=None):
    """Build and compile the report-runs graph without changing the chat graph."""

    builder = StateGraph(ResearchState)
    builder.add_node(PLANNER, planner_node)
    builder.add_node(RETRIEVER, retriever_node)
    builder.add_node(ANALYZER, analyzer_node)
    builder.add_node(CRITIC, critic_node)
    builder.add_node(REPORTER, reporter_node)
    builder.add_node(HUMAN_REVIEW, human_review_node)
    builder.add_node(FINALIZE, finalize_report_node)
    builder.add_node(REWRITE_REPORTER, prepare_reporter_revision_node)
    builder.add_node(REVIEW_LIMIT, human_review_limit_node)

    builder.add_edge(START, PLANNER)
    builder.add_edge(PLANNER, RETRIEVER)
    builder.add_edge(RETRIEVER, ANALYZER)
    builder.add_edge(ANALYZER, CRITIC)
    builder.add_conditional_edges(CRITIC, should_continue)
    builder.add_edge(REPORTER, HUMAN_REVIEW)
    builder.add_conditional_edges(
        HUMAN_REVIEW,
        route_after_human_review,
        {FINALIZE: FINALIZE, REWRITE_REPORTER: REWRITE_REPORTER, REVIEW_LIMIT: REVIEW_LIMIT},
    )
    builder.add_edge(REWRITE_REPORTER, REPORTER)
    builder.add_edge(FINALIZE, END)
    builder.add_edge(REVIEW_LIMIT, END)
    return builder.compile(checkpointer=checkpointer)


__all__ = [
    "FINALIZE",
    "HUMAN_REVIEW",
    "REWRITE_REPORTER",
    "build_report_run_graph",
    "route_after_human_review",
]
