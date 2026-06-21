"""日志助手 —— 全仓统一的日志脱敏、截断与节点日志标准化。

本模块是所有后端模块记录日志的公共工具,提供:
1. 敏感数据脱敏(``redact_value`` / ``redact_text``):自动识别并屏蔽 API Key、密码、
   手机号、身份证、银行卡号、Bearer token 等。
2. 大对象截断(``truncate_text`` / ``safe_log_value``):防止日志文件爆炸。
3. 节点日志标准化(``log_node_start`` / ``log_node_end`` / ``log_node_error``):
   graph 节点统一的日志骨架,带 trace_id 贯穿。
4. 结构化序列化(``json_for_log`` / ``state_summary``):把复杂对象转为安全的日志字符串。

使用原则:
- 凡是涉及用户数据(问题、SQL、结果、API Key)的日志,都应通过本模块输出。
- ``log_node_start/end/error`` 是 graph 节点的标准日志模式,所有节点必须使用。
- ``json_for_log`` 递归脱敏并截断,适合记录任意 dict/list 结构。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

# 敏感字段名关键字:字段名包含这些词时,value 会被替换为 ***REDACTED***
SENSITIVE_KEYWORDS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "pwd",
    "secret",
    "token",
    "dsn",
    "connection_string",
    "private_key",
    "credential",
    "credentials",
)
# 敏感值正则模式:在自由文本中匹配并脱敏(手机号/身份证/卡号/邮箱/Bearer token)
SENSITIVE_VALUE_PATTERNS = (
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "1**********"),
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "******************"),
    (re.compile(r"(?<!\d)\d{13,19}(?!\d)"), "****CARD****"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "***@***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1***REDACTED***"),
)


def truncate_text(value: Any, limit: int = 1200) -> str:
    """Return a bounded string so logs keep useful context without growing unbounded."""
    text = redact_text(str(value or ""))
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}...[truncated {omitted} chars]"


def redact_value(key: str, value: Any) -> Any:
    """Mask values whose field names indicate credentials or bearer-style secrets."""
    key_lower = key.lower()
    if any(keyword in key_lower for keyword in SENSITIVE_KEYWORDS):
        if value in (None, ""):
            return value
        return "***REDACTED***"
    return value


def redact_text(text: str) -> str:
    """Mask common sensitive values that may appear inside free-form log strings."""
    redacted = text
    for pattern, replacement in SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def safe_log_value(value: Any, *, text_limit: int = 1200, depth: int = 3) -> Any:
    """Recursively redact and shrink arbitrary payloads before they are written to logs."""
    if depth <= 0:
        return summarize_value(value)
    if isinstance(value, Mapping):
        return {
            str(key): safe_log_value(
                redact_value(str(key), item),
                text_limit=text_limit,
                depth=depth - 1,
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        max_items = 8
        items = [
            safe_log_value(item, text_limit=text_limit, depth=depth - 1)
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            items.append(f"...[{len(value) - max_items} more]")
        return items
    if isinstance(value, str):
        return truncate_text(redact_text(value), text_limit)
    return value


def summarize_value(value: Any) -> Any:
    """Collapse deep structures to a compact shape summary once recursion depth is reached."""
    if isinstance(value, Mapping):
        return {"type": "dict", "keys": list(value.keys())[:12], "size": len(value)}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return {"type": "list", "size": len(value)}
    if isinstance(value, str):
        return truncate_text(value, 200)
    return value


def json_for_log(value: Any, *, text_limit: int = 1200, depth: int = 3) -> str:
    """Serialize a safe, redacted version of a value for single-line log messages."""
    try:
        return json.dumps(
            safe_log_value(value, text_limit=text_limit, depth=depth),
            ensure_ascii=False,
            default=str,
        )
    except Exception:
        return truncate_text(repr(value), text_limit)


def state_summary(state: dict, keys: tuple[str, ...] | list[str] | None = None) -> dict[str, Any]:
    """Extract the small set of state fields that explain where a graph node is running."""
    selected = keys or (
        "trace_id",
        "agent_id",
        "datasource_id",
        "session_id",
        "question",
        "enhanced_question",
        "intent",
        "semantic_error",
        "sql_error",
        "sql_retry_count",
    )
    summary = {key: state.get(key) for key in selected if key in state}
    summary["history_count"] = len(state.get("chat_history") or [])
    if state.get("sql_result") is not None:
        summary["sql_result_count"] = len(state.get("sql_result") or [])
    if state.get("relevant_tables") is not None:
        summary["relevant_table_count"] = len(state.get("relevant_tables") or [])
    if state.get("relevant_columns") is not None:
        summary["relevant_column_count"] = len(state.get("relevant_columns") or [])
    return summary


def log_node_start(
    logger: logging.Logger,
    node: str,
    state: dict,
    keys: tuple[str, ...] | list[str] | None = None,
) -> None:
    """Log a standardized graph-node start message with a bounded state summary."""
    logger.info("node start node=%s state=%s", node, json_for_log(state_summary(state, keys)))


def log_node_end(
    logger: logging.Logger,
    node: str,
    result: dict,
    *,
    text_limit: int = 1600,
) -> None:
    """Log a standardized graph-node completion message with a bounded result summary."""
    logger.info(
        "node end node=%s result=%s",
        node,
        json_for_log(result, text_limit=text_limit, depth=3),
    )


def log_node_error(
    logger: logging.Logger,
    node: str,
    exc: Exception,
    state: dict | None = None,
) -> None:
    """Log a graph-node exception together with enough state to replay the failing branch."""
    logger.exception(
        "node error node=%s error_type=%s state=%s",
        node,
        exc.__class__.__name__,
        json_for_log(state_summary(state or {})),
    )
