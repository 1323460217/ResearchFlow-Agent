"""Run an infrastructure-backed report-run HITL smoke test.

External LLM/RAG nodes are replaced with a tiny graph, while the production
Celery task, human-review node, PostgreSQL business tables, PostgreSQL
checkpointer, and Redis projection remain in the path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from backend.api.serialization import sanitize_for_json  # noqa: E402
from backend.checkpoint.postgres_checkpointer import (  # noqa: E402
    build_graph_config,
    get_checkpoint_database_url,
    get_postgres_checkpointer,
    mask_database_url,
    reset_postgres_checkpointer,
    setup_postgres_checkpointer,
)
from backend.core.config import settings  # noqa: E402
from backend.memory.redis_task_status import (  # noqa: E402
    delete_run_status_projection,
    get_run_status_projection,
)
from backend.models.agent_run import AgentRun  # noqa: E402
from backend.models.human_review import HumanReview  # noqa: E402
from backend.models.research_report import ResearchReport  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.services.report_run_service import ReportRunService  # noqa: E402
from backend.services.report_status_service import ReportStatusService  # noqa: E402
from backend.workflow.human_review_node import human_review_node  # noqa: E402
from backend.workflow.report_run_graph import (  # noqa: E402
    FINALIZE,
    REVIEW_LIMIT,
    REWRITE_REPORTER,
    finalize_report_node,
    prepare_reporter_revision_node,
    route_after_human_review,
)
from backend.workflow.state import ResearchState  # noqa: E402
from backend.worker import tasks_report  # noqa: E402
from backend.worker.celery_app import celery_app  # noqa: E402


def build_minimal_e2e_graph(checkpointer):
    """Build the real interrupt/resume path without external service calls."""

    def draft_node(state: ResearchState) -> dict[str, Any]:
        return {
            "final_report": "# E2E_TEST_REPORT_HITL\n\nDurable review draft.",
            "report_sections": [],
            "key_findings": ["The durable review boundary was reached."],
            "workflow_status": "completed",
        }

    builder = StateGraph(ResearchState)
    builder.add_node("draft", draft_node)
    builder.add_node("human_review", human_review_node)
    builder.add_node(FINALIZE, finalize_report_node)
    builder.add_node(REWRITE_REPORTER, prepare_reporter_revision_node)
    builder.add_node(
        REVIEW_LIMIT,
        lambda state: {
            "workflow_status": "failed",
            "error_message": "maximum human review rounds exceeded",
        },
    )
    builder.add_edge(START, "draft")
    builder.add_edge("draft", "human_review")
    builder.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {FINALIZE: FINALIZE, REWRITE_REPORTER: REWRITE_REPORTER, REVIEW_LIMIT: REVIEW_LIMIT},
    )
    builder.add_edge(REWRITE_REPORTER, "human_review")
    builder.add_edge(FINALIZE, END)
    builder.add_edge(REVIEW_LIMIT, END)
    return builder.compile(checkpointer=checkpointer)


def _run(coro):
    # The application Redis singleton is loop-bound; this script intentionally
    # uses several short loops because Celery tasks are synchronous wrappers.
    from backend.memory.redis_client import reset_redis

    reset_redis()
    try:
        return asyncio.run(coro)
    finally:
        reset_redis()


async def _ping_redis() -> None:
    for url in (settings.REDIS_URL, settings.CELERY_BROKER_URL):
        redis = Redis.from_url(url)
        try:
            await redis.ping()
        finally:
            await redis.aclose()


def _make_session_factory():
    if settings.POSTGRES_URL == "postgresql+asyncpg://test:test@localhost:5432/test":
        raise RuntimeError("Set POSTGRES_URL to the real E2E database before running this script")
    engine = create_async_engine(settings.POSTGRES_URL, poolclass=NullPool)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def _ensure_user(session_factory, marker: str) -> int:
    async with session_factory() as db:
        user = await db.scalar(select(User).where(User.username == marker))
        if user is None:
            user = User(
                username=marker,
                email=f"{marker}@example.invalid",
                hashed_password="e2e-not-a-login-password",
                is_active=True,
            )
            db.add(user)
            await db.flush()
        user_id = user.id
        await db.commit()
        return user_id


async def _create_run(session_factory, user_id: int, marker: str) -> dict[str, Any]:
    async with session_factory() as db:
        result = await ReportRunService().create_report_run(
            session=db,
            user_id=user_id,
            query=f"{marker}: durable human review",
            options={"use_react": False},
        )
        await db.commit()
        return result


async def _prepare_resume(session_factory, run_id: int, user_id: int, review_id: int, action: str, round_: int):
    async with session_factory() as db:
        result = await ReportRunService().prepare_resume(
            session=db,
            run_id=run_id,
            user_id=user_id,
            review_id=review_id,
            action=action,
            feedback="E2E_TEST_REPORT_HITL: please revise" if action == "reject" else None,
            edited_report=(
                "# E2E_TEST_REPORT_HITL edited\n\nApproved edited content."
                if action == "edit" else None
            ),
            idempotency_key=f"{run_id}-{round_}-{action}-{uuid4().hex}",
        )
        await db.commit()
        return result


async def _read_run(session_factory, run_id: int) -> AgentRun:
    async with session_factory() as db:
        run = await db.scalar(select(AgentRun).where(AgentRun.id == run_id))
        if run is None:
            raise RuntimeError(f"agent run {run_id} disappeared")
        return run


async def _read_review(session_factory, review_id: int) -> HumanReview:
    async with session_factory() as db:
        review = await db.scalar(select(HumanReview).where(HumanReview.id == review_id))
        if review is None:
            raise RuntimeError(f"review {review_id} disappeared")
        return review


async def _read_report(session_factory, run_id: int) -> ResearchReport | None:
    async with session_factory() as db:
        return await db.scalar(select(ResearchReport).where(ResearchReport.agent_run_id == run_id))


async def _read_status(session_factory, run_id: int, user_id: int) -> dict[str, Any]:
    async with session_factory() as db:
        return await ReportStatusService().get_realtime_status(db, run_id, user_id)


def _checkpoint_counts(thread_id: str) -> dict[str, int]:
    connection = psycopg.connect(get_checkpoint_database_url())
    try:
        counts = {}
        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            row = connection.execute(
                f"select count(*) from {table} where thread_id = %s",  # noqa: S608
                (thread_id,),
            ).fetchone()
            counts[table] = int(row[0])
        return counts
    finally:
        connection.close()


def _legacy_paths() -> dict[str, bool]:
    from backend.main import app

    paths = {route.path for route in app.routes}
    return {
        "/api/chat": "/api/chat" in paths,
        "/api/chat/stream": "/api/chat/stream" in paths,
        "/api/report-runs": "/api/report-runs" in paths,
        "/ws/agent-stream": "/ws/agent-stream" in paths,
        "/api/reports": "/api/reports" in paths,
    }


def _wait_celery_result(result, timeout: int) -> Any:
    deadline = time.monotonic() + timeout
    while not result.ready() and time.monotonic() < deadline:
        time.sleep(0.25)
    if not result.ready():
        raise TimeoutError(f"Celery task {result.id} did not finish within {timeout}s")
    if result.failed():
        raise RuntimeError(f"Celery task {result.id} failed: {result.result!r}")
    return result.result


def _dispatch(task, run_id: int, mode: str, timeout: int):
    if mode == "eager":
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        return _wait_celery_result(task.delay(run_id), timeout)

    celery_app.conf.task_always_eager = False
    worker = celery_app.Worker(
        pool="solo",
        loglevel="ERROR",
        without_mingle=True,
        without_gossip=True,
        without_heartbeat=True,
    )
    thread = threading.Thread(target=worker.start, name="researchflow-e2e-worker", daemon=True)
    thread.start()
    try:
        time.sleep(2)
        return _wait_celery_result(task.delay(run_id), timeout)
    finally:
        worker.stop()
        thread.join(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("eager", "worker"), default="eager")
    parser.add_argument("--action", choices=("approve", "edit", "reject"), default="approve")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    marker = f"E2E_TEST_REPORT_RUN_HITL_{uuid4().hex[:10]}".lower()
    original_graph_builder = tasks_report.build_report_run_graph
    original_checkpointer_getter = tasks_report.get_postgres_checkpointer
    original_session_factory = tasks_report.async_session_factory
    session_factory = None
    engine = None
    run_id = None
    try:
        print(f"PostgreSQL: {mask_database_url(get_checkpoint_database_url())}")
        _run(_ping_redis())
        setup_postgres_checkpointer()
        session_factory, engine = _make_session_factory()
        tasks_report.async_session_factory = session_factory
        user_id = _run(_ensure_user(session_factory, marker))
        run = _run(_create_run(session_factory, user_id, marker))
        run_id = run["id"]
        thread_id = str(run["thread_id"])
        assert thread_id == str(run_id)
        assert build_graph_config(thread_id)["configurable"]["thread_id"] == thread_id

        reset_postgres_checkpointer()
        checkpointer = get_postgres_checkpointer()
        tasks_report.build_report_run_graph = build_minimal_e2e_graph
        tasks_report.get_postgres_checkpointer = lambda: checkpointer

        start_result = _dispatch(tasks_report.start_report_task, run_id, args.mode, args.timeout)
        waiting = _run(_read_run(session_factory, run_id))
        pending = _run(_read_review(session_factory, start_result["review_id"]))
        projection = _run(get_run_status_projection(run_id))
        assert waiting.status == "WAITING_HUMAN"
        assert pending.status == "PENDING"
        assert projection and projection["status"] == "WAITING_HUMAN"
        assert projection["review_required"] is True
        assert projection["review_id"] == pending.id
        checkpoint_counts = _checkpoint_counts(thread_id)
        assert checkpoint_counts["checkpoints"] > 0
        assert checkpoint_counts["checkpoint_writes"] > 0
        # Simulate a worker/checkpointer restart before resume.
        reset_postgres_checkpointer()
        checkpointer = get_postgres_checkpointer()
        tasks_report.get_postgres_checkpointer = lambda: checkpointer

        resume_request = _run(
            _prepare_resume(session_factory, run_id, user_id, pending.id, args.action, pending.review_round)
        )
        resume_result = _dispatch(tasks_report.resume_report_task, run_id, args.mode, args.timeout)
        final_run = _run(_read_run(session_factory, run_id))
        submitted = _run(_read_review(session_factory, pending.id))
        if args.action == "reject":
            next_status = _run(_read_status(session_factory, run_id, user_id))
            next_review = _run(_read_review(session_factory, next_status["review_id"]))
            assert final_run.status == "WAITING_HUMAN"
            assert submitted.status == "REJECTED"
            assert next_review.status == "PENDING"
            assert next_review.review_round == pending.review_round + 1
            final_status = "WAITING_HUMAN"
        else:
            assert final_run.status == "SUCCESS"
            assert submitted.status in {"APPROVED", "EDITED"}
            report = _run(_read_report(session_factory, run_id))
            assert report is not None
            assert report.agent_run_id == run_id
            assert report.generation_status == "SUCCESS"
            assert report.finalized_at is not None
            final_projection = _run(get_run_status_projection(run_id))
            assert final_projection and final_projection["status"] == "SUCCESS"
            assert final_projection["progress"] == 100
            assert final_projection["review_required"] is False
            final_status = "SUCCESS"

        _run(delete_run_status_projection(run_id))
        fallback = _run(_read_status(session_factory, run_id, user_id))
        repaired = _run(get_run_status_projection(run_id))
        assert fallback["source"] == "postgresql"
        assert repaired and repaired["status"] == final_status
        legacy = _legacy_paths()
        assert all(legacy.values()), legacy
        print(json.dumps({
            "marker": marker,
            "run_id": run_id,
            "thread_id": thread_id,
            "action": args.action,
            "mode": args.mode,
            "status": final_status,
            "start_result": sanitize_for_json(start_result),
            "resume_request": sanitize_for_json(resume_request),
            "resume_result": sanitize_for_json(resume_result),
            "checkpoint_counts": checkpoint_counts,
            "legacy_paths": legacy,
            "business_data_retained": not args.cleanup,
        }, ensure_ascii=False, indent=2, default=str))

        if args.cleanup:
            async def cleanup():
                async with session_factory() as db:
                    run_obj = await db.scalar(select(AgentRun).where(AgentRun.id == run_id))
                    if run_obj is not None:
                        await db.delete(run_obj)
                        await db.commit()
            _run(cleanup())
        return 0
    except Exception as exc:
        print(f"E2E FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        tasks_report.build_report_run_graph = original_graph_builder
        tasks_report.get_postgres_checkpointer = original_checkpointer_getter
        tasks_report.async_session_factory = original_session_factory
        reset_postgres_checkpointer()
        if engine is not None:
            _run(engine.dispose())


if __name__ == "__main__":
    raise SystemExit(main())
