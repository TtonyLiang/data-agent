from typing import Literal

from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    agent_id: int = Field(default=1, ge=1)
    session_id: str | None = None
    trace_id: str | None = None
    rating: Literal["positive", "negative", "neutral"] = "neutral"
    comment: str | None = None
    payload: dict = Field(default_factory=dict)
