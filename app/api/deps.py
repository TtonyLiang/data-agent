"""FastAPI 认证与权限依赖。"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from app.models.user import (
    PublicUser,
    is_model_editor_role,
    is_model_publisher_role,
    is_technical_role,
)
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
    """Compatibility guard for technical/platform management surfaces.

    The product-facing technical role replaces the old administrator-only
    boundary.  ``admin`` remains accepted for existing installations.
    """
    if not is_technical_role(current_user.role):
        raise HTTPException(status_code=403, detail="无权访问管理功能")
    return current_user


async def require_model_editor(
    current_user: PublicUser = Depends(get_current_user),
) -> PublicUser:
    """Allow business personnel and technical engineers to maintain model drafts.

    ``admin`` remains a compatibility super-role.  This is intentionally a
    narrow product permission and does not grant data-source or platform
    administration access.
    """
    if not is_model_editor_role(current_user.role):
        detail = (
            "无权访问管理功能"
            if current_user.role == "user"
            else "只有业务人员或技术工程师可以维护企业模型"
        )
        raise HTTPException(status_code=403, detail=detail)
    return current_user


async def require_data_engineer(
    current_user: PublicUser = Depends(get_current_user),
) -> PublicUser:
    """Allow technical engineers and legacy administrators to manage data."""
    if not is_technical_role(current_user.role):
        detail = (
            "无权访问管理功能"
            if current_user.role == "user"
            else "只有技术工程师可以维护数据接入与运行配置"
        )
        raise HTTPException(status_code=403, detail=detail)
    return current_user


async def require_model_publisher(
    current_user: PublicUser = Depends(get_current_user),
) -> PublicUser:
    """Allow technical engineers/admins to activate and roll back releases."""
    if not is_model_publisher_role(current_user.role):
        detail = (
            "无权访问管理功能"
            if current_user.role == "user"
            else "只有技术工程师可以发布或回滚企业模型"
        )
        raise HTTPException(status_code=403, detail=detail)
    return current_user


async def require_agent_access(agent_id: int, current_user: PublicUser) -> None:
    """校验当前用户是否可访问指定智能体。"""
    # Modern product roles use the enterprise model directly.  Agent access is
    # retained only for the old validation-client compatibility role.
    if is_model_editor_role(current_user.role) or is_technical_role(current_user.role):
        return
    if not await get_user_service().can_access_agent(current_user, agent_id):
        raise HTTPException(status_code=403, detail="无权访问该智能体")


async def require_domain_access(domain_id: int, current_user: PublicUser) -> int | None:
    """校验领域访问，并为兼容账号返回实际使用的 Agent ID。"""
    from app.services.semantic_runtime import get_semantic_runtime_service

    semantic_service = get_semantic_runtime_service()
    if await semantic_service.get_domain(domain_id) is None:
        raise HTTPException(status_code=404, detail="企业业务领域不存在")
    if is_model_editor_role(current_user.role) or is_technical_role(current_user.role):
        return None
    agent_ids = await get_user_service().get_user_agent_ids(current_user.id)
    for agent_id in agent_ids:
        if await semantic_service.is_domain_bound_to_agent(domain_id, agent_id):
            return agent_id
    raise HTTPException(status_code=403, detail="无权访问该企业业务领域")


def is_admin(user: PublicUser) -> bool:
    return is_technical_role(user.role)
