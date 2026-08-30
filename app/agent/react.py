"""受控的 ReAct 决策器。

问数链路不应该把每个问题都强行推入同一条深度分析流水线。这个模块提供一个
轻量、确定性的 ``Reason -> Act -> Observe`` 控制器：它只负责根据当前 state
选择下一步动作，真正的数据库/模型操作仍由现有节点执行。

控制器刻意不让大模型直接返回任意节点名。动作集合、重试次数和迭代预算都在
代码侧固定，避免模型输出导致越权、无限循环或重复执行 SQL。
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.utils.logging_helpers import (
    json_for_log,
    log_node_end,
    log_node_start,
    truncate_text,
)

_LOGGER = logging.getLogger(__name__)

# 这些动作是编排层的唯一出口。即使将来把决策器替换成 LLM，也必须先通过
# ``normalize_action``，不能让模型直接跳转到任意 LangGraph 节点。
REACT_ACTIONS = frozenset(
    {
        "recognize_intent",
        "conversation",
        "semantic_enhance",
        "semantic_recall",
        "schema_recall",
        "generate_logic_form",
        "validate_logic_form",
        "compile_sql",
        "fallback_sql",
        "semantic_check",
        "execute_sql",
        "repair",
        "confirm",
        "clarify",
        "analyze_result",
        "generate_analysis_code",
        "run_analysis",
        "generate_report",
        "respond",
        "stop",
    }
)

# Public aliases keep the action vocabulary easy to use from tests, adapters and
# future tool implementations.  The graph controller and the standalone loop
# intentionally share this same whitelist.
ALLOWED_ACTIONS = REACT_ACTIONS
SEMANTIC_RECALL = "semantic_recall"
SCHEMA_RECALL = "schema_recall"
GENERATE_LOGIC_FORM = "generate_logic_form"
COMPILE_SQL = "compile_sql"
EXECUTE_SQL = "execute_sql"
ANALYZE_RESULT = "analyze_result"
RESPOND = "respond"
CLARIFY = "clarify"
REPAIR = "repair"
CONVERSATION = "conversation"

TERMINATION_MAX_ITERATIONS = "max_iterations"
TERMINATION_REPAIR_LIMIT = "repair_limit"
TERMINATION_REPEATED_ACTION = "repeated_action"

# 当前图在意图识别、SQL 前检查、SQL 执行后三个决策点进入控制器，8 次足以
# 覆盖两轮 SQL 修复，同时给未来增加一个轻量决策点留出空间。
MAX_REACT_ITERATIONS = 24
MAX_REACT_HISTORY = 16

DEEP_ANALYSIS_TERMS = (
    "分析",
    "趋势",
    "变化",
    "排名",
    "排行",
    "top",
    "分布",
    "占比",
    "结构",
    "异常",
    "波动",
    "对比",
    "同比",
    "环比",
    "报表",
    "报告",
    "图表",
    "洞察",
    "trend",
    "dashboard",
)

NON_REPAIRABLE_ERROR_TERMS = (
    "安全拦截",
    "权限拦截",
    "无权",
    "未授权",
    "禁止访问",
    "缺少数据源",
    "没有数据源",
    "未绑定可用数据源",
)


@dataclass(frozen=True)
class ReactDecision:
    """控制器的一次动作选择。"""

    action: str
    reason: str
    analysis_required: bool = False
    done: bool = False
    termination_reason: str | None = None

    @property
    def analysis_requested(self) -> bool:
        """Backward-compatible name used by standalone loop consumers."""
        return self.analysis_required


class ReactState(dict[str, Any]):
    """Dict-compatible state container for standalone ReAct adapters."""


class _StateView(dict[str, Any]):
    """Small attribute-access view used by the standalone loop result."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - mirrors normal attr access
            raise AttributeError(name) from exc


@dataclass(frozen=True)
class ReactLoopResult:
    """Result returned by ``run_react_loop``/``arun_react_loop``."""

    state: _StateView
    iterations: int
    termination_reason: str


def normalize_action(action: Any, default: str = "respond") -> str:
    """只允许白名单动作，未知值统一降级到安全动作。"""
    candidate = str(action or "").strip().lower()
    return candidate if candidate in REACT_ACTIONS else default


def _as_bool(value: Any) -> bool:
    """Parse common boolean representations without treating ``"false"`` as true."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "是", "开启"}


def requires_deep_analysis(state: dict[str, Any]) -> bool:
    """判断用户是否明确要求深度分析。

    ``need_analysis`` 由早期意图节点为所有 data_query 设置为 True，不能直接
    用来决定是否启动昂贵的 Planner/Python/Report 阶段；这里优先看用户原话，
    只有明确出现分析类表达时才进入深度链路。
    """
    explicit = state.get("force_analysis")
    if explicit is not None:
        return _as_bool(explicit)
    mode = str(state.get("analysis_mode") or "").strip().lower()
    if mode in {"deep", "full", "analysis", "report"}:
        return True
    question = " ".join(
        str(value or "")
        for value in (
            state.get("question"),
            state.get("enhanced_question"),
        )
    ).lower()
    return any(term in question for term in DEEP_ANALYSIS_TERMS)


def requested_analysis_types(state: dict[str, Any]) -> set[str]:
    """Return coarse analysis intents requested by the user."""
    text = " ".join(
        str(value or "")
        for value in (state.get("question"), state.get("enhanced_question"))
    ).lower()
    requested: set[str] = set()
    if any(term in text for term in ("趋势", "变化", "同比", "环比", "trend")):
        requested.add("trend")
    if any(term in text for term in ("排名", "排行", "top", "最多", "最少", "最高", "最低")):
        requested.add("ranking")
    if any(term in text for term in ("分布", "占比", "结构", "比例")):
        requested.add("distribution")
    if any(term in text for term in ("异常", "波动", "离群", "风险")):
        requested.add("anomaly")
    if any(term in text for term in ("图表", "可视化", "dashboard", "chart")):
        requested.add("chart")
    if any(term in text for term in ("报表", "报告", "report")):
        requested.add("report")
    return requested


def is_simple_query(state: dict[str, Any]) -> bool:
    """Return true when a completed query can be answered without deep analysis."""
    if requested_analysis_types(state):
        return False
    if _as_bool(state.get("force_analysis")) or state.get("analysis_mode") in {
        "deep",
        "full",
        "analysis",
        "report",
    }:
        return False
    return bool(state.get("sql_result")) or _as_bool(state.get("sql_result_present"))


def _standalone_iteration(state: dict[str, Any]) -> int:
    return int(state.get("iteration", state.get("react_iteration", 0)) or 0)


def _standalone_history(state: dict[str, Any]) -> list[str]:
    history = state.get("action_history")
    if isinstance(history, list):
        return [
            str(item.get("action") if isinstance(item, dict) else item)
            for item in history
        ]
    history = state.get("react_history") or []
    return [str(item.get("action")) for item in history if isinstance(item, dict)]


def choose_next_action(state: ReactState) -> ReactDecision:
    """Choose an action for the reusable observe/act loop.

    This public helper models the whole query lifecycle independently from
    LangGraph.  It is useful for unit tests, alternate runtimes and dry-runs;
    the production graph uses :func:`decide_next_action` at its integration
    points.
    """
    question = str(state.get("question") or "").strip()
    if not question:
        return ReactDecision(
            CLARIFY,
            "缺少用户问题，需要先补充查询目标。",
            done=True,
            termination_reason="clarify",
        )

    if str(state.get("intent") or "data_query").strip().lower() in {
        "chat",
        "metadata_query",
    }:
        return ReactDecision(CONVERSATION, "非数据查询问题，交由对话节点处理。", done=True)

    iteration = _standalone_iteration(state)
    max_value = state.get("max_iterations", MAX_REACT_ITERATIONS)
    max_iterations = MAX_REACT_ITERATIONS if max_value is None else max(0, int(max_value))
    if iteration >= max_iterations:
        return ReactDecision(
            RESPOND,
            "达到 ReAct 迭代上限。",
            done=True,
            termination_reason=TERMINATION_MAX_ITERATIONS,
        )

    history = _standalone_history(state)
    repeat_value = state.get("repeat_limit", 2)
    repeat_limit = 2 if repeat_value is None else max(1, int(repeat_value))
    if len(history) >= repeat_limit and history[-repeat_limit:] == [history[-1]] * repeat_limit:
        return ReactDecision(
            RESPOND,
            "检测到重复动作，停止继续尝试。",
            done=True,
            termination_reason=TERMINATION_REPEATED_ACTION,
        )

    sql_error = str(state.get("sql_error") or "").strip()
    repair_value = state.get("repair_count", state.get("sql_retry_count", 0))
    repair_count = 0 if repair_value is None else max(0, int(repair_value))
    max_repair_value = state.get("max_repairs", 2)
    max_repairs = 2 if max_repair_value is None else max(0, int(max_repair_value))
    if sql_error:
        if repair_count >= max_repairs:
            return ReactDecision(
                RESPOND,
                "修复预算已用尽。",
                done=True,
                termination_reason=TERMINATION_REPAIR_LIMIT,
            )
        if not _error_is_repairable(sql_error):
            return ReactDecision(
                RESPOND,
                "错误属于安全或权限问题，不能自动重试。",
                done=True,
                termination_reason="non_repairable_error",
            )
        return ReactDecision(REPAIR, "携带错误观察重新尝试。")

    analysis_requested = bool(requested_analysis_types(state)) or requires_deep_analysis(state)
    has_result = bool(state.get("sql_result")) or _as_bool(state.get("sql_result_present"))
    if has_result:
        if analysis_requested and not state.get("analysis_completed"):
            return ReactDecision(
                ANALYZE_RESULT,
                "用户明确要求深度分析。",
                analysis_required=True,
            )
        return ReactDecision(
            RESPOND,
            "已有结果，可以直接整理回答。",
            analysis_required=False,
            done=True,
        )

    # The standalone loop uses explicit readiness markers so callers can plug
    # in their own implementations of each action without importing graph nodes.
    if not state.get("semantic_runtime"):
        return ReactDecision(SEMANTIC_RECALL, "先召回语义资产。")
    if not state.get("relevant_tables") and not state.get("schema_ready"):
        return ReactDecision(SCHEMA_RECALL, "定位可访问的数据表和字段。")
    if not state.get("logic_form"):
        return ReactDecision(GENERATE_LOGIC_FORM, "把问题转换为结构化查询意图。")
    if not state.get("compiled_sql") and not state.get("sql_text"):
        return ReactDecision(COMPILE_SQL, "编译出确定性的只读 SQL。")
    return ReactDecision(EXECUTE_SQL, "执行已校验的 SQL。")


def _merge_loop_state(state: ReactState, update: Any) -> ReactState:
    merged = deepcopy(state)
    if isinstance(update, dict):
        merged.update(update)
    return merged


def _record_loop_observation(state: ReactState, action: str, update: Any) -> ReactState:
    """Merge an action result and maintain lifecycle markers for adapters."""
    merged = _merge_loop_state(state, update)
    if isinstance(update, dict) and "sql_result" in update:
        merged["sql_result_present"] = True
    if action == REPAIR and not (isinstance(update, dict) and "repair_count" in update):
        base_count = merged.get("repair_count", merged.get("sql_retry_count", 0))
        merged["repair_count"] = int(base_count or 0) + 1
    elif action == ANALYZE_RESULT and not (
        isinstance(update, dict) and "analysis_completed" in update
    ):
        merged["analysis_completed"] = True
    return merged


def run_react_loop(
    state: ReactState,
    act: Callable[[str, ReactState], Any],
    observe: Callable[..., Any] | None = None,
    *,
    max_iterations: int = MAX_REACT_ITERATIONS,
) -> ReactLoopResult:
    """Run a bounded synchronous observe -> act -> observe loop."""
    current = deepcopy(state)
    current["max_iterations"] = max_iterations
    current.setdefault("action_history", [])
    iterations = 0
    if observe:
        observe(deepcopy(current), None)
    while iterations < max_iterations:
        decision = choose_next_action(current)
        action = normalize_action(decision.action, default=RESPOND)
        history = list(current.get("action_history") or [])
        history.append(action)
        current["action_history"] = history
        current["iteration"] = iterations
        update = act(action, deepcopy(current))
        current = _record_loop_observation(current, action, update)
        iterations += 1
        current["iteration"] = iterations
        if observe:
            observe(deepcopy(current), action)
        if action in {RESPOND, CONVERSATION}:
            return ReactLoopResult(
                _StateView(current),
                iterations,
                decision.termination_reason or "complete",
            )
        if action == CLARIFY:
            return ReactLoopResult(
                _StateView(current),
                iterations,
                decision.termination_reason or "clarify",
            )
    return ReactLoopResult(
        _StateView(current),
        iterations,
        TERMINATION_MAX_ITERATIONS,
    )


async def arun_react_loop(
    state: ReactState,
    act: Callable[[str, ReactState], Awaitable[Any]],
    observe: Callable[..., Awaitable[Any]] | None = None,
    *,
    max_iterations: int = MAX_REACT_ITERATIONS,
) -> ReactLoopResult:
    """Async variant that exposes an explicit observation before/after actions."""
    current = deepcopy(state)
    current["max_iterations"] = max_iterations
    current.setdefault("action_history", [])
    iterations = 0
    if observe:
        await observe(deepcopy(current), None)
    while iterations < max_iterations:
        decision = choose_next_action(current)
        action = normalize_action(decision.action, default=RESPOND)
        history = list(current.get("action_history") or [])
        history.append(action)
        current["action_history"] = history
        current["iteration"] = iterations
        update = await act(action, deepcopy(current))
        current = _record_loop_observation(current, action, update)
        iterations += 1
        current["iteration"] = iterations
        if observe:
            await observe(deepcopy(current), action)
        if action in {RESPOND, CONVERSATION}:
            return ReactLoopResult(
                _StateView(current),
                iterations,
                decision.termination_reason or "complete",
            )
        if action == CLARIFY:
            return ReactLoopResult(
                _StateView(current),
                iterations,
                decision.termination_reason or "clarify",
            )
    return ReactLoopResult(_StateView(current), iterations, TERMINATION_MAX_ITERATIONS)


def observe_state(state: dict[str, Any]) -> dict[str, Any]:
    """提取可审计但不泄露结果明细的观察值。"""
    semantic_check = state.get("semantic_check") or {}
    execution_trace = state.get("execution_trace") or {}
    sql_execution = execution_trace.get("sql_execution") or {}
    error = state.get("sql_error") or state.get("semantic_error")
    return {
        "intent": str(state.get("intent") or ""),
        "semantic_valid": semantic_check.get("valid") if semantic_check else None,
        "compiled_sql_ready": bool(state.get("compiled_sql") or state.get("sql_text")),
        "sql_result_rows": len(state.get("sql_result") or []),
        "sql_executed": _as_bool(state.get("sql_executed"))
        or bool(sql_execution)
        or bool(state.get("react_last_action") == "execute_sql"),
        "sql_error": truncate_text(error, 300) if error else "",
        "retry_count": int(state.get("sql_retry_count") or 0),
        "analysis_requested": requires_deep_analysis(state),
    }


def _last_action(state: dict[str, Any]) -> str:
    return normalize_action(state.get("react_last_action"), default="")


def _error_is_repairable(error: Any) -> bool:
    text = str(error or "").strip()
    if not text:
        return True
    return not any(term in text for term in NON_REPAIRABLE_ERROR_TERMS)


def _can_repair(state: dict[str, Any]) -> bool:
    retry_value = state.get("sql_retry_count")
    retry_count = 0 if retry_value is None else max(0, int(retry_value))
    iteration_value = state.get("react_iteration")
    iteration = 0 if iteration_value is None else max(0, int(iteration_value))
    error = state.get("sql_error") or ""
    retry_limit_value = state.get("max_sql_retries", 2)
    retry_limit = 2 if retry_limit_value is None else max(0, int(retry_limit_value))
    iteration_limit_value = state.get("max_react_iterations", MAX_REACT_ITERATIONS)
    iteration_limit = (
        MAX_REACT_ITERATIONS
        if iteration_limit_value is None
        else max(0, int(iteration_limit_value))
    )
    if retry_count >= retry_limit or iteration >= max(0, iteration_limit - 1):
        return False
    return _error_is_repairable(error)


def _repair_repeat_limit(state: dict[str, Any]) -> int:
    value = state.get("react_repeat_limit", 2)
    return 2 if value is None else max(1, int(value))


def _consecutive_action_count(state: dict[str, Any], action: str) -> int:
    history = state.get("react_history") or state.get("action_history") or []
    count = 0
    for item in reversed(history):
        item_action = item.get("action") if isinstance(item, dict) else item
        if item_action != action:
            break
        count += 1
    return count


def decide_next_action(state: dict[str, Any]) -> ReactDecision:
    """Choose one safe action from the complete task lifecycle."""
    question = str(state.get("question") or "").strip()
    intent = str(state.get("intent") or "").strip().lower()
    last_action = _last_action(state)
    iteration_value = state.get("react_iteration")
    iteration = 0 if iteration_value is None else max(0, int(iteration_value))
    max_iteration_value = state.get("max_react_iterations", MAX_REACT_ITERATIONS)
    max_iterations = (
        MAX_REACT_ITERATIONS
        if max_iteration_value is None
        else max(1, int(max_iteration_value))
    )
    if iteration >= max_iterations:
        return ReactDecision(
            "respond",
            "已达到 ReAct 迭代上限，停止继续调用工具。",
            done=True,
            termination_reason=TERMINATION_MAX_ITERATIONS,
        )
    if not question:
        return ReactDecision("clarify", "缺少用户问题，需要先补充查询目标。")

    repeat_limit = _repair_repeat_limit(state)
    if last_action and _consecutive_action_count(state, last_action) >= repeat_limit:
        return ReactDecision(
            "respond",
            "检测到连续重复动作，停止继续尝试。",
            done=True,
            termination_reason=TERMINATION_REPEATED_ACTION,
        )

    if not intent:
        return ReactDecision("recognize_intent", "需要先识别当前轮次的任务意图。")
    if intent in {"chat", "metadata_query"}:
        return ReactDecision("conversation", "非数据查询问题，交由对话工具处理。")
    if intent != "data_query":
        return ReactDecision("respond", "无法确认查询意图，先返回可读提示。")

    if state.get("turn_mode") == "respond":
        return ReactDecision("respond", "用户要求基于现有任务状态直接回答。")
    if not state.get("datasource_id"):
        return ReactDecision("respond", "数据查询没有可用数据源，不能执行 SQL。")

    semantic_check = state.get("semantic_check") or {}
    compiled_sql = state.get("compiled_sql") or state.get("sql_text")
    sql_error = state.get("sql_error") or ""
    execution_trace = state.get("execution_trace") or {}
    compile_strategy = str(execution_trace.get("compile_strategy") or "")

    if sql_error:
        if (
            _can_repair(state)
            and state.get("logic_form")
            and _consecutive_action_count(state, "repair") < _repair_repeat_limit(state)
        ):
            return ReactDecision("repair", "携带最新错误观察进入受限修复。")
        return ReactDecision("respond", "发现不可继续自动处理的错误。")

    sql_executed = _as_bool(state.get("sql_executed")) or last_action == "execute_sql"
    if sql_executed:
        if requires_deep_analysis(state):
            if not state.get("plan"):
                return ReactDecision("analyze_result", "已有查询结果，先制定分析计划。", True)
            if not state.get("python_code"):
                return ReactDecision(
                    "generate_analysis_code", "根据分析计划生成受限计算脚本。", True
                )
            python_result = state.get("python_result") or {}
            if not python_result or python_result.get("status") == "generated":
                return ReactDecision("run_analysis", "执行受限脚本并观察分析结果。", True)
            if not state.get("report_payload") and not state.get("report"):
                return ReactDecision("generate_report", "将分析观察整理成最终报告。", True)
        return ReactDecision("respond", "已有查询结果，可以直接整理回答。")

    # Backward-compatible restored SQL and retry turns can resume directly.
    # SQL execution still performs its own read-only and permission checks.
    if compiled_sql and (
        compile_strategy == "nl2sql_fallback"
        or semantic_check.get("valid")
        or (not compile_strategy and not state.get("semantic_check_attempted"))
    ):
        if state.get("require_sql_confirmation"):
            return ReactDecision("confirm", "已有待执行 SQL，按配置等待确认。")
        return ReactDecision("execute_sql", "复用已生成 SQL，从执行阶段继续。")

    if not state.get("enhanced_question"):
        return ReactDecision("semantic_enhance", "补全当前问题的业务口径和上下文。")
    if not state.get("semantic_runtime"):
        return ReactDecision("semantic_recall", "加载并召回当前任务需要的语义资产。")
    if not _as_bool(state.get("schema_ready")):
        return ReactDecision("schema_recall", "定位当前问题需要的数据表和字段。")
    if state.get("enable_low_confidence_clarification") and not (
        state.get("relevant_tables") or state.get("relevant_columns")
    ):
        return ReactDecision("clarify", "数据定位置信度不足，需要用户补充条件。")
    if not state.get("logic_form"):
        if state.get("logic_form_attempted"):
            if not state.get("fallback_attempted"):
                return ReactDecision("fallback_sql", "结构化查询生成失败，进入受控 SQL 兜底。")
            return ReactDecision("respond", "结构化查询和安全兜底都未生成可执行 SQL。")
        return ReactDecision("generate_logic_form", "把问题转换为结构化查询意图。")
    if state.get("lf_validation") is None:
        return ReactDecision("validate_logic_form", "校验结构化查询的指标、维度和过滤条件。")
    if not (state.get("lf_validation") or {}).get("valid"):
        if not state.get("fallback_attempted"):
            return ReactDecision("fallback_sql", "LogicForm 校验未通过，进入受控 SQL 兜底。")
        return ReactDecision("respond", "LogicForm 校验和 SQL 兜底均未通过。")
    if not compiled_sql:
        if not state.get("compile_attempted"):
            return ReactDecision("compile_sql", "将已校验的 LogicForm 编译为只读 SQL。")
        if not state.get("fallback_attempted"):
            return ReactDecision("fallback_sql", "确定性编译失败，进入受控 SQL 兜底。")
        return ReactDecision("respond", "没有生成可执行 SQL。")

    if compile_strategy != "nl2sql_fallback" and not state.get("semantic_check_attempted"):
        return ReactDecision("semantic_check", "执行 SQL 前检查语义与权限约束。")
    if compile_strategy != "nl2sql_fallback" and semantic_check and not semantic_check.get("valid"):
        if _can_repair(state) and state.get("logic_form"):
            return ReactDecision("repair", "语义检查未通过，尝试受限 LogicForm 修复。")
        return ReactDecision("respond", "语义检查未通过且修复预算已用尽。")
    if compiled_sql:
        if state.get("require_sql_confirmation"):
            return ReactDecision("confirm", "已有待执行 SQL，按配置等待确认。")
        return ReactDecision("execute_sql", "执行已校验的只读 SQL。")
    return ReactDecision("respond", "当前状态不足以继续查询，返回可读提示。")


async def react_controller_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph 节点：记录观察并选择下一动作。"""
    log_node_start(
        _LOGGER,
        "react_controller",
        state,
        keys=(
            "trace_id",
            "agent_id",
            "intent",
            "react_iteration",
            "react_last_action",
            "sql_error",
            "sql_retry_count",
        ),
    )
    iteration_value = state.get("react_iteration")
    iteration = (0 if iteration_value is None else max(0, int(iteration_value))) + 1
    decision = decide_next_action(state)
    max_iteration_value = state.get("max_react_iterations", MAX_REACT_ITERATIONS)
    max_iterations = (
        MAX_REACT_ITERATIONS
        if max_iteration_value is None
        else max(1, int(max_iteration_value))
    )
    budget_exhausted = iteration > max_iterations
    if budget_exhausted:
        iteration = max_iterations
        decision = ReactDecision(
            "respond",
            "已达到 ReAct 迭代上限，停止继续调用工具。",
            done=True,
            termination_reason=TERMINATION_MAX_ITERATIONS,
        )
    elif decision.termination_reason is None:
        terminal_reasons = {
            "respond": "complete",
            "conversation": "complete",
            "clarify": "clarify",
            "confirm": "awaiting_confirmation",
            "generate_report": "complete",
        }
        if decision.action in terminal_reasons:
            decision = ReactDecision(
                decision.action,
                decision.reason,
                decision.analysis_required,
                done=True,
                termination_reason=terminal_reasons[decision.action],
            )

    observation = observe_state(state)
    step = {
        "iteration": iteration,
        "action": decision.action,
        "reason": decision.reason,
        "observation": observation,
    }
    history = [
        item for item in list(state.get("react_history") or []) if isinstance(item, dict)
    ]
    history.append(step)
    history = history[-MAX_REACT_HISTORY:]
    task_history = [
        item
        for item in list(state.get("task_action_history") or [])
        if isinstance(item, dict)
    ]
    task_history.append({**step, "turn_id": state.get("turn_id")})
    task_history = task_history[-128:]

    execution_trace = dict(state.get("execution_trace") or {})
    existing_react = execution_trace.get("react") or {}
    # Some legacy nodes replace ``execution_trace`` instead of merging it.
    # ``react_history`` is the canonical source so the audit trail survives
    # those nodes and is rebuilt on the next controller pass.
    prior_trace_steps = [
        item
        for item in list(existing_react.get("steps") or [])
        if isinstance(item, dict)
    ]
    react_steps = list(history)
    if prior_trace_steps:
        seen_iterations = {
            item.get("iteration") for item in react_steps if isinstance(item, dict)
        }
        react_steps = [
            *[
                item
                for item in prior_trace_steps
                if item.get("iteration") not in seen_iterations
            ],
            *react_steps,
        ]
        react_steps.sort(key=lambda item: int(item.get("iteration") or 0))
    execution_trace["react"] = {
        "iteration": iteration,
        "max_iterations": max_iterations,
        "next_action": decision.action,
        "analysis_required": decision.analysis_required,
        "budget_exhausted": budget_exhausted,
        "termination_reason": decision.termination_reason,
        "steps": react_steps[-MAX_REACT_HISTORY:],
    }
    result = {
        "react_iteration": iteration,
        "react_last_action": decision.action,
        "react_next_action": decision.action,
        "react_history": history,
        "task_action_history": task_history,
        "analysis_required": decision.analysis_required,
        "react_termination_reason": decision.termination_reason,
        "execution_trace": execution_trace,
    }
    _LOGGER.info(
        "react decision iteration=%s action=%s reason=%s observation=%s",
        iteration,
        decision.action,
        decision.reason,
        json_for_log(observation),
    )
    log_node_end(_LOGGER, "react_controller", result)
    return result


__all__ = [
    "ALLOWED_ACTIONS",
    "ANALYZE_RESULT",
    "CLARIFY",
    "COMPILE_SQL",
    "CONVERSATION",
    "EXECUTE_SQL",
    "GENERATE_LOGIC_FORM",
    "MAX_REACT_HISTORY",
    "MAX_REACT_ITERATIONS",
    "REACT_ACTIONS",
    "REPAIR",
    "RESPOND",
    "SCHEMA_RECALL",
    "SEMANTIC_RECALL",
    "TERMINATION_MAX_ITERATIONS",
    "TERMINATION_REPAIR_LIMIT",
    "TERMINATION_REPEATED_ACTION",
    "ReactLoopResult",
    "ReactState",
    "ReactDecision",
    "arun_react_loop",
    "choose_next_action",
    "decide_next_action",
    "is_simple_query",
    "normalize_action",
    "observe_state",
    "react_controller_node",
    "requires_deep_analysis",
    "requested_analysis_types",
    "run_react_loop",
]
