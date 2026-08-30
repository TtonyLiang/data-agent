from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from langgraph.graph import END, START

from app.agent import react
from app.agent.graph import build_mvp_graph
from app.agent.nodes import (
    analysis_pipeline,
    clarification,
    conversation,
    human_confirm,
    intent,
    lf_repair,
    lf_to_sql_compile,
    lf_validate,
    nl2lf_generate,
    nl2sql_fallback,
    respond,
    schema_recall,
    semantic_enhance,
    semantic_runtime_recall,
    sql_execute,
)
from app.agent.react import TERMINATION_REPEATED_ACTION
from app.services import task_checkpoint_service

ACTION_NODE_NAMES = {
    "intent_recognition",
    "semantic_enhance",
    "semantic_runtime_recall",
    "schema_recall",
    "clarification",
    "nl2lf_generate",
    "lf_validate",
    "lf_to_sql_compile",
    "nl2sql_fallback",
    "semantic_check",
    "sql_confirmation",
    "lf_repair",
    "sql_execute",
    "planner",
    "python_generate",
    "python_analyze",
    "report_generator",
    "conversation",
    "respond",
}


class RecordingCheckpointService:
    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []

    async def save(self, state: dict[str, Any]) -> int:
        self.states.append(dict(state))
        return len(self.states)


def _fake_node(
    node_name: str,
    calls: list[str],
    update: Mapping[str, Any] | None = None,
):
    async def run(state: dict[str, Any]) -> dict[str, Any]:
        calls.append(node_name)
        return dict(update or {})

    return run


def _patch_nodes(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    updates: Mapping[str, Mapping[str, Any]] | None = None,
) -> RecordingCheckpointService:
    updates = updates or {}
    node_targets = {
        "intent_recognition": (intent, "intent_recognition_node"),
        "semantic_enhance": (semantic_enhance, "semantic_enhance_node"),
        "semantic_runtime_recall": (
            semantic_runtime_recall,
            "semantic_runtime_recall_node",
        ),
        "schema_recall": (schema_recall, "schema_recall_node"),
        "clarification": (clarification, "clarification_node"),
        "nl2lf_generate": (nl2lf_generate, "nl2lf_generate_node"),
        "lf_validate": (lf_validate, "lf_validate_node"),
        "lf_to_sql_compile": (lf_to_sql_compile, "lf_to_sql_compile_node"),
        "nl2sql_fallback": (nl2sql_fallback, "nl2sql_fallback_node"),
        "semantic_check": (analysis_pipeline, "semantic_check_node"),
        "sql_confirmation": (human_confirm, "sql_confirmation_node"),
        "lf_repair": (lf_repair, "lf_repair_node"),
        "sql_execute": (sql_execute, "sql_execute_node"),
        "planner": (analysis_pipeline, "planner_node"),
        "python_generate": (analysis_pipeline, "python_generate_node"),
        "python_analyze": (analysis_pipeline, "python_analyze_node"),
        "report_generator": (analysis_pipeline, "report_generator_node"),
        "conversation": (conversation, "conversation_node"),
        "respond": (respond, "respond_node"),
    }
    for node_name, (module, attribute) in node_targets.items():
        monkeypatch.setattr(
            module,
            attribute,
            _fake_node(node_name, calls, updates.get(node_name)),
        )

    checkpoint_service = RecordingCheckpointService()
    monkeypatch.setattr(
        task_checkpoint_service,
        "get_task_checkpoint_service",
        lambda: checkpoint_service,
    )
    return checkpoint_service


def _base_state(**overrides: Any) -> dict[str, Any]:
    state = {
        "question": "贷款申请有多少笔",
        "agent_id": 1,
        "user_id": 9,
        "session_id": "session-supervisor-test",
        "datasource_id": 7,
        "trace_id": "trace-supervisor-test",
        "task_id": "task-supervisor-test",
        "turn_id": "turn-supervisor-test",
        "turn_mode": "new_task",
        "sql_retry_count": 0,
    }
    state.update(overrides)
    return state


def _checkpoint_actions(service: RecordingCheckpointService) -> list[str]:
    return [str(state.get("react_last_action")) for state in service.states]


def test_every_production_action_returns_through_checkpoint_and_supervisor():
    graph = build_mvp_graph()

    assert set(graph.nodes) == ACTION_NODE_NAMES | {"react_controller", "task_checkpoint"}
    assert (START, "react_controller") in graph.edges
    assert {(name, "task_checkpoint") for name in ACTION_NODE_NAMES} <= graph.edges

    supervisor_branch = graph.branches["react_controller"]["route_after_react_controller"]
    assert set(supervisor_branch.ends.values()) == ACTION_NODE_NAMES
    checkpoint_branch = graph.branches["task_checkpoint"]["route_after_task_checkpoint"]
    assert checkpoint_branch.ends == {"continue": "react_controller", "end": END}


@pytest.mark.asyncio
async def test_new_task_is_decided_and_checkpointed_one_action_at_a_time(monkeypatch):
    calls: list[str] = []
    checkpoint_service = _patch_nodes(
        monkeypatch,
        calls,
        {
            "intent_recognition": {"intent": "data_query"},
            "semantic_enhance": {"enhanced_question": "统计贷款申请笔数"},
            "semantic_runtime_recall": {
                "semantic_runtime": {"domain": {"id": 3}},
                "runtime_evidence": [],
            },
            "schema_recall": {
                "relevant_tables": [{"table_name": "loan_application"}],
                "relevant_columns": [{"column_name": "application_id"}],
            },
            "nl2lf_generate": {"logic_form": {"metrics": ["application_count"]}},
            "lf_validate": {"lf_validation": {"valid": True, "errors": []}},
            "lf_to_sql_compile": {
                "compiled_sql": "SELECT COUNT(*) AS application_count FROM loan_application",
                "execution_trace": {"compile_strategy": "deterministic_logic_form"},
            },
            "semantic_check": {"semantic_check": {"valid": True}},
            "sql_execute": {"sql_result": [{"application_count": 42}], "sql_error": None},
            "respond": {"final_answer": "贷款申请共 42 笔。"},
        },
    )

    result = await build_mvp_graph().compile().ainvoke(_base_state())

    expected_nodes = [
        "intent_recognition",
        "semantic_enhance",
        "semantic_runtime_recall",
        "schema_recall",
        "nl2lf_generate",
        "lf_validate",
        "lf_to_sql_compile",
        "semantic_check",
        "sql_execute",
        "respond",
    ]
    expected_actions = [
        "recognize_intent",
        "semantic_enhance",
        "semantic_recall",
        "schema_recall",
        "generate_logic_form",
        "validate_logic_form",
        "compile_sql",
        "semantic_check",
        "execute_sql",
        "respond",
    ]
    assert calls == expected_nodes
    assert [step["action"] for step in result["react_history"]] == expected_actions
    assert _checkpoint_actions(checkpoint_service) == expected_actions
    assert result["checkpoint_revision"] == len(expected_actions)
    assert result["task_status"] == "completed"


@pytest.mark.asyncio
async def test_analyze_turn_starts_at_planner_and_skips_query_pipeline(monkeypatch):
    calls: list[str] = []
    checkpoint_service = _patch_nodes(
        monkeypatch,
        calls,
        {
            "planner": {"plan": {"mode": "trend"}},
            "python_generate": {"python_code": "result = {'trend': 'up'}"},
            "python_analyze": {"python_result": {"status": "success", "trend": "up"}},
            "report_generator": {
                "report": "贷款申请呈上升趋势。",
                "report_payload": {"title": "贷款趋势分析"},
            },
        },
    )

    result = await build_mvp_graph().compile().ainvoke(
        _base_state(
            question="分析刚才结果的趋势",
            turn_mode="analyze",
            intent="data_query",
            sql_executed=True,
            sql_result=[{"month": "2026-07", "application_count": 40}],
        )
    )

    assert calls == ["planner", "python_generate", "python_analyze", "report_generator"]
    assert _checkpoint_actions(checkpoint_service) == [
        "analyze_result",
        "generate_analysis_code",
        "run_analysis",
        "generate_report",
    ]
    assert not {
        "intent_recognition",
        "semantic_enhance",
        "semantic_runtime_recall",
        "schema_recall",
        "nl2lf_generate",
        "lf_to_sql_compile",
        "semantic_check",
        "sql_execute",
    }.intersection(calls)
    assert result["task_status"] == "completed"


@pytest.mark.asyncio
async def test_retry_turn_executes_existing_sql_without_regeneration(monkeypatch):
    calls: list[str] = []
    checkpoint_service = _patch_nodes(
        monkeypatch,
        calls,
        {
            "sql_execute": {"sql_result": [{"application_count": 42}], "sql_error": None},
            "respond": {"final_answer": "重新执行成功，共 42 笔。"},
        },
    )

    result = await build_mvp_graph().compile().ainvoke(
        _base_state(
            question="重新执行",
            turn_mode="retry",
            intent="data_query",
            compiled_sql="SELECT COUNT(*) AS application_count FROM loan_application",
            semantic_check={"valid": True},
            semantic_check_attempted=True,
            execution_trace={"compile_strategy": "deterministic_logic_form"},
        )
    )

    assert calls == ["sql_execute", "respond"]
    assert _checkpoint_actions(checkpoint_service) == ["execute_sql", "respond"]
    assert result["compiled_sql"].startswith("SELECT COUNT")
    assert result["sql_result"] == [{"application_count": 42}]


@pytest.mark.asyncio
async def test_graph_boundary_downgrades_non_whitelisted_controller_action(monkeypatch):
    calls: list[str] = []
    checkpoint_service = _patch_nodes(
        monkeypatch,
        calls,
        {"respond": {"final_answer": "已安全停止。"}},
    )

    async def malicious_controller(state):
        return {"react_next_action": "drop_database", "react_last_action": "drop_database"}

    monkeypatch.setattr(react, "react_controller_node", malicious_controller)

    result = await build_mvp_graph().compile().ainvoke(_base_state())

    assert calls == ["respond"]
    assert len(checkpoint_service.states) == 1
    assert result["task_status"] == "completed"


@pytest.mark.asyncio
async def test_repeated_action_guard_stops_the_production_graph(monkeypatch):
    calls: list[str] = []
    checkpoint_service = _patch_nodes(
        monkeypatch,
        calls,
        {"respond": {"final_answer": "已停止重复尝试。"}},
    )

    result = await build_mvp_graph().compile().ainvoke(
        _base_state(
            intent="data_query",
            react_last_action="repair",
            react_history=[{"action": "repair"}, {"action": "repair"}],
        )
    )

    assert calls == ["respond"]
    assert _checkpoint_actions(checkpoint_service) == ["respond"]
    assert result["react_termination_reason"] == TERMINATION_REPEATED_ACTION


@pytest.mark.asyncio
async def test_exhausted_repair_budget_prevents_another_repair_action(monkeypatch):
    calls: list[str] = []
    checkpoint_service = _patch_nodes(
        monkeypatch,
        calls,
        {"respond": {"final_answer": "自动修复次数已用尽。"}},
    )

    result = await build_mvp_graph().compile().ainvoke(
        _base_state(
            intent="data_query",
            logic_form={"metrics": ["application_count"]},
            sql_error="unknown column application_id",
            sql_retry_count=2,
        )
    )

    assert calls == ["respond"]
    assert "lf_repair" not in calls
    assert _checkpoint_actions(checkpoint_service) == ["respond"]
    assert result["react_next_action"] == "respond"
