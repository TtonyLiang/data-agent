async def clarification_node(state: dict) -> dict:
    question = state.get("enhanced_question") or state.get("question") or ""
    message = (
        "当前问题没有定位到足够明确的数据表或字段。"
        "请补充业务对象、时间范围、指标口径或希望查看的维度后再查询。"
    )
    return {
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
