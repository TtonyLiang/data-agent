from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class AgentState(TypedDict, total=False):
    # 输入
    question: str
    agent_id: int
    session_id: str
    datasource_id: int
    trace_id: str

    # 意图识别
    intent: str  # "data_query" | "chat" | "metadata_query"
    need_analysis: bool

    # 语义增强
    enhanced_question: str
    semantic_enhancement: dict[str, Any]

    # 语义运行时 / LogicForm
    runtime_evidence: list[dict[str, Any]]
    semantic_runtime: dict[str, Any]
    semantic_error: str | None
    schema_scope: dict[str, Any]
    logic_form: dict[str, Any]
    lf_validation: dict[str, Any]
    compiled_query: dict[str, Any]
    compiled_sql: str
    execution_trace: dict[str, Any]
    nl2sql_fallback_error: str | None

    # 多轮对话历史
    chat_history: list[dict[str, Any]]

    # 旧 Schema 召回字段保留给历史序列化兼容，不再由新图写入
    relevant_tables: list[dict[str, Any]]
    relevant_columns: list[dict[str, Any]]
    likely_joins: list[dict[str, Any]]

    # 计划 (Phase 3)
    plan: dict[str, Any]
    semantic_check: dict[str, Any]

    # SQL 生成与执行
    sql_text: str
    sql_result: list[dict[str, Any]]
    sql_error: str | None
    sql_retry_count: int
    require_sql_confirmation: bool
    enable_low_confidence_clarification: bool
    human_confirmation: dict[str, Any]
    clarification: dict[str, Any]

    # Python 分析 (Phase 3)
    python_code: str
    python_result: dict[str, Any]

    # 报告 (Phase 3)
    report: str
    report_payload: dict[str, Any]

    # 输出
    final_answer: str
    stream_chunks: list[str]


MAX_SQL_RETRIES = 2


def build_mvp_graph() -> StateGraph:
    """构建 LangGraph 工作流.

    流程: Intent → SemanticEnhance → SemanticRuntimeRecall → NL2LF → LFValidate → LFToSQL
    → SemanticCheck → SQLExecute → Planner → PythonGenerate → PythonAnalyze
    → ReportGenerator → End
    SQL 执行失败时自动重试 (最多2次).
    """
    from app.agent.nodes.analysis_pipeline import (
        planner_node,
        python_analyze_node,
        python_generate_node,
        report_generator_node,
        semantic_check_node,
    )
    from app.agent.nodes.clarification import clarification_node
    from app.agent.nodes.human_confirm import sql_confirmation_node
    from app.agent.nodes.intent import intent_recognition_node
    from app.agent.nodes.lf_repair import lf_repair_node
    from app.agent.nodes.lf_to_sql_compile import lf_to_sql_compile_node
    from app.agent.nodes.lf_validate import lf_validate_node
    from app.agent.nodes.nl2lf_generate import nl2lf_generate_node
    from app.agent.nodes.nl2sql_fallback import nl2sql_fallback_node
    from app.agent.nodes.schema_recall import schema_recall_node
    from app.agent.nodes.semantic_enhance import semantic_enhance_node
    from app.agent.nodes.semantic_runtime_recall import semantic_runtime_recall_node
    from app.agent.nodes.sql_execute import sql_execute_node

    graph = StateGraph(AgentState)

    graph.add_node("intent_recognition", intent_recognition_node)
    graph.add_node("semantic_enhance", semantic_enhance_node)
    graph.add_node("semantic_runtime_recall", semantic_runtime_recall_node)
    graph.add_node("schema_recall", schema_recall_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("nl2lf_generate", nl2lf_generate_node)
    graph.add_node("lf_validate", lf_validate_node)
    graph.add_node("lf_to_sql_compile", lf_to_sql_compile_node)
    graph.add_node("nl2sql_fallback", nl2sql_fallback_node)
    graph.add_node("semantic_check", semantic_check_node)
    graph.add_node("sql_confirmation", sql_confirmation_node)
    graph.add_node("lf_repair", lf_repair_node)
    graph.add_node("sql_execute", sql_execute_node)
    graph.add_node("planner", planner_node)
    graph.add_node("python_generate", python_generate_node)
    graph.add_node("python_analyze", python_analyze_node)
    graph.add_node("report_generator", report_generator_node)

    graph.add_edge(START, "intent_recognition")
    graph.add_conditional_edges(
        "intent_recognition",
        route_after_intent,
        {
            "data_query": "semantic_enhance",
            "chat": END,
            "metadata_query": END,
        },
    )
    graph.add_edge("semantic_enhance", "semantic_runtime_recall")
    graph.add_edge("semantic_runtime_recall", "schema_recall")
    graph.add_conditional_edges(
        "schema_recall",
        route_after_schema_recall,
        {
            "continue": "nl2lf_generate",
            "clarify": "clarification",
        },
    )
    graph.add_edge("clarification", END)
    graph.add_edge("nl2lf_generate", "lf_validate")
    graph.add_conditional_edges(
        "lf_validate",
        route_after_lf_validate,
        {
            "valid": "lf_to_sql_compile",
            "invalid": "nl2sql_fallback",
        },
    )
    graph.add_conditional_edges(
        "lf_to_sql_compile",
        route_after_sql_compile,
        {
            "compiled": "semantic_check",
            "failed": "nl2sql_fallback",
        },
    )
    graph.add_conditional_edges(
        "nl2sql_fallback",
        route_after_nl2sql_fallback_compile,
        {
            "compiled": "sql_execute",
            "confirm": "sql_confirmation",
            "failed": END,
        },
    )
    graph.add_conditional_edges(
        "semantic_check",
        route_after_semantic_check,
        {
            "valid": "sql_execute",
            "confirm": "sql_confirmation",
            "repair": "lf_repair",
            "invalid": END,
        },
    )
    graph.add_edge("sql_confirmation", END)
    graph.add_conditional_edges(
        "sql_execute",
        route_after_sql_execute,
        {
            "success": "planner",
            "retry": "lf_repair",
            "failed": END,
        },
    )
    graph.add_edge("lf_repair", "lf_validate")
    graph.add_edge("planner", "python_generate")
    graph.add_edge("python_generate", "python_analyze")
    graph.add_edge("python_analyze", "report_generator")
    graph.add_edge("report_generator", END)

    return graph


def route_after_intent(state: AgentState) -> str:
    intent = state.get("intent", "chat")
    if intent == "data_query":
        return "data_query"
    return intent


def route_after_lf_validate(state: AgentState) -> str:
    validation = state.get("lf_validation") or {}
    return "valid" if validation.get("valid") else "invalid"


def route_after_schema_recall(state: AgentState) -> str:
    if not state.get("enable_low_confidence_clarification"):
        return "continue"
    tables = state.get("relevant_tables") or []
    columns = state.get("relevant_columns") or []
    return "continue" if tables or columns else "clarify"


def route_after_sql_compile(state: AgentState) -> str:
    return "compiled" if state.get("compiled_sql") else "failed"


def route_after_semantic_check(state: AgentState) -> str:
    check = state.get("semantic_check") or {}
    if not check.get("valid"):
        if state.get("sql_retry_count", 0) < MAX_SQL_RETRIES:
            return "repair"
        return "invalid"
    return "confirm" if state.get("require_sql_confirmation") else "valid"


def route_after_nl2sql_fallback_compile(state: AgentState) -> str:
    if not state.get("compiled_sql"):
        return "failed"
    return "confirm" if state.get("require_sql_confirmation") else "compiled"


def route_after_sql_execute(state: AgentState) -> str:
    if state.get("sql_result"):
        return "success"
    if state.get("sql_error") and state.get("sql_retry_count", 0) < MAX_SQL_RETRIES:
        return "retry"
    if state.get("sql_error"):
        return "failed"
    return "success"
