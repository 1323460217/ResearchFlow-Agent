"""Run a safe transient-exception pilot for start_report_task."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from celery.result import AsyncResult

from audit_celery_idempotency import (  # noqa: E402
    db_snapshot,
    free_port,
    register_login,
    start_process,
    stop_process,
    wait_until,
    wait_status,
)
from backend.checkpoint.postgres_checkpointer import get_checkpoint_database_url  # noqa: E402


def main():
    log_dir = Path(tempfile.mkdtemp(prefix="researchflow-failure-audit-"))
    port = free_port()
    api = start_process(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port), "--log-level", "info"],
        log_dir / "api.log",
    )
    worker = None
    marker = f"audit_failure_{uuid4().hex[:12]}"
    run_id = None
    try:
        base_url = f"http://127.0.0.1:{port}"
        wait_until("FastAPI health", lambda: api.poll() is None and httpx.get(f"{base_url}/api/health", timeout=2).status_code == 200)
        with httpx.Client(base_url=base_url, timeout=10) as client:
            headers = register_login(client, marker)
            created = client.post(
                "/api/report-runs", headers=headers,
                json={"query": marker, "options": {"use_react": False}, "client_request_id": marker},
            )
            created.raise_for_status()
            run_data = created.json()["data"]
            run_id = int(run_data["run_id"])
            thread_id = str(run_data["thread_id"])
            first_task_id = str(run_data["celery_task_id"])

        worker = start_process(
            [sys.executable, "scripts/audit_failure_worker.py", "--worker-process", "--hostname", f"audit-failure-{uuid4().hex[:6]}@%h"],
            log_dir / "worker.log",
        )
        wait_until("failure worker", lambda: worker.poll() is None and " ready." in (log_dir / "worker.log").read_text(encoding="utf-8", errors="replace"))
        first = AsyncResult(first_task_id)
        wait_until("first task failure", lambda: first.ready())
        second = __import__("backend.worker.celery_app", fromlist=["celery_app"]).celery_app.send_task(
            "start_report_task", args=[run_id], queue="researchflow"
        )
        wait_until("second task completion", lambda: AsyncResult(second.id).ready())
        snapshot = db_snapshot(run_id, thread_id)
        print(json.dumps({
            "run_id": run_id,
            "first_task": {"id": first.id, "state": first.state, "result": repr(first.result)},
            "second_task": {"id": str(second.id), "state": AsyncResult(second.id).state, "result": repr(AsyncResult(second.id).result)},
            "failure_node_log": (log_dir / "worker.log").read_text(encoding="utf-8", errors="replace").count("AUDIT_FAILURE_NODE_CALL="),
            "snapshot": snapshot,
            "interpretation": "No automatic retry; second delivery is terminal-state guarded after first failure.",
        }, ensure_ascii=False, indent=2, default=str))
    finally:
        stop_process(worker)
        stop_process(api)
        if run_id is not None:
            try:
                with psycopg.connect(get_checkpoint_database_url()) as connection:
                    connection.execute("delete from agent_runs where id = %s", (run_id,))
                    connection.execute("delete from users where username = %s", (marker,))
                    connection.commit()
            except Exception as exc:
                print(f"cleanup failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
