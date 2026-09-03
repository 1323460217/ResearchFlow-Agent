from contextlib import asynccontextmanager

from backend.database.session import worker_session_runtime
from backend.memory.redis_client import worker_redis_runtime


@asynccontextmanager
async def worker_resource_runtime():
    """Scope async DB and Redis resources to one Celery asyncio.run call."""
    async with worker_session_runtime():
        async with worker_redis_runtime():
            yield


async def run_worker_coroutine(coro):
    async with worker_resource_runtime():
        return await coro
