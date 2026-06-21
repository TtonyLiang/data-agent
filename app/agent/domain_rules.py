from __future__ import annotations

import re
from typing import Any


GENERIC_COUNT_TERMS = ("笔数", "多少笔", "几笔", "数量", "件数", "次数", "count")
GENERIC_AMOUNT_TERMS = ("金额", "余额", "amount", "balance")
GENERIC_RANKING_TERMS = ("最多", "排名", "排行", "top", "前", "最高", "最低")
GENERIC_TREND_TERMS = ("变化", "趋势", "走势", "波动", "按月", "按日", "同比", "环比", "trend")
GENERIC_REGION_TERMS = ("区域", "地区", "region", "area")
GENERIC_PRODUCT_TERMS = ("产品类型", "产品", "producttype", "product")


def compact_text(text: str) -> str:
    """Lowercase and remove whitespace for mixed Chinese/English matching."""
    return re.sub(r"\s+", "", str(text or "")).lower()


def contains_any(text: str, values: list[str] | tuple[str, ...]) -> bool:
    """Return true when any configured term appears in text."""
    compact = compact_text(text)
    return any(str(value or "").lower() in compact for value in values if str(value or ""))


def extract_top_limit(text: str) -> int | None:
    """Extract numeric or small Chinese TopN limits from user text."""
    compact = compact_text(text)
    match = re.search(r"(?:top|前)(\d{1,3})", compact, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"前([一二两三四五六七八九十]+)", compact)
    if match:
        return chinese_number_to_int(match.group(1))
    return None


def chinese_number_to_int(text: str) -> int | None:
    """Convert small Chinese numerals used in TopN expressions into integers."""
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if text in digits:
        return digits[text]
    if text.startswith("十") and len(text) == 2:
        return 10 + digits.get(text[1], 0)
    if text.endswith("十") and len(text) == 2:
        return digits.get(text[0], 0) * 10
    if "十" in text and len(text) == 3:
        left, right = text.split("十", 1)
        return digits.get(left, 0) * 10 + digits.get(right, 0)
    return None


def semantic_rules(runtime: dict[str, Any] | None, rule_type: str | None = None) -> list[dict]:
    """Return semantic rules from an already loaded runtime payload."""
    if not isinstance(runtime, dict):
        return []
    rules = [item for item in runtime.get("rules", []) or [] if isinstance(item, dict)]
    if rule_type:
        return [item for item in rules if item.get("rule_type") == rule_type]
    return rules


def field_aliases(runtime: dict[str, Any] | None) -> dict[str, str]:
    """Build generic-to-canonical field aliases from domain normalization rules."""
    aliases: dict[str, str] = {}
    for rule in semantic_rules(runtime, "normalization"):
        expression = rule.get("expression") or {}
        if not isinstance(expression, dict):
            continue
        for source, target in (expression.get("field_aliases") or {}).items():
            if source and target:
                aliases[str(source)] = str(target)
    return aliases


def canonicalize_field(field: str, aliases: dict[str, str]) -> str:
    """Map a generic field key to the domain-specific configured key."""
    return aliases.get(field, field)


def metric_by_key(runtime: dict[str, Any] | None) -> dict[str, dict]:
    """Index loaded semantic metrics by metric key."""
    if not isinstance(runtime, dict):
        return {}
    return {
        str(item.get("metric_key")): item
        for item in runtime.get("metrics", []) or []
        if isinstance(item, dict) and item.get("metric_key")
    }


def mapping_by_key(runtime: dict[str, Any] | None) -> dict[str, dict]:
    """Index loaded semantic mappings by asset key."""
    if not isinstance(runtime, dict):
        return {}
    return {
        str(item.get("asset_key")): item
        for item in runtime.get("mappings", []) or []
        if isinstance(item, dict) and item.get("asset_key")
    }


def display_label_map(runtime: dict[str, Any] | None) -> dict[str, str]:
    """Return metric and mapping display labels from semantic runtime metadata."""
    labels: dict[str, str] = {}
    if not isinstance(runtime, dict):
        return labels
    for metric in runtime.get("metrics", []) or []:
        key = str(metric.get("metric_key") or "")
        name = str(metric.get("name") or "")
        if key and name:
            labels[key] = name
    for mapping in runtime.get("mappings", []) or []:
        key = str(mapping.get("asset_key") or "")
        name = str(mapping.get("name") or "")
        if key and name:
            labels[key] = name
    return labels


def find_logic_form_rules(
    runtime: dict[str, Any] | None,
    question: str,
    *,
    history_text: str = "",
) -> list[dict[str, Any]]:
    """Match configured LogicForm normalization rules against the current question."""
    text = f"{history_text} {question}"
    matched: list[dict[str, Any]] = []
    for rule in semantic_rules(runtime, "normalization"):
        expression = rule.get("expression") or {}
        if not isinstance(expression, dict):
            continue
        actions = expression.get("logic_form") or {}
        if not isinstance(actions, dict):
            continue
        if _rule_matches(expression.get("match") or {}, text):
            matched.append(actions)
    return matched


def business_groups_from_runtime(
    runtime: dict[str, Any] | None,
    question: str,
) -> list[dict[str, Any]]:
    """Match configured business recall groups for schema ranking."""
    groups: list[dict[str, Any]] = []
    for rule in semantic_rules(runtime, "recall"):
        expression = rule.get("expression") or {}
        if not isinstance(expression, dict):
            continue
        for group in expression.get("business_groups") or []:
            if not isinstance(group, dict):
                continue
            aliases = [str(item) for item in group.get("aliases") or []]
            if contains_any(question, aliases):
                groups.append(group)
    return _unique_groups(groups)


def schema_hints_from_runtime(
    runtime: dict[str, Any] | None,
    question: str,
) -> list[dict[str, Any]]:
    """Return configured physical schema hints matched by the question."""
    hints: list[dict[str, Any]] = []
    for rule in semantic_rules(runtime, "recall"):
        expression = rule.get("expression") or {}
        if not isinstance(expression, dict):
            continue
        for hint in expression.get("schema_hints") or []:
            if not isinstance(hint, dict):
                continue
            match = hint.get("match") or {}
            if isinstance(match, dict):
                if _rule_matches(match, question):
                    hints.append(hint)
                continue
            match_terms = [str(item) for item in hint.get("match_terms") or []]
            if match_terms and contains_any(question, match_terms):
                hints.append(hint)
    return _unique_groups(hints)


def recall_profiles_from_runtime(
    runtime: dict[str, Any] | None,
    question: str,
) -> list[dict[str, Any]]:
    """Return configured recall scoring profiles matched by the question."""
    profiles: list[dict[str, Any]] = []
    for rule in semantic_rules(runtime, "recall"):
        expression = rule.get("expression") or {}
        if not isinstance(expression, dict):
            continue
        for profile in expression.get("recall_profiles") or []:
            if not isinstance(profile, dict):
                continue
            match = profile.get("match") or {}
            if isinstance(match, dict) and match:
                if _rule_matches(match, question):
                    profiles.append(profile)
                continue
            match_terms = [str(item) for item in profile.get("match_terms") or []]
            if match_terms and contains_any(question, match_terms):
                profiles.append(profile)
    return _unique_groups(profiles)


def _rule_matches(match: dict[str, Any], text: str) -> bool:
    """Evaluate the small declarative matcher used by semantic_rule.expression."""
    if not isinstance(match, dict):
        return False
    any_terms = match.get("any") or []
    all_terms = match.get("all") or []
    none_terms = match.get("none") or []
    if any_terms and not contains_any(text, any_terms):
        return False
    if all_terms and not all(contains_any(text, [term]) for term in all_terms):
        return False
    if none_terms and contains_any(text, none_terms):
        return False
    intents = set(match.get("intents") or [])
    count_terms = [*GENERIC_COUNT_TERMS, *(match.get("count_terms") or [])]
    amount_terms = [*GENERIC_AMOUNT_TERMS, *(match.get("amount_terms") or [])]
    ranking_terms = [*GENERIC_RANKING_TERMS, *(match.get("ranking_terms") or [])]
    trend_terms = [*GENERIC_TREND_TERMS, *(match.get("trend_terms") or [])]
    region_terms = [*GENERIC_REGION_TERMS, *(match.get("region_terms") or [])]
    product_terms = [*GENERIC_PRODUCT_TERMS, *(match.get("product_terms") or [])]
    if "count" in intents and not contains_any(text, count_terms):
        return False
    if "amount" in intents and not contains_any(text, amount_terms):
        return False
    if "ranking" in intents and not contains_any(text, ranking_terms):
        return False
    if "trend" in intents and not contains_any(text, trend_terms):
        return False
    if "region" in intents and not contains_any(text, region_terms):
        return False
    if "product" in intents and not contains_any(text, product_terms):
        return False
    return True


def _unique_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for group in groups:
        key = str(group.get("key") or group.get("label") or "")
        if key and key not in seen:
            seen.add(key)
            result.append(group)
    return result
