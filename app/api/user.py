"""用户管理 API。"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_admin
from app.models.user import PasswordResetRequest, PublicUser, UserAgentPermissionUpdate, UserCreate, UserUpdate
from app.services.user_service import get_user_service, public_user_from_row

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("")
async def list_users():
    users = await get_user_service().list_users()
    return {"users": [user.model_dump() for user in users]}


@router.post("")
async def create_user(payload: UserCreate):
    try:
        user_id = await get_user_service().create_user(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = await get_user_service().get_user_by_id(user_id)
    return {
        "id": user_id,
        "user": public_user_from_row(row).model_dump() if row else None,
        "message": "用户已创建",
    }


@router.put("/{user_id}")
async def update_user(user_id: int, payload: UserUpdate):
    user = await get_user_service().update_user(user_id, payload)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"user": user.model_dump(), "message": "用户已更新"}


@router.post("/{user_id}/disable")
async def disable_user(user_id: int):
    user = await get_user_service().set_status(user_id, "disabled")
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"user": user.model_dump(), "message": "用户已禁用"}


@router.post("/{user_id}/enable")
async def enable_user(user_id: int):
    user = await get_user_service().set_status(user_id, "active")
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"user": user.model_dump(), "message": "用户已启用"}


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: int, payload: PasswordResetRequest):
    try:
        ok = await get_user_service().reset_password(
            user_id,
            payload.password,
            must_change_password=payload.must_change_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"message": "密码已重置"}


@router.get("/{user_id}/agents")
async def get_user_agents(user_id: int):
    if not await get_user_service().get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"agent_ids": await get_user_service().get_user_agent_ids(user_id)}


@router.put("/{user_id}/agents")
async def update_user_agents(user_id: int, payload: UserAgentPermissionUpdate):
    if not await get_user_service().get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    ids = await get_user_service().set_user_agent_ids(user_id, payload.agent_ids)
    return {"agent_ids": ids, "message": "智能体权限已保存"}
