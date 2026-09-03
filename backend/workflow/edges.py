import logging

from backend.workflow.state import ResearchState

logger = logging.getLogger(__name__)

# Node name constants
PLANNER = "planner"
RETRIEVER = "retriever"
ANALYZER = "analyzer"
CRITIC = "critic"
REPORTER = "reporter"


def should_continue(state: ResearchState) -> str:
    """Critic 之后的条件路由。

    score >= 0.7 → Reporter (质量合格)
    iteration_count >= max_iterations → Reporter (强制输出，防止无限循环)
    否则 → Planner (带着 critique feedback 重新规划)
    """
    score = state.get("quality_score", 0)
    iteration = state.get("iteration_count", 0)
    max_iter = state.get("max_iterations", 3)

    logger.info(
        "Conditional edge: score=%.3f iteration=%d/%d",
        score, iteration, max_iter,
    )

    if state.get("workflow_status") == "failed" or state.get("revision_action") == "stop":
        logger.info("Workflow failed closed, routing to reporter for a failure notice")
        return REPORTER

    if score >= 0.7:
        logger.info("Quality passed, routing to reporter")
        return REPORTER

    if iteration >= max_iter:
        logger.info("Max iterations reached, forcing reporter")
        return REPORTER

    logger.info("Quality below threshold, re-planning")
    return PLANNER
