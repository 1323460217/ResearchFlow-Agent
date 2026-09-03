"""Run the near-simultaneous duplicate API resume pilot."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx

from audit_celery_idempotency import (  # noqa: E402
    PROJECT_ROOT,
    db_snapshot,
    free_port,
    register_login,
    start_process,
    stop_process,
    wait_until,
    wait_status,
)


def main():
    log_dir = Path(__file__).resolve().parent / ".audit-api-duplicate-logs"
    log_dir.mkdir(exist_ok=True)
    api_log = log_dir / "api.log"
    port = free_port()
    api = start_process(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port), "--log-level", "info"],
        api_log,
    )
    marker = f"audit_api_duplicate_{uuid4().hex[:12]}"
    run_id = None
    try:
        base_url = f"http://127.0.0.1:{port}"
        wait_until("FastAPI health", lambda: api.poll() is None and httpx.get(f"{base_url}/api/health", timeout=2).status_code == 200)
        with httpx.Client(base_url=base_url, timeout=10) as client:
            headers = register_login(client, marker)
            create = client.post(
                "/api/report-runs",
                headers=headers,
                json={"query": marker, "options": {"use_react": False}, "client_request_id": marker},
            )
            create.raise_for_status()
            data = create.json()["data"]
            run_id = int(data["run_id"])

        worker_script = PROJECT_ROOT / "scripts" / "e2e_report_run_real_worker.py"
        workers = []
        for index in (1, 2):
            workers.append(start_process(
                [sys.executable, str(worker_script), "--worker-process", "--hostname", f"api-dup-start-{index}@%h"],
                log_dir / f"start-{index}.log",
            ))
        try:
            for index, worker in enumerate(workers):
                wait_until(f"worker {index + 1}", lambda w=worker: w.poll() is None)
            with httpx.Client(base_url=base_url, timeout=10) as client:
                waiting = wait_status(client, headers, run_id, "WAITING_HUMAN")
                pending = client.get(f"/api/report-runs/{run_id}/pending-review", headers=headers)
                pending.raise_for_status()
                review_id = int(pending.json()["data"]["review"]["id"])
            for worker in workers:
                stop_process(worker)

            key = f"{run_id}:{review_id}:approve"
            def submit_once():
                with httpx.Client(base_url=base_url, timeout=10) as client:
                    response = client.post(
                        f"/api/report-runs/{run_id}/resume",
                        headers=headers,
                        json={"review_id": review_id, "action": "approve", "idempotency_key": key},
                    )
                    return {"status_code": response.status_code, "body": response.json()}

            with ThreadPoolExecutor(max_workers=2) as executor:
                api_results = list(executor.map(lambda _: submit_once(), (1, 2)))
            print(json.dumps({
                "run_id": run_id,
                "review_id": review_id,
                "waiting": waiting,
                "business_idempotency_key": key,
                "api_duplicate_results": api_results,
                "db_after_api_only": db_snapshot(run_id, str(run_id)),
            }, ensure_ascii=False, indent=2, default=str))
        finally:
            for worker in workers:
                stop_process(worker)
    finally:
        stop_process(api)
        if run_id is not None:
            try:
                import psycopg
                from backend.checkpoint.postgres_checkpointer import get_checkpoint_database_url
                with psycopg.connect(get_checkpoint_database_url()) as connection:
                    connection.execute("delete from agent_runs where id = %s", (run_id,))
                    connection.execute("delete from users where username = %s", (marker,))
                    connection.commit()
            except Exception as exc:
                print(f"cleanup failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
