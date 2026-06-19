ANALYSIS_MODE = "multi_series_trend"
TIME_TOKENS = ("date", "time", "day", "week", "month", "year", "quarter", "snapshot", "日期", "时间", "月份", "年月", "季度", "周", "日")

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

def _to_float(value):
    return float(value) if _is_number(value) else None

def _fmt(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value

def _is_time_column(column):
    lower = str(column or "").lower()
    return any(token in lower for token in TIME_TOKENS)

columns = list(rows[0].keys()) if rows else []
numeric_columns = [
    column for column in columns
    if any(_is_number(row.get(column)) for row in rows)
]
dimension_columns = [column for column in columns if column not in numeric_columns]
time_columns = [column for column in dimension_columns if _is_time_column(column)]
series_columns = [column for column in dimension_columns if column not in time_columns]

time_column = time_columns[0] if time_columns else None
series_column = series_columns[0] if series_columns else None
metric_column = numeric_columns[0] if numeric_columns else None

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

null_counts = {
    column: sum(1 for row in rows if row.get(column) in (None, ""))
    for column in columns
}

time_order = []
series_map = {}
for row in rows:
    if not time_column or not series_column or not metric_column:
        continue
    time_value = row.get(time_column)
    series_value = row.get(series_column)
    metric_value = _to_float(row.get(metric_column))
    if time_value in (None, "") or series_value in (None, "") or metric_value is None:
        continue
    time_key = str(time_value)
    series_key = str(series_value)
    if time_key not in time_order:
        time_order.append(time_key)
    series_map.setdefault(series_key, {})[time_key] = metric_value

series_totals = {
    name: sum(points.values())
    for name, points in series_map.items()
}
series_names = [
    name for name, _ in sorted(
        series_totals.items(),
        key=lambda item: (-item[1], item[0])
    )
][:6]

chart_series = []
chart_rows = []
series_summary = []
for name in series_names:
    points = series_map.get(name, {})
    series_values = []
    ordered_values = []
    for time_key in time_order:
        value = points.get(time_key)
        series_values.append(None if value is None else value)
        if value is not None:
            ordered_values.append((time_key, value))
            chart_rows.append({
                "label": time_key,
                "value": _fmt(value),
                "series": name,
                time_column: time_key,
                series_column: name,
                metric_column: _fmt(value),
            })
    latest_pair = ordered_values[-1] if ordered_values else (None, None)
    first_pair = ordered_values[0] if ordered_values else (None, None)
    delta = None
    if first_pair[1] is not None and latest_pair[1] is not None:
        delta = latest_pair[1] - first_pair[1]
    chart_series.append({
        "name": name,
        "type": "line",
        "smooth": True,
        "connectNulls": False,
        "data": series_values,
    })
    series_summary.append({
        "name": name,
        "latest_time": latest_pair[0],
        "latest_value": _fmt(latest_pair[1]) if latest_pair[1] is not None else None,
        "first_time": first_pair[0],
        "first_value": _fmt(first_pair[1]) if first_pair[1] is not None else None,
        "delta": _fmt(delta) if delta is not None else None,
        "total": _fmt(series_totals.get(name, 0)),
    })

insights = []
if rows:
    insights.append(f"本次 SQL 返回 {len(rows)} 行趋势明细数据。")
if time_column and time_order:
    insights.append(f"时间范围覆盖 {time_order[0]} 至 {time_order[-1]}。")
if series_column and series_names:
    insights.append(f"共识别 {len(series_names)} 个主要{series_column}序列。")
latest_rank = [
    item for item in series_summary
    if item.get("latest_value") is not None
]
latest_rank.sort(key=lambda item: float(item["latest_value"]), reverse=True)
if latest_rank:
    top_latest = latest_rank[0]
    insights.append(f"最新一期 {top_latest['latest_time']} 中，{top_latest['name']} 的 {metric_column} 最高，为 {top_latest['latest_value']}。")
delta_rank = [
    item for item in series_summary
    if item.get("delta") is not None
]
delta_rank.sort(key=lambda item: float(item["delta"]), reverse=True)
if delta_rank:
    fastest = delta_rank[0]
    slowest = delta_rank[-1]
    insights.append(f"从整体变化看，{fastest['name']} 增长最明显，区间变化为 {fastest['delta']}。")
    if slowest['name'] != fastest['name']:
        insights.append(f"{slowest['name']} 的变化最弱，区间变化为 {slowest['delta']}。")
if not insights:
    insights.append("当前结果可用于多序列趋势分析，但尚未识别出稳定的时间与分类维度。")

charts = []
if chart_series and time_order and metric_column:
    charts.append({
        "title": f"{metric_column} 多序列趋势图",
        "subtitle": f"按 {series_column} 拆分，观察 {time_column} 维度上的变化趋势。",
        "type": "line",
        "chart_kind": "line",
        "x_field": time_column,
        "y_field": metric_column,
        "series_field": series_column,
        "series": [
            {
                "name": item["name"],
                "data": [
                    {"label": time_order[index], "value": _fmt(value)}
                    for index, value in enumerate(item["data"])
                    if value is not None
                ],
            }
            for item in chart_series
        ],
        "data": chart_rows,
        "echarts_option": {
            "tooltip": {"trigger": "axis"},
            "legend": {"bottom": 0},
            "grid": {"left": 48, "right": 24, "top": 36, "bottom": 64},
            "xAxis": {"type": "category", "data": time_order, "name": time_column},
            "yAxis": {"type": "value", "name": metric_column},
            "series": chart_series,
        },
    })

tables = []
if series_summary:
    tables.append({
        "title": "趋势汇总",
        "columns": ["name", "latest_time", "latest_value", "delta", "total"],
        "rows": series_summary,
    })
if rows:
    tables.append({
        "title": "趋势明细",
        "columns": columns,
        "rows": rows[:36],
    })

result = {
    "row_count": len(rows),
    "columns": columns,
    "metrics": metrics,
    "dimensions": dimension_columns,
    "null_counts": null_counts,
    "analysis_mode": ANALYSIS_MODE,
    "series_summary": series_summary,
    "insights": insights,
    "charts": charts,
    "tables": tables,
}
print(json.dumps(result, ensure_ascii=False))
