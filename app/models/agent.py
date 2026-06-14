from pydantic import BaseModel
from datetime import datetime


class AgentConfig(BaseModel):
    id: int | None = None
    name: str
    description: str = ""
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:14b"
    api_key: str | None = None
    api_key_enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:14b"
