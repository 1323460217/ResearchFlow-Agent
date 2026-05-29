from typing import Annotated, Any, List, Literal, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ── Sub-models ─────────────────────────────────────


class TaskNode(BaseModel):
    """Planner 生成的子任务"""

    # 子任务唯一标识，通常由 Planner 生成，如 "t1"、"t2"。
    id: str
    # 子任务的自然语言描述，用于说明该任务需要完成什么。
    description: str
    # 前置依赖任务 id 列表；为空表示该任务不依赖其他子任务。
    depends_on: List[str] = []
    # 子任务执行状态，用于跟踪计划执行进度。
    status: Literal["pending", "in_progress", "done"] = "pending"


class RetrievedDoc(BaseModel):
    """Retriever 返回的文档"""

    # 文档来源类型，例如 "arxiv"、"knowledge_base" 或 "mcp"。
    source: str  # "arxiv" | "knowledge_base" | "mcp"
    # 文档在来源系统中的唯一标识。
    doc_id: str
    # 文档标题。
    title: str
    # 文档正文或片段内容，用于后续分析和报告生成。
    content: str
    # 检索相关性分数，数值越高表示与查询越相关。
    relevance_score: float
    # 文档可访问链接；本地知识库文档可能没有 URL。
    url: Optional[str] = None


class ReportSection(BaseModel):
    """Reporter 生成的报告段落"""

    # 报告段落标题。
    heading: str
    # 报告段落正文。
    content: str
    # 报告段落排序序号，数值越小越靠前。
    order: int


class AgentTrace(BaseModel):
    """单步 agent 执行记录"""

    # 执行该步骤的 agent 名称，例如 planner、retriever、analyzer。
    agent_name: str
    # 当前 agent 执行的动作名称，用于区分同一 agent 的不同操作。
    action: str
    # 输入摘要，避免在 trace 中保存过长的完整输入。
    input_summary: str
    # 输出摘要，便于前端展示和问题排查。
    output_summary: str
    # 当前步骤耗时，单位为毫秒。
    duration_ms: int = 0
    # LLM token 使用量统计；未调用 LLM 或提供方未返回时为 None。
    token_usage: Optional[dict[str, Any]] = None
    # 当前步骤调用过的工具名称列表；未调用工具时为空列表。
    tool_calls: List[str] = []
    # 当前步骤异常信息；执行成功时为 None。
    error: Optional[str] = None


# ── Main State ─────────────────────────────────────


class ResearchState(TypedDict, total=False):
    """LangGraph 全局 State，所有 Agent 通过此 State 通信"""

    # ── 用户输入 ──
    # 对话消息列表，LangGraph 通过 add_messages 自动合并增量消息。
    messages: Annotated[List[BaseMessage], add_messages]
    # 用户提交的研究主题，是整个工作流的核心输入。
    research_topic: str
    # 当前用户 id，用于关联会话、权限、知识库和个性化信息。
    user_id: int

    # ── Planner 输出 ──
    # Planner 拆解出的子任务计划。
    task_plan: List[TaskNode]
    # 当前正在处理的子任务下标。
    current_task_index: int

    # ── Retriever 输出 ──
    # Query Rewrite 后生成的多组检索查询。
    search_queries: List[str]  # Query Rewrite 后的多组查询
    # Retriever 检索到的候选文档列表。
    retrieved_docs: List[RetrievedDoc]

    # ── Analyzer 输出 ──
    # Analyzer 输出的完整分析文本。
    analysis_result: str  # 完整分析文本
    # Analyzer 提炼出的关键发现列表。
    key_findings: List[str]  # 提炼的关键发现
    # Analyzer 总结的研究方法或技术路线。
    methodology_summary: str  # 方法概述

    # ── Critic 输出 ──
    # Critic 给出的质量评分，范围为 0.0 到 1.0。
    quality_score: float  # 0.0 - 1.0
    # Critic 的详细评审意见。
    critique_detail: str  # 详细评审意见
    # 是否需要根据 Critic 意见重新规划或修订。
    revision_needed: bool
    # 具体修订建议；不需要修订时通常为 None。
    revision_feedback: Optional[str]  # 具体修改建议

    # ── Reporter 输出 ──
    # Reporter 生成的结构化报告段落。
    report_sections: List[ReportSection]
    # 最终报告全文；报告未生成前为 None。
    final_report: Optional[str]

    # ── 元数据 ──
    # 当前工作流迭代次数，用于限制 Critic 触发的重试循环。
    iteration_count: int
    # 最大允许迭代次数，防止工作流无限循环。
    max_iterations: int  # 默认 3
    # 工作流状态，例如 "running"、"completed" 或 "failed"。
    workflow_status: str  # "running" | "completed" | "failed"
    # Agent 执行轨迹列表，用于监控、调试和前端展示。
    agent_trace: List[AgentTrace]
    # 是否启用 ReAct agent 路径。
    use_react: bool  # 是否使用 ReAct agent (Phase 4 集成)
    # 本次工作流使用的模型覆盖配置；为空时使用默认模型。
    model_override: Optional[str]  # 模型覆盖
    # 本次检索可用的知识库 collection 名称列表。
    kb_collections: List[str]  # 知识库 collection 名列表
