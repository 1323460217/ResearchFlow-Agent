import logging

from backend.core.llm import get_llm
from backend.tools.base import BaseTool, ToolDefinition

logger = logging.getLogger(__name__)

STYLE_PROMPTS = {
    "academic": "学术论文风格，使用正式严谨的语言",
    "summary": "简洁综述风格，突出重点和结论",
    "detailed": "详细分析风格，覆盖每个技术细节",
}


class ReportGeneratorTool(BaseTool):
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="report_generator",
            description="Generate a structured Markdown research report from provided analysis content and findings.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Research topic or title",
                    },
                    "content": {
                        "type": "string",
                        "description": "Analysis content, findings, and sources to synthesize into a report",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["academic", "summary", "detailed"],
                        "description": "Report writing style",
                        "default": "academic",
                    },
                },
                "required": ["topic", "content"],
            },
            category="generate",
            timeout_seconds=120,
        )

    async def execute(self, topic: str = "", content: str = "", style: str = "academic") -> str:
        style_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["academic"])
        system_prompt = (
            "你是一个科研报告撰写专家，请根据提供的内容生成一份结构完整的 Markdown 研究报告。\n"
            f"写作风格：{style_instruction}\n"
            "报告应包含：研究概述、文献综述、核心方法分析、关键发现、研究方向展望等章节。"
        )
        user_prompt = f"研究主题: {topic}\n\n分析内容:\n{content[:5000]}\n\n请生成研究报告。"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            llm = get_llm(temperature=0.4)
            response = await llm.ainvoke([(m["role"], m["content"]) for m in messages])
            return response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            logger.error("Report generation failed: %s", exc)
            return f"Error generating report: {exc}\n\n## {topic}\n\n{content[:2000]}"
