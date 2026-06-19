import logging

from app.utils.logging_helpers import log_node_end, log_node_start, truncate_text

logger = logging.getLogger(__name__)


async def sql_confirmation_node(state: dict) -> dict:
    """Pause before SQL execution when the caller requires human approval."""
    log_node_start(
        logger,
        "sql_confirmation",
        state,
        keys=("trace_id", "agent_id", "datasource_id", "compiled_sql", "sql_text"),
    )
    sql = state.get("compiled_sql") or state.get("sql_text") or ""
    logger.info("sql confirmation pending sql=%s", truncate_text(sql, 1600))
    payload = {
        "required": True,
        "status": "pending",
        "message": "SQL 已生成，等待用户确认后执行。",
        "sql": sql,
    }
    result = {
        "human_confirmation": payload,
        "final_answer": payload["message"],
        "sql_result": [],
        "sql_error": None,
        "execution_trace": {
            **dict(state.get("execution_trace") or {}),
            "human_confirmation": payload,
        },
    }
    log_node_end(logger, "sql_confirmation", result)
    return result
