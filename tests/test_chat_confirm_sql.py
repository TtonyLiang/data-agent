import pytest

from app import main


@pytest.mark.asyncio
async def test_confirm_sql_execution_runs_analysis_and_saves_turn(monkeypatch):
    saved_turns = []

    async def fake_validate_datasource_access(agent_id, datasource_id):
        return None

    async def fake_sql_execute_node(state):
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
        }

    async def fake_planner_node(state):
        return {"plan": {"row_count": 1, "analysis_steps": ["基础统计"]}}

    async def fake_python_generate_node(state):
        return {"python_code": "print('{}')", "python_result": {"status": "generated"}}

    async def fake_python_analyze_node(state):
        return {"python_result": {"status": "success", "metrics": [{"field": "application_count"}]}}

    async def fake_report_generator_node(state):
        return {
            "report_payload": {"title": "申请笔数分析", "summary": "申请笔数为 1。"},
            "final_answer": "申请笔数为 1。",
        }

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
    monkeypatch.setattr(main, "sql_execute_node", fake_sql_execute_node)
    monkeypatch.setattr(main, "planner_node", fake_planner_node)
    monkeypatch.setattr(main, "python_generate_node", fake_python_generate_node)
    monkeypatch.setattr(main, "python_analyze_node", fake_python_analyze_node)
    monkeypatch.setattr(main, "report_generator_node", fake_report_generator_node)
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
        }
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
        await main.confirm_sql_execution({"agent_id": 1})

    assert exc.value.status_code == 400
