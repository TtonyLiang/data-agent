import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.agent import ontology_tools
from app.api import capability_access as capability_api
from app.db.capability_access_schema import CAPABILITY_ACCESS_TABLE_STATEMENTS
from app.main import app
from app.models.capability_access import (
    CapabilityClientCreatePayload,
    CapabilityGrantUpsertPayload,
    CapabilityInvokePayload,
)
from app.models.knowledge import (
    LogicFilter,
    LogicForm,
    SemanticDomain,
    SemanticMapping,
    SemanticMetric,
    SemanticRuntime,
)
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


def _contract_binding(release_id: int = 12) -> dict:
    snapshot = {
        "schema_version": 1,
        "kind": "query_capability",
        "domain_id": 9,
        "model_release": {"id": release_id, "model_hash": "c" * 64},
        "data_policy": {
            "strategy": "live_source",
            "source": {"kind": "business_datasource", "datasource_id": 23},
            "as_of": {"mode": "invocation_time"},
            "uses_twin_snapshot": False,
        },
        "capability": {
            "key": "query_loan_application",
            "name": "贷款申请查询",
            "read_only": True,
        },
    }
    return {
        "model_release_id": release_id,
        "contract_hash": service_module.canonical_sha256(snapshot),
        "contract_json": snapshot,
    }


def _bound_grant(**overrides) -> dict:
    return {
        "id": 19,
        "client_id": 8,
        "domain_id": 9,
        "capability_key": "query_loan_application",
        "execution_agent_id": 17,
        "status": "active",
        **_contract_binding(),
        **overrides,
    }


def _mock_contract_binding(monkeypatch, service, binding=None):
    binding = binding or _contract_binding()
    builder = Mock(return_value=binding)
    monkeypatch.setattr(service, "_build_contract_binding", builder)
    return binding, builder


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
async def test_grant_without_agent_auto_resolves_internal_permission_adapter(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()
    monkeypatch.setattr(service, "get_client", AsyncMock(return_value={"id": 8}))
    monkeypatch.setattr(
        service,
        "_resolve_domain_permission_adapter",
        AsyncMock(return_value=17),
    )
    load_context = AsyncMock(return_value=({}, SimpleNamespace(domain=SimpleNamespace())))
    monkeypatch.setattr(service, "_load_execution_context", load_context)
    binding, _ = _mock_contract_binding(monkeypatch, service)
    monkeypatch.setattr(
        service,
        "get_grant",
        AsyncMock(
            return_value={
                "id": 31,
                "client_id": 8,
                "domain_id": 9,
                "capability_key": "query_loan_application",
                "execution_agent_id": 17,
                "status": "active",
            }
        ),
    )

    grant = await service.upsert_grant(
        8,
        CapabilityGrantUpsertPayload(
            domain_id=9,
            capability_key="query_loan_application",
        ),
        actor_id=7,
    )

    service._resolve_domain_permission_adapter.assert_awaited_once_with(9)
    load_context.assert_awaited_once_with(9, 17, "query_loan_application")
    assert db.inserts[0][1]["execution_agent_id"] == 17
    assert db.inserts[0][1]["model_release_id"] == 12
    assert db.inserts[0][1]["contract_hash"] == binding["contract_hash"]
    assert json.loads(db.inserts[0][1]["contract_json"])["data_policy"] == {
        "strategy": "live_source",
        "source": {"kind": "business_datasource", "datasource_id": 23},
        "as_of": {"mode": "invocation_time"},
        "uses_twin_snapshot": False,
    }
    assert grant["execution_agent_id"] == 17


@pytest.mark.asyncio
async def test_grant_keeps_explicit_agent_override_for_legacy_clients(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()
    monkeypatch.setattr(service, "get_client", AsyncMock(return_value={"id": 8}))
    resolver = AsyncMock(return_value=99)
    monkeypatch.setattr(service, "_resolve_domain_permission_adapter", resolver)
    load_context = AsyncMock(return_value=({}, SimpleNamespace(domain=SimpleNamespace())))
    monkeypatch.setattr(service, "_load_execution_context", load_context)
    _mock_contract_binding(monkeypatch, service)
    monkeypatch.setattr(service, "get_grant", AsyncMock(return_value={"id": 31}))

    await service.upsert_grant(
        8,
        CapabilityGrantUpsertPayload(
            domain_id=9,
            capability_key="query_loan_application",
            execution_agent_id=23,
        ),
        actor_id=7,
    )

    resolver.assert_not_awaited()
    load_context.assert_awaited_once_with(9, 23, "query_loan_application")
    assert db.inserts[0][1]["execution_agent_id"] == 23


@pytest.mark.asyncio
async def test_grant_without_agent_keeps_existing_permission_boundary(monkeypatch):
    db = FakeDB(query_rows=[[{"execution_agent_id": 23}]])
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()
    monkeypatch.setattr(service, "get_client", AsyncMock(return_value={"id": 8}))
    resolver = AsyncMock(return_value=99)
    monkeypatch.setattr(service, "_resolve_domain_permission_adapter", resolver)
    load_context = AsyncMock(return_value=({}, SimpleNamespace(domain=SimpleNamespace())))
    monkeypatch.setattr(service, "_load_execution_context", load_context)
    _mock_contract_binding(monkeypatch, service)
    monkeypatch.setattr(service, "get_grant", AsyncMock(return_value={"id": 31}))

    await service.upsert_grant(
        8,
        CapabilityGrantUpsertPayload(
            domain_id=9,
            capability_key="query_loan_application",
        ),
        actor_id=7,
    )

    resolver.assert_not_awaited()
    load_context.assert_awaited_once_with(9, 23, "query_loan_application")
    assert db.inserts[0][1]["execution_agent_id"] == 23


@pytest.mark.asyncio
async def test_revoking_grant_without_agent_reuses_stored_adapter(monkeypatch):
    db = FakeDB(query_rows=[[{"execution_agent_id": 17}]])
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()
    monkeypatch.setattr(service, "get_client", AsyncMock(return_value={"id": 8}))
    load_context = AsyncMock()
    monkeypatch.setattr(service, "_load_execution_context", load_context)
    monkeypatch.setattr(service, "get_grant", AsyncMock(return_value={"id": 31}))

    await service.upsert_grant(
        8,
        CapabilityGrantUpsertPayload(
            domain_id=9,
            capability_key="query_loan_application",
            status="revoked",
        ),
        actor_id=7,
    )

    load_context.assert_not_awaited()
    assert db.inserts[0][1]["execution_agent_id"] == 17


@pytest.mark.asyncio
async def test_domain_permission_adapter_skips_consumer_without_datasource_access(
    monkeypatch,
):
    service = CapabilityAccessService()
    runtime_service = AsyncMock()
    runtime_service.get_domain.return_value = SimpleNamespace(
        id=9,
        status="active",
        datasource_id=23,
    )
    runtime_service.resolve_domain_agent.return_value = 17
    runtime_service.get_domain_agent_ids.return_value = [17, 18]
    monkeypatch.setattr(
        service_module, "get_semantic_runtime_service", lambda: runtime_service
    )
    datasource_service = AsyncMock()
    datasource_service.belongs_to_agent.side_effect = [False, True]
    monkeypatch.setattr(
        service_module, "get_datasource_service", lambda: datasource_service
    )

    resolved = await service._resolve_domain_permission_adapter(9)

    assert resolved == 18
    assert datasource_service.belongs_to_agent.await_args_list[0].args == (23, 17)
    assert datasource_service.belongs_to_agent.await_args_list[1].args == (23, 18)


def test_contract_binding_freezes_release_capability_and_live_source_policy(monkeypatch):
    contract = {
        "key": "query_loan_application",
        "name": "贷款申请查询",
        "read_only": True,
        "metadata": {
            "data_policy": {
                "strategy": "live_source",
                "source_kind": "business_datasource",
                "as_of_mode": "invocation_time",
                "uses_twin_snapshot": False,
            }
        },
    }
    monkeypatch.setattr(
        service_module,
        "build_query_capability_definitions",
        Mock(return_value=[contract]),
    )

    binding = CapabilityAccessService._build_contract_binding(
        9,
        "query_loan_application",
        {"model_release": {"id": 12, "model_hash": "c" * 64}},
        SimpleNamespace(domain=SimpleNamespace(datasource_id=23)),
    )

    assert binding["model_release_id"] == 12
    assert len(binding["contract_hash"]) == 64
    assert binding["contract_json"]["capability"] == contract
    assert binding["contract_json"]["data_policy"] == {
        "strategy": "live_source",
        "source": {"kind": "business_datasource", "datasource_id": 23},
        "as_of": {"mode": "invocation_time"},
        "uses_twin_snapshot": False,
    }


@pytest.mark.asyncio
async def test_invoke_rejects_release_different_from_frozen_grant(monkeypatch):
    db = FakeDB(query_rows=[[_bound_grant()]])
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()
    load_context = AsyncMock()
    monkeypatch.setattr(service, "_load_execution_context", load_context)

    with pytest.raises(
        service_module.CapabilityConfigurationError,
        match="与能力授权合同不一致",
    ):
        await service.invoke(
            {"id": 8, "client_key": "cap_client", "name": "外部助手"},
            "query_loan_application",
            CapabilityInvokePayload(
                domain_id=9,
                model_release_id=13,
                logic_form=LogicForm(metrics=["application_count"]),
            ),
        )

    load_context.assert_not_awaited()
    assert db.inserts[0][1]["model_release_id"] == 12
    assert db.inserts[0][1]["status"] == "permission_blocked"


@pytest.mark.asyncio
async def test_invoke_rejects_tampered_frozen_contract(monkeypatch):
    grant = _bound_grant(contract_hash="0" * 64)
    db = FakeDB(query_rows=[[grant]])
    monkeypatch.setattr(service_module, "get_management_db", lambda: db)
    service = CapabilityAccessService()
    monkeypatch.setattr(
        service,
        "_load_execution_context",
        AsyncMock(return_value=({}, SimpleNamespace(domain=SimpleNamespace()))),
    )
    _mock_contract_binding(monkeypatch, service)

    with pytest.raises(
        service_module.CapabilityConfigurationError,
        match="合同快照校验失败",
    ):
        await service.invoke(
            {"id": 8, "client_key": "cap_client", "name": "外部助手"},
            "query_loan_application",
            CapabilityInvokePayload(
                domain_id=9,
                logic_form=LogicForm(metrics=["application_count"]),
            ),
        )

    assert db.inserts[0][1]["status"] == "permission_blocked"


@pytest.mark.asyncio
async def test_external_invoke_uses_grant_adapter_and_audits_summary_only(monkeypatch):
    grant = _bound_grant()
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
    _mock_contract_binding(monkeypatch, service)
    invoke = AsyncMock(
        return_value={
            "execution": {"status": "succeeded", "executed": True, "attempted": True},
            "sql_result": [{"channel": "APP", "application_count": 8}],
            "sql_error": None,
            "compiled_plan": {
                "sql": "SELECT channel, COUNT(*) FROM loan_application",
                "executed_sql": "SELECT channel, COUNT(*) FROM loan_application LIMIT 1000",
                "used_assets": ["metric:application_count", "mapping:channel"],
            },
            "executed_sql": "SELECT channel, COUNT(*) FROM loan_application LIMIT 1000",
            "execution_trace": {
                "trace_id": "trc_external",
                "target_object": "LoanApplication",
                "model_release": {"id": 12, "version": 3},
                "semantic_snapshot": {"id": 8},
                "ontology_release": {"id": 4, "version": 2},
                "executed_sql": "SELECT channel, COUNT(*) FROM loan_application LIMIT 1000",
                "sql_execution": {
                    "compiled_sql": "SELECT channel, COUNT(*) FROM loan_application LIMIT 1000",
                    "duration_ms": 12.5,
                },
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
        model_release_id=12,
    )
    invoke.assert_awaited_once()
    assert response["trace_id"] == "trc_external"
    assert response["result"]["sql_result"][0]["channel"] == "APP"
    assert "executed_sql" not in response["result"]
    assert "sql" not in response["result"]["compiled_plan"]
    assert "executed_sql" not in response["result"]["compiled_plan"]
    assert "executed_sql" not in response["result"]["execution_trace"]
    assert response["result"]["execution_trace"]["sql_execution"] == {
        "duration_ms": 12.5
    }
    assert "SELECT channel" not in json.dumps(response, ensure_ascii=False)
    assert response["result"]["compiled_plan"]["used_assets"] == [
        "metric:application_count",
        "mapping:channel",
    ]
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
async def test_external_unmodeled_logic_form_is_structured_and_never_falls_back(
    monkeypatch,
):
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
    runtime = SemanticRuntime(
        domain=SemanticDomain(
            id=9,
            agent_id=17,
            datasource_id=23,
            domain_key="loan_risk",
            name="贷款风控",
        ),
        metrics=[
            SemanticMetric(
                domain_id=9,
                metric_key="application_count",
                name="申请笔数",
                formula_sql="COUNT(*)",
                base_table="loan_application",
                dimensions=["channel"],
                metadata={"object_key": "LoanApplication"},
            )
        ],
        mappings=[
            SemanticMapping(
                domain_id=9,
                asset_type="dimension",
                asset_key="channel",
                table_name="loan_application",
                column_name="channel",
                role="dimension",
            )
        ],
    )
    context = {
        "domain": {"id": 9, "domain_key": "loan_risk", "name": "贷款风控"},
        "model_release": {"id": 12, "version": 3, "status": "active"},
        "semantic_snapshot": {"id": 8},
        "ontology_release": {"id": 4, "version": 2},
        "release": {"id": 4, "version": 2},
        "object_types": [
            {
                "object_key": "LoanApplication",
                "name": "贷款申请",
                "status": "active",
                "properties": [],
            }
        ],
        "link_types": [],
        "actions": [],
        "warnings": [],
    }
    service = CapabilityAccessService()
    monkeypatch.setattr(
        service,
        "_load_execution_context",
        AsyncMock(return_value=(context, runtime)),
    )
    monkeypatch.setattr(service_module, "get_ontology_service", lambda: Mock())
    executor = AsyncMock(side_effect=AssertionError("unmodeled query must not execute"))
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)

    response = await service.invoke(
        {"id": 8, "client_key": "cap_client", "name": "外部助手"},
        "query_loan_application",
        CapabilityInvokePayload(
            domain_id=9,
            logic_form=LogicForm(
                metrics=["application_count"],
                dimensions=["unmodeled_dimension"],
            ),
        ),
    )

    executor.assert_not_awaited()
    assert response["status"] == "validation_blocked"
    assert response["result"]["error"] == {
        "code": "semantic_model_not_covered",
        "category": "semantic_model",
        "message": "请求未被当前已发布企业模型覆盖，未执行查询。",
        "details": {
            "validation_errors": [
                "Capability 不支持维度: unmodeled_dimension",
                "指标 application_count 不支持维度: unmodeled_dimension",
                "未知维度: unmodeled_dimension",
            ],
            "fallback_allowed": False,
        },
    }
    assert response["result"]["execution"]["attempted"] is False
    assert response["result"]["execution"]["error_category"] == "semantic_model"
    assert "compiled_plan" not in response["result"]
    assert db.inserts[0][1]["status"] == "validation_blocked"
    assert db.inserts[0][1]["error_category"] == "semantic_model"


@pytest.mark.asyncio
async def test_external_query_rejects_any_nl2sql_fallback_result(monkeypatch):
    grant = _bound_grant()
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
    _mock_contract_binding(monkeypatch, service)
    monkeypatch.setattr(service_module, "get_ontology_service", lambda: object())
    monkeypatch.setattr(
        service_module,
        "invoke_ontology_tool",
        AsyncMock(
            return_value={
                "execution": {
                    "status": "succeeded",
                    "executed": True,
                    "mode": "nl2sql_fallback",
                },
                "sql_result": [{"application_count": 8}],
                "execution_trace": {"compile_strategy": "nl2sql_fallback"},
            }
        ),
    )

    with pytest.raises(service_module.CapabilityAccessError, match="禁止使用 NL2SQL 兜底"):
        await service.invoke(
            {"id": 8, "client_key": "cap_client", "name": "外部助手"},
            "query_loan_application",
            CapabilityInvokePayload(
                domain_id=9,
                logic_form=LogicForm(metrics=["application_count"]),
            ),
        )

    assert db.inserts[0][1]["status"] == "validation_blocked"
    assert db.inserts[0][1]["error_category"] == "validation"


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
    assert "execution_agent_id BIGINT DEFAULT NULL" in ddl
    assert "旧领域兼容的内部数据权限适配ID" in ddl
    assert "model_release_id BIGINT DEFAULT NULL" in ddl
    assert "contract_hash CHAR(64) DEFAULT NULL" in ddl
    assert "contract_json JSON DEFAULT NULL" in ddl
    assert "idx_capability_grant_release" in ddl
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
async def test_external_capability_api_authenticates_headers_and_invokes_without_agent(
    monkeypatch,
):
    class FakeCapabilityService:
        def __init__(self):
            self.authenticated = None
            self.invoked = None

        async def authenticate_client(self, client_key, client_secret):
            self.authenticated = (client_key, client_secret)
            if client_key != "client-key" or client_secret != "client-secret":
                raise CapabilityAuthenticationError("凭据无效")
            return {"id": 8, "client_key": client_key, "status": "active"}

        async def invoke(self, client, capability_key, payload):
            self.invoked = (client, capability_key, payload)
            return {
                "trace_id": "trace-api-1",
                "domain_id": payload.domain_id,
                "capability_key": capability_key,
                "status": "succeeded",
                "latency_ms": 1.5,
                "result": {"rows": [{"count": 3}]},
            }

    service = FakeCapabilityService()
    monkeypatch.setattr(capability_api, "get_capability_access_service", lambda: service)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/capabilities/query_loan_application:invoke",
            headers={
                "X-Capability-Key": "client-key",
                "X-Capability-Secret": "client-secret",
            },
            json={
                "domain_id": 9,
                "model_release_id": 12,
                "logic_form": {"metrics": ["loan_application_count"]},
            },
        )

    assert response.status_code == 200
    assert response.json()["trace_id"] == "trace-api-1"
    assert service.authenticated == ("client-key", "client-secret")
    assert service.invoked[0]["id"] == 8
    assert service.invoked[1] == "query_loan_application"
    assert service.invoked[2].domain_id == 9


@pytest.mark.asyncio
async def test_external_capability_api_returns_auth_and_authorization_failures(
    monkeypatch,
):
    class FakeCapabilityService:
        async def authenticate_client(self, client_key, client_secret):
            if client_secret != "client-secret":
                raise CapabilityAuthenticationError("凭据无效")
            return {"id": 8, "client_key": client_key, "status": "active"}

        async def invoke(self, client, capability_key, payload):
            raise CapabilityAuthorizationError("能力未授权")

    monkeypatch.setattr(
        capability_api, "get_capability_access_service", lambda: FakeCapabilityService()
    )
    request = {
        "domain_id": 9,
        "logic_form": {"metrics": ["loan_application_count"]},
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        unauthorized = await client.post(
            "/api/v1/capabilities/query_loan_application:invoke",
            headers={
                "X-Capability-Key": "client-key",
                "X-Capability-Secret": "wrong-secret",
            },
            json=request,
        )
        forbidden = await client.post(
            "/api/v1/capabilities/query_loan_application:invoke",
            headers={
                "X-Capability-Key": "client-key",
                "X-Capability-Secret": "client-secret",
            },
            json=request,
        )

    assert unauthorized.status_code == 401
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "能力未授权"


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
    load_query_runtime_context = AsyncMock(
        return_value=(
            {"model_release": None, "object_types": []},
            SimpleNamespace(domain=SimpleNamespace(agent_id=None)),
        )
    )
    monkeypatch.setattr(
        service_module,
        "_load_query_runtime_context",
        load_query_runtime_context,
    )

    with pytest.raises(
        service_module.CapabilityConfigurationError,
        match="尚未激活统一企业模型版本",
    ):
        await service._load_execution_context(9, 17, "query_loan_application")

    load_query_runtime_context.assert_awaited_once_with(
        service_module.get_ontology_service(),
        9,
        {"role": "user"},
        require_active_release=True,
    )


@pytest.mark.asyncio
async def test_successful_query_is_returned_when_audit_write_fails(monkeypatch):
    grant = _bound_grant()
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
    _mock_contract_binding(monkeypatch, service)
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
    grant = _bound_grant()
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
    _mock_contract_binding(monkeypatch, service)
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
    assert "请联系技术人员并提供 trace_id" in serialized
