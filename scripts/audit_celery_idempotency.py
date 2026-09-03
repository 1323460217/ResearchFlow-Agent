"""Run duplicate-delivery pilots against the real broker, DB, API, and workers.

The worker subprocesses use the deterministic minimal graph from
``e2e_report_run_real_worker``.  No real LLM, RAG, or MCP service is called.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from celery.result import AsyncResult
from redis import Redis

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.checkpoint.postgres_checkpointer import (  # noqa: E402
    get_checkpoint_database_url,
    mask_database_url,
    setup_postgres_checkpointer,
)
from backend.core.config import settings  # noqa: E402
from backend.worker.celery_app import celery_app  # noqa: E402


def wait_until(label, predicate, timeout=60.0, interval=0.25):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:
            last_error = exc
        time.sleep(interval)
    raise TimeoutError(f"{label} not ready; last_error={last_error!r}")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_process(command, log_path):
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    process._audit_log = log  # type: ignore[attr-defined]
    return process


def stop_process(process):
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    log = getattr(process, "_audit_log", None)
    if log is not None:
        log.close()


def log_text(path):
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def db_snapshot(run_id, thread_id):
    with psycopg.connect(get_checkpoint_database_url()) as connection:
        run = connection.execute(
            """select status, status_version, current_task_id, current_node,
                      human_review_round, iteration_count
               from agent_runs where id = %s""",
            (run_id,),
        ).fetchone()
        reviews = connection.execute(
            """select id, review_round, status, action, idempotency_key
               from human_reviews where run_id = %s order by id""",
            (run_id,),
        ).fetchall()
        report_rows = connection.execute(
            """select id, report_revision, generation_status, review_action
               from research_reports where agent_run_id = %s order by id""",
            (run_id,),
        ).fetchall()
        steps = connection.execute(
            """select node_name, status, count(*)
               from agent_run_steps where run_id = %s
               group by node_name, status order by node_name, status""",
            (run_id,),
        ).fetchall()
        checkpoints = {}
        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            checkpoints[table] = connection.execute(
                f"select count(*) from {table} where thread_id = %s",  # noqa: S608
                (thread_id,),
            ).fetchone()[0]
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        projection = redis_client.hgetall(f"report_run:{run_id}:status")
    finally:
        redis_client.close()
    return {
        "run": dict(zip(
            ("status", "status_version", "current_task_id", "current_node",
             "human_review_round", "iteration_count"), run or (), strict=False
        )),
        "reviews": [dict(zip(
            ("id", "review_round", "status", "action", "idempotency_key"), row, strict=False
        )) for row in reviews],
        "research_reports": [dict(zip(
            ("id", "report_revision", "generation_status", "review_action"), row, strict=False
        )) for row in report_rows],
        "steps": [dict(zip(("node_name", "status", "count"), row, strict=False)) for row in steps],
        "checkpoints": checkpoints,
        "redis_projection": projection,
    }


def register_login(client, marker):
    password = "audit-reliability-password-123"
    response = client.post(
        "/api/auth/register",
        json={"username": marker, "email": f"{marker}@example.com", "password": password},
    )
    response.raise_for_status()
    response = client.post("/api/auth/login", json={"username": marker, "password": password})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def create_run(client, headers, marker):
    response = client.post(
        "/api/report-runs",
        headers=headers,
        json={
            "query": f"{marker}: deterministic idempotency audit",
            "options": {"use_react": False},
            "client_request_id": marker,
        },
    )
    response.raise_for_status()
    return response.json()["data"]


def wait_status(client, headers, run_id, expected, timeout=60):
    def read():
        response = client.get(f"/api/report-runs/{run_id}/status", headers=headers)
        response.raise_for_status()
        data = response.json()["data"]
        return data if data["status"] == expected else None

    return wait_until(f"run {run_id} status {expected}", read, timeout)


def submit_resume(client, headers, run_id, review_id, key):
    response = client.post(
        f"/api/report-runs/{run_id}/resume",
        headers=headers,
        json={"review_id": review_id, "action": "approve", "idempotency_key": key},
    )
    return {"status_code": response.status_code, "body": response.json()}


def wait_results(task_ids, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        results = [AsyncResult(task_id, app=celery_app) for task_id in task_ids]
        if all(item.ready() for item in results):
            return [
                {"id": item.id, "state": item.state, "result": repr(item.result)}
                for item in results
            ]
        time.sleep(0.25)
    return [
        {"id": task_id, "state": AsyncResult(task_id, app=celery_app).state, "result": "TIMEOUT"}
        for task_id in task_ids
    ]


def enqueue_duplicate(task_name, run_id, first_task_id):
    duplicate = celery_app.send_task(task_name, args=[run_id], queue="researchflow")
    return [first_task_id, str(duplicate.id)]


def run_pilot(client, headers, label, worker_script, log_dir, action="start"):
    marker = f"audit_{label}_{uuid4().hex[:10]}"
    run_data = create_run(client, headers, marker)
    run_id = int(run_data["run_id"])
    thread_id = str(run_data["thread_id"])
    first_task_id = str(run_data["celery_task_id"])
    task_name = "start_report_task" if action == "start" else "resume_report_task"
    worker_processes = []
    worker_logs = []

    def launch_workers(suffix):
        for index in (1, 2):
            log_path = log_dir / f"{label}-{suffix}-worker-{index}.log"
            worker_logs.append(log_path)
            worker_processes.append(start_process(
                [sys.executable, str(worker_script), "--worker-process",
                 "--hostname", f"audit-{label}-{suffix}-{index}@%h"],
                log_path,
            ))
        for index, process in enumerate(worker_processes[-2:]):
            path = worker_logs[-2 + index]
            wait_until(
                f"{label} worker {index + 1}",
                lambda p=process, path=path: p.poll() is None and " ready." in log_text(path),
            )

    launch_workers("start")
    start_task_ids = enqueue_duplicate(task_name, run_id, first_task_id)
    if action == "start":
        wait_status(client, headers, run_id, "WAITING_HUMAN")
        start_results = wait_results(start_task_ids)
        snapshot = db_snapshot(run_id, thread_id)
        for process in worker_processes:
            stop_process(process)
        return {
            "run_id": run_id,
            "thread_id": thread_id,
            "task_ids": start_task_ids,
            "task_results": start_results,
            "worker_received_count": sum(log_text(path).count(f"Task {task_name}[") for path in worker_logs),
            "worker_succeeded_count": sum(log_text(path).count(f"succeeded") for path in worker_logs),
            "snapshot": snapshot,
        }

    waiting = wait_status(client, headers, run_id, "WAITING_HUMAN")
    start_results = wait_results(start_task_ids)
    pending = client.get(f"/api/report-runs/{run_id}/pending-review", headers=headers)
    pending.raise_for_status()
    review = pending.json()["data"]["review"]
    review_id = int(review["id"])
    for process in worker_processes:
        stop_process(process)

    resume_key = f"{run_id}:{review_id}:approve"
    first_resume = submit_resume(client, headers, run_id, review_id, resume_key)
    if first_resume["status_code"] >= 400:
        raise RuntimeError(f"first resume failed: {first_resume!r}")
    queued = first_resume["body"]["data"]
    resume_task_ids = enqueue_duplicate("resume_report_task", run_id, queued["celery_task_id"])
    launch_workers("resume")
    wait_status(client, headers, run_id, "SUCCESS")
    resume_results = wait_results(resume_task_ids)
    snapshot = db_snapshot(run_id, thread_id)
    for process in worker_processes:
        stop_process(process)
    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "review_id": review_id,
        "waiting_status": waiting,
        "start_task_ids": start_task_ids,
        "start_task_results": start_results,
        "resume_task_ids": resume_task_ids,
        "resume_task_results": resume_results,
        "worker_received_count": sum(log_text(path).count("Task resume_report_task[") for path in worker_logs),
        "worker_succeeded_count": sum(log_text(path).count("succeeded") for path in worker_logs),
        "snapshot": snapshot,
    }


def main():
    if celery_app.conf.task_always_eager:
        raise RuntimeError("task_always_eager must be False")
    setup_postgres_checkpointer()
    log_dir = Path(tempfile.mkdtemp(prefix="researchflow-celery-audit-"))
    api_log = log_dir / "api.log"
    api_process = None
    user_marker = f"audit_user_{uuid4().hex[:12]}"
    port = free_port()
    run_ids = []
    worker_script = PROJECT_ROOT / "scripts" / "e2e_report_run_real_worker.py"
    try:
        api_process = start_process(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port), "--log-level", "info"],
            api_log,
        )
        base_url = f"http://127.0.0.1:{port}"
        wait_until(
            "FastAPI health",
            lambda: api_process.poll() is None and httpx.get(f"{base_url}/api/health", timeout=2).status_code == 200,
        )
        with httpx.Client(base_url=base_url, timeout=10) as client:
            headers = register_login(client, user_marker)
            start = run_pilot(client, headers, "duplicate-start", worker_script, log_dir, action="start")
            resume = run_pilot(client, headers, "duplicate-resume", worker_script, log_dir, action="resume")
            run_ids.extend([start["run_id"], resume["run_id"]])
        print(json.dumps({
            "topology": {
                "redis_broker": settings.CELERY_BROKER_URL,
                "redis_projection": settings.REDIS_URL,
                "postgres": mask_database_url(get_checkpoint_database_url()),
                "fastapi": base_url,
                "workers": "two independent external solo processes",
                "task_always_eager": celery_app.conf.task_always_eager,
            },
            "log_dir": str(log_dir),
            "duplicate_start": start,
            "duplicate_resume": resume,
        }, ensure_ascii=False, indent=2, default=str))
    finally:
        stop_process(api_process)
        if run_ids:
            try:
                with psycopg.connect(get_checkpoint_database_url()) as connection:
                    connection.execute("delete from agent_runs where id = any(%s)", (run_ids,))
                    connection.execute("delete from users where username = %s", (user_marker,))
                    connection.commit()
                redis_client = Redis.from_url(settings.REDIS_URL)
                try:
                    redis_client.delete(*(f"report_run:{run_id}:status" for run_id in run_ids))
                finally:
                    redis_client.close()
            except Exception as exc:
                print(f"cleanup failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
