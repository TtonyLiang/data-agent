import asyncio
import json

import pytest

from app.agent.react import decide_next_action
from app.services import task_checkpoint_service
from app.services.task_checkpoint_service import (
    CheckpointConflictError,
    TaskCheckpointService,
    classify_turn_mode,
    reconcile_task_state,
)

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
        "enhanced_question": "查询本月贷款余额",
        "semantic_runtime": {"domain": {"id": 3}},
        "runtime_evidence": [{"metadata": {"asset_key": "outstanding_balance"}}],
        "schema_ready": True,
        "relevant_tables": [{"table_name": "loan_balance"}],
        "relevant_columns": [{"column_name": "balance"}],
        "logic_form": {"metrics": ["outstanding_balance"]},
        "lf_validation": {"valid": True},
        "compiled_sql": "SELECT SUM(balance) FROM loan_balance",
        "semantic_check": {"valid": True},
        "semantic_check_attempted": True,
        "sql_executed": True,
        "sql_result": [{"outstanding_balance": 100}],
        "plan": {"mode": "profile"},
        "python_result": {"status": "success"},
        "report_payload": {"title": "余额分析"},
        "execution_trace": {
            "trace_id": "old-trace",
            "compile_strategy": "deterministic_logic_form",
        },
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


def test_time_refinement_reuses_semantic_and_schema_but_invalidates_query_outputs():
    state = reconcile("换成上个月")

    assert state["turn_mode"] == "refine"
    assert state["semantic_runtime"]["domain"]["id"] == 3
    assert state["relevant_tables"][0]["table_name"] == "loan_balance"
    assert "semantic_runtime" in state["reused_artifacts"]
    assert "schema" in state["reused_artifacts"]
    assert "logic_form" not in state
    assert "compiled_sql" not in state
    assert "sql_result" not in state
    assert decide_next_action(state).action == "semantic_enhance"


def test_analysis_turn_preserves_business_subject_for_later_refinement():
    analyzed = reconcile("分析刚才的结果")
    assert analyzed["task_subject_question"] == "查询本月贷款余额"

    analyzed["enhanced_question"] = "查询本月贷款余额"
    refined = reconcile("换成前两个月", previous=analyzed)

    assert refined["task_subject_question"] == "查询本月贷款余额"
    assert refined["analysis_required"] is False


def test_dimension_refinement_reuses_semantic_runtime_and_reruns_schema_recall():
    state = reconcile("再按地区拆分")

    assert state["turn_mode"] == "refine"
    assert "semantic_runtime" in state
    assert "schema_ready" not in state
    assert "relevant_tables" not in state
    state["enhanced_question"] = "按地区拆分贷款余额"
    assert decide_next_action(state).action == "schema_recall"


def test_retry_reuses_validated_sql_and_starts_at_execution():
    state = reconcile("重新执行", requested_mode="retry")

    assert state["compiled_sql"] == "SELECT SUM(balance) FROM loan_balance"
    assert state["semantic_check"] == {"valid": True}
    assert "sql_result" not in state
    assert decide_next_action(state).action == "execute_sql"


def test_analyze_reuses_previous_result_without_regenerating_or_executing_sql():
    state = reconcile("分析刚才的结果")

    assert state["turn_mode"] == "analyze"
    assert state["sql_result"] == [{"outstanding_balance": 100}]
    assert "plan" not in state
    assert decide_next_action(state).action == "analyze_result"

    state["plan"] = {"mode": "profile"}
    assert decide_next_action(state).action == "generate_analysis_code"
    state["python_code"] = "print('{}')"
    state["python_result"] = {"status": "generated"}
    assert decide_next_action(state).action == "run_analysis"
    state["python_result"] = {"status": "success"}
    assert decide_next_action(state).action == "generate_report"


def test_unrelated_question_starts_a_new_task_and_drops_all_artifacts():
    previous = previous_task()
    state = reconcile("统计客户总数", previous)

    assert classify_turn_mode("统计客户总数", previous) == "new_task"
    assert state["task_id"] != previous["task_id"]
    assert state["turn_mode"] == "new_task"
    assert "semantic_runtime" not in state
    assert "compiled_sql" not in state
    assert "sql_result" not in state


def test_context_change_invalidates_stale_datasource_and_domain_artifacts():
    changed = {**CONTEXT, "fingerprint": "context-v2", "semantic_domain_id": 8}
    state = reconcile("继续执行", context=changed, requested_mode="continue")

    assert state["context_invalidated"] is True
    assert "semantic_runtime" not in state
    assert "relevant_tables" not in state
    assert "compiled_sql" not in state
    assert "sql_result" not in state
    assert decide_next_action(state).action == "recognize_intent"


class FakeCheckpointDB:
    def __init__(self):
        self.row = None
        self.transaction_lock = asyncio.Lock()

    async def execute_query(self, sql, params=None):
        if sql.startswith("SELECT revision, checkpoint_json"):
            return [dict(self.row)] if self.row else []
        return []

    async def execute_in_transaction(self, callback):
        async with self.transaction_lock:
            return await callback(FakeCheckpointSession(self))


class FakeCheckpointSession:
    def __init__(self, db):
        self.db = db

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if sql.startswith("SELECT revision FROM agent_task_checkpoint"):
            row = {"revision": self.db.row["revision"]} if self.db.row else None
            return FakeCheckpointResult(row=row)
        if sql.startswith("INSERT INTO agent_task_checkpoint"):
            if self.db.row is not None:
                raise AssertionError("row lock should prevent duplicate checkpoint inserts")
            self.db.row = {**params, "revision": params["new_revision"]}
            return FakeCheckpointResult(rowcount=1)
        if sql.startswith("UPDATE agent_task_checkpoint SET"):
            if (
                self.db.row is None
                or self.db.row["revision"] != params["expected_revision"]
            ):
                return FakeCheckpointResult(rowcount=0)
            self.db.row = {**self.db.row, **params, "revision": params["new_revision"]}
            return FakeCheckpointResult(rowcount=1)
        raise AssertionError(f"unexpected transaction SQL: {sql}")


class FakeCheckpointResult:
    def __init__(self, *, row=None, rowcount=0):
        self.row = row
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.row


@pytest.mark.asyncio
async def test_checkpoint_resumes_after_service_recreation(monkeypatch):
    db = FakeCheckpointDB()
    monkeypatch.setattr(task_checkpoint_service, "get_management_db", lambda: db)
    initial = previous_task(task_status="running")

    await TaskCheckpointService().save(initial)
    restarted_service = TaskCheckpointService()
    restored = await restarted_service.load(9, 1, "session-1")

    assert restored["task_id"] == "task-existing"
    assert restored["compiled_sql"] == initial["compiled_sql"]
    assert restored["sql_result"] == initial["sql_result"]
    assert restored["checkpoint_revision"] == 1
    stored_payload = json.loads(db.row["checkpoint_json"])
    assert stored_payload["checkpoint_revision"] == 1
    assert stored_payload["semantic_runtime"] == initial["semantic_runtime"]


@pytest.mark.asyncio
async def test_concurrent_stale_saves_do_not_overwrite_the_winner(monkeypatch):
    db = FakeCheckpointDB()
    monkeypatch.setattr(task_checkpoint_service, "get_management_db", lambda: db)
    service = TaskCheckpointService()
    initial = previous_task(task_status="running")
    assert await service.save(initial) == 1

    first = {
        **initial,
        "checkpoint_revision": 1,
        "turn_id": "turn-concurrent-a",
        "sql_result": [{"writer": "a"}],
    }
    second = {
        **initial,
        "checkpoint_revision": 1,
        "turn_id": "turn-concurrent-b",
        "sql_result": [{"writer": "b"}],
    }

    results = await asyncio.gather(
        service.save(first),
        service.save(second),
        return_exceptions=True,
    )

    assert [result for result in results if result == 2] == [2]
    conflicts = [result for result in results if isinstance(result, CheckpointConflictError)]
    assert len(conflicts) == 1
    stored_payload = json.loads(db.row["checkpoint_json"])
    assert db.row["revision"] == 2
    assert stored_payload["checkpoint_revision"] == 2
    winning_writer = {
        "turn-concurrent-a": "a",
        "turn-concurrent-b": "b",
    }[stored_payload["turn_id"]]
    assert stored_payload["sql_result"] == [{"writer": winning_writer}]
