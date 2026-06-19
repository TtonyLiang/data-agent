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
    update_sql, update_params = next(
        (sql, params) for sql, params in db.queries if sql.startswith("UPDATE semantic_domain")
    )
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


@pytest.mark.asyncio
async def test_snapshot_diff_reports_asset_changes(monkeypatch):
    service = SemanticRuntimeService()

    async def fake_get_snapshot(domain_id, snapshot_id):
        return {
            "id": snapshot_id,
            "name": "调整前",
            "description": "",
            "created_at": "2026-06-18",
            "snapshot_json": {
                "domain": {
                    "id": domain_id,
                    "agent_id": 1,
                    "datasource_id": 1,
                    "domain_key": "loan_risk",
                    "name": "贷款风控",
                    "description": "old",
                    "status": "active",
                },
                "assets": {
                    "metric": [
                        {
                            "id": 1,
                            "domain_id": domain_id,
                            "metric_key": "application_count",
                            "name": "申请笔数",
                        }
                    ],
                    "mapping": [],
                    "concept": [],
                    "relation": [],
                    "rule": [],
                    "template": [],
                },
            },
        }

    async def fake_export_domain_bundle(domain_id):
        return {
            "domain": {
                "id": domain_id,
                "agent_id": 1,
                "datasource_id": 1,
                "domain_key": "loan_risk",
                "name": "贷款风控",
                "description": "new",
                "status": "active",
            },
            "assets": {
                "metric": [
                    {
                        "id": 1,
                        "domain_id": domain_id,
                        "metric_key": "application_count",
                        "name": "申请数量",
                    },
                    {
                        "id": 2,
                        "domain_id": domain_id,
                        "metric_key": "approval_rate",
                        "name": "审批通过率",
                    },
                ],
                "mapping": [],
                "concept": [],
                "relation": [],
                "rule": [],
                "template": [],
            },
        }

    monkeypatch.setattr(service, "get_snapshot", fake_get_snapshot)
    monkeypatch.setattr(service, "export_domain_bundle", fake_export_domain_bundle)

    diff = await service.diff_snapshot(9, 3)

    assert diff["summary"]["domain_changed"] is True
    assert diff["summary"]["added"] == 1
    assert diff["summary"]["changed"] == 1
    assert diff["assets"]["metric"]["added"] == ["approval_rate"]
    assert diff["assets"]["metric"]["changed"][0]["key"] == "application_count"


@pytest.mark.asyncio
async def test_rollback_snapshot_replaces_current_assets(monkeypatch):
    service = SemanticRuntimeService()
    db = RecordingDB(
        {
            "SELECT * FROM semantic_domain WHERE id": [
                {"id": 9, "agent_id": 1, "domain_key": "loan_risk", "name": "贷款风控"}
            ]
        }
    )
    imported = {}

    async def fake_get_snapshot(domain_id, snapshot_id):
        return {
            "id": snapshot_id,
            "snapshot_json": {
                "domain": {
                    "datasource_id": 5,
                    "name": "贷款风控快照",
                    "description": "snapshot",
                    "status": "active",
                },
                "assets": {"metric": [{"metric_key": "application_count", "name": "申请笔数"}]},
                "asset_counts": {"metric": 1},
            },
        }

    async def fake_import_assets(domain_id, assets):
        imported["domain_id"] = domain_id
        imported["assets"] = assets

    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: db)
    monkeypatch.setattr(service, "get_snapshot", fake_get_snapshot)
    monkeypatch.setattr(service, "_import_assets", fake_import_assets)

    result = await service.rollback_snapshot(9, 3)

    statements = [sql for sql, _ in db.queries]
    assert any(sql.startswith("UPDATE semantic_domain") for sql in statements)
    assert any("DELETE FROM semantic_metric" in sql for sql in statements)
    assert imported["domain_id"] == 9
    assert imported["assets"]["metric"][0]["metric_key"] == "application_count"
    assert result["message"] == "语义层已回滚到快照"
