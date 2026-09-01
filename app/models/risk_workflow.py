"""Request models for the risk review and report delivery workflow."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

KEY_PATTERN = r"^[A-Za-z][A-Za-z0-9_.-]*$"

RiskSeverity = Literal["low", "medium", "high", "critical"]
RiskIssueStatus = Literal[
    "open",
    "in_review",
    "needs_info",
    "confirmed",
    "dismissed",
    "resolved",
]
EvidenceType = Literal["ontology_object", "metric", "query", "document", "manual"]
ReviewAction = Literal[
    "start_review",
    "confirm",
    "dismiss",
    "request_info",
    "resolve",
    "reopen",
]
ReportStatus = Literal["draft", "finalized"]


class RiskIssueCreatePayload(BaseModel):
    domain_id: int = Field(gt=0)
    subject_object_id: int | None = Field(default=None, gt=0)
    issue_key: str = Field(pattern=KEY_PATTERN, max_length=128)
    category: str = Field(min_length=1, max_length=128)
    severity: RiskSeverity = "medium"
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=20_000)
    rule_key: str | None = Field(default=None, pattern=KEY_PATTERN, max_length=128)
    detected_value: Any = None
    expected_value: Any = None
    source_context: dict[str, Any] = Field(default_factory=dict)
    assignee: str | None = Field(default=None, max_length=128)

    @field_validator("category", "title")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("description", "assignee")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class ChatRiskIssueCreatePayload(BaseModel):
    domain_id: int = Field(gt=0)
    agent_id: int = Field(gt=0)
    session_id: str = Field(min_length=1, max_length=64)
    trace_id: str | None = Field(default=None, max_length=128)
    subject_object_id: int | None = Field(default=None, gt=0)
    issue_key: str = Field(pattern=KEY_PATTERN, max_length=128)
    category: str = Field(min_length=1, max_length=128)
    severity: RiskSeverity = "medium"
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=20_000)
    rule_key: str | None = Field(default=None, pattern=KEY_PATTERN, max_length=128)
    expected_value: Any = None
    assignee: str | None = Field(default=None, max_length=128)

    @field_validator("session_id", "category", "title")
    @classmethod
    def strip_required_chat_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("description")
    @classmethod
    def strip_chat_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("trace_id", "assignee")
    @classmethod
    def strip_optional_chat_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class EvidenceCreatePayload(BaseModel):
    evidence_type: EvidenceType
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=20_000)
    source_ref: str | None = Field(default=None, max_length=1024)
    content: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = Field(default=None, max_length=128)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("证据标题不能为空")
        return value


class RiskReviewPayload(BaseModel):
    action: ReviewAction
    comment: str = Field(default="", max_length=20_000)
    expected_version: int | None = Field(default=None, gt=0)


class ReportCreatePayload(BaseModel):
    domain_id: int = Field(gt=0)
    report_key: str = Field(pattern=KEY_PATTERN, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    report_type: str = Field(min_length=1, max_length=128)
    period_start: date | None = None
    period_end: date | None = None
    status: ReportStatus = "draft"
    issue_ids: list[int] = Field(min_length=1, max_length=1000)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    markdown: str = Field(default="", max_length=2_000_000)

    @model_validator(mode="after")
    def validate_period_and_issues(self) -> "ReportCreatePayload":
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("报告开始日期不能晚于结束日期")
        if any(issue_id <= 0 for issue_id in self.issue_ids):
            raise ValueError("风险事项 ID 必须大于 0")
        if len(self.issue_ids) != len(set(self.issue_ids)):
            raise ValueError("报告风险事项不能重复")
        return self


class ReportVersionCreatePayload(BaseModel):
    issue_ids: list[int] = Field(min_length=1, max_length=1000)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    markdown: str = Field(default="", max_length=2_000_000)
    expected_current_version: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_issue_ids(self) -> "ReportVersionCreatePayload":
        if any(issue_id <= 0 for issue_id in self.issue_ids):
            raise ValueError("风险事项 ID 必须大于 0")
        if len(self.issue_ids) != len(set(self.issue_ids)):
            raise ValueError("报告风险事项不能重复")
        return self


class ReportFinalizePayload(BaseModel):
    expected_version: int | None = Field(default=None, gt=0)
