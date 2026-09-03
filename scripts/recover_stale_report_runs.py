"""Read-only report-run stale recovery inventory.

This tool deliberately does not update PostgreSQL, enqueue Celery tasks, or
touch WAITING_HUMAN/terminal runs. It produces candidates for an operator.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.checkpoint.postgres_checkpointer import get_checkpoint_database_url  # noqa: E402


ACTIVE_STATUSES = ("STARTED", "RUNNING", "RESUMED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--older-than-seconds", type=int, default=900)
    parser.add_argument("--dry-run", action="store_true", required=True)
    args = parser.parse_args()
    if args.older_than_seconds < 1:
        parser.error("--older-than-seconds must be positive")

    query = """
        SELECT id, user_id, status, updated_at, thread_id
        FROM agent_runs
        WHERE status = ANY(%s)
          AND updated_at < (CURRENT_TIMESTAMP - (%s * INTERVAL '1 second'))
        ORDER BY updated_at ASC, id ASC
    """
    with psycopg.connect(get_checkpoint_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (list(ACTIVE_STATUSES), args.older_than_seconds))
            candidates = cursor.fetchall()
            checkpoint_table_available = True
            rows = []
            for run_id, user_id, status, updated_at, thread_id in candidates:
                has_checkpoint = None
                try:
                    cursor.execute(
                        "SELECT EXISTS(SELECT 1 FROM checkpoints WHERE thread_id = %s)",
                        (str(thread_id),),
                    )
                    has_checkpoint = bool(cursor.fetchone()[0])
                except psycopg.errors.UndefinedTable:
                    connection.rollback()
                    checkpoint_table_available = False
                rows.append(
                    {
                        "run_id": run_id,
                        "user_id": user_id,
                        "status": status,
                        "updated_at": updated_at.isoformat() if updated_at else None,
                        "thread_id": str(thread_id),
                        "has_checkpoint": has_checkpoint,
                        "recommended_action": (
                            "REQUEUE_CANDIDATE"
                            if has_checkpoint is True
                            else "CHECKPOINT_STATUS_UNKNOWN"
                            if has_checkpoint is None
                            else "MARK_FAILURE_REVIEW"
                        ),
                    }
                )

    print(json.dumps({
        "dry_run": args.dry_run,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "older_than_seconds": args.older_than_seconds,
        "checkpoint_table_available": checkpoint_table_available,
        "candidates": rows,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
