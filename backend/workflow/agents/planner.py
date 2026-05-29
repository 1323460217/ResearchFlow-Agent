import logging
import time
import uuid

from backend.core.llm import LLMStreamResult, astream_llm_with_usage, parse_json_from_response
from backend.workflow.state import AgentTrace, ResearchState, TaskNode

logger = logging.getLogger(__name__)

PLANNER_PROMPT = """你是一个科研任务规划专家。给定一个研究主题，你需要将其拆解为可执行的子任务，并生成用于论文检索的搜索查询。

输出格式要求（严格返回 JSON）:
```json
{
  "task_plan": [
    {
      "id": "t1",
      "description": "子任务描述",
      "depends_on": []
    }
  ],
  "search_queries": ["query 1", "query 2"]
}
```

规则:
- task_plan 包含 3-5 个子任务，按逻辑顺序排列
- 每个子任务有唯一 id (t1, t2, t3...)
- depends_on 列出该任务依赖的前置任务 id 列表
- search_queries 包含 3-5 个中英文检索词，覆盖研究主题的不同方面
- 检索词应包含关键技术术语和同义表达
"""


async def astream_llm_text(*args, **kwargs):
    return await astream_llm_with_usage(*args, **kwargs)


def _as_llm_result(value) -> LLMStreamResult:
    if isinstance(value, LLMStreamResult):
        return value
    return LLMStreamResult(text=value or "", token_usage=None)


async def planner_node(state: ResearchState) -> dict:
    """Planner agent — 将研究主题拆解为子任务和搜索查询。"""
    t0 = time.monotonic()
    topic = state.get("research_topic", "")
    model = state.get("model_override")

    traces = list(state.get("agent_trace", []))
    trace = AgentTrace(
        agent_name="planner",
        action="task_decomposition",
        input_summary=topic[:200],
        output_summary="",
    )

    if not topic:
        trace.error = "No research_topic in state"
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        traces.append(trace)
        return {"agent_trace": traces}

    try:
        user_prompt = f"研究主题: {topic}\n\n请拆解任务并生成搜索查询。"
        messages = [
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        llm_result = _as_llm_result(await astream_llm_text(
            [(m["role"], m["content"]) for m in messages],
            model=model,
            temperature=0.3,
        )) #返回的是LLMStreamResult对象(属性：text, token_usage)
        text = llm_result.text

        data = parse_json_from_response(text)
        task_plan = [TaskNode(**t) for t in data.get("task_plan", [])]
        search_queries = data.get("search_queries", [topic])
    
        trace.output_summary = f"{len(task_plan)} tasks, {len(search_queries)} queries"
        trace.token_usage = llm_result.token_usage
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info("Planner: %d tasks, %d queries", len(task_plan), len(search_queries))
    except Exception as exc:
        logger.error("Planner failed: %s", exc)
        trace.error = str(exc)
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        # 降级: 单任务 + 原主题作为查询
        task_plan = [TaskNode(id="t1", description=topic, depends_on=[])]
        search_queries = [topic]

    traces.append(trace)
    return {
        "task_plan": task_plan,
        "search_queries": search_queries,
        "current_task_index": 0,
        "agent_trace": traces,
    }
