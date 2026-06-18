from pydantic import BaseModel


class PromptTemplateBase(BaseModel):
    prompt_key: str
    name: str
    description: str | None = None
    agent_id: int | None = None
    model_config_id: int | None = None
    semantic_domain_id: int | None = None
    template_text: str
    status: str = "active"


class PromptTemplateCreate(PromptTemplateBase):
    id: int | None = None


class PromptTemplateUpdate(PromptTemplateBase):
    pass


class PromptTemplate(PromptTemplateBase):
    id: int
    created_at: str | None = None
    updated_at: str | None = None
