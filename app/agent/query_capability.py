"""Agent-side Query Capability resolution helpers.

This module adapts the task C ``query_context`` contract to the P0 Query
Capability registry.  It deliberately contains no LLM calls, SQL execution,
or persistence.  A capability is selected only when the LogicForm has one
unambiguous complete match; ambiguity returns ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.models.knowledge import LogicForm
from app.models.query_capability import QueryCapability
from app.services.query_capability import QueryCapabilityFacade, QueryCapabilityRegistry


def build_query_capability_registry(
    query_context: Mapping[str, Any] | None,
) -> QueryCapabilityRegistry:
    """Build an in-memory registry from the explicit query context payload.

    The adapter accepts the frozen top-level ``query_capabilities`` field and
    the equivalent ``capabilities.query``/``capabilities.queries`` forms so
    that context producers can evolve without making the Agent guess from
    physical tables or arbitrary Ontology actions.
    """
    capabilities = extract_query_capabilities(query_context)
    return QueryCapabilityRegistry(capabilities)


def extract_query_capabilities(
    query_context: Mapping[str, Any] | None,
) -> list[QueryCapability]:
    """Return only explicit read-only Query Capability definitions."""
    if not isinstance(query_context, Mapping):
        return []

    raw_values: list[Any] = []
    for key in ("query_capabilities", "queryCapabilities"):
        raw_values.extend(_as_sequence(query_context.get(key)))

    capabilities = query_context.get("capabilities")
    if isinstance(capabilities, Mapping):
        for key in ("query_capabilities", "queryCapabilities", "query", "queries", "read"):
            raw_values.extend(_as_sequence(capabilities.get(key)))
    else:
        raw_values.extend(_as_sequence(capabilities))

    result: list[QueryCapability] = []
    seen: set[str] = set()
    for value in raw_values:
        try:
            capability = QueryCapability.model_validate(value)
        except Exception:
            continue
        if not capability.read_only or capability.key in seen:
            continue
        seen.add(capability.key)
        result.append(capability)
    return result


def resolve_query_capability_key(
    logic_form: LogicForm | Mapping[str, Any],
    query_context: Mapping[str, Any] | None,
) -> str | None:
    """Resolve one capability key for a LogicForm, or ``None`` if ambiguous.

    A complete match supports every requested metric and dimension.  Exact
    boundary matches are preferred, but a unique broader capability remains a
    valid fallback.  Multiple candidates at either level are intentionally
    left unresolved so the caller can use the existing fallback/clarification
    path instead of making an unsafe choice.
    """
    logic_form_model = LogicForm.model_validate(logic_form)
    capabilities = build_query_capability_registry(query_context).list()
    complete = [
        capability
        for capability in capabilities
        if _supports_logic_form(capability, logic_form_model)
    ]
    if not complete:
        return None

    requested_metrics = set(logic_form_model.metrics)
    requested_dimensions = set(logic_form_model.dimensions)
    exact = [
        capability
        for capability in complete
        if set(capability.supported_metrics) == requested_metrics
        and set(capability.supported_dimensions) == requested_dimensions
    ]
    candidates = exact or complete
    return candidates[0].key if len(candidates) == 1 else None


def resolve_query_capability(
    logic_form: LogicForm | Mapping[str, Any],
    query_context: Mapping[str, Any] | None,
) -> QueryCapability | None:
    """Return the unique capability selected for a LogicForm."""
    key = resolve_query_capability_key(logic_form, query_context)
    if key is None:
        return None
    return build_query_capability_registry(query_context).resolve(key)


def validate_query_capability(
    capability_key: str,
    logic_form: LogicForm | Mapping[str, Any],
    query_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate only the capability boundary, without duplicating runtime validation."""
    facade = QueryCapabilityFacade(build_query_capability_registry(query_context))
    return facade.validate_capability(
        capability_key,
        LogicForm.model_validate(logic_form),
        ontology_context=_ontology_context(query_context),
    ).model_dump()


def query_capability_prompt_payload(
    query_context: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return bounded capability metadata suitable for an NL2LF prompt."""
    return [
        capability.model_dump(
            include={
                "key",
                "name",
                "description",
                "target_object",
                "domain_key",
                "supported_metrics",
                "supported_dimensions",
                "input_slots",
                "output",
                "read_only",
            }
        )
        for capability in extract_query_capabilities(query_context)
    ]


def _supports_logic_form(capability: QueryCapability, logic_form: LogicForm) -> bool:
    return (
        bool(logic_form.metrics)
        and set(logic_form.metrics).issubset(capability.supported_metrics)
        and set(logic_form.dimensions).issubset(capability.supported_dimensions)
        and (
            not capability.domain_key
            or not logic_form.domain_key
            or capability.domain_key == logic_form.domain_key
        )
    )


def _ontology_context(query_context: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(query_context, Mapping):
        return None
    value = query_context.get("ontology_context")
    if isinstance(value, Mapping):
        return value
    value = query_context.get("ontology")
    return value if isinstance(value, Mapping) else None


def _as_sequence(value: Any) -> list[Any]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return []
    if isinstance(value, Sequence):
        return list(value)
    return []


__all__ = [
    "build_query_capability_registry",
    "extract_query_capabilities",
    "query_capability_prompt_payload",
    "resolve_query_capability",
    "resolve_query_capability_key",
    "validate_query_capability",
]
