import asyncio
import json
import logging

from backend.tools.base import BaseTool, ToolDefinition

logger = logging.getLogger(__name__)


class ArxivSearchTool(BaseTool):
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="arxiv_search",
            description="Search ArXiv for academic papers by keyword query. Returns paper title, summary, authors, and URL for each result.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string, e.g. 'transformer attention mechanism'",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (1-10)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            category="search",
            timeout_seconds=45,
        )

    async def execute(self, query: str = "", max_results: int = 5) -> str:
        from backend.workflow.agents.retriever import _search_arxiv_sync

        max_results = max(1, min(10, int(max_results)))
        try:
            docs = await asyncio.to_thread(_search_arxiv_sync, query, max_results)
        except Exception as exc:
            logger.error("ArXiv search failed: %s", exc)
            return json.dumps({"error": str(exc), "query": query})

        results = []
        for doc in docs:
            results.append({
                "doc_id": doc.doc_id,
                "title": doc.title,
                "summary": doc.content,
                "url": doc.url,
                "relevance_score": doc.relevance_score,
            })

        if not results:
            return json.dumps({"message": "No results found", "query": query})

        return json.dumps(results, ensure_ascii=False)
