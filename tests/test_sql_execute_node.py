import pytest

from app.agent.nodes import sql_execute


class FakeDB:
    def __init__(self):
        self.queries = []

    async def execute_query(self, sql: str):
        self.queries.append(sql)
        return [{"value": 1}]


class FakePermissionService:
    def __init__(self, *, allowed=True, reason=""):
        self.allowed = allowed
        self.reason = reason

    async def validate_sql_access(self, agent_id, datasource_id, sql):
        return self.allowed, self.reason or "OK"

    async def mask_rows(self, agent_id, datasource_id, rows):
        return [{**row, "mobile": "***"} if "mobile" in row else row for row in rows], {
            "mobile": "redact"
        } if rows and "mobile" in rows[0] else {}


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
    assert selected_db.queries == ["SELECT 1 AS value\nLIMIT 1000"]


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


@pytest.mark.asyncio
async def test_sql_execute_applies_table_permission_before_query(monkeypatch):
    db = FakeDB()

    async def fake_datasource_db(datasource_id: int):
        return db

    monkeypatch.setattr(sql_execute, "get_datasource_db", fake_datasource_db, raising=False)
    monkeypatch.setattr(
        sql_execute,
        "get_permission_service",
        lambda: FakePermissionService(allowed=False, reason="无权访问表: secret_table"),
    )

    result = await sql_execute.sql_execute_node(
        {"sql_text": "SELECT * FROM secret_table", "agent_id": 1, "datasource_id": 42}
    )

    assert result["sql_result"] == []
    assert "权限拦截" in result["sql_error"]
    assert db.queries == []


@pytest.mark.asyncio
async def test_sql_execute_masks_result_rows_and_records_trace(monkeypatch):
    class PiiDB(FakeDB):
        async def execute_query(self, sql: str):
            self.queries.append(sql)
            return [{"name": "张三", "mobile": "13800138000"}]

    selected_db = PiiDB()

    async def fake_datasource_db(datasource_id: int):
        return selected_db

    monkeypatch.setattr(sql_execute, "get_datasource_db", fake_datasource_db, raising=False)
    monkeypatch.setattr(sql_execute, "get_permission_service", lambda: FakePermissionService())

    result = await sql_execute.sql_execute_node(
        {
            "sql_text": "SELECT name, mobile FROM loan_application_indicator",
            "agent_id": 1,
            "datasource_id": 42,
            "trace_id": "trace-permission",
        }
    )

    assert result["sql_error"] is None
    assert result["sql_result"] == [{"name": "张三", "mobile": "***"}]
    assert result["execution_trace"]["trace_id"] == "trace-permission"
    assert result["execution_trace"]["permission"]["masked_columns"] == {"mobile": "redact"}


@pytest.mark.asyncio
async def test_sql_execute_passes_bound_logic_form_parameters_to_database(monkeypatch):
    class ParameterizedDB:
        def __init__(self):
            self.calls = []

        async def execute_query(self, sql, params):
            self.calls.append((sql, params))
            return [{"application_count": 1}]

    db = ParameterizedDB()

    async def fake_datasource_db(datasource_id):
        assert datasource_id == 42
        return db

    monkeypatch.setattr(sql_execute, "get_datasource_db", fake_datasource_db)
    monkeypatch.setattr(
        sql_execute,
        "get_permission_service",
        lambda: FakePermissionService(),
    )
    malicious_value = "\\' OR 1=1 #"

    result = await sql_execute.sql_execute_node(
        {
            "compiled_sql": (
                "SELECT COUNT(*) AS application_count FROM loan_application "
                "WHERE product_type = :lf_0"
            ),
            "sql_params": {"lf_0": malicious_value},
            "agent_id": 1,
            "datasource_id": 42,
        }
    )

    assert result["sql_error"] is None
    assert db.calls[0][1] == {"lf_0": malicious_value}
    assert malicious_value not in db.calls[0][0]


@pytest.mark.asyncio
async def test_sql_execute_masks_aliased_physical_column_from_lineage(monkeypatch):
    class AliasDB:
        async def execute_query(self, sql):
            return [{"phone_alias": "13800138000"}]

    class AliasPermissionService(FakePermissionService):
        async def get_result_column_policies(self, agent_id, datasource_id, sql):
            assert (agent_id, datasource_id) == (1, 42)
            assert "mobile AS phone_alias" in sql
            from app.services.permission_service import ColumnPolicy

            return {
                "phone_alias": ColumnPolicy(
                    allowed=True,
                    masking_policy="partial",
                )
            }

        async def mask_rows(
            self,
            agent_id,
            datasource_id,
            rows,
            *,
            result_column_policies=None,
        ):
            policy = result_column_policies["phone_alias"].masking_policy
            return [{"phone_alias": "13*******00"}], {"phone_alias": policy}

    async def fake_datasource_db(_datasource_id):
        return AliasDB()

    monkeypatch.setattr(sql_execute, "get_datasource_db", fake_datasource_db)
    monkeypatch.setattr(
        sql_execute,
        "get_permission_service",
        lambda: AliasPermissionService(),
    )

    result = await sql_execute.sql_execute_node(
        {
            "compiled_sql": "SELECT mobile AS phone_alias FROM loan_application",
            "agent_id": 1,
            "datasource_id": 42,
        }
    )

    assert result["sql_error"] is None
    assert result["sql_result"] == [{"phone_alias": "13*******00"}]
    assert result["execution_trace"]["permission"]["masked_columns"] == {
        "phone_alias": "partial"
    }
