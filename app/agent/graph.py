from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class AgentState(TypedDict, total=False):
    # 输入
    question: str
    agent_id: int
    session_id: str
    datasource_id: int

    # 意图识别
    intent: str  # "data_query" | "chat" | "metadata_query"
    need_analysis: bool

    # 知识召回 (Phase 2)
    evidence: list[dict[str, Any]]
    enhanced_query: str

    # 多轮对话历史
    chat_history: list[dict[str, Any]]

    # Schema 召回
    relevant_tables: list[dict[str, Any]]
    relevant_columns: list[dict[str, Any]]
    semantic_models: list[dict[str, Any]]
    likely_joins: list[dict[str, Any]]

    # 计划 (Phase 3)
    plan: dict[str, Any]

    # SQL 生成与执行
    sql_text: str
    sql_result: list[dict[str, Any]]
    sql_error: str | None
    sql_retry_count: int

    # Python 分析 (Phase 3)
    python_code: str
    python_result: str

    # 报告 (Phase 3)
    report: str

    # 输出
    final_answer: str
    stream_chunks: list[str]


MAX_SQL_RETRIES = 2


def build_mvp_graph() -> StateGraph:
    """构建 LangGraph 工作流.

    流程: Intent → EvidenceRecall → QueryEnhance → SchemaRecall → SQLGenerate → SQLExecute → End
    SQL 执行失败时自动重试 (最多2次).
    """
    from app.agent.nodes.evidence import evidence_recall_node
    from app.agent.nodes.intent import intent_recognition_node
    from app.agent.nodes.query_enhance import query_enhance_node
    from app.agent.nodes.schema_recall import schema_recall_node
    from app.agent.nodes.sql_execute import sql_execute_node
    from app.agent.nodes.sql_generate import sql_generate_node

    graph = StateGraph(AgentState)

    graph.add_node("intent_recognition", intent_recognition_node)
    graph.add_node("evidence_recall", evidence_recall_node)
    graph.add_node("query_enhance", query_enhance_node)
    graph.add_node("schema_recall", schema_recall_node)
    graph.add_node("sql_generate", sql_generate_node)
    graph.add_node("sql_execute", sql_execute_node)

    graph.add_edge(START, "intent_recognition")
    graph.add_conditional_edges(
        "intent_recognition",
        route_after_intent,
        {
            "data_query": "evidence_recall",
            "chat": END,
            "metadata_query": END,
        },
    )
    graph.add_edge("evidence_recall", "query_enhance")
    graph.add_edge("query_enhance", "schema_recall")
    graph.add_edge("schema_recall", "sql_generate")
    graph.add_edge("sql_generate", "sql_execute")
    graph.add_conditional_edges(
        "sql_execute",
        route_after_sql_execute,
        {
            "success": END,
            "retry": "sql_generate",
        },
    )

    return graph


def route_after_intent(state: AgentState) -> str:
    intent = state.get("intent", "chat")
    if intent == "data_query":
        return "data_query"
    return intent


def route_after_sql_execute(state: AgentState) -> str:
    if state.get("sql_result"):
        return "success"
    if state.get("sql_error") and state.get("sql_retry_count", 0) < MAX_SQL_RETRIES:
        return "retry"
    return "success"
