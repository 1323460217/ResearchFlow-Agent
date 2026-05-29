import asyncio
import logging
import sys

from backend.tools.base import BaseTool, ToolDefinition

logger = logging.getLogger(__name__)


class PythonExecutorTool(BaseTool):
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="python_executor",
            description="Execute Python code in a sandboxed subprocess. Use for data analysis, calculations, or data processing. Code must be self-contained.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. Use print() to output results.",
                    },
                },
                "required": ["code"],
            },
            category="execute",
            timeout_seconds=30,
            requires_confirmation=True,
        )

    async def execute(self, code: str = "") -> str:
        if not code.strip():
            return "(empty code)"

        timeout = self.definition().timeout_seconds
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            parts = []
            if stdout_text:
                parts.append(stdout_text)
            if stderr_text:
                parts.append(f"[stderr]\n{stderr_text}")
            return "\n".join(parts) if parts else "(no output)"
        except asyncio.TimeoutError:
            if proc:
                proc.kill()
            return f"Execution timed out after {timeout}s"
        except Exception as exc:
            logger.error("Python execution failed: %s", exc)
            return f"Error: {exc}"
