"""External solo worker for the report-run transient-failure pilot."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from backend.api.serialization import sanitize_for_json  # noqa: E402
from backend.worker import tasks_report  # noqa: E402
from backend.worker.celery_app import celery_app  # noqa: E402
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


calls = 0


def failure_once_graph(checkpointer):
    def failure_once_node(state: ResearchState) -> dict[str, Any]:
        global calls
        calls += 1
        print(f"AUDIT_FAILURE_NODE_CALL={calls}", flush=True)
        if calls == 1:
            raise RuntimeError("AUDIT_TRANSIENT_FAILURE_ONCE")
        return {
            "final_report": "# AUDIT_FAILURE_RECOVERED\n\nRecovered draft.",
            "report_sections": [],
            "key_findings": ["failure injection recovered"],
            "workflow_status": "completed",
        }

    builder = StateGraph(ResearchState)
    builder.add_node("failure_once", failure_once_node)
    builder.add_node("human_review", human_review_node)
    builder.add_node(FINALIZE, finalize_report_node)
    builder.add_node(REWRITE_REPORTER, prepare_reporter_revision_node)
    builder.add_node(REVIEW_LIMIT, lambda state: {"workflow_status": "failed"})
    builder.add_edge(START, "failure_once")
    builder.add_edge("failure_once", "human_review")
    builder.add_conditional_edges("human_review", route_after_human_review, {
        FINALIZE: FINALIZE,
        REWRITE_REPORTER: REWRITE_REPORTER,
        REVIEW_LIMIT: REVIEW_LIMIT,
    })
    builder.add_edge(REWRITE_REPORTER, "human_review")
    builder.add_edge(FINALIZE, END)
    builder.add_edge(REVIEW_LIMIT, END)
    return builder.compile(checkpointer=checkpointer)


def main():
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument("--worker-process", action="store_true")
    parser.add_argument("--hostname", default="audit-failure@%h")
    args = parser.parse_args()
    if not args.worker_process:
        raise SystemExit("use --worker-process")
    tasks_report.build_report_run_graph = failure_once_graph
    celery_app.worker_main([
        "worker", "--loglevel", "info", "--pool", "solo",
        "--hostname", args.hostname, "--queues", "researchflow",
        "--without-mingle", "--without-gossip", "--without-heartbeat",
    ])


if __name__ == "__main__":
    main()
