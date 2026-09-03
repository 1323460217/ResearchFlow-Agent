from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent_run import AgentRun
from backend.models.research_report import ResearchReport


_FINAL_GENERATION_STATES = {"SUCCESS", "COMPLETED", "FINALIZED", "completed"}


class ReportRepository:
    async def get_report_by_run_id(
        self, session: AsyncSession, run_id: int
    ) -> ResearchReport | None:
        return await session.scalar(
            select(ResearchReport).where(ResearchReport.agent_run_id == run_id)
        )

    async def attach_report_to_run(
        self, session: AsyncSession, report_id: int, run_id: int
    ) -> ResearchReport | None:
        report = await session.get(ResearchReport, report_id)
        if report is None:
            return None
        if report.agent_run_id is not None and report.agent_run_id != run_id:
            raise ValueError("report is already attached to another run")
        if report.agent_run_id != run_id:
            report.agent_run_id = run_id
            report.updated_at = datetime.utcnow()
            await session.flush()
        return report

    async def create_or_update_report_for_run(
        self,
        session: AsyncSession,
        run_id: int,
        user_id: int,
        title: str,
        content: str | None = None,
        sections: Any | None = None,
        sources: Any | None = None,
        generation_status: str | None = None,
        review_action: str | None = None,
    ) -> ResearchReport:
        run = await session.scalar(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
        )
        if run is None:
            raise LookupError("agent run does not exist for this user")

        report = await self.get_report_by_run_id(session, run_id)
        if report is None:
            if content is None:
                raise ValueError("content is required when creating a report")
            status = "completed" if generation_status in _FINAL_GENERATION_STATES else "draft"
            report = ResearchReport(
                user_id=user_id,
                conversation_id=run.conversation_id,
                title=title,
                content=content,
                sections=sections,
                sources=sources,
                status=status,
                agent_run_id=run_id,
                generation_status=generation_status,
                report_revision=1,
                review_action=review_action,
                finalized_at=(datetime.utcnow() if status == "completed" else None),
            )
            session.add(report)
        else:
            if report.user_id != user_id:
                raise PermissionError("report does not belong to this user")
            same_final_report = (
                report.generation_status in _FINAL_GENERATION_STATES
                and generation_status in _FINAL_GENERATION_STATES
                and content is not None
                and report.content == content
                and (review_action is None or report.review_action == review_action)
            )
            if same_final_report:
                return report
            report.title = title
            if content is not None:
                report.content = content
            if sections is not None:
                report.sections = sections
            if sources is not None:
                report.sources = sources
            if generation_status is not None:
                report.generation_status = generation_status
            if review_action is not None:
                report.review_action = review_action
            if generation_status in _FINAL_GENERATION_STATES:
                report.status = "completed"
                report.finalized_at = datetime.utcnow()
            report.report_revision += 1
            report.updated_at = datetime.utcnow()
        await session.flush()
        return report
