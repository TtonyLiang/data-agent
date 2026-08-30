"""统一的最终回答节点。

ReAct 控制器决定不需要深度分析时由此节点收束请求，避免把 Planner/Python/报告
生成当成所有问题的必经步骤。节点只消费已经完成的观察，不执行新的数据库操作。
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.nodes.sql_execute import format_value, is_number_like
from app.utils.field_labels import human_field_label
from app.utils.logging_helpers import log_node_end, log_node_start

logger = logging.getLogger(__name__)


def _friendly_error(error: Any) -> str:
    text = str(error or "").strip()
    if not text:
        return "这次查询没有完成，请补充更明确的指标、维度或时间范围后再试。"
    if text.startswith("SQL执行失败:"):
        detail = text.split(":", 1)[1].strip()
        return f"这次查询没有完成：{detail}。已停止自动重试，避免重复执行。"
    if text.startswith("SQL 执行失败:"):
        detail = text.split(":", 1)[1].strip()
        return f"这次查询没有完成：{detail}。已停止自动重试，避免重复执行。"
    return text


def _field_labels(state: dict[str, Any]) -> dict[str, str]:
    """Build human-readable labels from semantic assets when available."""
    labels: dict[str, str] = {}
    runtime = state.get("semantic_runtime") or {}
    for item in runtime.get("metrics", []) if isinstance(runtime, dict) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("metric_key") or item.get("asset_key") or "").strip()
        name = str(item.get("name") or item.get("label") or "").strip()
        if key and name:
            labels[key] = name
    for item in runtime.get("mappings", []) if isinstance(runtime, dict) else []:
        if not isinstance(item, dict):
            continue
        key = str(
            item.get("asset_key") or item.get("column_name") or item.get("column") or ""
        ).strip()
        name = str(item.get("name") or item.get("label") or item.get("description") or "").strip()
        if key and name:
            labels[key] = name
    return labels


def _natural_result_answer(rows: list[dict[str, Any]], state: dict[str, Any]) -> str:
    """Render a concise answer while leaving full rows to the result table."""
    if not rows:
        return "没有找到符合条件的数据。你可以调整筛选条件或时间范围后再试。"
    labels = _field_labels(state)
    if len(rows) == 1:
        row = rows[0] or {}
        numeric_items = [(key, value) for key, value in row.items() if is_number_like(value)]
        dimensions = [
            (key, value)
            for key, value in row.items()
            if not is_number_like(value) and value not in (None, "")
        ]
        if dimensions and numeric_items:
            _, dimension_value = dimensions[0]
            metric_key, metric_value = numeric_items[0]
            metric_label = labels.get(metric_key) or human_field_label(metric_key)
            return f"{dimension_value}的{metric_label}为 {format_value(metric_key, metric_value)}。"
        if numeric_items:
            metric_key, metric_value = numeric_items[0]
            metric_label = labels.get(metric_key) or human_field_label(metric_key)
            return f"{metric_label}为 {format_value(metric_key, metric_value)}。"
    return f"已找到 {len(rows)} 条结果，详细明细已在结果表中展示。"


async def respond_node(state: dict[str, Any]) -> dict[str, Any]:
    """根据 SQL 观察生成简洁、稳定且非空的最终回答。"""
    log_node_start(
        logger,
        "respond",
        state,
        keys=("trace_id", "agent_id", "question", "sql_error", "sql_retry_count"),
    )
    rows = state.get("sql_result") or []
    error = state.get("sql_error")
    existing = str(state.get("final_answer") or "").strip()

    # A stale error from a previous retry must not hide a successful result.
    if (
        not rows
        and str(state.get("intent") or "").strip().lower() == "data_query"
        and not state.get("datasource_id")
    ):
        answer = "当前智能体还没有绑定数据源，先在数据源管理中绑定后再查询。"
        mode = "missing_datasource"
    elif rows:
        answer = _natural_result_answer(rows, state)
        mode = "result"
    elif error:
        answer = _friendly_error(error)
        mode = "error"
    elif existing and existing not in {"查询完成，未返回匹配数据", ""}:
        answer = existing
        mode = "existing"
    else:
        answer = "没有找到符合条件的数据。你可以调整筛选条件或时间范围后再试。"
        mode = "empty"

    result = {
        "final_answer": answer,
        "response": {
            "mode": mode,
            "row_count": len(rows),
            "analysis_skipped": not bool(state.get("analysis_required")),
        },
    }
    log_node_end(logger, "respond", result)
    return result


__all__ = ["respond_node"]
