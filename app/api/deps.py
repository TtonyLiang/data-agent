"""FastAPI 认证与权限依赖。"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from app.models.user import PublicUser
from app.services.user_service import AuthError, PermissionDenied, get_user_service


async def get_current_user(authorization: str | None = Header(default=None)) -> PublicUser:
    """从 Authorization Bearer token 解析当前用户。"""
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    token = authorization[len(prefix) :].strip()
    try:
        return await get_user_service().get_user_by_token(token)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


async def require_admin(current_user: PublicUser = Depends(get_current_user)) -> PublicUser:
    """要求管理员角色。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权访问管理功能")
    return current_user


async def require_agent_access(agent_id: int, current_user: PublicUser) -> None:
    """校验当前用户是否可访问指定智能体。"""
    if not await get_user_service().can_access_agent(current_user, agent_id):
        raise HTTPException(status_code=403, detail="无权访问该智能体")


async def require_domain_access(domain_id: int, current_user: PublicUser) -> int | None:
    """校验领域访问，并返回普通用户实际通过的 Agent ID。"""
    from app.services.semantic_runtime import get_semantic_runtime_service

    semantic_service = get_semantic_runtime_service()
    if await semantic_service.get_domain(domain_id) is None:
        raise HTTPException(status_code=404, detail="企业业务领域不存在")
    if current_user.role == "admin":
        return None
    agent_ids = await get_user_service().get_user_agent_ids(current_user.id)
    for agent_id in agent_ids:
        if await semantic_service.is_domain_bound_to_agent(domain_id, agent_id):
            return agent_id
    raise HTTPException(status_code=403, detail="无权访问该企业业务领域")


def is_admin(user: PublicUser) -> bool:
    return user.role == "admin"
