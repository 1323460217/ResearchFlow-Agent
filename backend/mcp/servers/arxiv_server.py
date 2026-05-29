"""arxiv MCP Server — 论文检索与下载。

通过 HTTP+SSE transport 连接远程 arxiv MCP Server。
提供 search / download / cite 等论文检索工具。
"""

from pydantic import BaseModel, Field


class ArxivServerConfig(BaseModel):
    transport: str = Field(default="http", description="传输方式")
    url: str = Field(default="http://localhost:3002/mcp", description="MCP Server URL")
    headers: dict = Field(default_factory=dict, description="HTTP 请求头")


DEFAULT_CONFIG = ArxivServerConfig()
