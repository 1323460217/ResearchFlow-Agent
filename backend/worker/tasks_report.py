import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from celery import shared_task
from langgraph.types import Command

from backend.api.serialization import sanitize_for_json
from backend.checkpoint.postgres_checkpointer import build_graph_config, get_postgres_checkpointer
from backend.database.session import async_session_factory, get_worker_session_factory
from backend.memory.redis_task_status import set_run_status_projection_if_newer
from backend.models.enums import AgentRunStatus, HumanReviewStatus
from backend.models.research_report import ResearchReport
from backend.repositories.agent_run_repository import AgentRunRepository
from backend.repositories.human_review_repository import HumanReviewRepository
from backend.services.human_review_service import HumanReviewService
from backend.services.report_persistence_service import ReportPersistenceService
from backend.services.report_trace_service import ReportTraceService
from backend.workflow.adapters import (
    build_report_run_input,
    extract_final_report_payload,
    extract_interrupt_payload,
    review_snapshot_from_interrupt,
)
from backend.workflow.report_run_graph import build_report_run_graph
from backend.workflow.agents.retriever import _search_arxiv_sync
from backend.worker.runtime import run_worker_coroutine

logger = logging.getLogger(__name__)

_default_async_session_factory = async_session_factory


def _session_factory():
    # Unit tests patch the module alias; production workers use the scoped
    # factory installed by worker_resource_runtime.
    if async_session_factory is not _default_async_session_factory:
        return async_session_factory
    return get_worker_session_factory()


async def _run_in_worker_runtime(coro):
    if async_session_factory is not _default_async_session_factory:
        return await coro
    return await run_worker_coroutine(coro)


def _run_async(coro):
    runner = _run_in_worker_runtime(coro)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(runner)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, runner).result()


def _task_id(task: Any) -> str:
    return str(getattr(getattr(task, 'request', None), 'id', None) or 'unknown')


async def _write_projection(**values: Any) -> None:
    try:
        await set_run_status_projection_if_newer(**values)
    except Exception as exc:
        logger.warning('Redis status projection write failed for report run %s: %s', values.get('run_id'), exc)


def _draft_snapshot(query: str, message: str) -> dict[str, str]:
    return {'title': query[:100], 'query': query, 'message': message}


async def _latest_submitted_review(db, run_id: int):
    reviews = await HumanReviewRepository().list_reviews_for_run(db, run_id)
    submitted = [item for item in reviews if item.status != HumanReviewStatus.PENDING.value]
    return max(submitted, key=lambda item: (item.review_round, item.id)) if submitted else None


async def _mark_failure(run_id: int, error_code: str, exc: Exception) -> None:
    del exc
    error_message = f'{error_code}: task execution failed'
    try:
        async with _session_factory()() as db:
            runs = AgentRunRepository()
            run = await runs.get_by_id(db, run_id)
            if run is None:
                return
            if run.status != AgentRunStatus.FAILURE.value:
                run = await runs.compare_and_set_status(
                    session=db, run_id=run_id,
                    expected_statuses=[AgentRunStatus.STARTED, AgentRunStatus.RUNNING, AgentRunStatus.RESUMED],
                    new_status=AgentRunStatus.FAILURE,
                    current_node='failed', error_code=error_code,
                    error_message=error_message,
                )
            await db.commit()
            if run is not None:
                await _write_projection(
                    run_id=run.id, status=AgentRunStatus.FAILURE.value,
                    current_node='failed', progress=100, review_required=False,
                    task_id=run.current_task_id, status_version=run.status_version,
                )
    except Exception:
        logger.exception('Failed to persist failure for report run %s', run_id)


async def _record_trace_start(db, run, task_id: str, node_name: str, input_summary: Any) -> int | None:
    try:
        result = await ReportTraceService().start_step(
            session=db,
            user_id=run.user_id,
            run_id=run.id,
            node_name=node_name,
            celery_task_id=task_id,
            input_summary=input_summary,
        )
        return result.get("id")
    except Exception:
        logger.warning("Failed to record %s trace for report run %s", node_name, run.id, exc_info=True)
        return None


async def _record_trace_end(
    db,
    run,
    step_id: int | None,
    event: str,
    output_summary: Any | None = None,
    error_message: str | None = None,
) -> None:
    if step_id is None:
        return
    try:
        service = ReportTraceService()
        if error_message:
            await service.finish_step_failure(
                session=db,
                user_id=run.user_id,
                step_id=step_id,
                error_code=event.upper(),
                error_message=error_message[:1000],
                output_summary=output_summary,
            )
        elif event in {"langgraph_interrupt", "langgraph_reinterrupt"}:
            await service.mark_step_interrupted(
                session=db,
                user_id=run.user_id,
                step_id=step_id,
                output_summary=output_summary,
            )
        else:
            await service.finish_step_success(
                session=db,
                user_id=run.user_id,
                step_id=step_id,
                output_summary=output_summary,
            )
    except Exception:
        logger.warning("Failed to record %s trace for report run %s", event, run.id, exc_info=True)


async def _record_trace_failure(run_id: int, user_id: int | None, step_id: int | None, exc: Exception) -> None:
    if user_id is None or step_id is None:
        return
    try:
        async with _session_factory()() as db:
            await ReportTraceService().finish_step_failure(
                session=db,
                user_id=user_id,
                step_id=step_id,
                error_code="LANGGRAPH_FAILURE",
                error_message=str(exc)[:1000] or "LangGraph task failed",
                output_summary={"event": "langgraph_failure"},
            )
            await db.commit()
    except Exception:
        logger.warning("Failed to record langgraph_failure trace for report run %s", run_id, exc_info=True)


async def _stream_report_graph(graph, graph_input, config):
    chunks = []
    async for chunk in graph.astream(graph_input, config=config):
        chunks.append(chunk)
    snapshot = await graph.aget_state(config)
    values = dict(snapshot.values or {})
    return chunks, values, snapshot


def _checkpoint_id(snapshot) -> str | None:
    config = getattr(snapshot, "config", {}) or {}
    configurable = config.get("configurable", {})
    value = configurable.get("checkpoint_id")
    return str(value) if value else None


async def _create_pending_review(db, run, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    draft = review_snapshot_from_interrupt(payload)
    round_number = draft.get("review_round") or payload.get("review_round") or run.human_review_round + 1
    result = await HumanReviewService().create_pending_review_for_run(
        session=db,
        run_id=run.id,
        review_round=int(round_number),
        draft_report_snapshot=draft,
        checkpoint_id=payload.get("checkpoint_id"),
    )
    await db.commit()
    waiting = result["run"]
    await _write_projection(
        run_id=run.id,
        status=AgentRunStatus.WAITING_HUMAN.value,
        current_node="human_review",
        progress=70,
        review_required=True,
        review_id=result["review"]["id"],
        task_id=task_id,
        status_version=waiting["status_version"],
    )
    return result


async def _mark_success(db, runs, run, task_id: str, state: dict[str, Any], review_action: str | None = None):
    payload = extract_final_report_payload(state)
    if not payload["content"].strip():
        raise ValueError("LangGraph completed without a final report")
    persistence = ReportPersistenceService()
    await persistence.save_final_report_for_run(
        session=db,
        run_id=run.id,
        user_id=run.user_id,
        title=run.query[:100],
        content=payload["content"],
        sections=payload["sections"],
        sources=payload["sources"],
        evidence_items=payload["evidence_items"],
        generation_status="SUCCESS",
        review_action=review_action or payload["review_action"],
    )
    for call in payload["tool_calls"]:
        if not isinstance(call, dict):
            continue
        tool_name = call.get("tool_name") or call.get("name")
        if not tool_name:
            continue
        await persistence.save_tool_call(
            session=db,
            run_id=run.id,
            tool_name=str(tool_name)[:255],
            provider=call.get("provider"),
            request_summary=call.get("request_summary") or call.get("args"),
            idempotency_key=call.get("idempotency_key"),
            status=call.get("status", "SUCCESS"),
            response_summary=call.get("response_summary") or call.get("result"),
            error_code=call.get("error_code"),
            error_message=call.get("error_message"),
        )
    if payload["iteration_count"] is not None:
        run.iteration_count = int(payload["iteration_count"])
    success = await runs.compare_and_set_status(
        session=db,
        run_id=run.id,
        expected_status=AgentRunStatus.RUNNING,
        new_status=AgentRunStatus.SUCCESS,
        current_node="done",
        current_task_id=task_id,
    )
    if success is None:
        current = await runs.get_by_id(db, run.id)
        return {"run_id": run.id, "status": current.status if current else "UNKNOWN"}
    await db.commit()
    await _write_projection(
        run_id=run.id,
        status=AgentRunStatus.SUCCESS.value,
        current_node="done",
        progress=100,
        review_required=False,
        task_id=task_id,
        status_version=success.status_version,
    )
    return {"run_id": run.id, "status": AgentRunStatus.SUCCESS.value}


@shared_task(bind=True, name="start_report_task")
def start_report_task(self, run_id: int):
    """Execute a durable report workflow until completion or human review."""
    task_id = _task_id(self)
    trace_context = {"user_id": None, "step_id": None}

    async def _run():
        async with _session_factory()() as db:
            runs = AgentRunRepository()
            reviews = HumanReviewRepository()
            run = await runs.get_by_id(db, run_id)
            if run is None:
                raise LookupError("agent run does not exist")
            if run.status in {
                AgentRunStatus.WAITING_HUMAN.value,
                AgentRunStatus.SUCCESS.value,
                AgentRunStatus.FAILURE.value,
                AgentRunStatus.CANCELLED.value,
            }:
                pending = await reviews.get_pending_review(db, run_id)
                result = {"run_id": run_id, "status": run.status}
                if pending is not None:
                    result["review_id"] = pending.id
                return result
            if run.status not in {
                AgentRunStatus.PENDING.value,
                AgentRunStatus.STARTED.value,
                AgentRunStatus.RUNNING.value,
            }:
                return {"run_id": run_id, "status": run.status}
            if (
                run.status in {AgentRunStatus.STARTED.value, AgentRunStatus.RUNNING.value}
                and run.current_task_id
                and run.current_task_id != task_id
            ):
                logger.info("Ignoring duplicate start delivery for report run %s", run_id)
                return {"run_id": run_id, "status": run.status}

            if run.status == AgentRunStatus.PENDING.value:
                started = await runs.compare_and_set_status(
                    session=db,
                    run_id=run_id,
                    expected_status=AgentRunStatus.PENDING,
                    new_status=AgentRunStatus.STARTED,
                    current_node="start",
                    current_task_id=task_id,
                )
                if started is None:
                    current = await runs.get_by_id(db, run_id)
                    return {"run_id": run_id, "status": current.status if current else "UNKNOWN"}
                run = started
                await db.commit()
                await _write_projection(
                    run_id=run_id, status=AgentRunStatus.STARTED.value, current_node="start",
                    progress=5, review_required=False, task_id=task_id,
                    status_version=run.status_version,
                )

            if run.status == AgentRunStatus.RUNNING.value:
                return {"run_id": run_id, "status": run.status}
            running = await runs.compare_and_set_status(
                session=db,
                run_id=run_id,
                expected_status=AgentRunStatus.STARTED,
                new_status=AgentRunStatus.RUNNING,
                current_node="planner",
                current_task_id=task_id,
            )
            if running is None:
                current = await runs.get_by_id(db, run_id)
                if current is not None and current.status in {
                    AgentRunStatus.RUNNING.value,
                    AgentRunStatus.WAITING_HUMAN.value,
                    AgentRunStatus.SUCCESS.value,
                    AgentRunStatus.FAILURE.value,
                }:
                    return {"run_id": run_id, "status": current.status}
                raise ValueError("run could not be moved to RUNNING")
            run = running
            await db.commit()
            await _write_projection(
                run_id=run_id, status=AgentRunStatus.RUNNING.value, current_node="planner",
                progress=10, review_required=False, task_id=task_id,
                status_version=run.status_version,
            )

            trace_id = await _record_trace_start(
                db, run, task_id, "langgraph_start", {"query": run.query[:200], "thread_id": str(getattr(run, "thread_id", run.id))}
            )
            trace_context.update(user_id=run.user_id, step_id=trace_id)
            checkpointer = get_postgres_checkpointer()
            graph = build_report_run_graph(checkpointer=checkpointer)
            config = build_graph_config(getattr(run, "thread_id", None) or run.id)
            chunks, state, snapshot = await _stream_report_graph(
                graph, build_report_run_input(run), config
            )
            interrupt_payload = extract_interrupt_payload(chunks)
            if interrupt_payload is not None:
                interrupt_payload["checkpoint_id"] = _checkpoint_id(snapshot)
                await _record_trace_end(
                    db, run, trace_id, "langgraph_interrupt",
                    {"review_round": interrupt_payload.get("review_round")},
                )
                result = await _create_pending_review(db, run, task_id, interrupt_payload)
                return {
                    "run_id": run_id,
                    "status": AgentRunStatus.WAITING_HUMAN.value,
                    "review_id": result["review"]["id"],
                }
            await _record_trace_end(
                db, run, trace_id, "langgraph_success",
                {"output_keys": sorted(state.keys())},
            )
            if state.get("workflow_status") == "failed":
                raise ValueError(state.get("error_message") or "LangGraph workflow failed")
            return await _mark_success(db, runs, run, task_id, state)

    try:
        return _run_async(_run())
    except Exception as exc:
        logger.exception("start_report_task failed for report run %s", run_id)
        _run_async(_record_trace_failure(run_id, trace_context["user_id"], trace_context["step_id"], exc))
        _run_async(_mark_failure(run_id, "LANGGRAPH_START_FAILED", exc))
        raise


@shared_task(bind=True, name="resume_report_task")
def resume_report_task(self, run_id: int):
    """Resume the checkpointer state using the review stored in PostgreSQL."""
    task_id = _task_id(self)
    trace_context = {"user_id": None, "step_id": None}

    async def _run():
        async with _session_factory()() as db:
            runs = AgentRunRepository()
            run = await runs.get_by_id(db, run_id)
            if run is None:
                raise LookupError("agent run does not exist")
            if run.status != AgentRunStatus.RESUME_QUEUED.value:
                pending = await HumanReviewRepository().get_pending_review(db, run_id)
                result = {"run_id": run_id, "status": run.status}
                if pending is not None:
                    result["review_id"] = pending.id
                return result
            review = await _latest_submitted_review(db, run_id)
            if review is None or review.action is None:
                raise ValueError("submitted review does not exist")
            resumed = await runs.compare_and_set_status(
                session=db,
                run_id=run_id,
                expected_status=AgentRunStatus.RESUME_QUEUED,
                new_status=AgentRunStatus.RESUMED,
                current_node="human_review",
                current_task_id=task_id,
            )
            if resumed is None:
                current = await runs.get_by_id(db, run_id)
                return {"run_id": run_id, "status": current.status if current else "UNKNOWN"}
            run = resumed
            await db.commit()
            await _write_projection(
                run_id=run_id, status=AgentRunStatus.RESUMED.value, current_node="human_review",
                progress=75, review_required=False, review_id=review.id,
                task_id=task_id, status_version=run.status_version,
            )
            running = await runs.compare_and_set_status(
                session=db,
                run_id=run_id,
                expected_status=AgentRunStatus.RESUMED,
                new_status=AgentRunStatus.RUNNING,
                current_node="planner",
                current_task_id=task_id,
            )
            if running is None:
                current = await runs.get_by_id(db, run_id)
                if current is not None and current.status in {
                    AgentRunStatus.RUNNING.value,
                    AgentRunStatus.WAITING_HUMAN.value,
                    AgentRunStatus.SUCCESS.value,
                    AgentRunStatus.FAILURE.value,
                }:
                    return {"run_id": run_id, "status": current.status}
                return {"run_id": run_id, "status": current.status if current else "UNKNOWN"}
            run = running
            await db.commit()
            await _write_projection(
                run_id=run_id, status=AgentRunStatus.RUNNING.value, current_node="planner",
                progress=80, review_required=False, review_id=review.id,
                task_id=task_id, status_version=run.status_version,
            )
            trace_id = await _record_trace_start(
                db, run, task_id, "langgraph_resume", {"review_id": review.id, "action": review.action}
            )
            trace_context.update(user_id=run.user_id, step_id=trace_id)
            checkpointer = get_postgres_checkpointer()
            graph = build_report_run_graph(checkpointer=checkpointer)
            config = build_graph_config(getattr(run, "thread_id", None) or run.id)
            resume_payload = {
                "action": review.action,
                "feedback": review.feedback,
                "edited_report": review.edited_report,
                "review_id": review.id,
            }
            chunks, state, snapshot = await _stream_report_graph(
                graph, Command(resume=resume_payload), config
            )
            interrupt_payload = extract_interrupt_payload(chunks)
            if interrupt_payload is not None:
                interrupt_payload["checkpoint_id"] = _checkpoint_id(snapshot)
                await _record_trace_end(
                    db, run, trace_id, "langgraph_reinterrupt",
                    {"review_round": interrupt_payload.get("review_round")},
                )
                result = await _create_pending_review(db, run, task_id, interrupt_payload)
                return {
                    "run_id": run_id,
                    "status": AgentRunStatus.WAITING_HUMAN.value,
                    "review_id": result["review"]["id"],
                }
            await _record_trace_end(
                db, run, trace_id, "langgraph_success",
                {"output_keys": sorted(state.keys())},
            )
            if state.get("workflow_status") == "failed":
                raise ValueError(state.get("error_message") or "LangGraph workflow failed")
            return await _mark_success(db, runs, run, task_id, state, review_action=review.action)

    try:
        return _run_async(_run())
    except Exception as exc:
        logger.exception("resume_report_task failed for report run %s", run_id)
        _run_async(_record_trace_failure(run_id, trace_context["user_id"], trace_context["step_id"], exc))
        _run_async(_mark_failure(run_id, "LANGGRAPH_RESUME_FAILED", exc))
        raise


@shared_task(bind=True, name="generate_report", max_retries=2, default_retry_delay=60)
def generate_report_task(
    self,
    user_id: int,
    research_topic: str,
    kb_collections: list = None,
    max_iterations: int = 3,
    use_react: bool = True,
):
    """Async generate a full research report by running the LangGraph workflow."""

    async def _run():
        from backend.workflow.graph import graph
        initial_state = {
            "research_topic": research_topic,
            "user_id": user_id,
            "max_iterations": max_iterations,
            "kb_collections": kb_collections or [],
            "model_override": None,
            "iteration_count": 0,
            "workflow_status": "running",
            "agent_trace": [],
            "use_react": use_react,
            "messages": [],
        }

        self.update_state(
            state="PROGRESS",
            meta={"step": "workflow_running", "topic": research_topic[:100]},
        )

        config = {"configurable": {"thread_id": f"task-report-{self.request.id}"}}
        final_state = await graph.ainvoke(initial_state, config)

        final_report = final_state.get("final_report", "")
        report_sections = final_state.get("report_sections", [])
        retrieved_docs = final_state.get("retrieved_docs", [])

        sections_data = sanitize_for_json(report_sections) if report_sections else None
        sources_data = sanitize_for_json(retrieved_docs) if retrieved_docs else None

        async with _session_factory()() as db:
            report = ResearchReport(
                user_id=user_id,
                title=research_topic[:100],
                content=final_report,
                sections=sections_data,
                sources=sources_data,
                status="completed",
            )
            db.add(report)
            await db.commit()

            return {
                "report_id": report.id,
                "title": research_topic[:100],
                "status": "completed",
                "content_length": len(final_report),
            }

    try:
        return _run_async(_run())
    except Exception as exc:
        logger.error("generate_report task failed: %s", exc)

        async def _save_failed():
            async with _session_factory()() as db:
                report = ResearchReport(
                    user_id=user_id,
                    title=research_topic[:100],
                    content="报告生成失败: generate_report failed",
                    status="failed",
                )
                db.add(report)
                await db.commit()

        try:
            _run_async(_save_failed())
        except Exception:
            logger.exception("Failed to save failed report record")

        raise self.retry(exc=exc)


@shared_task(bind=True, name="batch_search", max_retries=2, default_retry_delay=30)
def batch_search_task(self, queries: list, max_results_per_query: int = 5):
    """Batch ArXiv search across multiple queries in parallel."""

    results = []
    total = len(queries)

    def _search_one(query: str):
        docs = _search_arxiv_sync(query, max_results=max_results_per_query)
        return {
            "query": query,
            "results": [
                {"title": d.title, "source": d.source, "url": d.url}
                for d in docs
            ],
            "count": len(docs),
        }

    try:
        with ThreadPoolExecutor(max_workers=min(total, 5)) as pool:
            futures = {pool.submit(_search_one, q): q for q in queries}
            for i, future in enumerate(as_completed(futures)):
                self.update_state(
                    state="PROGRESS",
                    meta={"step": "searching", "current": i + 1, "total": total},
                )
                results.append(future.result())

        return {"queries": queries, "total_results": sum(r["count"] for r in results), "results": results}

    except Exception as exc:
        logger.error("batch_search task failed: %s", exc)
        raise self.retry(exc=exc)
