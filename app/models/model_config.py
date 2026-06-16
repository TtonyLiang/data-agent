from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ModelConfigType = Literal["chat", "embedding"]


class ModelConfig(BaseModel):
    id: int | None = None
    name: str
    model_type: ModelConfigType = "chat"
    provider: str = "ollama"
    base_url: str
    model_name: str
    api_key: str | None = None
    api_key_enabled: bool = False
    embedding_dimension: int | None = None
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ModelConfigCreate(BaseModel):
    name: str
    model_type: ModelConfigType = "chat"
    provider: str = "ollama"
    base_url: str
    model_name: str
    api_key: str | None = None
    api_key_enabled: bool = False
    embedding_dimension: int | None = Field(default=None, ge=1)
    status: str = "active"


class ModelConfigUpdate(ModelConfigCreate):
    pass
