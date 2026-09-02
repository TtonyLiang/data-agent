"""Registry and facade for read-only Query Capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.models.knowledge import CompiledQuery, LogicForm, SemanticRuntime
from app.models.query_capability import (
    QueryCapability,
    QueryCapabilityValidation,
)
from app.services.semantic_runtime import SemanticRuntimeService


class QueryCapabilityRegistry:
    """In-memory registry for stable Query Capability definitions.

    Persistence is intentionally out of scope for P0.  A caller may build the
    registry from existing runtime/context data during application startup or
    a request, without introducing a database table.
    """

    def __init__(self, capabilities: list[QueryCapability] | None = None):
        self._capabilities: dict[str, QueryCapability] = {}
        for capability in capabilities or []:
            self.register(capability)

    def register(self, capability: QueryCapability, *, replace: bool = False) -> QueryCapability:
        capability = QueryCapability.model_validate(capability)
        if capability.key in self._capabilities and not replace:
            raise ValueError(f"Query Capability 已注册: {capability.key}")
        self._capabilities[capability.key] = capability
        return capability

    def resolve(self, key: str) -> QueryCapability | None:
        return self._capabilities.get(str(key or "").strip())

    def require(self, key: str) -> QueryCapability:
        capability = self.resolve(key)
        if capability is None:
            raise KeyError(f"未知 Query Capability: {key}")
        return capability

    def list(self) -> list[QueryCapability]:
        return list(self._capabilities.values())

    def register_from_logic_form(
        self,
        key: str,
        logic_form: LogicForm,
        runtime: SemanticRuntime | Mapping[str, Any] | None = None,
        ontology_context: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> QueryCapability:
        capability = QueryCapability.from_logic_form(
            key, logic_form, runtime, ontology_context, **kwargs
        )
        return self.register(capability)

    def register_from_runtime(
        self,
        key: str,
        runtime: SemanticRuntime | Mapping[str, Any],
        ontology_context: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> QueryCapability:
        capability = QueryCapability.from_runtime(key, runtime, ontology_context, **kwargs)
        return self.register(capability)


class QueryCapabilityFacade:
    """Application-facing facade for registering, validating, and compiling queries.

    This facade never executes SQL and never calls Ontology action execution.
    Compilation is delegated to the existing deterministic semantic runtime
    compiler, which returns a ``CompiledQuery`` for the existing execution path.
    """

    def __init__(
        self,
        registry: QueryCapabilityRegistry | None = None,
        semantic_runtime_service: SemanticRuntimeService | None = None,
    ):
        self.registry = registry or QueryCapabilityRegistry()
        self.semantic_runtime_service = semantic_runtime_service or SemanticRuntimeService()

    def register(self, capability: QueryCapability, *, replace: bool = False) -> QueryCapability:
        return self.registry.register(capability, replace=replace)

    def resolve(self, key: str) -> QueryCapability | None:
        return self.registry.resolve(key)

    def register_from_logic_form(
        self,
        key: str,
        logic_form: LogicForm,
        runtime: SemanticRuntime | Mapping[str, Any] | None = None,
        ontology_context: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> QueryCapability:
        return self.registry.register_from_logic_form(
            key, logic_form, runtime, ontology_context, **kwargs
        )

    def register_from_runtime(
        self,
        key: str,
        runtime: SemanticRuntime | Mapping[str, Any],
        ontology_context: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> QueryCapability:
        return self.registry.register_from_runtime(key, runtime, ontology_context, **kwargs)

    def validate_capability(
        self,
        capability_key: str,
        logic_form: LogicForm,
        *,
        runtime: SemanticRuntime | Mapping[str, Any] | None = None,
        ontology_context: Mapping[str, Any] | None = None,
    ) -> QueryCapabilityValidation:
        """Validate only the capability boundary, optionally with runtime semantics."""

        logic_form = LogicForm.model_validate(logic_form)
        capability = self.resolve(capability_key)
        if capability is None:
            return QueryCapabilityValidation(
                capability_key=capability_key,
                valid=False,
                errors=[f"未知 Query Capability: {capability_key}"],
            )

        errors: list[str] = []
        warnings: list[str] = []
        supported_metrics = set(capability.supported_metrics)
        supported_dimensions = set(capability.supported_dimensions)
        used_metrics = list(logic_form.metrics)
        used_dimensions = list(logic_form.dimensions)

        unsupported_metrics = [item for item in used_metrics if item not in supported_metrics]
        if unsupported_metrics:
            errors.append(f"Capability 不支持指标: {', '.join(unsupported_metrics)}")

        unsupported_dimensions = [
            item for item in used_dimensions if item not in supported_dimensions
        ]
        if unsupported_dimensions:
            errors.append(f"Capability 不支持维度: {', '.join(unsupported_dimensions)}")

        if capability.domain_key and logic_form.domain_key:
            if capability.domain_key != logic_form.domain_key:
                errors.append(
                    f"Capability 领域不匹配: {logic_form.domain_key} != {capability.domain_key}"
                )

        object_types = (ontology_context or {}).get("object_types") or []
        object_keys = {
            str(item.get("object_key"))
            for item in object_types
            if isinstance(item, Mapping) and item.get("object_key")
        }
        if object_keys and capability.target_object not in object_keys:
            errors.append(f"Capability 目标对象不存在: {capability.target_object}")

        slots = {slot.slot_key: slot for slot in capability.input_slots}
        slot_values = {
            "metrics": logic_form.metrics,
            "dimensions": logic_form.dimensions,
            "filters": logic_form.filters,
            "time_range": logic_form.time_range,
            "grain": logic_form.grain,
            "sort": logic_form.sort,
            "limit": logic_form.limit,
        }
        for slot_key, slot in slots.items():
            if slot.required and not slot_values.get(slot_key):
                errors.append(f"缺少必填输入槽位: {slot_key}")

        runtime_model = _coerce_runtime(runtime)
        if runtime_model is not None:
            semantic_validation = self.semantic_runtime_service.validate_logic_form(
                logic_form, runtime_model
            )
            errors.extend(semantic_validation.errors)
            warnings.extend(semantic_validation.warnings)

        return QueryCapabilityValidation(
            capability_key=capability.key,
            valid=not errors,
            errors=list(dict.fromkeys(errors)),
            warnings=list(dict.fromkeys(warnings)),
            used_metrics=used_metrics,
            used_dimensions=used_dimensions,
        )

    def validate(
        self,
        capability_key: str,
        logic_form: LogicForm,
        *,
        runtime: SemanticRuntime | Mapping[str, Any] | None = None,
        ontology_context: Mapping[str, Any] | None = None,
    ) -> QueryCapabilityValidation:
        """Short alias for ``validate_capability`` for callers building a facade."""

        return self.validate_capability(
            capability_key,
            logic_form,
            runtime=runtime,
            ontology_context=ontology_context,
        )

    def compile_logic_form(
        self,
        capability_key: str,
        logic_form: LogicForm,
        runtime: SemanticRuntime | Mapping[str, Any],
        *,
        ontology_context: Mapping[str, Any] | None = None,
        validation: QueryCapabilityValidation | None = None,
    ) -> CompiledQuery:
        """Delegate a capability-approved LogicForm to the existing compiler."""

        capability_validation = self.validate_capability(
            capability_key,
            logic_form,
            ontology_context=ontology_context,
        )
        if not capability_validation.valid:
            raise ValueError("；".join(capability_validation.errors))
        if validation is not None:
            if validation.capability_key != capability_key:
                raise ValueError("Query Capability 校验结果与当前 capability 不匹配")
            if not validation.valid:
                raise ValueError("；".join(validation.errors))

        runtime_model = SemanticRuntime.model_validate(runtime)
        logic_form_model = LogicForm.model_validate(logic_form)
        return self.semantic_runtime_service.compile_logic_form(logic_form_model, runtime_model)


def _coerce_runtime(
    runtime: SemanticRuntime | Mapping[str, Any] | None,
) -> SemanticRuntime | None:
    if runtime is None:
        return None
    return SemanticRuntime.model_validate(runtime)


__all__ = ["QueryCapabilityFacade", "QueryCapabilityRegistry"]
