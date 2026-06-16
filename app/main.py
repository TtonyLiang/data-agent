import json
import logging
import uuid
from collections.abc import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import AgentState, build_mvp_graph
from app.config import get_settings
from app.db.mysql import get_management_db
from app.db.migrations import run_management_migrations
from app.logging_config import configure_file_logging
from app.services.datasource_service import get_datasource_service

configure_file_logging()

app = FastAPI(title="WenQu DataQuery Agent", version="0.1.0")

ANSWER_CHUNK_SIZE = 32
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_migrations():
    try:
        await run_management_migrations()
    except Exception:
        logger.exception("management database migration failed")
        raise

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

    await validate_datasource_access(agent_id, datasource_id)

    # 加载历史上下文
    history = await load_history(agent_id, session_id, limit=5)

    graph = get_graph()
    state: AgentState = {
        "question": question,
        "agent_id": agent_id,
        "session_id": session_id,
        "datasource_id": datasource_id,
        "chat_history": history,
    }

    result = await graph.ainvoke(state)

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
        execution_trace=result.get("execution_trace"),
    )

    return {
        "session_id": session_id,
        "intent": result.get("intent"),
        "sql": sql,
        "compiled_sql": sql,
        "logic_form": result.get("logic_form"),
        "answer": answer,
        "sql_result": sql_result,
    }


@app.post("/api/chat/stream")
async def chat_stream(request: dict):
    """SSE 流式对话接口 — 输出思考过程 + 节点进度."""
    question = request.get("question", "")
    agent_id = request.get("agent_id", 1)
    datasource_id = request.get("datasource_id")
    session_id = request.get("session_id", str(uuid.uuid4()))

    await validate_datasource_access(agent_id, datasource_id)

    history = await load_history(agent_id, session_id, limit=5)

    # 节点中文名映射
    NODE_LABELS = {
        "intent_recognition": "意图识别",
        "semantic_runtime_recall": "语义运行时",
        "nl2lf_generate": "LogicForm 生成",
        "lf_validate": "语义校验",
        "lf_to_sql_compile": "SQL 编译",
        "lf_repair": "LF 修复",
        "sql_execute": "SQL 执行",
    }

    async def event_generator():
        graph = get_graph()
        state: AgentState = {
            "question": question,
            "agent_id": agent_id,
            "session_id": session_id,
            "datasource_id": datasource_id,
            "chat_history": history,
        }

        final_result = {}
        current_node = ""
        reasoning_buffer = ""
        reasoning_trace: list[dict] = []

        try:
            async for event in graph.astream_events(state, version="v2"):
                kind = event.get("event", "")
                node = event.get("name", "")

                # 节点开始
                if kind == "on_chain_start" and node in NODE_LABELS:
                    current_node = node
                    ensure_trace_step(reasoning_trace, node, NODE_LABELS[node])
                    yield sse_event({
                        "event": "node_start",
                        "data": json.dumps({
                            "node": node,
                            "label": NODE_LABELS[node],
                        }, ensure_ascii=False),
                    })

                # LLM 流式 token (思考过程 + 内容)
                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        content = getattr(chunk, "content", "") or ""
                        reasoning = ""
                        if hasattr(chunk, "additional_kwargs"):
                            reasoning = chunk.additional_kwargs.get("reasoning_content", "")
                        if reasoning:
                            reasoning_buffer += reasoning
                            append_trace_reasoning(reasoning_trace, current_node, NODE_LABELS.get(current_node, ""), reasoning)
                            yield sse_event({
                                "event": "reasoning",
                                "data": json.dumps({
                                    "node": current_node,
                                    "label": NODE_LABELS.get(current_node, ""),
                                    "delta": reasoning,
                                }, ensure_ascii=False),
                            })
                        elif content:
                            yield sse_event({
                                "event": "token",
                                "data": json.dumps({
                                    "node": current_node,
                                    "delta": content,
                                }, ensure_ascii=False),
                            })

                # LLM 调用结束 — 检查 reasoning_content
                elif kind == "on_chat_model_end":
                    msg = event.get("data", {}).get("output")
                    if msg and hasattr(msg, "additional_kwargs"):
                        rc = msg.additional_kwargs.get("reasoning_content", "")
                        if rc and not reasoning_buffer:
                            append_trace_reasoning(reasoning_trace, current_node, NODE_LABELS.get(current_node, ""), rc)
                            yield sse_event({
                                "event": "reasoning",
                                "data": json.dumps({
                                    "node": current_node,
                                    "label": NODE_LABELS.get(current_node, ""),
                                    "delta": rc,
                                }, ensure_ascii=False),
                            })

                # 节点结束
                elif kind == "on_chain_end" and node in NODE_LABELS:
                    output = event.get("data", {}).get("output", {})
                    final_result.update(output)
                    # 提取节点关键输出
                    node_output = _extract_node_output(node, output)
                    complete_trace_step(reasoning_trace, node, NODE_LABELS[node], node_output)
                    yield sse_event({
                        "event": "node_complete",
                        "data": json.dumps({
                            "node": node,
                            "label": NODE_LABELS[node],
                            "output": node_output,
                        }, ensure_ascii=False),
                    })
                    reasoning_buffer = ""
        except Exception as exc:
            logger.exception("chat stream failed")
            yield sse_event({
                "event": "error",
                "data": json.dumps({
                    "session_id": session_id,
                    "node": current_node,
                    "label": NODE_LABELS.get(current_node, current_node),
                    "error_type": exc.__class__.__name__,
                    "detail": truncate_error_detail(str(exc) or exc.__class__.__name__),
                    "message": format_stream_error_message(
                        exc,
                        NODE_LABELS.get(current_node, current_node),
                    ),
                }, ensure_ascii=False),
            })
            return

        # 最终结果
        answer = final_result.get("final_answer", "")
        sql = final_result.get("compiled_sql") or final_result.get("sql_text", "")
        sql_result = final_result.get("sql_result", [])

        yield sse_event({
            "event": "answer_start",
            "data": json.dumps({
                "session_id": session_id,
            }, ensure_ascii=False),
        })
        for delta in chunk_text(answer):
            yield sse_event({
                "event": "answer_delta",
                "data": json.dumps({
                    "session_id": session_id,
                    "delta": delta,
                }, ensure_ascii=False),
            })
        yield sse_event({
            "event": "answer_complete",
            "data": json.dumps({
                "session_id": session_id,
                "answer": answer,
            }, ensure_ascii=False),
        })

        await save_turn(
            agent_id,
            session_id,
            question,
            answer,
            sql,
            sql_result,
            logic_form=final_result.get("logic_form"),
            compiled_sql=sql,
            execution_trace=final_result.get("execution_trace"),
            reasoning_trace=reasoning_trace,
        )

        yield sse_event({
            "event": "result",
            "data": json.dumps({
                "session_id": session_id,
                "intent": final_result.get("intent", ""),
                "sql": sql,
                "compiled_sql": sql,
                "logic_form": final_result.get("logic_form"),
                "answer": answer,
                "sql_result": sql_result,
                "reasoning_trace": reasoning_trace,
            }, ensure_ascii=False),
        })
        yield sse_event({"event": "done", "data": "{}"})

    return EventSourceResponse(event_generator())


def sse_event(event: dict) -> dict:
    log_sse_event(event)
    return event


def log_sse_event(event: dict) -> None:
    event_name = event.get("event", "")
    data = event.get("data", "{}")
    try:
        payload = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError:
        payload = data
    logger.info("SSE event=%s data=%s", event_name, json.dumps(
        compact_stream_log_payload(payload),
        ensure_ascii=False,
    ))


def compact_stream_log_payload(payload):
    if not isinstance(payload, dict):
        return payload
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
    return compacted


def format_stream_error_message(exc: Exception, label: str = "") -> str:
    prefix = f"{label}节点失败" if label else "后端处理失败"
    detail = str(exc) or exc.__class__.__name__
    lowered = detail.lower()
    error_type = exc.__class__.__name__

    if "missing credentials" in lowered or "api_key" in lowered:
        reason = "大模型配置缺少 API Key；本地 OpenAI-compatible/Ollama 服务会自动使用占位 Key，请确认模型配置的 Base URL 和模型名正确。"
    elif "unauthorized" in lowered or "401" in lowered:
        reason = "大模型鉴权失败，请检查模型配置里的 API Key 是否启用且填写正确。"
    elif "connection" in lowered or "connect" in lowered or "timed out" in lowered or "timeout" in lowered:
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
        "output": None,
        "summary": "",
    }
    trace.append(step)
    return step


def append_trace_reasoning(trace: list[dict], node: str, label: str, delta: str) -> None:
    if not node:
        return
    step = ensure_trace_step(trace, node, label or node)
    step["reasoning"] = f"{step.get('reasoning', '')}{delta}"


def complete_trace_step(trace: list[dict], node: str, label: str, output: dict) -> None:
    step = ensure_trace_step(trace, node, label)
    step["status"] = "done"
    step["output"] = output
    step["summary"] = summarize_trace_step(node, output)


def summarize_trace_step(node: str, output: dict) -> str:
    if node == "intent_recognition":
        return f"→ {output.get('intent', '')}"
    if node == "semantic_runtime_recall":
        domain = output.get("domain") or ""
        count = output.get("count", 0)
        return f"{domain} · 召回 {count} 条语义资产" if domain else f"召回 {count} 条语义资产"
    if node == "nl2lf_generate":
        logic_form = output.get("logic_form") or {}
        metrics = logic_form.get("metrics", []) if isinstance(logic_form, dict) else []
        return f"指标: {', '.join(metrics)}" if metrics else "已生成 LogicForm"
    if node == "lf_validate":
        return "校验通过" if output.get("valid") else "校验未通过"
    if node == "lf_to_sql_compile":
        return "已编译 SQL" if output.get("compiled_sql") else ""
    if node == "sql_execute":
        error = output.get("error")
        return f"错误: {error}" if error else f"{output.get('row_count', 0)} 条结果"
    return ""


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
        yield text[start:start + chunk_size]


def _extract_node_output(node: str, output: dict) -> dict:
    """提取每个节点的关键输出用于前端展示."""
    if node == "intent_recognition":
        return {"intent": output.get("intent", "")}
    elif node == "semantic_runtime_recall":
        evidence = output.get("runtime_evidence", [])
        runtime = output.get("semantic_runtime") or {}
        domain = runtime.get("domain", {}) if isinstance(runtime, dict) else {}
        return {
            "domain": domain.get("name", ""),
            "count": len(evidence),
            "items": [
                e.get("metadata", {}).get("asset_key", e.get("source_type", ""))
                for e in evidence[:5]
            ],
            "error": output.get("semantic_error"),
        }
    elif node == "nl2lf_generate":
        return {"logic_form": output.get("logic_form")}
    elif node == "lf_validate":
        validation = output.get("lf_validation") or {}
        return {
            "valid": validation.get("valid", False),
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []),
        }
    elif node == "lf_to_sql_compile":
        return {"compiled_sql": output.get("compiled_sql", "")}
    elif node == "lf_repair":
        return {"execution_trace": output.get("execution_trace", {})}
    elif node == "sql_execute":
        result = output.get("sql_result", [])
        error = output.get("sql_error")
        return {"row_count": len(result), "error": error}
    return {}


@app.get("/api/chat/sessions/{agent_id}")
async def list_sessions(agent_id: int):
    """获取会话列表."""
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT session_id, MIN(created_at) AS created_at, COUNT(*) AS turn_count, "
        "SUBSTRING_INDEX(GROUP_CONCAT(CASE WHEN role='user' THEN content END ORDER BY id), ',', 1) AS last_question "
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
        "SELECT role, content, reasoning_trace, logic_form, compiled_sql, sql_text, sql_result, created_at "
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
    reasoning_trace: list[dict] | None = None,
):
    """保存一轮对话到 chat_history."""
    db = get_management_db()
    # 保存用户消息
    await db.execute_query(
        "INSERT INTO chat_history (agent_id, session_id, role, content) "
        "VALUES (:aid, :sid, 'user', :content)",
        {"aid": agent_id, "sid": session_id, "content": question},
    )
    # 保存助手消息
    await db.execute_query(
        "INSERT INTO chat_history "
        "(agent_id, session_id, role, content, reasoning_trace, logic_form, compiled_sql, execution_trace, sql_text, sql_result) "
        "VALUES (:aid, :sid, 'assistant', :content, :reasoning_trace, :logic_form, :compiled_sql, :trace, :sql, :result)",
        {
            "aid": agent_id, "sid": session_id,
            "content": answer,
            "reasoning_trace": json.dumps(reasoning_trace, ensure_ascii=False) if reasoning_trace else None,
            "logic_form": json.dumps(logic_form, ensure_ascii=False) if logic_form else None,
            "compiled_sql": compiled_sql or sql or None,
            "trace": json.dumps(execution_trace, ensure_ascii=False) if execution_trace else None,
            "sql": sql or compiled_sql or None,
            "result": json.dumps(sql_result, ensure_ascii=False) if sql_result else None,
        },
    )


# 注册子路由
from app.api.agent import router as agent_router
from app.api.datasource import router as ds_router
from app.api.model_config import router as model_config_router
from app.api.semantic import router as semantic_router

app.include_router(agent_router, prefix="/api/agent", tags=["智能体"])
app.include_router(ds_router, prefix="/api/datasource", tags=["数据源"])
app.include_router(model_config_router, prefix="/api/model-config", tags=["模型配置"])
app.include_router(semantic_router, prefix="/api/semantic", tags=["语义运行时"])


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=settings.debug)
