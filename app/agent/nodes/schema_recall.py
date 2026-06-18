from __future__ import annotations

import re
from typing import Any

from app.config import get_settings
from app.services.metadata_service import get_metadata_service


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


async def schema_recall_node(state: dict) -> dict:
    """Recall collected physical tables/columns for SQL grounding."""
    datasource_id = state.get("datasource_id")
    if not datasource_id:
        return {
            "relevant_tables": [],
            "relevant_columns": [],
            "likely_joins": [],
            "schema_scope": {
                "mode": "missing_datasource",
                "message": "缺少数据源，跳过数据定位。",
            },
        }

    metadata_service = get_metadata_service()
    if hasattr(metadata_service, "get_authorized_schema"):
        schema = await metadata_service.get_authorized_schema(datasource_id, state.get("agent_id"))
    else:
        schema = await metadata_service.get_schema(datasource_id)
    if not schema:
        return {
            "relevant_tables": [],
            "relevant_columns": [],
            "likely_joins": [],
            "schema_scope": {
                "mode": "empty_schema",
                "message": "当前数据源没有已采集表结构。",
            },
        }

    runtime = state.get("semantic_runtime") or {}
    evidence = state.get("runtime_evidence") or []
    question = state.get("enhanced_question") or state.get("question", "")
    tokens = _tokens(question)
    semantic_terms = _semantic_terms(runtime, evidence)
    business_priority = _business_priority(runtime, evidence, question)
    business_groups = _business_groups(question)
    settings = get_settings()

    table_scores: dict[str, dict[str, Any]] = {}
    column_hits: list[dict[str, Any]] = []
    joins: list[dict[str, Any]] = []

    for table in schema:
        table_name = str(table.get("table_name") or "")
        table_comment = str(table.get("table_comment") or "")
        table_score, table_reasons = _score_text(
            [table_name, table_comment],
            tokens,
            semantic_terms,
        )
        table_business = business_priority["tables"].get(table_name, {"score": 0.0, "reasons": []})
        table_score += float(table_business.get("score") or 0)
        table_reasons = [*table_business.get("reasons", []), *table_reasons]
        group_score, group_reasons = _score_business_groups(table_name, table_comment, business_groups)
        table_score += group_score
        table_reasons = [*group_reasons, *table_reasons]
        table_scores[table_name] = {
            "table": table_name,
            "table_name": table_name,
            "comment": table_comment,
            "table_comment": table_comment,
            "score": table_score,
            "reason": "、".join(table_reasons) or "已采集候选表",
            "column_count": len(table.get("columns") or []),
        }

        for column in table.get("columns") or []:
            column_name = str(column.get("column_name") or "")
            column_comment = str(column.get("column_comment") or "")
            score, reasons = _score_text(
                [table_name, table_comment, column_name, column_comment],
                tokens,
                semantic_terms,
            )
            column_business = business_priority["columns"].get(
                (table_name, column_name),
                {"score": 0.0, "reasons": []},
            )
            score += float(column_business.get("score") or 0)
            reasons = [*column_business.get("reasons", []), *reasons]
            column_group_score, column_group_reasons = _score_business_groups(
                f"{table_name}.{column_name}",
                column_comment,
                business_groups,
            )
            score += column_group_score
            reasons = [*column_group_reasons, *reasons]
            if score > 0:
                table_scores[table_name]["score"] += min(score, 6)
                column_hits.append({
                    "table": table_name,
                    "table_name": table_name,
                    "column": column_name,
                    "column_name": column_name,
                    "comment": column_comment,
                    "column_comment": column_comment,
                    "data_type": column.get("data_type"),
                    "score": score,
                    "reason": "、".join(reasons),
                })
            if column.get("is_foreign_key") and column.get("foreign_key_ref"):
                joins.append({
                    "left": f"{table_name}.{column_name}",
                    "right": column.get("foreign_key_ref"),
                    "reason": "已采集外键关系",
                })

    matched_tables = sorted(
        table_scores.values(),
        key=lambda item: (-float(item.get("score") or 0), item.get("table_name") or ""),
    )
    positive_tables = [item for item in matched_tables if float(item.get("score") or 0) > 0]
    max_tables = max(1, settings.schema_recall_max_tables)
    selected_tables = (positive_tables or matched_tables)[:max_tables]
    selected_names = {item["table_name"] for item in selected_tables}

    matched_columns = [
        item for item in sorted(
            column_hits,
            key=lambda item: (-float(item.get("score") or 0), item.get("table_name") or "", item.get("column_name") or ""),
        )
        if item["table_name"] in selected_names
    ][:max(1, settings.schema_recall_max_columns)]

    return {
        "relevant_tables": selected_tables,
        "relevant_columns": matched_columns,
        "likely_joins": [
            item for item in joins
            if str(item.get("left", "")).split(".", 1)[0] in selected_names
        ][:12],
        "schema_scope": {
            "mode": "semantic_guided" if positive_tables else "collected_schema_fallback",
            "total_tables": len(schema),
            "matched_tables": len(selected_tables),
            "matched_columns": len(matched_columns),
            "fallback_used": not bool(positive_tables),
            "business_groups": business_groups,
        },
    }


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(text or "")
        if token and len(token.strip()) > 1
    }


def _semantic_terms(runtime: dict, evidence: list[dict]) -> set[str]:
    terms: set[str] = set()
    for item in evidence:
        metadata = item.get("metadata") or {}
        for value in (metadata.get("asset_key"), item.get("content")):
            terms.update(_tokens(str(value or "")))
    for group in ("metrics", "mappings", "concepts", "rules"):
        for item in runtime.get(group, []) if isinstance(runtime, dict) else []:
            for key in ("metric_key", "asset_key", "concept_key", "rule_key", "name", "description"):
                terms.update(_tokens(str(item.get(key) or "")))
            for value in item.get("synonyms", []) or []:
                terms.update(_tokens(str(value)))
    return terms


def _business_priority(runtime: dict, evidence: list[dict], question: str) -> dict[str, Any]:
    table_boosts: dict[str, dict[str, Any]] = {}
    column_boosts: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(runtime, dict):
        return {"tables": table_boosts, "columns": column_boosts}

    mappings = [
        item for item in runtime.get("mappings", []) or []
        if isinstance(item, dict)
    ]
    mapping_by_asset: dict[str, list[dict[str, Any]]] = {}
    for mapping in mappings:
        asset_key = str(mapping.get("asset_key") or "")
        if asset_key:
            mapping_by_asset.setdefault(asset_key, []).append(mapping)

    evidence_keys = {
        str((item.get("metadata") or {}).get("asset_key") or "")
        for item in evidence
        if isinstance(item, dict)
    }
    question_profile = _question_profile(question)

    for metric in runtime.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        metric_key = str(metric.get("metric_key") or "")
        base_table = str(metric.get("base_table") or "")
        score, reasons = _metric_match(metric, evidence_keys, question_profile)
        if score <= 0 or not base_table:
            continue
        _add_boost(table_boosts, base_table, score + 40, [f"业务指标基础表: {metric.get('name') or metric_key}", *reasons])
        for dim_key in metric.get("dimensions", []) or []:
            for mapping in mapping_by_asset.get(str(dim_key), []):
                _boost_mapping(mapping, table_boosts, column_boosts, 32, 28, f"指标关联维度: {dim_key}")

    for mapping in mappings:
        score, reasons = _mapping_match(mapping, question_profile)
        if score <= 0:
            continue
        _boost_mapping(mapping, table_boosts, column_boosts, score + 18, score + 10, "问题命中业务字段", reasons)

    for relation in runtime.get("relations", []) or []:
        if not isinstance(relation, dict):
            continue
        relation_score, relation_reasons = _asset_match_score(
            relation,
            question_profile,
            ("relation_key", "name", "description", "source_concept", "target_concept"),
        )
        if relation_score <= 0:
            continue
        for item in relation.get("join_path", []) or []:
            if not isinstance(item, dict):
                continue
            for field in ("left", "right"):
                table_name, _ = _split_qualified(str(item.get(field) or ""))
                if table_name:
                    _add_boost(table_boosts, table_name, min(relation_score, 20), [*relation_reasons, "业务关系关联表"])

    return {"tables": table_boosts, "columns": column_boosts}


def _metric_match(metric: dict[str, Any], evidence_keys: set[str], question_profile: dict[str, Any]) -> tuple[float, list[str]]:
    metric_key = str(metric.get("metric_key") or "")
    score, reasons = _asset_match_score(
        metric,
        question_profile,
        ("metric_key", "name", "description"),
    )
    for synonym in metric.get("synonyms", []) or []:
        synonym_score, synonym_reasons = _match_label(str(synonym), question_profile, "指标别名")
        score += synonym_score
        reasons.extend(synonym_reasons)

    if metric_key and metric_key in evidence_keys:
        score += 55
        reasons.append("知识召回命中指标")

    metric_text = " ".join(
        str(metric.get(key) or "")
        for key in ("metric_key", "name", "description", "aggregation", "base_table")
    ).lower()
    if question_profile["asks_count"] and _looks_like_count_metric(metric):
        score += 36
        reasons.append("问题要求笔数/数量")
    if question_profile["asks_application"] and _contains_any(metric_text, ("application", "apply", "申请")):
        score += 24
        reasons.append("问题聚焦申请业务")
    if question_profile["asks_amount"] and _contains_any(metric_text, ("amount", "金额", "余额")):
        score += 20
        reasons.append("问题聚焦金额口径")
    if question_profile["asks_count"] and _contains_any(metric_text, ("amount", "金额", "余额")):
        score -= 18

    return max(score, 0), _unique_reasons(reasons)


def _mapping_match(mapping: dict[str, Any], question_profile: dict[str, Any]) -> tuple[float, list[str]]:
    score, reasons = _asset_match_score(
        mapping,
        question_profile,
        ("asset_key", "name", "description", "table_name", "column_name"),
    )
    if question_profile["asks_region"] and _contains_any(
        " ".join(str(mapping.get(key) or "") for key in ("asset_key", "name", "column_name", "column_comment")).lower(),
        ("region", "area", "区域", "地区"),
    ):
        score += 34
        reasons.append("问题要求区域维度")
    if question_profile["asks_application"] and _contains_any(
        " ".join(str(mapping.get(key) or "") for key in ("asset_key", "name", "table_name")).lower(),
        ("application", "apply", "申请"),
    ):
        score += 18
        reasons.append("问题聚焦申请业务")
    return max(score, 0), _unique_reasons(reasons)


def _business_groups(question: str) -> list[str]:
    compact = (question or "").lower().replace(" ", "")
    groups = []
    if any(token in compact for token in ("申请", "进件", "审批")):
        groups.append("application")
    if any(token in compact for token in ("放款", "发放", "借据", "余额", "本金")):
        groups.append("account")
    if any(token in compact for token in ("还款", "逾期", "m1", "m2", "m3", "dpd", "mob", "vintage")):
        groups.append("repayment")
    if any(token in compact for token in ("催收", "回收", "入催")):
        groups.append("collection")
    if any(token in compact for token in ("客户", "客群", "分层", "风险")):
        groups.append("customer")
    return _unique_reasons(groups)


def _score_business_groups(name: str, comment: str, groups: list[str]) -> tuple[float, list[str]]:
    if not groups:
        return 0.0, []
    text = f"{name} {comment}".lower()
    group_terms = {
        "application": ("application", "apply", "approval", "申请", "进件", "审批"),
        "account": ("account", "loan", "balance", "disbursement", "放款", "余额", "借据", "本金"),
        "repayment": ("repayment", "overdue", "dpd", "mob", "vintage", "还款", "逾期", "账龄", "批次"),
        "collection": ("collection", "recovery", "催收", "回收", "入催"),
        "customer": ("customer", "segment", "risk", "客户", "客群", "风险"),
    }
    score = 0.0
    reasons: list[str] = []
    for group in groups:
        terms = group_terms.get(group, ())
        if any(term in text for term in terms):
            score += 18
            reasons.append(f"业务域匹配: {business_group_label(group)}")
    return score, reasons


def business_group_label(group: str) -> str:
    labels = {
        "application": "申请/审批",
        "account": "放款/账户",
        "repayment": "还款/逾期",
        "collection": "催收/回收",
        "customer": "客户/风险",
    }
    return labels.get(group, group)


def _asset_match_score(item: dict[str, Any], question_profile: dict[str, Any], fields: tuple[str, ...]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    for field in fields:
        field_score, field_reasons = _match_label(str(item.get(field) or ""), question_profile, "业务资产")
        score += field_score
        reasons.extend(field_reasons)
    return score, _unique_reasons(reasons)


def _match_label(label: str, question_profile: dict[str, Any], prefix: str) -> tuple[float, list[str]]:
    compact = _compact(label)
    if not compact or len(compact) <= 1:
        return 0.0, []
    question_compact = question_profile["compact"]
    score = 0.0
    reasons: list[str] = []
    if len(compact) >= 2 and compact in question_compact:
        score += 30 if re.search(r"[\u4e00-\u9fff]", compact) else 20
        reasons.append(f"{prefix}命中 {label}")
    for token in _tokens(label):
        if token in question_profile["tokens"]:
            score += 12 if re.search(r"[\u4e00-\u9fff]", token) else 8
            reasons.append(f"{prefix}词命中 {token}")
    return score, reasons


def _boost_mapping(
    mapping: dict[str, Any],
    table_boosts: dict[str, dict[str, Any]],
    column_boosts: dict[tuple[str, str], dict[str, Any]],
    table_score: float,
    column_score: float,
    reason: str,
    extra_reasons: list[str] | None = None,
) -> None:
    table_name = str(mapping.get("table_name") or "")
    column_name = str(mapping.get("column_name") or "")
    reasons = [reason, *(extra_reasons or [])]
    if table_name:
        _add_boost(table_boosts, table_name, table_score, reasons)
    if table_name and column_name:
        _add_boost(column_boosts, (table_name, column_name), column_score, reasons)


def _add_boost(target: dict[Any, dict[str, Any]], key: Any, score: float, reasons: list[str]) -> None:
    item = target.setdefault(key, {"score": 0.0, "reasons": []})
    item["score"] += score
    item["reasons"] = _unique_reasons([*item["reasons"], *reasons])[:5]


def _question_profile(question: str) -> dict[str, Any]:
    compact = _compact(question)
    tokens = _tokens(question)
    return {
        "compact": compact,
        "tokens": tokens,
        "asks_count": _contains_any(compact, ("多少笔", "几笔", "笔数", "数量", "次数", "count", "top", "排名")),
        "asks_application": _contains_any(compact, ("申请", "application", "apply")),
        "asks_amount": _contains_any(compact, ("金额", "余额", "amount")),
        "asks_region": _contains_any(compact, ("区域", "地区", "region", "area")),
    }


def _looks_like_count_metric(metric: dict[str, Any]) -> bool:
    metric_key = str(metric.get("metric_key") or "").lower()
    metric_name = str(metric.get("name") or "")
    aggregation = str(metric.get("aggregation") or "").lower()
    aliases = " ".join(str(value or "") for value in metric.get("synonyms", []) or [])
    label_text = f"{metric_name} {aliases}"
    return (
        bool(re.search(r"(^|_)count($|_)", metric_key))
        or aggregation == "count"
        or _contains_any(label_text, ("数量", "笔数", "件数", "次数", "申请数", "申请量", "进件量"))
    )


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(value.lower() in lowered for value in values)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _split_qualified(value: str) -> tuple[str, str]:
    if "." not in value:
        return "", ""
    left, right = value.split(".", 1)
    return left.strip("` "), right.strip("` ")


def _unique_reasons(reasons: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for reason in reasons:
        clean = str(reason or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _score_text(values: list[str], tokens: set[str], semantic_terms: set[str]) -> tuple[float, list[str]]:
    text = " ".join(value for value in values if value).lower()
    score = 0.0
    reasons: list[str] = []
    for token in tokens:
        if token and token in text:
            score += 6 if re.search(r"[\u4e00-\u9fff]", token) else 4
            reasons.append(f"问题命中 {token}")
    for term in semantic_terms:
        if term and term in text:
            score += 2
            if len(reasons) < 3:
                reasons.append(f"语义资产命中 {term}")
    return score, reasons[:4]
