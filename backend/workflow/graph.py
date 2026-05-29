import logging

from langgraph.graph import END, START, StateGraph

from backend.workflow.agents.analyzer import analyzer_node
from backend.workflow.agents.critic import critic_node
from backend.workflow.agents.planner import planner_node
from backend.workflow.agents.reporter import reporter_node
from backend.workflow.agents.retriever import retriever_node
from backend.workflow.edges import (
    ANALYZER,
    CRITIC,
    PLANNER,
    REPORTER,
    RETRIEVER,
    should_continue,
)
from backend.workflow.state import ResearchState

logger = logging.getLogger(__name__)


# ── Graph construction ─────────────────────────────


def build_graph() -> StateGraph:
    """构建并编译 LangGraph 工作流图。

    流程: START → Planner → Retriever → Analyzer → Critic
              ↑                                      │
              └────────── (re-plan) ─────────────────┘
                                                      │
                                             Reporter ← (quality OK | max iter)
                                                      │
                                                     END

    所有 agent 节点均为 async 函数，使用 graph.ainvoke() 调用。
    """
    builder = StateGraph(ResearchState)

    # 注册节点
    builder.add_node(PLANNER, planner_node)
    builder.add_node(RETRIEVER, retriever_node)
    builder.add_node(ANALYZER, analyzer_node)
    builder.add_node(CRITIC, critic_node)
    builder.add_node(REPORTER, reporter_node)

    # 固定边
    builder.add_edge(START, PLANNER)
    builder.add_edge(PLANNER, RETRIEVER)
    builder.add_edge(RETRIEVER, ANALYZER)
    builder.add_edge(ANALYZER, CRITIC)

    # 条件边: Critic → Reporter (通过) 或 Planner (重新规划)
    builder.add_conditional_edges(CRITIC, should_continue)

    # 终点
    builder.add_edge(REPORTER, END)

    from backend.memory.checkpoint import get_checkpointer

    return builder.compile(checkpointer=get_checkpointer())


# 模块级单例
graph = build_graph()
