import logging
import time

from backend.core.llm import LLMStreamResult, astream_llm_with_usage, parse_json_from_response
from backend.workflow.state import AgentTrace, ResearchState

logger = logging.getLogger(__name__)

CRITIC_PROMPT = """你是一个严格的科研质量评审专家。你需要评估一份研究分析的质量，判断其是否达到可生成最终报告的标准。

输出格式要求（严格返回 JSON）:
```json
{
  "quality_score": 0.75,
  "critique_detail": "详细的评审意见",
  "revision_feedback": "具体的修改建议（评分<0.7时必填）"
}
```

评分标准 (0.0 - 1.0):
- 0.0-0.3: 分析严重不足，缺少核心信息
- 0.3-0.5: 分析不完整，关键方面遗漏
- 0.5-0.7: 分析基本合格，但深度或广度不足
- 0.7-0.85: 分析质量良好，覆盖主要方面
- 0.85-0.95: 分析优秀，深刻全面
- 0.95-1.0: 分析卓越，极具洞察力

评审维度:
1. 完整性: 是否覆盖了所有子任务
2. 深度: 是否深入分析了技术细节和创新点
3. 逻辑性: 分析结构是否清晰、论证是否合理
4. 实用性: 结论是否对后续研究有指导意义
5. 文献支撑: 分析是否有充分的文献依据
"""


async def astream_llm_text(*args, **kwargs):
    return await astream_llm_with_usage(*args, **kwargs)


def _as_llm_result(value) -> LLMStreamResult:
    if isinstance(value, LLMStreamResult):
        return value
    return LLMStreamResult(text=value or "", token_usage=None)


async def critic_node(state: ResearchState) -> dict:
    """Critic agent — 评估分析质量，决定是否需要重新规划。"""
    t0 = time.monotonic()
    topic = state.get("research_topic", "")
    analysis = state.get("analysis_result", "")
    findings = state.get("key_findings", [])
    doc_count = len(state.get("retrieved_docs", []))
    iteration = state.get("iteration_count", 0)
    model = state.get("model_override")

    traces = list(state.get("agent_trace", []))
    trace = AgentTrace(
        agent_name="critic",
        action="quality_assessment",
        input_summary=f"topic={topic[:100]}, iteration={iteration}",
        output_summary="",
    )

    # 没有分析内容时直接给低分
    if not analysis:
        trace.output_summary = "No analysis to evaluate, score=0"
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        traces.append(trace)
        return {
            "quality_score": 0.0,
            "critique_detail": "无分析内容可供评估。",
            "revision_needed": True,
            "revision_feedback": "请先完成文献检索和分析。",
            "iteration_count": iteration + 1,
            "agent_trace": traces,
        }

    findings_text = "\n".join(f"- {f}" for f in findings) if findings else "（无）"
    user_prompt = (
        f"研究主题: {topic}\n\n"
        f"分析结果:\n{analysis[:3000]}\n\n"
        f"关键发现:\n{findings_text}\n\n"
        f"文献数量: {doc_count}\n"
        f"当前迭代次数: {iteration}\n\n"
        f"请评估以上分析的质量，输出 JSON。"
    )

    try:
        messages = [
            {"role": "system", "content": CRITIC_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        llm_result = _as_llm_result(await astream_llm_text(
            [(m["role"], m["content"]) for m in messages],
            model=model,
            temperature=0.2,
        ))
        text = llm_result.text

        data = parse_json_from_response(text)
        quality_score = float(data.get("quality_score", 0.5))
        critique_detail = data.get("critique_detail", "")
        revision_feedback = data.get("revision_feedback", "")
        revision_needed = quality_score < 0.7

        # 确保分数在 [0, 1] 范围内
        quality_score = max(0.0, min(1.0, quality_score))

        trace.output_summary = f"score={quality_score:.2f}, revision_needed={revision_needed}"
        trace.token_usage = llm_result.token_usage
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info("Critic: score=%.2f, revision=%s", quality_score, revision_needed)
    except Exception as exc:
        logger.error("Critic failed: %s", exc)
        trace.error = str(exc)
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        # 降级: 给通过分数以推进流程
        quality_score = 0.75
        critique_detail = f"评审出错 ({exc})，降级为自动通过。"
        revision_feedback = ""
        revision_needed = False

    traces.append(trace)
    return {
        "quality_score": quality_score,
        "critique_detail": critique_detail,
        "revision_needed": revision_needed,
        "revision_feedback": revision_feedback if revision_needed else None,
        "iteration_count": iteration + 1,
        "agent_trace": traces,
    }
