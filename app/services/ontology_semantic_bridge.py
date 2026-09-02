"""Bridge Ontology definitions to the existing semantic asset runtime.

The bridge is deliberately read-only.  It normalizes the compact payload from
``OntologyService.build_agent_context`` and either a ``SemanticRuntime`` model
or its dumped dictionary, without changing either input.  Associations are
only made from explicit semantic keys or explicit metadata; physical table
names are never used to guess an Ontology object.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

_NON_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)
_METRIC_OBJECT_KEYS = (
    "object_key",
    "object_keys",
    "object_type_key",
    "object_type_keys",
    "concept_key",
    "concept_keys",
    "applies_to_objects",
)
_MAPPING_OBJECT_KEYS = ("object_key", "object_type_key")
_MAPPING_PROPERTY_KEYS = ("property_key", "object_property", "ontology_property")


def normalize_term(value: Any) -> str:
    """Normalize a user/business term for deterministic alias lookup."""
    if value is None:
        return ""
    text = re.sub(r"\s+", "", str(value).casefold())
    return _NON_WORD_RE.sub("", text)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, BaseModel):
        return copy.deepcopy(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return copy.deepcopy(model_dump(mode="python"))
    raise TypeError(f"expected a dict or Pydantic model, got {type(value).__name__}")


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        values = [value]
    elif isinstance(value, Sequence):
        values = value
    else:
        values = [value]
    return [_as_dict(item) for item in values]


def _runtime_payload(runtime: Any) -> dict[str, Any]:
    payload = _as_dict(runtime)
    nested = payload.get("semantic_runtime")
    return _as_dict(nested) if nested is not None else payload


def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _unique(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _warning(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    value = item.get("metadata")
    return dict(value) if isinstance(value, Mapping) else {}


def _explicit_metric_objects(metric: Mapping[str, Any]) -> list[str]:
    metadata = _metadata(metric)
    values: list[str] = []
    for key in _METRIC_OBJECT_KEYS:
        values.extend(_string_values(metadata.get(key)))
        if key in metric:
            values.extend(_string_values(metric.get(key)))
    return _unique(values)


def _explicit_mapping_target(mapping: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    metadata = _metadata(mapping)
    object_keys: list[str] = []
    property_keys: list[str] = []
    for key in _MAPPING_OBJECT_KEYS:
        object_keys.extend(_string_values(mapping.get(key)))
        object_keys.extend(_string_values(metadata.get(key)))
    for key in _MAPPING_PROPERTY_KEYS:
        property_keys.extend(_string_values(mapping.get(key)))
        property_keys.extend(_string_values(metadata.get(key)))
    return _unique(object_keys), _unique(property_keys)


class OntologySemanticBridge:
    """Immutable-in-use lookup facade over Ontology and semantic assets.

    Public result keys are ``objects``, ``metrics``, ``relations``,
    ``actions``, ``aliases`` and ``warnings``.  Metric ownership and mapping
    targets are populated only when the input declares them explicitly:
    metric metadata may use ``object_key``/``object_keys`` (or the equivalent
    ``concept_key`` forms), and a mapping may use ``object_key`` plus
    ``property_key``.  A mapping whose ``asset_key`` exactly equals an
    Ontology property key is also treated as an explicit semantic-key match.
    """

    def __init__(self, ontology_context: Any, semantic_runtime: Any):
        context = _as_dict(ontology_context)
        runtime = _runtime_payload(semantic_runtime)
        self._payload = _build_payload(context, runtime)

    def as_dict(self) -> dict[str, Any]:
        """Return a detached query-context-friendly dictionary."""
        return copy.deepcopy(self._payload)

    def resolve_object_key(self, term: Any) -> str | None:
        """Return the unique canonical object key for a name or synonym."""
        normalized = normalize_term(term)
        candidates = self._payload["aliases"].get(normalized, [])
        return candidates[0] if len(candidates) == 1 else None

    def object_property_mappings(
        self, object_key: str, property_key: str | None = None
    ) -> list[dict[str, Any]]:
        """Reverse-resolve semantic mappings for an Ontology property."""
        item = self._payload["objects"].get(object_key)
        if not item:
            return []
        if property_key is None:
            mappings: list[dict[str, Any]] = []
            for values in item["property_mappings"].values():
                mappings.extend(values)
            return copy.deepcopy(mappings)
        return copy.deepcopy(item["property_mappings"].get(property_key, []))

    def metric_bridge(self, metric_key: str) -> dict[str, Any] | None:
        item = self._payload["metrics"].get(metric_key)
        return copy.deepcopy(item) if item else None

    def relation_bridge(self, link_key: str) -> dict[str, Any] | None:
        item = self._payload["relations"].get(link_key)
        return copy.deepcopy(item) if item else None


def build_ontology_semantic_bridge(
    ontology_context: Any, semantic_runtime: Any
) -> dict[str, Any]:
    """Build a detached Ontology/semantic bridge payload."""
    return OntologySemanticBridge(ontology_context, semantic_runtime).as_dict()


def _build_payload(
    context: dict[str, Any], runtime: dict[str, Any]
) -> dict[str, Any]:
    object_types = _records(context.get("object_types"))
    link_types = _records(context.get("link_types"))
    actions = _records(context.get("actions"))
    concepts = _records(runtime.get("concepts"))
    metrics = _records(runtime.get("metrics"))
    mappings = _records(runtime.get("mappings"))
    relations = _records(runtime.get("relations"))
    warnings: list[dict[str, Any]] = []

    object_by_key = {
        str(item["object_key"]): item
        for item in object_types
        if str(item.get("object_key") or "").strip()
    }
    concept_by_key = {
        str(item["concept_key"]): item
        for item in concepts
        if str(item.get("concept_key") or "").strip()
    }
    action_by_key = {
        str(item["action_key"]): item
        for item in actions
        if str(item.get("action_key") or "").strip()
    }
    mapping_by_key = {
        str(item["asset_key"]): item
        for item in mappings
        if str(item.get("asset_key") or "").strip()
    }
    relation_by_key = {
        str(item["relation_key"]): item
        for item in relations
        if str(item.get("relation_key") or "").strip()
    }

    object_payload: dict[str, dict[str, Any]] = {}
    aliases: dict[str, list[str]] = {}
    for object_key, object_type in object_by_key.items():
        concept = concept_by_key.get(object_key)
        if concept is None:
            warnings.append(
                _warning(
                    "object_concept_missing",
                    f"本体对象 {object_key} 未找到同 key 的语义概念",
                    object_key=object_key,
                )
            )
        object_aliases = _unique(
            [
                object_key,
                str(object_type.get("name") or ""),
                *(_string_values(object_type.get("synonyms"))),
                *(_string_values(concept.get("name") if concept else None)),
                *(_string_values(concept.get("synonyms") if concept else None)),
            ]
        )
        object_payload[object_key] = {
            "object_key": object_key,
            "name": object_type.get("name") or object_key,
            "description": object_type.get("description") or "",
            "properties": copy.deepcopy(object_type.get("properties") or []),
            "concept": copy.deepcopy(concept) if concept else None,
            "aliases": object_aliases,
            "metrics": [],
            "actions": [],
            "property_mappings": {},
        }
        for alias in object_aliases:
            aliases.setdefault(normalize_term(alias), []).append(object_key)

    for normalized, candidates in aliases.items():
        aliases[normalized] = _unique(candidates)
        if len(aliases[normalized]) > 1:
            warnings.append(
                _warning(
                    "ambiguous_object_alias",
                    f"对象别名 {normalized} 对应多个本体对象，未自动选择",
                    alias=normalized,
                    object_keys=aliases[normalized],
                )
            )

    for action_key, action in action_by_key.items():
        target = str(action.get("target_object_key") or "")
        if target in object_payload:
            object_payload[target]["actions"].append(action_key)
        else:
            warnings.append(
                _warning(
                    "action_target_object_missing",
                    f"动作 {action_key} 的目标对象 {target or '<empty>'} 不存在",
                    action_key=action_key,
                    target_object_key=target,
                )
            )

    for object_key, object_item in object_payload.items():
        for property_item in object_item["properties"]:
            if not isinstance(property_item, Mapping):
                continue
            property_key = str(property_item.get("property_key") or "")
            if not property_key:
                continue
            matches: list[dict[str, Any]] = []
            for mapping in mappings:
                mapping_key = str(mapping.get("asset_key") or "")
                mapping_objects, mapping_properties = _explicit_mapping_target(mapping)
                explicit_match = (
                    object_key in mapping_objects
                    and property_key in mapping_properties
                )
                semantic_key_match = not mapping_objects and not mapping_properties and (
                    mapping_key == property_key
                )
                if explicit_match or semantic_key_match:
                    matches.append(copy.deepcopy(mapping))
            object_item["property_mappings"][property_key] = matches
            if not matches:
                warnings.append(
                    _warning(
                        "object_property_mapping_missing",
                        f"对象 {object_key} 的属性 {property_key} 未找到语义映射",
                        object_key=object_key,
                        property_key=property_key,
                    )
                )

    metric_payload: dict[str, dict[str, Any]] = {}
    object_keys = set(object_payload)
    for metric in metrics:
        metric_key = str(metric.get("metric_key") or "")
        if not metric_key:
            continue
        declared_objects = _explicit_metric_objects(metric)
        metric_objects = [key for key in declared_objects if key in object_keys]
        for declared in declared_objects:
            if declared not in object_keys:
                warnings.append(
                    _warning(
                        "metric_object_reference_missing",
                        f"指标 {metric_key} 显式引用的对象 {declared} 不存在",
                        metric_key=metric_key,
                        object_key=declared,
                    )
                )
        if not metric_objects:
            warnings.append(
                _warning(
                    "metric_object_association_missing",
                    f"指标 {metric_key} 未声明适用的本体对象，未根据物理表猜测归属",
                    metric_key=metric_key,
                    base_table=metric.get("base_table"),
                )
            )
        dimension_payload: list[dict[str, Any]] = []
        for dimension in _string_values(metric.get("dimensions")):
            mapping = mapping_by_key.get(dimension)
            dimension_payload.append(
                {"asset_key": dimension, "mapping": copy.deepcopy(mapping) if mapping else None}
            )
            if mapping is None:
                warnings.append(
                    _warning(
                        "metric_dimension_mapping_missing",
                        f"指标 {metric_key} 的适用维度 {dimension} 未找到语义映射",
                        metric_key=metric_key,
                        dimension=dimension,
                    )
                )
        metric_payload[metric_key] = {
            "metric_key": metric_key,
            "name": metric.get("name") or metric_key,
            "description": metric.get("description") or "",
            "object_keys": metric_objects,
            "declared_object_keys": declared_objects,
            "dimensions": dimension_payload,
            "metric": copy.deepcopy(metric),
        }
        for object_key in metric_objects:
            object_payload[object_key]["metrics"].append(metric_key)

    relation_payload: dict[str, dict[str, Any]] = {}
    matched_relation_keys: set[str] = set()
    for link in link_types:
        link_key = str(link.get("link_key") or "")
        if not link_key:
            continue
        relation = relation_by_key.get(link_key)
        if relation is None:
            relation = next(
                (
                    item
                    for item in relations
                    if str(_metadata(item).get("link_key") or "") == link_key
                ),
                None,
            )
        if relation is None:
            warnings.append(
                _warning(
                    "link_semantic_relation_missing",
                    f"本体关系 {link_key} 未找到同 key 的语义关系，未猜测 JOIN 路径",
                    link_key=link_key,
                )
            )
        else:
            relation_key = str(relation.get("relation_key") or link_key)
            matched_relation_keys.add(relation_key)
        relation_payload[link_key] = {
            "link_key": link_key,
            "link": copy.deepcopy(link),
            "relation": copy.deepcopy(relation) if relation else None,
            "relation_key": str(relation.get("relation_key")) if relation else None,
            "linked": relation is not None,
            "join_path": copy.deepcopy(relation.get("join_path") or []) if relation else [],
        }

    for relation in relations:
        relation_key = str(relation.get("relation_key") or "")
        if relation_key and relation_key not in matched_relation_keys and relation_key not in {
            str(item.get("link_key") or "") for item in link_types
        }:
            warnings.append(
                _warning(
                    "semantic_relation_link_missing",
                    f"语义关系 {relation_key} 未找到对应的本体 link_key",
                    relation_key=relation_key,
                )
            )

    return {
        "objects": object_payload,
        "metrics": metric_payload,
        "relations": relation_payload,
        "actions": action_by_key,
        "aliases": aliases,
        "warnings": warnings,
    }
