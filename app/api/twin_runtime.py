"""Observable twin-runtime synchronization API."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, require_domain_access
from app.models.twin_runtime import TwinSyncRequest
from app.models.user import PublicUser, is_technical_role
from app.services.permission_service import (
    domain_permission_not_configured_detail,
    get_permission_service,
)
from app.services.semantic_runtime import get_semantic_runtime_service
from app.services.twin_runtime_service import get_twin_runtime_service

router = APIRouter()


async def _resolve_access_agent(domain_id: int, access_agent_id: int | None) -> int | None:
    semantic_service = get_semantic_runtime_service()
    domain = await semantic_service.get_domain(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="企业业务领域不存在")
    if domain.datasource_id is None:
        return access_agent_id
    datasource_id = int(domain.datasource_id)
    permission_context = (
        await get_permission_service().resolve_domain_permission_context(
            domain_id,
            datasource_id,
            compatibility_agent_id=access_agent_id,
            allow_agent_fallback=bool(access_agent_id),
        )
    )
    if permission_context.source == "domain":
        return None
    if permission_context.source == "agent_compatibility":
        return access_agent_id
    return None


@router.post("/domains/{domain_id}/sync-runs")
async def create_sync_run(
    domain_id: int,
    payload: TwinSyncRequest,
    current_user: PublicUser = Depends(get_current_user),
):
    if not payload.dry_run and not is_technical_role(current_user.role):
        raise HTTPException(status_code=403, detail="只有技术工程师可以启动写入型孪生同步")
    access_agent_id = await require_domain_access(domain_id, current_user)
    permission_agent_id = await _resolve_access_agent(domain_id, access_agent_id)
    try:
        return await get_twin_runtime_service().execute_sync(
            domain_id=domain_id,
            access_agent_id=permission_agent_id,
            created_by=current_user.id,
            object_type_id=payload.object_type_id,
            page=payload.page,
            page_size=payload.page_size,
            sync_links=payload.sync_links,
            dry_run=payload.dry_run,
            trace_id=payload.trace_id,
        )
    except PermissionError as exc:
        if "未配置数据权限" in str(exc):
            domain = await get_semantic_runtime_service().get_domain(domain_id)
            datasource_id = int(domain.datasource_id or 0) if domain is not None else 0
            raise HTTPException(
                status_code=409,
                detail=domain_permission_not_configured_detail(
                    domain_id, datasource_id
                ),
            ) from exc
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/domains/{domain_id}/sync-runs")
async def list_sync_runs(
    domain_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    return {"runs": await get_twin_runtime_service().list_runs(domain_id, limit=limit)}


@router.get("/domains/{domain_id}/sync-runs/{run_id}")
async def get_sync_run(
    domain_id: int,
    run_id: int,
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    run = await get_twin_runtime_service().get_run(domain_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="同步运行记录不存在")
    return {"run": run}
