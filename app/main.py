import asyncio
import json
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager, suppress
from copy import deepcopy
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import AgentState, build_mvp_graph
from app.agent.nodes.analysis_pipeline import (
    planner_node,
    python_analyze_node,
    python_generate_node,
    report_generator_node,
)
from app.agent.nodes.sql_execute import sql_execute_node
from app.config import get_settings
from app.db.migrations import run_management_migrations
from app.db.mysql import get_management_db
from app.logging_config import configure_file_logging
from app.services.datasource_service import get_datasource_service

configure_file_logging()

ANSWER_CHUNK_SIZE = 32
STREAM_PROGRESS_INTERVAL_SECONDS = 0.5
MIN_NODE_DISPLAY_SECONDS = 1.0
logger = logging.getLogger(__name__)
CUSTOM_STREAM_NODES = {
    "semantic_enhance",
    "nl2lf_generate",
    "nl2sql_fallback",
    "python_generate",
    "python_analyze",
    "report_generator",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup database migrations through FastAPI's lifespan hook."""
    try:
        await run_management_migrations()
    except Exception:
        logger.exception("management database migration failed")
        raise
    yield


app = FastAPI(title="WenQu DataQuery Agent", version="0.1.0", lifespan=lifespan)


def new_trace_id() -> str:
    return f"trc_{uuid.uuid4().hex[:12]}"


def merge_execution_trace(
    trace: dict | None, trace_id: str, started_at: float | None = None
) -> dict:
    merged = dict(trace or {})
    merged["trace_id"] = trace_id
    if started_at is not None:
        merged["total_duration_ms"] = round((time.monotonic() - started_at) * 1000, 2)
    return merged


def classify_error(exc: Exception, node: str = "") -> dict[str, str]:
    detail = str(exc).lower()
    error_type = exc.__class__.__name__.lower()
    if "permission" in detail or "forbidden" in detail or isinstance(exc, HTTPException):
        category = "permission"
        severity = "warning"
    elif "sql" in node or "sql" in detail:
        category = "sql"
        severity = "error"
    elif "timeout" in detail or "timed out" in detail or "timeout" in error_type:
        category = "timeout"
        severity = "warning"
    elif "api_key" in detail or "unauthorized" in detail or "model" in detail or "llm" in detail:
        category = "llm"
        severity = "error"
    else:
        category = "runtime"
        severity = "error"
    return {"category": category, "severity": severity}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 编译 LangGraph
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_mvp_graph().compile()
    return _graph


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: dict):
    """同步对话接口."""
    question = request.get("question", "")
    agent_id = request.get("agent_id", 1)
    datasource_id = request.get("datasource_id")
    session_id = request.get("session_id", str(uuid.uuid4()))
    trace_id = request.get("trace_id") or new_trace_id()
    require_sql_confirmation = bool(request.get("require_sql_confirmation"))
    enable_low_confidence_clarification = bool(request.get("enable_low_confidence_clarification"))
    started_at = time.monotonic()

    await validate_datasource_access(agent_id, datasource_id)

    # 加载历史上下文
    history = await load_history(agent_id, session_id, limit=5)

    graph = get_graph()
    state: AgentState = {
        "question": question,
        "agent_id": agent_id,
        "session_id": session_id,
        "datasource_id": datasource_id,
        "trace_id": trace_id,
        "require_sql_confirmation": require_sql_confirmation,
        "enable_low_confidence_clarification": enable_low_confidence_clarification,
        "chat_history": history,
    }

    logger.info(
        "chat request started trace_id=%s session_id=%s agent_id=%s datasource_id=%s",
        trace_id,
        session_id,
        agent_id,
        datasource_id,
    )
    result = await graph.ainvoke(state)
    execution_trace = merge_execution_trace(result.get("execution_trace"), trace_id, started_at)

    # 保存本轮对话
    answer = result.get("final_answer", "")
    sql = result.get("compiled_sql") or result.get("sql_text", "")
    sql_result = result.get("sql_result", [])
    await save_turn(
        agent_id,
        session_id,
        question,
        answer,
        sql,
        sql_result,
        logic_form=result.get("logic_form"),
        compiled_sql=sql,
        execution_trace=execution_trace,
        plan_payload=result.get("plan"),
        semantic_check=result.get("semantic_check"),
        python_result=result.get("python_result"),
        report_payload=result.get("report_payload"),
    )

    return {
        "session_id": session_id,
        "trace_id": trace_id,
        "intent": result.get("intent"),
        "sql": sql,
        "compiled_sql": sql,
        "logic_form": result.get("logic_form"),
        "answer": answer,
        "sql_result": sql_result,
        "plan": result.get("plan"),
        "semantic_check": result.get("semantic_check"),
        "python_result": result.get("python_result"),
        "report_payload": result.get("report_payload"),
        "human_confirmation": result.get("human_confirmation"),
        "clarification": result.get("clarification"),
        "execution_trace": execution_trace,
    }


@app.post("/api/chat/stream")
async def chat_stream(request: dict):
    """SSE 流式对话接口 — 输出思考过程 + 节点进度."""
    question = request.get("question", "")
    agent_id = request.get("agent_id", 1)
    datasource_id = request.get("datasource_id")
    session_id = request.get("session_id", str(uuid.uuid4()))
    trace_id = request.get("trace_id") or new_trace_id()
    require_sql_confirmation = bool(request.get("require_sql_confirmation"))
    enable_low_confidence_clarification = bool(request.get("enable_low_confidence_clarification"))

    await validate_datasource_access(agent_id, datasource_id)

    history = await load_history(agent_id, session_id, limit=5)

    # 节点中文名映射
    NODE_LABELS = {
        "intent_recognition": "意图识别",
        "semantic_enhance": "语义增强",
        "semantic_runtime_recall": "知识召回",
        "schema_recall": "数据定位",
        "clarification": "低置信度追问",
        "nl2lf_generate": "LogicForm 生成",
        "lf_validate": "语义校验",
        "lf_to_sql_compile": "SQL 编译",
        "nl2sql_fallback": "NL2SQL 兜底",
        "semantic_check": "语义一致性检查",
        "sql_confirmation": "执行确认",
        "lf_repair": "LF 修复",
        "sql_execute": "SQL 执行",
        "planner": "分析计划",
        "python_generate": "Python 生成",
        "python_analyze": "Python 分析",
        "report_generator": "报告生成",
    }

    async def event_generator():
        stream_started_at = time.monotonic()
        graph = get_graph()
        state: AgentState = {
            "question": question,
            "agent_id": agent_id,
            "session_id": session_id,
            "datasource_id": datasource_id,
            "trace_id": trace_id,
            "require_sql_confirmation": require_sql_confirmation,
            "enable_low_confidence_clarification": enable_low_confidence_clarification,
            "chat_history": history,
        }

        final_result = {}
        current_node = ""
        reasoning_buffer = ""
        node_token_buffers: dict[str, str] = {}
        progress_counters: dict[str, int] = {}
        custom_stream_seen: dict[str, bool] = {}
        pending_model_tokens: dict[str, str] = {}
        node_started_at: dict[str, float] = {}
        reasoning_trace: list[dict] = []

        def emit(event: dict) -> dict:
            return sse_event(event, trace_id=trace_id)

        try:
            logger.info(
                "chat stream started trace_id=%s session_id=%s agent_id=%s datasource_id=%s",
                trace_id,
                session_id,
                agent_id,
                datasource_id,
            )
            event_queue: asyncio.Queue[dict] = asyncio.Queue()
            producer_task = asyncio.create_task(pump_graph_events(graph, state, event_queue))

            try:
                while True:
                    try:
                        queued = await asyncio.wait_for(
                            event_queue.get(),
                            timeout=STREAM_PROGRESS_INTERVAL_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        if current_node:
                            index = progress_counters.get(current_node, 0)
                            progress_counters[current_node] = index + 1
                            progress = node_progress_message(current_node, index)
                            step = ensure_trace_step(
                                reasoning_trace,
                                current_node,
                                NODE_LABELS.get(current_node, current_node),
                            )
                            append_trace_event(step, progress)
                            yield emit(
                                {
                                    "event": "node_progress",
                                    "data": json.dumps(
                                        {
                                            "node": current_node,
                                            "label": NODE_LABELS.get(current_node, current_node),
                                            "message": progress,
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            )
                        continue

                    if queued.get("kind") == "done":
                        break
                    if queued.get("kind") == "error":
                        raise queued["error"]

                    event = queued.get("event", {})
                    kind = event.get("event", "")
                    node = event.get("name", "")

                    # 节点开始
                    if kind == "on_chain_start" and node in NODE_LABELS:
                        current_node = node
                        node_started_at[node] = time.monotonic()
                        step = ensure_trace_step(reasoning_trace, node, NODE_LABELS[node])
                        append_trace_event(step, f"开始{NODE_LABELS[node]}。")
                        yield emit(
                            {
                                "event": "node_start",
                                "data": json.dumps(
                                    {
                                        "node": node,
                                        "label": NODE_LABELS[node],
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        )

                    # LLM 流式 token (思考过程 + 内容)
                    elif kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk:
                            content = getattr(chunk, "content", "") or ""
                            content = str(content)
                            if current_node and content:
                                if current_node in CUSTOM_STREAM_NODES:
                                    pending_model_tokens[current_node] = (
                                        pending_model_tokens.get(current_node, "") + content
                                    )
                                else:
                                    node_token_buffers[current_node] = (
                                        node_token_buffers.get(current_node, "") + content
                                    )
                                    append_trace_stream_text(
                                        reasoning_trace,
                                        current_node,
                                        NODE_LABELS.get(current_node, ""),
                                        content,
                                    )
                                    yield emit(
                                        {
                                            "event": "token",
                                            "data": json.dumps(
                                                {
                                                    "node": current_node,
                                                    "delta": content,
                                                },
                                                ensure_ascii=False,
                                            ),
                                        }
                                    )

                    elif kind == "on_custom_event" and node == "wenqu_token":
                        payload = event.get("data", {}) or {}
                        token_node = str(payload.get("node") or current_node or "")
                        content = str(payload.get("delta") or "")
                        event_kind = str(payload.get("kind") or "token")
                        if token_node and content:
                            custom_stream_seen[token_node] = True
                            pending_model_tokens.pop(token_node, None)
                            if event_kind == "reasoning":
                                reasoning_buffer += content
                                append_trace_reasoning(
                                    reasoning_trace,
                                    token_node,
                                    NODE_LABELS.get(token_node, token_node),
                                    content,
                                )
                                yield emit(
                                    {
                                        "event": "reasoning",
                                        "data": json.dumps(
                                            {
                                                "node": token_node,
                                                "label": NODE_LABELS.get(token_node, token_node),
                                                "delta": content,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    }
                                )
                            else:
                                node_token_buffers[token_node] = (
                                    node_token_buffers.get(token_node, "") + content
                                )
                                append_trace_stream_text(
                                    reasoning_trace,
                                    token_node,
                                    NODE_LABELS.get(token_node, token_node),
                                    content,
                                )
                                yield emit(
                                    {
                                        "event": "token",
                                        "data": json.dumps(
                                            {
                                                "node": token_node,
                                                "label": NODE_LABELS.get(token_node, token_node),
                                                "delta": content,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    }
                                )

                    # LLM 调用结束 — 检查 reasoning_content
                    elif kind == "on_chat_model_end":
                        if current_node in CUSTOM_STREAM_NODES:
                            continue
                        msg = event.get("data", {}).get("output")
                        if msg and hasattr(msg, "additional_kwargs"):
                            rc = msg.additional_kwargs.get("reasoning_content", "")
                            if rc and not reasoning_buffer:
                                append_trace_reasoning(
                                    reasoning_trace,
                                    current_node,
                                    NODE_LABELS.get(current_node, ""),
                                    rc,
                                )
                                yield emit(
                                    {
                                        "event": "reasoning",
                                        "data": json.dumps(
                                            {
                                                "node": current_node,
                                                "label": NODE_LABELS.get(current_node, ""),
                                                "delta": rc,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    }
                                )

                    # 节点结束
                    elif kind == "on_chain_end" and node in NODE_LABELS:
                        async for pending_event in hold_node_for_display(
                            node=node,
                            node_labels=NODE_LABELS,
                            node_started_at=node_started_at,
                            progress_counters=progress_counters,
                            reasoning_trace=reasoning_trace,
                            trace_id=trace_id,
                        ):
                            yield pending_event
                        if node in CUSTOM_STREAM_NODES and not custom_stream_seen.get(node):
                            pending = pending_model_tokens.pop(node, "")
                            if pending:
                                node_token_buffers[node] = (
                                    node_token_buffers.get(node, "") + pending
                                )
                                append_trace_stream_text(
                                    reasoning_trace,
                                    node,
                                    NODE_LABELS[node],
                                    pending,
                                )
                                yield emit(
                                    {
                                        "event": "token",
                                        "data": json.dumps(
                                            {
                                                "node": node,
                                                "delta": pending,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    }
                                )
                        output = event.get("data", {}).get("output", {})
                        final_result.update(output)
                        # 提取节点关键输出
                        node_output = _extract_node_output(node, output)
                        complete_trace_step(reasoning_trace, node, NODE_LABELS[node], node_output)
                        yield emit(
                            {
                                "event": "node_complete",
                                "data": json.dumps(
                                    {
                                        "node": node,
                                        "label": NODE_LABELS[node],
                                        "output": node_output,
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        )
                        current_node = ""
                        reasoning_buffer = ""
                        pending_model_tokens.pop(node, None)
                        node_started_at.pop(node, None)
            finally:
                if not producer_task.done():
                    producer_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await producer_task
        except Exception as exc:
            logger.exception("chat stream failed")
            error_info = classify_error(exc, current_node)
            yield emit(
                {
                    "event": "error",
                    "data": json.dumps(
                        {
                            "session_id": session_id,
                            "node": current_node,
                            "label": NODE_LABELS.get(current_node, current_node),
                            "error_type": exc.__class__.__name__,
                            "error_category": error_info["category"],
                            "severity": error_info["severity"],
                            "detail": truncate_error_detail(str(exc) or exc.__class__.__name__),
                            "message": format_stream_error_message(
                                exc,
                                NODE_LABELS.get(current_node, current_node),
                            ),
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            return

        # 最终结果
        answer = final_result.get("final_answer", "")
        sql = final_result.get("compiled_sql") or final_result.get("sql_text", "")
        sql_result = final_result.get("sql_result", [])
        execution_trace = merge_execution_trace(
            final_result.get("execution_trace"), trace_id, stream_started_at
        )
        final_result["execution_trace"] = execution_trace

        yield emit(
            {
                "event": "answer_start",
                "data": json.dumps(
                    {
                        "session_id": session_id,
                    },
                    ensure_ascii=False,
                ),
            }
        )
        for delta in chunk_text(answer):
            yield emit(
                {
                    "event": "answer_delta",
                    "data": json.dumps(
                        {
                            "session_id": session_id,
                            "delta": delta,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        yield emit(
            {
                "event": "answer_complete",
                "data": json.dumps(
                    {
                        "session_id": session_id,
                        "answer": answer,
                    },
                    ensure_ascii=False,
                ),
            }
        )

        try:
            await save_turn(
                agent_id,
                session_id,
                question,
                answer,
                sql,
                sql_result,
                logic_form=final_result.get("logic_form"),
                compiled_sql=sql,
                execution_trace=execution_trace,
                plan_payload=final_result.get("plan"),
                semantic_check=final_result.get("semantic_check"),
                python_result=final_result.get("python_result"),
                report_payload=final_result.get("report_payload"),
                reasoning_trace=reasoning_trace,
            )
        except Exception:
            logger.exception("chat stream failed to persist history")

        yield emit(
            {
                "event": "result",
                "data": json.dumps(
                    {
                        "session_id": session_id,
                        "intent": final_result.get("intent", ""),
                        "sql": sql,
                        "compiled_sql": sql,
                        "logic_form": final_result.get("logic_form"),
                        "answer": answer,
                        "sql_result": sql_result,
                        "plan": final_result.get("plan"),
                        "semantic_check": final_result.get("semantic_check"),
                        "python_result": final_result.get("python_result"),
                        "report_payload": final_result.get("report_payload"),
                        "human_confirmation": final_result.get("human_confirmation"),
                        "clarification": final_result.get("clarification"),
                        "execution_trace": execution_trace,
                        "reasoning_trace": reasoning_trace,
                    },
                    ensure_ascii=False,
                ),
            }
        )
        yield emit({"event": "done", "data": "{}"})

    return EventSourceResponse(event_generator())


@app.post("/api/chat/confirm-sql")
async def confirm_sql_execution(request: dict):
    """Execute a previously generated SQL after explicit human confirmation."""
    agent_id = request.get("agent_id", 1)
    datasource_id = request.get("datasource_id")
    session_id = request.get("session_id", str(uuid.uuid4()))
    trace_id = request.get("trace_id") or new_trace_id()
    question = request.get("question") or "确认执行 SQL"
    sql = request.get("sql") or request.get("compiled_sql") or ""
    started_at = time.monotonic()

    if not sql:
        raise HTTPException(status_code=400, detail="缺少待确认执行的 SQL")

    await validate_datasource_access(agent_id, datasource_id)

    state: AgentState = {
        "question": question,
        "enhanced_question": request.get("enhanced_question", ""),
        "agent_id": agent_id,
        "session_id": session_id,
        "datasource_id": datasource_id,
        "trace_id": trace_id,
        "compiled_sql": sql,
        "sql_text": sql,
        "logic_form": request.get("logic_form") or {},
        "semantic_runtime": request.get("semantic_runtime") or {},
        "execution_trace": {
            "trace_id": trace_id,
            "human_confirmation": {
                "required": True,
                "status": "confirmed",
                "sql": sql,
            },
        },
    }

    state.update(await sql_execute_node(state))
    if not state.get("sql_error"):
        state.update(await planner_node(state))
        state.update(await python_generate_node(state))
        state.update(await python_analyze_node(state))
        state.update(await report_generator_node(state))

    answer = state.get("final_answer", "")
    safe_sql = state.get("compiled_sql") or state.get("sql_text") or sql
    sql_result = state.get("sql_result", [])
    execution_trace = merge_execution_trace(state.get("execution_trace"), trace_id, started_at)
    state["execution_trace"] = execution_trace

    try:
        await save_turn(
            agent_id,
            session_id,
            question,
            answer,
            safe_sql,
            sql_result,
            logic_form=state.get("logic_form"),
            compiled_sql=safe_sql,
            execution_trace=execution_trace,
            plan_payload=state.get("plan"),
            semantic_check=state.get("semantic_check"),
            python_result=state.get("python_result"),
            report_payload=state.get("report_payload"),
        )
    except Exception:
        logger.exception("confirm-sql failed to persist history")

    return {
        "session_id": session_id,
        "trace_id": trace_id,
        "intent": "data_query",
        "sql": safe_sql,
        "compiled_sql": safe_sql,
        "logic_form": state.get("logic_form"),
        "answer": answer,
        "sql_result": sql_result,
        "plan": state.get("plan"),
        "semantic_check": state.get("semantic_check"),
        "python_result": state.get("python_result"),
        "report_payload": state.get("report_payload"),
        "human_confirmation": {
            "required": True,
            "status": "confirmed",
            "sql": safe_sql,
        },
        "execution_trace": execution_trace,
    }


async def pump_graph_events(graph, state: AgentState, event_queue: asyncio.Queue[dict]) -> None:
    try:
        async for event in graph.astream_events(state, version="v2"):
            await event_queue.put({"kind": "event", "event": event})
    except Exception as exc:
        await event_queue.put({"kind": "error", "error": exc})
    finally:
        await event_queue.put({"kind": "done"})


def sse_event(event: dict, trace_id: str | None = None) -> dict:
    if trace_id:
        event = attach_trace_id(event, trace_id)
    log_sse_event(event)
    return event


def attach_trace_id(event: dict, trace_id: str) -> dict:
    data = event.get("data", "{}")
    try:
        payload = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict):
        payload.setdefault("trace_id", trace_id)
        return {
            **event,
            "data": json.dumps(payload, ensure_ascii=False),
        }
    return event


async def hold_node_for_display(
    *,
    node: str,
    node_labels: dict[str, str],
    node_started_at: dict[str, float],
    progress_counters: dict[str, int],
    reasoning_trace: list[dict],
    trace_id: str | None = None,
):
    if MIN_NODE_DISPLAY_SECONDS <= 0:
        return
    started_at = node_started_at.get(node)
    if started_at is None:
        started_at = time.monotonic()
        node_started_at[node] = started_at
    remaining = MIN_NODE_DISPLAY_SECONDS - (time.monotonic() - started_at)
    if remaining <= 0:
        return

    index = progress_counters.get(node, 0)
    progress_counters[node] = index + 1
    progress = node_progress_message(node, index)
    step = ensure_trace_step(
        reasoning_trace,
        node,
        node_labels.get(node, node),
    )
    append_trace_event(step, progress)
    yield sse_event(
        {
            "event": "node_progress",
            "data": json.dumps(
                {
                    "node": node,
                    "label": node_labels.get(node, node),
                    "message": progress,
                },
                ensure_ascii=False,
            ),
        },
        trace_id=trace_id,
    )
    await asyncio.sleep(remaining)


def log_sse_event(event: dict) -> None:
    event_name = event.get("event", "")
    data = event.get("data", "{}")
    try:
        payload = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError:
        payload = data
    logger.info(
        "SSE event=%s data=%s",
        event_name,
        json.dumps(
            compact_stream_log_payload(payload),
            ensure_ascii=False,
        ),
    )


def compact_stream_log_payload(payload):
    if not isinstance(payload, dict):
        return payload
    settings = get_settings()
    compacted = dict(payload)
    sql_result = compacted.get("sql_result")
    if isinstance(sql_result, list):
        compacted["sql_result"] = {"row_count": len(sql_result)}
    logic_form = compacted.get("logic_form")
    if isinstance(logic_form, dict):
        compacted["logic_form"] = {
            "metrics": logic_form.get("metrics", []),
            "dimensions": logic_form.get("dimensions", []),
            "filters": len(logic_form.get("filters", [])),
        }
    report_payload = compacted.get("report_payload")
    if isinstance(report_payload, dict):
        compacted["report_payload"] = {
            "title": report_payload.get("title"),
            "row_count": report_payload.get("row_count"),
            "status": report_payload.get("status"),
        }
    return truncate_log_values(compacted, settings.max_sse_log_value_chars)


def truncate_log_values(value, limit: int):
    if isinstance(value, dict):
        return {key: truncate_log_values(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [truncate_log_values(item, limit) for item in value[:20]]
    if isinstance(value, str) and limit > 0 and len(value) > limit:
        return f"{value[:limit]}... [truncated {len(value) - limit} chars]"
    return value


def format_stream_error_message(exc: Exception, label: str = "") -> str:
    prefix = f"{label}节点失败" if label else "后端处理失败"
    detail = str(exc) or exc.__class__.__name__
    lowered = detail.lower()
    error_type = exc.__class__.__name__

    if "missing credentials" in lowered or "api_key" in lowered:
        reason = (
            "大模型配置缺少 API Key；本地 OpenAI-compatible/Ollama 服务会自动使用占位 Key，"
            "请确认模型配置的 Base URL 和模型名正确。"
        )
    elif "unauthorized" in lowered or "401" in lowered:
        reason = "大模型鉴权失败，请检查模型配置里的 API Key 是否启用且填写正确。"
    elif (
        "connection" in lowered
        or "connect" in lowered
        or "timed out" in lowered
        or "timeout" in lowered
    ):
        reason = "大模型服务连接失败，请确认模型服务已启动，Base URL 可访问。"
    else:
        reason = truncate_error_detail(detail)

    return f"{prefix}：{reason}（{error_type}）"


def truncate_error_detail(detail: str, limit: int = 260) -> str:
    text = " ".join(str(detail).split())
    return text if len(text) <= limit else f"{text[:limit]}..."


def ensure_trace_step(trace: list[dict], node: str, label: str) -> dict:
    for step in trace:
        if step.get("node") == node:
            return step
    step = {
        "node": node,
        "label": label,
        "status": "running",
        "reasoning": "",
        "streamText": "",
        "events": [],
        "output": None,
        "summary": "",
    }
    trace.append(step)
    return step


def append_trace_reasoning(trace: list[dict], node: str, label: str, delta: str) -> None:
    if not node:
        return
    step = ensure_trace_step(trace, node, label or node)
    limit = get_settings().max_reasoning_trace_chars
    step["reasoning"] = append_limited_text(step.get("reasoning", ""), delta, limit)


def append_trace_stream_text(trace: list[dict], node: str, label: str, delta: str) -> None:
    if not node:
        return
    step = ensure_trace_step(trace, node, label or node)
    limit = get_settings().max_stream_text_trace_chars
    step["streamText"] = append_limited_text(step.get("streamText", ""), delta, limit)


def append_limited_text(current: str, delta: str, limit: int) -> str:
    text = f"{current or ''}{delta or ''}"
    if limit <= 0 or len(text) <= limit:
        return text
    suffix = f"\n...[已截断，保留最近 {limit} 字符]"
    keep = max(0, limit - len(suffix))
    return f"{text[-keep:]}{suffix}" if keep else suffix


def append_trace_event(step: dict, message: str) -> None:
    text = message.strip()
    if not text:
        return
    events = step.setdefault("events", [])
    if not events or events[-1] != text:
        events.append(text)


def complete_trace_step(trace: list[dict], node: str, label: str, output: dict) -> None:
    step = ensure_trace_step(trace, node, label)
    step["status"] = "done"
    step["output"] = output
    step["summary"] = summarize_trace_step(node, output)
    if step["summary"]:
        append_trace_event(step, f"完成：{step['summary']}。")


def summarize_trace_step(node: str, output: dict) -> str:
    if node == "intent_recognition":
        return f"→ {output.get('intent', '')}"
    if node == "semantic_enhance":
        enhance = output.get("semantic_enhancement") or {}
        original = str(enhance.get("original_question") or "")
        enhanced = str(enhance.get("enhanced_question") or "")
        if enhanced and enhanced != original:
            return f"已改写问题：{enhanced}"
        return "问题已整理"
    if node == "semantic_runtime_recall":
        domain = output.get("domain") or ""
        count = output.get("count", 0)
        return f"{domain} · 召回 {count} 条语义资产" if domain else f"召回 {count} 条语义资产"
    if node == "schema_recall":
        scope = output.get("schema_scope") or {}
        tables = len(output.get("matched_tables") or output.get("relevant_tables") or [])
        columns = len(output.get("matched_columns") or output.get("relevant_columns") or [])
        if scope.get("fallback_used"):
            return f"使用已采集表结构兜底 · {tables} 张表 {columns} 个字段"
        return f"定位 {tables} 张候选表 · {columns} 个候选字段"
    if node == "clarification":
        clarification = output.get("clarification") or output
        return str(clarification.get("message") or "需要补充问题信息")
    if node == "nl2lf_generate":
        logic_form = output.get("logic_form") or {}
        metrics = logic_form.get("metrics", []) if isinstance(logic_form, dict) else []
        return f"指标: {', '.join(metrics)}" if metrics else "已生成 LogicForm"
    if node == "lf_validate":
        return "校验通过" if output.get("valid") else "校验未通过"
    if node == "lf_to_sql_compile":
        if output.get("compiled_sql"):
            return "已编译 SQL"
        if output.get("sql_error"):
            return f"编译失败: {output.get('sql_error')}"
        return ""
    if node == "nl2sql_fallback":
        if output.get("compiled_sql"):
            return "已生成兜底 SQL"
        if output.get("sql_error"):
            return f"兜底失败: {output.get('sql_error')}"
        return ""
    if node == "semantic_check":
        check = output.get("semantic_check") or output
        return "一致性通过" if check.get("valid") else "一致性未通过"
    if node == "sql_confirmation":
        confirmation = output.get("human_confirmation") or {}
        return str(confirmation.get("message") or "等待用户确认执行 SQL")
    if node == "sql_execute":
        error = output.get("error")
        return f"错误: {error}" if error else f"{output.get('row_count', 0)} 条结果"
    if node == "planner":
        plan = output.get("plan") or {}
        mode_label = plan.get("mode_label") or "本地分析计划"
        return f"{mode_label} · {len(plan.get('analysis_steps') or [])} 个步骤"
    if node == "python_generate":
        result = output.get("python_result") or {}
        scope = result.get("analysis_scope") or "SQL 结果集分析"
        return (
            f"已生成基础统计脚本 · {scope}"
            if output.get("python_code") or output.get("code_length")
            else ""
        )
    if node == "python_analyze":
        result = output.get("python_result") or {}
        if result.get("status") == "success":
            return "基础统计完成 · " + "、".join(result.get("computed_items") or [])
        return str(result.get("status") or "")
    if node == "report_generator":
        report = output.get("report_payload") or {}
        mode_label = report.get("mode_label") or "结构化报告"
        return f"{mode_label} · {report.get('title', '已生成报告')}"
    return ""


def node_progress_message(node: str, index: int = 0) -> str:
    messages = {
        "intent_recognition": ["正在识别问题意图...", "正在判断是否进入问数链路..."],
        "semantic_enhance": ["正在补全省略的指标、维度和 TopN 口径..."],
        "semantic_runtime_recall": [
            "正在检索知识库、匹配语义资产...",
            "正在整理可用指标、维度和规则...",
        ],
        "schema_recall": [
            "正在定位相关数据表、字段和关联关系...",
            "正在根据业务口径缩小候选 schema...",
        ],
        "clarification": ["正在判断是否需要补充查询条件..."],
        "nl2lf_generate": [
            "正在调用大模型生成 LogicForm...",
            "正在把自然语言映射为指标、维度和过滤条件...",
            "正在等待模型流式返回结构化 JSON...",
        ],
        "lf_validate": ["正在校验指标、维度、过滤和时间口径...", "正在确认语义资产能否编译执行..."],
        "lf_to_sql_compile": [
            "正在把 LogicForm 编译成受控 SQL...",
            "正在解析表字段映射和关联路径...",
        ],
        "nl2sql_fallback": [
            "语义层未命中，正在调用大模型生成兜底 SQL...",
            "正在使用数据定位候选表约束 SQL 生成...",
        ],
        "semantic_check": [
            "正在执行 SQL 前语义一致性检查...",
            "正在检查指标、维度和 SQL 是否一致...",
        ],
        "sql_confirmation": ["正在等待用户确认是否执行 SQL..."],
        "lf_repair": ["正在根据错误尝试修复 LogicForm...", "正在调整失败的指标或维度槽位..."],
        "sql_execute": ["正在执行 SQL 查询并等待数据库返回...", "数据库仍在处理查询结果..."],
        "planner": ["正在生成后续分析计划...", "正在规划统计、解读和报告结构..."],
        "python_generate": ["正在生成结果分析代码...", "正在准备只处理 SQL 结果集的统计脚本..."],
        "python_analyze": [
            "正在执行统计分析并整理结果...",
            "正在计算分布、极值、空值和维度样例...",
        ],
        "report_generator": [
            "正在生成最终结构化报告...",
            "正在写入执行摘要、过程、解读和建议...",
            "正在组装图表和结果明细...",
        ],
    }
    options = messages.get(node) or ["当前步骤仍在处理中..."]
    return options[index % len(options)]


async def validate_datasource_access(agent_id: int, datasource_id: int | None):
    if not datasource_id:
        return
    if not await get_datasource_service().belongs_to_agent(datasource_id, agent_id):
        raise HTTPException(status_code=403, detail="数据源不属于当前智能体")


def chunk_text(text: str, chunk_size: int = ANSWER_CHUNK_SIZE) -> Iterator[str]:
    """Split final answer text into stable UI streaming chunks."""
    if not text:
        return
    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]


def _extract_node_output(node: str, output: dict) -> dict:
    """提取每个节点的关键输出用于前端展示."""
    if node == "intent_recognition":
        return {"intent": output.get("intent", "")}
    elif node == "semantic_enhance":
        enhance = output.get("semantic_enhancement") or {}
        return {
            "original_question": enhance.get("original_question", ""),
            "enhanced_question": enhance.get("enhanced_question", ""),
            "rewrite_type": enhance.get("rewrite_type", ""),
            "preserved_constraints": enhance.get("preserved_constraints", []),
            "reason": enhance.get("reason", ""),
        }
    elif node == "semantic_runtime_recall":
        evidence = output.get("runtime_evidence", [])
        runtime = output.get("semantic_runtime") or {}
        domain = runtime.get("domain", {}) if isinstance(runtime, dict) else {}
        metrics = runtime.get("metrics", []) if isinstance(runtime, dict) else []
        mappings = runtime.get("mappings", []) if isinstance(runtime, dict) else []
        return {
            "domain": domain.get("name", ""),
            "count": len(evidence),
            "runtime_counts": {
                "metrics": len(metrics),
                "dimensions": len(
                    [
                        item
                        for item in mappings
                        if item.get("role") in {"dimension", "filter", "time"}
                    ]
                ),
                "rules": len(runtime.get("rules", [])) if isinstance(runtime, dict) else 0,
                "templates": len(runtime.get("templates", [])) if isinstance(runtime, dict) else 0,
            },
            "matched_assets": [
                {
                    "key": e.get("metadata", {}).get("asset_key", e.get("source_type", "")),
                    "type": e.get("source_type", ""),
                    "score": e.get("score"),
                    "content": e.get("content", ""),
                }
                for e in evidence[:8]
            ],
            "available_metrics": [
                {
                    "key": item.get("metric_key"),
                    "name": item.get("name"),
                    "dimensions": item.get("dimensions", []),
                }
                for item in metrics[:12]
            ],
            "items": [
                e.get("metadata", {}).get("asset_key", e.get("source_type", ""))
                for e in evidence[:5]
            ],
            "error": output.get("semantic_error"),
        }
    elif node == "schema_recall":
        tables = output.get("relevant_tables", [])
        columns = output.get("relevant_columns", [])
        joins = output.get("likely_joins", [])
        scope = output.get("schema_scope", {})
        return {
            "matched_tables": tables[:8],
            "matched_columns": columns[:20],
            "likely_joins": joins[:10],
            "schema_scope": scope,
            "fallback_used": scope.get("fallback_used", False),
        }
    elif node == "clarification":
        clarification = output.get("clarification") or {}
        return {
            "required": clarification.get("required", True),
            "reason": clarification.get("reason", ""),
            "question": clarification.get("question", ""),
            "message": clarification.get("message", output.get("final_answer", "")),
        }
    elif node == "nl2lf_generate":
        logic_form = output.get("logic_form") or {}
        return {
            "logic_form": logic_form,
            "metrics": logic_form.get("metrics", []) if isinstance(logic_form, dict) else [],
            "dimensions": logic_form.get("dimensions", []) if isinstance(logic_form, dict) else [],
            "filters": logic_form.get("filters", []) if isinstance(logic_form, dict) else [],
            "sort": logic_form.get("sort", []) if isinstance(logic_form, dict) else [],
            "limit": logic_form.get("limit") if isinstance(logic_form, dict) else None,
        }
    elif node == "lf_validate":
        validation = output.get("lf_validation") or {}
        return {
            "valid": validation.get("valid", False),
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []),
            "used_assets": validation.get("used_assets", []),
        }
    elif node == "lf_to_sql_compile":
        trace = output.get("execution_trace") or {}
        return {
            "compiled_sql": output.get("compiled_sql", ""),
            "error": output.get("sql_error"),
            "strategy": trace.get("compile_strategy"),
            "used_assets": trace.get("used_assets", []),
            "warnings": trace.get("warnings", []),
        }
    elif node == "nl2sql_fallback":
        return {
            "compiled_sql": output.get("compiled_sql", ""),
            "error": output.get("sql_error"),
            "strategy": (output.get("execution_trace") or {}).get("compile_strategy"),
            "reason": (output.get("execution_trace") or {}).get("fallback_reason"),
        }
    elif node == "semantic_check":
        check = output.get("semantic_check") or {}
        return {
            "valid": check.get("valid", False),
            "errors": check.get("errors", []),
            "warnings": check.get("warnings", []),
            "checked_items": check.get("checked_items", {}),
        }
    elif node == "sql_confirmation":
        confirmation = output.get("human_confirmation") or {}
        return {
            "required": confirmation.get("required", True),
            "status": confirmation.get("status", "pending"),
            "message": confirmation.get("message", "SQL 已生成，等待用户确认后执行。"),
            "sql": confirmation.get("sql", output.get("compiled_sql", "")),
        }
    elif node == "lf_repair":
        return {"execution_trace": output.get("execution_trace", {})}
    elif node == "sql_execute":
        result = output.get("sql_result", [])
        error = output.get("sql_error")
        trace = output.get("execution_trace") or {}
        sql_execution = trace.get("sql_execution") or {}
        sample = result[:3] if isinstance(result, list) else []
        columns = list(sample[0].keys()) if sample else []
        return {
            "row_count": len(result),
            "error": error,
            "columns": columns,
            "sample_rows": sample,
            "duration_ms": sql_execution.get("duration_ms"),
            "slow_query": sql_execution.get("slow_query", False),
        }
    elif node == "planner":
        plan = output.get("plan", {})
        return {
            "plan": plan,
            "mode": plan.get("mode"),
            "mode_label": plan.get("mode_label"),
            "row_count": plan.get("row_count"),
            "column_count": plan.get("column_count"),
            "numeric_columns": plan.get("numeric_columns", []),
            "dimension_columns": plan.get("dimension_columns", []),
            "limitations": plan.get("limitations", []),
        }
    elif node == "python_generate":
        py_result = output.get("python_result", {})
        return {
            "python_code": output.get("python_code", ""),
            "code_length": len(output.get("python_code") or ""),
            "python_result": py_result,
            "analysis_scope": py_result.get("analysis_scope"),
            "generated_tasks": py_result.get("generated_tasks", []),
            "numeric_columns": py_result.get("numeric_columns", []),
            "dimension_columns": py_result.get("dimension_columns", []),
        }
    elif node == "python_analyze":
        py_result = output.get("python_result", {})
        return {
            "python_result": py_result,
            "status": py_result.get("status"),
            "computed_items": py_result.get("computed_items", []),
            "metrics": py_result.get("metrics", []),
            "dimensions": py_result.get("dimensions", []),
            "null_counts": py_result.get("null_counts", {}),
        }
    elif node == "report_generator":
        report = output.get("report_payload") or {}
        return {
            "title": report.get("title", ""),
            "mode": report.get("mode"),
            "mode_label": report.get("mode_label"),
            "summary": report.get("summary", ""),
            "row_count": report.get("row_count", 0),
            "executive_summary": report.get("executive_summary", {}),
            "analysis_process": report.get("analysis_process", {}),
            "interpretation": report.get("interpretation", {}),
            "suggestions": report.get("suggestions", {}),
            "charts": report.get("charts", []),
            "tables": report.get("tables", []),
            "sections": report.get("sections", []),
            "limitations": report.get("limitations", []),
        }
    return {}


@app.get("/api/chat/sessions/{agent_id}")
async def list_sessions(agent_id: int):
    """获取会话列表."""
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT session_id, MIN(created_at) AS created_at, COUNT(*) AS turn_count, "
        "SUBSTRING_INDEX("
        "GROUP_CONCAT(CASE WHEN role='user' THEN content END ORDER BY id), ',', 1"
        ") AS last_question "
        "FROM chat_history WHERE agent_id = :aid "
        "GROUP BY session_id ORDER BY MAX(id) DESC LIMIT 50",
        {"aid": agent_id},
    )
    return {"sessions": rows}


@app.get("/api/chat/history/{agent_id}/{session_id}")
async def get_history(agent_id: int, session_id: str):
    """获取某个会话的完整历史."""
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT role, content, reasoning_trace, logic_form, compiled_sql, sql_text, sql_result, "
        "plan_payload, semantic_check, python_result, report_payload, created_at "
        "FROM chat_history WHERE agent_id = :aid AND session_id = :sid ORDER BY id",
        {"aid": agent_id, "sid": session_id},
    )
    # 解析 sql_result JSON
    for row in rows:
        if row.get("sql_result"):
            try:
                row["sql_result"] = json.loads(row["sql_result"])
            except (json.JSONDecodeError, TypeError):
                row["sql_result"] = []
        if row.get("logic_form"):
            if isinstance(row["logic_form"], str):
                try:
                    row["logic_form"] = json.loads(row["logic_form"])
                except json.JSONDecodeError:
                    row["logic_form"] = None
        if row.get("reasoning_trace"):
            if isinstance(row["reasoning_trace"], str):
                try:
                    row["reasoning_trace"] = json.loads(row["reasoning_trace"])
                except json.JSONDecodeError:
                    row["reasoning_trace"] = []
        for field in ("plan_payload", "semantic_check", "python_result", "report_payload"):
            if row.get(field) and isinstance(row[field], str):
                try:
                    row[field] = json.loads(row[field])
                except json.JSONDecodeError:
                    row[field] = None
        if row.get("compiled_sql"):
            row["sql_text"] = row["compiled_sql"]
    return {"history": rows}


@app.delete("/api/chat/sessions/{agent_id}/{session_id}")
async def delete_session(agent_id: int, session_id: str):
    """删除某个会话."""
    db = get_management_db()
    await db.execute_query(
        "DELETE FROM chat_history WHERE agent_id = :aid AND session_id = :sid",
        {"aid": agent_id, "sid": session_id},
    )
    return {"message": "会话已删除"}


async def load_history(agent_id: int, session_id: str, limit: int = 5) -> list[dict]:
    """加载最近 N 轮对话历史."""
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT role, content, logic_form, compiled_sql, sql_text, sql_result "
        "FROM chat_history WHERE agent_id = :aid AND session_id = :sid "
        "ORDER BY id DESC LIMIT :limit",
        {"aid": agent_id, "sid": session_id, "limit": limit * 2},
    )
    if not rows:
        return []
    rows.reverse()
    history = []
    for row in rows:
        entry = {"role": row["role"], "content": row["content"]}
        sql = row.get("compiled_sql") or row.get("sql_text")
        if sql:
            entry["sql"] = sql
        if row.get("logic_form"):
            entry["logic_form"] = row["logic_form"]
        history.append(entry)
    return history


async def save_turn(
    agent_id: int,
    session_id: str,
    question: str,
    answer: str,
    sql: str | None = None,
    sql_result: list | None = None,
    logic_form: dict | None = None,
    compiled_sql: str | None = None,
    execution_trace: dict | None = None,
    plan_payload: dict | None = None,
    semantic_check: dict | None = None,
    python_result: dict | None = None,
    report_payload: dict | None = None,
    reasoning_trace: list[dict] | None = None,
):
    """保存一轮对话到 chat_history."""
    db = get_management_db()
    try:
        await db.execute_query(
            "INSERT INTO chat_history (agent_id, session_id, role, content) "
            "VALUES (:aid, :sid, 'user', :content)",
            {"aid": agent_id, "sid": session_id, "content": question},
        )
    except Exception:
        logger.exception("failed to persist user chat history")

    assistant_params = build_assistant_history_params(
        agent_id=agent_id,
        session_id=session_id,
        answer=answer,
        sql=sql,
        sql_result=sql_result,
        logic_form=logic_form,
        compiled_sql=compiled_sql,
        execution_trace=execution_trace,
        plan_payload=plan_payload,
        semantic_check=semantic_check,
        python_result=python_result,
        report_payload=report_payload,
        reasoning_trace=reasoning_trace,
    )

    try:
        await insert_assistant_turn(db, assistant_params)
    except Exception:
        logger.exception(
            "failed to persist full assistant chat history, retry with compact payload"
        )
        try:
            await insert_assistant_turn(db, compact_assistant_history_params(assistant_params))
        except Exception:
            logger.exception("failed to persist compact assistant chat history")


def build_assistant_history_params(
    *,
    agent_id: int,
    session_id: str,
    answer: str,
    sql: str | None,
    sql_result: list | None,
    logic_form: dict | None,
    compiled_sql: str | None,
    execution_trace: dict | None,
    plan_payload: dict | None,
    semantic_check: dict | None,
    python_result: dict | None,
    report_payload: dict | None,
    reasoning_trace: list[dict] | None,
) -> dict[str, Any]:
    return {
        "aid": agent_id,
        "sid": session_id,
        "content": answer,
        "reasoning_trace": json.dumps(reasoning_trace, ensure_ascii=False)
        if reasoning_trace
        else None,
        "logic_form": json.dumps(logic_form, ensure_ascii=False) if logic_form else None,
        "compiled_sql": compiled_sql or sql or None,
        "trace": json.dumps(execution_trace, ensure_ascii=False) if execution_trace else None,
        "sql": sql or compiled_sql or None,
        "result": json.dumps(sql_result, ensure_ascii=False) if sql_result else None,
        "plan_payload": json.dumps(plan_payload, ensure_ascii=False) if plan_payload else None,
        "semantic_check": json.dumps(semantic_check, ensure_ascii=False)
        if semantic_check
        else None,
        "python_result": json.dumps(python_result, ensure_ascii=False) if python_result else None,
        "report_payload": json.dumps(report_payload, ensure_ascii=False)
        if report_payload
        else None,
    }


async def insert_assistant_turn(db, params: dict[str, Any]) -> None:
    await db.execute_query(
        "INSERT INTO chat_history "
        "(agent_id, session_id, role, content, reasoning_trace, logic_form, "
        "compiled_sql, execution_trace, "
        "sql_text, sql_result, plan_payload, semantic_check, python_result, report_payload) "
        "VALUES (:aid, :sid, 'assistant', :content, :reasoning_trace, "
        ":logic_form, :compiled_sql, :trace, "
        ":sql, :result, :plan_payload, :semantic_check, :python_result, :report_payload)",
        params,
    )


def compact_assistant_history_params(params: dict[str, Any]) -> dict[str, Any]:
    compacted = dict(params)
    compacted["result"] = compact_json_text(compacted.get("result"), max_chars=120000)
    compacted["reasoning_trace"] = compact_json_text(
        compacted.get("reasoning_trace"), max_chars=120000
    )
    compacted["trace"] = compact_json_text(compacted.get("trace"), max_chars=60000)
    compacted["plan_payload"] = compact_json_text(compacted.get("plan_payload"), max_chars=60000)
    compacted["semantic_check"] = compact_json_text(
        compacted.get("semantic_check"), max_chars=60000
    )
    compacted["python_result"] = compact_json_text(compacted.get("python_result"), max_chars=60000)
    compacted["report_payload"] = compact_report_payload_text(
        compacted.get("report_payload"), max_chars=120000
    )
    return compacted


def compact_json_text(value: Any, max_chars: int) -> Any:
    if not isinstance(value, str) or max_chars <= 0 or len(value) <= max_chars:
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return f"{value[:max_chars]}... [truncated {len(value) - max_chars} chars]"
    compacted = compact_history_value(parsed)
    compacted_text = json.dumps(compacted, ensure_ascii=False)
    if len(compacted_text) <= max_chars:
        return compacted_text
    return f"{compacted_text[:max_chars]}... [truncated {len(compacted_text) - max_chars} chars]"


def compact_report_payload_text(value: Any, max_chars: int) -> Any:
    if not isinstance(value, str) or max_chars <= 0 or len(value) <= max_chars:
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return compact_json_text(value, max_chars)
    compacted = deepcopy(parsed) if isinstance(parsed, dict) else parsed
    if isinstance(compacted, dict):
        markdown = compacted.get("markdown")
        if isinstance(markdown, str) and len(markdown) > 12000:
            compacted["markdown"] = (
                f"{markdown[:12000]}... [truncated {len(markdown) - 12000} chars]"
            )
            compacted["body"] = compacted["markdown"]
    compacted_text = json.dumps(compacted, ensure_ascii=False)
    if len(compacted_text) <= max_chars:
        return compacted_text
    return compact_json_text(compacted_text, max_chars)


def compact_history_value(value: Any) -> Any:
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            limit = 120 if len(value) > 120 else len(value)
            compacted_rows = value[:limit]
            if len(value) > limit:
                return {
                    "row_count": len(value),
                    "truncated": True,
                    "preview_rows": compacted_rows,
                }
            return compacted_rows
        return value[:50]
    if isinstance(value, dict):
        compacted = dict(value)
        for key in ("sql_result", "rows", "preview_rows"):
            inner = compacted.get(key)
            if isinstance(inner, list) and inner and all(isinstance(item, dict) for item in inner):
                limit = 120 if len(inner) > 120 else len(inner)
                compacted[key] = inner[:limit]
                if len(inner) > limit:
                    compacted[f"{key}_row_count"] = len(inner)
                    compacted[f"{key}_truncated"] = True
        return compacted
    return value


# 注册子路由
from app.api.agent import router as agent_router  # noqa: E402
from app.api.datasource import router as ds_router  # noqa: E402
from app.api.feedback import router as feedback_router  # noqa: E402
from app.api.model_config import router as model_config_router  # noqa: E402
from app.api.prompt import router as prompt_router  # noqa: E402
from app.api.semantic import router as semantic_router  # noqa: E402

app.include_router(agent_router, prefix="/api/agent", tags=["智能体"])
app.include_router(ds_router, prefix="/api/datasource", tags=["数据源"])
app.include_router(feedback_router, prefix="/api/feedback", tags=["反馈"])
app.include_router(model_config_router, prefix="/api/model-config", tags=["模型配置"])
app.include_router(prompt_router, prefix="/api/prompt", tags=["Prompt配置"])
app.include_router(semantic_router, prefix="/api/semantic", tags=["知识召回"])


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app", host=settings.app_host, port=settings.app_port, reload=settings.debug
    )
