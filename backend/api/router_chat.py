import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.schemas import (
    ApiResponse,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationItem,
    MessageItem,
)
from backend.api.serialization import sanitize_for_json
from backend.api.workflow_helpers import (
    build_workflow_initial_state,
    langchain_messages_from_history,
    merge_langgraph_output,
)
from backend.core.exceptions import NotFoundError
from backend.database.session import get_db
from backend.memory.chat_memory import ChatMemory
from backend.memory.user_profile import UserProfile
from backend.models.conversation import Conversation
from backend.models.agent_execution import AgentExecution
from backend.models.knowledge_base import KnowledgeBase
from backend.models.message import Message
from backend.models.research_report import ResearchReport
from backend.models.user import User
from backend.workflow.graph import graph

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)


async def _save_research_report_from_state(
    db: AsyncSession,
    user_id: int,
    conversation_id: int,
    topic: str,
    final_state: dict,
) -> None:
    final_report = final_state.get("final_report") or ""
    if not final_report.strip():
        return

    report = ResearchReport(
        user_id=user_id,
        conversation_id=conversation_id,
        title=(topic or "研究报告")[:100],
        content=final_report,
        sections=sanitize_for_json(final_state.get("report_sections", [])) or None,
        sources=sanitize_for_json(final_state.get("retrieved_docs", [])) or None,
        status="completed",
    )
    db.add(report)


async def _save_agent_executions_from_trace(
    db: AsyncSession,
    user_id: int,
    conversation_id: int,
    agent_trace: list,
) -> None:
    for trace in agent_trace or []:
        trace_data = sanitize_for_json(trace)
        if not isinstance(trace_data, dict):
            continue

        error = trace_data.get("error")
        execution = AgentExecution(
            user_id=user_id,
            conversation_id=conversation_id,
            agent_name=trace_data.get("agent_name") or trace_data.get("agent") or "unknown",
            status="failed" if error else "completed",
            input_state={"summary": trace_data.get("input_summary")},
            output_state={
                "summary": trace_data.get("output_summary"),
                "action": trace_data.get("action"),
            },
            token_usage=trace_data.get("token_usage"),
            tool_calls=trace_data.get("tool_calls"),
            error_message=error,
            duration_ms=trace_data.get("duration_ms"),
        )
        db.add(execution)


async def _update_user_profile(user_id: int, topic: str, final_state: dict) -> None:
    """后台更新用户画像（fire-and-forget，不阻塞响应）。"""
    try:
        key_findings = final_state.get("key_findings", [])
        profile = UserProfile(user_id)
        await profile.update_from_research(topic=topic, findings=key_findings)
    except Exception as exc:
        logger.warning("UserProfile update failed for user=%d: %s", user_id, exc)


@router.post("/chat", response_model=ApiResponse)
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Find or create conversation
    conversation: Conversation | None = None
    if body.conversation_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == body.conversation_id,
                Conversation.user_id == user.id,
            )
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise NotFoundError("会话")

    if conversation is None:
        conversation = Conversation(
            user_id=user.id,
            title=body.message[:50],
            thread_id=f"th-{uuid.uuid4().hex[:16]}",
        )
        db.add(conversation)
        await db.flush()

    # Save user message
    user_msg = Message(conversation_id=conversation.id, role="user", content=body.message)
    db.add(user_msg)
    await db.flush()

    # ── Memory: load chat history from Redis ──
    chat_memory = ChatMemory(session_id=conversation.thread_id)
    await chat_memory.save("user", body.message)

    history = await chat_memory.load_history(limit=20)

    # Fallback to PostgreSQL if Redis history is empty (e.g. TTL expired)
    if not history and body.conversation_id:
        pg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == body.conversation_id)
            .order_by(Message.created_at.desc())
            .limit(20)
        )
        pg_messages = pg_result.scalars().all()
        history = [
            {"role": m.role, "content": m.content}
            for m in reversed(pg_messages)
        ]

    langchain_messages = langchain_messages_from_history(history)

    # Resolve kb_collections: auto-select all user KBs if none specified
    if body.knowledge_base_ids:
        kb_result = await db.execute(
            select(KnowledgeBase.collection_name).where(
                KnowledgeBase.id.in_(body.knowledge_base_ids),
                KnowledgeBase.user_id == user.id,
            )
        )
    else:
        kb_result = await db.execute(
            select(KnowledgeBase.collection_name).where(
                KnowledgeBase.user_id == user.id,
            )
        )
    kb_collections = [row[0] for row in kb_result.fetchall()]

    # Run Agent Workflow
    initial_state = build_workflow_initial_state(
        message=body.message,
        user_id=user.id,
        max_iterations=body.max_iterations,
        kb_collections=kb_collections,
        model=body.model,
        use_react=body.use_react,
        messages=langchain_messages,
    )
    config = {"configurable": {"thread_id": conversation.thread_id}}

    try:
        final_state = await graph.ainvoke(initial_state, config)
    except Exception as e:
        logger.exception("Workflow failed: %s", e)
        assistant_content = f"[研究工作流执行失败: {e}]"
        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_content,
            token_count=0,
        )
        db.add(assistant_msg)
        await db.flush()
        return ApiResponse(
            data=ChatResponse(
                conversation_id=conversation.id,
                message_id=assistant_msg.id,
                response=assistant_content,
            )
        )

    # Extract results from workflow
    final_report = final_state.get("final_report", "")
    analysis_result = final_state.get("analysis_result", "")
    assistant_content = final_report or analysis_result or "[工作流完成，但未生成内容]"
    quality_score = final_state.get("quality_score", 0)

    agent_trace = sanitize_for_json(final_state.get("agent_trace", []))
    sources = sanitize_for_json(final_state.get("retrieved_docs", []))

    # ── Memory: save assistant message to Redis ──
    await chat_memory.save("assistant", assistant_content)

    # ── Memory: update user profile (fire-and-forget) ──
    asyncio.create_task(_update_user_profile(user.id, body.message, final_state))

    # Save assistant message (with sources + agent_trace in metadata)
    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=assistant_content,
        token_count=0,
        extra_metadata={"sources": sources, "agent_trace": agent_trace},
    )
    db.add(assistant_msg)
    await _save_research_report_from_state(
        db=db,
        user_id=user.id,
        conversation_id=conversation.id,
        topic=body.message,
        final_state=final_state,
    )
    await _save_agent_executions_from_trace(
        db=db,
        user_id=user.id,
        conversation_id=conversation.id,
        agent_trace=agent_trace,
    )

    # Update conversation title on first message
    if conversation.title == body.message[:50]:
        conversation.title = body.message[:40] + ("..." if len(body.message) > 40 else "")
    # Note: updated_at is handled by SQLAlchemy onupdate=func.now() automatically on any UPDATE

    await db.flush()

    return ApiResponse(
        data=ChatResponse(
            conversation_id=conversation.id,
            message_id=assistant_msg.id,
            response=assistant_content,
            sources=sources,
            agent_trace=agent_trace,
            quality_score=quality_score,
        )
    )


AGENT_NODE_NAMES = {"planner", "retriever", "analyzer", "critic", "reporter"}


def _format_sse(typ: str, data: dict) -> str:
    return f"data: {json.dumps({'type': typ, 'data': sanitize_for_json(data)}, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation: Conversation | None = None
    if body.conversation_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == body.conversation_id,
                Conversation.user_id == user.id,
            )
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise NotFoundError("会话")

    if conversation is None:
        conversation = Conversation(
            user_id=user.id,
            title=body.message[:50],
            thread_id=f"th-{uuid.uuid4().hex[:16]}",
        )
        db.add(conversation)
        await db.flush()

    user_msg = Message(conversation_id=conversation.id, role="user", content=body.message)
    db.add(user_msg)
    await db.flush()

    chat_memory = ChatMemory(session_id=conversation.thread_id)
    await chat_memory.save("user", body.message)

    history = await chat_memory.load_history(limit=20)

    # Fallback to PostgreSQL if Redis history is empty (e.g. TTL expired)
    if not history and body.conversation_id:
        pg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == body.conversation_id)
            .order_by(Message.created_at.desc())
            .limit(20)
        )
        pg_messages = pg_result.scalars().all()
        history = [
            {"role": m.role, "content": m.content}
            for m in reversed(pg_messages)
        ]

    langchain_messages = langchain_messages_from_history(history)

    if body.knowledge_base_ids:
        kb_result = await db.execute(
            select(KnowledgeBase.collection_name).where(
                KnowledgeBase.id.in_(body.knowledge_base_ids),
                KnowledgeBase.user_id == user.id,
            )
        )
    else:
        kb_result = await db.execute(
            select(KnowledgeBase.collection_name).where(
                KnowledgeBase.user_id == user.id,
            )
        )
    kb_collections = [row[0] for row in kb_result.fetchall()]

    initial_state = build_workflow_initial_state(
        message=body.message,
        user_id=user.id,
        max_iterations=body.max_iterations,
        kb_collections=kb_collections,
        model=body.model,
        use_react=body.use_react,
        messages=langchain_messages,
    )
    config = {"configurable": {"thread_id": conversation.thread_id}}

    async def _event_stream():
        final_state = {}
        _current_agent = None
        try:
            async for event in graph.astream_events(initial_state, config=config, version="v1"):
                kind = event["event"]
                name = event["name"]

                if kind == "on_chain_start" and name in AGENT_NODE_NAMES:
                    _current_agent = name
                    yield _format_sse("agent_status", {"agent_name": name, "status": "started"})

                elif kind == "on_chain_end" and name in AGENT_NODE_NAMES:
                    output = event.get("data", {}).get("output")
                    # Accumulate node output into final_state
                    if isinstance(output, dict):
                        for k, v in output.items():
                            if k not in final_state or final_state[k] is None:
                                final_state[k] = v
                    logger.info(
                        "AGENT END name=%s output_keys=%s final_state_keys=%s final_report_in_state=%s",
                        name,
                        list(output.keys()) if isinstance(output, dict) else type(output).__name__,
                        list(final_state.keys()),
                        "final_report" in final_state,
                    )
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
                    yield _format_sse("agent_status", {
                        "agent_name": name, "status": "completed",
                        "duration_ms": 0, "output_summary": str(out_data),
                    })
                    if name == _current_agent:
                        _current_agent = None

                elif kind == "on_chat_model_stream":
                    # Only stream tokens from the Reporter (final markdown report).
                    # Planner / Analyzer / Critic produce internal JSON — skip those.
                    if _current_agent == "reporter":
                        chunk = event.get("data", {}).get("chunk")
                        content = chunk.content if hasattr(chunk, "content") else str(chunk) if chunk else ""
                        if content:
                            yield _format_sse("token", {"content": content})

                elif kind == "on_tool_start":
                    yield _format_sse("tool_call", {
                        "name": name, "action": "started",
                        "input": event.get("data", {}).get("input"),
                    })

                elif kind == "on_tool_end":
                    yield _format_sse("tool_call", {
                        "name": name, "action": "completed",
                        "output": event.get("data", {}).get("output"),
                    })

                if kind == "on_chain_end" and name == "LangGraph":
                    graph_output = event.get("data", {}).get("output", {})
                    logger.info(
                        "LANGGRAPH END output_type=%s output_keys=%s",
                        type(graph_output).__name__,
                        list(graph_output.keys()) if isinstance(graph_output, dict) else "N/A",
                    )
                    merge_langgraph_output(final_state, graph_output)

            # Extract results from final state
            logger.debug(
                "EXTRACT final_state_keys=%s final_report=%s analysis_result=%s",
                list(final_state.keys()),
                repr(final_state.get("final_report", ""))[:120],
                repr(final_state.get("analysis_result", ""))[:120],
            )
            final_report = final_state.get("final_report", "")
            assistant_content = final_report or final_state.get("analysis_result", "") or "[工作流完成]"
            quality_score = final_state.get("quality_score", 0)

            agent_trace = sanitize_for_json(final_state.get("agent_trace", []))
            sources = sanitize_for_json(final_state.get("retrieved_docs", []))

            # Save assistant message (with sources + agent_trace in metadata)
            assistant_msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=assistant_content,
                token_count=0,
                extra_metadata={"sources": sources, "agent_trace": agent_trace},
            )
            db.add(assistant_msg)
            await _save_research_report_from_state(
                db=db,
                user_id=user.id,
                conversation_id=conversation.id,
                topic=body.message,
                final_state=final_state,
            )
            await _save_agent_executions_from_trace(
                db=db,
                user_id=user.id,
                conversation_id=conversation.id,
                agent_trace=agent_trace,
            )
            if conversation.title == body.message[:50]:
                conversation.title = body.message[:40] + ("..." if len(body.message) > 40 else "")
            await db.flush()
            await db.commit()

            await chat_memory.save("assistant", assistant_content)
            asyncio.create_task(_update_user_profile(user.id, body.message, final_state))

            yield _format_sse("done", {
                "conversation_id": conversation.id,
                "message_id": assistant_msg.id,
                "quality_score": quality_score,
                "sources": sources,
                "agent_trace": agent_trace,
            })

        except Exception as exc:
            logger.exception("SSE stream failed: %s", exc)
            yield _format_sse("error", {"message": str(exc)})
            yield _format_sse("done", {
                "conversation_id": conversation.id,
                "message_id": 0,
                "quality_score": 0,
                "sources": [],
                "agent_trace": [],
            })

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=ApiResponse)
async def list_conversations(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    offset = (page - 1) * page_size

    # Count total
    from sqlalchemy import func
    count_result = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.user_id == user.id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = [ConversationItem.model_validate(c) for c in result.scalars().all()]
    return ApiResponse(data={
        "items": [i.model_dump() for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/conversations/{conv_id}", response_model=ApiResponse)
async def get_conversation(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.id == conv_id,
            Conversation.user_id == user.id,
        )
        .options(selectinload(Conversation.messages))
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("会话")

    detail = ConversationDetail(
        id=conv.id,
        title=conv.title,
        thread_id=conv.thread_id,
        status=conv.status,
        messages=[MessageItem.model_validate(m) for m in conv.messages],
        created_at=conv.created_at,
    )
    return ApiResponse(data=detail)


@router.delete("/conversations/{conv_id}", response_model=ApiResponse)
async def delete_conversation(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("会话")

    thread_id = conv.thread_id
    await db.delete(conv)

    # Clean up Redis data (chat history + checkpoint)
    try:
        chat_memory = ChatMemory(session_id=thread_id)
        await chat_memory.clear()
    except Exception as exc:
        logger.warning("Failed to clear Redis chat memory for %s: %s", thread_id, exc)

    return ApiResponse(message="已删除")
