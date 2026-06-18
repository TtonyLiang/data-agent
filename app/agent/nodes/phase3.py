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

from app.models.knowledge import LogicForm, SemanticRuntime
from app.services.llm_service import get_llm_service
from app.services.prompt_service import get_prompt_service
from app.services.python_executor import PythonExecutionError, get_python_executor
from app.services.semantic_runtime import get_semantic_runtime_service

logger = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
PYTHON_GENERATE_PROMPT = (PROMPT_DIR / "phase3_python_generate.system.md").read_text(encoding="utf-8")
REPORT_GENERATOR_PROMPT = (PROMPT_DIR / "phase3_report_generator.system.md").read_text(encoding="utf-8")


async def semantic_check_node(state: dict) -> dict:
    """SQL 执行前的语义一致性校验。"""
    logic_form_data = state.get("logic_form") or {}
    runtime_data = state.get("semantic_runtime") or {}
    compiled_sql = state.get("compiled_sql") or state.get("sql_text") or ""
    if not logic_form_data or not runtime_data:
        return _semantic_check_failed(["缺少 LogicForm 或知识库，无法执行 SQL 前校验"])
    if not compiled_sql:
        return _semantic_check_failed(["SQL 为空，无法执行 SQL 前校验"])

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
        return result
    except Exception as exc:
        return _semantic_check_failed([str(exc) or exc.__class__.__name__])


async def planner_node(state: dict) -> dict:
    """生成 SQL 后分析计划。"""
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
    return {"plan": plan}


async def python_generate_node(state: dict) -> dict:
    """生成只处理 SQL 结果集的 Python 分析代码。"""
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
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            logger.warning("LLM PythonGenerate failed, fallback to safe template: %s", error)
            await emit_phase3_stream(
                "python_generate",
                f"LLM 生成脚本未通过安全校验，已切换到默认安全模板。原因：{error}\n\n",
                chunk_size=80,
            )
            code = ""
    if not code:
        code = _build_analysis_code(mode)
    if source != "llm_python_generate":
        await emit_phase3_stream("python_generate", code)
    return {
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


async def python_analyze_node(state: dict) -> dict:
    """执行 Python 分析并输出结构化结果。"""
    rows = state.get("sql_result") or []
    code = state.get("python_code") or _build_analysis_code(infer_analysis_mode(state, profile_rows(rows))["mode"])
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
        return result

    try:
        executed = get_python_executor().execute(code, rows)
        payload = executed.payload or {}
        payload["status"] = "success" if executed.ok else "failed"
        payload["analysis_scope"] = "SQL 结果集分析，不访问业务库"
        payload.setdefault("analysis_mode", (state.get("plan") or {}).get("mode") or "profile")
        payload["computed_items"] = computed_items(payload)
        if executed.stderr:
            payload["stderr"] = executed.stderr[-1000:]
        await emit_phase3_stream("python_analyze", json_dumps_pretty(payload))
        return {"python_result": payload}
    except (PythonExecutionError, TimeoutError, Exception) as exc:
        result = {
            "python_result": {
                "status": "failed",
                "row_count": len(rows),
                "error": str(exc) or exc.__class__.__name__,
            }
        }
        await emit_phase3_stream("python_analyze", json_dumps_pretty(result["python_result"]))
        return result


async def report_generator_node(state: dict) -> dict:
    """生成前端可展示的结构化报告。"""
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
            markdown = await generate_report_markdown_with_llm(state, rows, logic_form, plan, python_result)
            if len(re.sub(r"\s+", "", markdown)) < min_report_length(rows):
                raise ValueError("报告正文过短，未达到分析报告信息密度要求")
            source = "llm_report_generator"
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            logger.warning("LLM report generation failed, fallback to structured report: %s", error)
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
    return {
        "report": markdown,
        "report_payload": report,
        "final_answer": _final_answer_from_report(report, state.get("final_answer", "")),
    }


def profile_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    columns = list(rows[0].keys()) if rows else []
    numeric_columns = [
        column for column in columns
        if any(_is_number_like(row.get(column)) for row in rows)
    ]
    return {
        "columns": columns,
        "numeric_columns": numeric_columns,
        "dimension_columns": [column for column in columns if column not in numeric_columns],
    }


def computed_items(python_result: dict[str, Any]) -> list[str]:
    metrics = python_result.get("metrics") or []
    dimensions = python_result.get("dimensions") or []
    items = [
        f"数值字段统计 {len(metrics)} 个",
        f"维度字段识别 {len(dimensions)} 个",
    ]
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
                    "delta": text[start:start + chunk_size],
                    "kind": "token",
                },
            )
        except RuntimeError:
            return


async def emit_phase3_reasoning(node: str, text: str, chunk_size: int = 120) -> None:
    if not text:
        return
    for start in range(0, len(text), chunk_size):
        try:
            await adispatch_custom_event(
                "wenqu_token",
                {
                    "node": node,
                    "delta": text[start:start + chunk_size],
                    "kind": "reasoning",
                },
            )
        except RuntimeError:
            return


def infer_analysis_mode(state: dict, profile: dict[str, Any]) -> dict[str, str]:
    has_time_dimension = _has_time_like_dimension(profile.get("dimension_columns") or [])
    text = " ".join(
        str(value or "")
        for value in (
            state.get("question"),
            state.get("enhanced_question"),
            json_dumps_compact(state.get("logic_form") or {}),
        )
    ).lower()
    if any(token in text for token in ("趋势", "变化", "环比", "同比", "按月", "按日", "month", "day", "trend")):
        if not has_time_dimension:
            if profile.get("numeric_columns") and profile.get("dimension_columns"):
                row_count = len(state.get("sql_result") or [])
                if 2 <= row_count <= 8:
                    return {"mode": "distribution", "label": "结构分布分析"}
                return {"mode": "ranking", "label": "分组对比分析"}
            return {"mode": "profile", "label": "结果画像分析"}
        return {"mode": "trend", "label": "趋势分析"}
    if any(token in text for token in ("排名", "排行", "top", "前", "最多", "最少", "最高", "最低")):
        return {"mode": "ranking", "label": "排名分析"}
    if any(token in text for token in ("占比", "结构", "分布", "比例", "构成")):
        return {"mode": "distribution", "label": "结构分布分析"}
    if any(token in text for token in ("异常", "波动", "离群", "风险")):
        return {"mode": "anomaly", "label": "异常识别分析"}
    if profile.get("numeric_columns") and profile.get("dimension_columns"):
        return {"mode": "ranking", "label": "分组对比分析"}
    return {"mode": "profile", "label": "结果画像分析"}


def _has_time_like_dimension(columns: list[str]) -> bool:
    if not columns:
        return False
    joined = " ".join(str(column or "").lower() for column in columns)
    time_tokens = ("date", "time", "day", "week", "month", "year", "quarter", "snapshot", "日期", "时间", "月份", "年月", "季度", "周", "日")
    return any(token in joined for token in time_tokens)


def should_use_llm_python_generate(state: dict) -> bool:
    return bool(state.get("agent_id") and state.get("sql_result"))


def should_use_llm_report(state: dict) -> bool:
    return bool(state.get("agent_id"))


async def generate_python_code_with_llm(state: dict, profile: dict[str, Any]) -> str:
    llm = get_llm_service()
    llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
    domain = ((state.get("semantic_runtime") or {}).get("domain") or {})
    system_prompt = await get_prompt_service().resolve(
        "phase3_python_generate.system",
        PYTHON_GENERATE_PROMPT,
        agent_id=state.get("agent_id"),
        semantic_domain_id=domain.get("id") if isinstance(domain, dict) else None,
        variables=phase3_prompt_variables(state, profile),
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请只输出可执行 Python 代码。"},
    ]
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
    return strip_code_fence("".join(chunks)).strip()


async def generate_report_markdown_with_llm(
    state: dict,
    rows: list[dict[str, Any]],
    logic_form: dict[str, Any],
    plan: dict[str, Any],
    python_result: dict[str, Any],
) -> str:
    llm = get_llm_service()
    llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
    domain = ((state.get("semantic_runtime") or {}).get("domain") or {})
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
        {"role": "user", "content": "请直接流式输出完整 Markdown 分析报告。"},
    ]
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
    return "".join(chunks).strip()


def phase3_prompt_variables(state: dict, profile: dict[str, Any]) -> dict[str, str]:
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
    if not code:
        raise PythonExecutionError("LLM 未生成 Python 代码")
    if "rows" not in code:
        raise PythonExecutionError("Python 分析代码必须使用 rows 输入变量")
    if "print(" not in code or "json.dumps" not in code:
        raise PythonExecutionError("Python 分析代码必须通过 print(json.dumps(...)) 输出 JSON")
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {"open", "exec", "eval", "compile", "__import__"}:
                raise PythonExecutionError(f"Python 分析代码禁止调用 {node.func.id}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                _assert_prompt_allowed_module(alias.name)
        if isinstance(node, ast.ImportFrom):
            _assert_prompt_allowed_module(node.module or "")


def _assert_prompt_allowed_module(module: str) -> None:
    allowed = {"json", "math", "statistics", "collections", "datetime", "decimal", "itertools", "numpy", "pandas"}
    root = module.split(".", 1)[0]
    if root not in allowed:
        raise PythonExecutionError(f"Python 分析代码禁止导入模块: {module}")


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if "```" not in stripped:
        return stripped
    match = re.search(r"```(?:python|py)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return stripped.replace("```python", "").replace("```py", "").replace("```", "").strip()


def json_dumps_pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def json_dumps_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def min_report_length(rows: list[dict[str, Any]]) -> int:
    return 120 if not rows else 300


def extract_report_summary(markdown: str) -> str:
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
    rows = int(report.get("row_count") or 0)
    sql = str(report.get("sql") or "")
    python_result = report.get("python_result") or {}
    insights = python_result.get("insights") if isinstance(python_result, dict) else []
    charts = report.get("charts") or []
    additions = [
        "",
        "## 补充解读",
        f"本报告基于 SQL 查询返回的 {rows} 行结果生成。Python 阶段没有直接访问业务数据库，只对已经返回的结果集做二次统计、排序和图表结构整理，因此报告中的数字应与结果表保持一致。",
    ]
    if insights:
        additions.append("从分析脚本输出看，最值得关注的是：" + "；".join(str(item) for item in insights[:4]) + "。")
    if charts:
        chart_titles = "、".join(str(item.get("title") or "图表") for item in charts if isinstance(item, dict))
        additions.append(f"可视化建议优先查看 {chart_titles}，用于判断头部集中、趋势变化或结构分布是否明显。")
    if sql:
        additions.append("如需复核口径，建议先查看 SQL 的筛选条件、分组字段和排序字段，再对照语义层指标定义确认是否与业务问题一致。")
    additions.append("后续如果要继续追问，可以围绕排名靠前/靠后的对象、时间变化、区域差异或异常点进行下钻，以便从“查到结果”进一步走向“解释原因”。")
    return markdown.rstrip() + "\n" + "\n".join(additions)


def _is_number_like(value: Any) -> bool:
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
    if not rows:
        return [{"name": "空结果检查", "status": "pending", "description": "结果为空时给出业务提示"}]
    return [
        {
            "name": "基础统计",
            "status": "pending",
            "description": "识别数值列、维度列、行数和空值情况",
        },
        {
            "name": "指标解释",
            "status": "pending",
            "description": f"围绕 {', '.join(logic_form.get('metrics') or []) or '查询结果'} 生成业务解释",
        },
        {
            "name": "异常与重点",
            "status": "pending",
            "description": "提取最大值、最小值和可疑空值字段",
        },
    ]


def _build_analysis_code(mode: str = "profile") -> str:
    return '''
ANALYSIS_MODE = "__ANALYSIS_MODE__"

def _is_number(value):
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

columns = list(rows[0].keys()) if rows else []
numeric_columns = [
    column for column in columns
    if any(_is_number(row.get(column)) for row in rows)
]
dimension_columns = [column for column in columns if column not in numeric_columns]

def _to_float(value):
    return float(value) if _is_number(value) else None

def _fmt(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value

metrics = []
for column in numeric_columns:
    values = [_to_float(row.get(column)) for row in rows if _is_number(row.get(column))]
    if not values:
        continue
    metrics.append({
        "field": column,
        "count": len(values),
        "sum": sum(values),
        "avg": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    })

dimension_samples = {}
for column in dimension_columns[:8]:
    seen = []
    for row in rows:
        value = row.get(column)
        if value in (None, "") or value in seen:
            continue
        seen.append(value)
        if len(seen) >= 5:
            break
    dimension_samples[column] = seen

null_counts = {
    column: sum(1 for row in rows if row.get(column) in (None, ""))
    for column in columns
}

primary_dimension = dimension_columns[0] if dimension_columns else None
primary_metric = numeric_columns[0] if numeric_columns else None
rank_rows = []
if primary_dimension and primary_metric:
    for row in rows[:20]:
        value = _to_float(row.get(primary_metric))
        if value is None:
            continue
        rank_rows.append({
            "label": row.get(primary_dimension),
            "value": _fmt(value),
            primary_dimension: row.get(primary_dimension),
            primary_metric: _fmt(value),
        })

charts = []
if rank_rows:
    if ANALYSIS_MODE == "trend":
        chart_type = "line"
    elif ANALYSIS_MODE == "distribution" and len(rank_rows[:12]) <= 8:
        chart_type = "pie"
    else:
        chart_type = "bar"
    charts.append({
        "title": f"{primary_metric} 按 {primary_dimension} 展示",
        "type": chart_type,
        "x_field": primary_dimension,
        "y_field": primary_metric,
        "data": rank_rows[:12],
        "echarts_option": {
            **(
                {
                    "tooltip": {"trigger": "item"},
                    "legend": {"bottom": 0},
                    "series": [{
                        "type": "pie",
                        "radius": ["42%", "72%"],
                        "name": primary_metric,
                        "data": [{"name": str(item["label"]), "value": item["value"]} for item in rank_rows[:12]],
                    }],
                }
                if chart_type == "pie" else
                {
                    "tooltip": {"trigger": "axis"},
                    "xAxis": {"type": "category", "data": [str(item["label"]) for item in rank_rows[:12]]},
                    "yAxis": {"type": "value", "name": primary_metric},
                    "series": [{"type": chart_type, "name": primary_metric, "data": [item["value"] for item in rank_rows[:12]]}],
                }
            ),
        },
    })

insights = []
if rows:
    insights.append(f"本次 SQL 返回 {len(rows)} 行、{len(columns)} 个字段。")
if rank_rows:
    first = rank_rows[0]
    insights.append(f"{primary_dimension} 排在首位的是 {first.get('label')}，{primary_metric} 为 {first.get('value')}。")
    if len(rank_rows) >= 3:
        insights.append(f"前 3 项分别为 " + "、".join(f"{item.get('label')}({item.get('value')})" for item in rank_rows[:3]) + "。")
if metrics:
    metric = metrics[0]
    insights.append(f"{metric['field']} 合计为 {_fmt(metric['sum'])}，平均值为 {_fmt(metric['avg'])}。")
if not insights:
    insights.append("当前结果主要为明细数据，未识别出可直接聚合的数值字段。")

result = {
    "row_count": len(rows),
    "columns": columns,
    "metrics": metrics,
    "dimensions": dimension_columns,
    "dimension_samples": dimension_samples,
    "null_counts": null_counts,
    "analysis_mode": ANALYSIS_MODE,
    "insights": insights,
    "charts": charts,
    "tables": [{
        "title": "分析结果明细",
        "columns": columns,
        "rows": rows[:20],
    }] if rows else [],
}
print(json.dumps(result, ensure_ascii=False))
'''.strip().replace("__ANALYSIS_MODE__", mode)


def _build_report_payload(
    state: dict,
    rows: list[dict[str, Any]],
    logic_form: dict[str, Any],
    plan: dict[str, Any],
    python_result: dict[str, Any],
) -> dict[str, Any]:
    metric_keys = logic_form.get("metrics") or []
    dimension_keys = logic_form.get("dimensions") or []
    profile = profile_rows(rows)
    title = _report_title(metric_keys, dimension_keys)
    summary = _report_summary(rows, metric_keys, dimension_keys, python_result)
    executive_summary = _report_executive_summary(rows, metric_keys, dimension_keys, python_result)
    background = _report_background(state, metric_keys, dimension_keys)
    analysis_process = _report_process(rows, logic_form, plan, python_result)
    interpretation = _report_interpretation(rows, profile, metric_keys, dimension_keys, python_result)
    suggestions = _report_suggestions(rows, metric_keys, dimension_keys, python_result)
    charts = _report_charts(rows, profile, metric_keys, dimension_keys, python_result)
    tables = _report_tables(rows, profile, python_result)
    highlights = _report_highlights(rows, python_result)
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
        sections.append({
            "title": "分析执行提示",
            "items": [f"Python 分析未完成: {python_result.get('error', '未知错误')}"],
        })

    return {
        "title": title,
        "summary": summary,
        "status": "empty" if not rows else "success",
        "mode": plan.get("mode") or python_result.get("analysis_mode") or "profile",
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


def _report_title(metric_keys: list[str], dimension_keys: list[str]) -> str:
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
) -> str:
    if not rows:
        return "查询执行完成，但当前条件下没有返回匹配数据。"
    metric_text = f"围绕 {', '.join(metric_keys)}" if metric_keys else "围绕本次查询结果"
    dimension_text = f"，按 {', '.join(dimension_keys)} 展开" if dimension_keys else ""
    metric_count = len(python_result.get("metrics") or [])
    top_sentence = _top_row_sentence(rows, python_result)
    suffix = f"已完成 {metric_count} 个数值字段的基础统计。"
    return f"{metric_text}{dimension_text} 共返回 {len(rows)} 行数据，{top_sentence}{suffix}"


def _report_highlights(rows: list[dict[str, Any]], python_result: dict[str, Any]) -> list[dict[str, Any]]:
    highlights: list[dict[str, Any]] = [
        {"label": "结果行数", "value": len(rows), "field": "row_count"}
    ]
    for metric in (python_result.get("metrics") or [])[:3]:
        if not isinstance(metric, dict):
            continue
        field = metric.get("field", "")
        highlights.append({
            "label": f"{field} 平均值",
            "value": metric.get("avg"),
            "field": field,
        })
    return highlights


def _report_executive_summary(
    rows: list[dict[str, Any]],
    metric_keys: list[str],
    dimension_keys: list[str],
    python_result: dict[str, Any],
) -> dict[str, Any]:
    bullets = []
    if rows:
        bullets.append(f"本次查询共返回 {len(rows)} 行数据，已完成基础画像分析。")
    else:
        bullets.append("本次查询未返回结果，当前报告主要说明查询口径和空结果原因。")
    if metric_keys:
        bullets.append(f"核心指标为 {', '.join(metric_keys)}。")
    if dimension_keys:
        bullets.append(f"结果按 {', '.join(dimension_keys)} 展开。")
    metrics = python_result.get("metrics") or []
    if metrics:
        top_metric = metrics[0]
        if isinstance(top_metric, dict) and top_metric.get("max") is not None:
            bullets.append(f"数值字段 {top_metric.get('field')} 的最大值为 {top_metric.get('max')}。")
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


def _report_background(state: dict, metric_keys: list[str], dimension_keys: list[str]) -> dict[str, Any]:
    enhanced_question = str(state.get("enhanced_question") or "").strip()
    original_question = str(state.get("question") or "").strip()
    question_line = f"用户原始问题：{original_question or '未提供'}。"
    if enhanced_question and enhanced_question != original_question:
        question_line += f" 语义增强后问题：{enhanced_question}。"
    return {
        "title": "分析背景与用户诉求",
        "paragraphs": [
            question_line,
            f"当前分析基于已编译 SQL 结果，围绕 {', '.join(metric_keys) if metric_keys else '查询结果'} 展开。",
            f"关注维度为 {', '.join(dimension_keys) if dimension_keys else '无'}。",
            f"SQL 结果用于后续 Python 统计和报告生成，不直接在 Python 阶段访问业务库。",
        ],
    }


def _report_process(
    rows: list[dict[str, Any]],
    logic_form: dict[str, Any],
    plan: dict[str, Any],
    python_result: dict[str, Any],
) -> dict[str, Any]:
    steps = [
        {
            "title": "步骤1：SQL 查询",
            "text": "已执行语义编译后的 SQL，并取得查询结果集。",
            "result": plan.get("sql_steps", [{}])[0].get("sql", ""),
        },
        {
            "title": "步骤2：基础画像",
            "text": "识别数值列、维度列，并对结果集做基础统计。",
            "result": f"数值字段 {len(python_result.get('metrics') or [])} 个，维度字段 {len(python_result.get('dimensions') or [])} 个。",
        },
        {
            "title": "步骤3：结果整理",
            "text": "汇总关键结论、建议和可视化数据，形成可阅读报告。",
            "result": "报告已生成，可继续展开查看明细。",
        },
    ]
    if not rows:
        steps[1]["text"] = "当前没有结果集，因此跳过基础统计。"
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
) -> dict[str, Any]:
    bullets: list[str] = []
    if not rows:
        bullets.append("当前条件下没有返回结果，建议检查时间范围、筛选条件或数据源选择。")
        return {"title": "结果解读", "bullets": bullets}

    metric = (python_result.get("metrics") or [{}])[0] if python_result.get("metrics") else {}
    dimension_item = (python_result.get("dimensions") or profile.get("dimension_columns") or [None])[0]
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
            bullets.append(f"排名第一的 {dimension_column} 为 {top_value}，对应 {top_metric} 为 {_format_number(top_row.get(top_metric))}。")
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
            bullets.append("存在空值字段：" + "、".join(f"{key} {value} 个" for key, value in list(non_zero_nulls.items())[:5]) + "。")
        else:
            bullets.append("本次返回字段未发现空值。")
    if metric_keys or dimension_keys:
        bullets.append(f"该结果主要围绕 {', '.join(metric_keys) if metric_keys else '查询指标'} 与 {', '.join(dimension_keys) if dimension_keys else '查询维度'} 展开。")
    return {
        "title": "结果解读",
        "bullets": bullets,
    }


def _report_suggestions(
    rows: list[dict[str, Any]],
    metric_keys: list[str],
    dimension_keys: list[str],
    python_result: dict[str, Any],
) -> dict[str, Any]:
    items = []
    if dimension_keys:
        items.append(f"可继续围绕 {', '.join(dimension_keys)} 与渠道、产品类型、风险等级做交叉下钻。")
    else:
        items.append("可补充维度后继续下钻，例如渠道、地区、产品类型或风险等级。")
    if metric_keys:
        items.append(f"建议核对 {', '.join(metric_keys)} 的业务口径，确认是否需要时间范围或过滤条件。")
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
    dimension_item = (python_result.get("dimensions") or profile.get("dimension_columns") or [None])[0]
    dimension_column = _result_field_name(dimension_item)
    if not dimension_column:
        return []
    data = []
    for row in rows[:8]:
        label = row.get(dimension_column)
        value = row.get(metric_field)
        if label is None or value is None:
            continue
        data.append({
            "label": label,
            "value": float(value) if _is_number_like(value) else value,
        })
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
            normalized_data.append({
                "label": row.get("label") if row.get("label") is not None else row.get(chart.get("x_field") or "x"),
                "value": row.get("value") if row.get("value") is not None else row.get(chart.get("y_field") or "y"),
                **row,
            })
        option = chart.get("echarts_option")
        if not isinstance(option, dict):
            option = {}
        chart_type = _normalize_chart_kind(chart.get("chart_kind") or chart.get("type") or _chart_kind_from_echarts_option(option))
        normalized.append({
            "title": str(chart.get("title") or f"分析图表 {index + 1}"),
            "subtitle": str(chart.get("subtitle") or ""),
            "type": chart_type,
            "chart_kind": chart_type,
            "x_field": chart.get("x_field"),
            "y_field": chart.get("y_field"),
            "data": normalized_data,
            "echarts_option": option,
        })
    return [item for item in normalized if item["data"] or item["echarts_option"]]


def _normalize_chart_kind(value: Any) -> str:
    kind = str(value or "").strip().lower()
    if kind in {"pie", "bar", "line"}:
        return kind
    return "bar"


def _chart_kind_from_echarts_option(option: Any) -> str:
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
        normalized.append({
            "title": str(table.get("title") or f"分析表 {index + 1}"),
            "columns": [str(column) for column in columns],
            "rows": rows[:50],
        })
    return normalized


def _top_row_sentence(rows: list[dict[str, Any]], python_result: dict[str, Any]) -> str:
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
        return f"首位 {dimension} 为 {row.get(dimension)}，{metric} 为 {_format_number(row.get(metric))}。"
    return ""


def _result_field_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("field", "column", "name", "key", "metric", "dimension"):
            field = value.get(key)
            if isinstance(field, str) and field:
                return field
    return ""


def _format_number(value: Any) -> str:
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
    interpretation_bullets = interpretation.get("bullets") if isinstance(interpretation, dict) else []
    if interpretation_bullets:
        lines.append("")
        lines.append("## 结果解读")
        lines.extend(f"- {item}" for item in interpretation_bullets)

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
    title = report.get("title") or "分析报告"
    bullets = ((report.get("executive_summary") or {}).get("bullets") or [])[:3]
    if bullets:
        return f"{title}\n" + "\n".join(f"- {item}" for item in bullets)
    return report.get("summary") or fallback
