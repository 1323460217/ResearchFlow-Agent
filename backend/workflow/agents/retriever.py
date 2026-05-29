import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from backend.workflow.state import AgentTrace, ResearchState, RetrievedDoc

logger = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_DELAY = 3.5  # ArXiv 要求请求间隔 >= 3 秒
MAX_RETRIES = 2


def _search_arxiv_sync(query: str, max_results: int = 5) -> List[RetrievedDoc]:
    """同步查询 ArXiv API，带重试和退避。"""
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "max_results": str(max_results),
        "sortBy": "relevance",
    })
    url = f"{ARXIV_API_URL}?{params}"

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ResearchFlow-Agent/0.1"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 429:
                    wait = (attempt + 1) * 5
                    logger.debug("ArXiv 429, retrying in %ds", wait)
                    time.sleep(wait)
                    continue
                xml_data = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = (attempt + 1) * 5
                logger.debug("ArXiv 429 for %r, retry %d/%d in %ds", query, attempt + 1, MAX_RETRIES, wait)
                time.sleep(wait)
            else:
                logger.warning("ArXiv HTTP %d for %r: %s", exc.code, query, exc)
                return []
        except Exception as exc:
            if attempt < MAX_RETRIES - 1:
                logger.debug("ArXiv retry %d/%d for %r: %s", attempt + 1, MAX_RETRIES, query, exc)
                time.sleep(2)
            else:
                logger.warning("ArXiv API call failed for %r: %s", query, exc)
                return []
    else:
        logger.warning("ArXiv exhausted retries for %r", query)
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        logger.warning("ArXiv XML parse error: %s", exc)
        return []

    docs = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        title_el = entry.find("atom:title", ARXIV_NS)
        summary_el = entry.find("atom:summary", ARXIV_NS)
        id_el = entry.find("atom:id", ARXIV_NS)

        title = (title_el.text or "").strip().replace("\n", " ")
        summary = (summary_el.text or "").strip().replace("\n", " ")
        arxiv_id = (id_el.text or "").strip()
        arxiv_id = arxiv_id.split("/abs/")[-1] if "/abs/" in arxiv_id else arxiv_id
        url = f"https://arxiv.org/abs/{arxiv_id}"

        docs.append(RetrievedDoc(
            source="arxiv",
            doc_id=arxiv_id,
            title=title,
            content=summary,
            relevance_score=0.8,
            url=url,
        ))

    return docs


async def _search_arxiv(query: str, max_results: int = 5) -> List[RetrievedDoc]:
    """异步包装 ArXiv 搜索，串行化以避免触发限流。"""
    return await asyncio.to_thread(_search_arxiv_sync, query, max_results)


async def _search_kb(query: str, kb_collections: List[str], top_k: int = 5) -> List[RetrievedDoc]:
    """从本地知识库检索并转换为 RetrievedDoc。"""
    if not kb_collections:
        return []

    from backend.rag.retrieval import retrieve_with_rewrite

    results = []
    for coll_name in kb_collections:
        try:
            chunks, _rewrites = await retrieve_with_rewrite(
                query=query,
                collection_name=coll_name,
                top_k=top_k,
                num_rewrites=3,
                use_rerank=True,
                use_hyde=True,
            )
        except Exception as exc:
            logger.warning("KB search failed for %s: %s", coll_name, exc)
            continue

        for chunk in chunks:
            if any(r.doc_id == chunk.chunk_id for r in results):
                continue
            results.append(RetrievedDoc(
                source="knowledge_base",
                doc_id=chunk.chunk_id,
                title=chunk.filename,
                content=chunk.content,
                relevance_score=chunk.score,
            ))

    return results


def _extract_docs_from_results(tool_results: list) -> List[RetrievedDoc]:
    """从工具执行结果中提取 RetrievedDoc 列表（直接处理返回值，不依赖 ToolMessage）。"""
    docs: List[RetrievedDoc] = []
    seen = set()
    for tool_name, result in tool_results:
        if tool_name not in ("arxiv_search", "rag_retriever"):
            continue
        try:
            items = result
            if isinstance(items, str):
                items = json.loads(items)
            if isinstance(items, dict):
                items = [items]
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            doc_id = item.get("doc_id") or item.get("chunk_id", "")
            key = f"{tool_name}:{doc_id}"
            if key in seen:
                continue
            seen.add(key)
            docs.append(RetrievedDoc(
                source="arxiv" if tool_name == "arxiv_search" else "knowledge_base",
                doc_id=doc_id,
                title=item.get("title", item.get("filename", "")),
                content=item.get("content") or item.get("summary", ""),
                relevance_score=float(item.get("score", item.get("relevance_score", 0.5))),
                url=item.get("url"),
            ))
    return docs


async def _retriever_react(state: ResearchState) -> dict:
    """ReAct 模式检索 — 手动 ReAct 循环,避免嵌套 LangGraph 图的 checkpointer 序列化问题。"""
    from backend.core.llm import get_llm
    from backend.mcp import get_tool_router

    t0 = time.monotonic()
    topic = state.get("research_topic", "")
    task_plan = state.get("task_plan", [])
    model = state.get("model_override")
    kb_collections = state.get("kb_collections", [])

    traces = list(state.get("agent_trace", []))
    trace = AgentTrace(
        agent_name="retriever",
        action="react_retrieval",
        input_summary=f"topic={topic[:100]}, kb={kb_collections}",
        output_summary="",
    )

    tool_router = await get_tool_router()
    langchain_tools = await tool_router.to_langchain_tools()
    tool_map = {tool.name: tool for tool in langchain_tools}

    task_lines = "\n".join(
        f"- {t.description if hasattr(t, 'description') else t.get('description', '')}"
        for t in task_plan
    ) if task_plan else topic

    kb_hint = (
        f"IMPORTANT: First, always search the knowledge bases ({', '.join(kb_collections)}) "
        f"using rag_retriever. Only use arxiv_search or other tools if the knowledge base "
        f"search returns no relevant results."
    ) if kb_collections else ""

    system_prompt = (
        "You are a research assistant with access to search and analysis tools.\n"
        f"Research topic: {topic}\n"
        f"Sub-tasks:\n{task_lines}\n\n"
        f"{kb_hint}\n"
        "Use available tools to find relevant papers and information. "
        "After searching, summarize the key documents you found."
    )

    messages: list = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Research topic: {topic}"),
    ]

    try:
        llm = get_llm(model=model, temperature=0.3)
        llm_with_tools = llm.bind_tools(langchain_tools)
    except Exception as exc:
        logger.error("ReAct retriever: LLM bind_tools failed: %s", exc)
        trace.error = str(exc)
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        traces.append(trace)
        return {"retrieved_docs": [], "agent_trace": traces}

    tool_results: list[tuple] = []  # (tool_name, result)
    called_tools: list[str] = []

    MAX_TURNS = 10
    try:
        for _ in range(MAX_TURNS):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            if not response.tool_calls:
                break

            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                tool = tool_map.get(tool_name)
                if tool is None:
                    logger.warning("ReAct: unknown tool %r, skipping", tool_name)
                    messages.append(HumanMessage(
                        content=f"Tool '{tool_name}' not found. Available: {list(tool_map.keys())}"
                    ))
                    continue
                try:
                    try:
                        result = await tool.ainvoke(tool_args)
                    except (TypeError, ValueError, AttributeError):
                        result = await tool.coroutine(**tool_args)
                except Exception as tool_exc:
                    logger.warning("ReAct: tool %r failed: %s", tool_name, tool_exc)
                    result = {"error": str(tool_exc)}

                if tool_name not in called_tools:
                    called_tools.append(tool_name)
                tool_results.append((tool_name, result))
                messages.append(ToolMessage(
                    content=str(result)[:3000],
                    name=tool_name,
                    tool_call_id=tool_call.get("id", ""),
                ))
    except Exception as exc:
        logger.error("ReAct retriever failed: %s", exc)
        trace.error = str(exc)
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        traces.append(trace)
        return {"retrieved_docs": [], "agent_trace": traces}

    docs = _extract_docs_from_results(tool_results)

    trace.output_summary = f"ReAct: {len(docs)} docs via tools"
    trace.tool_calls = called_tools
    trace.duration_ms = int((time.monotonic() - t0) * 1000)
    traces.append(trace)

    return {"retrieved_docs": docs, "agent_trace": traces}


async def retriever_node(state: ResearchState) -> dict:
    """Retriever agent — KB 优先检索 (本地知识库 → ArXiv 回退)。

    KB 优先策略：先搜索知识库，结果充足时跳过 ArXiv，节省时间。
    KB 结果不足（max_score < 0.5 或少于 3 条）时才回退到 ArXiv 搜索。

    ArXiv 请求串行化（间隔 >= 3s）以避免 HTTP 429 限流。
    use_react=True 时切换为 ReAct 模式，由 LLM 动态决定调用哪些工具。
    """
    if state.get("use_react"):
        react_result = await _retriever_react(state)
        if react_result.get("retrieved_docs"):
            return react_result

        fallback_state = dict(state)
        fallback_state["use_react"] = False
        fallback_state["agent_trace"] = react_result.get("agent_trace", state.get("agent_trace", []))
        if not fallback_state.get("search_queries"):
            fallback_state["search_queries"] = [state.get("research_topic", "")]

        fallback_result = await retriever_node(fallback_state)
        traces = fallback_result.get("agent_trace", [])
        if traces:
            traces[-1].action = "react_fallback_retrieval"
        return fallback_result

    t0 = time.monotonic()
    queries = state.get("search_queries", [])
    kb_collections = state.get("kb_collections", [])

    traces = list(state.get("agent_trace", []))
    trace = AgentTrace(
        agent_name="retriever",
        action="kb_first_retrieval",
        input_summary=f"queries={queries}, kb={kb_collections}",
        output_summary="",
    )

    if not queries:
        trace.error = "No search_queries in state"
        trace.duration_ms = int((time.monotonic() - t0) * 1000)
        traces.append(trace)
        return {"agent_trace": traces}

    all_docs: List[RetrievedDoc] = []
    seen_ids: set = set()
    called_tools: list[str] = []

    # KB 优先：先搜索本地知识库
    kb_docs: List[RetrievedDoc] = []
    if kb_collections:
        called_tools.append("rag_retriever")
        kb_results = await asyncio.gather(
            *[_search_kb(q, kb_collections, top_k=5) for q in queries[:3]],
            return_exceptions=True,
        )
        for result in kb_results:
            if isinstance(result, BaseException):
                logger.warning("KB search failed: %s", result)
                continue
            kb_docs.extend(result)

    # 判断 KB 结果是否充足
    if kb_docs:
        max_kb_score = max(d.relevance_score for d in kb_docs)
        kb_sufficient = max_kb_score >= 0.5 and len(kb_docs) >= 3
    else:
        kb_sufficient = False

    if kb_sufficient:
        logger.info("KB results sufficient (max_score=%.3f, count=%d), skipping ArXiv",
                    max(d.relevance_score for d in kb_docs), len(kb_docs))
        all_docs = kb_docs
    else:
        # KB 结果不足，回退到 ArXiv 搜索
        called_tools.append("arxiv_search")
        if not kb_docs:
            trace.output_summary = "KB returned no results, falling back to ArXiv"
        else:
            trace.output_summary = f"KB insufficient (max_score={max(d.relevance_score for d in kb_docs):.3f}, count={len(kb_docs)}), falling back to ArXiv"

        arxiv_docs: List[RetrievedDoc] = []
        for i, query in enumerate(queries[:5]):
            if i > 0:
                await asyncio.sleep(ARXIV_DELAY)
            docs = await _search_arxiv(query, max_results=5)
            arxiv_docs.extend(docs)
            logger.debug("ArXiv query %d/%d: %d results", i + 1, min(len(queries), 5), len(docs))

        # 合并 KB + ArXiv 结果
        for doc in kb_docs + arxiv_docs:
            key = f"{doc.source}:{doc.doc_id}"
            if key not in seen_ids:
                seen_ids.add(key)
                all_docs.append(doc)

    all_docs.sort(key=lambda d: d.relevance_score, reverse=True)

    trace.output_summary = f"{len(all_docs)} docs (arxiv={sum(1 for d in all_docs if d.source=='arxiv')}, kb={sum(1 for d in all_docs if d.source=='knowledge_base')})"
    trace.tool_calls = called_tools
    trace.duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info("Retriever: %d docs retrieved in %.1fs", len(all_docs), trace.duration_ms / 1000)
    traces.append(trace)

    return {
        "retrieved_docs": all_docs,
        "agent_trace": traces,
    }
