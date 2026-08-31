"""Helpers for narrowing schema recall to the subject explicitly named by a query."""

from __future__ import annotations

from typing import Any


def primary_scope_tables(runtime: dict[str, Any]) -> set[str]:
    """Find tables represented by subject-specific semantic assets."""
    tables: set[str] = set()
    for mapping in runtime.get("mappings", []) or []:
        if not isinstance(mapping, dict):
            continue
        key = str(mapping.get("asset_key") or "")
        table = str(mapping.get("table_name") or "")
        if table and (key.startswith("application_") or "application" in table.lower()):
            tables.add(table)
    for metric in runtime.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        table = str(metric.get("base_table") or "")
        if table and "application" in table.lower():
            tables.add(table)
    return tables


def subject_focus(profile: dict[str, Any]) -> bool:
    """Detect a primary application/ingress subject before broad loan terms dominate."""
    compact = str(profile.get("compact") or "")
    return any(term in compact for term in ("申请", "进件", "application"))


def explicit_metric(metric: dict[str, Any], profile: dict[str, Any]) -> bool:
    """Return true for a concrete metric label, not a generic subject word."""
    question = str(profile.get("compact") or "")
    for value in (
        metric.get("metric_key"),
        metric.get("name"),
        *(metric.get("synonyms") or []),
    ):
        label = "".join(str(value or "").lower().split())
        if (
            len(label) >= 2
            and label not in {"贷款", "申请", "数量", "总数", "总量"}
            and label in question
        ):
            return True
    return False


def primary_channel_scope(
    profile: dict[str, Any], runtime: dict[str, Any], scope_tables: set[str]
) -> bool:
    """Use only subject tables for an explicit channel breakdown query."""
    compact = str(profile.get("compact") or "")
    if not subject_focus(profile):
        return False
    if not any(
        term in compact
        for term in (
            "申请渠道",
            "申请状态",
            "审批状态",
            "审批进度",
            "审批结果",
            "application_channel",
            "application_approval_status",
        )
    ):
        return False
    return not any(
        str(metric.get("base_table") or "") not in scope_tables
        and explicit_metric(metric, profile)
        for metric in runtime.get("metrics", []) or []
        if isinstance(metric, dict)
    )
