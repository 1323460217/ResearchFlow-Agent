"""Small adapters between durable report runs and the existing workflow state."""

from __future__ import annotations

from typing import Any

from backend.api.serialization import sanitize_for_json


def build_report_run_input(run: Any) -> dict[str, Any]:
    request_snapshot = getattr(run, "request_snapshot", None)
    snapshot = request_snapshot if isinstance(request_snapshot, dict) else {}
    options = snapshot.get("options") if isinstance(snapshot.get("options"), dict) else {}
    return {
        "run_id": run.id,
        "thread_id": str(getattr(run, "thread_id", None) or run.id),
        "user_id": run.user_id,
        "query": run.query,
        "research_topic": run.query,
        "conversation_id": getattr(run, "conversation_id", None),
        "request_snapshot": sanitize_for_json(snapshot),
        "max_iterations": getattr(run, "max_iterations", 3),
        "max_human_reviews": getattr(run, "max_human_reviews", 3),
        "review_round": getattr(run, "human_review_round", 0) + 1,
        "iteration_count": getattr(run, "iteration_count", 0),
        "kb_collections": options.get("kb_collections", []),
        "model_override": options.get("model_override"),
        "use_react": bool(options.get("use_react", True)),
        "workflow_status": "running",
        "agent_trace": [],
        "messages": [],
    }


def extract_interrupt_payload(chunks: list[Any]) -> dict[str, Any] | None:
    for chunk in chunks:
        if not isinstance(chunk, dict) or "__interrupt__" not in chunk:
            continue
        interrupts = chunk["__interrupt__"]
        if not interrupts:
            continue
        item = interrupts[0]
        value = getattr(item, "value", item)
        return value if isinstance(value, dict) else {"value": value}
    return None


def extract_final_report_payload(output: Any) -> dict[str, Any]:
    """Normalize cumulative LangGraph state or a node output for persistence."""

    state = output if isinstance(output, dict) else {}
    report = state.get("final_report") or state.get("report") or state.get("answer")
    if isinstance(report, dict):
        report = report.get("content") or report.get("text") or report.get("answer")
    source_summaries = []
    for source in state.get("retrieved_docs", []) or []:
        item = sanitize_for_json(source)
        if isinstance(item, dict):
            source_summaries.append({
                key: item.get(key)
                for key in ("doc_id", "title", "source", "url", "relevance_score")
                if item.get(key) is not None
            })
    return {
        "content": str(report or ""),
        "sections": sanitize_for_json(state.get("report_sections")) if state.get("report_sections") else None,
        "sources": source_summaries or None,
        "evidence_items": sanitize_for_json(state.get("evidence_items", [])),
        "tool_calls": sanitize_for_json(state.get("tool_calls", [])),
        "review_action": state.get("human_review_action"),
        "status": state.get("workflow_status"),
        "iteration_count": state.get("iteration_count"),
    }


def review_snapshot_from_interrupt(payload: dict[str, Any]) -> dict[str, Any]:
    draft = payload.get("draft_report")
    if isinstance(draft, dict):
        return sanitize_for_json(draft)
    return {"summary": str(draft or "")[:1200]}


__all__ = [
    "build_report_run_input",
    "extract_final_report_payload",
    "extract_interrupt_payload",
    "review_snapshot_from_interrupt",
]
