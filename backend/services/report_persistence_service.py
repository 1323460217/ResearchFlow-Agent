from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import ToolCallStatus
from backend.repositories.agent_run_repository import AgentRunRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.report_repository import ReportRepository
from backend.repositories.tool_call_repository import ToolCallRepository
from backend.services._utils import evidence_to_dict, report_to_dict, tool_call_to_dict


class ReportPersistenceService:
    def __init__(
        self,
        agent_run_repository: AgentRunRepository | None = None,
        report_repository: ReportRepository | None = None,
        evidence_repository: EvidenceRepository | None = None,
        tool_call_repository: ToolCallRepository | None = None,
    ):
        self.agent_runs = agent_run_repository or AgentRunRepository()
        self.reports = report_repository or ReportRepository()
        self.evidence = evidence_repository or EvidenceRepository()
        self.tool_calls = tool_call_repository or ToolCallRepository()

    async def save_final_report_for_run(
        self,
        session: AsyncSession,
        run_id: int,
        user_id: int,
        title: str,
        content: str,
        sections: Any | None = None,
        sources: Any | None = None,
        evidence_items: list[dict[str, Any]] | None = None,
        generation_status: str = "SUCCESS",
        review_action: str | None = None,
    ) -> dict[str, Any]:
        report = await self.reports.create_or_update_report_for_run(
            session=session,
            run_id=run_id,
            user_id=user_id,
            title=title,
            content=content,
            sections=sections,
            sources=sources,
            generation_status=generation_status,
            review_action=review_action,
        )
        evidence = await self.evidence.bulk_create_evidence(
            session=session,
            run_id=run_id,
            report_id=report.id,
            evidence_items=evidence_items or [],
        )
        return {
            "report": report_to_dict(report),
            "evidence": [evidence_to_dict(item) for item in evidence],
        }

    async def save_tool_call(
        self,
        session: AsyncSession,
        run_id: int,
        tool_name: str,
        step_id: int | None = None,
        provider: str | None = None,
        request_summary: Any | None = None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        status: str | ToolCallStatus = ToolCallStatus.STARTED,
        response_summary: Any | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retry_count: int = 0,
    ) -> dict[str, Any]:
        call = await self.tool_calls.create_tool_call_started(
            session=session,
            run_id=run_id,
            step_id=step_id,
            tool_name=tool_name,
            provider=provider,
            request_summary=request_summary,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )
        status_value = status.value if hasattr(status, "value") else status
        if status_value == ToolCallStatus.SUCCESS.value:
            call = await self.tool_calls.mark_tool_call_success(
                session=session,
                tool_call_id=call.id,
                response_summary=response_summary,
            )
        elif status_value == ToolCallStatus.FAILURE.value:
            call = await self.tool_calls.mark_tool_call_failure(
                session=session,
                tool_call_id=call.id,
                error_code=error_code,
                error_message=error_message or "tool call failed",
                retry_count=retry_count,
            )
        elif status_value != ToolCallStatus.STARTED.value:
            raise ValueError("status must be STARTED, SUCCESS, or FAILURE")
        return tool_call_to_dict(call)

    async def get_report_with_evidence(
        self, session: AsyncSession, run_id: int, user_id: int
    ) -> dict[str, Any]:
        if await self.agent_runs.get_by_id_for_user(session, run_id, user_id) is None:
            raise LookupError("agent run does not exist for this user")
        report = await self.reports.get_report_by_run_id(session, run_id)
        if report is None:
            raise LookupError("report does not exist for this run")
        evidence = await self.evidence.list_evidence_for_report(session, report.id)
        return {
            "report": report_to_dict(report),
            "evidence": [evidence_to_dict(item) for item in evidence],
        }
