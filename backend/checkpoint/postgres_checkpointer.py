"""PostgreSQL checkpoint adapter for the report-runs workflow.

The pinned project versions expose a synchronous ``PostgresSaver`` while the
installed LangGraph runtime calls asynchronous saver methods from
``graph.astream``.  ``AsyncPostgresSaverAdapter`` bridges those calls through a
single locked worker thread without changing dependency versions or the
legacy chat checkpoint path.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
from contextlib import AbstractContextManager
from threading import RLock
from typing import Any, AsyncIterator, Sequence
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from langgraph.checkpoint.postgres import PostgresSaver

from backend.core.config import settings

logger = logging.getLogger(__name__)

_checkpointer: PostgresSaver | AsyncPostgresSaverAdapter | None = None
_checkpointer_context: AbstractContextManager[PostgresSaver] | None = None
_checkpointer_lock = RLock()

_REDACTED = "[REDACTED]"
_SENSITIVE_QUERY_KEYS = {"pass", "passwd", "password", "pwd", "sslpassword"}


class AsyncPostgresSaverAdapter:
    """Async facade over the synchronous saver in checkpoint-postgres 2.0.25."""

    def __init__(self, saver: PostgresSaver):
        self._saver = saver
        self._sync_lock = RLock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._saver, name)

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        def invoke():
            with self._sync_lock:
                return getattr(self._saver, method)(*args, **kwargs)

        return await asyncio.to_thread(invoke)

    async def aget_tuple(self, config):
        return await self._call("get_tuple", config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await self._call("put", config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await self._call("put_writes", config, writes, task_id, task_path)

    async def alist(
        self,
        config,
        *,
        filter: dict[str, Any] | None = None,
        before=None,
        limit: int | None = None,
    ) -> AsyncIterator[Any]:
        items = await self._call("list", config, filter=filter, before=before, limit=limit)
        for item in items:
            yield item

    async def adelete_thread(self, thread_id: str) -> None:
        await self._call("delete_thread", thread_id)


def get_checkpoint_database_url() -> str:
    """Return the configured database URL in a psycopg-compatible form."""

    configured_url = settings.POSTGRES_URL
    parsed = urlsplit(configured_url)
    if parsed.scheme.lower().startswith("postgresql+"):
        return urlunsplit(("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    return configured_url


def mask_database_url(url: str) -> str:
    """Redact database credentials and password-like query parameters."""

    if not url:
        return url
    try:
        parsed = urlsplit(url)
        netloc = parsed.netloc
        if parsed.username is not None or parsed.password is not None:
            hostname = parsed.hostname or ""
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            if parsed.port is not None:
                hostname = f"{hostname}:{parsed.port}"
            username = quote(parsed.username or "", safe="")
            netloc = f"{username}:{_REDACTED}@{hostname}"
        query = parsed.query
        if query:
            query = urlencode([
                (key, _REDACTED if key.lower() in _SENSITIVE_QUERY_KEYS else value)
                for key, value in parse_qsl(query, keep_blank_values=True)
            ])
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))
    except ValueError:
        return "[REDACTED_DATABASE_URL]"


def setup_postgres_checkpointer() -> None:
    """Create LangGraph's own checkpoint tables using a short-lived saver."""

    database_url = get_checkpoint_database_url()
    logger.info("Initializing LangGraph PostgreSQL checkpointer at %s", mask_database_url(database_url))
    with PostgresSaver.from_conn_string(database_url) as checkpointer:
        checkpointer.setup()


def get_postgres_checkpointer() -> PostgresSaver | AsyncPostgresSaverAdapter:
    """Return a process-scoped saver with its connection and adapter alive."""

    global _checkpointer, _checkpointer_context
    with _checkpointer_lock:
        if _checkpointer is not None:
            return _checkpointer
        database_url = get_checkpoint_database_url()
        context = PostgresSaver.from_conn_string(database_url)
        saver = context.__enter__()
        _checkpointer_context = context
        # MagicMock-based unit tests retain the raw fake. The real pinned
        # PostgresSaver needs the async compatibility facade.
        _checkpointer = AsyncPostgresSaverAdapter(saver) if isinstance(saver, PostgresSaver) else saver
        logger.info("LangGraph PostgreSQL checkpointer connected to %s", mask_database_url(database_url))
        return _checkpointer


def reset_postgres_checkpointer() -> None:
    """Close and clear the process-scoped saver, primarily for shutdown/tests."""

    global _checkpointer, _checkpointer_context
    with _checkpointer_lock:
        if _checkpointer_context is not None:
            _checkpointer_context.__exit__(None, None, None)
        _checkpointer_context = None
        _checkpointer = None


def build_graph_config(thread_id: Any) -> dict[str, dict[str, str]]:
    """Build the stable LangGraph configuration for one durable report run."""

    return {"configurable": {"thread_id": str(thread_id)}}


atexit.register(reset_postgres_checkpointer)
