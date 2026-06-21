import pytest

from app.services import metadata_service
from app.services.metadata_service import MetadataService


class FakeBusinessDB:
    def __init__(self):
        self.queries = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        if "information_schema.TABLES" in sql:
            return [
                {"TABLE_NAME": "customers", "TABLE_COMMENT": "客户表"},
                {"TABLE_NAME": "orders", "TABLE_COMMENT": "订单表"},
                {"TABLE_NAME": "applications", "TABLE_COMMENT": "申请表"},
            ]
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
        self.inserted = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        if "COUNT(mc.id) AS column_count" in sql:
            return [
                {"id": 7, "table_name": "orders", "column_count": 1},
                {"id": 3, "table_name": "applications", "column_count": 2},
            ]
        if "SELECT id, table_name, table_comment FROM meta_table" in sql:
            if params and params.get("tn") == "orders":
                return [{"id": 7, "table_name": "orders", "table_comment": "订单表"}]
            return []
        if "SELECT id FROM meta_table" in sql:
            return [{"id": 7}]
        if "SELECT id FROM meta_column" in sql:
            return []
        return []

    async def execute_insert(self, sql: str, params: dict | None = None):
        self.inserted.append((sql, params))
        self.queries.append((sql, params))
        return 7

    async def execute_transaction(self, statements):
        for sql, params in statements:
            await self.execute_query(sql, params)

    async def execute_in_transaction(self, callback):
        return await callback(FakeTransactionSession(self))


class FakeResult:
    def __init__(self, rows=None, lastrowid=0):
        self._rows = rows or []
        self.lastrowid = lastrowid

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class FakeTransactionSession:
    def __init__(self, db: FakeManagementDB):
        self.db = db

    async def execute(self, sql, params=None):
        sql_text = str(sql)
        rows = await self.db.execute_query(sql_text, params)
        if sql_text.startswith("INSERT INTO meta_table"):
            return FakeResult(lastrowid=7)
        if rows:
            return FakeResult(rows)
        return FakeResult()


class FakeSchemaManagementDB:
    async def execute_query(self, sql: str, params: dict | None = None):
        if "COUNT(mc.id) AS column_count" in sql:
            return [
                {
                    "id": 7,
                    "datasource_id": params["did"],
                    "table_name": "orders",
                    "table_comment": "订单表",
                    "column_count": 1,
                }
            ]
        if "FROM meta_table" in sql:
            return [
                {
                    "id": 7,
                    "datasource_id": params["did"],
                    "table_name": "orders",
                    "table_comment": "订单表",
                }
            ]
        if "FROM meta_column" in sql:
            return [
                {
                    "id": 11,
                    "table_id": params["tid"],
                    "column_name": "amount",
                    "data_type": "decimal",
                    "column_comment": "订单金额",
                    "is_primary_key": 0,
                    "is_foreign_key": 0,
                    "foreign_key_ref": None,
                }
            ]
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

    result = await MetadataService().collect_schema(42, table_names=["orders"])

    assert result == [
        {"table_name": "orders", "table_comment": "订单表", "table_id": 7, "columns": 1}
    ]
    assert any("information_schema.TABLES" in sql for sql, _ in selected_db.queries)
    assert all(
        params is None or params.get("tn") != "customers" for _, params in selected_db.queries
    )


@pytest.mark.asyncio
async def test_list_remote_tables_returns_catalog_without_collecting_columns(monkeypatch):
    selected_db = FakeBusinessDB()
    management_db = FakeManagementDB()

    async def fake_datasource_db(datasource_id: int):
        assert datasource_id == 42
        return selected_db

    monkeypatch.setattr(metadata_service, "get_datasource_db", fake_datasource_db, raising=False)
    monkeypatch.setattr(metadata_service, "get_management_db", lambda: management_db)

    result = await MetadataService().list_remote_tables(42)

    assert result == [
        {
            "table_name": "applications",
            "table_comment": "申请表",
            "collected": True,
            "table_id": 3,
            "column_count": 2,
        },
        {
            "table_name": "orders",
            "table_comment": "订单表",
            "collected": True,
            "table_id": 7,
            "column_count": 1,
        },
        {
            "table_name": "customers",
            "table_comment": "客户表",
            "collected": False,
            "table_id": None,
            "column_count": 0,
        },
    ]
    assert not any("information_schema.COLUMNS" in sql for sql, _ in selected_db.queries)


@pytest.mark.asyncio
async def test_get_schema_returns_tables_with_columns(monkeypatch):
    monkeypatch.setattr(metadata_service, "get_management_db", lambda: FakeSchemaManagementDB())

    result = await MetadataService().get_schema(42)

    assert result == [
        {
            "id": 7,
            "datasource_id": 42,
            "table_name": "orders",
            "table_comment": "订单表",
            "columns": [
                {
                    "id": 11,
                    "table_id": 7,
                    "column_name": "amount",
                    "data_type": "decimal",
                    "column_comment": "订单金额",
                    "is_primary_key": False,
                    "is_foreign_key": False,
                    "foreign_key_ref": None,
                }
            ],
        }
    ]


@pytest.mark.asyncio
async def test_get_table_detail_validates_datasource_and_returns_columns(monkeypatch):
    monkeypatch.setattr(metadata_service, "get_management_db", lambda: FakeSchemaManagementDB())

    result = await MetadataService().get_table_detail(42, 7)

    assert result == {
        "id": 7,
        "datasource_id": 42,
        "table_name": "orders",
        "table_comment": "订单表",
        "columns": [
            {
                "id": 11,
                "table_id": 7,
                "column_name": "amount",
                "data_type": "decimal",
                "column_comment": "订单金额",
                "is_primary_key": False,
                "is_foreign_key": False,
                "foreign_key_ref": None,
            }
        ],
    }


@pytest.mark.asyncio
async def test_uncollect_schema_removes_selected_table_metadata(monkeypatch):
    management_db = FakeManagementDB()
    monkeypatch.setattr(metadata_service, "get_management_db", lambda: management_db)

    result = await MetadataService().uncollect_schema(42, ["orders", "missing_table"])

    assert result == [{"table_name": "orders", "table_comment": "订单表", "table_id": 7}]
    assert any(
        sql == "DELETE FROM meta_column WHERE table_id = :tid" for sql, _ in management_db.queries
    )
    assert any(
        sql == "DELETE FROM meta_table WHERE datasource_id = :did AND id = :tid"
        for sql, _ in management_db.queries
    )
