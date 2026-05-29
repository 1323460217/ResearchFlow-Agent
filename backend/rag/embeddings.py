from typing import List

from langchain_openai import OpenAIEmbeddings

from backend.core.config import settings

_embedding_model: OpenAIEmbeddings | None = None


def get_embedding_model() -> OpenAIEmbeddings:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            openai_api_base=settings.LLM_API_BASE,
            openai_api_key=settings.LLM_API_KEY,
            dimensions=3072,
        )
    return _embedding_model


async def embed_texts(texts: List[str]) -> List[List[float]]:
    """将文本列表向量化，返回 3072 维向量列表。"""
    model = get_embedding_model()
    return await model.aembed_documents(texts)


async def embed_query(query: str) -> List[float]:
    """将查询文本向量化，返回单个 3072 维向量。"""
    model = get_embedding_model()
    return await model.aembed_query(query)
