"""短期对话记忆 — Redis List 存储。

Key pattern:  chat:{session_id}:messages
TTL:         7 天
Trim:        保留最近 50 条消息 (LTRIM)
"""

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from backend.memory.redis_client import get_redis

logger = logging.getLogger(__name__)

MAX_MESSAGES = 50
TTL_SECONDS = 7 * 24 * 3600  # 7 days


class ChatMemory:
    """会话级别的短期记忆管理器。

    Usage::

        memory = ChatMemory(session_id="th-abc123")
        await memory.save("user", "What is RLHF?")
        history = await memory.load_history()
    """

    def __init__(self, session_id: str):
        self._key = f"chat:{session_id}:messages"

    # ── Public API ───────────────────────────────────

    async def save(self, role: str, content: str, token_count: int = 0) -> None:
        """追加一条消息到会话历史。"""
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "token_count": token_count,
        }
        try:
            redis = await get_redis()
            await redis.rpush(self._key, json.dumps(entry, ensure_ascii=False))
            await redis.ltrim(self._key, -MAX_MESSAGES, -1)
            await redis.expire(self._key, TTL_SECONDS)
        except Exception as exc:
            logger.warning("ChatMemory.save failed for %s: %s", self._key, exc)

    async def load_history(self, limit: int = 50) -> List[dict]:
        """加载最近 N 条对话历史（最新在前）。"""
        try:
            redis = await get_redis()
            items = await redis.lrange(self._key, -limit, -1)
            return [json.loads(item) for item in items]
        except Exception as exc:
            logger.warning("ChatMemory.load_history failed for %s: %s", self._key, exc)
            return []

    async def get_recent_messages(self, limit: int = 20) -> List[dict]:
        """获取最近 N 条消息，格式化为 LangChain message 可用的 dict 列表。"""
        return await self.load_history(limit)

    async def clear(self) -> None:
        """删除该会话的全部历史（用户主动清空时调用）。"""
        try:
            redis = await get_redis()
            await redis.delete(self._key)
        except Exception as exc:
            logger.warning("ChatMemory.clear failed for %s: %s", self._key, exc)

    async def message_count(self) -> int:
        """返回当前会话的消息总数。"""
        try:
            redis = await get_redis()
            return await redis.llen(self._key)
        except Exception as exc:
            logger.warning("ChatMemory.message_count failed for %s: %s", self._key, exc)
            return 0
