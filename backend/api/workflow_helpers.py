from typing import Any

from langchain_core.messages import AIMessage, HumanMessage


def langchain_messages_from_history(history: list[dict]) -> list:
    messages = []
    for msg in history:
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg.get("content", "")))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg.get("content", "")))
    return messages


def build_workflow_initial_state(
    *,
    message: str,
    user_id: int,
    max_iterations: int,
    kb_collections: list[str],
    model: str | None,
    use_react: bool,
    messages: list,
) -> dict:
    return {
        "research_topic": message,
        "user_id": user_id,
        "max_iterations": max_iterations,
        "kb_collections": kb_collections,
        "model_override": model or None,
        "iteration_count": 0,
        "workflow_status": "running",
        "agent_trace": [],
        "use_react": use_react,
        "messages": messages,
    }


def merge_langgraph_output(final_state: dict, graph_output: Any) -> None:
    if not isinstance(graph_output, dict):
        return

    for key, value in graph_output.items():
        if isinstance(value, dict) and not key.startswith("_"):
            for inner_key, inner_value in value.items():
                if (
                    inner_key not in final_state
                    and (
                        isinstance(inner_value, (str, list, float, int, bool, dict))
                        or inner_value is None
                    )
                ):
                    final_state[inner_key] = inner_value

        if key not in final_state:
            final_state[key] = value
