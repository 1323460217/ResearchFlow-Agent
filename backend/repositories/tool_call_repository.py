from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import ToolCallStatus
from backend.models.tool_call import ToolCall


_SENSITIVE_PARTS = (
    "token",
    "password",
    "access_key",
    "api_key",
    "secret",
    "authorization",
)


def sanitize_summary(value: Any) -> Any:
    """Redact sensitive keys before a summary reaches JSONB storage."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(part in str(key).lower() for part in _SENSITIVE_PARTS)
            else sanitize_summary(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_summary(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_summary(item) for item in value]
    return value


def _duration_ms(started_at: datetime | None, ended_at: datetime) -> int:
    if started_at is None:
        return 0
    return max(0, int((ended_at - started_at).total_seconds() * 1000))


class ToolCallRepository:
    async def create_tool_call_started(
        self,
        session: AsyncSession,
        run_id: int,
        tool_name: str,
        step_id: int | None = None,
        provider: str | None = None,
        request_summary: Any | None = None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> ToolCall:
        if idempotency_key is not None:
            existing = await session.scalar(
                select(ToolCall).where(
                    ToolCall.run_id == run_id,
                    ToolCall.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return existing
        call = ToolCall(
            run_id=run_id,
            step_id=step_id,
            tool_name=tool_name,
            provider=provider,
            status=ToolCallStatus.STARTED.value,
            request_summary=sanitize_summary(request_summary),
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            started_at=datetime.utcnow(),
        )
        session.add(call)
        await session.flush()
        return call

    async def get_by_id(self, session: AsyncSession, tool_call_id: int) -> ToolCall | None:
        return await session.scalar(select(ToolCall).where(ToolCall.id == tool_call_id))

    async def mark_tool_call_success(
        self,
        session: AsyncSession,
        tool_call_id: int,
        response_summary: Any | None = None,
        duration_ms: int | None = None,
    ) -> ToolCall | None:
        call = await self.get_by_id(session, tool_call_id)
        if call is None:
            return None
        ended_at = datetime.utcnow()
        call.status = ToolCallStatus.SUCCESS.value
        call.ended_at = ended_at
        call.duration_ms = duration_ms if duration_ms is not None else _duration_ms(call.started_at, ended_at)
        if response_summary is not None:
            call.response_summary = sanitize_summary(response_summary)
        call.updated_at = ended_at
        await session.flush()
        return call

    async def mark_tool_call_failure(
        self,
        session: AsyncSession,
        tool_call_id: int,
        error_message: str,
        error_code: str | None = None,
        retry_count: int = 0,
    ) -> ToolCall | None:
        if not error_message:
            raise ValueError("error_message is required")
        call = await self.get_by_id(session, tool_call_id)
        if call is None:
            return None
        ended_at = datetime.utcnow()
        call.status = ToolCallStatus.FAILURE.value
        call.ended_at = ended_at
        call.duration_ms = _duration_ms(call.started_at, ended_at)
        call.error_code = error_code
        call.error_message = error_message
        call.retry_count = retry_count
        call.updated_at = ended_at
        await session.flush()
        return call

    async def list_tool_calls_for_run(
        self, session: AsyncSession, run_id: int, offset: int = 0, limit: int = 200
    ) -> list[ToolCall]:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be non-negative and limit must be positive")
        result = await session.execute(
            select(ToolCall)
            .where(ToolCall.run_id == run_id)
            .order_by(ToolCall.started_at.asc(), ToolCall.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())
