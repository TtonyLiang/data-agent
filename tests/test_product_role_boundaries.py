from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app import main
from app.api import deps
from app.api import ontology as ontology_api
from app.api import risk_workflow as risk_api
from app.api import semantic as semantic_api
from app.api import twin_runtime as twin_api
from app.main import app
from app.models.user import PublicUser
from app.services import semantic_runtime as semantic_runtime_module

USER = PublicUser(id=31, username="operator", role="user", status="active")


def _route_dependency_names(method: str, path: str) -> set[str]:
    route = next(
        item
        for item in app.routes
        if isinstance(item, APIRoute)
        and item.path == path
        and method.upper() in (item.methods or set())
    )
    names: set[str] = set()
    pending = [route.dependant]
    while pending:
        dependant = pending.pop()
        for child in dependant.dependencies:
            names.add(getattr(child.call, "__name__", str(child.call)))
            pending.append(child)
    return names


@pytest.fixture
def regular_user_app():
    previous = dict(app.dependency_overrides)

    async def current_user() -> PublicUser:
        return USER

    app.dependency_overrides[deps.get_current_user] = current_user
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_regular_user_product_routes_are_authenticated_without_admin_dependency():
    routes = (
        # 企业模型只读
        ("GET", "/api/ontology/domains"),
        ("GET", "/api/ontology/domains/{domain_id}/summary"),
        ("GET", "/api/ontology/domains/{domain_id}/object-types"),
        ("GET", "/api/ontology/domains/{domain_id}/link-types"),
        ("GET", "/api/ontology/domains/{domain_id}/action-types"),
        ("GET", "/api/ontology/domains/{domain_id}/releases"),
        ("GET", "/api/semantic/assets/{domain_id}"),
        # 孪生预览、查询与受控动作
        ("POST", "/api/twin/domains/{domain_id}/sync-runs"),
        ("GET", "/api/twin/domains/{domain_id}/sync-runs"),
        ("GET", "/api/twin/domains/{domain_id}/sync-runs/{run_id}"),
        ("GET", "/api/ontology/domains/{domain_id}/query"),
        ("GET", "/api/ontology/domains/{domain_id}/objects"),
        ("GET", "/api/ontology/domains/{domain_id}/links"),
        ("POST", "/api/ontology/domains/{domain_id}/actions/{action_type_id}/execute"),
        ("GET", "/api/ontology/domains/{domain_id}/action-runs"),
        # 能力合同与内部验证调用
        ("GET", "/api/ontology/domains/{domain_id}/agent-context"),
        ("GET", "/api/ontology/domains/{domain_id}/query-capabilities"),
        ("POST", "/api/ontology/domains/{domain_id}/agent-tools/{tool_name}"),
        # 风险交付（最终定稿除外）
        ("GET", "/api/risk/domains/{domain_id}/summary"),
        ("POST", "/api/risk/domains/{domain_id}/issues"),
        ("POST", "/api/risk/domains/{domain_id}/issues/{issue_id}/reviews"),
        ("POST", "/api/risk/domains/{domain_id}/reports"),
        ("POST", "/api/risk/domains/{domain_id}/reports/{report_id}/versions"),
        # 内置验证对话与用户自己的会话
        ("POST", "/api/chat"),
        ("POST", "/api/chat/stream"),
        ("POST", "/api/chat/confirm-sql"),
        ("GET", "/api/chat/sessions/{agent_id}"),
        ("GET", "/api/chat/history/{agent_id}/{session_id}"),
        ("DELETE", "/api/chat/sessions/{agent_id}/{session_id}"),
    )

    for method, path in routes:
        dependencies = _route_dependency_names(method, path)
        assert "get_current_user" in dependencies, (method, path, dependencies)
        assert "require_admin" not in dependencies, (method, path, dependencies)


def test_external_capability_uses_client_credentials_instead_of_user_role():
    dependencies = _route_dependency_names(
        "POST", "/api/v1/capabilities/{capability_key}:invoke"
    )

    assert "get_capability_client" in dependencies
    assert "get_current_user" not in dependencies
    assert "require_admin" not in dependencies


@pytest.mark.asyncio
async def test_domain_and_agent_access_follow_regular_user_assignments(monkeypatch):
    class UserService:
        async def get_user_agent_ids(self, user_id: int):
            assert user_id == USER.id
            return [7, 9]

        async def can_access_agent(self, user: PublicUser, agent_id: int):
            return user.id == USER.id and agent_id == 7

    class SemanticService:
        async def get_domain(self, domain_id: int):
            return None if domain_id == 404 else SimpleNamespace(id=domain_id)

        async def is_domain_bound_to_agent(self, domain_id: int, agent_id: int):
            return domain_id == 4 and agent_id == 7

    monkeypatch.setattr(deps, "get_user_service", lambda: UserService())
    monkeypatch.setattr(
        semantic_runtime_module,
        "get_semantic_runtime_service",
        lambda: SemanticService(),
    )

    assert await deps.require_domain_access(4, USER) == 7
    await deps.require_agent_access(7, USER)

    with pytest.raises(HTTPException) as domain_error:
        await deps.require_domain_access(5, USER)
    with pytest.raises(HTTPException) as agent_error:
        await deps.require_agent_access(9, USER)
    with pytest.raises(HTTPException) as missing_error:
        await deps.require_domain_access(404, USER)

    assert domain_error.value.status_code == 403
    assert agent_error.value.status_code == 403
    assert missing_error.value.status_code == 404


@pytest.mark.asyncio
async def test_regular_user_can_read_enterprise_model_and_invoke_capability(
    monkeypatch,
    regular_user_app,
):
    domain_access = AsyncMock(return_value=7)
    ontology_service = AsyncMock()
    ontology_service.get_summary.return_value = {
        "domain": {"id": 4, "name": "贷款业务"},
        "counts": {"object_types": 2},
    }
    ontology_service.list_object_types.return_value = [
        {"id": 11, "domain_id": 4, "object_key": "LoanApplication", "name": "贷款申请"}
    ]
    runtime = SimpleNamespace(domain=SimpleNamespace(agent_id=None, datasource_id=23))
    context = {"actions": [], "model_release": {"id": 12, "version": 2}}
    load_context = AsyncMock(return_value=(context, runtime))
    invoke_tool = AsyncMock(
        return_value={
            "execution": {"status": "succeeded", "executed": True},
            "sql_result": [{"application_count": 8}],
        }
    )

    class DatasourceService:
        async def belongs_to_agent(self, datasource_id: int, agent_id: int):
            return (datasource_id, agent_id) == (23, 7)

    semantic_service = AsyncMock()
    semantic_service.get_domain.return_value = SimpleNamespace(
        id=4,
        model_dump=lambda: {"id": 4, "name": "贷款业务"},
    )
    semantic_service.list_assets.return_value = {"concept": [], "mapping": []}

    monkeypatch.setattr(ontology_api, "require_domain_access", domain_access)
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: ontology_service)
    monkeypatch.setattr(ontology_api, "_load_query_runtime_context", load_context)
    monkeypatch.setattr(
        ontology_api,
        "build_query_capability_definitions",
        lambda _runtime, _context: [
            {"key": "query_loan_application", "name": "查询贷款申请"}
        ],
    )
    monkeypatch.setattr(
        ontology_api, "get_datasource_service", lambda: DatasourceService()
    )
    monkeypatch.setattr(ontology_api, "invoke_ontology_tool", invoke_tool)
    monkeypatch.setattr(semantic_api, "require_domain_access", domain_access)
    monkeypatch.setattr(
        semantic_api, "get_semantic_runtime_service", lambda: semantic_service
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        summary = await client.get("/api/ontology/domains/4/summary")
        object_types = await client.get("/api/ontology/domains/4/object-types")
        assets = await client.get("/api/semantic/assets/4")
        capabilities = await client.get(
            "/api/ontology/domains/4/query-capabilities"
        )
        invocation = await client.post(
            "/api/ontology/domains/4/agent-tools/ontology_query_capability",
            json={"arguments": {"capability_key": "query_loan_application"}},
        )

    assert summary.status_code == 200
    assert object_types.json()["object_types"][0]["object_key"] == "LoanApplication"
    assert assets.status_code == 200
    assert capabilities.json()["query_capabilities"][0]["key"] == (
        "query_loan_application"
    )
    assert invocation.json()["execution"]["status"] == "succeeded"
    assert runtime.domain.agent_id == 7
    assert invoke_tool.await_args.args[4]["role"] == "user"


@pytest.mark.asyncio
async def test_regular_user_can_preview_twin_but_cannot_start_write_sync(
    monkeypatch,
    regular_user_app,
):
    domain_access = AsyncMock(return_value=7)
    twin_service = AsyncMock()
    twin_service.execute_sync.return_value = {
        "run": {"id": 51, "dry_run": True, "status": "succeeded"},
        "result": {"types": [], "has_errors": False},
    }
    twin_service.list_runs.return_value = [
        {"id": 51, "domain_id": 4, "dry_run": True, "status": "succeeded"}
    ]
    twin_service.get_run.return_value = {
        "id": 51,
        "domain_id": 4,
        "dry_run": True,
        "status": "succeeded",
    }
    monkeypatch.setattr(twin_api, "require_domain_access", domain_access)
    monkeypatch.setattr(twin_api, "get_twin_runtime_service", lambda: twin_service)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        preview = await client.post(
            "/api/twin/domains/4/sync-runs",
            json={"object_type_id": 11, "dry_run": True},
        )
        runs = await client.get("/api/twin/domains/4/sync-runs")
        run = await client.get("/api/twin/domains/4/sync-runs/51")
        write_sync = await client.post(
            "/api/twin/domains/4/sync-runs",
            json={"object_type_id": 11, "dry_run": False},
        )
        legacy_write_sync = await client.post(
            "/api/ontology/domains/4/sync",
            json={"object_type_id": 11},
        )

    assert preview.status_code == 200
    assert preview.json()["run"]["dry_run"] is True
    assert runs.json()["runs"][0]["id"] == 51
    assert run.json()["run"]["id"] == 51
    assert write_sync.status_code == 403
    assert legacy_write_sync.status_code == 403
    twin_service.execute_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_regular_user_can_operate_risk_workflow_but_cannot_finalize(
    monkeypatch,
    regular_user_app,
):
    domain_access = AsyncMock(return_value=7)
    risk_service = AsyncMock()
    risk_service.get_summary.return_value = {"open_issues": 1}
    risk_service.create_issue.return_value = {"id": 61, "status": "open"}
    monkeypatch.setattr(risk_api, "require_domain_access", domain_access)
    monkeypatch.setattr(risk_api, "get_risk_workflow_service", lambda: risk_service)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        summary = await client.get("/api/risk/domains/4/summary")
        created = await client.post(
            "/api/risk/domains/4/issues",
            json={
                "domain_id": 4,
                "issue_key": "loan_risk_001",
                "category": "授信风险",
                "severity": "high",
                "title": "贷款申请风险",
            },
        )
        finalized = await client.post(
            "/api/risk/domains/4/reports/9/finalize",
            json={"expected_version": 1},
        )

    assert summary.status_code == 200
    assert created.status_code == 201
    assert created.json()["status"] == "open"
    assert finalized.status_code == 403
    assert risk_service.create_issue.await_args.kwargs["access_agent_id"] == 7
    risk_service.finalize_report.assert_not_awaited()


@pytest.mark.asyncio
async def test_regular_user_chat_executes_only_after_agent_access_check(
    monkeypatch,
    regular_user_app,
):
    access_check = AsyncMock()
    save_turn = AsyncMock()
    graph_calls = 0

    class Graph:
        async def ainvoke(self, state, config=None):
            nonlocal graph_calls
            graph_calls += 1
            return {
                "final_answer": "验证对话可用",
                "sql_result": [],
                "execution_trace": {"trace_id": state["trace_id"]},
            }

    async def prepare_state(**kwargs):
        return {
            "question": kwargs["question"],
            "agent_id": kwargs["agent_id"],
            "user_id": kwargs["user"].id,
            "session_id": kwargs["session_id"],
            "trace_id": kwargs["trace_id"],
        }

    monkeypatch.setattr(main, "require_agent_access", access_check)
    monkeypatch.setattr(main, "load_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        main, "resolve_chat_datasource_access", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(main, "prepare_chat_state", prepare_state)
    monkeypatch.setattr(main, "get_graph", lambda: Graph())
    monkeypatch.setattr(main, "save_turn", save_turn)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        allowed = await client.post(
            "/api/chat",
            json={"question": "你好", "agent_id": 7, "session_id": "user-session"},
        )
        access_check.side_effect = HTTPException(
            status_code=403, detail="无权访问该智能体"
        )
        denied = await client.post(
            "/api/chat",
            json={"question": "你好", "agent_id": 9, "session_id": "blocked"},
        )

    assert allowed.status_code == 200
    assert allowed.json()["answer"] == "验证对话可用"
    assert denied.status_code == 403
    assert graph_calls == 1
    assert save_turn.await_args.kwargs["user"].id == USER.id


@pytest.mark.asyncio
async def test_regular_user_is_rejected_from_administrative_surfaces(regular_user_app):
    requests = (
        ("GET", "/api/datasource/list", None),
        ("POST", "/api/datasource/create", {}),
        ("PUT", "/api/datasource/1", {}),
        ("DELETE", "/api/datasource/1", None),
        ("POST", "/api/datasource/1/collect-schema", {}),
        ("PUT", "/api/datasource/1/permissions/7", {}),
        ("POST", "/api/agent/create", {}),
        ("PUT", "/api/agent/7", {}),
        ("PUT", "/api/agent/7/domain-ids", {}),
        ("DELETE", "/api/agent/7", None),
        ("GET", "/api/model-config/list", None),
        ("POST", "/api/model-config/create", {}),
        ("PUT", "/api/model-config/1", {}),
        ("POST", "/api/model-config/1/test", None),
        ("DELETE", "/api/model-config/1", None),
        ("GET", "/api/system/parameters", None),
        ("PUT", "/api/system/parameters", []),
        ("GET", "/api/prompt/list", None),
        ("GET", "/api/users", None),
        ("GET", "/api/workspaces", None),
        ("POST", "/api/semantic/domains", {}),
        ("DELETE", "/api/semantic/domains/4", None),
        ("POST", "/api/semantic/assets/4", {}),
        ("DELETE", "/api/semantic/assets/4/metric/1", None),
        ("POST", "/api/semantic/runtime/build", {}),
        ("POST", "/api/semantic/logic-form/validate", {}),
        ("POST", "/api/semantic/sync-vector/4", None),
        ("POST", "/api/ontology/domains/4/object-types", {}),
        ("DELETE", "/api/ontology/domains/4/object-types/11", None),
        ("POST", "/api/ontology/domains/4/link-types", {}),
        ("POST", "/api/ontology/domains/4/action-types", {}),
        ("POST", "/api/ontology/domains/4/validate", None),
        ("POST", "/api/ontology/domains/4/publish", {}),
        ("POST", "/api/ontology/domains/4/import", {}),
        ("POST", "/api/ontology/domains/4/objects", {}),
        ("POST", "/api/ontology/domains/4/links", {}),
        ("GET", "/api/model-releases/domains/4/releases", None),
        ("POST", "/api/model-releases/domains/4/releases", {}),
        ("POST", "/api/model-releases/domains/4/releases/2/validate", {}),
        ("POST", "/api/model-releases/domains/4/releases/2/activate", None),
        ("POST", "/api/model-releases/domains/4/releases/2/deactivate", None),
        ("POST", "/api/model-releases/domains/4/releases/2/rollback", None),
        ("GET", "/api/capability-clients", None),
        ("POST", "/api/capability-clients", {}),
        ("PATCH", "/api/capability-clients/1", {}),
        ("PUT", "/api/capability-clients/1/grants", {}),
        ("GET", "/api/capability-invocations", None),
        ("POST", "/api/risk/domains/4/reports/9/finalize", {}),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        for method, path, payload in requests:
            response = await client.request(
                method,
                path,
                **({"json": payload} if payload is not None else {}),
            )
            assert response.status_code == 403, (method, path, response.text)
            assert response.json()["detail"] == "无权访问管理功能"
