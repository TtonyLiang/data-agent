"""企业空间只读 API。

当前阶段只暴露最小逻辑容器及其领域列表，避免提前引入复杂租户管理。
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_admin
from app.models.user import PublicUser
from app.services.workspace_service import get_workspace_service

router = APIRouter()


@router.get("")
async def list_workspaces(_: PublicUser = Depends(require_admin)):
    workspaces = await get_workspace_service().list_workspaces()
    return {"workspaces": [item.model_dump() for item in workspaces]}


@router.get("/{workspace_id}/domains")
async def list_workspace_domains(
    workspace_id: int,
    _: PublicUser = Depends(require_admin),
):
    service = get_workspace_service()
    workspace = await service.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="企业空间不存在")
    domains = await service.list_domains(workspace_id)
    return {
        "workspace": workspace.model_dump(),
        "domains": [item.model_dump() for item in domains],
    }
