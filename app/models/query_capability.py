"""Read-only Query Capability contracts.

The contracts in this module are deliberately independent from the existing
semantic and Ontology models.  They describe the application-facing boundary
for a query and can be backed by the current LogicForm/SemanticRuntime path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.knowledge import LogicForm, SemanticRuntime

CAPABILITY_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,127}$"
OBJECT_KEY_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,127}$"


class QueryCapabilityInputSlot(BaseModel):
    """One named input slot accepted by a query capability."""

    slot_key: str = Field(pattern=OBJECT_KEY_PATTERN, max_length=128)
    data_type: str = Field(default="string", min_length=1, max_length=64)
    required: bool = False
    description: str = ""
    aliases: list[str] = Field(default_factory=list)


class QueryCapabilityOutputMetadata(BaseModel):
    """Stable metadata describing a query result without containing data."""

    result_type: Literal["table", "scalar", "object_set", "json"] = "table"
    columns: list[str] = Field(default_factory=list)
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryCapabilityExecutionMetadata(BaseModel):
    """Execution hints for a capability's deterministic read-only backend."""

    compiler: str = Field(default="semantic_runtime", min_length=1, max_length=128)
    mode: str = Field(default="deterministic", min_length=1, max_length=64)
    max_limit: int = Field(default=1000, ge=1, le=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryCapability(BaseModel):
    """A stable, read-only business query contract.

    ``supported_metrics`` and ``supported_dimensions`` define the capability
    boundary.  The actual LogicForm and SemanticRuntime remain existing
    project models and are supplied at validation/compile time.
    """

    key: str = Field(pattern=CAPABILITY_KEY_PATTERN, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str = ""
    target_object: str = Field(pattern=OBJECT_KEY_PATTERN, max_length=128)
    domain_key: str | None = Field(default=None, max_length=128)
    supported_metrics: list[str] = Field(default_factory=list)
    supported_dimensions: list[str] = Field(default_factory=list)
    input_slots: list[QueryCapabilityInputSlot] = Field(default_factory=list)
    output: QueryCapabilityOutputMetadata = Field(
        default_factory=QueryCapabilityOutputMetadata
    )
    execution: QueryCapabilityExecutionMetadata = Field(
        default_factory=QueryCapabilityExecutionMetadata
    )
    read_only: Literal[True] = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_contract_keys(self) -> "QueryCapability":
        for field_name in ("supported_metrics", "supported_dimensions"):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} 不能包含重复标识")

        slot_keys = [slot.slot_key for slot in self.input_slots]
        if len(slot_keys) != len(set(slot_keys)):
            raise ValueError("input_slots 不能包含重复标识")
        return self

    @classmethod
    def from_logic_form(
        cls,
        key: str,
        logic_form: LogicForm,
        runtime: SemanticRuntime | Mapping[str, Any] | None = None,
        ontology_context: Mapping[str, Any] | None = None,
        *,
        target_object: str | None = None,
        name: str | None = None,
        description: str = "",
        input_slots: list[QueryCapabilityInputSlot] | None = None,
        output: QueryCapabilityOutputMetadata | None = None,
        execution: QueryCapabilityExecutionMetadata | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "QueryCapability":
        """Build a capability contract from an existing LogicForm.

        The LogicForm supplies the supported metric/dimension boundary.  The
        target object should normally come from the Ontology context; it may
        also be supplied explicitly when the context contains several objects.
        """

        logic_form = LogicForm.model_validate(logic_form)
        runtime_model = _coerce_runtime(runtime)
        resolved_target = target_object or _infer_target_object(
            runtime_model, ontology_context
        )
        if not resolved_target:
            raise ValueError("无法从 Ontology context 推断 target_object，请显式提供")

        return cls(
            key=key,
            name=name or key.replace("_", " ").title(),
            description=description,
            target_object=resolved_target,
            domain_key=(
                logic_form.domain_key
                or (runtime_model.domain.domain_key if runtime_model else None)
            ),
            supported_metrics=list(dict.fromkeys(logic_form.metrics)),
            supported_dimensions=list(dict.fromkeys(logic_form.dimensions)),
            input_slots=input_slots or _logic_form_slots(logic_form),
            output=output or QueryCapabilityOutputMetadata(),
            execution=execution or QueryCapabilityExecutionMetadata(),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_runtime(
        cls,
        key: str,
        runtime: SemanticRuntime | Mapping[str, Any],
        ontology_context: Mapping[str, Any] | None = None,
        *,
        target_object: str | None = None,
        name: str | None = None,
        description: str = "",
        input_slots: list[QueryCapabilityInputSlot] | None = None,
        output: QueryCapabilityOutputMetadata | None = None,
        execution: QueryCapabilityExecutionMetadata | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "QueryCapability":
        """Build a broad query contract from one existing semantic runtime."""

        runtime_model = _coerce_runtime(runtime)
        assert runtime_model is not None
        resolved_target = target_object or _infer_target_object(runtime_model, ontology_context)
        if not resolved_target:
            raise ValueError("无法从 Ontology context 推断 target_object，请显式提供")

        dimensions = [
            mapping.asset_key
            for mapping in runtime_model.mappings
            if mapping.role in {"dimension", "filter", "time"}
        ]
        return cls(
            key=key,
            name=name or key.replace("_", " ").title(),
            description=description,
            target_object=resolved_target,
            domain_key=runtime_model.domain.domain_key,
            supported_metrics=[metric.metric_key for metric in runtime_model.metrics],
            supported_dimensions=list(dict.fromkeys(dimensions)),
            input_slots=input_slots or _default_input_slots(),
            output=output or QueryCapabilityOutputMetadata(),
            execution=execution or QueryCapabilityExecutionMetadata(),
            metadata=dict(metadata or {}),
        )


class QueryCapabilityValidation(BaseModel):
    """Result of validating a LogicForm against one capability boundary."""

    capability_key: str
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    used_metrics: list[str] = Field(default_factory=list)
    used_dimensions: list[str] = Field(default_factory=list)


def _coerce_runtime(
    runtime: SemanticRuntime | Mapping[str, Any] | None,
) -> SemanticRuntime | None:
    if runtime is None:
        return None
    return SemanticRuntime.model_validate(runtime)


def _infer_target_object(
    runtime: SemanticRuntime | None,
    ontology_context: Mapping[str, Any] | None,
) -> str | None:
    if ontology_context:
        object_types = ontology_context.get("object_types") or []
        object_keys = [
            str(item.get("object_key"))
            for item in object_types
            if isinstance(item, Mapping) and item.get("object_key")
        ]
        if len(object_keys) == 1:
            return object_keys[0]

    if runtime:
        entity_keys = [
            concept.concept_key
            for concept in runtime.concepts
            if concept.concept_type == "entity"
        ]
        if len(entity_keys) == 1:
            return entity_keys[0]
    return None


def _default_input_slots() -> list[QueryCapabilityInputSlot]:
    return [
        QueryCapabilityInputSlot(
            slot_key="metrics", data_type="string[]", required=True, description="指标 key 列表"
        ),
        QueryCapabilityInputSlot(
            slot_key="dimensions", data_type="string[]", description="分组维度 key 列表"
        ),
        QueryCapabilityInputSlot(
            slot_key="filters", data_type="filter[]", description="过滤条件列表"
        ),
        QueryCapabilityInputSlot(
            slot_key="time_range", data_type="time_range", description="时间窗口"
        ),
        QueryCapabilityInputSlot(
            slot_key="grain", data_type="string", description="时间粒度"
        ),
        QueryCapabilityInputSlot(
            slot_key="sort", data_type="sort[]", description="排序项列表"
        ),
        QueryCapabilityInputSlot(
            slot_key="limit", data_type="integer", description="结果行数限制"
        ),
    ]


def _logic_form_slots(logic_form: LogicForm) -> list[QueryCapabilityInputSlot]:
    slots = _default_input_slots()
    if logic_form.grain is None:
        slots = [slot for slot in slots if slot.slot_key != "grain"]
    if logic_form.limit is None:
        slots = [slot for slot in slots if slot.slot_key != "limit"]
    return slots


__all__ = [
    "CAPABILITY_KEY_PATTERN",
    "QueryCapability",
    "QueryCapabilityExecutionMetadata",
    "QueryCapabilityInputSlot",
    "QueryCapabilityOutputMetadata",
    "QueryCapabilityValidation",
]
