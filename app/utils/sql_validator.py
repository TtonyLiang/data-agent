"""SQL 安全校验器 —— 保守的词法扫描,拦截危险 SQL。

本模块在 SQL 执行前做安全校验,设计原则是"宁可误杀,不可放过":
- 只允许单条 SELECT 查询。
- 拦截 DML/DDL/权限操作(DROP/INSERT/DELETE/UPDATE/UNION 等)。
- 拦截危险函数(SLEEP/LOAD_FILE/BENCHMARK 等)。
- 拦截系统库和跨库访问。
- 自动注入/截断 LIMIT(默认 1000)。
- 注释和字符串被词法分析器正确跳过,避免注入绕过。

词法扫描器(``tokenize_sql``)手工实现,不依赖第三方 SQL 解析库,
保证轻量且可覆盖项目需要的所有 MySQL 语法。
"""

from __future__ import annotations

from dataclasses import dataclass

# SELECT 结果行数上限,防止大结果集溢出
MAX_SELECT_LIMIT = 1000

# 禁止的 SQL 关键字:DDL/DML/权限/文件操作/锁/预处理等
FORBIDDEN_KEYWORDS = {
    "ALTER",
    "CALL",
    "CREATE",
    "DELETE",
    "DROP",
    "EXEC",
    "EXECUTE",
    "GRANT",
    "HANDLER",
    "INSERT",
    "INTO",
    "INFILE",
    "LOCK",
    "OUTFILE",
    "PREPARE",
    "REPLACE",
    "REVOKE",
    "TRUNCATE",
    "UNION",
    "UPDATE",
    "DUMPFILE",
    "XA",
}

# 禁止的危险函数:时间盲注/文件读取/锁竞争等
DANGEROUS_FUNCTIONS = {
    "BENCHMARK",
    "GET_LOCK",
    "LOAD_FILE",
    "RELEASE_LOCK",
    "SLEEP",
    "SYSDATE",
}

# 禁止访问的系统 schema
SYSTEM_SCHEMAS = {
    "information_schema",
    "mysql",
    "performance_schema",
    "sys",
}

# FROM/JOIN 关键字:用于提取表名引用
TABLE_SOURCE_KEYWORDS = {"FROM", "JOIN"}
# 表名提取停止词:遇到这些关键字时停止向后扫描表名
TABLE_SOURCE_STOPWORDS = {
    "WHERE",
    "GROUP",
    "ORDER",
    "HAVING",
    "LIMIT",
    "ON",
    "USING",
    "LEFT",
    "RIGHT",
    "INNER",
    "OUTER",
    "FULL",
    "CROSS",
    "JOIN",
}


@dataclass(frozen=True)
class SqlToken:
    kind: str
    value: str
    start: int
    end: int

    @property
    def upper(self) -> str:
        return self.value.upper()


@dataclass(frozen=True)
class SqlValidationResult:
    ok: bool
    reason: str
    sql: str


def validate_sql(sql: str) -> tuple[bool, str]:
    """Backward-compatible safety check used by older tests and callers."""
    result = normalize_sql_for_execution(sql)
    return result.ok, result.reason


def normalize_sql_for_execution(sql: str, max_limit: int = MAX_SELECT_LIMIT) -> SqlValidationResult:
    """Validate and normalize a user/model generated SQL statement.

    The project only executes MySQL read queries. This scanner is intentionally
    conservative: it rejects anything that is hard to prove safe, injects a
    bounded LIMIT when absent, and prevents model fallback SQL from crossing into
    system or foreign schemas.
    """
    sql_stripped = sql.strip()
    if not sql_stripped:
        return SqlValidationResult(False, "SQL为空", "")

    tokens = tokenize_sql(sql_stripped)
    meaningful = [token for token in tokens if token.kind != "comment"]
    if not meaningful:
        return SqlValidationResult(False, "SQL为空", "")

    semicolons = [token for token in meaningful if token.value == ";"]
    if semicolons:
        if len(semicolons) > 1 or semicolons[-1] is not meaningful[-1]:
            return SqlValidationResult(False, "只允许单条 SELECT 查询", "")
        sql_stripped = sql_stripped[: semicolons[-1].start].strip()
        tokens = tokenize_sql(sql_stripped)
        meaningful = [token for token in tokens if token.kind != "comment"]

    first = next((token for token in meaningful if token.kind in {"word", "identifier"}), None)
    if not first or first.upper != "SELECT":
        return SqlValidationResult(False, "只允许 SELECT 查询", "")

    forbidden = first_forbidden_keyword(meaningful)
    if forbidden:
        return SqlValidationResult(False, f"禁止操作: {forbidden}", "")

    dangerous_function = first_dangerous_function(meaningful)
    if dangerous_function:
        return SqlValidationResult(False, f"禁止危险函数: {dangerous_function}", "")

    cross_schema_reason = find_cross_schema_table_reference(meaningful)
    if cross_schema_reason:
        return SqlValidationResult(False, cross_schema_reason, "")

    limit_result = enforce_top_level_limit(sql_stripped, meaningful, max_limit)
    if not limit_result.ok:
        return limit_result
    return SqlValidationResult(True, "OK", limit_result.sql)


def extract_table_references(sql: str) -> list[str]:
    """从 SQL 的 FROM/JOIN 子句中提取物理表名(用于权限校验)。"""
    """Return physical table names referenced by FROM/JOIN clauses."""
    tokens = tokenize_sql(sql)
    tables: list[str] = []
    for index, token in enumerate(tokens):
        if token.kind != "word" or token.upper not in TABLE_SOURCE_KEYWORDS:
            continue
        table_token = next_meaningful(tokens, index + 1)
        if not table_token or table_token.value == "(":
            continue
        if table_token.kind not in {"word", "identifier"}:
            continue
        name = table_token.value
        if "." in name:
            name = name.split(".")[-1]
        if name and name not in tables:
            tables.append(name)
    return tables


def tokenize_sql(sql: str) -> list[SqlToken]:
    """SQL 词法扫描器 —— 把 SQL 字符串拆分为 token 列表。

    支持的 token 类型:
    - ``word``:标识符/关键字(字母/下划线开头,后跟字母/数字/下划线/$)
    - ``identifier``:反引号包裹的标识符(``table``)
    - ``string``:单引号/双引号字符串(支持转义和连续引号)
    - ``number``:数字字面量
    - ``symbol``:其他单字符运算符
    - ``comment``:行注释(--/#)和块注释(/* */),会被过滤掉

    注释在后续流程中被跳过,不参与安全校验。
    """
    tokens: list[SqlToken] = []
    index = 0
    length = len(sql)

    while index < length:
        char = sql[index]

        if char.isspace():
            index += 1
            continue

        if sql.startswith("--", index):
            end = sql.find("\n", index + 2)
            index = length if end == -1 else end + 1
            continue

        if char == "#":
            end = sql.find("\n", index + 1)
            index = length if end == -1 else end + 1
            continue

        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end == -1:
                tokens.append(SqlToken("comment", sql[index:], index, length))
                break
            index = end + 2
            continue

        if char in {"'", '"'}:
            start = index
            index = consume_quoted(sql, index, char)
            tokens.append(SqlToken("string", sql[start:index], start, index))
            continue

        if char == "`":
            start = index
            index = consume_backtick_identifier(sql, index)
            value = (
                sql[start + 1 : index - 1].replace("``", "`")
                if index <= length
                else sql[start + 1 :]
            )
            tokens.append(SqlToken("identifier", value, start, index))
            continue

        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < length and (sql[index].isalnum() or sql[index] in {"_", "$"}):
                index += 1
            tokens.append(SqlToken("word", sql[start:index], start, index))
            continue

        if char.isdigit():
            start = index
            index += 1
            while index < length and (sql[index].isdigit() or sql[index] == "."):
                index += 1
            tokens.append(SqlToken("number", sql[start:index], start, index))
            continue

        tokens.append(SqlToken("symbol", char, index, index + 1))
        index += 1

    return tokens


def consume_quoted(sql: str, start: int, quote: str) -> int:
    """消费一个引号字符串(支持转义 \\ 和连续引号 ''),返回结束位置。"""
    index = start + 1
    while index < len(sql):
        char = sql[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            if index + 1 < len(sql) and sql[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return len(sql)


def consume_backtick_identifier(sql: str, start: int) -> int:
    """消费一个反引号标识符(支持连续反引号转义 ```),返回结束位置。"""
    index = start + 1
    while index < len(sql):
        if sql[index] == "`":
            if index + 1 < len(sql) and sql[index + 1] == "`":
                index += 2
                continue
            return index + 1
        index += 1
    return len(sql)


def first_forbidden_keyword(tokens: list[SqlToken]) -> str:
    for token in tokens:
        if token.kind == "word" and token.upper in FORBIDDEN_KEYWORDS:
            return token.upper
    return ""


def first_dangerous_function(tokens: list[SqlToken]) -> str:
    for index, token in enumerate(tokens):
        if token.kind != "word" or token.upper not in DANGEROUS_FUNCTIONS:
            continue
        next_token = next_meaningful(tokens, index + 1)
        if next_token and next_token.value == "(":
            return token.upper
    return ""


def find_cross_schema_table_reference(tokens: list[SqlToken]) -> str:
    for index, token in enumerate(tokens):
        if token.kind != "word" or token.upper not in TABLE_SOURCE_KEYWORDS:
            continue
        table_token = next_meaningful(tokens, index + 1)
        if not table_token:
            continue
        if table_token.value == "(":
            continue
        if table_token.kind not in {"word", "identifier"}:
            continue
        name = table_token.value
        if "." in name:
            return "禁止跨库或复合表名访问"
        if name.lower() in SYSTEM_SCHEMAS:
            return f"禁止访问系统库: {name}"

        dot = next_meaningful(tokens, token_index(tokens, table_token) + 1)
        right = next_meaningful(tokens, token_index(tokens, table_token) + 2)
        if dot and dot.value == "." and right and right.kind in {"word", "identifier"}:
            if name.lower() in SYSTEM_SCHEMAS:
                return f"禁止访问系统库: {name}"
            return "禁止跨库访问，请只使用当前数据源的已采集表"
    return ""


def enforce_top_level_limit(
    sql: str, tokens: list[SqlToken], max_limit: int
) -> SqlValidationResult:
    """确保顶层查询有 LIMIT 且不超过 max_limit。

    无 LIMIT 时自动追加;有 LIMIT 但超限时截断到 max_limit。
    子查询中的 LIMIT 不受影响(通过 depth 计数括号层级)。
    """
    limit_index = find_top_level_keyword(tokens, "LIMIT")
    if limit_index is None:
        return SqlValidationResult(True, "OK", f"{sql.rstrip()}\nLIMIT {max_limit}")

    limit_token = tokens[limit_index]
    count_token = next_meaningful(tokens, limit_index + 1)
    if not count_token or count_token.kind != "number" or "." in count_token.value:
        return SqlValidationResult(False, "LIMIT 必须是正整数", "")

    try:
        count = int(count_token.value)
    except ValueError:
        return SqlValidationResult(False, "LIMIT 必须是正整数", "")
    if count <= 0:
        return SqlValidationResult(False, "LIMIT 必须大于 0", "")
    if count <= max_limit:
        return SqlValidationResult(True, "OK", sql)

    normalized = f"{sql[: limit_token.start].rstrip()}\nLIMIT {max_limit}"
    return SqlValidationResult(True, "OK", normalized)


def find_top_level_keyword(tokens: list[SqlToken], keyword: str) -> int | None:
    depth = 0
    for index, token in enumerate(tokens):
        if token.value == "(":
            depth += 1
            continue
        if token.value == ")":
            depth = max(depth - 1, 0)
            continue
        if depth == 0 and token.kind == "word" and token.upper == keyword:
            return index
    return None


def next_meaningful(tokens: list[SqlToken], start: int) -> SqlToken | None:
    for token in tokens[start:]:
        if token.kind != "comment":
            return token
    return None


def token_index(tokens: list[SqlToken], target: SqlToken) -> int:
    for index, token in enumerate(tokens):
        if token is target:
            return index
    return -1


def extract_sql_from_llm(text: str) -> str:
    """从 LLM 输出中提取 SQL."""
    text = text.strip()
    if "```sql" in text:
        text = text.split("```sql")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return text
