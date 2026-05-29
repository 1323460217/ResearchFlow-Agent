"""python MCP Server — Python 代码执行环境。

通过 stdio transport 连接本地 Python MCP Server。
提供 execute / repl 等代码执行工具（沙箱隔离）。
"""

from pydantic import BaseModel, Field


class PythonServerConfig(BaseModel):
    transport: str = Field(default="stdio", description="传输方式")
    command: str = Field(default="python", description="Python 解释器路径")
    args: list[str] = Field(
        default_factory=lambda: ["-m", "mcp_server_python"],
        description="命令行参数",
    )
    env: dict = Field(default_factory=dict, description="环境变量")


DEFAULT_CONFIG = PythonServerConfig()
