from contextlib import asynccontextmanager
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from backend.core.config import settings

engine = create_async_engine(
    settings.POSTGRES_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

_worker_session_factory: ContextVar[object | None] = ContextVar(
    "worker_session_factory", default=None
)


def get_worker_session_factory():
    """Return the per-task factory when the Celery worker runtime is active."""
    return _worker_session_factory.get() or async_session_factory


@asynccontextmanager
async def worker_session_runtime():
    """Create and dispose DB resources inside one worker event-loop lifetime."""
    worker_engine = create_async_engine(
        settings.POSTGRES_URL,
        echo=settings.DEBUG,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    worker_factory = async_sessionmaker(
        worker_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    token = _worker_session_factory.set(worker_factory)
    try:
        yield worker_factory
    finally:
        _worker_session_factory.reset(token)
        await worker_engine.dispose()


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception as rollback_exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Session rollback failed: %s", rollback_exc
                )
            raise
