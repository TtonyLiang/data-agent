from __future__ import annotations

import ast
import json
import logging
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.callbacks.manager import adispatch_custom_event

from app.agent.prompts import load_prompt
from app.config import get_settings
from app.models.knowledge import LogicForm, SemanticRuntime
from app.services.llm_service import get_llm_service
from app.services.prompt_service import get_prompt_service
from app.services.python_executor import PythonExecutionError, get_python_executor
from app.services.semantic_runtime import get_semantic_runtime_service
from app.utils.logging_helpers import (
    json_for_log,
    log_node_end,
    log_node_error,
    log_node_start,
    truncate_text,
)

logger = logging.getLogger(__name__)
PYTHON_GENERATE_PROMPT = load_prompt("phase3_python_generate.system.md")
PYTHON_GENERATE_USER_PROMPT = load_prompt("phase3_python_generate.user.md")
REPORT_GENERATOR_PROMPT = load_prompt("phase3_report_generator.system.md")
REPORT_GENERATOR_USER_PROMPT = load_prompt("phase3_report_generator.user.md")


async def semantic_check_node(state: dict) -> dict:
    """SQL 执行前的语义一致性校验。"""
    log_node_start(
        logger,
        "semantic_check",
        state,
        keys=("trace_id", "agent_id", "logic_form", "compiled_sql", "sql_text"),
    )
    logic_form_data = state.get("logic_form") or {}
    runtime_data = state.get("semantic_runtime") or {}
    compiled_sql = state.get("compiled_sql") or state.get("sql_text") or ""
    if not logic_form_data or not runtime_data:
        result = _semantic_check_failed(["缺少 LogicForm 或知识库，无法执行 SQL 前校验"])
        log_node_end(logger, "semantic_check", result)
        return result
    if not compiled_sql:
        result = _semantic_check_failed(["SQL 为空，无法执行 SQL 前校验"])
        log_node_end(logger, "semantic_check", result)
        return result

    try:
        svc = get_semantic_runtime_service()
        logic_form = LogicForm(**logic_form_data)
        runtime = SemanticRuntime(**runtime_data)
        validation = svc.validate_logic_form(logic_form, runtime)
        errors = list(validation.errors)
        warnings = list(validation.warnings)

        metric_map = {metric.metric_key: metric for metric in runtime.metrics}
        mapping_map = {mapping.asset_key: mapping for mapping in runtime.mappings}
        for metric_key in logic_form.metrics:
            metric = metric_map.get(metric_key)
            if not metric:
                continue
            if logic_form.time_range and not metric.time_field:
                errors.append(f"指标 {metric_key} 缺少默认时间字段，无法应用时间口径")
            for dimension in logic_form.dimensions:
                mapping = mapping_map.get(dimension)
                if mapping and mapping.table_name not in compiled_sql:
                    warnings.append(f"维度 {dimension} 的物理表未直接出现在 SQL 中，请确认关系路径")

        check = {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "checked_items": {
                "metrics": logic_form.metrics,
                "dimensions": logic_form.dimensions,
                "filters": [item.field for item in logic_form.filters],
                "has_time_range": bool(logic_form.time_range),
            },
        }
        result: dict[str, Any] = {"semantic_check": check}
        if errors:
            result["final_answer"] = "语义一致性校验未通过: " + "；".join(errors)
            result["sql_error"] = "；".join(errors)
        logger.info(
            "semantic check result=%s sql=%s",
            json_for_log(check),
            truncate_text(compiled_sql, 1600),
        )
        log_node_end(logger, "semantic_check", result)
        return result
    except Exception as exc:
        log_node_error(logger, "semantic_check", exc, state)
        result = _semantic_check_failed([str(exc) or exc.__class__.__name__])
        log_node_end(logger, "semantic_check", result)
        return result


async def planner_node(state: dict) -> dict:
    """生成 SQL 后分析计划。"""
    log_node_start(
        logger,
        "planner",
        state,
        keys=(
            "trace_id",
            "agent_id",
            "question",
            "enhanced_question",
            "logic_form",
            "compiled_sql",
        ),
    )
    rows = state.get("sql_result") or []
    logic_form = state.get("logic_form") or {}
    profile = profile_rows(rows)
    analysis_steps = _analysis_steps(rows, logic_form)
    mode = infer_analysis_mode(state, profile)
    plan = {
        "objective": state.get("enhanced_question") or state.get("question", ""),
        "original_question": state.get("question", ""),
        "enhanced_question": state.get("enhanced_question", ""),
        "mode": mode["mode"],
        "mode_label": mode["label"],
        "row_count": len(rows),
        "column_count": len(profile["columns"]),
        "numeric_columns": profile["numeric_columns"],
        "dimension_columns": profile["dimension_columns"],
        "sql_steps": [
            {
                "name": "执行语义编译后的 SQL",
                "status": "done" if rows else "empty",
                "sql": state.get("compiled_sql") or state.get("sql_text") or "",
            }
        ],
        "analysis_steps": analysis_steps,
        "report_steps": [
            "整理 Python 分析输出与 SQL 样例",
            "由大模型流式生成 Markdown 报告",
            "提取报告摘要、图表和明细表供前端展示",
        ],
        "limitations": [
            "Python 阶段只处理 SQL 结果集，不直接访问业务库",
            "图表配置基于返回结果和 Python 分析输出生成，复杂归因仍需结合更多业务上下文复核",
        ],
    }
    result = {"plan": plan}
    logger.info(
        "planner profile=%s mode=%s plan=%s",
        json_for_log(profile),
        json_for_log(mode),
        json_for_log(plan),
    )
    log_node_end(logger, "planner", result)
    return result


async def python_generate_node(state: dict) -> dict:
    """生成只处理 SQL 结果集的 Python 分析代码。"""
    log_node_start(
        logger,
        "python_generate",
        state,
        keys=("trace_id", "agent_id", "question", "plan", "sql_result"),
    )
    rows = state.get("sql_result") or []
    profile = profile_rows(rows)
    plan = state.get("plan") or {}
    mode = plan.get("mode") or infer_analysis_mode(state, profile)["mode"]
    source = "safe_template"
    error = ""
    code = ""
    if should_use_llm_python_generate(state):
        try:
            code = await generate_python_code_with_llm(state, profile)
            validate_generated_python(code)
            source = "llm_python_generate"
            logger.info("python generate LLM code validated chars=%s", len(code))
            if get_settings().detailed_data_logging_enabled:
                logger.info("python generate LLM code preview=%s", truncate_text(code, 2400))
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            logger.warning(
                "LLM PythonGenerate failed, fallback to safe template: %s", error, exc_info=True
            )
            await emit_phase3_stream(
                "python_generate",
                f"LLM 生成脚本未通过安全校验，已切换到默认安全模板。原因：{error}\n\n",
                chunk_size=80,
            )
            code = ""
    if not code:
        code = _build_analysis_code(mode)
        logger.info("python generate using safe template mode=%s chars=%s", mode, len(code))
    if source != "llm_python_generate":
        await emit_phase3_stream("python_generate", code)
    result = {
        "python_code": code,
        "python_result": {
            "status": "generated",
            "generation_source": source,
            "generation_error": error,
            "row_count": len(rows),
            "column_count": len(profile["columns"]),
            "numeric_columns": profile["numeric_columns"],
            "dimension_columns": profile["dimension_columns"],
            "executor": "restricted_local_subprocess",
            "analysis_scope": "SQL 结果集分析，不访问业务库",
            "analysis_mode": mode,
            "generated_tasks": [
                "识别用户问题对应的指标列与维度列",
                "根据排名、趋势、分布等语义生成统计结果",
                "输出报告可消费的 insights、charts 和 tables",
            ],
        },
    }
    log_node_end(
        logger,
        "python_generate",
        {
            "python_code_chars": len(code),
            "python_result": result["python_result"],
        },
    )
    return result


async def python_analyze_node(state: dict) -> dict:
    """执行 Python 分析并输出结构化结果。"""
    log_node_start(
        logger,
        "python_analyze",
        state,
        keys=("trace_id", "agent_id", "plan", "python_code", "sql_result"),
    )
    rows = state.get("sql_result") or []
    code = state.get("python_code") or _build_analysis_code(
        infer_analysis_mode(state, profile_rows(rows))["mode"]
    )
    if not rows:
        result = {
            "python_result": {
                "status": "skipped",
                "row_count": 0,
                "summary": "SQL 执行成功，但结果为空，跳过统计分析。",
                "columns": [],
                "metrics": [],
                "dimensions": [],
            }
        }
        await emit_phase3_stream("python_analyze", json_dumps_pretty(result["python_result"]))
        log_node_end(logger, "python_analyze", result)
        return result

    profile = profile_rows(rows)
    mode = (state.get("plan") or {}).get("mode") or infer_analysis_mode(state, profile)["mode"]
    attempts: list[dict[str, Any]] = []
    settings = get_settings()
    max_repair_attempts = (
        max(0, settings.python_repair_max_attempts)
        if settings.python_repair_enabled and should_use_llm_python_generate(state)
        else 0
    )
    current_code = code
    for attempt_index in range(max_repair_attempts + 2):
        executed, error_text = execute_python_analysis_attempt(current_code, rows)
        attempt = {
            "attempt": attempt_index + 1,
            "source": python_code_source(current_code, code, mode),
            "ok": bool(executed and executed.ok),
            "error": error_text,
        }
        attempts.append(attempt)
        logger.info("python analyze attempt=%s", json_for_log(attempt))
        if executed and executed.ok:
            payload = python_success_payload(executed, state, attempts)
            await emit_phase3_stream("python_analyze", json_dumps_pretty(payload))
            logger.info(
                "python analyze success payload=%s stdout_chars=%s stderr_chars=%s",
                json_for_log(payload),
                len(executed.stdout or ""),
                len(executed.stderr or ""),
            )
            if current_code != code:
                result = {"python_code": current_code, "python_result": payload}
                log_node_end(logger, "python_analyze", result)
                return result
            result = {"python_result": payload}
            log_node_end(logger, "python_analyze", result)
            return result

        await emit_phase3_stream(
            "python_analyze",
            (
                f"\n第 {attempt_index + 1} 次 Python 分析执行失败，"
                "正在观察错误并尝试修复脚本。\n"
                f"错误摘要：{compact_error(error_text, settings.python_repair_error_chars)}\n"
            ),
            chunk_size=80,
        )
        if attempt_index < max_repair_attempts:
            repaired = await repair_python_code_with_llm(
                state, profile, current_code, error_text, attempts
            )
            if repaired:
                current_code = repaired
                continue
        template_code = _build_analysis_code(mode)
        if current_code != template_code:
            await emit_phase3_stream(
                "python_analyze", "\n已切换到安全模板脚本重新执行。\n", chunk_size=80
            )
            current_code = template_code
            continue
        break

    failed_payload = {
        "status": "failed",
        "row_count": len(rows),
        "error": compact_error(
            attempts[-1].get("error") if attempts else "Python 分析失败",
            settings.python_repair_error_chars,
        ),
        "analysis_scope": "SQL 结果集分析，不访问业务库",
        "analysis_mode": mode,
        "repair_attempts": attempts,
        "computed_items": ["Python 分析失败，已停止统计结果生成"],
    }
    await emit_phase3_stream("python_analyze", json_dumps_pretty(failed_payload))
    result = {"python_result": failed_payload}
    log_node_end(logger, "python_analyze", result)
    return result


def normalize_python_payload(value: Any) -> Any:
    """Normalize numpy/pandas scalar objects inside Python analysis payloads."""
    if isinstance(value, dict):
        return {key: normalize_python_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_python_payload(item) for item in value]
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return normalize_python_payload(value.item())
        except Exception:
            return value
    return value


def execute_python_analysis_attempt(
    code: str, rows: list[dict[str, Any]]
) -> tuple[Any | None, str]:
    """Run one Python analysis attempt and return either execution output or error text."""
    settings = get_settings()
    logger.info("python execute attempt rows=%s code_chars=%s", len(rows), len(code or ""))
    if settings.detailed_data_logging_enabled:
        logger.info("python execute code preview=%s", truncate_text(code, 2400))
    try:
        executed = get_python_executor().execute(code, rows)
        if not executed.ok:
            logger.warning(
                "python execute failed returncode output stdout=%s stderr=%s",
                truncate_text(executed.stdout, 1200),
                truncate_text(executed.stderr, 1200),
            )
            return executed, executed.stderr or executed.stdout or "Python 进程返回非 0 状态"
        logger.info(
            "python execute ok stdout_chars=%s stderr_chars=%s payload=%s",
            len(executed.stdout or ""),
            len(executed.stderr or ""),
            json_for_log(executed.payload or {}),
        )
        return executed, ""
    except (PythonExecutionError, TimeoutError, Exception) as exc:
        logger.exception("python execute raised error_type=%s", exc.__class__.__name__)
        return None, str(exc) or exc.__class__.__name__


def python_success_payload(
    executed: Any, state: dict, attempts: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build the canonical successful Python analysis payload."""
    payload = normalize_python_payload(executed.payload or {})
    payload["status"] = "success"
    payload["analysis_scope"] = "SQL 结果集分析，不访问业务库"
    payload.setdefault("analysis_mode", (state.get("plan") or {}).get("mode") or "profile")
    payload["computed_items"] = computed_items(payload)
    if executed.stderr:
        payload["stderr"] = executed.stderr[-1000:]
    payload["repair_attempts"] = attempts
    payload["repair_count"] = max(0, len(attempts) - 1)
    if len(attempts) > 1:
        payload["computed_items"].append(f"脚本修复重试 {len(attempts) - 1} 次后成功")
    return payload


def python_code_source(code: str, original_code: str, mode: str) -> str:
    """Classify whether a Python script is initial, repaired, or safe-template code."""
    if code == original_code:
        return "initial"
    if code == _build_analysis_code(mode):
        return "safe_template"
    return "llm_repair"


async def repair_python_code_with_llm(
    state: dict,
    profile: dict[str, Any],
    previous_code: str,
    error_text: str,
    attempts: list[dict[str, Any]],
) -> str:
    """Ask the model to repair failed Python analysis code using the observed error."""
    try:
        settings = get_settings()
        logger.info(
            "python repair start attempts=%s error=%s previous_code_chars=%s",
            json_for_log(attempts),
            truncate_text(error_text, min(settings.python_repair_error_chars, 1600)),
            len(previous_code or ""),
        )
        if settings.detailed_data_logging_enabled:
            logger.info("python repair previous_code=%s", truncate_text(previous_code, 2400))
        llm = get_llm_service()
        llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
        domain = (state.get("semantic_runtime") or {}).get("domain") or {}
        variables = phase3_prompt_variables(state, profile)
        variables.update(
            {
                "previous_code": previous_code,
                "python_error": compact_error(error_text, limit=settings.python_repair_error_chars),
                "repair_attempts": json_dumps_pretty(attempts),
            }
        )
        system_prompt = await get_prompt_service().resolve(
            "phase3_python_generate.system",
            PYTHON_GENERATE_PROMPT,
            agent_id=state.get("agent_id"),
            semantic_domain_id=domain.get("id") if isinstance(domain, dict) else None,
            variables=variables,
        )
        user_prompt = (
            "上一次 Python 分析脚本执行失败。请采用 ReAct 思路：先根据错误观察问题，"
            "再重新输出一份完整、可执行、安全的 Python 代码。"
            "不要解释，不要 Markdown，只输出代码。\n\n"
            f"错误信息：\n{variables['python_error']}\n\n"
            f"上一次代码：\n{previous_code}"
        )
        chunks: list[str] = []
        async for chunk in llm.achat_stream(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **llm_kwargs,
        ):
            reasoning = ""
            if hasattr(chunk, "additional_kwargs"):
                reasoning = chunk.additional_kwargs.get("reasoning_content", "")
            if reasoning:
                await emit_phase3_reasoning("python_analyze", reasoning)
            content = str(getattr(chunk, "content", "") or "")
            if content:
                chunks.append(content)
        repaired = strip_code_fence("".join(chunks)).strip()
        logger.info("python repair LLM code chars=%s", len(repaired))
        if settings.detailed_data_logging_enabled:
            logger.info("python repair LLM code preview=%s", truncate_text(repaired, 2400))
        validate_generated_python(repaired)
        await emit_phase3_stream(
            "python_analyze",
            "\n已基于错误重新生成 Python 分析脚本，准备再次执行。\n",
            chunk_size=80,
        )
        return repaired
    except Exception as exc:
        logger.warning("LLM Python repair failed, fallback to safe template: %s", exc)
        await emit_phase3_stream(
            "python_analyze",
            (
                "\n脚本修复生成失败，准备使用安全模板兜底。"
                f"原因：{str(exc) or exc.__class__.__name__}\n"
            ),
            chunk_size=80,
        )
        return ""


def compact_error(value: Any, limit: int = 1200) -> str:
    """Trim noisy traceback text into a concise error summary."""
    text = str(value or "").strip()
    if not text:
        return "未知错误"
    text = re.sub(r"\n\s*\^+\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[-limit:]


async def report_generator_node(state: dict) -> dict:
    """生成前端可展示的结构化报告。"""
    log_node_start(
        logger,
        "report_generator",
        state,
        keys=("trace_id", "agent_id", "question", "plan", "python_result"),
    )
    rows = state.get("sql_result") or []
    logic_form = state.get("logic_form") or {}
    plan = state.get("plan") or {}
    python_result = state.get("python_result") or {}
    report = _build_report_payload(state, rows, logic_form, plan, python_result)
    markdown = ""
    source = "fallback_template"
    error = ""
    if should_use_llm_report(state):
        try:
            markdown = await generate_report_markdown_with_llm(
                state, rows, logic_form, plan, python_result
            )
            if len(re.sub(r"\s+", "", markdown)) < min_report_length(rows):
                raise ValueError("报告正文过短，未达到分析报告信息密度要求")
            source = "llm_report_generator"
            logger.info("report generator LLM markdown chars=%s", len(markdown))
            if get_settings().detailed_data_logging_enabled:
                logger.info(
                    "report generator LLM markdown preview=%s", truncate_text(markdown, 3000)
                )
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            logger.warning(
                "LLM report generation failed, fallback to structured report: %s",
                error,
                exc_info=True,
            )
            markdown = ""
    if not markdown:
        markdown = report_to_stream_text(report)
        if rows and len(re.sub(r"\s+", "", markdown)) < 300:
            markdown = enrich_fallback_report(markdown, report)
    markdown = align_markdown_chart_kinds(markdown, report.get("charts") or [])
    report["markdown"] = markdown
    report["body"] = markdown
    report["generation_source"] = source
    report["generation_error"] = error
    report["summary"] = extract_report_summary(markdown) or report.get("summary", "")
    report["sections"] = markdown_to_sections(markdown) or report.get("sections", [])
    if source != "llm_report_generator":
        await emit_phase3_stream("report_generator", markdown, chunk_size=80)
    result = {
        "report": markdown,
        "report_payload": report,
        "final_answer": _final_answer_from_report(report, state.get("final_answer", "")),
    }
    log_node_end(
        logger,
        "report_generator",
        {
            "generation_source": source,
            "generation_error": error,
            "markdown_chars": len(markdown),
            "summary": report.get("summary"),
            "chart_count": len(report.get("charts") or []),
            "table_count": len(report.get("tables") or []),
            "final_answer": result["final_answer"],
        },
    )
    return result


def profile_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Identify result columns, numeric columns, and dimension-like columns."""
    columns = list(rows[0].keys()) if rows else []
    numeric_columns = [
        column for column in columns if any(_is_number_like(row.get(column)) for row in rows)
    ]
    return {
        "columns": columns,
        "numeric_columns": numeric_columns,
        "dimension_columns": [column for column in columns if column not in numeric_columns],
    }


def computed_items(python_result: dict[str, Any]) -> list[str]:
    """Summarize which analysis artifacts were produced."""
    metrics = python_result.get("metrics") or []
    dimensions = python_result.get("dimensions") or []
    items = [
        f"数值字段统计 {len(metrics)} 个",
        f"维度字段识别 {len(dimensions)} 个",
    ]
    repair_count = int(python_result.get("repair_count") or 0)
    if repair_count:
        items.append(f"脚本修复重试 {repair_count} 次")
    if python_result.get("null_counts"):
        items.append("空值计数")
    if python_result.get("dimension_samples"):
        items.append("维度样例")
    if python_result.get("charts"):
        items.append(f"图表建议 {len(python_result.get('charts') or [])} 个")
    if python_result.get("insights"):
        items.append(f"关键洞察 {len(python_result.get('insights') or [])} 条")
    return items


async def emit_phase3_stream(node: str, text: str, chunk_size: int = 120) -> None:
    """Emit real node content before node_complete so the UI can render it live."""
    if not text:
        return
    for start in range(0, len(text), chunk_size):
        try:
            await adispatch_custom_event(
                "wenqu_token",
                {
                    "node": node,
                    "delta": text[start : start + chunk_size],
                    "kind": "token",
                },
            )
        except RuntimeError:
            return


async def emit_phase3_reasoning(node: str, text: str, chunk_size: int = 120) -> None:
    """Stream Phase3 reasoning deltas to the graph event channel."""
    if not text:
        return
    for start in range(0, len(text), chunk_size):
        try:
            await adispatch_custom_event(
                "wenqu_token",
                {
                    "node": node,
                    "delta": text[start : start + chunk_size],
                    "kind": "reasoning",
                },
            )
        except RuntimeError:
            return


def infer_analysis_mode(state: dict, profile: dict[str, Any]) -> dict[str, str]:
    """Choose the analysis mode from question intent and result shape."""
    time_dimensions, category_dimensions = _split_time_like_dimensions(
        profile.get("dimension_columns") or []
    )
    has_time_dimension = bool(time_dimensions)
    text = " ".join(
        str(value or "")
        for value in (
            state.get("question"),
            state.get("enhanced_question"),
            json_dumps_compact(state.get("logic_form") or {}),
        )
    ).lower()
    if any(
        token in text
        for token in ("趋势", "变化", "环比", "同比", "按月", "按日", "month", "day", "trend")
    ):
        if not has_time_dimension:
            if profile.get("numeric_columns") and profile.get("dimension_columns"):
                row_count = len(state.get("sql_result") or [])
                if 2 <= row_count <= 8:
                    return {"mode": "distribution", "label": "结构分布分析"}
                return {"mode": "ranking", "label": "分组对比分析"}
            return {"mode": "profile", "label": "结果画像分析"}
        if category_dimensions:
            return {"mode": "multi_series_trend", "label": "多序列趋势分析"}
        return {"mode": "trend", "label": "趋势分析"}
    if any(
        token in text for token in ("排名", "排行", "top", "前", "最多", "最少", "最高", "最低")
    ):
        return {"mode": "ranking", "label": "排名分析"}
    if any(token in text for token in ("占比", "结构", "分布", "比例", "构成")):
        return {"mode": "distribution", "label": "结构分布分析"}
    if any(token in text for token in ("异常", "波动", "离群", "风险")):
        return {"mode": "anomaly", "label": "异常识别分析"}
    if profile.get("numeric_columns") and profile.get("dimension_columns"):
        return {"mode": "ranking", "label": "分组对比分析"}
    return {"mode": "profile", "label": "结果画像分析"}


def _has_time_like_dimension(columns: list[str]) -> bool:
    """Return true when any dimension column looks temporal."""
    return bool(_split_time_like_dimensions(columns)[0])


def _split_time_like_dimensions(columns: list[str]) -> tuple[list[str], list[str]]:
    """Separate temporal dimensions from categorical dimensions."""
    if not columns:
        return [], []
    time_tokens = (
        "date",
        "time",
        "day",
        "week",
        "month",
        "year",
        "quarter",
        "snapshot",
        "日期",
        "时间",
        "月份",
        "年月",
        "季度",
        "周",
        "日",
    )
    time_columns: list[str] = []
    category_columns: list[str] = []
    for column in columns:
        lower = str(column or "").lower()
        if any(token in lower for token in time_tokens):
            time_columns.append(column)
        else:
            category_columns.append(column)
    return time_columns, category_columns


def should_use_llm_python_generate(state: dict) -> bool:
    """Decide whether there is enough context to ask the model for Python code."""
    return bool(state.get("agent_id") and state.get("sql_result"))


def should_use_llm_report(state: dict) -> bool:
    """Decide whether to ask the model for the final Markdown report."""
    return bool(state.get("agent_id"))


async def generate_python_code_with_llm(state: dict, profile: dict[str, Any]) -> str:
    """Generate a bounded Python analysis script from SQL result context."""
    llm = get_llm_service()
    llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
    domain = (state.get("semantic_runtime") or {}).get("domain") or {}
    system_prompt = await get_prompt_service().resolve(
        "phase3_python_generate.system",
        PYTHON_GENERATE_PROMPT,
        agent_id=state.get("agent_id"),
        semantic_domain_id=domain.get("id") if isinstance(domain, dict) else None,
        variables=phase3_prompt_variables(state, profile),
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": PYTHON_GENERATE_USER_PROMPT},
    ]
    logger.info(
        "python generate LLM call profile=%s variables=%s",
        json_for_log(profile),
        json_for_log(phase3_prompt_variables(state, profile), text_limit=1800),
    )
    chunks: list[str] = []
    async for chunk in llm.achat_stream(messages, **llm_kwargs):
        reasoning = ""
        if hasattr(chunk, "additional_kwargs"):
            reasoning = chunk.additional_kwargs.get("reasoning_content", "")
        if reasoning:
            await emit_phase3_reasoning("python_generate", reasoning)
        content = str(getattr(chunk, "content", "") or "")
        if not content:
            continue
        chunks.append(content)
        await emit_phase3_stream("python_generate", content, chunk_size=80)
    code = strip_code_fence("".join(chunks)).strip()
    logger.info("python generate LLM raw code chars=%s", len(code))
    if get_settings().detailed_data_logging_enabled:
        logger.info("python generate LLM raw code preview=%s", truncate_text(code, 2400))
    return code


async def generate_report_markdown_with_llm(
    state: dict,
    rows: list[dict[str, Any]],
    logic_form: dict[str, Any],
    plan: dict[str, Any],
    python_result: dict[str, Any],
) -> str:
    """Generate the final Markdown report from SQL and Python analysis outputs."""
    llm = get_llm_service()
    llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
    domain = (state.get("semantic_runtime") or {}).get("domain") or {}
    profile = profile_rows(rows)
    variables = phase3_prompt_variables(
        {
            **state,
            "logic_form": logic_form,
            "plan": plan,
            "python_result": python_result,
        },
        profile,
    )
    system_prompt = await get_prompt_service().resolve(
        "phase3_report_generator.system",
        REPORT_GENERATOR_PROMPT,
        agent_id=state.get("agent_id"),
        semantic_domain_id=domain.get("id") if isinstance(domain, dict) else None,
        variables=variables,
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": REPORT_GENERATOR_USER_PROMPT},
    ]
    logger.info(
        "report generator LLM call profile=%s variables=%s",
        json_for_log(profile),
        json_for_log(variables, text_limit=2400),
    )
    chunks: list[str] = []
    async for chunk in llm.achat_stream(messages, **llm_kwargs):
        reasoning = ""
        if hasattr(chunk, "additional_kwargs"):
            reasoning = chunk.additional_kwargs.get("reasoning_content", "")
        if reasoning:
            await emit_phase3_reasoning("report_generator", reasoning)
        content = str(getattr(chunk, "content", "") or "")
        if not content:
            continue
        chunks.append(content)
        await emit_phase3_stream("report_generator", content, chunk_size=80)
    markdown = "".join(chunks).strip()
    logger.info("report generator LLM raw markdown chars=%s", len(markdown))
    if get_settings().detailed_data_logging_enabled:
        logger.info("report generator LLM raw markdown preview=%s", truncate_text(markdown, 3000))
    return markdown


def phase3_prompt_variables(state: dict, profile: dict[str, Any]) -> dict[str, str]:
    """Assemble prompt variables shared by Phase3 Python and report prompts."""
    rows = state.get("sql_result") or []
    return {
        "question": str(state.get("question") or ""),
        "enhanced_question": str(state.get("enhanced_question") or ""),
        "plan": json_dumps_pretty(state.get("plan") or {}),
        "logic_form": json_dumps_pretty(state.get("logic_form") or {}),
        "sql": str(state.get("compiled_sql") or state.get("sql_text") or ""),
        "profile": json_dumps_pretty(profile),
        "sample_rows": json_dumps_pretty(rows[:30]),
        "python_result": json_dumps_pretty(state.get("python_result") or {}),
    }


def validate_generated_python(code: str) -> None:
    """Reject generated Python that violates the restricted execution contract."""
    logger.info("validate generated python chars=%s", len(code or ""))
    if not code:
        raise PythonExecutionError("LLM 未生成 Python 代码")
    if "rows" not in code:
        raise PythonExecutionError("Python 分析代码必须使用 rows 输入变量")
    if "print(" not in code or "json.dumps" not in code:
        raise PythonExecutionError("Python 分析代码必须通过 print(json.dumps(...)) 输出 JSON")
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {
                "open",
                "exec",
                "eval",
                "compile",
                "__import__",
            }:
                raise PythonExecutionError(f"Python 分析代码禁止调用 {node.func.id}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                _assert_prompt_allowed_module(alias.name)
        if isinstance(node, ast.ImportFrom):
            _assert_prompt_allowed_module(node.module or "")


def _assert_prompt_allowed_module(module: str) -> None:
    """Allow only safe analysis libraries in generated Python imports."""
    allowed = {
        "json",
        "math",
        "statistics",
        "collections",
        "datetime",
        "decimal",
        "itertools",
        "numpy",
        "pandas",
    }
    root = module.split(".", 1)[0]
    if root not in allowed:
        raise PythonExecutionError(f"Python 分析代码禁止导入模块: {module}")


def strip_code_fence(text: str) -> str:
    """Extract code from a Markdown fenced block when the model includes one."""
    stripped = text.strip()
    if "```" not in stripped:
        return stripped
    match = re.search(r"```(?:python|py)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return stripped.replace("```python", "").replace("```py", "").replace("```", "").strip()


def json_dumps_pretty(value: Any) -> str:
    """Serialize JSON with readable indentation and Chinese text preserved."""
    return json.dumps(value, ensure_ascii=False, indent=2)


def json_dumps_compact(value: Any) -> str:
    """Serialize JSON compactly for prompt classification text."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def min_report_length(rows: list[dict[str, Any]]) -> int:
    """Return the minimum useful Markdown length for empty versus non-empty results."""
    return 120 if not rows else 300


def extract_report_summary(markdown: str) -> str:
    """Pick the first non-heading report line as a short summary."""
    lines = [
        line.strip(" -")
        for line in markdown.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and not line.strip().startswith("```")
    ]
    if not lines:
        return ""
    summary = lines[0]
    return summary[:220] + "..." if len(summary) > 220 else summary


def markdown_to_sections(markdown: str) -> list[dict[str, Any]]:
    """Convert Markdown headings and bullet text into frontend report sections."""
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_code = False
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.startswith("## "):
            current = {"title": line[3:].strip(), "items": []}
            sections.append(current)
            continue
        if line.startswith("# "):
            continue
        text = line.strip()
        if not text:
            continue
        if current is None:
            current = {"title": "执行摘要", "items": []}
            sections.append(current)
        current["items"].append(text.lstrip("- ").strip())
    return [section for section in sections if section.get("items")]


def enrich_fallback_report(markdown: str, report: dict[str, Any]) -> str:
    """Add explanatory paragraphs when the template report is too thin."""
    rows = int(report.get("row_count") or 0)
    sql = str(report.get("sql") or "")
    python_result = report.get("python_result") or {}
    insights = python_result.get("insights") if isinstance(python_result, dict) else []
    charts = report.get("charts") or []
    additions = [
        "",
        "## 补充解读",
        (
            f"本报告基于 SQL 查询返回的 {rows} 行结果生成。"
            "Python 阶段没有直接访问业务数据库，只对已经返回的结果集"
            "做二次统计、排序和图表结构整理，因此报告中的数字应与结果表保持一致。"
        ),
    ]
    if insights:
        additions.append(
            "从分析脚本输出看，最值得关注的是："
            + "；".join(str(item) for item in insights[:4])
            + "。"
        )
    if charts:
        chart_titles = "、".join(
            str(item.get("title") or "图表") for item in charts if isinstance(item, dict)
        )
        additions.append(
            f"可视化建议优先查看 {chart_titles}，用于判断头部集中、趋势变化或结构分布是否明显。"
        )
    if sql:
        additions.append(
            "如需复核口径，建议先查看 SQL 的筛选条件、分组字段和排序字段，"
            "再对照语义层指标定义确认是否与业务问题一致。"
        )
    additions.append(
        "后续如果要继续追问，可以围绕排名靠前/靠后的对象、时间变化、区域差异或异常点进行下钻，以便从“查到结果”进一步走向“解释原因”。"
    )
    return markdown.rstrip() + "\n" + "\n".join(additions)


def _is_number_like(value: Any) -> bool:
    """Return true for numeric values and numeric strings, excluding booleans."""
    if isinstance(value, bool) or value is None:
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


def _semantic_check_failed(errors: list[str]) -> dict:
    """Build a failed semantic-check graph state update."""
    return {
        "semantic_check": {
            "valid": False,
            "errors": errors,
            "warnings": [],
            "checked_items": {},
        },
        "sql_error": "；".join(errors),
        "final_answer": "语义一致性校验未通过: " + "；".join(errors),
    }


def _analysis_steps(rows: list[dict[str, Any]], logic_form: dict[str, Any]) -> list[dict[str, Any]]:
    """Describe expected analysis steps for the planner output."""
    if not rows:
        return [
            {"name": "空结果检查", "status": "pending", "description": "结果为空时给出业务提示"}
        ]
    return [
        {
            "name": "基础统计",
            "status": "pending",
            "description": "识别数值列、维度列、行数和空值情况",
        },
        {
            "name": "指标解释",
            "status": "pending",
            "description": (
                f"围绕 {', '.join(logic_form.get('metrics') or []) or '查询结果'} "
                "生成业务解释"
            ),
        },
        {
            "name": "趋势拆解",
            "status": "pending",
            "description": "如果结果同时包含时间维度和分类维度，则按多序列趋势拆解波动和分化情况",
        },
        {
            "name": "异常与重点",
            "status": "pending",
            "description": "提取最大值、最小值和可疑空值字段",
        },
    ]


def _build_analysis_code(mode: str = "profile") -> str:
    """Load the safe Python template for an analysis mode."""
    template_name = (
        "multi_series_trend.py.tpl" if mode == "multi_series_trend" else "generic_analysis.py.tpl"
    )
    code = load_python_template(template_name)
    return code.replace("__ANALYSIS_MODE__", mode)


def load_python_template(name: str) -> str:
    """Read a packaged Python analysis template from disk."""
    template_path = Path(__file__).resolve().parents[1] / "python_templates" / name
    code = template_path.read_text(encoding="utf-8").strip()
    logger.info("python template loaded name=%s path=%s chars=%s", name, template_path, len(code))
    return code


def _build_report_payload(
    state: dict,
    rows: list[dict[str, Any]],
    logic_form: dict[str, Any],
    plan: dict[str, Any],
    python_result: dict[str, Any],
) -> dict[str, Any]:
    """Build the structured report object consumed by the frontend."""
    metric_keys = logic_form.get("metrics") or []
    dimension_keys = logic_form.get("dimensions") or []
    profile = profile_rows(rows)
    mode = plan.get("mode") or python_result.get("analysis_mode") or "profile"
    title = _report_title(metric_keys, dimension_keys, mode)
    summary = _report_summary(rows, metric_keys, dimension_keys, python_result, mode)
    executive_summary = _report_executive_summary(
        rows, metric_keys, dimension_keys, python_result, mode
    )
    background = _report_background(state, metric_keys, dimension_keys)
    analysis_process = _report_process(rows, logic_form, plan, python_result)
    interpretation = _report_interpretation(
        rows, profile, metric_keys, dimension_keys, python_result, mode
    )
    suggestions = _report_suggestions(rows, metric_keys, dimension_keys, python_result, mode)
    charts = _report_charts(rows, profile, metric_keys, dimension_keys, python_result)
    tables = _report_tables(rows, profile, python_result)
    highlights = _report_highlights(rows, python_result, mode)
    sections = [
        {
            "title": executive_summary["title"],
            "items": executive_summary["bullets"],
        },
        {
            "title": background["title"],
            "items": background["paragraphs"],
        },
        {
            "title": analysis_process["title"],
            "items": [step["text"] for step in analysis_process["steps"]],
        },
        {
            "title": interpretation["title"],
            "items": interpretation["bullets"],
        },
        {
            "title": suggestions["title"],
            "items": suggestions["items"],
        },
    ]
    if python_result.get("status") == "failed":
        sections.append(
            {
                "title": "分析执行提示",
                "items": [f"Python 分析未完成: {python_result.get('error', '未知错误')}"],
            }
        )

    return {
        "title": title,
        "summary": summary,
        "status": "analysis_failed"
        if python_result.get("status") == "failed"
        else ("empty" if not rows else "success"),
        "mode": mode,
        "mode_label": plan.get("mode_label") or "结果画像分析",
        "row_count": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "question": state.get("question", ""),
        "enhanced_question": state.get("enhanced_question", ""),
        "metrics": metric_keys,
        "dimensions": dimension_keys,
        "data_profile": profile,
        "executive_summary": executive_summary,
        "background": background,
        "analysis_process": analysis_process,
        "interpretation": interpretation,
        "suggestions": suggestions,
        "charts": charts,
        "tables": tables,
        "highlights": highlights,
        "sections": sections,
        "plan": plan,
        "python_result": python_result,
        "sql": state.get("compiled_sql") or state.get("sql_text") or "",
        "limitations": plan.get("limitations", []),
    }


def _report_title(metric_keys: list[str], dimension_keys: list[str], mode: str = "profile") -> str:
    """Choose a readable report title from metrics, dimensions, and mode."""
    if mode == "multi_series_trend":
        if metric_keys and dimension_keys:
            return f"{', '.join(metric_keys)} 按 {', '.join(dimension_keys)} 月度趋势分析"
        if metric_keys:
            return f"{', '.join(metric_keys)} 月度趋势分析"
    if metric_keys and dimension_keys:
        return f"{', '.join(metric_keys)} 按 {', '.join(dimension_keys)} 分析"
    if metric_keys:
        return f"{', '.join(metric_keys)} 分析"
    return "查询结果分析"


def _report_summary(
    rows: list[dict[str, Any]],
    metric_keys: list[str],
    dimension_keys: list[str],
    python_result: dict[str, Any],
    mode: str = "profile",
) -> str:
    """Generate a short report summary from rows and analysis payload."""
    if not rows:
        return "查询执行完成，但当前条件下没有返回匹配数据。"
    if python_result.get("status") == "failed":
        return (
            f"SQL 查询返回 {len(rows)} 行数据，但 Python 深度分析在重试后仍未成功："
            f"{python_result.get('error', '未知错误')}。"
        )
    if mode == "multi_series_trend":
        insights = [
            str(item) for item in (python_result.get("insights") or []) if str(item or "").strip()
        ]
        metric_text = f"围绕 {', '.join(metric_keys)}" if metric_keys else "围绕本次查询结果"
        dimension_text = f"，按 {', '.join(dimension_keys)} 拆分" if dimension_keys else ""
        lead = insights[0] if insights else "已完成多序列趋势分析。"
        return f"{metric_text}{dimension_text} 共返回 {len(rows)} 行趋势明细，{lead}"
    metric_text = f"围绕 {', '.join(metric_keys)}" if metric_keys else "围绕本次查询结果"
    dimension_text = f"，按 {', '.join(dimension_keys)} 展开" if dimension_keys else ""
    metric_count = len(python_result.get("metrics") or [])
    top_sentence = _top_row_sentence(rows, python_result)
    suffix = f"已完成 {metric_count} 个数值字段的基础统计。"
    return f"{metric_text}{dimension_text} 共返回 {len(rows)} 行数据，{top_sentence}{suffix}"


def _report_highlights(
    rows: list[dict[str, Any]], python_result: dict[str, Any], mode: str = "profile"
) -> list[dict[str, Any]]:
    """Build top-level KPI highlight cards for the report."""
    highlights: list[dict[str, Any]] = [
        {"label": "结果行数", "value": len(rows), "field": "row_count"}
    ]
    if mode == "multi_series_trend":
        series_summary = python_result.get("series_summary") or []
        if isinstance(series_summary, list):
            highlights.append(
                {"label": "趋势序列数", "value": len(series_summary), "field": "series_count"}
            )
        return highlights
    for metric in (python_result.get("metrics") or [])[:3]:
        if not isinstance(metric, dict):
            continue
        field = metric.get("field", "")
        highlights.append(
            {
                "label": f"{field} 平均值",
                "value": metric.get("avg"),
                "field": field,
            }
        )
    return highlights


def _report_executive_summary(
    rows: list[dict[str, Any]],
    metric_keys: list[str],
    dimension_keys: list[str],
    python_result: dict[str, Any],
    mode: str = "profile",
) -> dict[str, Any]:
    """Build executive summary bullets from result and Python analysis."""
    bullets = []
    if rows:
        bullets.append(f"本次查询共返回 {len(rows)} 行数据，已完成基础画像分析。")
    else:
        bullets.append("本次查询未返回结果，当前报告主要说明查询口径和空结果原因。")
    if metric_keys:
        bullets.append(f"核心指标为 {', '.join(metric_keys)}。")
    if dimension_keys:
        bullets.append(f"结果按 {', '.join(dimension_keys)} 展开。")
    if mode == "multi_series_trend":
        insights = [
            str(item) for item in (python_result.get("insights") or []) if str(item or "").strip()
        ]
        bullets.extend(insights[:3])
        return {
            "title": "执行摘要",
            "bullets": bullets[:6],
            "key_points": [
                {"label": "结果行数", "value": len(rows)},
                {"label": "指标数量", "value": len(metric_keys)},
                {"label": "维度数量", "value": len(dimension_keys)},
                {"label": "趋势序列", "value": len(python_result.get("series_summary") or [])},
            ],
        }
    metrics = python_result.get("metrics") or []
    if metrics:
        top_metric = metrics[0]
        if isinstance(top_metric, dict) and top_metric.get("max") is not None:
            bullets.append(
                f"数值字段 {top_metric.get('field')} 的最大值为 {top_metric.get('max')}。"
            )
            bullets.append(
                f"{top_metric.get('field')} 合计为 {_format_number(top_metric.get('sum'))}，"
                f"平均值为 {_format_number(top_metric.get('avg'))}。"
            )
    top = _top_row_sentence(rows, python_result)
    if top:
        bullets.append(top)
    return {
        "title": "执行摘要",
        "bullets": bullets,
        "key_points": [
            {"label": "结果行数", "value": len(rows)},
            {"label": "指标数量", "value": len(metric_keys)},
            {"label": "维度数量", "value": len(dimension_keys)},
            {"label": "数值字段", "value": len(metrics)},
        ],
    }


def _report_background(
    state: dict, metric_keys: list[str], dimension_keys: list[str]
) -> dict[str, Any]:
    """Explain the question, rewrite, and semantic query context."""
    enhanced_question = str(state.get("enhanced_question") or "").strip()
    original_question = str(state.get("question") or "").strip()
    question_line = f"用户原始问题：{original_question or '未提供'}。"
    if enhanced_question and enhanced_question != original_question:
        question_line += f" 语义增强后问题：{enhanced_question}。"
    return {
        "title": "分析背景与用户诉求",
        "paragraphs": [
            question_line,
            (
                "当前分析基于已编译 SQL 结果，围绕 "
                f"{', '.join(metric_keys) if metric_keys else '查询结果'} 展开。"
            ),
            f"关注维度为 {', '.join(dimension_keys) if dimension_keys else '无'}。",
            "SQL 结果用于后续 Python 统计和报告生成，不直接在 Python 阶段访问业务库。",
        ],
    }


def _report_process(
    rows: list[dict[str, Any]],
    logic_form: dict[str, Any],
    plan: dict[str, Any],
    python_result: dict[str, Any],
) -> dict[str, Any]:
    """Describe how SQL and Python analysis produced the answer."""
    steps = [
        {
            "title": "步骤1：SQL 查询",
            "text": "已执行语义编译后的 SQL，并取得查询结果集。",
            "result": plan.get("sql_steps", [{}])[0].get("sql", ""),
        },
        {
            "title": "步骤2：基础画像",
            "text": "识别数值列、维度列，并对结果集做基础统计。",
            "result": (
                f"数值字段 {len(python_result.get('metrics') or [])} 个，"
                f"维度字段 {len(python_result.get('dimensions') or [])} 个。"
            ),
        },
        {
            "title": "步骤3：结果整理",
            "text": "汇总关键结论、建议和可视化数据，形成可阅读报告。",
            "result": "报告已生成，可继续展开查看明细。",
        },
    ]
    if not rows:
        steps[1]["text"] = "当前没有结果集，因此跳过基础统计。"
    if python_result.get("status") == "failed":
        attempts = python_result.get("repair_attempts") or []
        steps[1]["text"] = (
            "Python 分析脚本执行失败，系统已按 ReAct 思路观察错误并尝试重新生成脚本。"
        )
        steps[1]["result"] = (
            f"已尝试 {len(attempts)} 次，最终失败原因：{python_result.get('error', '未知错误')}"
        )
        steps[2]["text"] = "由于 Python 深度分析未成功，报告仅保留 SQL 结果、错误说明和可复核建议。"
        steps[2]["result"] = "建议查看 Python 分析节点的错误摘要与脚本修复记录。"
    return {
        "title": "数据分析过程",
        "steps": steps,
        "logic_form": logic_form,
    }


def _report_interpretation(
    rows: list[dict[str, Any]],
    profile: dict[str, Any],
    metric_keys: list[str],
    dimension_keys: list[str],
    python_result: dict[str, Any],
    mode: str = "profile",
) -> dict[str, Any]:
    """Generate interpretation bullets for metrics, dimensions, and insights."""
    bullets: list[str] = []
    if not rows:
        bullets.append("当前条件下没有返回结果，建议检查时间范围、筛选条件或数据源选择。")
        return {"title": "结果解读", "bullets": bullets}
    if mode == "multi_series_trend":
        insights = [
            str(item) for item in (python_result.get("insights") or []) if str(item or "").strip()
        ]
        if insights:
            return {"title": "结果解读", "bullets": insights[:6]}

    metric = (python_result.get("metrics") or [{}])[0] if python_result.get("metrics") else {}
    dimension_item = (
        python_result.get("dimensions") or profile.get("dimension_columns") or [None]
    )[0]
    dimension_column = _result_field_name(dimension_item)
    metric_field = _result_field_name(metric)
    if isinstance(metric, dict) and metric.get("field") and metric.get("max") is not None:
        bullets.append(
            f"{metric.get('field')} 的最大值为 {_format_number(metric.get('max'))}，"
            f"最小值为 {_format_number(metric.get('min'))}，"
            f"平均值为 {_format_number(metric.get('avg'))}。"
        )
    if dimension_column and rows:
        top_row = rows[0]
        top_value = top_row.get(dimension_column)
        top_metric = metric_field
        if top_metric and top_metric in top_row:
            bullets.append(
                f"排名第一的 {dimension_column} 为 {top_value}，"
                f"对应 {top_metric} 为 {_format_number(top_row.get(top_metric))}。"
            )
    if len(rows) >= 3 and dimension_column and metric_field:
        first = rows[0].get(metric_field)
        third = rows[2].get(metric_field)
        if _is_number_like(first) and _is_number_like(third):
            gap = float(first) - float(third)
            bullets.append(f"Top1 与 Top3 相差 {_format_number(gap)}，头部集中度较明显。")
    null_counts = python_result.get("null_counts") or {}
    if isinstance(null_counts, dict):
        non_zero_nulls = {key: value for key, value in null_counts.items() if value}
        if non_zero_nulls:
            bullets.append(
                "存在空值字段："
                + "、".join(f"{key} {value} 个" for key, value in list(non_zero_nulls.items())[:5])
                + "。"
            )
        else:
            bullets.append("本次返回字段未发现空值。")
    if metric_keys or dimension_keys:
        bullets.append(
            "该结果主要围绕 "
            f"{', '.join(metric_keys) if metric_keys else '查询指标'} 与 "
            f"{', '.join(dimension_keys) if dimension_keys else '查询维度'} 展开。"
        )
    return {
        "title": "结果解读",
        "bullets": bullets,
    }


def _report_suggestions(
    rows: list[dict[str, Any]],
    metric_keys: list[str],
    dimension_keys: list[str],
    python_result: dict[str, Any],
    mode: str = "profile",
) -> dict[str, Any]:
    """Generate follow-up suggestions and caveats for the user."""
    items = []
    if mode == "multi_series_trend":
        items.append("可继续围绕趋势拐点月份、增长最快产品类型和下滑序列做二次追问。")
        items.append(
            "建议进一步补充渠道、区域或风险等级维度，观察不同贷款产品趋势是否存在结构性分化。"
        )
        items.append("如需复核趋势口径，可先查看 SQL 中的时间窗口、时间粒度和产品类型分组字段。")
        if not rows:
            items = [
                "可以尝试放宽时间范围或调整趋势窗口。",
                "可先查看 SQL，再判断是否需要修改语义层或问法。",
            ]
        return {
            "title": "建议与后续行动",
            "items": items,
        }
    if dimension_keys:
        items.append(
            f"可继续围绕 {', '.join(dimension_keys)} 与渠道、产品类型、风险等级做交叉下钻。"
        )
    else:
        items.append("可补充维度后继续下钻，例如渠道、地区、产品类型或风险等级。")
    if metric_keys:
        items.append(
            f"建议核对 {', '.join(metric_keys)} 的业务口径，确认是否需要时间范围或过滤条件。"
        )
    items.append("若要复核结果，可查看 SQL 与语义层映射，确认字段含义和聚合方式。")
    if not rows:
        items = [
            "可以尝试放宽时间范围或重新检查过滤条件。",
            "可先查看 SQL，再判断是否需要修改语义层或问法。",
        ]
    return {
        "title": "建议与后续行动",
        "items": items,
    }


def _report_charts(
    rows: list[dict[str, Any]],
    profile: dict[str, Any],
    metric_keys: list[str],
    dimension_keys: list[str],
    python_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build chart specifications from Python output or result shape."""
    generated_charts = normalize_python_charts(python_result.get("charts") or [])
    if generated_charts:
        return generated_charts
    metrics = python_result.get("metrics") or []
    if not rows or not metrics:
        return []
    metric = metrics[0]
    metric_field = _result_field_name(metric)
    if not metric_field:
        return []
    dimension_item = (
        python_result.get("dimensions") or profile.get("dimension_columns") or [None]
    )[0]
    dimension_column = _result_field_name(dimension_item)
    if not dimension_column:
        return []
    data = []
    for row in rows[:8]:
        label = row.get(dimension_column)
        value = row.get(metric_field)
        if label is None or value is None:
            continue
        data.append(
            {
                "label": label,
                "value": float(value) if _is_number_like(value) else value,
            }
        )
    if not data:
        return []
    return [
        {
            "title": f"{metric_field} 排序图",
            "subtitle": f"按 {dimension_column} 展开，展示前 {len(data)} 项结果。",
            "type": "bar",
            "chart_kind": "bar",
            "x_field": dimension_column,
            "y_field": metric_field,
            "data": data,
            "echarts_option": {
                "tooltip": {"trigger": "axis"},
                "grid": {"left": 48, "right": 24, "top": 36, "bottom": 48},
                "xAxis": {
                    "type": "category",
                    "name": dimension_column,
                    "data": [str(item["label"]) for item in data],
                },
                "yAxis": {"type": "value", "name": str(metric_field)},
                "series": [
                    {
                        "type": "bar",
                        "name": str(metric_field),
                        "data": [item["value"] for item in data],
                    }
                ],
            },
        }
    ]


def normalize_python_charts(charts: Any) -> list[dict[str, Any]]:
    """Normalize chart specs emitted by generated Python into frontend format."""
    if not isinstance(charts, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, chart in enumerate(charts):
        if not isinstance(chart, dict):
            continue
        data = chart.get("data") or []
        if not isinstance(data, list):
            data = []
        normalized_data = []
        for row in data[:50]:
            if not isinstance(row, dict):
                continue
            normalized_data.append(
                {
                    "label": row.get("label")
                    if row.get("label") is not None
                    else row.get(chart.get("x_field") or "x"),
                    "value": row.get("value")
                    if row.get("value") is not None
                    else row.get(chart.get("y_field") or "y"),
                    **row,
                }
            )
        option = chart.get("echarts_option")
        if not isinstance(option, dict):
            option = {}
        chart_type = _normalize_chart_kind(
            chart.get("chart_kind") or chart.get("type") or _chart_kind_from_echarts_option(option)
        )
        raw_series = chart.get("series") or []
        normalized_series: list[dict[str, Any]] = []
        if isinstance(raw_series, list):
            for series in raw_series[:12]:
                if not isinstance(series, dict):
                    continue
                series_name = str(series.get("name") or f"序列 {len(normalized_series) + 1}")
                series_rows = series.get("data") or []
                if not isinstance(series_rows, list):
                    continue
                normalized_points = []
                for row in series_rows[:120]:
                    if not isinstance(row, dict):
                        continue
                    label = row.get("label")
                    value = row.get("value")
                    if label is None and chart.get("x_field"):
                        label = row.get(chart.get("x_field"))
                    if value is None and chart.get("y_field"):
                        value = row.get(chart.get("y_field"))
                    normalized_points.append(
                        {
                            "label": label if label is not None else "",
                            "value": value,
                            **row,
                        }
                    )
                if normalized_points:
                    normalized_series.append(
                        {
                            "name": series_name,
                            "data": normalized_points,
                        }
                    )
        normalized.append(
            {
                "title": str(chart.get("title") or f"分析图表 {index + 1}"),
                "subtitle": str(chart.get("subtitle") or ""),
                "type": chart_type,
                "chart_kind": chart_type,
                "x_field": chart.get("x_field"),
                "y_field": chart.get("y_field"),
                "series_field": chart.get("series_field"),
                "data": normalized_data,
                "series": normalized_series,
                "echarts_option": option,
            }
        )
    return [item for item in normalized if item["data"] or item["echarts_option"]]


def _normalize_chart_kind(value: Any) -> str:
    """Map chart kind aliases to supported chart kinds."""
    kind = str(value or "").strip().lower()
    if kind in {"pie", "bar", "line"}:
        return kind
    return "bar"


def _chart_kind_from_echarts_option(option: Any) -> str:
    """Infer chart kind from an ECharts option object."""
    if not isinstance(option, dict):
        return "bar"
    series = option.get("series")
    if not isinstance(series, list) or not series:
        return "bar"
    first = series[0]
    if not isinstance(first, dict):
        return "bar"
    return _normalize_chart_kind(first.get("type"))


def _report_tables(
    rows: list[dict[str, Any]],
    profile: dict[str, Any],
    python_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build report table specs from Python output or SQL rows."""
    generated_tables = normalize_python_tables(python_result.get("tables") or [])
    if generated_tables:
        return generated_tables
    if not rows:
        return []
    columns = profile.get("columns") or list(rows[0].keys())
    return [
        {
            "title": "结果明细",
            "columns": columns,
            "rows": rows[:10],
        }
    ]


def normalize_python_tables(tables: Any) -> list[dict[str, Any]]:
    """Normalize generated table specs into frontend table definitions."""
    if not isinstance(tables, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, table in enumerate(tables):
        if not isinstance(table, dict):
            continue
        rows = table.get("rows") or []
        if not isinstance(rows, list):
            continue
        rows = [row for row in rows if isinstance(row, dict)]
        if not rows:
            continue
        columns = table.get("columns")
        if not isinstance(columns, list) or not columns:
            columns = list(rows[0].keys())
        normalized.append(
            {
                "title": str(table.get("title") or f"分析表 {index + 1}"),
                "columns": [str(column) for column in columns],
                "rows": rows[:50],
            }
        )
    return normalized


def _top_row_sentence(rows: list[dict[str, Any]], python_result: dict[str, Any]) -> str:
    """Describe the leading row for ranking-style summaries."""
    if not rows:
        return ""
    dimensions = python_result.get("dimensions") or []
    metrics = python_result.get("metrics") or []
    if not dimensions or not metrics:
        return ""
    dimension = _result_field_name(dimensions[0])
    metric = _result_field_name(metrics[0])
    if not metric:
        return ""
    row = rows[0]
    if dimension in row and metric in row:
        return (
            f"首位 {dimension} 为 {row.get(dimension)}，"
            f"{metric} 为 {_format_number(row.get(metric))}。"
        )
    return ""


def _result_field_name(value: Any) -> str:
    """Choose the best display field from a result row."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("field", "column", "name", "key", "metric", "dimension"):
            field = value.get(key)
            if isinstance(field, str) and field:
                return field
    return ""


def _format_number(value: Any) -> str:
    """Format numeric values with compact decimal handling."""
    if value is None:
        return "-"
    if _is_number_like(value):
        number = float(value)
        if number.is_integer():
            return f"{int(number):,}"
        return f"{number:,.4f}".rstrip("0").rstrip(".")
    return str(value)


def report_to_stream_text(report: dict[str, Any]) -> str:
    """Convert the structured report payload to a readable streamed report draft."""
    lines: list[str] = []
    title = str(report.get("title") or "查询结果分析")
    summary = str(report.get("summary") or "")
    lines.append(f"# {title}")
    if summary:
        lines.append(summary)

    executive = report.get("executive_summary") or {}
    bullets = executive.get("bullets") if isinstance(executive, dict) else []
    if bullets:
        lines.append("")
        lines.append("## 执行摘要")
        lines.extend(f"- {item}" for item in bullets)

    background = report.get("background") or {}
    paragraphs = background.get("paragraphs") if isinstance(background, dict) else []
    if paragraphs:
        lines.append("")
        lines.append("## 分析背景与用户诉求")
        lines.extend(str(item) for item in paragraphs)

    process = report.get("analysis_process") or {}
    steps = process.get("steps") if isinstance(process, dict) else []
    if steps:
        lines.append("")
        lines.append("## 数据分析过程")
        for item in steps:
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('title', '分析步骤')}：{item.get('text', '')}")
            result = str(item.get("result") or "")
            if result and len(result) < 260:
                lines.append(f"  结果：{result}")

    interpretation = report.get("interpretation") or {}
    interpretation_bullets = (
        interpretation.get("bullets") if isinstance(interpretation, dict) else []
    )
    if interpretation_bullets:
        lines.append("")
        lines.append("## 结果解读")
        lines.extend(f"- {item}" for item in interpretation_bullets)

    python_result = report.get("python_result") or {}
    if isinstance(python_result, dict) and python_result.get("status") == "failed":
        lines.append("")
        lines.append("## 分析执行提示")
        lines.append(f"- Python 深度分析在重试后仍未成功：{python_result.get('error', '未知错误')}")
        attempts = python_result.get("repair_attempts") or []
        if attempts:
            lines.append(
                "- 系统已按 ReAct 思路尝试观察错误、重新生成脚本并再次执行，"
                f"共尝试 {len(attempts)} 次。"
            )
        lines.append(
            "- 当前报告仅保留 SQL 返回结果、错误说明和复核建议，暂不输出 Python 统计图表。"
        )

    charts = report.get("charts") or []
    if charts:
        lines.append("")
        lines.append("## 图表")
        for chart in charts:
            if not isinstance(chart, dict):
                continue
            lines.append(f"- {chart.get('title', '图表')}：{chart.get('subtitle', '')}")
            for row in (chart.get("data") or [])[:6]:
                if isinstance(row, dict):
                    lines.append(f"  - {row.get('label')}: {_format_number(row.get('value'))}")

    suggestions = report.get("suggestions") or {}
    suggestion_items = suggestions.get("items") if isinstance(suggestions, dict) else []
    if suggestion_items:
        lines.append("")
        lines.append("## 建议与后续行动")
        lines.extend(f"- {item}" for item in suggestion_items)

    return "\n".join(lines).strip()


def align_markdown_chart_kinds(markdown: str, charts: list[dict[str, Any]]) -> str:
    """Make Markdown ECharts blocks match structured chart kinds."""
    if not markdown or not charts:
        return markdown
    normalized = markdown
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        kind = _normalize_chart_kind(chart.get("chart_kind") or chart.get("type"))
        option = chart.get("echarts_option")
        if kind not in {"pie", "bar", "line"} or not isinstance(option, dict):
            continue
        expected_option = deepcopy(option)
        block = "```echarts\n" + json.dumps(expected_option, ensure_ascii=False, indent=2) + "\n```"
        title = str(chart.get("title") or "").strip()
        if title and title in normalized:
            normalized = replace_first_echarts_block_after_title(normalized, title, block)
    return normalized


def replace_first_echarts_block_after_title(markdown: str, title: str, block: str) -> str:
    """Patch the first ECharts JSON block after a chart heading."""
    title_index = markdown.find(title)
    if title_index < 0:
        return markdown
    fence_start = markdown.find("```", title_index)
    if fence_start < 0:
        return markdown
    fence_end = markdown.find("```", fence_start + 3)
    if fence_end < 0:
        return markdown
    fence_end += 3
    return markdown[:fence_start] + block + markdown[fence_end:]


def _final_answer_from_report(report: dict[str, Any], fallback: str) -> str:
    """Return a short final answer string from the generated report payload."""
    title = report.get("title") or "分析报告"
    bullets = ((report.get("executive_summary") or {}).get("bullets") or [])[:3]
    if bullets:
        return f"{title}\n" + "\n".join(f"- {item}" for item in bullets)
    return report.get("summary") or fallback
