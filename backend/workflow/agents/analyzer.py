import logging
import time

from backend.core.llm import LLMStreamResult, astream_llm_with_usage, parse_json_from_response
from backend.workflow.state import AgentTrace, ResearchState

logger = logging.getLogger(__name__)

ANALYZER_PROMPT = """你是一个科研文献分析专家。给定检索到的论文文献，你需要进行深度分析并提取关键信息。

输出格式要求（严格返回 JSON）:
```json
{
  "analysis_result": "完整的分析文本，涵盖研究现状、技术路线、创新点对比",
  "key_findings": ["发现1", "发现2", "发现3"],
  "methodology_summary": "研究方法概述"
}
```

规则:
- analysis_result: 对文献的综合分析，200-500 字，涵盖研究背景、主流方法、核心挑战
- key_findings: 3-5 个关键发现，每条 10-30 字，聚焦创新点和重要结论
- methodology_summary: 50-150 字的研究方法总结，概括主要技术路线
"""

MAX_DOC_CONTENT_LENGTH = 2000  # 每篇文档最多保留的字符数


async def astream_llm_text(*args, **kwargs):
    return await astream_llm_with_usage(*args, **kwargs)


def _as_llm_result(value) -> LLMStreamResult:
    if isinstance(value, LLMStreamResult):
        return value
    return LLMStreamResult(text=value or "", token_usage=None)


def _format_docs_for_prompt(docs: list, max_docs: int = 10) -> str:
    """将检索到的文档格式化为 prompt 可用的文本。"""
    if not docs:
        return "（无文献）"

    lines = []
    for i, doc in enumerate(docs[:max_docs]):
        content = doc.content[:MAX_DOC_CONTENT_LENGTH] if hasattr(doc, 'content') else str(doc)[:MAX_DOC_CONTENT_LENGTH]
        title = doc.title if hasattr(doc, 'title') else ""
        source = doc.source if hasattr(doc, 'source') else ""
        lines.append(f"### [{i+1}] {title} (来源: {source})\n{content}\n")
    return "\n".join(lines)


async def analyzer_node(state: ResearchState) -> dict:
    """Analyzer agent — 深度分析检索到的文献。"""
    t0 = time.monotonic()
    topic = state.get("research_topic", "")
    docs = state.get("retrieved_docs", [])
    task_plan = state.get("task_plan", [])
    model = state.get("model_override")

    traces = list(state.get("agent_trace", []))
    trace = AgentTrace(
        agent_name="analyzer",
        action="deep_analysis",
        input_summary=f"topic={topic[:100]}, docs={len(docs)}",
        output_summary="",
    )

    if not docs:
        trace.output_summary = "No documents to analyze"
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        traces.append(trace)
        return {
            "analysis_result": "未检索到相关文献，无法进行深度分析。",
            "key_findings": [],
            "methodology_summary": "无",
            "agent_trace": traces,
        }

    task_descriptions = "\n".join(
        f"- [{t.id if hasattr(t, 'id') else t.get('id', '?')}] "
        f"{t.description if hasattr(t, 'description') else t.get('description', '')}"
        for t in task_plan
    )

    user_prompt = (
        f"研究主题: {topic}\n\n"
        f"子任务列表:\n{task_descriptions}\n\n"
        f"检索到的文献:\n{_format_docs_for_prompt(docs)}\n\n"
        f"请对以上文献进行深度分析，输出 JSON。"
    )

    try:
        messages = [
            {"role": "system", "content": ANALYZER_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        llm_result = _as_llm_result(await astream_llm_text(
            [(m["role"], m["content"]) for m in messages],
            model=model,
            temperature=0.3,
        ))
        text = llm_result.text

        data = parse_json_from_response(text)
        analysis_result = data.get("analysis_result", text)
        key_findings = data.get("key_findings", [])
        methodology_summary = data.get("methodology_summary", "")

        trace.output_summary = f"{len(key_findings)} findings, analysis {len(analysis_result)} chars"
        trace.token_usage = llm_result.token_usage
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info("Analyzer: %d key findings extracted", len(key_findings))
    except Exception as exc:
        logger.error("Analyzer failed: %s", exc)
        trace.error = str(exc)
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        # 降级：用文档摘要作为分析结果
        analysis_result = "\n\n".join(
            f"## {d.title if hasattr(d, 'title') else 'Document'}\n{d.content[:500] if hasattr(d, 'content') else str(d)[:500]}"
            for d in docs[:3]
        )
        key_findings = []
        methodology_summary = "分析失败，降级为文献摘要。"

    traces.append(trace)
    return {
        "analysis_result": analysis_result,
        "key_findings": key_findings,
        "methodology_summary": methodology_summary,
        "agent_trace": traces,
    }
