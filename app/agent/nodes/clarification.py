"""低置信度追问节点 —— 当意图识别置信度不足时,生成引导性追问。

触发条件:意图识别返回 needs_clarification 时进入此节点。
输出:question 字段填充为引导性追问文本,随后 graph 路由到 END,
用户回复后重新进入意图识别。
"""

import logging

from app.utils.logging_helpers import log_node_end, log_node_start

logger = logging.getLogger(__name__)


async def clarification_node(state: dict) -> dict:
    """低置信度追问:停止图执行,向用户发出引导性问题。"""
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
