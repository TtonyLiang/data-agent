import pytest

from app.services import metadata_service
from app.services.metadata_service import MetadataService


class FakeBusinessDB:
    def __init__(self):
        self.queries = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        if "information_schema.TABLES" in sql:
            return [{"TABLE_NAME": "orders", "TABLE_COMMENT": "订单表"}]
        if "information_schema.COLUMNS" in sql:
            return [
                {
                    "COLUMN_NAME": "id",
                    "DATA_TYPE": "bigint",
                    "COLUMN_COMMENT": "主键",
                    "COLUMN_KEY": "PRI",
                }
            ]
        if "information_schema.KEY_COLUMN_USAGE" in sql:
            return []
        return []


class FakeManagementDB:
    def __init__(self):
        self.queries = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        if "SELECT id FROM meta_table" in sql:
            return [{"id": 7}]
        if "SELECT id FROM meta_column" in sql:
            return []
        return []


@pytest.mark.asyncio
async def test_collect_schema_uses_selected_datasource(monkeypatch):
    selected_db = FakeBusinessDB()
    management_db = FakeManagementDB()

    async def fake_datasource_db(datasource_id: int):
        assert datasource_id == 42
        return selected_db

    monkeypatch.setattr(metadata_service, "get_datasource_db", fake_datasource_db, raising=False)
    monkeypatch.setattr(metadata_service, "get_management_db", lambda: management_db)

    result = await MetadataService().collect_schema(42)

    assert result == [{"table_name": "orders", "columns": 1}]
    assert any("information_schema.TABLES" in sql for sql, _ in selected_db.queries)
