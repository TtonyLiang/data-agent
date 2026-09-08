"""Observable twin-runtime synchronization API."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, require_domain_access
from app.models.twin_runtime import TwinSyncRequest
from app.models.user import PublicUser
from app.services.semantic_runtime import get_semantic_runtime_service
from app.services.twin_runtime_service import get_twin_runtime_service

router = APIRouter()


async def _resolve_access_agent(domain_id: int, access_agent_id: int | None) -> int:
    if isinstance(access_agent_id, int) and access_agent_id > 0:
        return access_agent_id
    resolved = await get_semantic_runtime_service().resolve_domain_agent(domain_id)
    if resolved is None:
        raise HTTPException(status_code=403, detail="领域没有可用于数据权限校验的验证智能体")
    return resolved


@router.post("/domains/{domain_id}/sync-runs")
async def create_sync_run(
    domain_id: int,
    payload: TwinSyncRequest,
    current_user: PublicUser = Depends(get_current_user),
):
    if not payload.dry_run and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以启动写入型孪生同步")
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
