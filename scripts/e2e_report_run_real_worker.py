"""Run the report-run HITL flow through real OS processes.

The harness starts an independent Celery worker and Uvicorn process.  The
worker-process mode installs the same minimal test graph used by the eager
smoke test, so no external LLM/RAG service is called.  Celery, Kombu, Redis,
PostgreSQL, and LangGraph PostgreSQL checkpointing remain real.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from redis import Redis

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _tail(path: Path, lines: int = 60) -> str:
    if not path.exists():
        return "<log file does not exist>"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def _wait_until(label: str, predicate, timeout: float, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:  # readiness probes should keep retrying
            last_error = exc
        time.sleep(interval)
    detail = f"; last error: {last_error}" if last_error else ""
    raise TimeoutError(f"{label} was not ready within {timeout:.1f}s{detail}")


def _worker_process(args) -> int:
    """Celery worker entrypoint, executed in a separate OS process."""

    from backend.worker import tasks_report
    from backend.worker.celery_app import celery_app
    from scripts.e2e_report_run_hitl import build_minimal_e2e_graph

    # This is test-harness injection in the worker process only. It avoids
    # external LLM/RAG calls while retaining the production task wrapper.
    tasks_report.build_report_run_graph = build_minimal_e2e_graph
    if celery_app.conf.task_always_eager:
        raise RuntimeError("task_always_eager must remain False in worker mode")

    argv = [
        "worker",
        "--loglevel",
        "info",
        "--pool",
        "solo",
        "--hostname",
        args.hostname,
        "--queues",
        "researchflow",
        "--without-mingle",
        "--without-gossip",
        "--without-heartbeat",
    ]
    celery_app.worker_main(argv)
    return 0


def _start_process(command: list[str], log_path: Path) -> subprocess.Popen:
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    process._e2e_log = log  # type: ignore[attr-defined]
    return process


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    log = getattr(process, "_e2e_log", None)
    if log is not None:
        log.close()


def _redis_ping(url: str) -> bool:
    client = Redis.from_url(url, decode_responses=True)
    try:
        return bool(client.ping())
    finally:
        client.close()


def _db_connection():
    from backend.checkpoint.postgres_checkpointer import get_checkpoint_database_url

    return psycopg.connect(get_checkpoint_database_url())


def _checkpoint_counts(connection, thread_id: str) -> dict[str, int]:
    return {
        table: int(
            connection.execute(
                f"select count(*) from {table} where thread_id = %s",  # noqa: S608
                (thread_id,),
            ).fetchone()[0]
        )
        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs")
    }


def _legacy_and_checkpoint_evidence(connection, thread_id: str) -> dict[str, object]:
    tables = [
        row[0]
        for row in connection.execute(
            """select table_name from information_schema.tables
               where table_schema = 'public'
                 and table_name in ('checkpoints', 'checkpoint_writes',
                                    'checkpoint_blobs', 'checkpoint_migrations')
               order by table_name"""
        ).fetchall()
    ]
    return {"tables": tables, "thread_id_counts": _checkpoint_counts(connection, thread_id)}


def _run_api_flow(client: httpx.Client, marker: str, action: str, timeout: float) -> dict[str, object]:
    username = f"{marker}_{action}"[:90]
    email = f"{username}@example.com"
    password = "E2E-real-worker-password-123"
    register = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    if register.status_code >= 400:
        raise RuntimeError(f"register failed: {register.status_code} {register.text}")
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    if login.status_code >= 400:
        raise RuntimeError(f"login failed: {login.status_code} {login.text}")
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/api/report-runs",
        headers=headers,
        json={
            "query": f"{marker}: real worker {action}",
            "options": {"use_react": False},
            "client_request_id": f"{marker}-{action}",
        },
    )
    if created.status_code >= 400:
        raise RuntimeError(f"report-run create failed: {created.status_code} {created.text}")
    run_data = created.json()["data"]
    run_id = int(run_data["run_id"])
    task_id = run_data["celery_task_id"]
    thread_id = str(run_data["thread_id"])
    started_at = time.time()

    def waiting():
        response = client.get(f"/api/report-runs/{run_id}/status", headers=headers)
        response.raise_for_status()
        data = response.json()["data"]
        return data if data["status"] == "WAITING_HUMAN" else None

    waiting_status = _wait_until("report run WAITING_HUMAN", waiting, timeout)
    pending_response = client.get(f"/api/report-runs/{run_id}/pending-review", headers=headers)
    pending_response.raise_for_status()
    pending = pending_response.json()["data"]["review"]
    if not pending or pending["status"] != "PENDING":
        raise RuntimeError(f"pending review missing: {pending!r}")
    review_id = int(pending["id"])

    redis_status = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    try:
        projection = redis_status.hgetall(f"report_run:{run_id}:status")
    finally:
        redis_status.close()
    if projection.get("status") != "WAITING_HUMAN" or projection.get("review_required") != "true":
        raise RuntimeError(f"invalid Redis waiting projection: {projection!r}")

    with _db_connection() as connection:
        checkpoint = _legacy_and_checkpoint_evidence(connection, thread_id)
    if checkpoint["thread_id_counts"]["checkpoints"] <= 0:
        raise RuntimeError(f"no PostgreSQL checkpoint for thread {thread_id}")

    return {
        "username": username,
        "run_id": run_id,
        "task_id": task_id,
        "thread_id": thread_id,
        "review_id": review_id,
        "waiting_status": waiting_status,
        "redis_waiting_projection": projection,
        "postgres_checkpoint": checkpoint,
        "created_to_waiting_seconds": round(time.time() - started_at, 3),
        "headers": headers,
        "pending_review": pending,
    }


def _resume(client: httpx.Client, flow: dict[str, object], action: str, timeout: float) -> dict[str, object]:
    run_id = int(flow["run_id"])
    headers = flow["headers"]
    payload = {
        "review_id": int(flow["review_id"]),
        "action": action,
        "idempotency_key": f"{flow['run_id']}-{action}-{uuid4().hex}",
    }
    if action == "edit":
        payload["edited_report"] = "# E2E_REAL_WORKER_EDIT\n\nEdited report content."
    if action == "reject":
        payload["feedback"] = "E2E_REAL_WORKER_REJECT: revise this draft"
    response = client.post(f"/api/report-runs/{run_id}/resume", headers=headers, json=payload)
    response.raise_for_status()
    resume_data = response.json()["data"]

    def current_status():
        result = client.get(f"/api/report-runs/{run_id}/status", headers=headers)
        result.raise_for_status()
        return result.json()["data"]

    expected = "WAITING_HUMAN" if action == "reject" else "SUCCESS"

    def expected_status():
        data = current_status()
        return data if data["status"] == expected else None

    status = _wait_until(f"resume {action} {expected}", expected_status, timeout)
    evidence: dict[str, object] = {}
    if action in {"approve", "edit"}:
        with _db_connection() as connection:
            report = connection.execute(
                "select id, generation_status, review_action, content from research_reports where agent_run_id = %s",
                (run_id,),
            ).fetchone()
        if report is None or report[1] != "SUCCESS":
            raise RuntimeError(f"ResearchReport was not persisted successfully for run {run_id}: {report!r}")
        if action == "edit" and "E2E_REAL_WORKER_EDIT" not in str(report[3]):
            raise RuntimeError(f"edited report content was not persisted for run {run_id}: {report!r}")
        evidence["research_report"] = {
            "id": int(report[0]),
            "generation_status": report[1],
            "review_action": report[2],
            "edited_content_verified": action != "edit" or "E2E_REAL_WORKER_EDIT" in str(report[3]),
        }
    else:
        pending_response = client.get(f"/api/report-runs/{run_id}/pending-review", headers=headers)
        pending_response.raise_for_status()
        pending_review = pending_response.json()["data"]["review"]
        if not pending_review or pending_review["status"] != "PENDING":
            raise RuntimeError(f"reject did not create a new PENDING review: {pending_review!r}")
        evidence["next_pending_review"] = pending_review
    return {"resume_request": resume_data, "status": status, **evidence}

def _cleanup(connection, run_ids: list[int], usernames: list[str]) -> None:
    if run_ids:
        connection.execute("delete from agent_runs where id = any(%s)", (run_ids,))
    if usernames:
        connection.execute("delete from users where username = any(%s)", (usernames,))
    if run_ids:
        redis_status = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        try:
            redis_status.delete(*(f"report_run:{run_id}:status" for run_id in run_ids))
        finally:
            redis_status.close()
    connection.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-process", action="store_true")
    parser.add_argument("--hostname", default=f"e2e-worker-{uuid4().hex[:8]}@%h")
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--keep-data", action="store_true")
    args = parser.parse_args()
    if args.worker_process:
        return _worker_process(args)

    from backend.checkpoint.postgres_checkpointer import (
        get_checkpoint_database_url,
        mask_database_url,
        setup_postgres_checkpointer,
    )
    from backend.core.config import settings
    from backend.worker.celery_app import celery_app

    if celery_app.conf.task_always_eager:
        raise RuntimeError("task_always_eager must be False")
    setup_postgres_checkpointer()
    marker = f"e2e_real_worker_{uuid4().hex[:10]}"
    log_dir = PROJECT_ROOT / "scripts" / ".e2e-real-worker-logs"
    log_dir.mkdir(exist_ok=True)
    api_log = log_dir / f"{marker}-api.log"
    worker_log = log_dir / f"{marker}-worker-1.log"
    worker_restart_log = log_dir / f"{marker}-worker-2.log"
    worker_edit_log = log_dir / f"{marker}-worker-3-edit-start.log"
    worker_edit_resume_log = log_dir / f"{marker}-worker-4-edit-resume.log"
    worker_reject_log = log_dir / f"{marker}-worker-5-reject-start.log"
    worker_reject_resume_log = log_dir / f"{marker}-worker-6-reject-resume.log"
    api_process = None
    worker_process = None

    def restart_worker(log_path: Path, label: str) -> None:
        nonlocal worker_process
        _stop_process(worker_process)
        worker_process = _start_process(
            [sys.executable, str(Path(__file__)), "--worker-process", "--hostname", args.hostname],
            log_path,
        )
        _wait_until(
            label,
            lambda: worker_process.poll() is None and " ready." in log_path.read_text(encoding="utf-8", errors="replace"),
            args.timeout,
        )

    run_ids: list[int] = []
    usernames: list[str] = []
    result: dict[str, object] = {
        "process_topology": {"redis": settings.REDIS_URL, "celery": "independent subprocess", "fastapi": "independent subprocess", "client": "parent process"},
        "worker_configuration": {"task_always_eager": False, "pool": "solo", "broker": settings.CELERY_BROKER_URL},
        "postgres_url": mask_database_url(get_checkpoint_database_url()),
    }
    try:
        if not _redis_ping(settings.REDIS_URL) or not _redis_ping(settings.CELERY_BROKER_URL):
            raise RuntimeError("Redis PING failed")
        api_process = _start_process(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(args.port), "--log-level", "info"],
            api_log,
        )
        _wait_until(
            "FastAPI health",
            lambda: httpx.get(f"http://127.0.0.1:{args.port}/api/health", timeout=2).status_code == 200,
            args.timeout,
        )
        _wait_until(
            "FastAPI report-run route",
            lambda: "/api/report-runs" in httpx.get(f"http://127.0.0.1:{args.port}/openapi.json", timeout=2).text,
            args.timeout,
        )
        worker_process = _start_process(
            [sys.executable, str(Path(__file__)), "--worker-process", "--hostname", args.hostname],
            worker_log,
        )
        _wait_until(
            "Celery worker ready",
            lambda: worker_process.poll() is None and " ready." in worker_log.read_text(encoding="utf-8", errors="replace"),
            args.timeout,
        )
        result["readiness"] = {"redis_ping": True, "fastapi_health": True, "fastapi_report_run_route": True, "celery_worker_ready": True}

        with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=10) as client:
            approve = _run_api_flow(client, marker, "approve", args.timeout)
            run_ids.append(int(approve["run_id"]))
            usernames.append(str(approve["username"]))
            result["approve_waiting"] = {key: value for key, value in approve.items() if key != "headers"}
            # Restart only the worker while the run is WAITING_HUMAN. FastAPI
            # remains up to keep the control variable narrow; resume must use
            # the PostgreSQL checkpoint from the new worker process.
            restart_worker(worker_restart_log, "restarted Celery worker ready")
            result["approve_resume"] = _resume(client, approve, "approve", args.timeout)

            # Windows solo workers must not reuse the asyncpg pool across
            # separate asyncio.run() task loops. Keep edit/reject lightweight,
            # but isolate each real task in a fresh external worker process.
            restart_worker(worker_edit_log, "edit worker ready")
            edit = _run_api_flow(client, marker, "edit", args.timeout)
            run_ids.append(int(edit["run_id"]))
            usernames.append(str(edit["username"]))
            result["edit_waiting"] = {key: value for key, value in edit.items() if key != "headers"}
            restart_worker(worker_edit_resume_log, "edit resume worker ready")
            result["edit_resume"] = _resume(client, edit, "edit", args.timeout)

            restart_worker(worker_reject_log, "reject worker ready")
            reject = _run_api_flow(client, marker, "reject", args.timeout)
            run_ids.append(int(reject["run_id"]))
            usernames.append(str(reject["username"]))
            result["reject_waiting"] = {key: value for key, value in reject.items() if key != "headers"}
            restart_worker(worker_reject_resume_log, "reject resume worker ready")
            result["reject_resume"] = _resume(client, reject, "reject", args.timeout)

        worker_logs = (
            worker_log,
            worker_restart_log,
            worker_edit_log,
            worker_edit_resume_log,
            worker_reject_log,
            worker_reject_resume_log,
        )
        worker_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in worker_logs)
        result["non_eager_evidence"] = {
            "task_always_eager": False,
            "received": bool(re.search(r"Task start_report_task\[[^]]+\] received", worker_text)),
            "started": bool(re.search(r"Task start_report_task\[[^]]+\] succeeded", worker_text)),
            "resume_received": bool(re.search(r"Task resume_report_task\[[^]]+\] received", worker_text)),
            "resume_completed": bool(re.search(r"Task resume_report_task\[[^]]+\] succeeded", worker_text)),
            "worker_log_tail": _tail(worker_log),
            "worker_restart_log_tail": _tail(worker_restart_log),
            "worker_edit_log_tail": _tail(worker_edit_log),
            "worker_edit_resume_log_tail": _tail(worker_edit_resume_log),
            "worker_reject_log_tail": _tail(worker_reject_log),
            "worker_reject_resume_log_tail": _tail(worker_reject_resume_log),
        }
        evidence = result["non_eager_evidence"]
        if evidence["task_always_eager"] or not all(
            value
            for key, value in evidence.items()
            if not key.endswith("_log_tail") and key != "task_always_eager"
        ):
            raise RuntimeError("worker log did not contain complete received/succeeded evidence")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"REAL WORKER E2E FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"API LOG TAIL:\n{_tail(api_log)}", file=sys.stderr)
        print(f"WORKER LOG TAIL:\n{_tail(worker_log)}\n--- RESTART WORKER ---\n{_tail(worker_restart_log)}\n--- EDIT START ---\n{_tail(worker_edit_log)}\n--- EDIT RESUME ---\n{_tail(worker_edit_resume_log)}\n--- REJECT START ---\n{_tail(worker_reject_log)}\n--- REJECT RESUME ---\n{_tail(worker_reject_resume_log)}", file=sys.stderr)
        return 1
    finally:
        _stop_process(worker_process)
        _stop_process(api_process)
        if not args.keep_data:
            try:
                with _db_connection() as connection:
                    _cleanup(connection, run_ids, usernames)
            except Exception as cleanup_exc:
                print(f"cleanup failed: {cleanup_exc}", file=sys.stderr)
        else:
            print(f"business data retained for run_ids={run_ids}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
