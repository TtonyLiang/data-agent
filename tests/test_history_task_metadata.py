import json

import pytest

from app import main
from app.models.user import PublicUser

ADMIN_USER = PublicUser(id=1, username="admin", role="admin", status="active")
TASK_METADATA = {
    "reused_artifacts": ["semantic_runtime", "schema"],
    "invalidated_artifacts": ["logic_form", "compiled_sql", "sql_result"],
    "context_invalidated": True,
}


class RecordingHistoryDB:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries: list[tuple[str, dict | None]] = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        if sql.startswith("SELECT role, content"):
            return [dict(row) for row in self.rows]
        return []


@pytest.mark.asyncio
async def test_save_turn_persists_task_identity_status_and_metadata(monkeypatch):
    db = RecordingHistoryDB()
    monkeypatch.setattr(main, "get_management_db", lambda: db)

    await main.save_turn(
        agent_id=7,
        session_id="session-history-task",
        question="换成上个月",
        answer="上个月贷款余额为 100。",
        sql="SELECT SUM(balance) FROM loan_balance",
        sql_result=[{"balance": 100}],
        task_id="task-existing",
        turn_id="turn-refine-2",
        turn_mode="refine",
        task_status="completed",
        task_metadata=TASK_METADATA,
        user=ADMIN_USER,
    )

    assistant_sql, assistant_params = next(
        (sql, params) for sql, params in db.queries if "'assistant'" in sql
    )
    assert all(
        column in assistant_sql
        for column in ("task_id", "turn_id", "turn_mode", "task_status", "task_metadata")
    )
    assert assistant_params["task_id"] == "task-existing"
    assert assistant_params["turn_id"] == "turn-refine-2"
    assert assistant_params["turn_mode"] == "refine"
    assert assistant_params["task_status"] == "completed"
    assert json.loads(assistant_params["task_metadata"]) == TASK_METADATA


@pytest.mark.asyncio
async def test_history_api_restores_task_fields_and_expands_task_metadata(monkeypatch):
    db = RecordingHistoryDB(
        [
            {
                "role": "assistant",
                "content": "上个月贷款余额为 100。",
                "reasoning_trace": None,
                "logic_form": None,
                "compiled_sql": "SELECT SUM(balance) FROM loan_balance",
                "sql_text": None,
                "sql_result": '[{"balance": 100}]',
                "execution_trace": json.dumps(
                    {"trace_id": "trace-history-1", "compile_strategy": "semantic"}
                ),
                "plan_payload": None,
                "semantic_check": None,
                "python_result": None,
                "report_payload": None,
                "task_id": "task-existing",
                "turn_id": "turn-refine-2",
                "turn_mode": "refine",
                "task_status": "completed",
                "task_metadata": json.dumps(TASK_METADATA, ensure_ascii=False),
                "created_at": "2026-08-29 10:00:00",
            }
        ]
    )

    async def allow_agent_access(agent_id, current_user):
        return None

    monkeypatch.setattr(main, "require_agent_access", allow_agent_access)
    monkeypatch.setattr(main, "get_management_db", lambda: db)

    response = await main.get_history(
        agent_id=7,
        session_id="session-history-task",
        current_user=ADMIN_USER,
    )

    select_sql, _ = db.queries[0]
    assert all(
        column in select_sql
        for column in (
            "execution_trace",
            "task_id",
            "turn_id",
            "turn_mode",
            "task_status",
            "task_metadata",
        )
    )
    restored = response["history"][0]
    assert restored["task_id"] == "task-existing"
    assert restored["turn_id"] == "turn-refine-2"
    assert restored["turn_mode"] == "refine"
    assert restored["task_status"] == "completed"
    assert restored["trace_id"] == "trace-history-1"
    assert restored["execution_trace"]["compile_strategy"] == "semantic"
    assert restored["reused_artifacts"] == ["semantic_runtime", "schema"]
    assert restored["invalidated_artifacts"] == [
        "logic_form",
        "compiled_sql",
        "sql_result",
    ]
    assert restored["context_invalidated"] is True
