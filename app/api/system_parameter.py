from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.system_parameter import SystemParameterUpdate
from app.services.system_parameter_service import get_system_parameter_service

router = APIRouter()


@router.get("/parameters")
async def list_system_parameters(category: str | None = Query(default=None)):
    params = await get_system_parameter_service().list(category)
    return {"parameters": params}


@router.put("/parameters")
async def update_system_parameters(updates: list[SystemParameterUpdate]):
    try:
        params = await get_system_parameter_service().update_many(updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"parameters": params, "message": "系统参数已更新"}
