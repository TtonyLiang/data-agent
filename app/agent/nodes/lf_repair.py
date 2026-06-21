"""LF 修复节点 —— SQL 执行失败后的轻量修复挂点。

当 SQL 执行失败(如语义一致性校验未通过)时,工作流进入此节点尝试修复 LogicForm。

修复策略(当前版本):
1. 解析错误信息中的关键词(不支持维度/未知指标/时间字段缺失)。
2. 从 LogicForm 中移除有问题的字段(避免再次触发同一错误)。
3. 记录修复动作到 execution_trace.repairs,供排障与前端展示。
4. 修复后回到 lf_validate 重新走 校验 → 编译 → 语义一致性检查 链路。

注意:当前版本不让模型绕过 LogicForm 直接写 SQL,只做槽位级别的修复。
后续可以在此处接入更智能的修复策略(如基于错误类型替换指标)。
"""

import logging
import re

from app.utils.logging_helpers import log_node_end, log_node_start, truncate_text

logger = logging.getLogger(__name__)


async def lf_repair_node(state: dict) -> dict:
    """LF 修复节点 —— 根据错误信息尝试修复 LogicForm 的槽位。

    入口状态:
        - ``sql_error``:SQL 执行或语义一致性校验产生的错误信息
        - ``logic_form``:当前未通过的 LogicForm
        - ``sql_retry_count``:重试次数,用于控制最大重试预算

    出口状态:
        - ``logic_form``:修复后的 LogicForm(或原样返回)
        - ``execution_trace``:追加 repairs 记录
        - ``sql_retry_count``:递增

    路由:此节点返回后回到 lf_validate 节点重新走校验链路。
    """
    log_node_start(
        logger,
        "lf_repair",
        state,
        keys=("trace_id", "agent_id", "sql_error", "sql_retry_count", "logic_form"),
    )

    trace = dict(state.get("execution_trace") or {})
    logic_form = dict(state.get("logic_form") or {})
    sql_error = state.get("sql_error", "")
    semantic_check = state.get("semantic_check") or {}
    errors = list(semantic_check.get("errors") or [])

    # 把 SQL 执行错误也加入错误列表,一并处理
    if sql_error and sql_error not in errors:
        errors.append(sql_error)

    # 尝试修复 LogicForm
    repaired_logic_form, actions = repair_logic_form(logic_form, errors)

    # 记录修复历史到 execution_trace,便于排障
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

    logger.info(
        "lf repair actions=%s retry_count=%s errors=%s",
        actions,
        state.get("sql_retry_count", 0),
        truncate_text("；".join(errors) if errors else "", 400),
    )

    result = {
        "logic_form": repaired_logic_form or logic_form,
        "execution_trace": trace,
        "sql_error": None,  # 清空错误,进入下一轮校验
        "sql_retry_count": state.get("sql_retry_count", 0) + 1,
    }
    log_node_end(logger, "lf_repair", result)
    return result


def repair_logic_form(logic_form: dict, errors: list[str]) -> tuple[dict, list[str]]:
    """根据错误信息从 LogicForm 中移除有问题的槽位。

    当前支持 3 类修复:
    1. "不支持维度:xxx" → 从 dimensions 中移除该维度
    2. "未知指标:xxx" → 从 metrics 中移除该指标
    3. "缺少默认时间字段" → 清空 time_range(避免反复校验失败)

    返回 (修复后的 LogicForm, 修复动作列表)。
    """
    repaired = dict(logic_form or {})
    actions: list[str] = []
    dimensions = list(repaired.get("dimensions") or [])
    metrics = list(repaired.get("metrics") or [])

    for error in errors:
        error_str = str(error)

        # 场景1:语义校验返回"不支持维度:region_name"类错误
        # 原因:LogicForm 中引用了指标不允许的维度,从 dimensions 中移除
        unsupported_dimension = re.search(r"不支持维度[:：]\s*([A-Za-z0-9_]+)", error_str)
        if unsupported_dimension:
            dimension = unsupported_dimension.group(1)
            if dimension in dimensions:
                dimensions = [item for item in dimensions if item != dimension]
                actions.append(f"移除不支持维度 {dimension}")

        # 场景2:语义校验返回"未知指标:xxx"类错误
        # 原因:LogicForm 中引用了语义层未配置的指标,从 metrics 中移除
        unknown_metric = re.search(r"未知指标[:：]\s*([A-Za-z0-9_]+)", error_str)
        if unknown_metric:
            metric = unknown_metric.group(1)
            if metric in metrics:
                metrics = [item for item in metrics if item != metric]
                actions.append(f"移除未知指标 {metric}")

        # 场景3:指标缺少时间字段,无法应用 time_range
        # 原因:用户问了时间相关问题但指标未配置 time_field,清空 time_range 避免卡死
        if "缺少默认时间字段" in error_str and repaired.get("time_range"):
            repaired["time_range"] = None
            actions.append("移除无法应用的时间范围")

    repaired["dimensions"] = dimensions
    repaired["metrics"] = metrics
    return repaired, actions
