"""Small business-field label helpers used by user-facing summaries."""

from __future__ import annotations

import re
from typing import Any

# These are deliberately conservative aliases.  Unknown keys remain visible so
# a technical field can still be traced back to SQL/result details.
KNOWN_FIELD_LABELS = {
    "assigned_team": "负责团队",
    "collector_team": "催收团队",
    "application_region": "申请区域",
    "region": "区域",
    "application_product_type": "贷款产品",
    "product_type": "产品类型",
    "application_count": "申请笔数",
    "collection_recovery_rate": "催收回收率",
    "m1_plus_rate": "M1+逾期率",
    "m2_plus_rate": "M2+逾期率",
    "m3_plus_rate": "M3+逾期率",
    "snapshot_date": "快照日期",
    "apply_date": "申请日期",
}


def human_field_label(key: Any, *, fallback_to_key: bool = True) -> str:
    """Return a configured label, or a readable fallback for snake-case keys."""
    value = str(key or "").strip()
    if not value:
        return ""
    if value in KNOWN_FIELD_LABELS:
        return KNOWN_FIELD_LABELS[value]
    if not fallback_to_key:
        return ""
    # Keep already human-readable labels untouched; only expand technical
    # snake/kebab names to avoid presenting an opaque identifier.
    if re.search(r"[_-]", value):
        return re.sub(r"[_-]+", " ", value).strip()
    return value


__all__ = ["KNOWN_FIELD_LABELS", "human_field_label"]
