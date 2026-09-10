from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.models.user import (
    PublicUser,
    ontology_action_role,
    role_capabilities,
    role_label,
)


def make_user(role: str) -> PublicUser:
    return PublicUser(id=7, username=role, role=role, status="active")


def test_product_roles_have_business_facing_labels_and_capabilities():
    assert role_label("business") == "业务人员"
    assert role_label("technical") == "技术人员"
    assert "model_edit" in role_capabilities("business")
    assert "data_source_manage" not in role_capabilities("business")
    assert "data_source_manage" in role_capabilities("technical")
    assert role_capabilities("user") == [
        "domain_read",
        "capability_validate",
        "risk_review",
    ]


@pytest.mark.asyncio
async def test_model_and_data_boundaries_keep_legacy_user_read_only(monkeypatch):
    for role in ("business", "technical", "admin"):
        assert await deps.require_model_editor(make_user(role))
    with pytest.raises(HTTPException) as legacy_editor_error:
        await deps.require_model_editor(make_user("user"))
    assert legacy_editor_error.value.status_code == 403

    for role in ("technical", "admin"):
        assert await deps.require_data_engineer(make_user(role))
    with pytest.raises(HTTPException, match="技术人员"):
        await deps.require_data_engineer(make_user("business"))

    assert await deps.require_model_publisher(make_user("technical"))
    with pytest.raises(HTTPException, match="发布或回滚"):
        await deps.require_model_publisher(make_user("business"))

    semantic = SimpleNamespace(get_domain=AsyncMock(return_value=SimpleNamespace(id=3)))
    user_service = SimpleNamespace(
        get_user_agent_ids=AsyncMock(
            side_effect=AssertionError("modern roles do not use Agent grants")
        ),
    )
    monkeypatch.setattr(
        "app.services.semantic_runtime.get_semantic_runtime_service",
        lambda: semantic,
    )
    monkeypatch.setattr(deps, "get_user_service", lambda: user_service)
    assert await deps.require_domain_access(3, make_user("business")) is None
    assert await deps.require_domain_access(3, make_user("technical")) is None


@pytest.mark.asyncio
async def test_agent_access_keeps_legacy_user_compatibility(monkeypatch):
    service = SimpleNamespace(can_access_agent=AsyncMock(return_value=True))
    monkeypatch.setattr(deps, "get_user_service", lambda: service)

    await deps.require_agent_access(9, make_user("business"))
    await deps.require_agent_access(9, make_user("technical"))
    service.can_access_agent.assert_not_awaited()

    await deps.require_agent_access(9, make_user("user"))
    service.can_access_agent.assert_awaited_once()


def test_ontology_action_contract_maps_modern_roles_to_legacy_values():
    assert ontology_action_role("business") == "user"
    assert ontology_action_role("user") == "user"
    assert ontology_action_role("technical") == "admin"
    assert ontology_action_role("admin") == "admin"
