"""SQL 执行节点 —— 安全校验、权限检查、执行查询并格式化结果。

SQLExecuteNode 是问数链路的执行引擎,负责:
1. SQL 安全校验(normalize_sql_for_execution):拦截 DML/DDL/危险函数,注入 LIMIT。
2. 权限检查(validate_sql_access):验证 SQL 引用的表是否在 agent 白名单内。
3. 执行查询:对业务库执行 SELECT,记录耗时、行数、SQL 预览。
4. 行级脱敏(mask_rows):对配置了脱敏策略的列进行脱敏处理。
5. 结果格式化(format_result):把原始行转为自然语言摘要。
6. 慢查询告警:超过 SLOW_QUERY_THRESHOLD_SECONDS 时记录 warning。

异常时记录错误并进入 lf_repair 修复链路。
"""

import logging
import time

from app.db.mysql import get_business_db, get_datasource_db
from app.services.permission_service import get_permission_service
from app.utils.logging_helpers import (
    json_for_log,
    log_node_end,
    log_node_error,
    log_node_start,
    truncate_text,
)
from app.utils.sql_validator import normalize_sql_for_execution

logger = logging.getLogger(__name__)
# 慢查询告警阈值(秒)
SLOW_QUERY_THRESHOLD_SECONDS = 2.0


async def sql_execute_node(state: dict) -> dict:
    """SQL 执行节点."""
    log_node_start(
        logger,
        "sql_execute",
        state,
        keys=(
            "trace_id",
            "agent_id",
            "datasource_id",
            "compiled_sql",
            "sql_text",
            "sql_retry_count",
        ),
    )
    sql = state.get("compiled_sql") or state.get("sql_text", "")
    agent_id = state.get("agent_id")
    datasource_id = state.get("datasource_id")
    retry_count = state.get("sql_retry_count", 0)
    trace_id = state.get("trace_id", "")

    if not sql:
        result = {
            "sql_result": [],
            "sql_error": "SQL为空",
            "final_answer": "未能编译出可执行 SQL。",
        }
        log_node_end(logger, "sql_execute", result)
        return result

    # 第1步:SQL 安全校验 —— 拦截 DML/DDL/危险函数,注入 LIMIT
    validation = normalize_sql_for_execution(sql)
    logger.info(
        "sql normalize trace_id=%s ok=%s reason=%s original=%s normalized=%s",
        trace_id,
        validation.ok,
        validation.reason,
        truncate_text(sql, 1600),
        truncate_text(validation.sql, 1600),
    )
    if not validation.ok:
        # 安全校验失败:直接拦截,不进入修复链路(因为不是语义问题)
        result = {
            "sql_result": [],
            "sql_error": f"安全拦截: {validation.reason}",
            "final_answer": f"安全拦截: {validation.reason}",
            "sql_retry_count": retry_count + 1,
        }
        log_node_end(logger, "sql_execute", result)
        return result
    safe_sql = validation.sql

    # 第2步:权限校验 —— 检查 SQL 引用的表是否在 agent 白名单内
    access_ok, access_reason = await get_permission_service().validate_sql_access(
        agent_id, datasource_id, safe_sql
    )
    logger.info(
        "sql permission check trace_id=%s agent_id=%s datasource_id=%s allowed=%s reason=%s",
        trace_id,
        agent_id,
        datasource_id,
        access_ok,
        access_reason,
    )
    if not access_ok:
        result = {
            "sql_result": [],
            "sql_error": f"权限拦截: {access_reason}",
            "final_answer": f"权限拦截: {access_reason}",
            "sql_retry_count": retry_count + 1,
            "execution_trace": {
                **dict(state.get("execution_trace") or {}),
                "trace_id": trace_id,
                "permission": {
                    "allowed": False,
                    "reason": access_reason,
                },
            },
        }
        log_node_end(logger, "sql_execute", result)
        return result

    # 第3步:执行查询 —— 对业务库执行 SELECT,记录耗时和行数
    try:
        db = await get_datasource_db(datasource_id) if datasource_id else get_business_db()
        started_at = time.monotonic()
        logger.info(
            "sql executing trace_id=%s datasource_id=%s sql=%s",
            trace_id,
            datasource_id,
            truncate_text(safe_sql, 2400),
        )
        results = await db.execute_query(safe_sql)
        masked_results, masking_applied = await get_permission_service().mask_rows(
            agent_id, datasource_id, results
        )
        duration_ms = round((time.monotonic() - started_at) * 1000, 2)
        slow_query = duration_ms >= SLOW_QUERY_THRESHOLD_SECONDS * 1000
        if slow_query:
            logger.warning(
                "slow SQL query trace_id=%s duration_ms=%s rows=%s sql=%s",
                trace_id,
                duration_ms,
                len(masked_results),
                safe_sql,
            )
        execution_trace = dict(state.get("execution_trace") or {})
        execution_trace.update(
            {
                "trace_id": trace_id or execution_trace.get("trace_id"),
                "sql_security": {
                    "normalized": safe_sql != sql.strip(),
                    "limit_injected": "LIMIT" not in sql.upper(),
                    "max_limit": 1000,
                },
                "sql_execution": {
                    "duration_ms": duration_ms,
                    "row_count": len(masked_results),
                    "slow_query": slow_query,
                },
                "permission": {
                    "allowed": True,
                    "masked_columns": masking_applied,
                },
            }
        )
        logger.info(
            "sql executed trace_id=%s duration_ms=%s rows=%s masked_columns=%s sample=%s",
            trace_id,
            duration_ms,
            len(masked_results),
            json_for_log(masking_applied),
            json_for_log(masked_results[:3]),
        )
        result = {
            "sql_result": masked_results,
            "sql_error": None,
            "compiled_sql": safe_sql,
            "sql_text": safe_sql,
            "execution_trace": execution_trace,
            "final_answer": format_result(masked_results, safe_sql),
        }
        log_node_end(
            logger,
            "sql_execute",
            {
                "row_count": len(masked_results),
                "sql_error": None,
                "compiled_sql": safe_sql,
                "execution_trace": execution_trace,
                "final_answer": result["final_answer"],
            },
        )
        return result
    except Exception as e:
        log_node_error(logger, "sql_execute", e, state)
        execution_trace = dict(state.get("execution_trace") or {})
        execution_trace.update(
            {
                "trace_id": trace_id or execution_trace.get("trace_id"),
                "sql_execution": {
                    "error_type": e.__class__.__name__,
                    "error": str(e),
                },
            }
        )
        result = {
            "sql_result": [],
            "sql_error": str(e),
            "final_answer": f"SQL执行失败: {e}",
            "sql_retry_count": retry_count + 1,
            "execution_trace": execution_trace,
        }
        log_node_end(logger, "sql_execute", result)
        return result


def format_result(results: list[dict], sql: str) -> str:
    """Generate a short natural-language answer from SQL result rows."""
    if not results:
        return "查询结果为空，没有匹配的数据。"

    if len(results) == 1:
        sentence = describe_single_row(results[0])
        if sentence:
            return sentence
    return f"查询完成，共 {len(results)} 条结果。详细数据已在结果表中展示。"


def describe_single_row(row: dict) -> str:
    """Summarize a single-row result using the first dimension and metric when possible."""
    if not row:
        return ""
    numeric_items = [(key, row[key]) for key in row if is_number_like(row[key])]
    dimension_items = [
        (key, row[key])
        for key in row
        if not is_number_like(row[key]) and row[key] not in (None, "")
    ]
    if dimension_items and numeric_items:
        dimension_key, dimension_value = dimension_items[0]
        metric_key, metric_value = numeric_items[0]
        metric_label = field_label(metric_key)
        formatted_value = format_value(metric_key, metric_value)
        return f"{dimension_value}的 {metric_label}为 {formatted_value}。"
    if numeric_items:
        metric_key, metric_value = numeric_items[0]
        return f"{field_label(metric_key)}为 {format_value(metric_key, metric_value)}。"
    return "查询完成，共 1 条结果。详细数据已在结果表中展示。"


def field_label(key: str) -> str:
    """Return a readable fallback label when no semantic label is available."""
    return str(key or "")


def is_number_like(value) -> bool:
    """Return true for numeric values and numeric strings, excluding booleans."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str) and value.strip():
        try:
            float(value)
            return True
        except ValueError:
            return False
    return False


def format_value(key: str, value) -> str:
    """Format numeric values, percentages, and plain values for final answers."""
    number = float(value)
    if should_format_percent(key, number):
        return f"{number * 100:.2f}%"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.4f}".rstrip("0").rstrip(".")


def should_format_percent(key: str, value: float) -> bool:
    """Infer whether a metric key should be rendered as a percentage."""
    if abs(value) > 1:
        return False
    return any(
        token in key.lower()
        for token in ("rate", "ratio", "percent", "pct", "probability", "pd", "dti")
    )
