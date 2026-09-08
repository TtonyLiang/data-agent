import pytest

from app.models.permission import (
    ColumnPermissionRule,
    DatasourcePermissionReplace,
    TablePermissionRule,
)
from app.services import permission_service
from app.services.permission_service import PermissionService, mask_value
from app.utils.sql_validator import extract_table_references


class FakePermissionDB:
    async def execute_query(self, sql: str, params: dict | None = None):
        if "FROM agent_table_permission" in sql:
            return [
                {"table_name": "loan_application_indicator", "allowed": 1},
                {"table_name": "customer_private_profile", "allowed": 0},
            ]
        if "FROM agent_column_permission" in sql:
            return [
                {
                    "table_name": "loan_application_indicator",
                    "column_name": "mobile",
                    "allowed": 1,
                    "masking_policy": "partial",
                },
                {
                    "table_name": "loan_application_indicator",
                    "column_name": "id_card",
                    "allowed": 0,
                    "masking_policy": "redact",
                },
            ]
        return []


class DeniedColumnDB:
    async def execute_query(self, sql: str, params: dict | None = None):
        if "FROM agent_table_permission" in sql:
            return [{"table_name": "loan_application", "allowed": 1}]
        if "FROM agent_column_permission" in sql:
            return [
                {
                    "table_name": "loan_application",
                    "column_name": "mobile",
                    "allowed": 0,
                    "masking_policy": "redact",
                }
            ]
        return []


class MaskedColumnDB:
    async def execute_query(self, sql: str, params: dict | None = None):
        if "FROM agent_table_permission" in sql:
            return [{"table_name": "loan_application", "allowed": 1}]
        if "FROM agent_column_permission" in sql:
            return [
                {
                    "table_name": "loan_application",
                    "column_name": "mobile",
                    "allowed": 1,
                    "masking_policy": "partial",
                }
            ]
        return []


@pytest.mark.asyncio
async def test_permission_service_filters_schema_and_masks_rows(monkeypatch):
    monkeypatch.setattr(permission_service, "get_management_db", lambda: FakePermissionDB())

    schema = [
        {
            "table_name": "loan_application_indicator",
            "columns": [
                {"column_name": "application_id"},
                {"column_name": "mobile"},
                {"column_name": "id_card"},
            ],
        },
        {"table_name": "customer_private_profile", "columns": [{"column_name": "name"}]},
    ]

    service = PermissionService()
    filtered = await service.filter_schema(1, 2, schema)
    assert [table["table_name"] for table in filtered] == ["loan_application_indicator"]
    assert [column["column_name"] for column in filtered[0]["columns"]] == [
        "application_id",
        "mobile",
    ]
    assert filtered[0]["columns"][1]["masking_policy"] == "partial"

    ok, reason = await service.validate_sql_access(
        1,
        2,
        "SELECT * FROM customer_private_profile LIMIT 10",
    )
    assert not ok
    assert "无权访问表" in reason

    rows, applied = await service.mask_rows(
        1,
        2,
        [{"mobile": "13800138000", "application_id": 1, "id_card": "123456"}],
    )
    assert rows[0]["mobile"] == "13*******00"
    assert rows[0]["id_card"] == "***"
    assert applied == {"mobile": "partial", "id_card": "redact"}


def test_extract_table_references_and_mask_value():
    assert extract_table_references(
        "SELECT t0.region FROM loan_application_indicator t0 "
        "JOIN loan_account_indicator a ON a.id=t0.id"
    ) == ["loan_application_indicator", "loan_account_indicator"]
    assert mask_value("abcdef", "partial") == "ab**ef"
    assert len(mask_value("abcdef", "hash")) == 12


@pytest.mark.asyncio
async def test_permission_service_returns_explicit_configuration(monkeypatch):
    monkeypatch.setattr(permission_service, "get_management_db", lambda: FakePermissionDB())

    configuration = await PermissionService().get_permission_configuration(1, 2)

    assert configuration.agent_id == 1
    assert configuration.datasource_id == 2
    assert [rule.table_name for rule in configuration.table_permissions] == [
        "loan_application_indicator",
        "customer_private_profile",
    ]
    assert configuration.column_permissions[0].masking_policy == "partial"
    assert configuration.column_permissions[1].allowed is False


@pytest.mark.asyncio
async def test_permission_service_replaces_configuration_in_one_transaction(monkeypatch):
    class RecordingPermissionDB:
        def __init__(self):
            self.statements = []

        async def execute_transaction(self, statements):
            self.statements = statements

    db = RecordingPermissionDB()
    monkeypatch.setattr(permission_service, "get_management_db", lambda: db)
    request = DatasourcePermissionReplace(
        table_permissions=[
            TablePermissionRule(table_name="loan_account", allowed=False),
            TablePermissionRule(table_name="loan_application", allowed=True),
        ],
        column_permissions=[
            ColumnPermissionRule(
                table_name="loan_application",
                column_name="mobile",
                allowed=True,
                masking_policy="partial",
            )
        ],
    )

    configuration = await PermissionService().replace_permission_configuration(4, 7, request)

    assert len(db.statements) == 5
    assert db.statements[0][0].startswith("DELETE FROM agent_table_permission")
    assert db.statements[1][0].startswith("DELETE FROM agent_column_permission")
    assert db.statements[2][1] == {
        "aid": 4,
        "did": 7,
        "table_name": "loan_account",
        "allowed": 0,
    }
    assert db.statements[-1][1]["masking_policy"] == "partial"
    assert configuration.table_permissions[1].table_name == "loan_application"
    assert configuration.column_permissions[0].column_name == "mobile"


def test_empty_table_configuration_is_fail_closed_unless_compatibility_is_explicit():
    request = DatasourcePermissionReplace()

    assert request.table_permissions == []
    assert PermissionService.table_allowed("new_table", {}) is False
    assert (
        PermissionService.table_allowed(
            "new_table", {}, enforce_table_allowlist=False
        )
        is True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT mobile AS phone_alias FROM loan_application",
        "SELECT COUNT(DISTINCT mobile) AS customer_count FROM loan_application",
        "SELECT t.mobile AS phone_alias FROM loan_application t",
    ],
)
async def test_denied_physical_column_cannot_hide_behind_alias_or_aggregate(
    monkeypatch, sql
):
    monkeypatch.setattr(permission_service, "get_management_db", lambda: DeniedColumnDB())

    allowed, reason = await PermissionService().validate_sql_access(1, 2, sql)

    assert allowed is False
    assert "loan_application.mobile" in reason


@pytest.mark.asyncio
async def test_row_count_does_not_imply_access_to_a_denied_column(monkeypatch):
    monkeypatch.setattr(permission_service, "get_management_db", lambda: DeniedColumnDB())

    allowed, reason = await PermissionService().validate_sql_access(
        1, 2, "SELECT COUNT(*) AS application_count FROM loan_application"
    )

    assert allowed is True
    assert reason == "OK"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sql", "output_column"),
    [
        ("SELECT mobile AS phone_alias FROM loan_application", "phone_alias"),
        (
            "SELECT CONCAT(mobile, '-verified') AS phone_label FROM loan_application",
            "phone_label",
        ),
        (
            "SELECT COUNT(DISTINCT mobile) AS unique_mobile_count FROM loan_application",
            "unique_mobile_count",
        ),
    ],
)
async def test_masked_physical_column_policy_follows_output_alias(
    monkeypatch, sql, output_column
):
    monkeypatch.setattr(permission_service, "get_management_db", lambda: MaskedColumnDB())
    service = PermissionService()

    allowed, reason = await service.validate_sql_access(1, 2, sql)
    output_policies = await service.get_result_column_policies(1, 2, sql)
    rows, applied = await service.mask_rows(
        1,
        2,
        [{output_column: "13800138000"}],
        result_column_policies=output_policies,
    )

    assert allowed is True
    assert reason == "OK"
    assert output_policies[output_column].masking_policy == "partial"
    assert rows[0][output_column] == "13*******00"
    assert applied == {output_column: "partial"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT CONCAT(mobile, '-verified') FROM loan_application",
        "SELECT mobile + application_id FROM loan_application",
        "SELECT mobile phone_alias FROM loan_application",
        (
            "SELECT q.phone_alias FROM "
            "(SELECT mobile AS phone_alias FROM loan_application) q"
        ),
    ],
)
async def test_unresolved_masked_column_expression_is_fail_closed(monkeypatch, sql):
    monkeypatch.setattr(permission_service, "get_management_db", lambda: MaskedColumnDB())

    allowed, reason = await PermissionService().validate_sql_access(1, 2, sql)

    assert allowed is False
    assert "无法安全解析脱敏字段血缘" in reason


@pytest.mark.asyncio
async def test_empty_table_rules_require_explicit_compatibility_mode(monkeypatch):
    class EmptyPermissionDB:
        async def execute_query(self, sql: str, params: dict | None = None):
            return []

    monkeypatch.setattr(
        permission_service, "get_management_db", lambda: EmptyPermissionDB()
    )
    service = PermissionService()

    denied, reason = await service.validate_sql_access(
        1, 2, "SELECT 1 FROM loan_application"
    )
    compatible, compatibility_reason = await service.validate_sql_access(
        1,
        2,
        "SELECT 1 FROM loan_application",
        enforce_table_allowlist=False,
    )

    assert denied is False
    assert "未配置表白名单" in reason
    assert compatible is True
    assert compatibility_reason == "OK"

    schema = [{"table_name": "loan_application", "columns": []}]
    assert await service.filter_schema(1, 2, schema) == []
    assert await service.filter_schema(
        1, 2, schema, enforce_table_allowlist=False
    ) == schema
