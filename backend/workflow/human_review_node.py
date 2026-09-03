"""LangGraph human-review node used by the durable report-run workflow."""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from backend.workflow.state import ResearchState

_MAX_FEEDBACK_CHARS = 4000
_MAX_CLAIM_CHARS = 500


def _as_report_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("content", "final_report", "report", "answer", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    return None


def extract_draft_report_snapshot(state: ResearchState) -> dict[str, Any]:
    """Build a bounded review payload without copying source documents."""

    report = state.get("final_report") or ""
    findings = [
        str(item)[:_MAX_CLAIM_CHARS]
        for item in state.get("key_findings", [])[:8]
    ]
    headings = [
        str(section.heading)[:200]
        for section in state.get("report_sections", [])[:12]
        if getattr(section, "heading", None)
    ]
    return {
        "title": (state.get("query") or state.get("research_topic") or "")[:200],
        "summary": report[:1200],
        "headings": headings,
        "key_claims": findings,
        "quality_score": state.get("quality_score"),
        "review_round": state.get("review_round", 1),
    }


def _review_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("human review response must be an object")
    action = value.get("action")
    if action not in {"approve", "edit", "reject"}:
        raise ValueError("human review action must be approve, edit, or reject")
    feedback = value.get("feedback")
    edited_report = value.get("edited_report")
    if action == "edit" and edited_report is None:
        raise ValueError("edited_report is required for edit")
    if action == "reject" and not feedback:
        raise ValueError("feedback is required for reject")
    return {
        "action": action,
        "feedback": str(feedback)[:_MAX_FEEDBACK_CHARS] if feedback is not None else None,
        "edited_report": edited_report,
    }


def human_review_node(state: ResearchState) -> dict[str, Any]:
    """Pause after Reporter and accept a small approve/edit/reject decision."""

    payload = {
        "type": "human_review",
        "draft_report": extract_draft_report_snapshot(state),
        "question": (state.get("query") or state.get("research_topic") or "")[:1000],
        "options": ["approve", "edit", "reject"],
        "review_round": state.get("review_round", 1),
    }
    result = _review_payload(interrupt(payload))
    edited_report = result["edited_report"]
    report_text = _as_report_text(edited_report)
    return {
        "human_review_action": result["action"],
        "human_feedback": result["feedback"],
        "edited_report": edited_report,
        "final_report": report_text if result["action"] == "edit" else state.get("final_report"),
        "workflow_status": "running",
    }


__all__ = ["extract_draft_report_snapshot", "human_review_node"]
