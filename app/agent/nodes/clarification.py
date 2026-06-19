import logging

from app.utils.logging_helpers import log_node_end, log_node_start

logger = logging.getLogger(__name__)


async def clarification_node(state: dict) -> dict:
    """Stop the graph with a clarification request when schema recall confidence is too low."""
    log_node_start(
        logger,
        "clarification",
        state,
        keys=("trace_id", "agent_id", "question", "enhanced_question", "schema_scope"),
    )
    question = state.get("enhanced_question") or state.get("question") or ""
    message = (
        "当前问题没有定位到足够明确的数据表或字段。"
        "请补充业务对象、时间范围、指标口径或希望查看的维度后再查询。"
    )
    result = {
        "clarification": {
            "required": True,
            "reason": "low_schema_confidence",
            "question": question,
            "message": message,
        },
        "final_answer": message,
        "sql_result": [],
        "sql_error": None,
    }
    log_node_end(logger, "clarification", result)
    return result
