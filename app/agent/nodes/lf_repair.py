import re


async def lf_repair_node(state: dict) -> dict:
    """SQL 执行失败后的轻量修复挂点。

    当前版本不让模型绕过 LogicForm 直接写 SQL，只记录失败并回到校验/编译链路。
    后续可以在这里基于错误类型调整 LogicForm 槽位。
    """
    trace = dict(state.get("execution_trace") or {})
    logic_form = dict(state.get("logic_form") or {})
    sql_error = state.get("sql_error", "")
    semantic_check = state.get("semantic_check") or {}
    errors = list(semantic_check.get("errors") or [])
    if sql_error and sql_error not in errors:
        errors.append(sql_error)
    repaired_logic_form, actions = repair_logic_form(logic_form, errors)
    repairs = list(trace.get("repairs", []))
    repairs.append(
        {
            "sql_error": sql_error,
            "attempt": state.get("sql_retry_count", 0),
            "action": "semantic_repair" if actions else "retry_logic_form_compile",
            "details": actions,
        }
    )
    trace["repairs"] = repairs
    return {
        "logic_form": repaired_logic_form or logic_form,
        "execution_trace": trace,
        "sql_error": None,
        "sql_retry_count": state.get("sql_retry_count", 0) + 1,
    }


def repair_logic_form(logic_form: dict, errors: list[str]) -> tuple[dict, list[str]]:
    repaired = dict(logic_form or {})
    actions: list[str] = []
    dimensions = list(repaired.get("dimensions") or [])
    metrics = list(repaired.get("metrics") or [])

    for error in errors:
        unsupported_dimension = re.search(r"不支持维度[:：]\s*([A-Za-z0-9_]+)", str(error))
        if unsupported_dimension:
            dimension = unsupported_dimension.group(1)
            if dimension in dimensions:
                dimensions = [item for item in dimensions if item != dimension]
                actions.append(f"移除不支持维度 {dimension}")

        unknown_metric = re.search(r"未知指标[:：]\s*([A-Za-z0-9_]+)", str(error))
        if unknown_metric:
            metric = unknown_metric.group(1)
            if metric in metrics:
                metrics = [item for item in metrics if item != metric]
                actions.append(f"移除未知指标 {metric}")

        if "缺少默认时间字段" in str(error) and repaired.get("time_range"):
            repaired["time_range"] = None
            actions.append("移除无法应用的时间范围")

    repaired["dimensions"] = dimensions
    repaired["metrics"] = metrics
    return repaired, actions
