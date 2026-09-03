from typing import Any

from backend.models.agent_run import AgentRun
from backend.models.agent_run_step import AgentRunStep
from backend.models.evidence import Evidence
from backend.models.human_review import HumanReview
from backend.models.research_report import ResearchReport
from backend.models.tool_call import ToolCall


def run_to_dict(run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "user_id": run.user_id,
        "conversation_id": run.conversation_id,
        "thread_id": run.thread_id,
        "status": run.status,
        "query": run.query,
        "current_node": run.current_node,
        "iteration_count": run.iteration_count,
        "max_iterations": run.max_iterations,
        "human_review_round": run.human_review_round,
        "max_human_reviews": run.max_human_reviews,
        "current_task_id": run.current_task_id,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "status_version": run.status_version,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "failed_at": run.failed_at,
        "updated_at": run.updated_at,
    }


def step_to_dict(step: AgentRunStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "run_id": step.run_id,
        "sequence": step.sequence,
        "node_name": step.node_name,
        "status": step.status,
        "attempt": step.attempt,
        "celery_task_id": step.celery_task_id,
        "started_at": step.started_at,
        "ended_at": step.ended_at,
        "duration_ms": step.duration_ms,
        "input_summary": step.input_summary,
        "output_summary": step.output_summary,
        "checkpoint_id": step.checkpoint_id,
        "trace_id": step.trace_id,
        "error_code": step.error_code,
        "error_message": step.error_message,
    }


def review_to_dict(review: HumanReview) -> dict[str, Any]:
    return {
        "id": review.id,
        "run_id": review.run_id,
        "review_round": review.review_round,
        "status": review.status,
        "action": review.action,
        "feedback": review.feedback,
        "edited_report": review.edited_report,
        "requested_at": review.requested_at,
        "answered_at": review.answered_at,
        "reviewer_user_id": review.reviewer_user_id,
        "resume_task_id": review.resume_task_id,
        "checkpoint_id": review.checkpoint_id,
    }


def report_to_dict(report: ResearchReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "user_id": report.user_id,
        "conversation_id": report.conversation_id,
        "agent_run_id": report.agent_run_id,
        "title": report.title,
        "content": report.content,
        "sections": report.sections,
        "sources": report.sources,
        "status": report.status,
        "generation_status": report.generation_status,
        "report_revision": report.report_revision,
        "review_action": report.review_action,
        "finalized_at": report.finalized_at,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def evidence_to_dict(evidence: Evidence) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "run_id": evidence.run_id,
        "report_id": evidence.report_id,
        "document_id": evidence.document_id,
        "source_type": evidence.source_type,
        "source_uri": evidence.source_uri,
        "title": evidence.title,
        "page_number": evidence.page_number,
        "section": evidence.section,
        "chunk_id": evidence.chunk_id,
        "quote": evidence.quote,
        "locator": evidence.locator,
        "relevance_score": evidence.relevance_score,
        "citation_key": evidence.citation_key,
        "metadata": evidence.metadata_,
        "content_hash": evidence.content_hash,
        "created_at": evidence.created_at,
    }


def tool_call_to_dict(call: ToolCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "run_id": call.run_id,
        "step_id": call.step_id,
        "tool_name": call.tool_name,
        "provider": call.provider,
        "status": call.status,
        "request_summary": call.request_summary,
        "response_summary": call.response_summary,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "duration_ms": call.duration_ms,
        "retry_count": call.retry_count,
        "error_code": call.error_code,
        "error_message": call.error_message,
        "trace_id": call.trace_id,
    }
