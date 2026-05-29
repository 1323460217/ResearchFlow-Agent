import math
import re

from backend.tools.base import BaseTool, ToolDefinition


def _build_safe_globals() -> dict:
    allowed = {"__builtins__": {}}
    for name in dir(math):
        if not name.startswith("_"):
            allowed[name] = getattr(math, name)
    return allowed


_SAFE_GLOBALS = _build_safe_globals()
_WHITELIST_RE = re.compile(r"^[\d\s+\-*/().,%e\^_a-zA-Z]+$")


class CalculatorTool(BaseTool):
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="calculator",
            description="Evaluate a precise mathematical expression. Supports arithmetic, trigonometry (via math module), sqrt, log, sin, cos, pi, e, etc.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate, e.g. 'sqrt(3**2 + 4**2)'",
                    },
                },
                "required": ["expression"],
            },
            category="execute",
            timeout_seconds=10,
        )

    async def execute(self, expression: str = "") -> str:
        if not expression.strip():
            return "Error: empty expression"

        if not _WHITELIST_RE.match(expression):
            return f"Error: expression contains disallowed characters: {expression!r}"

        try:
            result = eval(expression, _SAFE_GLOBALS)
            return str(result)
        except Exception as exc:
            return f"Error: {exc}"
