import pytest

from app.services import semantic_runtime
from app.services.semantic_runtime import SemanticRuntimeService


class RecordingDB:
    def __init__(self, rows_by_query=None):
        self.rows_by_query = rows_by_query or {}
        self.queries: list[tuple[str, dict | None]] = []
        self.insert_params: dict | None = None

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        for marker, rows in self.rows_by_query.items():
            if marker in sql:
                return rows
        return []

    async def execute_insert(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        self.insert_params = params
        return 42


@pytest.mark.asyncio
async def test_upsert_domain_updates_by_id(monkeypatch):
    db = RecordingDB({"SELECT id FROM semantic_domain WHERE id": [{"id": 9}]})
    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: db)

    domain_id = await SemanticRuntimeService().upsert_domain(
        {
            "id": 9,
            "agent_id": 2,
            "datasource_id": 5,
            "domain_key": "loan_risk",
            "name": "贷款风控",
            "description": "信贷风险分析语义层",
            "status": "active",
        }
    )

    assert domain_id == 9
    update_sql, update_params = next((sql, params) for sql, params in db.queries if sql.startswith("UPDATE semantic_domain"))
    assert "domain_key = :domain_key" in update_sql
    assert update_params["id"] == 9
    assert update_params["name"] == "贷款风控"


@pytest.mark.asyncio
async def test_delete_domain_removes_assets_and_unbinds_agents(monkeypatch):
    db = RecordingDB({"SELECT id FROM semantic_domain WHERE id": [{"id": 9}]})
    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: db)

    deleted = await SemanticRuntimeService().delete_domain(9)

    assert deleted is True
    statements = [sql for sql, _ in db.queries]
    assert "DELETE FROM semantic_concept WHERE domain_id = :id" in statements
    assert "DELETE FROM semantic_metric WHERE domain_id = :id" in statements
    assert "UPDATE agent SET semantic_domain_id = NULL WHERE semantic_domain_id = :id" in statements
    assert statements[-1] == "DELETE FROM semantic_domain WHERE id = :id"


@pytest.mark.asyncio
async def test_list_all_domains_orders_by_id(monkeypatch):
    db = RecordingDB()
    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: db)

    await SemanticRuntimeService().list_all_domains()

    assert db.queries[0][0] == "SELECT * FROM semantic_domain ORDER BY id ASC"
