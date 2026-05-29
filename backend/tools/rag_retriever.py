import json
import logging

from backend.tools.base import BaseTool, ToolDefinition

logger = logging.getLogger(__name__)


class RagRetrieverTool(BaseTool):
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="rag_retriever",
            description="Search the local knowledge base (ChromaDB) for relevant document chunks. Supports hybrid search (dense + BM25).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "collection_name": {
                        "type": "string",
                        "description": "Knowledge base collection name, e.g. 'kb_1'",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of top results to return",
                        "default": 5,
                    },
                },
                "required": ["query", "collection_name"],
            },
            category="search",
            timeout_seconds=30,
        )

    async def execute(self, query: str = "", collection_name: str = "", top_k: int = 5) -> str:
        from backend.rag.retrieval import retrieve_from_kb

        top_k = max(1, min(20, int(top_k)))
        try:
            chunks = await retrieve_from_kb(
                query=query,
                collection_name=collection_name,
                top_k=top_k,
                strategy="hybrid",
                use_rerank=True,
            )
        except Exception as exc:
            logger.error("KB retrieval failed for %s: %s", collection_name, exc)
            return json.dumps({"error": str(exc), "query": query})

        results = []
        for chunk in chunks:
            results.append({
                "chunk_id": chunk.chunk_id,
                "content": chunk.content,
                "score": chunk.score,
                "filename": chunk.filename,
                "document_id": getattr(chunk, "document_id", None),
            })

        if not results:
            return json.dumps({"message": "No relevant chunks found", "query": query})

        return json.dumps(results, ensure_ascii=False)
