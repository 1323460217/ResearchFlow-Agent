"""Initialize LangGraph PostgreSQL checkpoint tables for this project."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.checkpoint.postgres_checkpointer import (  # noqa: E402
    get_checkpoint_database_url,
    mask_database_url,
    setup_postgres_checkpointer,
)


def main() -> int:
    database_url = get_checkpoint_database_url()
    try:
        setup_postgres_checkpointer()
    except Exception as exc:
        print(
            "LangGraph PostgreSQL checkpointer setup failed for "
            f"{mask_database_url(database_url)}: {type(exc).__name__}"
        )
        return 1

    print(
        "LangGraph PostgreSQL checkpointer setup completed for "
        f"{mask_database_url(database_url)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
