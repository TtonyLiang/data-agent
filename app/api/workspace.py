"""单公司内部兼容容器只读 API。

仅为迁移和旧客户端保留，不能作为多租户或多企业空间产品入口。
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
        raise HTTPException(status_code=404, detail="内部兼容容器不存在")
    domains = await service.list_domains(workspace_id)
    return {
        "workspace": workspace.model_dump(),
        "domains": [item.model_dump() for item in domains],
    }
