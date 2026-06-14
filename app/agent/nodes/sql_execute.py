
from app.db.mysql import get_business_db, get_datasource_db
from app.utils.sql_validator import validate_sql


async def sql_execute_node(state: dict) -> dict:
    """SQL 执行节点."""
    sql = state.get("sql_text", "")
    datasource_id = state.get("datasource_id")

    if not sql:
        return {"sql_result": [], "sql_error": "SQL为空", "final_answer": "未能生成SQL查询。"}

    ok, reason = validate_sql(sql)
    if not ok:
        return {
            "sql_result": [],
            "sql_error": f"安全拦截: {reason}",
            "final_answer": f"安全拦截: {reason}",
        }

    try:
        db = await get_datasource_db(datasource_id) if datasource_id else get_business_db()
        results = await db.execute_query(sql)
        return {
            "sql_result": results,
            "sql_error": None,
            "final_answer": format_result(results, sql),
        }
    except Exception as e:
        return {
            "sql_result": [],
            "sql_error": str(e),
            "final_answer": f"SQL执行失败: {e}",
        }


def format_result(results: list[dict], sql: str) -> str:
    if not results:
        return "查询结果为空，没有匹配的数据。"

    lines = [f"SQL: `{sql}`\n", f"共 {len(results)} 条结果:\n"]

    if len(results) <= 20:
        headers = list(results[0].keys())
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in results:
            lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    else:
        lines.append("| " + " | ".join(list(results[0].keys())) + " |")
        lines.append("| " + " | ".join(["---"] * len(results[0])) + " |")
        for row in results[:10]:
            lines.append("| " + " | ".join(str(row.get(h, "")) for h in results[0].keys()) + " |")
        lines.append(f"\n... 共 {len(results)} 条，仅显示前10条")

    return "\n".join(lines)
