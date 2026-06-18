
import logging
import time

from app.db.mysql import get_business_db, get_datasource_db
from app.services.permission_service import get_permission_service
from app.utils.sql_validator import normalize_sql_for_execution


logger = logging.getLogger(__name__)
SLOW_QUERY_THRESHOLD_SECONDS = 2.0


async def sql_execute_node(state: dict) -> dict:
    """SQL 执行节点."""
    sql = state.get("compiled_sql") or state.get("sql_text", "")
    agent_id = state.get("agent_id")
    datasource_id = state.get("datasource_id")
    retry_count = state.get("sql_retry_count", 0)
    trace_id = state.get("trace_id", "")

    if not sql:
        return {"sql_result": [], "sql_error": "SQL为空", "final_answer": "未能编译出可执行 SQL。"}

    validation = normalize_sql_for_execution(sql)
    if not validation.ok:
        return {
            "sql_result": [],
            "sql_error": f"安全拦截: {validation.reason}",
            "final_answer": f"安全拦截: {validation.reason}",
            "sql_retry_count": retry_count + 1,
        }
    safe_sql = validation.sql
    access_ok, access_reason = await get_permission_service().validate_sql_access(agent_id, datasource_id, safe_sql)
    if not access_ok:
        return {
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

    try:
        db = await get_datasource_db(datasource_id) if datasource_id else get_business_db()
        started_at = time.monotonic()
        results = await db.execute_query(safe_sql)
        masked_results, masking_applied = await get_permission_service().mask_rows(agent_id, datasource_id, results)
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
        execution_trace.update({
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
        })
        return {
            "sql_result": masked_results,
            "sql_error": None,
            "compiled_sql": safe_sql,
            "sql_text": safe_sql,
            "execution_trace": execution_trace,
            "final_answer": format_result(masked_results, safe_sql),
        }
    except Exception as e:
        execution_trace = dict(state.get("execution_trace") or {})
        execution_trace.update({
            "trace_id": trace_id or execution_trace.get("trace_id"),
            "sql_execution": {
                "error_type": e.__class__.__name__,
                "error": str(e),
            },
        })
        return {
            "sql_result": [],
            "sql_error": str(e),
            "final_answer": f"SQL执行失败: {e}",
            "sql_retry_count": retry_count + 1,
            "execution_trace": execution_trace,
        }


FIELD_LABELS = {
    "approval_rate": "审批通过率",
    "application_count": "申请笔数",
    "disbursement_amount": "放款金额",
    "outstanding_balance": "贷款余额",
    "m1_plus_rate": "M1+逾期率",
    "mob": "账龄",
    "dpd": "逾期天数",
    "vintage": "放款批次",
    "pd": "预测违约概率",
    "dti": "负债收入比",
    "writeoff_amount": "核销金额",
    "collection_recovery_rate": "催收回收率",
    "product_type": "产品类型",
    "application_product_type": "申请产品类型",
    "application_region": "申请地区",
    "application_risk_grade": "申请风险等级",
    "region": "地区",
    "channel": "渠道",
    "risk_grade": "风险等级",
    "overdue_bucket": "逾期阶段",
    "assigned_team": "催收团队",
    "collection_strategy": "催收策略",
    "overdue_bucket_at_entry": "入催逾期阶段",
    "customer_segment": "客户分层",
}


def format_result(results: list[dict], sql: str) -> str:
    if not results:
        return "查询结果为空，没有匹配的数据。"

    if len(results) == 1:
        sentence = describe_single_row(results[0])
        if sentence:
            return sentence
    return f"查询完成，共 {len(results)} 条结果。详细数据已在结果表中展示。"


def describe_single_row(row: dict) -> str:
    if not row:
        return ""
    numeric_items = [(key, row[key]) for key in row if is_number_like(row[key])]
    dimension_items = [(key, row[key]) for key in row if not is_number_like(row[key]) and row[key] not in (None, "")]
    if dimension_items and numeric_items:
        dimension_key, dimension_value = dimension_items[0]
        metric_key, metric_value = numeric_items[0]
        return f"{dimension_value}的 {field_label(metric_key)}为 {format_value(metric_key, metric_value)}。"
    if numeric_items:
        metric_key, metric_value = numeric_items[0]
        return f"{field_label(metric_key)}为 {format_value(metric_key, metric_value)}。"
    return "查询完成，共 1 条结果。详细数据已在结果表中展示。"


def field_label(key: str) -> str:
    return FIELD_LABELS.get(key, key)


def is_number_like(value) -> bool:
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
    number = float(value)
    if should_format_percent(key, number):
        return f"{number * 100:.2f}%"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.4f}".rstrip("0").rstrip(".")


def should_format_percent(key: str, value: float) -> bool:
    if abs(value) > 1:
        return False
    return any(token in key.lower() for token in ("rate", "ratio", "percent", "pct", "probability", "pd", "dti"))
