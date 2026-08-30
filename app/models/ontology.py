"""Business Ontology request models.

The product models an operational ontology rather than an RDF/OWL knowledge base:
object and link types describe business reality, while action types describe governed
state changes that can be invoked by people or agents.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Key = str
PropertyType = Literal[
    "string",
    "text",
    "integer",
    "number",
    "boolean",
    "date",
    "datetime",
    "json",
]
KEY_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"


class OntologyProperty(BaseModel):
    property_key: Key = Field(pattern=KEY_PATTERN, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    data_type: PropertyType = "string"
    required: bool = False
    unique: bool = False
    description: str = ""
    default_value: Any = None
    sort_order: int = Field(default=0, ge=0)


class OntologyObjectTypePayload(BaseModel):
    id: int | None = Field(default=None, gt=0)
    domain_id: int = Field(gt=0)
    object_key: Key = Field(pattern=KEY_PATTERN, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str = ""
    primary_property: Key = Field(pattern=KEY_PATTERN, max_length=128)
    display_property: Key | None = Field(default=None, pattern=KEY_PATTERN, max_length=128)
    status: Literal["draft", "active", "deprecated"] = "draft"
    properties: list[OntologyProperty] = Field(default_factory=list)


class OntologyLinkTypePayload(BaseModel):
    id: int | None = Field(default=None, gt=0)
    domain_id: int = Field(gt=0)
    link_key: Key = Field(pattern=KEY_PATTERN, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    source_object_key: Key = Field(pattern=KEY_PATTERN, max_length=128)
    target_object_key: Key = Field(pattern=KEY_PATTERN, max_length=128)
    source_property: Key | None = Field(default=None, pattern=KEY_PATTERN, max_length=128)
    target_property: Key | None = Field(default=None, pattern=KEY_PATTERN, max_length=128)
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"] = (
        "many_to_many"
    )
    description: str = ""
    status: Literal["draft", "active", "deprecated"] = "draft"


class OntologyActionParameter(BaseModel):
    parameter_key: Key = Field(pattern=KEY_PATTERN, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    data_type: PropertyType = "string"
    required: bool = False
    options: list[Any] = Field(default_factory=list)
    description: str = ""


class OntologyPrecondition(BaseModel):
    property: Key = Field(pattern=KEY_PATTERN, max_length=128)
    operator: Literal["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "exists"] = "eq"
    value: Any = None
    message: str = ""


class OntologyEffect(BaseModel):
    property: Key = Field(pattern=KEY_PATTERN, max_length=128)
    value: Any = None


class OntologyActionTypePayload(BaseModel):
    id: int | None = Field(default=None, gt=0)
    domain_id: int = Field(gt=0)
    action_key: Key = Field(pattern=KEY_PATTERN, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    target_object_key: Key = Field(pattern=KEY_PATTERN, max_length=128)
    description: str = ""
    parameters: list[OntologyActionParameter] = Field(default_factory=list)
    preconditions: list[OntologyPrecondition] = Field(default_factory=list)
    effects: list[OntologyEffect] = Field(default_factory=list)
    allowed_roles: list[Literal["admin", "user"]] = Field(
        default_factory=lambda: ["admin"], min_length=1
    )
    requires_approval: bool = False
    status: Literal["draft", "active", "deprecated"] = "draft"


class OntologyObjectPayload(BaseModel):
    id: int | None = Field(default=None, gt=0)
    domain_id: int = Field(gt=0)
    object_type_id: int = Field(gt=0)
    primary_value: str | int | float
    display_name: str | None = Field(default=None, max_length=512)
    properties: dict[str, Any] = Field(default_factory=dict)
    status: Literal["active", "archived"] = "active"

    @field_validator("primary_value", mode="before")
    @classmethod
    def validate_primary_value(cls, value: Any) -> str | int | float:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError("主标识必须是文本或数字")
        if isinstance(value, str) and not value.strip():
            raise ValueError("主标识不能为空")
        if isinstance(value, str) and len(value) > 512:
            raise ValueError("主标识长度不能超过 512")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("主标识必须是有限数字")
        return value


class OntologyLinkPayload(BaseModel):
    domain_id: int = Field(gt=0)
    link_type_id: int = Field(gt=0)
    source_object_id: int = Field(gt=0)
    target_object_id: int = Field(gt=0)
    properties: dict[str, Any] = Field(default_factory=dict)


class OntologyActionExecutePayload(BaseModel):
    target_object_id: int = Field(gt=0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    decision_context: dict[str, Any] = Field(default_factory=dict)
    approval_reference: str | None = Field(default=None, max_length=256)
    expected_version: int | None = Field(default=None, gt=0)
class OntologyPublishPayload(BaseModel):
    name: str | None = Field(default=None, max_length=256)
    description: str = ""


class OntologyImportPayload(BaseModel):
    bundle: dict[str, Any] = Field(min_length=1)
    replace: bool = False


class OntologyAgentToolPayload(BaseModel):
    """Arguments passed to one of the bounded Ontology runtime tools.

    Tool names are selected by the API route, while the arguments remain an
    opaque JSON object so clients can evolve parameter values without adding a
    new endpoint for every action type.  The service validates the actual
    argument keys before dispatching.
    """

    arguments: dict[str, Any] = Field(default_factory=dict)
