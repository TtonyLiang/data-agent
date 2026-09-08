from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import model_release as model_release_api
from app.main import app
from app.models.model_release import EnterpriseModelReleaseCreatePayload
from app.models.user import PublicUser
from app.services.model_release_service import ModelReleaseConflict

ADMIN = PublicUser(id=7, username="admin", role="admin", status="active")


@pytest.mark.asyncio
async def test_create_release_passes_admin_actor_to_service(monkeypatch):
    service = AsyncMock()
    service.create_draft.return_value = {"id": 12, "status": "draft"}
    monkeypatch.setattr(model_release_api, "get_model_release_service", lambda: service)

    result = await model_release_api.create_release(
        9,
        EnterpriseModelReleaseCreatePayload(
            semantic_snapshot_id=10,
            ontology_release_id=20,
        ),
        ADMIN,
    )

    service.create_draft.assert_awaited_once()
    assert service.create_draft.await_args.args[2] == 7
    assert result["release"] == {"id": 12, "status": "draft"}


@pytest.mark.asyncio
async def test_activate_release_maps_state_conflict_to_http_409(monkeypatch):
    service = AsyncMock()
    service.activate_release.side_effect = ModelReleaseConflict("版本尚未通过校验")
    monkeypatch.setattr(model_release_api, "get_model_release_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await model_release_api.activate_release(9, 12, ADMIN)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "版本尚未通过校验"


def test_model_release_routes_are_registered():
    paths = {route.path for route in app.routes}

    assert "/api/model-releases/domains/{domain_id}/releases" in paths
    assert "/api/model-releases/domains/{domain_id}/releases/{release_id}/validate" in paths
    assert "/api/model-releases/domains/{domain_id}/releases/{release_id}/activate" in paths
    assert "/api/model-releases/domains/{domain_id}/releases/{release_id}/deactivate" in paths
    assert "/api/model-releases/domains/{domain_id}/releases/{release_id}/rollback" in paths
