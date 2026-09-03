from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.report_runs import get_report_run_status
from backend.memory.redis_task_status import (
    build_run_status_key,
    delete_run_status_projection,
    get_run_status_projection,
    set_run_status_projection,
)
from backend.models.enums import AgentRunStatus
from backend.services.report_status_service import ReportStatusService


def _run(status=AgentRunStatus.RUNNING.value, status_version=2):
    return SimpleNamespace(
        id=9,
        user_id=7,
        conversation_id=None,
        thread_id="9",
        status=status,
        query="research",
        current_node="analyzer",
        iteration_count=0,
        max_iterations=3,
        human_review_round=0,
        max_human_reviews=3,
        current_task_id="task-9",
        error_code=None,
        error_message=None,
        status_version=status_version,
        created_at=datetime(2026, 9, 1, 10, 0),
        started_at=None,
        completed_at=None,
        failed_at=None,
        updated_at=datetime(2026, 9, 1, 10, 1),
    )


@pytest.mark.asyncio
async def test_run_status_projection_set_get_delete():
    redis = AsyncMock()
    redis.hgetall = AsyncMock(
        return_value={
            "run_id": "9",
            "status": "WAITING_HUMAN",
            "progress": "70",
            "review_required": "true",
            "review_id": "12",
            "status_version": "3",
            "updated_at": "2026-09-01T10:02:00",
            "source": "redis",
        }
    )
    with patch("backend.memory.redis_task_status.get_redis", AsyncMock(return_value=redis)):
        await set_run_status_projection(
            run_id=9,
            status="WAITING_HUMAN",
            current_node="human_review",
            progress=70,
            review_required=True,
            review_id=12,
            status_version=3,
            ttl_seconds=60,
        )
        projection = await get_run_status_projection(9)
        await delete_run_status_projection(9)

    assert build_run_status_key(9) == "report_run:9:status"
    redis.hset.assert_awaited_once()
    redis.expire.assert_awaited_once_with("report_run:9:status", 60)
    assert projection["progress"] == 70
    assert projection["status_version"] == 3
    assert projection["review_required"] is True
    assert projection["review_id"] == 12
    redis.delete.assert_awaited_once_with("report_run:9:status")


@pytest.mark.asyncio
async def test_realtime_status_uses_current_redis_projection():
    run = _run(status=AgentRunStatus.RUNNING.value, status_version=2)
    agent_runs = AsyncMock()
    agent_runs.get_by_id_for_user.return_value = run
    reviews = AsyncMock()
    service = ReportStatusService(agent_runs, reviews)
    projection = {
        "status": "WAITING_HUMAN",
        "current_node": "human_review",
        "progress": 70,
        "review_required": True,
        "review_id": 12,
        "task_id": "task-9",
        "status_version": 2,
        "updated_at": datetime(2026, 9, 1, 10, 2),
    }
    with patch(
        "backend.services.report_status_service.get_run_status_projection",
        AsyncMock(return_value=projection),
    ) as get_projection, patch(
        "backend.services.report_status_service.repair_run_status_projection_from_run",
        AsyncMock(),
    ) as repair:
        result = await service.get_realtime_status(AsyncMock(), 9, 7)

    get_projection.assert_awaited_once_with(9)
    repair.assert_not_awaited()
    assert result["source"] == "redis"
    assert result["status"] == "WAITING_HUMAN"
    assert result["review_id"] == 12


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "projection",
    [None, {"status": "RUNNING", "status_version": 1}],
)
async def test_realtime_status_falls_back_and_repairs_projection(projection):
    run = _run(status=AgentRunStatus.RUNNING.value, status_version=2)
    agent_runs = AsyncMock()
    agent_runs.get_by_id_for_user.return_value = run
    service = ReportStatusService(agent_runs, AsyncMock())
    with patch(
        "backend.services.report_status_service.get_run_status_projection",
        AsyncMock(return_value=projection),
    ), patch(
        "backend.services.report_status_service.repair_run_status_projection_from_run",
        AsyncMock(),
    ) as repair:
        result = await service.get_realtime_status(AsyncMock(), 9, 7)

    repair.assert_awaited_once()
    assert result["source"] == "postgresql"
    assert result["status"] == AgentRunStatus.RUNNING.value
    assert result["progress"] == 25


@pytest.mark.asyncio
async def test_realtime_status_checks_postgresql_ownership_before_redis():
    agent_runs = AsyncMock()
    agent_runs.get_by_id_for_user.return_value = None
    service = ReportStatusService(agent_runs, AsyncMock())
    with patch(
        "backend.services.report_status_service.get_run_status_projection",
        AsyncMock(),
    ) as get_projection:
        with pytest.raises(LookupError):
            await service.get_realtime_status(AsyncMock(), 9, 999)

    get_projection.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_api_maps_realtime_fields_and_source():
    result = {
        "run_id": 9,
        "status": "WAITING_HUMAN",
        "current_node": "human_review",
        "progress": 70,
        "review_required": True,
        "review_id": 12,
        "task_id": None,
        "status_version": 3,
        "updated_at": datetime(2026, 9, 1, 10, 2),
        "source": "redis",
    }
    with patch(
        "backend.api.report_runs.report_status_service.get_realtime_status",
        AsyncMock(return_value=result),
    ):
        response = await get_report_run_status(
            run_id=9,
            db=AsyncMock(),
            user=SimpleNamespace(id=7),
        )

    assert response.data["run_id"] == 9
    assert response.data["progress"] == 70
    assert response.data["review_required"] is True
    assert response.data["source"] == "redis"
