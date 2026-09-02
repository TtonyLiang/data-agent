from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.agent.ontology_tools import QUERY_CAPABILITY_TOOL
from app.api import ontology as ontology_api
from app.models.knowledge import SemanticDomain, SemanticRuntime
from app.models.ontology import OntologyAgentToolPayload
from app.models.user import PublicUser


def make_runtime(datasource_id: int | None) -> SemanticRuntime:
    return SemanticRuntime(
        domain=SemanticDomain(
            id=7,
            agent_id=11,
            datasource_id=datasource_id,
            domain_key="loan_risk",
            name="贷款风控",
        )
    )


def make_user() -> PublicUser:
    return PublicUser(
        id=1,
        username="tester",
        role="user",
        status="active",
    )


def patch_query_route(monkeypatch, runtime: SemanticRuntime):
    ontology_service = object()
    datasource_service = SimpleNamespace(belongs_to_agent=AsyncMock())
    invoke = AsyncMock(return_value={"ok": True})

    monkeypatch.setattr(ontology_api, "require_domain_access", AsyncMock())
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: ontology_service)
    monkeypatch.setattr(
        ontology_api,
        "_load_query_runtime_context",
        AsyncMock(return_value=({"domain": {"id": 7}}, runtime)),
    )
    monkeypatch.setattr(ontology_api, "get_datasource_service", lambda: datasource_service)
    monkeypatch.setattr(ontology_api, "invoke_ontology_tool", invoke)
    return ontology_service, datasource_service, invoke


def query_payload() -> OntologyAgentToolPayload:
    return OntologyAgentToolPayload(arguments={"capability_key": "query_loan_application"})


@pytest.mark.asyncio
async def test_query_capability_rejects_missing_datasource(monkeypatch):
    _, datasource_service, invoke = patch_query_route(monkeypatch, make_runtime(None))

    with pytest.raises(HTTPException) as exc_info:
        await ontology_api.run_agent_tool(7, QUERY_CAPABILITY_TOOL, query_payload(), make_user())

    assert exc_info.value.status_code == 400
    assert "datasource_id" in str(exc_info.value.detail)
    datasource_service.belongs_to_agent.assert_not_awaited()
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_capability_rejects_datasource_bound_to_another_agent(monkeypatch):
    runtime = make_runtime(42)
    _, datasource_service, invoke = patch_query_route(monkeypatch, runtime)
    datasource_service.belongs_to_agent.return_value = False

    with pytest.raises(HTTPException) as exc_info:
        await ontology_api.run_agent_tool(7, QUERY_CAPABILITY_TOOL, query_payload(), make_user())

    assert exc_info.value.status_code == 403
    datasource_service.belongs_to_agent.assert_awaited_once_with(42, 11)
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_capability_invokes_tool_for_agent_owned_datasource(monkeypatch):
    runtime = make_runtime(42)
    ontology_service, datasource_service, invoke = patch_query_route(monkeypatch, runtime)
    datasource_service.belongs_to_agent.return_value = True
    user = make_user()
    payload = query_payload()

    result = await ontology_api.run_agent_tool(7, QUERY_CAPABILITY_TOOL, payload, user)

    assert result == {"ok": True}
    datasource_service.belongs_to_agent.assert_awaited_once_with(42, 11)
    invoke.assert_awaited_once()
    args, kwargs = invoke.await_args
    assert args[:4] == (
        ontology_service,
        7,
        QUERY_CAPABILITY_TOOL,
        payload.arguments,
    )
    assert args[4] == user.model_dump()
    assert kwargs == {
        "ontology_context": {"domain": {"id": 7}},
        "semantic_runtime": runtime,
    }
