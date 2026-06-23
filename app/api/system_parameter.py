"""系统参数管理 API —— 运行时可调参数的查询与更新。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import require_admin
from app.models.system_parameter import SystemParameterUpdate
from app.services.system_parameter_service import get_system_parameter_service

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/parameters")
async def list_system_parameters(category: str | None = Query(default=None)):
    """列出系统参数,可按 category 过滤。"""
    params = await get_system_parameter_service().list(category)
    return {"parameters": params}


@router.put("/parameters")
async def update_system_parameters(updates: list[SystemParameterUpdate]):
    """批量更新系统参数。只允许更新已存在的 key。"""
    try:
        params = await get_system_parameter_service().update_many(updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"parameters": params, "message": "系统参数已更新"}
