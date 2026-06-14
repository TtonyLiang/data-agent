import json

from app.services.llm_service import get_llm_service

SQL_GENERATE_PROMPT = """你是一个SQL专家。根据用户的问题和数据库Schema信息，生成正确的SQL查询。

## 数据库Schema
{schema_info}

## 语义模型(业务术语到字段的映射)
{semantic_info}

{join_info}

## 用户问题
{question}

## 要求
1. 只生成SELECT语句，禁止INSERT/UPDATE/DELETE/DROP等操作
2. 使用标准MySQL语法
3. 合理使用聚合函数、排序、分页
4. 如果涉及时间，使用合理的日期函数
5. 字段名使用物理字段名（不是业务名称）
6. 多表查询时，使用上述表关联提示中的JOIN条件

{error_hint}

请返回JSON格式：
{{"sql": "SELECT ...", "explanation": "SQL逻辑简要说明"}}
只返回JSON，不要其他内容。
"""

ERROR_HINT_TEMPLATE = """## 上次执行错误
SQL: {failed_sql}
错误: {error_message}
请修正上述错误，重新生成正确的SQL。"""


async def sql_generate_node(state: dict) -> dict:
    """SQL 生成节点."""
    llm = get_llm_service()
    question = state.get("question", "")
    relevant_columns = state.get("relevant_columns", [])
    relevant_tables = state.get("relevant_tables", [])
    semantic_models = state.get("semantic_models", [])
    likely_joins = state.get("likely_joins", [])
    enhanced_query = state.get("enhanced_query", question)
    sql_error = state.get("sql_error")
    failed_sql = state.get("sql_text", "")

    # 构建 schema 信息 (含表级元数据)
    table_meta_map: dict[str, dict] = {}
    for t in relevant_tables:
        table_meta_map[t["table_name"]] = t

    schema_parts = []
    table_cols: dict[str, list[str]] = {}
    for col in relevant_columns:
        tname = col["table_name"]
        if tname not in table_cols:
            table_cols[tname] = []
        desc = f"{col['column_name']} ({col['data_type']})"
        if col.get("column_comment"):
            desc += f" - {col['column_comment']}"
        table_cols[tname].append(desc)

    for tname, cols in table_cols.items():
        tmeta = table_meta_map.get(tname, {})
        table_desc = f"表: {tname}"
        if tmeta.get("table_comment"):
            table_desc += f" ({tmeta['table_comment']})"
        if tmeta.get("business_name"):
            table_desc += f" [业务名:{tmeta['business_name']}]"
        schema_parts.append(f"{table_desc}\n  字段:\n  " + "\n  ".join(cols))
    schema_info = "\n\n".join(schema_parts) if schema_parts else "无可用Schema信息"

    # 构建语义模型信息
    semantic_parts = []
    for sm in semantic_models:
        line = f"{sm['table_name']}.{sm['column_name']} -> 业务名: {sm['business_name']}"
        if sm.get("synonyms"):
            line += f", 同义词: {sm['synonyms']}"
        if sm.get("description"):
            line += f", 说明: {sm['description']}"
        semantic_parts.append(line)
    semantic_info = "\n".join(semantic_parts) if semantic_parts else "无语义模型信息"

    # 构建 join 提示
    if likely_joins:
        join_lines = []
        for j in likely_joins:
            join_lines.append(f"- {j['left']} = {j['right']} ({j.get('reason', '')})")
        join_info = "## 表关联提示\n" + "\n".join(join_lines)
    else:
        join_info = ""

    # 构建错误提示
    if sql_error and failed_sql:
        error_hint = ERROR_HINT_TEMPLATE.format(
            failed_sql=failed_sql, error_message=sql_error
        )
    else:
        error_hint = ""

    messages = [
        {"role": "system", "content": SQL_GENERATE_PROMPT.format(
            schema_info=schema_info,
            semantic_info=semantic_info,
            join_info=join_info,
            question=enhanced_query,
            error_hint=error_hint,
        )},
        {"role": "user", "content": enhanced_query},
    ]

    response = await llm.achat(messages)

    try:
        result = json.loads(response.strip())
        sql = result.get("sql", "")
    except (json.JSONDecodeError, AttributeError):
        # 尝试提取 SQL
        sql = response.strip()
        if "```sql" in sql:
            sql = sql.split("```sql")[1].split("```")[0].strip()
        elif "```" in sql:
            sql = sql.split("```")[1].split("```")[0].strip()

    # 重试时清空错误状态，累加重试计数
    retry_count = state.get("sql_retry_count", 0)
    if sql_error:
        retry_count += 1

    return {
        "sql_text": sql,
        "sql_error": None,
        "sql_retry_count": retry_count,
    }
