from fastapi import APIRouter

from app.models.prompt import PromptTemplateCreate
from app.services.prompt_service import get_prompt_service

router = APIRouter()


@router.get("/list")
async def list_prompt_templates(prompt_key: str | None = None):
    return {"templates": await get_prompt_service().list(prompt_key)}


@router.post("/templates")
async def upsert_prompt_template(template: PromptTemplateCreate):
    template_id = await get_prompt_service().upsert(template)
    return {"id": template_id, "message": "Prompt 模板已保存"}


@router.delete("/templates/{template_id}")
async def delete_prompt_template(template_id: int):
    await get_prompt_service().delete(template_id)
    return {"message": "Prompt 模板已删除"}


@router.post("/resolve")
async def resolve_prompt_template(request: dict):
    prompt = await get_prompt_service().resolve(
        str(request.get("prompt_key") or ""),
        str(request.get("default_template") or ""),
        agent_id=request.get("agent_id"),
        model_config_id=request.get("model_config_id"),
        semantic_domain_id=request.get("semantic_domain_id"),
        variables=request.get("variables") or {},
    )
    return {"prompt": prompt}
