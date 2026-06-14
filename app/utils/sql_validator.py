import re


def validate_sql(sql: str) -> tuple[bool, str]:
    """基础 SQL 安全校验."""
    sql_stripped = sql.strip()
    sql_upper = sql_stripped.upper()

    if not sql_stripped:
        return False, "SQL为空"

    # 必须以 SELECT 开头
    if not sql_upper.startswith("SELECT"):
        return False, "只允许 SELECT 查询"

    statements = [part.strip() for part in sql_stripped.split(";") if part.strip()]
    if len(statements) != 1:
        return False, "只允许单条 SELECT 查询"

    # 禁止危险操作
    forbidden = [
        r'\bINSERT\b', r'\bUPDATE\b', r'\bDELETE\b', r'\bDROP\b',
        r'\bALTER\b', r'\bCREATE\b', r'\bTRUNCATE\b', r'\bGRANT\b',
        r'\bREVOKE\b', r'\bEXEC\b', r'\bEXECUTE\b', r'\bCALL\b',
    ]
    for pattern in forbidden:
        if re.search(pattern, sql_upper):
            keyword = pattern.replace("\\b", "")
            return False, f"禁止操作: {keyword}"

    return True, "OK"


def extract_sql_from_llm(text: str) -> str:
    """从 LLM 输出中提取 SQL."""
    text = text.strip()
    if "```sql" in text:
        text = text.split("```sql")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return text
