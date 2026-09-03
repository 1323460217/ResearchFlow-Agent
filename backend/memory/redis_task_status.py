"""Lightweight Redis projection for report-run realtime status."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.memory.redis_client import get_redis

DEFAULT_RUN_STATUS_TTL_SECONDS = 86400
RUN_STATUS_KEY_PREFIX = "report_run:"

_VERSIONED_PROJECTION_LUA = """
local incoming = tonumber(ARGV[1])
local existing_raw = redis.call('HGET', KEYS[1], 'status_version')
local existing = tonumber(existing_raw)
if existing and not incoming then return 0 end
if existing and incoming and incoming < existing then return 0 end
local pair_count = tonumber(ARGV[3])
local index = 4
for _ = 1, pair_count do
  redis.call('HSET', KEYS[1], ARGV[index], ARGV[index + 1])
  index = index + 2
end
local clear_count = tonumber(ARGV[index])
index = index + 1
for _ = 1, clear_count do
  redis.call('HDEL', KEYS[1], ARGV[index])
  index = index + 1
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return 1
"""


def build_run_status_key(run_id: int | str) -> str:
    return f"{RUN_STATUS_KEY_PREFIX}{run_id}:status"


def _read_value(run: Any, name: str, default: Any = None) -> Any:
    if isinstance(run, dict):
        return run.get(name, default)
    return getattr(run, name, default)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def set_run_status_projection(
    run_id: int | str,
    status: str,
    current_node: str | None = None,
    progress: int | None = None,
    review_required: bool | None = None,
    review_id: int | None = None,
    task_id: str | None = None,
    status_version: int | None = None,
    ttl_seconds: int | None = None,
) -> None:
    redis = await get_redis()
    key = build_run_status_key(run_id)
    mapping: dict[str, str] = {
        "run_id": str(run_id),
        "status": status,
        "updated_at": datetime.utcnow().isoformat(),
        "source": "redis",
    }
    values = {
        "current_node": current_node,
        "progress": progress,
        "review_required": review_required,
        "review_id": review_id,
        "task_id": task_id,
        "status_version": status_version,
    }
    for field, value in values.items():
        if value is not None:
            mapping[field] = str(value).lower() if isinstance(value, bool) else str(value)

    await redis.hset(key, mapping=mapping)
    fields_to_clear = [field for field, value in values.items() if value is None]
    if fields_to_clear:
        await redis.hdel(key, *fields_to_clear)
    await redis.expire(
        key,
        ttl_seconds if ttl_seconds is not None else DEFAULT_RUN_STATUS_TTL_SECONDS,
    )


async def set_run_status_projection_if_newer(
    run_id: int | str,
    status: str,
    current_node: str | None = None,
    progress: int | None = None,
    review_required: bool | None = None,
    review_id: int | None = None,
    task_id: str | None = None,
    status_version: int | None = None,
    ttl_seconds: int | None = None,
) -> bool:
    """Atomically apply a projection only when its version is not stale."""
    redis = await get_redis()
    key = build_run_status_key(run_id)
    values = {
        "current_node": current_node,
        "progress": progress,
        "review_required": review_required,
        "review_id": review_id,
        "task_id": task_id,
        "status_version": status_version,
    }
    mapping: dict[str, str] = {
        "run_id": str(run_id),
        "status": status,
        "updated_at": datetime.utcnow().isoformat(),
        "source": "redis",
    }
    for field, value in values.items():
        if value is not None:
            mapping[field] = str(value).lower() if isinstance(value, bool) else str(value)
    fields_to_clear = [field for field, value in values.items() if value is None]
    args: list[str] = [str(status_version or ""), str(ttl_seconds or DEFAULT_RUN_STATUS_TTL_SECONDS), str(len(mapping))]
    for field, value in mapping.items():
        args.extend((field, value))
    args.append(str(len(fields_to_clear)))
    args.extend(fields_to_clear)
    result = await redis.eval(_VERSIONED_PROJECTION_LUA, 1, key, *args)
    return bool(result)


async def get_run_status_projection(run_id: int | str) -> dict[str, Any] | None:
    redis = await get_redis()
    raw = await redis.hgetall(build_run_status_key(run_id))
    if not raw:
        return None

    projection: dict[str, Any] = dict(raw)
    projection["run_id"] = _as_int(projection.get("run_id")) or run_id
    projection["progress"] = _as_int(projection.get("progress"))
    projection["review_id"] = _as_int(projection.get("review_id"))
    projection["status_version"] = _as_int(projection.get("status_version"))
    projection["review_required"] = _as_bool(projection.get("review_required"))
    projection["updated_at"] = _as_datetime(projection.get("updated_at"))
    return projection


async def delete_run_status_projection(run_id: int | str) -> None:
    redis = await get_redis()
    await redis.delete(build_run_status_key(run_id))


def _progress_for_status(status: str | None) -> int | None:
    return {
        "PENDING": 0,
        "STARTED": 10,
        "RUNNING": 25,
        "WAITING_HUMAN": 70,
        "RESUME_QUEUED": 75,
        "RESUMED": 80,
        "SUCCESS": 100,
        "FAILURE": 100,
        "CANCELLED": 100,
    }.get(status)


async def repair_run_status_projection_from_run(run: Any) -> None:
    status = _read_value(run, "status")
    review_required = _read_value(run, "review_required")
    if review_required is None:
        review_required = status == "WAITING_HUMAN"
    progress = _read_value(run, "progress")
    if progress is None:
        progress = _progress_for_status(status)

    await set_run_status_projection_if_newer(
        run_id=_read_value(run, "id", _read_value(run, "run_id")),
        status=status,
        current_node=_read_value(run, "current_node"),
        progress=progress,
        review_required=review_required,
        review_id=_read_value(run, "review_id", _read_value(run, "current_review_id")),
        task_id=_read_value(run, "task_id", _read_value(run, "current_task_id")),
        status_version=_as_int(_read_value(run, "status_version")),
    )
