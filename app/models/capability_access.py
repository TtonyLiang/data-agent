"""Contracts for third-party capability identities, grants, and invocation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.knowledge import LogicForm
from app.models.query_capability import CAPABILITY_KEY_PATTERN


class CapabilityClientCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=20_000)

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class CapabilityClientStatusPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "disabled"]


class CapabilityClient(BaseModel):
    id: int
    client_key: str
    name: str
    description: str | None = ""
    status: Literal["active", "disabled"]
    created_by: int | None = None
    last_used_at: datetime | str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class CapabilityClientCredential(BaseModel):
    client: CapabilityClient
    client_key: str
    client_secret: str
    secret_returned_once: Literal[True] = True


class CapabilityGrantUpsertPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: int = Field(gt=0)
    capability_key: str = Field(pattern=CAPABILITY_KEY_PATTERN, max_length=128)
    execution_agent_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "兼容旧调用方的内部权限适配覆盖值；省略时由平台按业务领域自动解析"
        ),
    )
    status: Literal["active", "revoked"] = "active"


class CapabilityGrant(BaseModel):
    id: int
    client_id: int
    domain_id: int
    capability_key: str
    execution_agent_id: int | None = None
    model_release_id: int | None = None
    contract_hash: str | None = None
    contract_json: dict[str, Any] | None = None
    status: Literal["active", "revoked"]
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class CapabilityInvokePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: int = Field(gt=0)
    model_release_id: int | None = Field(default=None, gt=0)
    logic_form: LogicForm


class CapabilityInvocationResponse(BaseModel):
    trace_id: str
    domain_id: int
    capability_key: str
    status: str
    latency_ms: float
    result: dict[str, Any]


class CapabilityInvocationAudit(BaseModel):
    id: int
    trace_id: str
    client_id: int
    grant_id: int | None = None
    domain_id: int
    capability_key: str
    execution_agent_id: int | None = None
    model_release_id: int | None = None
    semantic_snapshot_id: int | None = None
    ontology_release_id: int | None = None
    status: str
    latency_ms: float
    row_count: int
    error_category: str | None = None
    error_message: str | None = None
    request_summary: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | str | None = None
