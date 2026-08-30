import asyncio

from app.agent.react import (
    ALLOWED_ACTIONS,
    ANALYZE_RESULT,
    CLARIFY,
    COMPILE_SQL,
    EXECUTE_SQL,
    GENERATE_LOGIC_FORM,
    REPAIR,
    RESPOND,
    SCHEMA_RECALL,
    SEMANTIC_RECALL,
    TERMINATION_MAX_ITERATIONS,
    TERMINATION_REPAIR_LIMIT,
    TERMINATION_REPEATED_ACTION,
    arun_react_loop,
    choose_next_action,
    is_simple_query,
    requested_analysis_types,
    run_react_loop,
)


def _ready_state(**overrides):
    state = {
        "intent": "data_query",
        "question": "申请笔数",
        "semantic_runtime": {"metrics": []},
        "relevant_tables": [{"table_name": "loan_application_indicator"}],
        "logic_form": {"metrics": ["application_count"], "dimensions": []},
        "compiled_sql": "SELECT COUNT(*) AS application_count FROM loan_application_indicator",
        "sql_result": [{"application_count": 42}],
    }
    state.update(overrides)
    return state


def test_allowed_actions_cover_the_query_lifecycle():
    assert {
        SEMANTIC_RECALL,
        SCHEMA_RECALL,
        GENERATE_LOGIC_FORM,
        COMPILE_SQL,
        EXECUTE_SQL,
        ANALYZE_RESULT,
        RESPOND,
        CLARIFY,
        REPAIR,
    } <= ALLOWED_ACTIONS


def test_normal_query_follows_bounded_pipeline_then_responds():
    actions_seen = []

    def act(action, state):
        actions_seen.append(action)
        return {
            SEMANTIC_RECALL: {"semantic_runtime": {"domain": {"id": 1}}},
            SCHEMA_RECALL: {"relevant_tables": [{"table_name": "orders"}]},
            GENERATE_LOGIC_FORM: {"logic_form": {"metrics": ["application_count"]}},
            COMPILE_SQL: {"compiled_sql": "SELECT COUNT(*) AS application_count FROM orders"},
            EXECUTE_SQL: {"sql_result": [{"application_count": 42}]},
            RESPOND: {"final_answer": "申请笔数为 42。"},
        }.get(action, {})

    result = run_react_loop(
        {"intent": "data_query", "question": "申请笔数"},
        act,
        max_iterations=8,
    )

    assert actions_seen == [
        SEMANTIC_RECALL,
        SCHEMA_RECALL,
        GENERATE_LOGIC_FORM,
        COMPILE_SQL,
        EXECUTE_SQL,
        RESPOND,
    ]
    assert result.termination_reason == "complete"
    assert result.state.final_answer == "申请笔数为 42。"
    assert result.iterations == len(actions_seen)


def test_simple_query_skips_deep_analysis():
    state = _ready_state()

    decision = choose_next_action(state)

    assert decision.action == RESPOND
    assert decision.done is True
    assert decision.analysis_requested is False
    assert is_simple_query(state) is True


def test_explicit_analysis_request_routes_to_analyze_result():
    state = _ready_state(
        question="请分析近三个月申请笔数趋势并生成图表",
        sql_result=[
            {"month": "2026-01", "application_count": 12},
            {"month": "2026-02", "application_count": 18},
        ],
    )

    decision = choose_next_action(state)

    assert decision.action == ANALYZE_RESULT
    assert decision.done is False
    assert decision.analysis_requested is True
    assert requested_analysis_types(state) == {"trend", "chart"}


def test_repair_stops_at_configured_error_budget():
    state = _ready_state(
        sql_result=[],
        sql_error="temporary database error",
        sql_result_present=True,
        repair_count=2,
        max_repairs=2,
    )

    decision = choose_next_action(state)

    assert decision.action == RESPOND
    assert decision.done is True
    assert decision.termination_reason == TERMINATION_REPAIR_LIMIT


def test_repeated_action_is_terminated_before_third_attempt():
    state = {
        "question": "申请笔数",
        "action_history": [SEMANTIC_RECALL, SEMANTIC_RECALL],
        "repeat_limit": 2,
    }

    decision = choose_next_action(state)

    assert decision.action == RESPOND
    assert decision.done is True
    assert decision.termination_reason == TERMINATION_REPEATED_ACTION


def test_max_iterations_is_a_hard_bound():
    state = {
        "question": "申请笔数",
        "iteration": 3,
        "max_iterations": 3,
    }

    decision = choose_next_action(state)

    assert decision.action == RESPOND
    assert decision.done is True
    assert decision.termination_reason == TERMINATION_MAX_ITERATIONS


def test_missing_question_requests_clarification():
    decision = choose_next_action({})

    assert decision.action == CLARIFY
    assert decision.done is True


def test_chooser_does_not_mutate_caller_state():
    state = _ready_state(action_history=[])
    before = dict(state)

    choose_next_action(state)

    assert state == before
    assert state["action_history"] == []


def test_async_loop_supports_observe_act_observe_order():
    events = []

    async def observe(state, action=None):
        events.append(("observe", action))
        return None

    async def act(action, state):
        events.append(("act", action))
        if action == SEMANTIC_RECALL:
            return {"semantic_runtime": {"domain": {"id": 1}}}
        if action == SCHEMA_RECALL:
            return {"relevant_tables": [{"table_name": "orders"}]}
        if action == GENERATE_LOGIC_FORM:
            return {"logic_form": {"metrics": ["application_count"]}}
        if action == COMPILE_SQL:
            return {"compiled_sql": "SELECT 1"}
        if action == EXECUTE_SQL:
            return {"sql_result": [{"value": 1}]}
        return {"final_answer": "完成。"}

    result = asyncio.run(
        arun_react_loop(
            {"intent": "data_query", "question": "申请笔数"},
            act,
            observe,
            max_iterations=8,
        )
    )

    assert result.termination_reason == "complete"
    assert events[0] == ("observe", None)
    assert events[1][0] == "act"
    assert events[2][0] == "observe"
