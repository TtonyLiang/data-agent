import pytest

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
