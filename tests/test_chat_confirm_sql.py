import pytest

from app import main
from app.models.user import PublicUser

ADMIN_USER = PublicUser(id=1, username="admin", role="admin", status="active")


@pytest.mark.asyncio
async def test_confirm_sql_execution_runs_analysis_and_saves_turn(monkeypatch):
    saved_turns = []
    checkpoint = {
        "task_id": "task-confirm",
        "task_status": "awaiting_input",
        "compiled_sql": "SELECT 1 AS application_count",
        "human_confirmation": {"status": "pending", "sql": "SELECT 1 AS application_count"},
    }

    async def fake_validate_datasource_access(agent_id, datasource_id):
        return None

    class FakeGraph:
        async def ainvoke(self, state, config=None):
            assert state["compiled_sql"] == "SELECT 1 AS application_count"
            assert config == {"recursion_limit": main.GRAPH_RECURSION_LIMIT}
            return {
            "compiled_sql": "SELECT 1 AS application_count LIMIT 1000",
            "sql_text": "SELECT 1 AS application_count LIMIT 1000",
            "sql_result": [{"application_count": 1}],
            "sql_error": None,
            "execution_trace": {
                **state["execution_trace"],
                "sql_execution": {"row_count": 1, "duration_ms": 3, "slow_query": False},
            },
            "final_answer": "申请笔数为 1。",
            "plan": {"row_count": 1, "analysis_steps": ["基础统计"]},
            "python_code": "print('{}')",
            "python_result": {
                "status": "success",
                "metrics": [{"field": "application_count"}],
            },
            "report_payload": {"title": "申请笔数分析", "summary": "申请笔数为 1。"},
            "task_status": "completed",
            }

    async def fake_load_history(agent_id, session_id, limit=5, **kwargs):
        return []

    async def fake_prepare_chat_state(**kwargs):
        return {
            "question": "申请笔数是多少",
            "agent_id": kwargs["agent_id"],
            "user_id": kwargs["user"].id,
            "datasource_id": kwargs["datasource_id"],
            "session_id": kwargs["session_id"],
            "trace_id": kwargs["trace_id"],
            "task_id": "task-confirm",
            "turn_id": "turn-confirm",
            "turn_mode": "retry",
            "task_status": "running",
            "context_invalidated": False,
            "compiled_sql": checkpoint["compiled_sql"],
            "human_confirmation": checkpoint["human_confirmation"],
            "execution_trace": {"trace_id": kwargs["trace_id"]},
            "chat_history": [],
        }

    class FakeCheckpointService:
        async def load(self, user_id, agent_id, session_id):
            return checkpoint

    async def fake_save_turn(agent_id, session_id, question, answer, sql, sql_result, **kwargs):
        saved_turns.append(
            {
                "agent_id": agent_id,
                "session_id": session_id,
                "question": question,
                "answer": answer,
                "sql": sql,
                "sql_result": sql_result,
                "report_payload": kwargs.get("report_payload"),
            }
        )

    monkeypatch.setattr(main, "validate_datasource_access", fake_validate_datasource_access)
    monkeypatch.setattr(main, "load_history", fake_load_history)
    monkeypatch.setattr(main, "prepare_chat_state", fake_prepare_chat_state)
    monkeypatch.setattr(main, "get_graph", lambda: FakeGraph())
    monkeypatch.setattr(main, "get_task_checkpoint_service", lambda: FakeCheckpointService())
    monkeypatch.setattr(main, "save_turn", fake_save_turn)

    response = await main.confirm_sql_execution(
        {
            "question": "确认执行 SQL",
            "agent_id": 1,
            "datasource_id": 2,
            "session_id": "session-confirm",
            "trace_id": "trace-confirm",
            "sql": "SELECT 1 AS application_count",
            "logic_form": {"metrics": ["application_count"]},
        },
        current_user=ADMIN_USER,
    )

    assert response["human_confirmation"]["status"] == "confirmed"
    assert response["sql"] == "SELECT 1 AS application_count LIMIT 1000"
    assert response["sql_result"] == [{"application_count": 1}]
    assert response["report_payload"]["title"] == "申请笔数分析"
    assert response["execution_trace"]["trace_id"] == "trace-confirm"
    assert response["execution_trace"]["human_confirmation"]["status"] == "confirmed"
    assert saved_turns[0]["report_payload"]["title"] == "申请笔数分析"


@pytest.mark.asyncio
async def test_confirm_sql_execution_requires_sql():
    with pytest.raises(main.HTTPException) as exc:
        await main.confirm_sql_execution({"agent_id": 1}, current_user=ADMIN_USER)

    assert exc.value.status_code == 400


def test_confirm_sql_rejects_request_sql_that_differs_from_checkpoint():
    checkpoint = {
        "task_id": "task-confirm",
        "task_status": "awaiting_input",
        "compiled_sql": "SELECT 1 AS application_count",
        "human_confirmation": {"status": "pending"},
    }

    with pytest.raises(main.HTTPException) as exc:
        main.resolve_pending_confirmation_sql(
            checkpoint,
            {"task_id": "task-confirm", "sql": "SELECT secret FROM app_user"},
        )

    assert exc.value.status_code == 409
    assert "checkpoint" in exc.value.detail
