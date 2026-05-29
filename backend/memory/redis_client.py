import logging
from typing import Optional

import redis.asyncio as aioredis
from redis.asyncio import Redis

from backend.core.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[Redis] = None


async def get_redis() -> Redis:
    """获取异步 Redis 连接单例。

    首次调用时创建连接池，后续复用同一连接。
    连接失败时记录警告但返回 None 会中断调用链 ——
    调用方应在 get_redis() 返回后自行处理可用性。
    """
    global _pool
    if _pool is not None:
        return _pool

    try:
        _pool = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=10,
        )
        await _pool.ping()
        logger.info("Redis connected: %s", settings.REDIS_URL)
    except Exception as exc:
        logger.warning("Redis unavailable (%s), memory features disabled: %s", settings.REDIS_URL, exc)
        _pool = None  # Ensure _pool is None so callers can check
        raise

    return _pool


async def close_redis() -> None:
    """关闭 Redis 连接（服务停止时调用）。"""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Redis connection closed")


def reset_redis() -> None:
    """重置连接单例（测试用）。"""
    global _pool
    _pool = None
