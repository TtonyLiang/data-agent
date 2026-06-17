from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from langchain_core.callbacks.manager import adispatch_custom_event

from app.models.knowledge import LogicForm, SemanticRuntime
from app.services.python_executor import PythonExecutionError, get_python_executor
from app.services.semantic_runtime import get_semantic_runtime_service


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
    plan = {
        "objective": state.get("enhanced_question") or state.get("question", ""),
        "original_question": state.get("question", ""),
        "enhanced_question": state.get("enhanced_question", ""),
        "mode": "local_basic_profile",
        "mode_label": "本地基础画像",
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
            "基于 SQL 结果生成摘要",
            "汇总数值字段基础统计",
            "组装前端结构化报告",
        ],
        "limitations": [
            "当前阶段只做 SQL 结果后的基础统计画像",
            "尚未接入大模型解释、图表推荐和异常归因",
        ],
    }
    return {"plan": plan}


async def python_generate_node(state: dict) -> dict:
    """生成只处理 SQL 结果集的 Python 分析代码。"""
    rows = state.get("sql_result") or []
    profile = profile_rows(rows)
    code = _build_analysis_code()
    await emit_phase3_stream("python_generate", code)
    return {
        "python_code": code,
        "python_result": {
            "status": "generated",
            "row_count": len(rows),
            "column_count": len(profile["columns"]),
            "numeric_columns": profile["numeric_columns"],
            "dimension_columns": profile["dimension_columns"],
            "executor": "restricted_local_subprocess",
            "analysis_scope": "SQL 结果集基础统计，不访问业务库",
            "generated_tasks": [
                "识别数值列与维度列",
                "计算 count/sum/avg/min/max",
                "提取维度样例和空值计数",
            ],
        },
    }


async def python_analyze_node(state: dict) -> dict:
    """执行 Python 分析并输出结构化结果。"""
    rows = state.get("sql_result") or []
    code = state.get("python_code") or _build_analysis_code()
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
        payload["analysis_scope"] = "SQL 结果集基础统计"
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
    await emit_phase3_stream("report_generator", report_to_stream_text(report))
    return {
        "report": report.get("summary", ""),
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


def json_dumps_pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


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


def _build_analysis_code() -> str:
    return r'''
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
metrics = []
for column in numeric_columns:
    values = [float(row.get(column)) for row in rows if _is_number(row.get(column))]
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

result = {
    "row_count": len(rows),
    "columns": columns,
    "metrics": metrics,
    "dimensions": dimension_columns,
    "dimension_samples": dimension_samples,
    "null_counts": null_counts,
}
print(json.dumps(result, ensure_ascii=False))
'''.strip()


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
        "mode": "local_basic_profile",
        "mode_label": "本地基础画像",
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
    dimension_column = (python_result.get("dimensions") or profile.get("dimension_columns") or [None])[0]
    if isinstance(metric, dict) and metric.get("field") and metric.get("max") is not None:
        bullets.append(
            f"{metric.get('field')} 的最大值为 {_format_number(metric.get('max'))}，"
            f"最小值为 {_format_number(metric.get('min'))}，"
            f"平均值为 {_format_number(metric.get('avg'))}。"
        )
    if dimension_column and rows:
        top_row = rows[0]
        top_value = top_row.get(dimension_column)
        top_metric = metric.get("field") if isinstance(metric, dict) else None
        if top_metric and top_metric in top_row:
            bullets.append(f"排名第一的 {dimension_column} 为 {top_value}，对应 {top_metric} 为 {_format_number(top_row.get(top_metric))}。")
    if len(rows) >= 3 and dimension_column and metric.get("field"):
        first = rows[0].get(metric["field"])
        third = rows[2].get(metric["field"])
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
    metrics = python_result.get("metrics") or []
    if not rows or not metrics:
        return []
    metric = metrics[0]
    if not isinstance(metric, dict) or not metric.get("field"):
        return []
    dimension_column = (python_result.get("dimensions") or profile.get("dimension_columns") or [None])[0]
    if not dimension_column:
        return []
    data = []
    for row in rows[:8]:
        label = row.get(dimension_column)
        value = row.get(metric["field"])
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
            "title": f"{metric.get('field')} 排序图",
            "subtitle": f"按 {dimension_column} 展开，展示前 {len(data)} 项结果。",
            "type": "bar",
            "x_field": dimension_column,
            "y_field": metric["field"],
            "data": data,
        }
    ]


def _report_tables(
    rows: list[dict[str, Any]],
    profile: dict[str, Any],
    python_result: dict[str, Any],
) -> list[dict[str, Any]]:
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


def _top_row_sentence(rows: list[dict[str, Any]], python_result: dict[str, Any]) -> str:
    if not rows:
        return ""
    dimensions = python_result.get("dimensions") or []
    metrics = python_result.get("metrics") or []
    if not dimensions or not metrics or not isinstance(metrics[0], dict):
        return ""
    dimension = dimensions[0]
    metric = metrics[0].get("field")
    if not metric:
        return ""
    row = rows[0]
    if dimension in row and metric in row:
        return f"首位 {dimension} 为 {row.get(dimension)}，{metric} 为 {_format_number(row.get(metric))}。"
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


def _final_answer_from_report(report: dict[str, Any], fallback: str) -> str:
    title = report.get("title") or "分析报告"
    bullets = ((report.get("executive_summary") or {}).get("bullets") or [])[:3]
    if bullets:
        return f"{title}\n" + "\n".join(f"- {item}" for item in bullets)
    return report.get("summary") or fallback
