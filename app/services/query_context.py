"""Build the unified Ontology and semantic query context for an Agent."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from app.models.query_capability import QueryCapability
from app.services.ontology_semantic_bridge import build_ontology_semantic_bridge


def build_query_context(
    question: str,
    semantic_runtime: Any,
    ontology_context: Any,
    ontology_evidence: Any = None,
) -> dict[str, Any]:
    """Assemble a detached, read-only query context for downstream Agent nodes.

    Query capabilities are generated only from metrics that have an explicit
    Ontology object association in the semantic bridge.  Physical table names
    and column names are intentionally not used for capability ownership.
    """
    runtime_payload = _as_dict(semantic_runtime)
    ontology_payload = _as_dict(ontology_context)
    bridge = build_ontology_semantic_bridge(ontology_payload, runtime_payload)
    warnings = copy.deepcopy(bridge.get("warnings") or [])
    capabilities = _build_query_capabilities(
        bridge,
        runtime_payload=runtime_payload,
        warnings=warnings,
    )
    domain = copy.deepcopy(
        runtime_payload.get("domain")
        or ontology_payload.get("domain")
        or {}
    )
    release = copy.deepcopy(ontology_payload.get("release"))
    evidence = copy.deepcopy(ontology_evidence) if isinstance(ontology_evidence, Mapping) else {}

    return {
        "question": str(question or ""),
        "domain": domain,
        "ontology": copy.deepcopy(ontology_payload),
        "ontology_context": copy.deepcopy(ontology_payload),
        "bridge": bridge,
        "query_capabilities": [item.model_dump(mode="python") for item in capabilities],
        "release": release,
        "evidence": evidence,
        "warnings": warnings,
    }


def _build_query_capabilities(
    bridge: Mapping[str, Any],
    *,
    runtime_payload: Mapping[str, Any],
    warnings: list[dict[str, Any]],
) -> list[QueryCapability]:
    objects = bridge.get("objects") or {}
    metrics = bridge.get("metrics") or {}
    domain = runtime_payload.get("domain") or {}
    domain_key = domain.get("domain_key") if isinstance(domain, Mapping) else None
    capabilities: list[QueryCapability] = []

    for object_key, object_payload in objects.items():
        if not isinstance(object_payload, Mapping):
            continue
        metric_keys = _unique(
            str(metric_key)
            for metric_key in object_payload.get("metrics") or []
            if str(metric_key).strip()
        )
        if not metric_keys:
            continue

        supported_dimensions: list[str] = []
        metric_names: list[str] = []
        for metric_key in metric_keys:
            metric_payload = metrics.get(metric_key)
            if not isinstance(metric_payload, Mapping):
                continue
            metric_names.append(str(metric_payload.get("name") or metric_key))
            for dimension in metric_payload.get("dimensions") or []:
                if isinstance(dimension, Mapping):
                    asset_key = str(dimension.get("asset_key") or "").strip()
                else:
                    asset_key = str(dimension or "").strip()
                if asset_key and asset_key not in supported_dimensions:
                    supported_dimensions.append(asset_key)

        capability_key = _capability_key(str(object_key))
        if not capability_key:
            warnings.append(
                {
                    "code": "query_capability_key_invalid",
                    "message": f"本体对象 {object_key} 无法生成稳定 Query Capability key",
                    "details": {"object_key": str(object_key)},
                }
            )
            continue

        try:
            capabilities.append(
                QueryCapability(
                    key=capability_key,
                    name=f"{object_payload.get('name') or object_key}查询",
                    description=(
                        f"面向{object_payload.get('name') or object_key}的只读业务查询能力；"
                        f"支持指标：{'、'.join(metric_names or metric_keys)}"
                    ),
                    target_object=str(object_key),
                    domain_key=domain_key,
                    supported_metrics=metric_keys,
                    supported_dimensions=supported_dimensions,
                    metadata={
                        "source": "ontology_semantic_bridge",
                        "metric_object_binding": "explicit",
                    },
                )
            )
        except Exception as exc:
            warnings.append(
                {
                    "code": "query_capability_build_failed",
                    "message": f"本体对象 {object_key} 的 Query Capability 构建失败",
                    "details": {"object_key": str(object_key), "error": str(exc)},
                }
            )

    return capabilities


def _capability_key(object_key: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", object_key)
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    if not value:
        return ""
    if value[0].isdigit():
        value = f"object_{value}"
    return f"query_{value}"


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return copy.deepcopy(model_dump(mode="python"))
    raise TypeError(f"expected a mapping or Pydantic model, got {type(value).__name__}")


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = ["build_query_context"]
