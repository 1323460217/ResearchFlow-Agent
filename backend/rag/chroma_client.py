import logging
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.api.types import EmbeddingFunction
from chromadb.config import Settings as ChromaSettings

from backend.core.config import settings

logger = logging.getLogger(__name__)

_client: Optional[chromadb.PersistentClient] = None


def get_client() -> chromadb.PersistentClient:
    """获取 ChromaDB 持久化客户端（单例）。"""
    global _client
    if _client is None:
        persist_dir = Path(settings.CHROMA_PERSIST_DIR)
        persist_dir.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        logger.info("ChromaDB client initialized at %s", persist_dir)
    return _client


def get_or_create_collection(collection_name: str) -> chromadb.Collection:
    """按名称获取或创建 collection。"""
    client = get_client()
    return client.get_or_create_collection(name=collection_name)


def delete_collection(collection_name: str) -> None:
    """删除指定 collection。不存在则忽略。"""
    client = get_client()
    try:
        client.delete_collection(name=collection_name)
        logger.info("Deleted ChromaDB collection: %s", collection_name)
    except Exception:
        logger.debug("Collection %s not found or already deleted", collection_name)


def collection_exists(collection_name: str) -> bool:
    """检查 collection 是否存在。"""
    client = get_client()
    collections = client.list_collections()
    return any(c.name == collection_name for c in collections)
