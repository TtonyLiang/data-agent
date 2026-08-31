"""Deterministic bridge from a domain Ontology to the query workflow."""

from __future__ import annotations

import re
from typing import Any

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
ONTOLOGY_GENERIC_FRAGMENTS = frozenset(
    {"贷款", "申请", "客户", "状态", "风险", "案件", "账户", "还款", "指标", "当前"}
)


def build_ontology_evidence(question: str, context: dict[str, Any] | None) -> dict[str, Any]:
    """Return the small, question-relevant part of an agent's Ontology context."""
    if not isinstance(context, dict):
        return _empty_evidence()

    profile = {"compact": _compact(question)}
    object_types = [item for item in context.get("object_types", []) if isinstance(item, dict)]
    link_types = [item for item in context.get("link_types", []) if isinstance(item, dict)]
    actions = [item for item in context.get("actions", []) if isinstance(item, dict)]
    object_by_key = {
        str(item.get("object_key") or ""): item
        for item in object_types
        if item.get("object_key")
    }

    object_matches = {
        item["object_key"]: item
        for item in (_object_evidence(entry, profile) for entry in object_types)
        if item
    }
    link_matches = [
        item for item in (_link_evidence(entry, profile) for entry in link_types) if item
    ]
    action_matches = [
        item for item in (_action_evidence(entry, profile) for entry in actions) if item
    ]

    related_object_keys = set(object_matches)
    for item in link_matches:
        related_object_keys.update(
            key
            for key in (item.get("source_object_key"), item.get("target_object_key"))
            if key
        )
    for item in action_matches:
        if item.get("target_object_key"):
            related_object_keys.add(str(item["target_object_key"]))

    for key in related_object_keys:
        if key not in object_matches and key in object_by_key:
            source = object_by_key[key]
            object_matches[key] = {
                "object_key": key,
                "name": str(source.get("name") or key),
                "score": 8,
                "reason": "与命中的本体关系或动作关联",
                "matched_properties": [],
            }

    direct_link_keys = {str(item.get("link_key") or "") for item in link_matches}
    for item in link_types:
        link_key = str(item.get("link_key") or "")
        endpoints = {
            str(item.get("source_object_key") or ""),
            str(item.get("target_object_key") or ""),
        }
        if (
            link_key
            and link_key not in direct_link_keys
            and endpoints.intersection(related_object_keys)
        ):
            link_matches.append(
                {
                    "link_key": link_key,
                    "name": str(item.get("name") or link_key),
                    "source_object_key": str(item.get("source_object_key") or ""),
                    "target_object_key": str(item.get("target_object_key") or ""),
                    "score": 8,
                    "reason": "关联命中的业务对象",
                }
            )

    direct_action_keys = {str(item.get("action_key") or "") for item in action_matches}
    for item in actions:
        action_key = str(item.get("action_key") or "")
        target_key = str(item.get("target_object_key") or "")
        if (
            action_key
            and action_key not in direct_action_keys
            and target_key in related_object_keys
        ):
            action_matches.append(
                {
                    "action_key": action_key,
                    "name": str(item.get("name") or action_key),
                    "target_object_key": target_key,
                    "score": 8,
                    "reason": "作用于命中的业务对象",
                }
            )

    object_evidence = _limit(object_matches.values(), "object_key", 4)
    link_evidence = _limit(link_matches, "link_key", 4)
    action_evidence = _limit(action_matches, "action_key", 4)
    return {
        "object_types": object_evidence,
        "link_types": link_evidence,
        "actions": action_evidence,
        "count": len(object_evidence) + len(link_evidence) + len(action_evidence),
    }


def ontology_schema_terms(
    context: dict[str, Any] | None, evidence: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Translate matched Ontology definitions into bounded schema-ranking terms."""
    if not isinstance(context, dict) or not isinstance(evidence, dict):
        return []
    objects = {
        str(item.get("object_key") or ""): item
        for item in context.get("object_types", [])
        if isinstance(item, dict) and item.get("object_key")
    }
    terms: list[dict[str, Any]] = []
    for item in evidence.get("object_types", []) or []:
        if not isinstance(item, dict):
            continue
        related = float(item.get("score") or 0) < 12 and "关联" in str(item.get("reason") or "")
        name_weight = 6 if related else 28
        key_weight = 3 if related else 14
        key = str(item.get("object_key") or "")
        name = str(item.get("name") or key)
        _append_term(terms, name, name_weight, f"企业本体对象命中: {name}")
        _append_term(terms, key, key_weight, f"企业本体对象标识: {name}")
        source = objects.get(key) or {}
        property_keys = {
            str(prop.get("property_key") or "")
            for prop in item.get("matched_properties", [])
            if isinstance(prop, dict)
        }
        for prop in source.get("properties", []) or []:
            if (
                not isinstance(prop, dict)
                or str(prop.get("property_key") or "") not in property_keys
            ):
                continue
            prop_name = str(prop.get("name") or prop.get("property_key") or "")
            _append_term(terms, prop_name, 20, f"企业本体属性命中: {prop_name}")
            _append_term(
                terms,
                str(prop.get("property_key") or ""),
                10,
                f"企业本体属性标识: {prop_name}",
            )
    for item in evidence.get("link_types", []) or []:
        if isinstance(item, dict):
            related = float(item.get("score") or 0) < 12 and "关联" in str(item.get("reason") or "")
            name = str(item.get("name") or item.get("link_key") or "")
            _append_term(terms, name, 4 if related else 14, f"企业本体关系命中: {name}")
    for item in evidence.get("actions", []) or []:
        if isinstance(item, dict):
            related = float(item.get("score") or 0) < 12 and "关联" in str(item.get("reason") or "")
            name = str(item.get("name") or item.get("action_key") or "")
            _append_term(terms, name, 4 if related else 14, f"企业本体动作命中: {name}")
    return terms


def score_ontology_schema_text(
    values: list[str], terms: list[dict[str, Any]] | None
) -> tuple[float, list[str]]:
    """Score a table or field using question-matched Ontology definitions."""
    text = _compact(" ".join(str(value or "") for value in values))
    if not text:
        return 0.0, []
    score = 0.0
    reasons: list[str] = []
    for item in terms or []:
        value = _compact(str(item.get("value") or ""))
        if len(value) < 2:
            continue
        weight = float(item.get("weight") or 0)
        reason = str(item.get("reason") or "企业本体关联")
        if value in text:
            score += weight
            reasons.append(reason)
            continue
        if any(fragment in text for fragment in _fragments(value)):
            score += min(max(weight * 0.45, 6), 14)
            reasons.append(reason)
    return score, _unique(reasons)[:4]


def select_ontology_context(
    context: dict[str, Any] | None, evidence: dict[str, Any] | None
) -> dict[str, Any]:
    """Return only matched Ontology definitions for the LogicForm prompt."""
    if not isinstance(context, dict):
        return {"domain": {}, "release": None, "object_types": [], "link_types": [], "actions": []}
    evidence = evidence if isinstance(evidence, dict) else _empty_evidence()
    object_keys = _keys(evidence.get("object_types"), "object_key")
    link_keys = _keys(evidence.get("link_types"), "link_key")
    action_keys = _keys(evidence.get("actions"), "action_key")
    return {
        "domain": context.get("domain") or {},
        "release": context.get("release"),
        "object_types": [
            item for item in context.get("object_types", []) or []
            if isinstance(item, dict) and str(item.get("object_key") or "") in object_keys
        ][:4],
        "link_types": [
            item
            for item in context.get("link_types", []) or []
            if isinstance(item, dict)
            and str(item.get("link_key") or "") in link_keys
            and str(item.get("source_object_key") or "") in object_keys
            and str(item.get("target_object_key") or "") in object_keys
        ][:4],
        "actions": [
            item for item in context.get("actions", []) or []
            if isinstance(item, dict) and str(item.get("action_key") or "") in action_keys
        ][:4],
        "evidence": {
            "object_types": list(evidence.get("object_types") or [])[:4],
            "link_types": list(evidence.get("link_types") or [])[:4],
            "actions": list(evidence.get("actions") or [])[:4],
        },
    }


def _object_evidence(item: dict[str, Any], profile: dict[str, str]) -> dict[str, Any] | None:
    key = str(item.get("object_key") or "")
    if not key:
        return None
    score, reasons = _score_labels(
        profile, [item.get("object_key"), item.get("name"), item.get("description")], "业务对象"
    )
    properties: list[dict[str, Any]] = []
    for prop in item.get("properties", []) or []:
        if not isinstance(prop, dict):
            continue
        prop_score, prop_reasons = _score_labels(
            profile,
            [prop.get("property_key"), prop.get("name"), prop.get("description")],
            "业务属性",
        )
        if prop_score <= 0:
            continue
        score += prop_score
        reasons.extend(prop_reasons)
        properties.append(
            {
                "property_key": str(prop.get("property_key") or ""),
                "name": str(prop.get("name") or ""),
                "score": prop_score,
            }
        )
    if score <= 0:
        return None
    return {
        "object_key": key,
        "name": str(item.get("name") or key),
        "score": round(score, 2),
        "reason": "、".join(_unique(reasons)[:3]),
        "matched_properties": _limit(properties, "property_key", 4),
    }


def _link_evidence(item: dict[str, Any], profile: dict[str, str]) -> dict[str, Any] | None:
    key = str(item.get("link_key") or "")
    if not key:
        return None
    score, reasons = _score_labels(
        profile,
        [
            item.get("link_key"),
            item.get("name"),
            item.get("description"),
            item.get("source_property"),
            item.get("target_property"),
        ],
        "业务关系",
    )
    if score <= 0:
        return None
    return {
        "link_key": key,
        "name": str(item.get("name") or key),
        "source_object_key": str(item.get("source_object_key") or ""),
        "target_object_key": str(item.get("target_object_key") or ""),
        "score": round(score, 2),
        "reason": "、".join(_unique(reasons)[:3]),
    }


def _action_evidence(item: dict[str, Any], profile: dict[str, str]) -> dict[str, Any] | None:
    key = str(item.get("action_key") or "")
    if not key:
        return None
    labels: list[Any] = [item.get("action_key"), item.get("name"), item.get("description")]
    for parameter in item.get("parameters", []) or []:
        if isinstance(parameter, dict):
            labels.extend([parameter.get("parameter_key"), parameter.get("name")])
    score, reasons = _score_labels(profile, labels, "业务动作")
    if score <= 0:
        return None
    return {
        "action_key": key,
        "name": str(item.get("name") or key),
        "target_object_key": str(item.get("target_object_key") or ""),
        "score": round(score, 2),
        "reason": "、".join(_unique(reasons)[:3]),
    }


def _score_labels(profile: dict[str, str], values: list[Any], kind: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    question = profile["compact"]
    for raw in values:
        label = str(raw or "").strip()
        value = _compact(label)
        if len(value) < 2:
            continue
        if value in question:
            score += 36 if _has_cjk(value) else 24
            reasons.append(f"{kind}命中 {label}")
            continue
        for fragment in _fragments(value):
            if fragment in question:
                score += 12 if _has_cjk(fragment) else 8
                reasons.append(f"{kind}词命中 {fragment}")
                break
    return score, _unique(reasons)


def _empty_evidence() -> dict[str, Any]:
    return {"object_types": [], "link_types": [], "actions": [], "count": 0}


def _append_term(terms: list[dict[str, Any]], value: str, weight: float, reason: str) -> None:
    value = str(value or "").strip()
    if len(_compact(value)) < 2 or any(item.get("value") == value for item in terms):
        return
    terms.append({"value": value, "weight": weight, "reason": reason})


def _keys(items: Any, key: str) -> set[str]:
    return {
        str(item.get(key) or "")
        for item in items or []
        if isinstance(item, dict) and item.get(key)
    }


def _limit(items: Any, key: str, limit: int) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        value = str(item.get(key) or "")
        previous = unique.get(value)
        if value and (
            previous is None
            or float(item.get("score") or 0) > float(previous.get("score") or 0)
        ):
            unique[value] = item
    return sorted(
        unique.values(),
        key=lambda item: (-float(item.get("score") or 0), str(item.get(key) or "")),
    )[:limit]


def _fragments(value: str) -> list[str]:
    values: list[str] = []
    for token in TOKEN_RE.findall(value):
        token = token.lower().strip()
        if len(token) < 2:
            continue
        if _has_cjk(token):
            for size in range(min(4, len(token)), 1, -1):
                values.extend(
                    fragment
                    for index in range(len(token) - size + 1)
                    for fragment in [token[index : index + size]]
                    if fragment not in ONTOLOGY_GENERIC_FRAGMENTS
                )
        else:
            values.append(token)
            values.extend(part for part in token.split("_") if len(part) > 1)
    return _unique(values)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            result.append(clean)
            seen.add(clean)
    return result
