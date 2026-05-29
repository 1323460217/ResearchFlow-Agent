"""LangGraph Checkpoint — Agent State persistence.

Uses RedisSaver when redis with checkpoint support is available;
falls back to in-memory MemorySaver otherwise.

Key pattern:  wf:{thread_id}:checkpoint
TTL:         30 days policy constant
"""

import logging
from contextlib import AbstractContextManager
from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from backend.core.config import settings

logger = logging.getLogger(__name__)

CHECKPOINT_TTL = 30 * 24 * 3600

_checkpointer: Optional[BaseCheckpointSaver] = None
_redis_saver_context: Optional[AbstractContextManager[BaseCheckpointSaver]] = None


def _try_redis_saver() -> Optional[BaseCheckpointSaver]:
# 与 RedisSaver 的核心区别
# 在当前代码逻辑中，MemorySaver 是 RedisSaver 的降级方案，两者有本质区别：

# 持久性：RedisSaver 将数据写入磁盘（Redis 持久化机制），应用重启后数据依然存在；MemorySaver 随进程消亡而丢失数据。
# 并发与共享：RedisSaver 支持多进程、多实例共享同一个状态存储；MemorySaver 仅限当前单一进程内访问，无法跨进程共享状态。
# 性能：MemorySaver 读写纯内存，延迟极低；RedisSaver 需要网络 I/O，存在微小的延迟开销。
    global _redis_saver_context

    try:
        from langgraph.checkpoint.redis import RedisSaver

        _redis_saver_context = RedisSaver.from_conn_string(settings.REDIS_URL) 
        saver = _redis_saver_context.__enter__()    # 获取Saver对象
        saver.setup()   # 初始化RedisSaver
        return saver
    except ImportError:
        logger.info("RedisSaver not available, using MemorySaver")   
        #MemorySaver 是 LangGraph 框架提供的一个内置的、轻量级的检查点保存器。它的核心特点是将所有的工作流状态数据直接保存在当前进程的内存中
        return None
    except Exception as exc:
        if _redis_saver_context is not None:
            _redis_saver_context.__exit__(None, None, None)
            _redis_saver_context = None
        logger.warning("RedisSaver init failed (%s), using MemorySaver", exc)
        return None


def get_checkpointer() -> BaseCheckpointSaver:
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    _checkpointer = _try_redis_saver()
    if _checkpointer is None:
        _checkpointer = MemorySaver()
        logger.info("MemorySaver initialized (in-memory checkpoint)")

    return _checkpointer


def reset_checkpointer() -> None:
    global _checkpointer, _redis_saver_context
    if _redis_saver_context is not None:
        _redis_saver_context.__exit__(None, None, None)
        _redis_saver_context = None
    _checkpointer = None
