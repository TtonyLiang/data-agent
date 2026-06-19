from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AssetType = Literal["concept", "relation", "metric", "rule", "mapping", "template"]


class SemanticDomain(BaseModel):
    id: int | None = None
    agent_id: int
    datasource_id: int | None = None
    domain_key: str
    name: str
    description: str | None = ""
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SemanticConcept(BaseModel):
    id: int | None = None
    domain_id: int
    concept_key: str
    concept_type: str
    name: str
    description: str | None = ""
    synonyms: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticRelation(BaseModel):
    id: int | None = None
    domain_id: int
    relation_key: str
    relation_type: str
    source_concept: str
    target_concept: str
    name: str
    description: str | None = ""
    join_path: list[dict[str, str]] = Field(default_factory=list)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticMetric(BaseModel):
    id: int | None = None
    domain_id: int
    metric_key: str
    name: str
    description: str | None = ""
    synonyms: list[str] = Field(default_factory=list)
    metric_type: str = "measure"
    formula_sql: str
    aggregation: str | None = None
    base_table: str
    time_field: str | None = None
    default_filters: list[dict[str, Any]] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticRule(BaseModel):
    id: int | None = None
    domain_id: int
    rule_key: str
    rule_type: str
    name: str
    description: str | None = ""
    expression: dict[str, Any] = Field(default_factory=dict)
    applies_to: list[str] = Field(default_factory=list)
    severity: str = "info"


class SemanticMapping(BaseModel):
    id: int | None = None
    domain_id: int
    asset_type: str
    asset_key: str
    table_name: str
    column_name: str | None = None
    expression_sql: str | None = None
    data_type: str | None = None
    role: str = "field"
    filters: list[dict[str, Any]] = Field(default_factory=list)


class LogicFormTemplate(BaseModel):
    id: int | None = None
    domain_id: int
    template_key: str
    intent_type: str
    name: str
    description: str | None = ""
    required_slots: list[str] = Field(default_factory=list)
    optional_slots: list[str] = Field(default_factory=list)
    compile_strategy: dict[str, Any] = Field(default_factory=dict)
    examples: list[str] = Field(default_factory=list)


class SemanticAssetPayload(BaseModel):
    asset_type: AssetType
    data: dict[str, Any]


class LogicFilter(BaseModel):
    field: str
    operator: str = "="
    value: Any


class LogicSort(BaseModel):
    field: str
    direction: Literal["asc", "desc"] = "desc"


class LogicTimeRange(BaseModel):
    type: str = "relative"
    period: str | None = None
    start: str | None = None
    end: str | None = None


class LogicForm(BaseModel):
    intent_type: str = "metric_query"
    domain_key: str = "loan_risk"
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[LogicFilter] = Field(default_factory=list)
    time_range: LogicTimeRange | None = None
    grain: str | None = None
    sort: list[LogicSort] = Field(default_factory=list)
    limit: int | None = None


class SemanticRuntime(BaseModel):
    domain: SemanticDomain
    concepts: list[SemanticConcept] = Field(default_factory=list)
    relations: list[SemanticRelation] = Field(default_factory=list)
    metrics: list[SemanticMetric] = Field(default_factory=list)
    rules: list[SemanticRule] = Field(default_factory=list)
    mappings: list[SemanticMapping] = Field(default_factory=list)
    templates: list[LogicFormTemplate] = Field(default_factory=list)


class LogicFormValidation(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    used_assets: list[str] = Field(default_factory=list)


class CompiledQuery(BaseModel):
    logic_form: LogicForm
    sql: str
    used_assets: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AgentKnowledge(BaseModel):
    id: int | None = None
    agent_id: int
    title: str
    content: str
    knowledge_type: str = "document"
    chunk_count: int = 0
    created_at: datetime | None = None
