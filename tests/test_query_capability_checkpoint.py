import json
from typing import get_type_hints

from app.agent.graph import AgentState
from app.services.task_checkpoint_service import checkpoint_payload, reconcile_task_state

CONTEXT = {
    "fingerprint": "context-v1",
    "datasource_id": 7,
    "semantic_domain_id": 3,
    "chat_model_config_id": 1,
    "embedding_model_config_id": 2,
}


def previous_task(**overrides):
    state = {
        "task_id": "task-existing",
        "turn_id": "turn-1",
        "task_revision": 1,
        "task_status": "completed",
        "turn_mode": "new_task",
        "question": "查询本月贷款余额",
        "intent": "data_query",
        "agent_id": 1,
        "user_id": 9,
        "session_id": "session-1",
        "datasource_id": 7,
        "task_context": CONTEXT,
        "query_context": {
            "question": "查询本月贷款余额",
            "query_capabilities": [{"key": "query_loan_balance"}],
        },
        "query_capability_key": "query_loan_balance",
        "query_capability_validation": {
            "capability_key": "query_loan_balance",
            "valid": True,
        },
        "semantic_runtime": {"domain": {"id": 3}},
        "logic_form": {"metrics": ["outstanding_balance"]},
        "lf_validation": {"valid": True},
        "compiled_sql": "SELECT SUM(balance) FROM loan_balance",
        "sql_executed": True,
        "sql_result": [{"outstanding_balance": 100}],
    }
    state.update(overrides)
    return state


def reconcile(question, previous=None, context=None, requested_mode=None):
    return reconcile_task_state(
        previous if previous is not None else previous_task(),
        question=question,
        agent_id=1,
        user_id=9,
        session_id="session-1",
        datasource_id=7,
        trace_id="new-trace",
        context=context or CONTEXT,
        requested_mode=requested_mode,
    )


def test_new_task_clears_query_context_and_capability_state():
    state = reconcile("统计客户总数")

    assert state["turn_mode"] == "new_task"
    for field in (
        "query_context",
        "query_capability_key",
        "query_capability_validation",
        "logic_form",
    ):
        assert field not in state


def test_refine_preserves_query_context_but_clears_query_capability_artifacts():
    state = reconcile("换成上个月")

    assert state["turn_mode"] == "refine"
    assert state["query_context"] == previous_task()["query_context"]
    assert "query_capability_key" not in state
    assert "query_capability_validation" not in state
    assert "logic_form" not in state
    assert "compiled_sql" not in state
    assert "query_context" in state["reused_artifacts"]
    assert "query_capability" not in state["reused_artifacts"]


def test_retry_clears_query_capability_artifacts_but_keeps_existing_sql():
    state = reconcile("重新执行", requested_mode="retry")

    assert state["turn_mode"] == "retry"
    assert state["query_context"] == previous_task()["query_context"]
    assert "query_capability_key" not in state
    assert "query_capability_validation" not in state
    assert state["logic_form"] == previous_task()["logic_form"]
    assert state["compiled_sql"] == previous_task()["compiled_sql"]
    assert "query_context" in state["reused_artifacts"]
    assert "query_capability" not in state["reused_artifacts"]


def test_context_fingerprint_change_clears_query_context_and_dependent_artifacts():
    changed_context = {**CONTEXT, "fingerprint": "context-v2", "semantic_domain_id": 8}
    state = reconcile("继续执行", context=changed_context, requested_mode="continue")

    assert state["context_invalidated"] is True
    for field in (
        "query_context",
        "query_capability_key",
        "query_capability_validation",
        "logic_form",
        "compiled_sql",
    ):
        assert field not in state
    assert {
        "query_context",
        "query_capability_key",
        "query_capability_validation",
    }.issubset(state["invalidated_artifacts"])


def test_checkpoint_payload_round_trips_query_capability_fields_as_json():
    state = previous_task(
        query_context={
            "query_capabilities": [{"key": "query_loan_balance", "limits": [1, 10]}],
            "release": {"version": 2},
        },
        query_capability_validation={
            "capability_key": "query_loan_balance",
            "valid": True,
            "used_metrics": ["outstanding_balance"],
        },
    )

    payload = checkpoint_payload(state)
    restored = json.loads(json.dumps(payload, ensure_ascii=False))

    assert restored["query_context"] == state["query_context"]
    assert restored["query_capability_key"] == state["query_capability_key"]
    assert restored["query_capability_validation"] == state["query_capability_validation"]


def test_old_checkpoint_without_new_fields_remains_compatible():
    previous = previous_task()
    for field in ("query_context", "query_capability_key", "query_capability_validation"):
        previous.pop(field)

    state = reconcile("换成上个月", previous=previous)

    assert "query_context" not in state
    assert "query_capability_key" not in state
    assert "query_capability_validation" not in state
    assert checkpoint_payload(previous) == previous


def test_agent_state_declares_query_capability_fields():
    annotations = get_type_hints(AgentState)

    assert str(annotations["query_context"]) == "dict[str, typing.Any]"
    assert str(annotations["query_capability_key"]) == "str | None"
    assert str(annotations["query_capability_validation"]) == "dict[str, typing.Any]"
