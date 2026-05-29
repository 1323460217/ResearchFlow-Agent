import asyncio
import json
import logging

from backend.tools.base import BaseTool, ToolDefinition

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_search",
            description="Search the web for recent information about any topic. Returns titles, snippets, and URLs from search results.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to execute on the web",
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
            timeout_seconds=30,
        )

    async def execute(self, query: str = "", max_results: int = 5) -> str:
        from backend.core.config import settings

        api_key = settings.TAVILY_API_KEY
        if not api_key:
            return json.dumps({
                "error": "TAVILY_API_KEY is not configured. Set it in .env to enable web search.",
            })

        max_results = max(1, min(10, int(max_results)))
        try:
            from tavily import TavilyClient

            client = TavilyClient(api_key=api_key)
            response = await asyncio.to_thread(
                client.search, query=query, max_results=max_results
            )
        except Exception as exc:
            logger.error("Web search failed: %s", exc)
            return json.dumps({"error": str(exc), "query": query})

        results = []
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "score": item.get("score", 0),
            })

        if not results:
            return json.dumps({"message": "No results found", "query": query})

        return json.dumps(results, ensure_ascii=False)
