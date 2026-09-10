import pytest
from fastapi import HTTPException

from app.api import datasource as datasource_api
from app.models.permission import (
    ColumnPermissionRule,
    DatasourcePermissionConfig,
    DatasourcePermissionReplace,
    DomainDatasourcePermissionConfig,
    TablePermissionRule,
)


class FakePermissionService:
    def __init__(self):
        self.replaced = None

    async def get_permission_configuration(self, agent_id, datasource_id):
        return DatasourcePermissionConfig(
            agent_id=agent_id,
            datasource_id=datasource_id,
            table_permissions=[TablePermissionRule(table_name="loan_application", allowed=True)],
            column_permissions=[
                ColumnPermissionRule(
                    table_name="loan_application",
                    column_name="mobile",
                    masking_policy="partial",
                )
            ],
        )

    async def replace_permission_configuration(self, agent_id, datasource_id, request):
        self.replaced = (agent_id, datasource_id, request)
        return DatasourcePermissionConfig(
            agent_id=agent_id,
            datasource_id=datasource_id,
            **request.model_dump(),
        )

    async def get_domain_permission_configuration(self, domain_id, datasource_id):
        return DomainDatasourcePermissionConfig(
            domain_id=domain_id,
            datasource_id=datasource_id,
            table_permissions=[TablePermissionRule(table_name="loan_application", allowed=True)],
            column_permissions=[
                ColumnPermissionRule(
                    table_name="loan_application",
                    column_name="mobile",
                    masking_policy="partial",
                )
            ],
        )

    async def replace_domain_permission_configuration(self, domain_id, datasource_id, request):
        self.replaced = (domain_id, datasource_id, request)
        return DomainDatasourcePermissionConfig(
            domain_id=domain_id,
            datasource_id=datasource_id,
            **request.model_dump(),
        )


class FakeManagementDB:
    def __init__(self, *, agent_exists=True):
        self.agent_exists = agent_exists

    async def execute_query(self, sql, params=None):
        if sql.startswith("SELECT id FROM agent"):
            return [{"id": params["agent_id"]}] if self.agent_exists else []
        raise AssertionError(f"unexpected query: {sql}")


class FakeDatasourceService:
    def __init__(self, *, datasource_exists=True, bound=True):
        self.datasource_exists = datasource_exists
        self.bound = bound

    async def get(self, datasource_id):
        return {"id": datasource_id} if self.datasource_exists else None

    async def belongs_to_agent(self, datasource_id, agent_id):
        return self.bound


class FakeMetadataService:
    async def get_schema(self, datasource_id):
        return [
            {
                "id": 11,
                "datasource_id": datasource_id,
                "table_name": "loan_application",
                "columns": [
                    {"id": 21, "column_name": "application_id"},
                    {"id": 22, "column_name": "mobile"},
                ],
            }
        ]


def configure_permission_scope(
    monkeypatch, *, agent_exists=True, datasource_exists=True, bound=True
):
    monkeypatch.setattr(
        datasource_api,
        "get_management_db",
        lambda: FakeManagementDB(agent_exists=agent_exists),
    )
    monkeypatch.setattr(
        datasource_api,
        "get_datasource_service",
        lambda: FakeDatasourceService(
            datasource_exists=datasource_exists,
            bound=bound,
        ),
    )
    monkeypatch.setattr(datasource_api, "get_metadata_service", lambda: FakeMetadataService())


@pytest.mark.asyncio
async def test_datasource_permission_api_reads_and_replaces_rules(monkeypatch):
    service = FakePermissionService()
    monkeypatch.setattr(datasource_api, "get_permission_service", lambda: service)
    configure_permission_scope(monkeypatch)

    fetched = await datasource_api.get_datasource_permissions(7, 4)
    request = DatasourcePermissionReplace(
        table_permissions=[TablePermissionRule(table_name="loan_application", allowed=True)],
        column_permissions=[
            ColumnPermissionRule(
                table_name="loan_application",
                column_name="mobile",
                allowed=False,
            )
        ],
    )
    updated = await datasource_api.replace_datasource_permissions(7, 4, request)

    assert fetched["permissions"]["agent_id"] == 4
    assert fetched["permissions"]["column_permissions"][0]["masking_policy"] == "partial"
    assert service.replaced == (4, 7, request)
    assert updated["permissions"]["column_permissions"][0]["allowed"] is False
    assert updated["message"] == "访问权限已保存"


@pytest.mark.asyncio
async def test_domain_permission_api_reads_and_replaces_rules(monkeypatch):
    service = FakePermissionService()

    class Domain:
        datasource_id = 7

    class SemanticService:
        async def get_domain(self, domain_id):
            return Domain() if domain_id == 4 else None

    monkeypatch.setattr(datasource_api, "get_permission_service", lambda: service)
    monkeypatch.setattr(datasource_api, "get_semantic_runtime_service", lambda: SemanticService())
    configure_permission_scope(monkeypatch)

    fetched = await datasource_api.get_domain_datasource_permissions(7, 4)
    request = DatasourcePermissionReplace(
        table_permissions=[TablePermissionRule(table_name="loan_application", allowed=True)],
        column_permissions=[
            ColumnPermissionRule(
                table_name="loan_application",
                column_name="mobile",
                allowed=False,
                masking_policy="redact",
            )
        ],
    )
    updated = await datasource_api.replace_domain_datasource_permissions(7, 4, request)

    assert fetched["permissions"]["domain_id"] == 4
    assert fetched["permissions"]["column_permissions"][0]["masking_policy"] == "partial"
    assert service.replaced == (4, 7, request)
    assert updated["permissions"]["column_permissions"][0]["allowed"] is False


@pytest.mark.asyncio
async def test_domain_permission_api_rejects_unbound_datasource(monkeypatch):
    class Domain:
        datasource_id = 8

    class SemanticService:
        async def get_domain(self, _domain_id):
            return Domain()

    monkeypatch.setattr(datasource_api, "get_semantic_runtime_service", lambda: SemanticService())
    configure_permission_scope(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        await datasource_api.get_domain_datasource_permissions(7, 4)

    assert exc_info.value.status_code == 400
    assert "未绑定当前数据源" in str(exc_info.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope_options", "status_code", "detail"),
    [
        ({"agent_exists": False}, 404, "智能体不存在"),
        ({"datasource_exists": False}, 404, "数据源不存在"),
        ({"bound": False}, 400, "尚未绑定"),
    ],
)
async def test_permission_api_rejects_invalid_agent_datasource_scope(
    monkeypatch,
    scope_options,
    status_code,
    detail,
):
    configure_permission_scope(monkeypatch, **scope_options)

    with pytest.raises(HTTPException) as exc_info:
        await datasource_api.get_datasource_permissions(7, 4)

    assert exc_info.value.status_code == status_code
    assert detail in str(exc_info.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        (
            DatasourcePermissionReplace(
                table_permissions=[
                    TablePermissionRule(table_name="missing_table", allowed=True)
                ]
            ),
            "表不存在或尚未采集",
        ),
        (
            DatasourcePermissionReplace(
                column_permissions=[
                    ColumnPermissionRule(
                        table_name="loan_application",
                        column_name="missing_column",
                    )
                ]
            ),
            "字段不存在或尚未采集",
        ),
    ],
)
async def test_permission_api_rejects_unknown_tables_and_columns(
    monkeypatch,
    payload,
    detail,
):
    configure_permission_scope(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        await datasource_api.replace_datasource_permissions(7, 4, payload)

    assert exc_info.value.status_code == 400
    assert detail in str(exc_info.value.detail)
