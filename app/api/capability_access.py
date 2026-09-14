"""Management and external invocation API for published Query Capabilities."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query

from app.api.deps import require_data_engineer
from app.models.capability_access import (
    CapabilityClientCreatePayload,
    CapabilityClientStatusPayload,
    CapabilityGrantUpsertPayload,
    CapabilityInvocationResponse,
    CapabilityInvokePayload,
)
from app.models.query_capability import CAPABILITY_KEY_PATTERN
from app.models.user import PublicUser
from app.services.capability_access_service import (
    CapabilityAccessError,
    CapabilityAuthenticationError,
    CapabilityAuthorizationError,
    CapabilityClientNotFound,
    CapabilityConfigurationError,
    get_capability_access_service,
)

router = APIRouter()


def _error_detail(exc: CapabilityAccessError):
    if exc.trace_id:
        return {"message": str(exc), "trace_id": exc.trace_id}
    return str(exc)


async def get_capability_client(
    client_key: Annotated[str | None, Header(alias="X-Capability-Key")] = None,
    client_secret: Annotated[str | None, Header(alias="X-Capability-Secret")] = None,
) -> dict:
    try:
        return await get_capability_access_service().authenticate_client(
            client_key or "", client_secret or ""
        )
    except CapabilityAuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/capability-clients", status_code=201)
async def create_client(
    payload: CapabilityClientCreatePayload,
    current_user: PublicUser = Depends(require_data_engineer),
):
    credential = await get_capability_access_service().create_client(
        payload, created_by=current_user.id
    )
    return {"credential": credential, "message": "调用凭据已创建，密钥仅返回本次"}


@router.get("/capability-clients")
async def list_clients(_: PublicUser = Depends(require_data_engineer)):
    return {"clients": await get_capability_access_service().list_clients()}


@router.patch("/capability-clients/{client_id}")
async def update_client_status(
    client_id: int,
    payload: CapabilityClientStatusPayload,
    _: PublicUser = Depends(require_data_engineer),
):
    try:
        client = await get_capability_access_service().set_client_status(
            client_id, payload.status
        )
    except CapabilityClientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"client": client, "message": "调用方状态已更新"}


@router.put("/capability-clients/{client_id}/grants")
async def upsert_grant(
    client_id: int,
    payload: CapabilityGrantUpsertPayload,
    current_user: PublicUser = Depends(require_data_engineer),
):
    try:
        grant = await get_capability_access_service().upsert_grant(
            client_id, payload, actor_id=current_user.id
        )
    except CapabilityClientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CapabilityConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"grant": grant, "message": "能力授权已保存"}


@router.get("/capability-clients/{client_id}/grants")
async def list_grants(client_id: int, _: PublicUser = Depends(require_data_engineer)):
    try:
        grants = await get_capability_access_service().list_grants(client_id)
    except CapabilityClientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"grants": grants}


@router.get("/capability-invocations")
async def list_invocation_audits(
    client_id: int | None = Query(default=None, gt=0),
    domain_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    _: PublicUser = Depends(require_data_engineer),
):
    audits = await get_capability_access_service().list_invocation_audits(
        client_id=client_id,
        domain_id=domain_id,
        limit=limit,
    )
    return {"invocations": audits}


@router.get("/v1/capabilities")
async def list_capabilities(
    domain_id: int = Query(..., gt=0),
    client: dict = Depends(get_capability_client),
):
    try:
        return await get_capability_access_service().list_granted_capabilities(
            client, domain_id
        )
    except CapabilityAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=_error_detail(exc)) from exc
    except CapabilityConfigurationError as exc:
        raise HTTPException(status_code=409, detail=_error_detail(exc)) from exc


@router.post(
    "/v1/capabilities/{capability_key}:invoke",
    response_model=CapabilityInvocationResponse,
)
async def invoke_capability(
    capability_key: Annotated[
        str,
        Path(min_length=1, max_length=128, pattern=CAPABILITY_KEY_PATTERN),
    ],
    payload: CapabilityInvokePayload,
    client: dict = Depends(get_capability_client),
):
    try:
        return await get_capability_access_service().invoke(client, capability_key, payload)
    except CapabilityAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=_error_detail(exc)) from exc
    except CapabilityConfigurationError as exc:
        raise HTTPException(status_code=409, detail=_error_detail(exc)) from exc
    except CapabilityAccessError as exc:
        raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc
