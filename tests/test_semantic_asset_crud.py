import pytest

from app.services import semantic_runtime
from app.services.semantic_runtime import SemanticRuntimeService


class FakeManagementDb:
    def __init__(self):
        self.queries = []
        self.rows = {
            ("semantic_metric", 12, 3): [{"id": 12}],
            ("semantic_rule", 14, 3): [{"id": 14}],
        }

    async def execute_query(self, sql, params=None):
        params = params or {}
        self.queries.append((sql, params))
        if "SELECT id FROM semantic_metric WHERE id" in sql:
            return self.rows.get(("semantic_metric", params["id"], params["domain_id"]), [])
        if "SELECT id FROM semantic_rule WHERE id" in sql:
            return self.rows.get(("semantic_rule", params["id"], params["domain_id"]), [])
        return []

    async def execute_insert(self, sql, params=None):
        self.queries.append((sql, params or {}))
        return 99


@pytest.mark.asyncio
async def test_upsert_asset_updates_existing_asset_by_id(monkeypatch):
    fake_db = FakeManagementDb()
    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: fake_db)

    asset_id = await SemanticRuntimeService().upsert_asset(
        3,
        "metric",
        {
            "id": 12,
            "metric_key": "m1_plus_rate_new",
            "name": "M1+逾期率",
            "formula_sql": "SUM({base}.remaining_principal)",
            "base_table": "loan_account_indicator",
        },
    )

    update_sql, update_params = fake_db.queries[-1]
    assert asset_id == 12
    assert update_sql.startswith("UPDATE semantic_metric SET")
    assert "WHERE id = :id AND domain_id = :domain_id" in update_sql
    assert update_params["id"] == 12
    assert update_params["domain_id"] == 3
    assert update_params["metric_key"] == "m1_plus_rate_new"


@pytest.mark.asyncio
async def test_delete_asset_validates_domain_before_delete(monkeypatch):
    fake_db = FakeManagementDb()
    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: fake_db)

    deleted = await SemanticRuntimeService().delete_asset(3, "rule", 14)

    assert deleted is True
    delete_sql, delete_params = fake_db.queries[-1]
    assert delete_sql == "DELETE FROM semantic_rule WHERE id = :id AND domain_id = :domain_id"
    assert delete_params == {"id": 14, "domain_id": 3}


@pytest.mark.asyncio
async def test_delete_asset_returns_false_when_asset_not_found(monkeypatch):
    fake_db = FakeManagementDb()
    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: fake_db)

    deleted = await SemanticRuntimeService().delete_asset(3, "rule", 999)

    assert deleted is False
    assert len(fake_db.queries) == 1
