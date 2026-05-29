import logging
import re
import time

from backend.core.llm import LLMStreamResult, astream_llm_with_usage
from backend.workflow.state import AgentTrace, ReportSection, ResearchState

logger = logging.getLogger(__name__)

REPORTER_PROMPT = """你是一个科研报告撰写专家。给定研究主题、分析结果和文献来源，你需要生成一份结构完整、内容详实的 Markdown 研究报告。

报告结构要求（使用 Markdown 标题）:
## 1. 研究概述
简要介绍研究背景、目标和范围。

## 2. 文献综述
梳理相关文献，总结主流方法和代表性工作。

## 3. 核心方法分析
深入分析关键技术的原理、优缺点和适用场景。

## 4. 关键发现
提炼研究中的核心发现和创新点，逐条列出。

## 5. 研究方向展望
展望未来的研究趋势和可能的突破方向。

## 6. 参考文献
列出报告中引用的文献（包含标题和链接）。

规则:
- 报告内容充实，总长度 800-2000 字
- 每条发现或结论尽量引用文献来源
- 使用学术语言但保持可读性
- 参考文献格式: [编号] 标题 (来源)
"""


async def astream_llm_text(*args, **kwargs):
    return await astream_llm_with_usage(*args, **kwargs)


def _as_llm_result(value) -> LLMStreamResult:
    if isinstance(value, LLMStreamResult):
        return value
    return LLMStreamResult(text=value or "", token_usage=None)


def _parse_report_sections(markdown: str) -> list[ReportSection]:
    """将 Markdown 报告按 ## 标题拆分为 ReportSection 列表。"""
    sections = []
    # 匹配 ## 标题及其后续内容
    pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(markdown))

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()
        sections.append(ReportSection(heading=heading, content=content, order=i + 1))

    return sections


def _format_sources_for_prompt(docs: list, max_docs: int = 10) -> str:
    """格式化文献来源列表。"""
    if not docs:
        return "（无文献来源）"

    lines = []
    for i, doc in enumerate(docs[:max_docs]):
        title = doc.title if hasattr(doc, 'title') else str(doc)
        source = doc.source if hasattr(doc, 'source') else ""
        url = doc.url if hasattr(doc, 'url') and doc.url else ""
        url_str = f" - {url}" if url else ""
        lines.append(f"[{i+1}] {title} ({source}){url_str}")
    return "\n".join(lines)


def _build_fallback_report(
    topic: str,
    analysis: str,
    findings_text: str,
    sources_text: str,
    error: Exception,
) -> str:
    """Build a useful deterministic report when the LLM call is unavailable."""
    return (
        f"# 研究报告: {topic}\n\n"
        f"> ⚠️ 报告生成失败 ({error})，以下为系统降级生成的研究报告框架。"
        f"由于当前无法调用大模型，内容应作为选题和实验设计草案，后续需要结合最新论文进一步校准。\n\n"
        f"## 1. 研究背景与问题定义\n\n"
        f"{analysis[:2000]}\n\n"
        f"本研究可围绕现有 YOLO 检测框架在小目标、复杂背景、遮挡、尺度变化和部署效率上的瓶颈展开。"
        f"如果 MFAE-YOLO 已经包含多尺度特征增强或注意力增强模块，改进时应优先避免只做模块堆叠，"
        f"而是明确改动解决的误检、漏检、速度或泛化问题。\n\n"
        f"## 2. 模型结构改进方向\n\n"
        f"- 特征融合: 对 Neck 部分进行轻量化跨层融合，比较 PAN/FPN、BiFPN、加权融合和跨尺度注意力的收益。\n"
        f"- 小目标增强: 在浅层高分辨率特征中加入细粒度纹理保留分支，减少下采样导致的信息损失。\n"
        f"- 注意力机制: 尝试通道、空间、坐标或动态注意力，但需要用消融实验验证其对 MFAE 模块的真实增益。\n"
        f"- 检测头改造: 比较解耦头、轻量检测头、Anchor-Free 设计和多尺度检测头对精度与速度的影响。\n"
        f"- 损失函数优化: 针对定位误差和类别不均衡，可评估 Wise-IoU、SIoU、Focal Loss 或质量感知分类损失。\n\n"
        f"## 3. 训练与数据增强方向\n\n"
        f"- 数据增强: 使用 Mosaic、MixUp、Copy-Paste、小目标复制增强和多尺度训练，重点观察小目标召回率变化。\n"
        f"- 样本重加权: 对困难样本、遮挡样本和小尺度目标做采样或损失权重调整。\n"
        f"- 迁移学习: 使用公开数据集预训练后迁移到目标场景，并比较冻结骨干、全量微调和分阶段训练策略。\n\n"
        f"## 4. 实验设计建议\n\n"
        f"- Baseline: 复现原始 MFAE-YOLO，记录 mAP、AP_small、FPS、参数量和 FLOPs。\n"
        f"- 单因素消融: 每次只加入一个改进模块，避免多个改动同时上线导致无法归因。\n"
        f"- 组合实验: 仅保留单因素实验中收益稳定且成本可控的模块组合。\n"
        f"- 鲁棒性实验: 在尺度变化、低光照、复杂背景、遮挡和跨数据集场景下验证泛化能力。\n"
        f"- 可视化分析: 使用 Grad-CAM、特征图响应和错误案例分类解释改进是否真正关注目标区域。\n\n"
        f"## 5. 关键发现\n\n"
        f"{findings_text}\n\n"
        f"## 6. 风险与下一步\n\n"
        f"- 风险: 只堆叠注意力或融合模块容易增加参数和延迟，却不一定提升泛化能力。\n"
        f"- 风险: 如果数据集规模较小，单次实验波动可能掩盖真实效果，需要固定随机种子并重复实验。\n"
        f"- 下一步: 先完成 MFAE-YOLO 复现，再选择 2-3 个方向做小规模消融，最后确定主创新点。\n\n"
        f"## 7. 参考来源\n\n"
        f"{sources_text}\n"
    )


async def reporter_node(state: ResearchState) -> dict:
    """Reporter agent — 生成最终 Markdown 研究报告。"""
    t0 = time.monotonic()
    topic = state.get("research_topic", "")
    analysis = state.get("analysis_result", "")
    findings = state.get("key_findings", [])
    docs = state.get("retrieved_docs", [])
    quality_score = state.get("quality_score", 0)
    iteration = state.get("iteration_count", 0)
    model = state.get("model_override")

    traces = list(state.get("agent_trace", []))
    trace = AgentTrace(
        agent_name="reporter",
        action="report_generation",
        input_summary=f"topic={topic[:100]}, score={quality_score:.2f}",
        output_summary="",
    )

    findings_text = "\n".join(f"- {f}" for f in findings) if findings else "（无）"
    sources_text = _format_sources_for_prompt(docs)
    forced = iteration >= state.get("max_iterations", 3) and quality_score < 0.7
    forced_note = "\n> ⚠️ 注意：本次报告在质量评分未达标但达到最大迭代次数的情况下生成，质量可能受限。\n" if forced else ""

    user_prompt = (
        f"研究主题: {topic}\n\n"
        f"分析结果:\n{analysis[:3000]}\n\n"
        f"关键发现:\n{findings_text}\n\n"
        f"文献来源:\n{sources_text}\n\n"
        f"质量评分: {quality_score:.2f}\n"
        f"{forced_note}\n"
        f"请生成完整的研究报告（Markdown 格式）。"
    )

    try:
        messages = [
            {"role": "system", "content": REPORTER_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        llm_result = _as_llm_result(await astream_llm_text(
            [(m["role"], m["content"]) for m in messages],
            model=model,
            temperature=0.4,
        ))
        final_report = llm_result.text
    except Exception as exc:
        logger.error("Reporter failed: %s", exc)
        trace.error = str(exc)
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        final_report = _build_fallback_report(
            topic=topic,
            analysis=analysis,
            findings_text=findings_text,
            sources_text=sources_text,
            error=exc,
        )
        traces.append(trace)
        return {
            "final_report": final_report,
            "report_sections": [ReportSection(heading="分析结果", content=analysis[:2000], order=1)],
            "agent_trace": traces,
        }

    report_sections = _parse_report_sections(final_report)

    trace.output_summary = f"Report {len(final_report)} chars, {len(report_sections)} sections"
    trace.token_usage = llm_result.token_usage
    trace.duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info("Reporter: report generated, %d chars, %d sections", len(final_report), len(report_sections))
    traces.append(trace)

    return {
        "final_report": final_report,
        "report_sections": report_sections,
        "agent_trace": traces,
    }
