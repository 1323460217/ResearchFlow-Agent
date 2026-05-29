"""长期用户画像 — Redis Hash 存储。

Key pattern:  user:{user_id}:profile
TTL:         永久（用户主动删除时清除）

存储用户的研究兴趣、偏好来源、语言偏好等。
工作流执行后由 Analyzer 产出的 key_findings 增量更新。
"""

import json
import logging
from typing import List, Optional

from backend.memory.redis_client import get_redis

logger = logging.getLogger(__name__)

# 默认值 —— Redis 不可用时的兜底
DEFAULT_PROFILE = {
    "research_interests": [],
    "frequent_topics": {},
    "preferred_sources": ["arxiv"],
    "language_preference": "zh-CN",
    "expertise_level": "intermediate",
}


class UserProfile:
    """用户级别的长期画像管理器。

    Usage::

        profile = UserProfile(user_id=42)
        interests = await profile.get_interests()
        await profile.add_topic("遥感目标检测")
    """

    def __init__(self, user_id: int):
        self._key = f"user:{user_id}:profile"

    # ── Core read/write ──────────────────────────────

    async def _read(self) -> dict:
        """读取完整 Hash 并反序列化 JSON 字段。"""
        try:
            redis = await get_redis()
            raw = await redis.hgetall(self._key)
        except Exception as exc:
            logger.warning("UserProfile._read failed for %s: %s", self._key, exc)
            return DEFAULT_PROFILE.copy()

        if not raw:
            return DEFAULT_PROFILE.copy()

        return self._deserialize(raw)

    async def _write(self, data: dict) -> None:
        """将完整 profile dict 写入 Redis Hash（序列化嵌套字段为 JSON）。"""
        try:
            redis = await get_redis()
            serialized = self._serialize(data)
            await redis.hset(self._key, mapping=serialized)
        except Exception as exc:
            logger.warning("UserProfile._write failed for %s: %s", self._key, exc)

    # ── Serialization helpers ────────────────────────

    @staticmethod
    def _serialize(data: dict) -> dict:
        result = {}
        for k, v in data.items():
            result[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)
        return result

    @staticmethod
    def _deserialize(raw: dict) -> dict:
        result = {}
        for k, v in raw.items():
            # All values in raw are strings (Redis Hash)
            val = v.decode("utf-8") if isinstance(v, bytes) else v
            try:
                result[k] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                result[k] = val
        return result

    # ── High-level API ───────────────────────────────

    async def get_profile(self) -> dict:
        """获取完整用户画像。"""
        return await self._read()

    async def get_interests(self) -> List[str]:
        """获取用户研究兴趣列表（如 ["遥感目标检测", "注意力机制"]）。"""
        profile = await self._read()
        return profile.get("research_interests", [])

    async def add_topic(self, topic: str) -> None:
        """增量增加研究主题（frequent_topics 计数 +1）。"""
        profile = await self._read()
        topics: dict = profile.get("frequent_topics", {})
        topics[topic] = topics.get(topic, 0) + 1
        profile["frequent_topics"] = topics

        # Auto-add to interests if not present
        interests: list = profile.get("research_interests", [])
        if topic not in interests:
            interests.append(topic)
            profile["research_interests"] = interests

        await self._write(profile)

    async def update_from_research(
        self,
        topic: str,
        findings: Optional[List[str]] = None,
    ) -> None:
        """工作流执行后更新画像：记录研究主题 + 可选更新兴趣。

        由 router_chat.py 在 workflow 完成后异步调用。
        """
        await self.add_topic(topic)

        if findings:
            profile = await self._read()
            profile["research_interests"] = list(set(profile.get("research_interests", []) + findings))
            await self._write(profile)

        logger.debug("UserProfile updated for %s, topic=%s", self._key, topic)

    async def set_preference(self, key: str, value) -> None:
        """设置单个偏好字段。"""
        profile = await self._read()
        profile[key] = value
        await self._write(profile)

    async def clear(self) -> None:
        """删除用户画像（用户主动重置时调用）。"""
        try:
            redis = await get_redis()
            await redis.delete(self._key)
        except Exception as exc:
            logger.warning("UserProfile.clear failed for %s: %s", self._key, exc)
