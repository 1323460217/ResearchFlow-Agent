import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy import select

from backend.api.serialization import sanitize_for_json
from backend.api.workflow_helpers import (
    build_workflow_initial_state,
    langchain_messages_from_history,
    merge_langgraph_output,
)
from backend.core.security import decode_token
from backend.database.session import async_session_factory
from backend.memory.chat_memory import ChatMemory
from backend.models.conversation import Conversation
from backend.models.knowledge_base import KnowledgeBase
from backend.models.message import Message
from backend.models.user import User
from backend.workflow.graph import graph

router = APIRouter()
logger = logging.getLogger(__name__)

AGENT_NODE_NAMES = {"planner", "retriever", "analyzer", "critic", "reporter"}


async def _authenticate_ws(websocket: WebSocket) -> Optional[User]:
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = decode_token(token)
    except JWTError:
        return None
    if payload.get("type") != "access":
        return None
    user_id_str = payload.get("sub")
    if user_id_str is None:
        return None
    user_id = int(user_id_str)
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        return user


@router.websocket("/ws/agent-stream")
async def agent_stream(websocket: WebSocket):
    await websocket.accept()

    user = await _authenticate_ws(websocket)
    if user is None:
        await websocket.send_json({"type": "error", "data": {"message": "Unauthorized"}})
        await websocket.close(code=4001)
        return

    workflow_task: Optional[asyncio.Task] = None

    async def _send_event(typ: str, data: dict):
        try:
            await websocket.send_json({"type": typ, "data": sanitize_for_json(data)})
        except Exception:
            pass

    async def _run_workflow(conv: Conversation, user_msg: Message, chat_request: dict):
        kb_ids = chat_request.get("knowledge_base_ids", [])
        kb_collections: list[str] = []
        if kb_ids:
            async with async_session_factory() as db:
                kb_result = await db.execute(
                    select(KnowledgeBase.collection_name).where(
                        KnowledgeBase.id.in_(kb_ids),
                        KnowledgeBase.user_id == user.id,
                    )
                )
                kb_collections = [row[0] for row in kb_result.fetchall()]

        chat_memory = ChatMemory(session_id=conv.thread_id)
        history = await chat_memory.load_history(limit=20)
        langchain_messages = langchain_messages_from_history(history)

        initial_state = build_workflow_initial_state(
            message=chat_request.get("message", ""),
            user_id=user.id,
            max_iterations=chat_request.get("max_iterations", 3),
            kb_collections=kb_collections,
            model=chat_request.get("model"),
            use_react=chat_request.get("use_react", True),
            messages=langchain_messages,
        )
        config = {"configurable": {"thread_id": conv.thread_id}}

        final_state = {}
        _current_agent = None
        try:
            async for event in graph.astream_events(initial_state, config=config, version="v1"):
                kind = event["event"]
                name = event["name"]

                if kind == "on_chain_start" and name in AGENT_NODE_NAMES:
                    _current_agent = name
                    await _send_event("agent_status", {"agent_name": name, "status": "started"})

                elif kind == "on_chain_end" and name in AGENT_NODE_NAMES:
                    output = event.get("data", {}).get("output")
                    out_data = {}
                    if isinstance(output, dict):
                        if name == "planner":
                            out_data = {
                                "task_count": len(output.get("task_plan", [])),
                                "query_count": len(output.get("search_queries", [])),
                            }
                        elif name == "critic":
                            out_data = {"quality_score": output.get("quality_score", 0)}
                        elif name == "reporter":
                            out_data = {"report_length": len(output.get("final_report", ""))}
                    await _send_event("agent_status", {
                        "agent_name": name, "status": "completed", "output": out_data,
                    })
                    if name == _current_agent:
                        _current_agent = None

                elif kind == "on_chat_model_stream":
                    # Only stream tokens from the Reporter — same behavior as SSE endpoint
                    if _current_agent == "reporter":
                        chunk = event.get("data", {}).get("chunk")
                        content = chunk.content if hasattr(chunk, "content") else str(chunk) if chunk else ""
                        if content:
                            await _send_event("token", {"content": content})

                elif kind == "on_tool_start":
                    await _send_event("tool_call", {
                        "name": name, "action": "started",
                        "input": event.get("data", {}).get("input"),
                    })

                elif kind == "on_tool_end":
                    await _send_event("tool_call", {
                        "name": name, "action": "completed",
                        "output": event.get("data", {}).get("output"),
                    })

                if kind == "on_chain_end" and name == "LangGraph":
                    merge_langgraph_output(final_state, event.get("data", {}).get("output", {}))

            # Save results
            final_report = final_state.get("final_report", "")
            assistant_content = final_report or final_state.get("analysis_result", "") or "[工作流完成]"
            quality_score = final_state.get("quality_score", 0)

            sources = sanitize_for_json(final_state.get("retrieved_docs", []))
            agent_trace = sanitize_for_json(final_state.get("agent_trace", []))

            async with async_session_factory() as db:
                assistant_msg = Message(
                    conversation_id=conv.id,
                    role="assistant",
                    content=assistant_content,
                    token_count=0,
                )
                db.add(assistant_msg)
                if conv.title == chat_request.get("message", "")[:50]:
                    conv.title = chat_request.get("message", "")[:40] + (
                        "..." if len(chat_request.get("message", "")) > 40 else ""
                    )
                await db.flush()
                await db.commit()

            await chat_memory.save("assistant", assistant_content)

            await _send_event("done", {
                "conversation_id": conv.id,
                "message_id": assistant_msg.id,
                "quality_score": quality_score,
                "sources": sources,
                "agent_trace": agent_trace,
            })

        except asyncio.CancelledError:
            await _send_event("agent_status", {
                "agent_name": "workflow", "status": "cancelled",
            })
            await _send_event("done", {
                "conversation_id": conv.id,
                "message_id": 0,
                "quality_score": 0,
            })
        except Exception as exc:
            logger.exception("WebSocket workflow failed: %s", exc)
            await _send_event("error", {"message": str(exc)})
            await _send_event("done", {
                "conversation_id": conv.id,
                "message_id": 0,
                "quality_score": 0,
            })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_event("error", {"message": "Invalid JSON"})
                continue

            action = msg.get("action")

            if action == "chat":
                if workflow_task and not workflow_task.done():
                    await _send_event("error", {"message": "Workflow already running"})
                    continue

                message_text = msg.get("message", "")
                if not message_text:
                    await _send_event("error", {"message": "Message is required"})
                    continue

                conversation_id = msg.get("conversation_id")
                async with async_session_factory() as db:
                    conversation = None
                    if conversation_id:
                        result = await db.execute(
                            select(Conversation).where(
                                Conversation.id == conversation_id,
                                Conversation.user_id == user.id,
                            )
                        )
                        conversation = result.scalar_one_or_none()

                    if conversation is None:
                        conversation = Conversation(
                            user_id=user.id,
                            title=message_text[:50],
                            thread_id=f"th-{uuid.uuid4().hex[:16]}",
                        )
                        db.add(conversation)
                        await db.flush()

                    user_msg_obj = Message(
                        conversation_id=conversation.id,
                        role="user",
                        content=message_text,
                    )
                    db.add(user_msg_obj)
                    await db.flush()
                    await db.commit()

                chat_memory = ChatMemory(session_id=conversation.thread_id)
                await chat_memory.save("user", message_text)

                workflow_task = asyncio.create_task(
                    _run_workflow(conversation, user_msg_obj, msg)
                )

            elif action == "cancel":
                if workflow_task and not workflow_task.done():
                    workflow_task.cancel()
                    await _send_event("agent_status", {
                        "agent_name": "workflow", "status": "cancelling",
                    })
                else:
                    await _send_event("error", {"message": "No running workflow to cancel"})

            else:
                await _send_event("error", {"message": f"Unknown action: {action}"})

    except WebSocketDisconnect:
        if workflow_task and not workflow_task.done():
            workflow_task.cancel()
        logger.info("WebSocket disconnected for user %d", user.id)
    except Exception as exc:
        logger.exception("WebSocket error for user %d: %s", user.id, exc)
        if workflow_task and not workflow_task.done():
            workflow_task.cancel()
