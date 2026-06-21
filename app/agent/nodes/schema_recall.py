"""数据定位节点 —— 从已采集的表结构中筛选出与问题相关的候选表和字段。

SchemaRecallNode 是语义增强后的第三个节点,负责:
1. 文本匹配:把用户问题与表名/表注释/字段名/字段注释做 token 级匹配打分。
2. 业务加权:从 semantic_runtime 中读取 recall 规则,对匹配的表做额外加分。
3. 阈值筛选:按 required_score_ratio/optional_score_ratio 相对阈值分层筛选。
4. 外键推断:自动发现候选表之间的外键关系,生成 JOIN Hint。
5. 噪音控制:限制最多 max_tables 张表和 max_columns 个字段,避免大模型噪音。

筛选结果存入 state.tables_columns 和 state.table_names,供 NL2LF 和 NL2SQL 兜底使用。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agent.domain_rules import (
    business_groups_from_runtime,
    contains_any,
    recall_profiles_from_runtime,
    schema_hints_from_runtime,
)
from app.services.metadata_service import get_metadata_service
from app.services.system_parameter_service import get_system_parameter_service
from app.config import get_settings
from app.utils.logging_helpers import json_for_log, log_node_end, log_node_start, truncate_text

# token 切分正则:英文/数字/下划线为一个 token,连续中文字符为一个 token
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
logger = logging.getLogger(__name__)


async def schema_recall_node(state: dict) -> dict:
    """Recall collected physical tables/columns for SQL grounding."""
    log_node_start(
        logger,
        "schema_recall",
        state,
        keys=("trace_id", "agent_id", "datasource_id", "enhanced_question", "question"),
    )
    datasource_id = state.get("datasource_id")
    if not datasource_id:
        result = {
            "relevant_tables": [],
            "relevant_columns": [],
            "likely_joins": [],
            "schema_scope": {
                "mode": "missing_datasource",
                "message": "缺少数据源，跳过数据定位。",
            },
        }
        log_node_end(logger, "schema_recall", result)
        return result

    metadata_service = get_metadata_service()
    if hasattr(metadata_service, "get_authorized_schema"):
        schema = await metadata_service.get_authorized_schema(datasource_id, state.get("agent_id"))
    else:
        schema = await metadata_service.get_schema(datasource_id)
    logger.info(
        "schema recall loaded schema datasource_id=%s table_count=%s",
        datasource_id,
        len(schema or []),
    )
    if not schema:
        result = {
            "relevant_tables": [],
            "relevant_columns": [],
            "likely_joins": [],
            "schema_scope": {
                "mode": "empty_schema",
                "message": "当前数据源没有已采集表结构。",
            },
        }
        log_node_end(logger, "schema_recall", result)
        return result

    runtime = state.get("semantic_runtime") or {}
    evidence = state.get("runtime_evidence") or []
    question = state.get("enhanced_question") or state.get("question", "")
    recall_profiles = recall_profiles_from_runtime(runtime, question)
    tokens = _tokens(question, recall_profiles)
    semantic_terms = _semantic_terms(runtime, evidence)
    business_priority = _business_priority(runtime, evidence, question, recall_profiles)
    business_groups = business_groups_from_runtime(runtime, question)
    schema_hints = schema_hints_from_runtime(runtime, question)
    recall_settings = await get_system_parameter_service().get_schema_recall_settings()
    settings = get_settings()
    logger.info(
        "schema recall signals question=%s tokens=%s semantic_terms_count=%s "
        "evidence_count=%s business_groups=%s schema_hints=%s recall_profiles=%s",
        truncate_text(question, 600),
        json_for_log(sorted(tokens)),
        len(semantic_terms),
        len(evidence),
        json_for_log(business_groups),
        json_for_log(schema_hints),
        json_for_log(recall_profiles),
    )

    # 候选表打分:每张表 = 文本匹配分 + 业务优先级分 + 业务分组分
    table_scores: dict[str, dict[str, Any]] = {}
    column_hits: list[dict[str, Any]] = []
    joins: list[dict[str, Any]] = []

    for table in schema:
        table_name = str(table.get("table_name") or "")
        table_comment = str(table.get("table_comment") or "")
        # 信号1:表名/表注释与问题 token 的文本匹配分
        table_score, table_reasons = _score_text(
            [table_name, table_comment],
            tokens,
            semantic_terms,
        )
        # 信号2:语义资产(指标/映射/关系)命中的业务优先级加分
        table_business = business_priority["tables"].get(table_name, {"score": 0.0, "reasons": []})
        table_score += float(table_business.get("score") or 0)
        table_reasons = [*table_business.get("reasons", []), *table_reasons]
        # 信号3:recall 规则中的业务分组加分(如"贷款"分组加权)
        group_score, group_reasons = _score_business_groups(
            table_name, table_comment, business_groups
        )
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

        # 字段级打分:每列 = 文本匹配分 + profile 加分 + 业务优先级分 + 业务分组分
        for column in table.get("columns") or []:
            column_name = str(column.get("column_name") or "")
            column_comment = str(column.get("column_comment") or "")
            # 信号1:字段名/字段注释/表名/表注释的文本匹配
            score, reasons = _score_text(
                [table_name, table_comment, column_name, column_comment],
                tokens,
                semantic_terms,
            )
            # 信号2:recall 规则中的 schema_hints 和 recall_profiles 加分
            profile_score, profile_reasons = _score_column_profile(
                table_name,
                column_name,
                column_comment,
                business_priority["question_profile"],
                schema_hints,
            )
            score += profile_score
            reasons = [*profile_reasons, *reasons]
            # 信号3:语义资产(指标/映射)命中的业务优先级加分
            column_business = business_priority["columns"].get(
                (table_name, column_name),
                {"score": 0.0, "reasons": []},
            )
            score += float(column_business.get("score") or 0)
            reasons = [*column_business.get("reasons", []), *reasons]
            # 信号4:业务分组加分
            column_group_score, column_group_reasons = _score_business_groups(
                f"{table_name}.{column_name}",
                column_comment,
                business_groups,
            )
            score += column_group_score
            reasons = [*column_group_reasons, *reasons]
            # 字段得分 > 0 时:给所在表加分(上限 6 分,防止单表因字段多而过度膨胀)
            if score > 0:
                table_scores[table_name]["score"] += min(score, 6)
                column_hits.append(
                    {
                        "table": table_name,
                        "table_name": table_name,
                        "column": column_name,
                        "column_name": column_name,
                        "comment": column_comment,
                        "column_comment": column_comment,
                        "data_type": column.get("data_type"),
                        "score": score,
                        "reason": "、".join(reasons),
                    }
                )
            if column.get("is_foreign_key") and column.get("foreign_key_ref"):
                joins.append(
                    {
                        "left": f"{table_name}.{column_name}",
                        "right": column.get("foreign_key_ref"),
                        "reason": "已采集外键关系",
                    }
                )

    matched_tables = sorted(
        table_scores.values(),
        key=lambda item: (-float(item.get("score") or 0), item.get("table_name") or ""),
    )
    positive_tables = [item for item in matched_tables if float(item.get("score") or 0) > 0]
    selected_tables, threshold_scope = select_tables_by_score(
        positive_tables,
        matched_tables,
        max_tables=recall_settings.max_tables,
        required_score_ratio=recall_settings.required_score_ratio,
        optional_score_ratio=recall_settings.optional_score_ratio,
    )
    selected_names = {item["table_name"] for item in selected_tables}

    matched_columns = [
        item
        for item in sorted(
            column_hits,
            key=lambda item: (
                -float(item.get("score") or 0),
                item.get("table_name") or "",
                item.get("column_name") or "",
            ),
        )
        if item["table_name"] in selected_names
    ][: max(1, settings.schema_recall_max_columns)]

    result = {
        "relevant_tables": selected_tables,
        "relevant_columns": matched_columns,
        "likely_joins": [
            item for item in joins if str(item.get("left", "")).split(".", 1)[0] in selected_names
        ][:12],
        "schema_scope": {
            "mode": "semantic_guided" if positive_tables else "collected_schema_fallback",
            "total_tables": len(schema),
            "matched_tables": len(selected_tables),
            "matched_columns": len(matched_columns),
            "fallback_used": not bool(positive_tables),
            **threshold_scope,
            "business_groups": business_groups,
            "recall_profiles": [
                {
                    "key": item.get("key"),
                    "label": item.get("label"),
                    "reason": item.get("reason"),
                }
                for item in recall_profiles
            ],
            "schema_hints": [
                {
                    "key": item.get("key"),
                    "label": item.get("label"),
                    "reason": item.get("reason"),
                }
                for item in schema_hints
            ],
        },
    }
    logger.info(
        "schema recall selected tables=%s columns=%s joins=%s scope=%s",
        json_for_log(selected_tables),
        json_for_log(matched_columns),
        json_for_log(result["likely_joins"]),
        json_for_log(result["schema_scope"]),
    )
    log_node_end(
        logger,
        "schema_recall",
        {
            "table_count": len(selected_tables),
            "column_count": len(matched_columns),
            "join_count": len(result["likely_joins"]),
            "schema_scope": result["schema_scope"],
        },
    )
    return result


def select_tables_by_score(
    positive_tables: list[dict[str, Any]],
    matched_tables: list[dict[str, Any]],
    *,
    max_tables: int,
    required_score_ratio: float,
    optional_score_ratio: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select candidate tables with relative score thresholds and a max cap."""
    max_tables = max(1, int(max_tables))
    if not positive_tables:
        return matched_tables[:max_tables], {
            "top_score": 0,
            "required_score": 0,
            "optional_score": 0,
            "required_score_ratio": required_score_ratio,
            "optional_score_ratio": optional_score_ratio,
            "selection_mode": "fallback_topn",
        }
    top_score = max(float(positive_tables[0].get("score") or 0), 0)
    required_score = top_score * max(0, min(required_score_ratio, 1))
    optional_score = top_score * max(0, min(optional_score_ratio, required_score_ratio, 1))
    required = [
        item for item in positive_tables if float(item.get("score") or 0) >= required_score
    ]
    optional = [
        item
        for item in positive_tables
        if optional_score <= float(item.get("score") or 0) < required_score
    ]
    selected = [*required, *optional[: max(0, max_tables - len(required))]]
    if not selected:
        selected = positive_tables[:1]
    return selected[:max_tables], {
        "top_score": round(top_score, 4),
        "required_score": round(required_score, 4),
        "optional_score": round(optional_score, 4),
        "required_score_ratio": required_score_ratio,
        "optional_score_ratio": optional_score_ratio,
        "selection_mode": "relative_threshold",
        "required_table_count": len(required),
        "optional_table_count": len(optional),
    }


def _tokens(text: str, recall_profiles: list[dict[str, Any]] | None = None) -> set[str]:
    """Split mixed Chinese and identifier text into normalized recall tokens."""
    tokens: set[str] = set()
    for token in TOKEN_RE.findall(text or ""):
        clean = token.lower().strip()
        if len(clean) <= 1:
            continue
        tokens.add(clean)
        if re.search(r"[A-Za-z_]", clean):
            tokens.update(part for part in re.split(r"[_\W]+", clean) if len(part) > 1)
    for profile in recall_profiles or []:
        tokens.update(str(term).lower() for term in profile.get("question_terms") or [] if term)
    return tokens


def _semantic_terms(runtime: dict, evidence: list[dict]) -> set[str]:
    """Collect searchable terms from recalled semantic runtime assets."""
    terms: set[str] = set()
    for item in evidence:
        metadata = item.get("metadata") or {}
        for value in (metadata.get("asset_key"), item.get("content")):
            terms.update(_tokens(str(value or "")))
    for group in ("metrics", "mappings", "concepts", "rules"):
        for item in runtime.get(group, []) if isinstance(runtime, dict) else []:
            for key in (
                "metric_key",
                "asset_key",
                "concept_key",
                "rule_key",
                "name",
                "description",
            ):
                terms.update(_tokens(str(item.get(key) or "")))
            for value in item.get("synonyms", []) or []:
                terms.update(_tokens(str(value)))
    return terms


def _business_priority(
    runtime: dict,
    evidence: list[dict],
    question: str,
    recall_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Translate matched semantic assets into table and column score boosts."""
    table_boosts: dict[str, dict[str, Any]] = {}
    column_boosts: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(runtime, dict):
        return {
            "tables": table_boosts,
            "columns": column_boosts,
            "question_profile": _question_profile(question, recall_profiles),
        }

    mappings = [item for item in runtime.get("mappings", []) or [] if isinstance(item, dict)]
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
    question_profile = _question_profile(question, recall_profiles)

    for metric in runtime.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        metric_key = str(metric.get("metric_key") or "")
        base_table = str(metric.get("base_table") or "")
        score, reasons = _metric_match(metric, evidence_keys, question_profile)
        if score <= 0 or not base_table:
            continue
        _add_boost(
            table_boosts,
            base_table,
            score + 40,
            [f"业务指标基础表: {metric.get('name') or metric_key}", *reasons],
        )
        for dim_key in metric.get("dimensions", []) or []:
            for mapping in mapping_by_asset.get(str(dim_key), []):
                _boost_mapping(
                    mapping, table_boosts, column_boosts, 32, 28, f"指标关联维度: {dim_key}"
                )

    for mapping in mappings:
        score, reasons = _mapping_match(mapping, question_profile)
        if score <= 0:
            continue
        _boost_mapping(
            mapping,
            table_boosts,
            column_boosts,
            score + 18,
            score + 10,
            "问题命中业务字段",
            reasons,
        )

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
                    _add_boost(
                        table_boosts,
                        table_name,
                        min(relation_score, 20),
                        [*relation_reasons, "业务关系关联表"],
                    )

    return {
        "tables": table_boosts,
        "columns": column_boosts,
        "question_profile": question_profile,
    }


def _metric_match(
    metric: dict[str, Any], evidence_keys: set[str], question_profile: dict[str, Any]
) -> tuple[float, list[str]]:
    """Score how strongly a metric matches the question and recalled evidence."""
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
    for profile in question_profile["profiles"]:
        score_delta, profile_reasons = _score_profile_against_text(profile, metric_text, "指标")
        score += score_delta
        reasons.extend(profile_reasons)

    return max(score, 0), _unique_reasons(reasons)


def _mapping_match(
    mapping: dict[str, Any], question_profile: dict[str, Any]
) -> tuple[float, list[str]]:
    """Score how strongly a semantic mapping matches the question profile."""
    score, reasons = _asset_match_score(
        mapping,
        question_profile,
        ("asset_key", "name", "description", "table_name", "column_name"),
    )
    mapping_text = " ".join(
        str(mapping.get(key) or "")
        for key in ("asset_key", "name", "description", "table_name", "column_name", "column_comment")
    ).lower()
    for profile in question_profile["profiles"]:
        score_delta, profile_reasons = _score_profile_against_text(profile, mapping_text, "字段映射")
        score += score_delta
        reasons.extend(profile_reasons)
    return max(score, 0), _unique_reasons(reasons)


def _score_business_groups(
    name: str, comment: str, groups: list[dict[str, Any]] | list[str]
) -> tuple[float, list[str]]:
    """Boost schema candidates that belong to inferred business groups."""
    if not groups:
        return 0.0, []
    text = f"{name} {comment}".lower()
    score = 0.0
    reasons: list[str] = []
    for group in groups:
        if isinstance(group, dict):
            terms = tuple(str(item).lower() for item in group.get("terms") or [])
            label = str(group.get("label") or group.get("key") or "")
            weight = float(group.get("weight") or 18)
        else:
            terms = ()
            label = str(group)
            weight = 0.0
        if any(term in text for term in terms):
            score += weight
            reasons.append(f"业务域匹配: {label}")
    return score, reasons


def _asset_match_score(
    item: dict[str, Any], question_profile: dict[str, Any], fields: tuple[str, ...]
) -> tuple[float, list[str]]:
    """Score generic semantic assets against question tokens and labels."""
    score = 0.0
    reasons: list[str] = []
    for field in fields:
        field_score, field_reasons = _match_label(
            str(item.get(field) or ""), question_profile, "业务资产"
        )
        score += field_score
        reasons.extend(field_reasons)
    return score, _unique_reasons(reasons)


def _match_label(
    label: str, question_profile: dict[str, Any], prefix: str
) -> tuple[float, list[str]]:
    """Score one label against compact question text and token sets."""
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
    """Apply table and column boosts for a physical semantic mapping."""
    table_name = str(mapping.get("table_name") or "")
    column_name = str(mapping.get("column_name") or "")
    reasons = [reason, *(extra_reasons or [])]
    if table_name:
        _add_boost(table_boosts, table_name, table_score, reasons)
    if table_name and column_name:
        _add_boost(column_boosts, (table_name, column_name), column_score, reasons)


def _add_boost(
    target: dict[Any, dict[str, Any]], key: Any, score: float, reasons: list[str]
) -> None:
    """Accumulate a score boost and reasons in a mutable boost map."""
    item = target.setdefault(key, {"score": 0.0, "reasons": []})
    item["score"] += score
    item["reasons"] = _unique_reasons([*item["reasons"], *reasons])[:5]


def _question_profile(
    question: str,
    recall_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract reusable intent flags from the current question."""
    tokens = _tokens(question, recall_profiles)
    return {
        "compact": _compact(question),
        "tokens": tokens,
        "profiles": recall_profiles or [],
    }


def _score_column_profile(
    table_name: str,
    column_name: str,
    column_comment: str,
    question_profile: dict[str, Any],
    schema_hints: list[dict[str, Any]] | None = None,
) -> tuple[float, list[str]]:
    """Boost raw schema columns that match explicit configured schema hints."""
    text = f"{table_name} {column_name} {column_comment}".lower()
    score = 0.0
    reasons: list[str] = []
    for hint in schema_hints or []:
        terms = [str(item) for item in hint.get("column_terms") or [] if str(item or "")]
        if not terms or not contains_any(text, terms):
            continue
        score += float(hint.get("weight") or 42)
        reasons.append(str(hint.get("reason") or f"命中字段提示: {hint.get('label') or hint.get('key')}"))
    for profile in question_profile["profiles"]:
        score_delta, profile_reasons = _score_profile_against_text(profile, text, "字段")
        score += score_delta
        reasons.extend(profile_reasons)
    return score, reasons


def _score_profile_against_text(
    profile: dict[str, Any],
    text: str,
    target_label: str,
) -> tuple[float, list[str]]:
    """Apply configured recall profile terms to a metric, mapping, table or column."""
    positive_terms = [str(item) for item in profile.get("positive_terms") or [] if str(item or "")]
    negative_terms = [str(item) for item in profile.get("negative_terms") or [] if str(item or "")]
    score = 0.0
    reasons: list[str] = []
    if positive_terms and contains_any(text, positive_terms):
        score += float(profile.get("weight") or 0)
        reasons.append(str(profile.get("reason") or f"{target_label}命中召回画像: {profile.get('label') or profile.get('key')}"))
    if negative_terms and contains_any(text, negative_terms):
        score -= float(profile.get("negative_weight") or profile.get("weight") or 0)
        negative_reason = profile.get("negative_reason") or f"{target_label}命中召回排除项: {profile.get('label') or profile.get('key')}"
        reasons.append(str(negative_reason))
    return score, reasons


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    """Return true when any token is present in text."""
    lowered = text.lower()
    return any(value.lower() in lowered for value in values)


def _compact(text: str) -> str:
    """Lowercase and remove whitespace for keyword matching."""
    return re.sub(r"\s+", "", text or "").lower()


def _split_qualified(value: str) -> tuple[str, str]:
    """Split a table.column reference into table and column parts."""
    if "." not in value:
        return "", ""
    left, right = value.split(".", 1)
    return left.strip("` "), right.strip("` ")


def _unique_reasons(reasons: list[str]) -> list[str]:
    """Deduplicate scoring reasons while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for reason in reasons:
        clean = str(reason or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _score_text(
    values: list[str], tokens: set[str], semantic_terms: set[str]
) -> tuple[float, list[str]]:
    """Score raw schema text against question and semantic terms."""
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
