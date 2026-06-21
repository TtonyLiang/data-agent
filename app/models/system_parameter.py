from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SystemParameter(BaseModel):
    key: str
    name: str
    value: Any
    value_type: str = "string"
    category: str = "general"
    description: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SystemParameterUpdate(BaseModel):
    key: str
    value: Any


class SchemaRecallSettings(BaseModel):
    max_tables: int = Field(default=6, ge=1, le=50)
    required_score_ratio: float = Field(default=0.35, ge=0, le=1)
    optional_score_ratio: float = Field(default=0.15, ge=0, le=1)

    @field_validator("optional_score_ratio")
    @classmethod
    def optional_not_above_required(cls, value: float, info):
        required = (info.data or {}).get("required_score_ratio")
        if required is not None and value > required:
            raise ValueError("可召回阈值不能大于必须召回阈值")
        return value
