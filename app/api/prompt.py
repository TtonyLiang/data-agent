"""Prompt 模板管理 API —— 节点提示词的配置化管理。"""

from fastapi import APIRouter

from app.agent.prompts import default_prompt_templates
from app.models.prompt import PromptTemplateCreate
from app.services.prompt_service import get_prompt_service

router = APIRouter()


@router.get("/list")
async def list_prompt_templates(prompt_key: str | None = None):
    """列出 Prompt 模板,可按 prompt_key 过滤。"""
    return {"templates": await get_prompt_service().list(prompt_key)}


@router.get("/catalog")
async def list_prompt_catalog():
    """列出代码内置默认 Prompt 清单,供管理台展示节点选项。"""
    return {"prompts": default_prompt_templates()}


@router.post("/templates")
async def upsert_prompt_template(template: PromptTemplateCreate):
    """创建或更新 Prompt 模板。"""
    template_id = await get_prompt_service().upsert(template)
    return {"id": template_id, "message": "Prompt 模板已保存"}


@router.delete("/templates/{template_id}")
async def delete_prompt_template(template_id: int):
    """删除 Prompt 模板。"""
    await get_prompt_service().delete(template_id)
    return {"message": "Prompt 模板已删除"}


@router.post("/resolve")
async def resolve_prompt_template(request: dict):
    """调试用:手动解析 Prompt 模板(模拟节点调用)。"""
    prompt = await get_prompt_service().resolve(
        str(request.get("prompt_key") or ""),
        str(request.get("default_template") or ""),
        agent_id=request.get("agent_id"),
        model_config_id=request.get("model_config_id"),
        semantic_domain_id=request.get("semantic_domain_id"),
        variables=request.get("variables") or {},
    )
    return {"prompt": prompt}
