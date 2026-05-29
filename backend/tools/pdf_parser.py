import logging
import os

from backend.tools.base import BaseTool, ToolDefinition

logger = logging.getLogger(__name__)
MAX_OUTPUT_CHARS = 10000


class PdfParserTool(BaseTool):
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="pdf_parser",
            description="Parse a PDF file and extract text content, including tables when available. Provide the absolute path to the PDF.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file to parse",
                    },
                },
                "required": ["file_path"],
            },
            category="parse",
            timeout_seconds=60,
        )

    async def execute(self, file_path: str = "") -> str:
        from backend.rag.ingestion import _parse_pdf

        if not file_path or not os.path.isfile(file_path):
            return f"Error: file not found at {file_path}"

        ext = os.path.splitext(file_path)[1].lower()
        if ext != ".pdf":
            return f"Error: expected .pdf file, got {ext!r}"

        try:
            text = await _parse_pdf(file_path)
        except Exception as exc:
            logger.error("PDF parse failed for %s: %s", file_path, exc)
            return f"Error parsing PDF: {exc}"

        if not text.strip():
            return "(no text extracted)"

        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS] + "\n\n... (truncated)"

        return text
