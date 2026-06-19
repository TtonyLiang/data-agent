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
