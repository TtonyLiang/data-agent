from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import ontology as ontology_api
from app.api import twin_runtime as twin_api
from app.models.twin_runtime import TwinSyncRequest
from app.models.user import PublicUser
from app.services.permission_service import (
    DOMAIN_PERMISSION_NOT_CONFIGURED_CODE,
    domain_permission_not_configured_detail,
)

ADMIN = PublicUser(id=1, username="admin", role="admin", status="active")


class SemanticService:
    async def get_domain(self, domain_id):
        return SimpleNamespace(id=domain_id, datasource_id=42, status="active")


class PermissionService:
    def __init__(self, source):
        self.source = source
        self.calls = []

    async def resolve_domain_permission_context(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return SimpleNamespace(source=self.source)


def test_missing_domain_permission_detail_is_structured_and_actionable():
    detail = domain_permission_not_configured_detail(7, 42)

    assert detail == {
        "code": DOMAIN_PERMISSION_NOT_CONFIGURED_CODE,
        "message": (
            "当前业务领域未配置数据权限，请在数据源访问权限中选择该业务领域，"
            "配置表与字段白名单；无需创建智能体。"
        ),
        "domain_id": 7,
        "datasource_id": 42,
        "permission_subject": "domain",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "resolver_name"),
    [
        (ontology_api, "_resolve_data_access_agent"),
        (twin_api, "_resolve_access_agent"),
    ],
)
async def test_unconfigured_domain_returns_no_agent_adapter(
    monkeypatch, module, resolver_name
):
    permission_service = PermissionService("unconfigured")
    monkeypatch.setattr(
        module, "get_semantic_runtime_service", lambda: SemanticService()
    )
    monkeypatch.setattr(
        module, "get_permission_service", lambda: permission_service
    )

    resolved = await getattr(module, resolver_name)(7, None)

    assert resolved is None
    assert permission_service.calls == [
        (
            (7, 42),
            {"compatibility_agent_id": None, "allow_agent_fallback": False},
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "resolver_name"),
    [
        (ontology_api, "_resolve_data_access_agent"),
        (twin_api, "_resolve_access_agent"),
    ],
)
async def test_agent_permission_is_used_only_as_explicit_compatibility(
    monkeypatch, module, resolver_name
):
    permission_service = PermissionService("agent_compatibility")
    monkeypatch.setattr(
        module, "get_semantic_runtime_service", lambda: SemanticService()
    )
    monkeypatch.setattr(
        module, "get_permission_service", lambda: permission_service
    )

    resolved = await getattr(module, resolver_name)(7, 11)

    assert resolved == 11
    assert permission_service.calls == [
        (
            (7, 42),
            {"compatibility_agent_id": 11, "allow_agent_fallback": True},
        )
    ]


@pytest.mark.asyncio
async def test_ontology_permission_configuration_error_is_structured(monkeypatch):
    service = AsyncMock()
    service.query_objects.side_effect = PermissionError(
        "对象数据访问缺少明确的权限主体：当前业务领域未配置数据权限"
    )
    monkeypatch.setattr(
        ontology_api, "require_domain_access", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        ontology_api, "_resolve_data_access_agent", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: service)
    monkeypatch.setattr(
        ontology_api, "get_semantic_runtime_service", lambda: SemanticService()
    )

    with pytest.raises(HTTPException) as exc_info:
        await ontology_api.query_objects(7, current_user=ADMIN)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == DOMAIN_PERMISSION_NOT_CONFIGURED_CODE
    assert "无需创建智能体" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_twin_permission_configuration_error_is_structured(monkeypatch):
    service = AsyncMock()
    service.execute_sync.side_effect = PermissionError("当前业务领域未配置数据权限")
    monkeypatch.setattr(
        twin_api, "require_domain_access", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        twin_api, "_resolve_access_agent", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(twin_api, "get_twin_runtime_service", lambda: service)
    monkeypatch.setattr(
        twin_api, "get_semantic_runtime_service", lambda: SemanticService()
    )

    with pytest.raises(HTTPException) as exc_info:
        await twin_api.create_sync_run(
            7,
            TwinSyncRequest(dry_run=True),
            ADMIN,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == DOMAIN_PERMISSION_NOT_CONFIGURED_CODE
    assert exc_info.value.detail["permission_subject"] == "domain"
