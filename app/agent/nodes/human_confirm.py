async def sql_confirmation_node(state: dict) -> dict:
    """Pause before SQL execution when the caller requires human approval."""
    sql = state.get("compiled_sql") or state.get("sql_text") or ""
    payload = {
        "required": True,
        "status": "pending",
        "message": "SQL 已生成，等待用户确认后执行。",
        "sql": sql,
    }
    return {
        "human_confirmation": payload,
        "final_answer": payload["message"],
        "sql_result": [],
        "sql_error": None,
        "execution_trace": {
            **dict(state.get("execution_trace") or {}),
            "human_confirmation": payload,
        },
    }
