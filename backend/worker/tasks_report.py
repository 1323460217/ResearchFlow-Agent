import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from celery import shared_task

from backend.api.serialization import sanitize_for_json
from backend.database.session import async_session_factory
from backend.models.research_report import ResearchReport
from backend.workflow.agents.retriever import _search_arxiv_sync
from backend.workflow.graph import graph

logger = logging.getLogger(__name__)


def _run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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

        async with async_session_factory() as db:
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
            async with async_session_factory() as db:
                report = ResearchReport(
                    user_id=user_id,
                    title=research_topic[:100],
                    content=f"报告生成失败: {exc}",
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
