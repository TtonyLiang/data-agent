import pytest

from app.agent.graph import route_after_intent, route_after_react_controller
from app.agent.nodes import analysis_pipeline
from app.agent.nodes.analysis_pipeline import repair_python_code_with_llm
from app.agent.react import (
    MAX_REACT_ITERATIONS,
    decide_next_action,
    react_controller_node,
)


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        ("data_query", "data_query"),
        ("chat", "chat"),
        ("metadata_query", "metadata_query"),
    ],
)
def test_route_after_intent_covers_supported_dynamic_branches(intent, expected):
    assert route_after_intent({"intent": intent}) == expected


def test_unknown_react_action_is_downgraded_to_response():
    assert route_after_react_controller({"react_next_action": "drop_database"}) == "respond"


def test_react_skips_deep_analysis_for_simple_result():
    decision = decide_next_action(
        {
            "intent": "data_query",
            "react_last_action": "execute_sql",
            "datasource_id": 1,
            "question": "申请笔数是多少",
            "sql_result": [{"application_count": 42}],
        }
    )

    assert decision.action == "respond"
    assert decision.analysis_required is False


def test_react_enters_analysis_for_explicit_trend_request_even_empty_result():
    decision = decide_next_action(
        {
            "intent": "data_query",
            "react_last_action": "execute_sql",
            "datasource_id": 1,
            "question": "请分析近三个月申请笔数趋势并生成报告",
            "sql_result": [],
            "sql_error": None,
        }
    )

    assert decision.action == "analyze_result"
    assert decision.analysis_required is True


@pytest.mark.asyncio
async def test_react_controller_rebuilds_trace_after_legacy_trace_replacement():
    first = await react_controller_node(
        {"intent": "data_query", "datasource_id": 1, "question": "查一个值"}
    )
    second = await react_controller_node(
        {
            "intent": "data_query",
            "datasource_id": 1,
            "question": "查一个值",
            "react_iteration": first["react_iteration"],
            "react_last_action": first["react_last_action"],
            "react_history": first["react_history"],
            "semantic_check": {"valid": True},
            "compiled_sql": "SELECT 1",
            # Simulate a node that replaced execution_trace.
            "execution_trace": {"compile_strategy": "deterministic_logic_form"},
        }
    )

    trace = second["execution_trace"]["react"]
    assert trace["max_iterations"] == MAX_REACT_ITERATIONS
    assert [step["action"] for step in trace["steps"]] == [
        "semantic_enhance",
        "execute_sql",
    ]


@pytest.mark.asyncio
async def test_react_repair_prompt_contains_observation_and_attempt_history(monkeypatch):
    captured = {}

    class FakePromptService:
        async def resolve(self, prompt_key, default_template, **kwargs):
            captured["prompt_key"] = prompt_key
            return "只输出安全 Python 代码。"

    class FakeChunk:
        content = (
            "import json\n"
            "result = {'row_count': len(rows)}\n"
            "print(json.dumps(result, ensure_ascii=False))"
        )
        additional_kwargs = {}

    class FakeLlmService:
        async def resolve_agent_chat_kwargs(self, agent_id):
            return {"model": "repair-test"}

        async def achat_stream(self, messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            yield FakeChunk()

    async def no_stream(*args, **kwargs):
        return None

    monkeypatch.setattr(analysis_pipeline, "get_prompt_service", lambda: FakePromptService())
    monkeypatch.setattr(analysis_pipeline, "get_llm_service", lambda: FakeLlmService())
    monkeypatch.setattr(analysis_pipeline, "emit_phase3_stream", no_stream)

    repaired = await repair_python_code_with_llm(
        {
            "agent_id": 4,
            "question": "分析结果",
            "plan": {"mode": "profile"},
            "sql_result": [{"value": 1}],
        },
        {
            "columns": ["value"],
            "numeric_columns": ["value"],
            "dimension_columns": [],
        },
        "raise ValueError('broken')",
        "NameError: missing_name",
        [{"attempt": 1, "source": "initial", "ok": False, "error": "NameError: missing_name"}],
    )

    assert "result =" in repaired
    assert captured["prompt_key"] == "phase3_python_generate.system"
    user_prompt = captured["messages"][-1]["content"]
    assert "ReAct" in user_prompt
    assert "NameError: missing_name" in user_prompt
    assert "raise ValueError('broken')" in user_prompt
    assert captured["kwargs"] == {"model": "repair-test"}
