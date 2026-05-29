"""filesystem MCP Server — 本地文件系统操作。

通过 stdio transport 连接 @anthropic/mcp-server-filesystem。
提供 read_file / write_file / list_directory 等文件操作工具。
"""

from pydantic import BaseModel, Field


class FilesystemServerConfig(BaseModel):
    transport: str = Field(default="stdio", description="传输方式")
    command: str = Field(default="npx", description="启动命令")
    args: list[str] = Field(
        default_factory=lambda: ["-y", "@anthropic/mcp-server-filesystem", "/workspace"],
        description="命令行参数",
    )
    env: dict = Field(default_factory=dict, description="环境变量")


DEFAULT_CONFIG = FilesystemServerConfig()
