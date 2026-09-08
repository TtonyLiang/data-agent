from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import twin_runtime as twin_api
from app.main import app
from app.models.twin_runtime import TwinSyncRequest
from app.models.user import PublicUser

USER = PublicUser(id=3, username="reader", role="user", status="active")
ADMIN = PublicUser(id=1, username="admin", role="admin", status="active")


@pytest.mark.asyncio
async def test_create_sync_run_uses_resolved_permission_agent(monkeypatch):
    service = AsyncMock()
    service.execute_sync.return_value = {
        "run": {"id": 11, "status": "succeeded"},
        "result": {"types": [], "has_errors": False},
    }
    monkeypatch.setattr(twin_api, "get_twin_runtime_service", lambda: service)
    monkeypatch.setattr(
        twin_api,
        "require_domain_access",
        AsyncMock(return_value=7),
    )
    monkeypatch.setattr(
        twin_api,
        "_resolve_access_agent",
        AsyncMock(return_value=7),
    )

    result = await twin_api.create_sync_run(
        4,
        TwinSyncRequest(
            object_type_id=12,
            page=1,
            page_size=100,
            sync_links=True,
            dry_run=True,
        ),
        USER,
    )

    service.execute_sync.assert_awaited_once_with(
        domain_id=4,
        access_agent_id=7,
        created_by=3,
        object_type_id=12,
        page=1,
        page_size=100,
        sync_links=True,
        dry_run=True,
        trace_id=None,
    )
    assert result["run"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_admin_sync_without_domain_rules_does_not_require_agent(monkeypatch):
    class SemanticService:
        get_domain = AsyncMock(
            return_value=SimpleNamespace(id=4, datasource_id=8)
        )

    class PermissionService:
        resolve_domain_permission_context = AsyncMock(
            return_value=SimpleNamespace(source="unconfigured")
        )

    semantic_service = SemanticService()
    monkeypatch.setattr(
        twin_api, "get_semantic_runtime_service", lambda: semantic_service
    )
    permission_service = PermissionService()
    monkeypatch.setattr(
        twin_api, "get_permission_service", lambda: permission_service
    )

    assert await twin_api._resolve_access_agent(4, None) is None
    permission_service.resolve_domain_permission_context.assert_awaited_once_with(
        4,
        8,
        compatibility_agent_id=None,
        allow_agent_fallback=False,
    )


@pytest.mark.asyncio
async def test_non_admin_cannot_start_write_sync(monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr(twin_api, "get_twin_runtime_service", lambda: service)
    monkeypatch.setattr(
        twin_api,
        "require_domain_access",
        AsyncMock(return_value=7),
    )

    with pytest.raises(twin_api.HTTPException) as exc_info:
        await twin_api.create_sync_run(
            4,
            TwinSyncRequest(object_type_id=12, dry_run=False),
            USER,
        )

    assert exc_info.value.status_code == 403
    service.execute_sync.assert_not_awaited()


def test_twin_runtime_routes_are_registered():
    paths = {route.path for route in app.routes}

    assert "/api/twin/domains/{domain_id}/sync-runs" in paths
    assert "/api/twin/domains/{domain_id}/sync-runs/{run_id}" in paths
