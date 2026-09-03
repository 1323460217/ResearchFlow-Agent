"""Opt-in infrastructure tests for the durable report-run HITL path."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_legacy_and_report_run_routes_are_registered():
    from backend.main import app

    paths = {route.path for route in app.routes}
    assert "/api/chat" in paths
    assert "/api/chat/stream" in paths
    assert "/api/report-runs" in paths
    assert "/ws/agent-stream" in paths
    assert "/api/reports" in paths


def test_real_report_run_hitl_e2e_subprocess():
    postgres_url = os.environ.get("REPORT_E2E_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("set REPORT_E2E_POSTGRES_URL to run the real infrastructure E2E")

    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["POSTGRES_URL"] = postgres_url
    if os.environ.get("REPORT_E2E_REDIS_URL"):
        environment["REDIS_URL"] = os.environ["REPORT_E2E_REDIS_URL"]
    if os.environ.get("REPORT_E2E_CELERY_BROKER_URL"):
        environment["CELERY_BROKER_URL"] = os.environ["REPORT_E2E_CELERY_BROKER_URL"]

    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "e2e_report_run_hitl.py"),
            "--mode",
            os.environ.get("REPORT_E2E_MODE", "eager"),
            "--action",
            os.environ.get("REPORT_E2E_ACTION", "approve"),
            "--cleanup",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    assert '"thread_id"' in completed.stdout
    assert '"checkpoint_counts"' in completed.stdout
