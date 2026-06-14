import pytest

from app.agent.nodes import sql_execute


class FakeDB:
    def __init__(self):
        self.queries = []

    async def execute_query(self, sql: str):
        self.queries.append(sql)
        return [{"value": 1}]


@pytest.mark.asyncio
async def test_sql_execute_uses_selected_datasource(monkeypatch):
    selected_db = FakeDB()

    def fail_global_db():
        raise AssertionError("global business database should not be used")

    async def fake_datasource_db(datasource_id: int):
        assert datasource_id == 42
        return selected_db

    monkeypatch.setattr(sql_execute, "get_business_db", fail_global_db)
    monkeypatch.setattr(sql_execute, "get_datasource_db", fake_datasource_db, raising=False)

    result = await sql_execute.sql_execute_node(
        {"sql_text": "SELECT 1 AS value", "datasource_id": 42}
    )

    assert result["sql_error"] is None
    assert result["sql_result"] == [{"value": 1}]
    assert selected_db.queries == ["SELECT 1 AS value"]


@pytest.mark.asyncio
async def test_sql_execute_blocks_multiple_statement_injection(monkeypatch):
    db = FakeDB()

    async def fake_datasource_db(datasource_id: int):
        return db

    monkeypatch.setattr(sql_execute, "get_datasource_db", fake_datasource_db, raising=False)

    result = await sql_execute.sql_execute_node(
        {"sql_text": "SELECT 1; DROP TABLE users", "datasource_id": 42}
    )

    assert result["sql_result"] == []
    assert result["sql_error"]
    assert "安全拦截" in result["final_answer"]
    assert db.queries == []
