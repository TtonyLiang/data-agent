"""Twin-runtime synchronization request and response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TwinSyncStatus = Literal["running", "succeeded", "partial", "failed"]


class TwinSyncRequest(BaseModel):
    object_type_id: int | None = Field(default=None, gt=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=200, ge=1, le=1000)
    sync_links: bool = True
    dry_run: bool = False
    trace_id: str | None = Field(default=None, min_length=1, max_length=128)


class TwinSyncRun(BaseModel):
    id: int
    domain_id: int
    object_type_id: int | None = None
    model_release_id: int | None = None
    datasource_id: int
    caller_agent_id: int | None = None
    trace_id: str
    trigger_type: str
    dry_run: bool
    status: TwinSyncStatus
    page: int
    page_size: int
    sync_links: bool
    statistics_json: dict[str, Any] = Field(default_factory=dict)
    error_summary: str | None = None
    created_by: int | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None
