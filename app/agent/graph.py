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

    # 语义运行时 / LogicForm
    runtime_evidence: list[dict[str, Any]]
    semantic_runtime: dict[str, Any]
    semantic_error: str | None
    logic_form: dict[str, Any]
    lf_validation: dict[str, Any]
    compiled_query: dict[str, Any]
    compiled_sql: str
    execution_trace: dict[str, Any]

    # 多轮对话历史
    chat_history: list[dict[str, Any]]

    # 旧 Schema 召回字段保留给历史序列化兼容，不再由新图写入
    relevant_tables: list[dict[str, Any]]
    relevant_columns: list[dict[str, Any]]
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

    流程: Intent → SemanticRuntimeRecall → NL2LF → LFValidate → LFToSQL → SQLExecute → End
    SQL 执行失败时自动重试 (最多2次).
    """
    from app.agent.nodes.intent import intent_recognition_node
    from app.agent.nodes.lf_repair import lf_repair_node
    from app.agent.nodes.lf_to_sql_compile import lf_to_sql_compile_node
    from app.agent.nodes.lf_validate import lf_validate_node
    from app.agent.nodes.nl2lf_generate import nl2lf_generate_node
    from app.agent.nodes.semantic_runtime_recall import semantic_runtime_recall_node
    from app.agent.nodes.sql_execute import sql_execute_node

    graph = StateGraph(AgentState)

    graph.add_node("intent_recognition", intent_recognition_node)
    graph.add_node("semantic_runtime_recall", semantic_runtime_recall_node)
    graph.add_node("nl2lf_generate", nl2lf_generate_node)
    graph.add_node("lf_validate", lf_validate_node)
    graph.add_node("lf_to_sql_compile", lf_to_sql_compile_node)
    graph.add_node("lf_repair", lf_repair_node)
    graph.add_node("sql_execute", sql_execute_node)

    graph.add_edge(START, "intent_recognition")
    graph.add_conditional_edges(
        "intent_recognition",
        route_after_intent,
        {
            "data_query": "semantic_runtime_recall",
            "chat": END,
            "metadata_query": END,
        },
    )
    graph.add_edge("semantic_runtime_recall", "nl2lf_generate")
    graph.add_edge("nl2lf_generate", "lf_validate")
    graph.add_conditional_edges(
        "lf_validate",
        route_after_lf_validate,
        {
            "valid": "lf_to_sql_compile",
            "invalid": END,
        },
    )
    graph.add_edge("lf_to_sql_compile", "sql_execute")
    graph.add_conditional_edges(
        "sql_execute",
        route_after_sql_execute,
        {
            "success": END,
            "retry": "lf_repair",
        },
    )
    graph.add_edge("lf_repair", "lf_validate")

    return graph


def route_after_intent(state: AgentState) -> str:
    intent = state.get("intent", "chat")
    if intent == "data_query":
        return "data_query"
    return intent


def route_after_lf_validate(state: AgentState) -> str:
    validation = state.get("lf_validation") or {}
    return "valid" if validation.get("valid") else "invalid"


def route_after_sql_execute(state: AgentState) -> str:
    if state.get("sql_result"):
        return "success"
    if state.get("sql_error") and state.get("sql_retry_count", 0) < MAX_SQL_RETRIES:
        return "retry"
    return "success"
