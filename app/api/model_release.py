"""Administrative API for unified enterprise model release lifecycle."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_model_editor, require_model_publisher
from app.models.model_release import (
    EnterpriseModelReleaseCreatePayload,
    EnterpriseModelValidationPayload,
)
from app.models.user import PublicUser
from app.services.model_release_service import (
    ModelReleaseConflict,
    ModelReleaseNotFound,
    get_model_release_service,
)

router = APIRouter()


def _not_found(exc: ModelReleaseNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _conflict(exc: ModelReleaseConflict) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/domains/{domain_id}/releases")
async def list_releases(domain_id: int, _: PublicUser = Depends(require_model_editor)):
    try:
        releases = await get_model_release_service().list_releases(domain_id)
    except ModelReleaseNotFound as exc:
        raise _not_found(exc) from exc
    return {"releases": releases}


@router.get("/domains/{domain_id}/releases/{release_id}")
async def get_release(
    domain_id: int,
    release_id: int,
    _: PublicUser = Depends(require_model_editor),
):
    try:
        return {"release": await get_model_release_service().get_release(domain_id, release_id)}
    except ModelReleaseNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/domains/{domain_id}/releases", status_code=201)
async def create_release(
    domain_id: int,
    payload: EnterpriseModelReleaseCreatePayload,
    current_user: PublicUser = Depends(require_model_editor),
):
    try:
        release = await get_model_release_service().create_draft(
            domain_id, payload, current_user.id
        )
    except ModelReleaseNotFound as exc:
        raise _not_found(exc) from exc
    except ModelReleaseConflict as exc:
        raise _conflict(exc) from exc
    return {"release": release, "message": "企业模型草稿已创建"}


@router.post("/domains/{domain_id}/releases/{release_id}/validate")
async def validate_release(
    domain_id: int,
    release_id: int,
    payload: EnterpriseModelValidationPayload,
    current_user: PublicUser = Depends(require_model_editor),
):
    try:
        release = await get_model_release_service().validate_release(
            domain_id, release_id, payload, current_user.id
        )
    except ModelReleaseNotFound as exc:
        raise _not_found(exc) from exc
    except ModelReleaseConflict as exc:
        raise _conflict(exc) from exc
    return {"release": release, "message": "企业模型版本校验已完成"}


@router.post("/domains/{domain_id}/releases/{release_id}/activate")
async def activate_release(
    domain_id: int,
    release_id: int,
    current_user: PublicUser = Depends(require_model_publisher),
):
    try:
        release = await get_model_release_service().activate_release(
            domain_id, release_id, current_user.id
        )
    except ModelReleaseNotFound as exc:
        raise _not_found(exc) from exc
    except ModelReleaseConflict as exc:
        raise _conflict(exc) from exc
    return {"release": release, "message": "企业模型版本已激活"}


@router.post("/domains/{domain_id}/releases/{release_id}/deactivate")
async def deactivate_release(
    domain_id: int,
    release_id: int,
    current_user: PublicUser = Depends(require_model_publisher),
):
    try:
        release = await get_model_release_service().deactivate_release(
            domain_id, release_id, current_user.id
        )
    except ModelReleaseNotFound as exc:
        raise _not_found(exc) from exc
    except ModelReleaseConflict as exc:
        raise _conflict(exc) from exc
    return {"release": release, "message": "企业模型版本已停用"}


@router.post("/domains/{domain_id}/releases/{release_id}/rollback")
async def rollback_release(
    domain_id: int,
    release_id: int,
    current_user: PublicUser = Depends(require_model_publisher),
):
    try:
        release = await get_model_release_service().rollback_release(
            domain_id, release_id, current_user.id
        )
    except ModelReleaseNotFound as exc:
        raise _not_found(exc) from exc
    except ModelReleaseConflict as exc:
        raise _conflict(exc) from exc
    return {"release": release, "message": "企业模型版本已回滚并激活"}
