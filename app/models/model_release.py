"""Request and response models for unified enterprise model releases."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

EnterpriseModelReleaseStatus = Literal["draft", "validated", "active", "retired"]


class EnterpriseModelReleaseCreatePayload(BaseModel):
    semantic_snapshot_id: int = Field(gt=0)
    ontology_release_id: int = Field(gt=0)
    name: str | None = Field(default=None, max_length=256)
    description: str = Field(default="", max_length=20_000)

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class EnterpriseModelValidationPayload(BaseModel):
    errors: list[str] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=200)
    checks: dict[str, Any] = Field(default_factory=dict)


class EnterpriseModelRelease(BaseModel):
    id: int
    domain_id: int
    version: int
    name: str
    description: str | None = ""
    semantic_snapshot_id: int
    ontology_release_id: int
    status: EnterpriseModelReleaseStatus
    semantic_snapshot_hash: str
    ontology_definition_hash: str
    model_hash: str
    validation: dict[str, Any] | None = None
    created_by: int | None = None
    validated_by: int | None = None
    activated_by: int | None = None
    retired_by: int | None = None
    previous_active_release_id: int | None = None
    validated_at: datetime | str | None = None
    activated_at: datetime | str | None = None
    retired_at: datetime | str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
