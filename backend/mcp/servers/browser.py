"""browser MCP Server — 浏览器自动化操作。

通过 HTTP+SSE transport 连接远程 browser MCP Server。
提供网页抓取、截图、DOM 查询等工具。
"""

from pydantic import BaseModel, Field


class BrowserServerConfig(BaseModel):
    transport: str = Field(default="http", description="传输方式")
    url: str = Field(default="http://localhost:3001/mcp", description="MCP Server URL")
    headers: dict = Field(default_factory=dict, description="HTTP 请求头")


DEFAULT_CONFIG = BrowserServerConfig()
