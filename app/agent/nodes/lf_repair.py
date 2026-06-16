async def lf_repair_node(state: dict) -> dict:
    """SQL 执行失败后的轻量修复挂点。

    当前版本不让模型绕过 LogicForm 直接写 SQL，只记录失败并回到校验/编译链路。
    后续可以在这里基于错误类型调整 LogicForm 槽位。
    """
    trace = dict(state.get("execution_trace") or {})
    repairs = list(trace.get("repairs", []))
    repairs.append(
        {
            "sql_error": state.get("sql_error", ""),
            "attempt": state.get("sql_retry_count", 0),
            "action": "retry_logic_form_compile",
        }
    )
    trace["repairs"] = repairs
    return {"execution_trace": trace}
