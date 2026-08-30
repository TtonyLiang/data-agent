from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.react import REACT_ACTIONS


class AgentState(TypedDict, total=False):
    # 输入
    question: str
    agent_id: int
    session_id: str
    datasource_id: int | None
    trace_id: str
    user_id: int
    user_role: str
    user_turn_question: str
    task_subject_question: str

    # 持久任务 / 轮次
    task_id: str
    turn_id: str
    task_revision: int
    checkpoint_revision: int
    turn_mode: str
    task_status: str
    task_terminal: bool
    task_context: dict[str, Any]
    context_invalidated: bool
    invalidated_artifacts: list[str]
    reused_artifacts: list[str]
    task_action_history: list[dict[str, Any]]

    # 意图识别
    intent: str  # "data_query" | "chat" | "metadata_query"
    need_analysis: bool

    # 语义增强
    enhanced_question: str
    semantic_enhancement: dict[str, Any]

    # 语义运行时 / LogicForm
    runtime_evidence: list[dict[str, Any]]
    semantic_runtime: dict[str, Any]
    ontology_context: dict[str, Any]
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
    schema_ready: bool

    # 计划 (Phase 3)
    plan: dict[str, Any]
    semantic_check: dict[str, Any]

    # SQL 生成与执行
    sql_text: str
    sql_result: list[dict[str, Any]]
    sql_error: str | None
    sql_retry_count: int
    sql_executed: bool
    sql_result_present: bool
    logic_form_attempted: bool
    compile_attempted: bool
    fallback_attempted: bool
    semantic_check_attempted: bool
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
    conversation: dict[str, Any]
    conversation_metadata: dict[str, Any]

    # ReAct 控制器
    react_iteration: int
    react_last_action: str
    react_next_action: str
    react_termination_reason: str | None
    react_history: list[dict[str, Any]]
    analysis_required: bool
    force_analysis: bool
    response: dict[str, Any]


MAX_SQL_RETRIES = 2


def build_mvp_graph() -> StateGraph:
    """Build a bounded supervisor loop around the existing business nodes.

    Every iteration chooses exactly one whitelisted action, executes one node,
    persists the resulting observation, then returns to the supervisor.  This
    keeps the existing node implementations while removing the fixed pipeline.
    """
    from app.agent.nodes.analysis_pipeline import (
        planner_node,
        python_analyze_node,
        python_generate_node,
        report_generator_node,
        semantic_check_node,
    )
    from app.agent.nodes.clarification import clarification_node
    from app.agent.nodes.conversation import conversation_node
    from app.agent.nodes.human_confirm import sql_confirmation_node
    from app.agent.nodes.intent import intent_recognition_node
    from app.agent.nodes.lf_repair import lf_repair_node
    from app.agent.nodes.lf_to_sql_compile import lf_to_sql_compile_node
    from app.agent.nodes.lf_validate import lf_validate_node
    from app.agent.nodes.nl2lf_generate import nl2lf_generate_node
    from app.agent.nodes.nl2sql_fallback import nl2sql_fallback_node
    from app.agent.nodes.respond import respond_node
    from app.agent.nodes.schema_recall import schema_recall_node
    from app.agent.nodes.semantic_enhance import semantic_enhance_node
    from app.agent.nodes.semantic_runtime_recall import semantic_runtime_recall_node
    from app.agent.nodes.sql_execute import sql_execute_node
    from app.agent.react import react_controller_node

    graph = StateGraph(AgentState)

    action_nodes = {
        "intent_recognition": _action_node("recognize_intent", intent_recognition_node),
        "semantic_enhance": _action_node("semantic_enhance", semantic_enhance_node),
        "semantic_runtime_recall": _action_node("semantic_recall", semantic_runtime_recall_node),
        "schema_recall": _action_node(
            "schema_recall", schema_recall_node, markers={"schema_ready": True}
        ),
        "clarification": _action_node(
            "clarify", clarification_node, terminal_status="awaiting_input"
        ),
        "nl2lf_generate": _action_node(
            "generate_logic_form",
            nl2lf_generate_node,
            markers={"logic_form_attempted": True},
        ),
        "lf_validate": _action_node("validate_logic_form", lf_validate_node),
        "lf_to_sql_compile": _action_node(
            "compile_sql", lf_to_sql_compile_node, markers={"compile_attempted": True}
        ),
        "nl2sql_fallback": _action_node(
            "fallback_sql", nl2sql_fallback_node, markers={"fallback_attempted": True}
        ),
        "semantic_check": _action_node(
            "semantic_check", semantic_check_node, markers={"semantic_check_attempted": True}
        ),
        "sql_confirmation": _action_node(
            "confirm", sql_confirmation_node, terminal_status="awaiting_input"
        ),
        "lf_repair": _action_node(
            "repair",
            lf_repair_node,
            clears={
                "lf_validation",
                "compiled_query",
                "compiled_sql",
                "sql_text",
                "compile_attempted",
                "semantic_check",
                "semantic_check_attempted",
                "sql_result",
                "sql_result_present",
                "sql_executed",
                "sql_error",
            },
        ),
        "sql_execute": _action_node(
            "execute_sql",
            sql_execute_node,
            markers={"sql_executed": True, "sql_result_present": True},
        ),
        "planner": _action_node("analyze_result", planner_node),
        "python_generate": _action_node("generate_analysis_code", python_generate_node),
        "python_analyze": _action_node("run_analysis", python_analyze_node),
        "report_generator": _action_node(
            "generate_report", report_generator_node, terminal_status="completed"
        ),
        "conversation": _action_node(
            "conversation", conversation_node, terminal_status="completed"
        ),
        "respond": _action_node("respond", respond_node, terminal_status="completed"),
    }
    for name, node in action_nodes.items():
        graph.add_node(name, node)
    graph.add_node("react_controller", react_controller_node)
    graph.add_node("task_checkpoint", task_checkpoint_node)

    graph.add_edge(START, "react_controller")
    graph.add_conditional_edges(
        "react_controller",
        route_after_react_controller,
        {
            "recognize_intent": "intent_recognition",
            "conversation": "conversation",
            "semantic_enhance": "semantic_enhance",
            "semantic_recall": "semantic_runtime_recall",
            "schema_recall": "schema_recall",
            "generate_logic_form": "nl2lf_generate",
            "validate_logic_form": "lf_validate",
            "compile_sql": "lf_to_sql_compile",
            "fallback_sql": "nl2sql_fallback",
            "semantic_check": "semantic_check",
            "execute_sql": "sql_execute",
            "repair": "lf_repair",
            "confirm": "sql_confirmation",
            "clarify": "clarification",
            "analyze_result": "planner",
            "generate_analysis_code": "python_generate",
            "run_analysis": "python_analyze",
            "generate_report": "report_generator",
            "respond": "respond",
            "stop": "respond",
        },
    )

    for name in action_nodes:
        graph.add_edge(name, "task_checkpoint")
    graph.add_conditional_edges(
        "task_checkpoint",
        route_after_task_checkpoint,
        {"continue": "react_controller", "end": END},
    )

    return graph


def _action_node(
    action: str,
    node,
    *,
    clears: set[str] | None = None,
    markers: dict[str, Any] | None = None,
    terminal_status: str | None = None,
):
    """Wrap one existing node as a single supervisor action."""

    async def run(state: AgentState) -> dict[str, Any]:
        result = await node(dict(state))
        update: dict[str, Any] = {field: None for field in clears or set()}
        if isinstance(result, dict):
            update.update(result)
        update.update(markers or {})
        update["task_last_action"] = action
        update["task_status"] = terminal_status or "running"
        update["task_terminal"] = terminal_status is not None
        return update

    return run


async def task_checkpoint_node(state: AgentState) -> dict[str, Any]:
    """Persist the observation produced by the most recent action."""
    from app.services.task_checkpoint_service import get_task_checkpoint_service

    revision = await get_task_checkpoint_service().save(dict(state))
    return {"checkpoint_revision": revision}


def route_after_task_checkpoint(state: AgentState) -> str:
    return "end" if state.get("task_terminal") else "continue"


def route_after_intent(state: AgentState) -> str:
    intent = state.get("intent", "chat")
    if intent == "data_query":
        return "data_query"
    return intent if intent in {"chat", "metadata_query"} else "chat"


def route_after_react_controller(state: AgentState) -> str:
    """Map a controller action to a graph edge, with a safe fallback."""
    action = str(state.get("react_next_action") or "respond").strip().lower()
    graph_actions = {
        "recognize_intent",
        "conversation",
        "semantic_enhance",
        "semantic_recall",
        "schema_recall",
        "generate_logic_form",
        "validate_logic_form",
        "compile_sql",
        "fallback_sql",
        "semantic_check",
        "execute_sql",
        "repair",
        "confirm",
        "clarify",
        "analyze_result",
        "generate_analysis_code",
        "run_analysis",
        "generate_report",
        "respond",
        "stop",
    }
    return action if action in REACT_ACTIONS and action in graph_actions else "respond"


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
