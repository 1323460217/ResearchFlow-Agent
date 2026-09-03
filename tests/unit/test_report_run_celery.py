from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.report_runs import create_report_run, resume_report_run
from backend.api.schemas_report_runs import CreateReportRunRequest, ResumeReportRunRequest
from backend.models.enums import AgentRunStatus
from backend.worker.tasks_report import resume_report_task, start_report_task
from backend.workflow.human_review_node import human_review_node
from backend.workflow.report_run_graph import (
    FINALIZE,
    REVIEW_LIMIT,
    REWRITE_REPORTER,
    route_after_human_review,
)


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _run(status, version=1, round_=0, max_reviews=3):
    return SimpleNamespace(
        id=9,
        user_id=7,
        conversation_id=None,
        thread_id="9",
        query="A research query",
        request_snapshot={"options": {}},
        status=status,
        current_node=None,
        current_task_id=None,
        status_version=version,
        iteration_count=0,
        max_iterations=3,
        human_review_round=round_,
        max_human_reviews=max_reviews,
    )


class _RunRepository:
    def __init__(self, run):
        self.run = run

    async def get_by_id(self, *args, **kwargs):
        return self.run

    async def compare_and_set_status(self, *args, **kwargs):
        expected = kwargs["expected_status"]
        expected = expected.value if hasattr(expected, "value") else expected
        if self.run.status != expected:
            return None
        new_status = kwargs["new_status"]
        self.run.status = new_status.value if hasattr(new_status, "value") else new_status
        self.run.current_node = kwargs.get("current_node")
        self.run.current_task_id = kwargs.get("current_task_id")
        self.run.status_version += 1
        return self.run

    async def update_status(self, *args, **kwargs):
        status = kwargs["status"]
        self.run.status = status.value if hasattr(status, "value") else status
        self.run.current_node = kwargs.get("current_node")
        if kwargs.get("current_task_id") is not None:
            self.run.current_task_id = kwargs["current_task_id"]
        self.run.status_version += 1
        return self.run


class _ReviewRepository:
    def __init__(self, review=None):
        self.review = review

    async def get_pending_review(self, *args, **kwargs):
        return self.review if self.review and self.review.status == "PENDING" else None

    async def list_reviews_for_run(self, *args, **kwargs):
        return [self.review] if self.review else []


class _Graph:
    def __init__(self, chunks, state):
        self.chunks = chunks
        self.state = state
        self.inputs = []

    async def astream(self, value, config=None):
        self.inputs.append((value, config))
        for chunk in self.chunks:
            yield chunk

    async def aget_state(self, config):
        return SimpleNamespace(
            values=self.state,
            config={"configurable": {"checkpoint_id": "cp-1"}},
        )


def _interrupt_chunk(payload):
    return {"__interrupt__": (SimpleNamespace(value=payload),)}


def _task_context(session):
    return _AsyncSessionContext(session)


def _common_task_patches(session, repo, review_repo):
    return [
        patch("backend.worker.tasks_report.async_session_factory", return_value=_task_context(session)),
        patch("backend.worker.tasks_report.AgentRunRepository", return_value=repo),
        patch("backend.worker.tasks_report.HumanReviewRepository", return_value=review_repo),
        patch("backend.worker.tasks_report.get_postgres_checkpointer", return_value=object()),
        patch("backend.worker.tasks_report._task_id", return_value="celery-task"),
        patch("backend.worker.tasks_report._record_trace_start", new_callable=AsyncMock, return_value=1),
        patch("backend.worker.tasks_report._record_trace_end", new_callable=AsyncMock),
        patch("backend.worker.tasks_report._write_projection", new_callable=AsyncMock),
    ]


def test_human_review_node_accepts_approve_edit_and_reject():
    state = {"query": "q", "final_report": "draft", "review_round": 1}
    with patch("backend.workflow.human_review_node.interrupt", return_value={"action": "approve"}) as pause:
        result = human_review_node(state)
    assert result["human_review_action"] == "approve"
    payload = pause.call_args.args[0]
    assert payload["type"] == "human_review"
    assert payload["draft_report"]["summary"] == "draft"
    assert "retrieved_docs" not in payload

    with patch("backend.workflow.human_review_node.interrupt", return_value={"action": "edit", "edited_report": "edited"}):
        assert human_review_node(state)["final_report"] == "edited"
    with patch("backend.workflow.human_review_node.interrupt", return_value={"action": "reject", "feedback": "fix claims"}):
        assert human_review_node(state)["human_feedback"] == "fix claims"


def test_route_after_human_review():
    assert route_after_human_review({"human_review_action": "approve"}) == FINALIZE
    assert route_after_human_review({"human_review_action": "edit"}) == FINALIZE
    assert route_after_human_review({"human_review_action": "reject", "review_round": 1, "max_human_reviews": 3}) == REWRITE_REPORTER
    assert route_after_human_review({"human_review_action": "reject", "review_round": 3, "max_human_reviews": 3}) == REVIEW_LIMIT


def test_start_task_creates_pending_review_from_langgraph_interrupt():
    run = _run(AgentRunStatus.PENDING.value)
    session = SimpleNamespace(commit=AsyncMock())
    repo = _RunRepository(run)
    review_repo = _ReviewRepository()
    review_service = AsyncMock()
    review_service.create_pending_review_for_run = AsyncMock(
        return_value={"run": {"id": 9, "status_version": 4}, "review": {"id": 21}}
    )
    graph = _Graph(
        [_interrupt_chunk({
            "type": "human_review",
            "draft_report": {"title": "q", "summary": "draft", "review_round": 1},
            "review_round": 1,
        })],
        {"final_report": "draft", "workflow_status": "running"},
    )
    patches = _common_task_patches(session, repo, review_repo)
    patches += [
        patch("backend.worker.tasks_report.HumanReviewService", return_value=review_service),
        patch("backend.worker.tasks_report.build_report_run_graph", return_value=graph),
    ]
    with _enter_patches(patches):
        result = start_report_task.run(9)

    assert result == {"run_id": 9, "status": "WAITING_HUMAN", "review_id": 21}
    review_service.create_pending_review_for_run.assert_awaited_once()
    assert graph.inputs[0][0]["thread_id"] == "9"
    assert session.commit.await_count == 3


def test_resume_task_approve_uses_command_and_saves_report():
    run = _run(AgentRunStatus.RESUME_QUEUED.value, version=4, round_=1)
    session = SimpleNamespace(commit=AsyncMock())
    repo = _RunRepository(run)
    review = SimpleNamespace(id=21, status="APPROVED", action="approve", review_round=1, feedback=None, edited_report=None)
    review_repo = _ReviewRepository(review)
    graph = _Graph(
        [{"finalize": {"final_report": "approved report"}}],
        {"final_report": "approved report", "workflow_status": "completed", "iteration_count": 1},
    )
    persistence = AsyncMock()
    patches = _common_task_patches(session, repo, review_repo)
    patches += [
        patch("backend.worker.tasks_report.build_report_run_graph", return_value=graph),
        patch("backend.worker.tasks_report.ReportPersistenceService", return_value=persistence),
    ]
    with _enter_patches(patches):
        result = resume_report_task.run(9)

    assert result == {"run_id": 9, "status": "SUCCESS"}
    command = graph.inputs[0][0]
    assert command.resume == {"action": "approve", "feedback": None, "edited_report": None, "review_id": 21}
    persistence.save_final_report_for_run.assert_awaited_once()
    assert run.status == AgentRunStatus.SUCCESS.value


def test_resume_task_reject_creates_next_pending_review_on_reinterrupt():
    run = _run(AgentRunStatus.RESUME_QUEUED.value, version=4, round_=1)
    session = SimpleNamespace(commit=AsyncMock())
    repo = _RunRepository(run)
    review = SimpleNamespace(id=21, status="REJECTED", action="reject", review_round=1, feedback="fix", edited_report=None)
    review_repo = _ReviewRepository(review)
    review_service = AsyncMock()
    review_service.create_pending_review_for_run = AsyncMock(
        return_value={"run": {"id": 9, "status_version": 8}, "review": {"id": 22}}
    )
    graph = _Graph(
        [_interrupt_chunk({
            "type": "human_review",
            "draft_report": {"title": "q", "summary": "rewritten", "review_round": 2},
            "review_round": 2,
        })],
        {"final_report": "rewritten", "workflow_status": "running"},
    )
    patches = _common_task_patches(session, repo, review_repo)
    patches += [
        patch("backend.worker.tasks_report.HumanReviewService", return_value=review_service),
        patch("backend.worker.tasks_report.build_report_run_graph", return_value=graph),
    ]
    with _enter_patches(patches):
        result = resume_report_task.run(9)

    assert result == {"run_id": 9, "status": "WAITING_HUMAN", "review_id": 22}
    assert review_service.create_pending_review_for_run.await_args.kwargs["review_round"] == 2


class _enter_patches:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        self.contexts = [item.start() for item in self.patches]
        return self.contexts

    def __exit__(self, exc_type, exc, tb):
        for item in reversed(self.patches):
            item.stop()
        return False


def _run_dict(status="PENDING", task_id=None):
    return {
        "id": 9,
        "thread_id": "9",
        "status": status,
        "current_node": "created",
        "query": "query",
        "status_version": 1,
        "current_task_id": task_id,
        "created_at": datetime(2026, 9, 1, 10, 0),
    }


@pytest.mark.asyncio
async def test_create_report_run_enqueues_only_run_id():
    body = CreateReportRunRequest(query="query")
    db = AsyncMock()
    user = SimpleNamespace(id=7)
    service = AsyncMock()
    service.create_report_run.return_value = _run_dict()
    service.enqueue_start_report_run.return_value = {
        "run": _run_dict(task_id="celery-start"), "task_id": "celery-start"
    }

    with patch("backend.api.report_runs.report_run_service", service):
        response = await create_report_run(body=body, db=db, user=user)

    service.enqueue_start_report_run.assert_awaited_once_with(session=db, run_id=9, user_id=7)
    assert response.data["celery_task_id"] == "celery-start"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_report_run_enqueues_resume_task():
    body = ResumeReportRunRequest(review_id=21, action="approve", idempotency_key="idem-1")
    db = AsyncMock()
    user = SimpleNamespace(id=7)
    service = AsyncMock()
    service.prepare_resume.return_value = {
        "run": _run_dict("RESUME_QUEUED"),
        "review": {"id": 21},
        "enqueue_required": True,
    }
    service.enqueue_resume_report_run.return_value = {
        "run": _run_dict("RESUME_QUEUED", "celery-resume"),
        "task_id": "celery-resume",
    }

    with patch("backend.api.report_runs.report_run_service", service):
        response = await resume_report_run(run_id=9, body=body, db=db, user=user)

    service.enqueue_resume_report_run.assert_awaited_once_with(session=db, run_id=9, user_id=7)
    assert response.data["celery_task_id"] == "celery-resume"
    assert db.commit.await_count == 1
