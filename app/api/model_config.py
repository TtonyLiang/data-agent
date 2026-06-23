"""模型配置管理 API —— 大语言模型与向量模型的连接配置 CRUD 和连通性测试。"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import require_admin
from app.models.model_config import ModelConfigCreate, ModelConfigType, ModelConfigUpdate
from app.services.model_config_service import get_model_config_service

router = APIRouter(dependencies=[Depends(require_admin)])


@router.post("/create")
async def create_model_config(config: ModelConfigCreate):
    """创建模型配置。"""
    config_id = await get_model_config_service().create(config)
    return {"id": config_id, "message": "模型配置创建成功"}


@router.get("/list")
async def list_model_configs(model_type: ModelConfigType | None = Query(default=None)):
    """列出模型配置,可按类型(chat/embedding)过滤。"""
    configs = await get_model_config_service().list(model_type)
    return {"configs": configs}


@router.put("/{config_id}")
async def update_model_config(config_id: int, config: ModelConfigUpdate):
    """更新模型配置。API Key 为空或掩码时保留原密钥。"""
    updated = await get_model_config_service().update(config_id, config)
    if updated is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {
        "config": updated.model_dump(exclude={"api_key"}),
        "message": "更新成功",
    }


@router.post("/{config_id}/test")
async def test_model_config(config_id: int):
    """测试模型连通性。"""
    result = await get_model_config_service().test_connection(config_id)
    if result.get("message") == "模型配置不存在":
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return result


@router.delete("/{config_id}")
async def delete_model_config(config_id: int):
    """删除模型配置。"""
    await get_model_config_service().delete(config_id)
    return {"message": "删除成功"}
