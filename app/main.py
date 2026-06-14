import json
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import AgentState, build_mvp_graph
from app.config import get_settings
from app.db.mysql import get_management_db

app = FastAPI(title="WenQu DataQuery Agent", version="0.1.0")

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
    sql = result.get("sql_text", "")
    sql_result = result.get("sql_result", [])
    await save_turn(agent_id, session_id, question, answer, sql, sql_result)

    return {
        "session_id": session_id,
        "intent": result.get("intent"),
        "sql": sql,
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

    history = await load_history(agent_id, session_id, limit=5)

    # 节点中文名映射
    NODE_LABELS = {
        "intent_recognition": "意图识别",
        "evidence_recall": "知识召回",
        "query_enhance": "查询增强",
        "schema_recall": "Schema 匹配",
        "sql_generate": "SQL 生成",
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

        async for event in graph.astream_events(state, version="v2"):
            kind = event.get("event", "")
            node = event.get("name", "")

            # 节点开始
            if kind == "on_chain_start" and node in NODE_LABELS:
                current_node = node
                yield {
                    "event": "node_start",
                    "data": json.dumps({
                        "node": node,
                        "label": NODE_LABELS[node],
                    }, ensure_ascii=False),
                }

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
                        yield {
                            "event": "reasoning",
                            "data": json.dumps({
                                "node": current_node,
                                "label": NODE_LABELS.get(current_node, ""),
                                "delta": reasoning,
                            }, ensure_ascii=False),
                        }
                    elif content:
                        yield {
                            "event": "token",
                            "data": json.dumps({
                                "node": current_node,
                                "delta": content,
                            }, ensure_ascii=False),
                        }

            # LLM 调用结束 — 检查 reasoning_content
            elif kind == "on_chat_model_end":
                msg = event.get("data", {}).get("output")
                if msg and hasattr(msg, "additional_kwargs"):
                    rc = msg.additional_kwargs.get("reasoning_content", "")
                    if rc and not reasoning_buffer:
                        yield {
                            "event": "reasoning",
                            "data": json.dumps({
                                "node": current_node,
                                "label": NODE_LABELS.get(current_node, ""),
                                "delta": rc,
                            }, ensure_ascii=False),
                        }

            # 节点结束
            elif kind == "on_chain_end" and node in NODE_LABELS:
                output = event.get("data", {}).get("output", {})
                if node == "sql_execute":
                    final_result = output
                # 提取节点关键输出
                node_output = _extract_node_output(node, output)
                yield {
                    "event": "node_complete",
                    "data": json.dumps({
                        "node": node,
                        "label": NODE_LABELS[node],
                        "output": node_output,
                    }, ensure_ascii=False),
                }
                reasoning_buffer = ""

        # 最终结果
        answer = final_result.get("final_answer", "")
        sql = final_result.get("sql_text", "")
        sql_result = final_result.get("sql_result", [])
        await save_turn(agent_id, session_id, question, answer, sql, sql_result)

        yield {
            "event": "result",
            "data": json.dumps({
                "session_id": session_id,
                "intent": final_result.get("intent", ""),
                "sql": sql,
                "answer": answer,
                "sql_result": sql_result,
            }, ensure_ascii=False),
        }
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())


def _extract_node_output(node: str, output: dict) -> dict:
    """提取每个节点的关键输出用于前端展示."""
    if node == "intent_recognition":
        return {"intent": output.get("intent", "")}
    elif node == "evidence_recall":
        evidence = output.get("evidence", [])
        return {"count": len(evidence), "items": [e.get("metadata", {}).get("title", "") for e in evidence[:5]]}
    elif node == "query_enhance":
        return {"enhanced_query": output.get("enhanced_query", "")}
    elif node == "schema_recall":
        tables = output.get("relevant_tables", [])
        return {"tables": [t.get("table_name", "") for t in tables]}
    elif node == "sql_generate":
        return {"sql": output.get("sql_text", "")}
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
        "SELECT role, content, sql_text, sql_result, created_at "
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
        "SELECT role, content, sql_text, sql_result "
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
        if row.get("sql_text"):
            entry["sql"] = row["sql_text"]
        history.append(entry)
    return history


async def save_turn(
    agent_id: int,
    session_id: str,
    question: str,
    answer: str,
    sql: str | None = None,
    sql_result: list | None = None,
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
        "INSERT INTO chat_history (agent_id, session_id, role, content, sql_text, sql_result) "
        "VALUES (:aid, :sid, 'assistant', :content, :sql, :result)",
        {
            "aid": agent_id, "sid": session_id,
            "content": answer, "sql": sql or None,
            "result": json.dumps(sql_result, ensure_ascii=False) if sql_result else None,
        },
    )


# 注册子路由
from app.api.agent import router as agent_router
from app.api.datasource import router as ds_router
from app.api.knowledge import router as kb_router

app.include_router(agent_router, prefix="/api/agent", tags=["智能体"])
app.include_router(ds_router, prefix="/api/datasource", tags=["数据源"])
app.include_router(kb_router, prefix="/api/knowledge", tags=["知识库"])


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=settings.debug)
