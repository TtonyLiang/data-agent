from datetime import datetime

from pydantic import BaseModel


class AgentConfig(BaseModel):
    id: int | None = None
    name: str
    description: str = ""
    chat_model_config_id: int | None = None
    embedding_model_config_id: int | None = None
    semantic_domain_id: int | None = None
    chat_model_config_name: str | None = None
    embedding_model_config_name: str | None = None
    semantic_domain_name: str | None = None
    semantic_domain_key: str | None = None
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:14b"
    api_key: str | None = None
    api_key_enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    chat_model_config_id: int | None = None
    embedding_model_config_id: int | None = None
    semantic_domain_id: int | None = None
    datasource_ids: list[int] = []
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:14b"
