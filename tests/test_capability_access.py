import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import capability_access as capability_api
from app.db.capability_access_schema import CAPABILITY_ACCESS_TABLE_STATEMENTS
from app.main import app
from app.models.capability_access import (
    CapabilityClientCreatePayload,
    CapabilityInvokePayload,
)
from app.models.knowledge import LogicFilter, LogicForm
from app.services import capability_access_service as service_module
from app.services.capability_access_service import (
    CapabilityAccessService,
    CapabilityAuthenticationError,
    CapabilityAuthorizationError,
    verify_capability_secret,
)


class FakeDB:
    def __init__(self, query_rows=None):
        self.query_rows = list(query_rows or [])
        self.inserts = []
        self.queries = []

    async def execute_query(self, sql, params=None):
        self.queries.append((sql, params or {}))
        if self.query_rows:
            return self.query_rows.pop(0)
        return []

    async def execute_insert(self, sql, params=None):
        self.inserts.append((sql, params or {}))
        return 11 if "capability_client" in sql else 31


@pytest.mark.asyncio
async def test_client_creation_returns_secret_once_and_stores_only_hash(monkeypatch):
    db = FakeDB()
    service = CapabilityAccessService()
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    monkeypatch.setattr(
        service,
        "get_client",
        AsyncMock(
            return_value={
                "id": 11,
                "client_key": "generated",
                "name": "外部审批助手",
                "status": "active",
            }
        ),
    )

    credential = await service.create_client(
        CapabilityClientCreatePayload(name="外部审批助手"),
        created_by=7,
    )

    stored = db.inserts[0][1]
    assert credential["client_secret"] not in stored.values()
    assert stored["secret_hash"].startswith("sha256:")
    assert verify_capability_secret(credential["client_secret"], stored["secret_hash"])
    assert "secret_hash" not in credential["client"]
    assert credential["secret_returned_once"] is True


@pytest.mark.asyncio
async def test_client_authentication_rejects_wrong_secret_and_updates_last_used(monkeypatch):
    secret = "high-entropy-secret"
    row = {
        "id": 8,
        "client_key": "cap_client",
        "name": "外部助手",
        "status": "active",
        "secret_hash": service_module.hash_capability_secret(secret),
    }
    db = FakeDB(query_rows=[[row], [row]])
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()

    client = await service.authenticate_client("cap_client", secret)
    with pytest.raises(CapabilityAuthenticationError, match="凭据无效"):
        await service.authenticate_client("cap_client", "wrong")

    assert "secret_hash" not in client
    assert "last_used_at" in db.queries[1][0]


@pytest.mark.asyncio
async def test_external_invoke_uses_grant_adapter_and_audits_summary_only(monkeypatch):
    grant = {
        "id": 19,
        "client_id": 8,
        "domain_id": 9,
        "capability_key": "query_loan_application",
        "execution_agent_id": 17,
        "status": "active",
    }
    db = FakeDB(query_rows=[[grant]])
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()
    runtime = SimpleNamespace(domain=SimpleNamespace(agent_id=17, datasource_id=23))
    load_context = AsyncMock(
        return_value=(
            {
                "model_release": {"id": 12, "version": 3},
                "semantic_snapshot": {"id": 8},
                "ontology_release": {"id": 4},
                "release": {"id": 4},
            },
            runtime,
        )
    )
    monkeypatch.setattr(service, "_load_execution_context", load_context)
    invoke = AsyncMock(
        return_value={
            "execution": {"status": "succeeded", "executed": True, "attempted": True},
            "sql_result": [{"channel": "APP", "application_count": 8}],
            "sql_error": None,
            "execution_trace": {
                "trace_id": "trc_external",
                "target_object": "LoanApplication",
                "model_release": {"id": 12, "version": 3},
                "semantic_snapshot": {"id": 8},
                "ontology_release": {"id": 4, "version": 2},
            },
        }
    )
    monkeypatch.setattr(service_module, "invoke_ontology_tool", invoke)
    monkeypatch.setattr(service_module, "get_ontology_service", lambda: object())
    payload = CapabilityInvokePayload(
        domain_id=9,
        logic_form=LogicForm(
            metrics=["application_count"],
            dimensions=["channel"],
            filters=[LogicFilter(field="customer_name", operator="=", value="张三")],
        ),
    )

    response = await service.invoke(
        {"id": 8, "client_key": "cap_client", "name": "外部助手"},
        "query_loan_application",
        payload,
    )

    load_context.assert_awaited_once_with(
        9,
        17,
        "query_loan_application",
        model_release_id=None,
    )
    invoke.assert_awaited_once()
    assert response["trace_id"] == "trc_external"
    assert response["result"]["sql_result"][0]["channel"] == "APP"
    audit_params = db.inserts[0][1]
    request_summary = json.loads(audit_params["request_summary"])
    result_summary = json.loads(audit_params["result_summary"])
    assert request_summary["filters"] == [
        {"field": "customer_name", "operator": "="}
    ]
    assert "张三" not in audit_params["request_summary"]
    assert result_summary["row_count"] == 1
    assert result_summary["columns"] == ["channel", "application_count"]
    assert "APP" not in audit_params["result_summary"]
    assert audit_params["ontology_release_id"] == 4
    assert audit_params["model_release_id"] == 12
    assert audit_params["semantic_snapshot_id"] == 8
    assert audit_params["status"] == "succeeded"


@pytest.mark.asyncio
async def test_external_invoke_blocks_missing_grant_and_records_trace(monkeypatch):
    db = FakeDB(query_rows=[[]])
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()
    payload = CapabilityInvokePayload(
        domain_id=9,
        logic_form=LogicForm(metrics=["application_count"]),
    )

    with pytest.raises(CapabilityAuthorizationError) as exc_info:
        await service.invoke(
            {"id": 8, "client_key": "cap_client", "name": "外部助手"},
            "query_loan_application",
            payload,
        )

    assert exc_info.value.trace_id.startswith("trc_")
    assert db.inserts[0][1]["status"] == "permission_blocked"
    assert db.inserts[0][1]["grant_id"] is None


@pytest.mark.asyncio
async def test_api_dependency_maps_invalid_capability_credentials_to_401(monkeypatch):
    service = AsyncMock()
    service.authenticate_client.side_effect = CapabilityAuthenticationError("凭据无效")
    monkeypatch.setattr(capability_api, "get_capability_access_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await capability_api.get_capability_client("bad-key", "bad-secret")

    assert exc_info.value.status_code == 401


def test_capability_access_schema_and_routes_are_registered():
    ddl = "\n".join(CAPABILITY_ACCESS_TABLE_STATEMENTS)
    assert "CREATE TABLE IF NOT EXISTS capability_client" in ddl
    assert "secret_hash" in ddl
    assert "client_secret" not in ddl
    assert "CREATE TABLE IF NOT EXISTS capability_grant" in ddl
    assert "execution_agent_id BIGINT NOT NULL" in ddl
    assert "CREATE TABLE IF NOT EXISTS capability_invocation_audit" in ddl
    assert "model_release_id BIGINT" in ddl
    assert "semantic_snapshot_id BIGINT" in ddl
    assert "request_summary JSON" in ddl
    assert "result_summary JSON" in ddl

    paths = {route.path for route in app.routes}
    assert "/api/capability-clients" in paths
    assert "/api/capability-clients/{client_id}/grants" in paths
    assert "/api/capability-invocations" in paths
    assert "/api/v1/capabilities/{capability_key}:invoke" in paths


@pytest.mark.asyncio
async def test_execution_context_requires_active_unified_model(monkeypatch):
    service = CapabilityAccessService()
    runtime_service = AsyncMock()
    runtime_service.get_domain.return_value = SimpleNamespace(
        id=9,
        status="active",
        datasource_id=23,
    )
    runtime_service.is_domain_bound_to_agent.return_value = True
    monkeypatch.setattr(
        service_module, "get_semantic_runtime_service", lambda: runtime_service
    )
    datasource_service = AsyncMock()
    datasource_service.belongs_to_agent.return_value = True
    monkeypatch.setattr(
        service_module, "get_datasource_service", lambda: datasource_service
    )
    monkeypatch.setattr(
        service_module,
        "_load_query_runtime_context",
        AsyncMock(
            return_value=(
                {"model_release": None, "object_types": []},
                SimpleNamespace(domain=SimpleNamespace(agent_id=None)),
            )
        ),
    )

    with pytest.raises(
        service_module.CapabilityConfigurationError,
        match="尚未激活统一企业模型版本",
    ):
        await service._load_execution_context(9, 17, "query_loan_application")


@pytest.mark.asyncio
async def test_successful_query_is_returned_when_audit_write_fails(monkeypatch):
    grant = {
        "id": 19,
        "client_id": 8,
        "domain_id": 9,
        "capability_key": "query_loan_application",
        "execution_agent_id": 17,
        "status": "active",
    }
    db = FakeDB(query_rows=[[grant]])
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()
    monkeypatch.setattr(
        service,
        "_load_execution_context",
        AsyncMock(
            return_value=(
                {"model_release": {"id": 12}},
                SimpleNamespace(domain=SimpleNamespace(agent_id=17, datasource_id=23)),
            )
        ),
    )
    monkeypatch.setattr(
        service_module,
        "invoke_ontology_tool",
        AsyncMock(
            return_value={
                "execution": {"status": "succeeded", "executed": True},
                "sql_result": [{"application_count": 8}],
                "sql_error": None,
                "execution_trace": {"trace_id": "trc_success"},
            }
        ),
    )
    monkeypatch.setattr(service_module, "get_ontology_service", lambda: object())
    monkeypatch.setattr(
        service,
        "_write_audit",
        AsyncMock(side_effect=RuntimeError("audit database unavailable")),
    )

    response = await service.invoke(
        {"id": 8, "client_key": "cap_client", "name": "外部助手"},
        "query_loan_application",
        CapabilityInvokePayload(
            domain_id=9,
            logic_form=LogicForm(metrics=["application_count"]),
        ),
    )

    assert response["status"] == "succeeded"
    assert response["result"]["sql_result"] == [{"application_count": 8}]
    assert response["result"]["execution_trace"]["capability_audit"] == {
        "recorded": False
    }


@pytest.mark.asyncio
async def test_database_error_is_sanitized_for_external_caller(monkeypatch):
    grant = {
        "id": 19,
        "client_id": 8,
        "domain_id": 9,
        "capability_key": "query_loan_application",
        "execution_agent_id": 17,
        "status": "active",
    }
    db = FakeDB(query_rows=[[grant]])
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()
    monkeypatch.setattr(
        service,
        "_load_execution_context",
        AsyncMock(
            return_value=(
                {},
                SimpleNamespace(domain=SimpleNamespace(agent_id=17, datasource_id=23)),
            )
        ),
    )
    raw_error = "Unknown column 'customer_secret' in field list"
    monkeypatch.setattr(
        service_module,
        "invoke_ontology_tool",
        AsyncMock(
            return_value={
                "execution": {
                    "status": "database_error",
                    "executed": False,
                    "error_category": "database",
                    "message": raw_error,
                },
                "sql_result": [],
                "sql_error": raw_error,
                "final_answer": f"SQL执行失败: {raw_error}",
                "execution_trace": {
                    "trace_id": "trc_db_error",
                    "sql_execution": {"error": raw_error, "error_type": "OperationalError"},
                },
            }
        ),
    )
    monkeypatch.setattr(service_module, "get_ontology_service", lambda: object())

    response = await service.invoke(
        {"id": 8, "client_key": "cap_client", "name": "外部助手"},
        "query_loan_application",
        CapabilityInvokePayload(
            domain_id=9,
            logic_form=LogicForm(metrics=["application_count"]),
        ),
    )

    serialized = json.dumps(response, ensure_ascii=False)
    assert "customer_secret" not in serialized
    assert "请联系平台管理员并提供 trace_id" in serialized
