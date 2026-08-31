"""Conversation node for non-query turns.

This node handles the two branches that do not need the SQL workflow:

* ``metadata_query``: summarize the collected schema for the selected data
  source;
* ``chat``: answer common greetings and capability questions locally, and use
  the configured chat model only for other casual conversation.

The result deliberately exposes only a safe model summary.  API keys and raw
model configuration objects never leave this module.
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Mapping
from typing import Any

from app.services.llm_service import get_llm_service
from app.services.metadata_service import get_metadata_service
from app.services.model_config_service import get_model_config_service

logger = logging.getLogger(__name__)

MODEL_CONFIG_TERMS = (
    "模型配置",
    "模型设置",
    "大模型配置",
    "大模型",
    "大语言模型",
    "对话模型",
    "聊天模型",
    "llm",
    "当前模型",
    "当前配置",
    "配置是什么",
    "模型参数",
    "什么模型",
    "用的什么模型",
    "使用什么模型",
    "使用的模型",
    "用的模型",
    "哪个模型",
    "模型名称",
    "模型名",
    "模型版本",
    "版本号",
    "provider",
    "base_url",
    "base url",
    "api key",
    "apikey",
    "接口地址",
    "模型地址",
)

GREETING_TERMS = (
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "hello",
    "hi",
    "hey",
    "早上好",
    "上午好",
    "中午好",
    "下午好",
    "晚上好",
    "在吗",
)

CAPABILITY_TERMS = (
    "你能做什么",
    "你会什么",
    "有什么功能",
    "你的能力",
    "能帮我做什么",
    "能帮我查什么",
    "可以做什么",
    "可以查什么",
    "支持什么",
    "如何使用",
    "怎么使用",
    "怎么用",
    "介绍一下",
    "帮助",
)

THANKS_TERMS = ("谢谢", "感谢", "多谢")

DEFAULT_GREETING_ANSWER = (
    "你好，我可以帮你查询和分析已连接数据库中的数据，也可以查看表结构。"
    "直接告诉我想了解的指标、维度或时间范围即可。"
)
DEFAULT_CAPABILITY_ANSWER = (
    "我可以根据自然语言查询已连接的数据，生成 SQL、返回结果并做基础分析；"
    "也能查看已采集的表和字段。"
)
DEFAULT_THANKS_ANSWER = "不客气。需要查数据时，直接告诉我问题即可。"
DEFAULT_EMPTY_ANSWER = "我在这里。你可以直接问数据，或询问已连接数据源的表和字段。"
DEFAULT_METADATA_NO_DATASOURCE_ANSWER = (
    "当前没有选择数据源，暂时无法查看表结构。请先选择一个已连接的数据源。"
)
DEFAULT_METADATA_EMPTY_ANSWER = (
    "当前数据源还没有采集到表结构。请先在数据源管理中采集 schema。"
)
DEFAULT_METADATA_ERROR_ANSWER = (
    "读取当前数据源的表结构失败，请检查数据源连接和采集状态。"
)
DEFAULT_MODEL_CONFIG_MISSING_ANSWER = (
    "当前智能体还没有配置对话模型。请先在模型配置中绑定一个大语言模型。"
)


async def conversation_node(state: dict[str, Any]) -> dict[str, Any]:
    """Answer a ``chat`` or ``metadata_query`` turn without entering SQL flow."""
    question = str(state.get("question") or "").strip()
    intent = str(state.get("intent") or "").strip().lower()
    resolved_intent = intent if intent in {"chat", "metadata_query"} else infer_intent(question)

    if resolved_intent == "metadata_query":
        answer, metadata = await _answer_metadata_query(state)
    elif is_model_config_question(question):
        answer, metadata = await _answer_model_config_question(state)
    else:
        answer, metadata = await _answer_chat(question, state)

    metadata = {
        "intent": resolved_intent,
        "question": question,
        **metadata,
    }
    # Keep both names during the transition to the conversation branch.  They
    # point to the same safe object and make the node usable by old callers and
    # the forthcoming graph integration.
    return {
        "final_answer": answer,
        "conversation": metadata,
        "conversation_metadata": metadata,
        "response": metadata,
    }


async def _answer_model_config_question(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Read the agent-bound chat model and render a non-sensitive summary."""
    agent_id = state.get("agent_id")
    try:
        service = get_model_config_service()
        config = await _maybe_await(service.get_agent_chat_config(agent_id))
    except Exception as exc:  # configuration lookup must not break casual chat
        logger.warning(
            "conversation model config lookup failed agent_id=%s error=%s",
            agent_id,
            exc.__class__.__name__,
        )
        return (
            DEFAULT_MODEL_CONFIG_MISSING_ANSWER,
            {
                "mode": "model_config",
                "source": "model_config_service",
                "fallback": True,
                "config_found": False,
                "error_type": exc.__class__.__name__,
            },
        )

    if config is None:
        return (
            DEFAULT_MODEL_CONFIG_MISSING_ANSWER,
            {
                "mode": "model_config",
                "source": "model_config_service",
                "fallback": True,
                "config_found": False,
            },
        )

    provider = _first_value(config, "provider") or "未配置"
    model = _first_value(config, "model_name", "model") or "未配置"
    base_url = _first_value(config, "base_url") or "未配置"
    status = _first_value(config, "status")
    answer = (
        "当前智能体使用的大语言模型配置：\n"
        f"- 提供商：{provider}\n"
        f"- 模型：{model}\n"
        f"- Base URL：{base_url}\n"
        "- 鉴权信息：已隐藏"
    )
    summary: dict[str, Any] = {
        "mode": "model_config",
        "source": "model_config_service",
        "fallback": False,
        "config_found": True,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "model_config": {
            "provider": provider,
            "model": model,
            "base_url": base_url,
        },
    }
    if status:
        summary["status"] = status
    return answer, summary


async def _answer_metadata_query(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Render a bounded table/column overview from the selected data source."""
    datasource_id = state.get("datasource_id")
    base_metadata: dict[str, Any] = {
        "mode": "metadata_query",
        "source": "metadata_service",
        "fallback": False,
        "datasource_id": datasource_id,
    }
    if not datasource_id:
        return DEFAULT_METADATA_NO_DATASOURCE_ANSWER, {**base_metadata, "fallback": True}

    try:
        service = get_metadata_service()
        authorized_getter = getattr(service, "get_authorized_schema", None)
        if callable(authorized_getter):
            schema = await _maybe_await(
                authorized_getter(datasource_id, state.get("agent_id"))
            )
        else:
            schema = await _maybe_await(service.get_schema(datasource_id))
    except Exception as exc:
        logger.warning(
            "conversation metadata lookup failed datasource_id=%s error=%s",
            datasource_id,
            exc.__class__.__name__,
        )
        return (
            DEFAULT_METADATA_ERROR_ANSWER,
            {**base_metadata, "fallback": True, "error_type": exc.__class__.__name__},
        )

    if isinstance(schema, Mapping):
        schema = schema.get("tables") or schema.get("schema") or []
    tables = _as_list(schema)
    if not tables:
        return DEFAULT_METADATA_EMPTY_ANSWER, {
            **base_metadata,
            "fallback": True,
            "table_count": 0,
            "column_count": 0,
        }

    lines = []
    total_columns = 0
    for table in tables:
        table_name = _first_value(table, "table_name", "table", "name") or "未命名表"
        comment = _first_value(table, "table_comment", "comment", "description")
        columns = _as_list(_first_value(table, "columns", "fields"))
        total_columns += len(columns)
        rendered_columns = []
        for column in columns[:MAX_COLUMNS_PER_TABLE]:
            name = _first_value(column, "column_name", "column", "name") or "未命名字段"
            data_type = _first_value(column, "data_type", "type")
            rendered_columns.append(f"{name}（{data_type}）" if data_type else name)
        if len(columns) > MAX_COLUMNS_PER_TABLE:
            rendered_columns.append(f"等 {len(columns)} 个字段")
        suffix = f"：{comment}" if comment else ""
        field_text = ", ".join(rendered_columns) if rendered_columns else "暂无字段"
        lines.append(f"- {table_name}{suffix}\n  字段：{field_text}")

    visible_tables = lines[:MAX_TABLES_IN_ANSWER]
    if len(lines) > MAX_TABLES_IN_ANSWER:
        visible_tables.append(f"- 其余 {len(lines) - MAX_TABLES_IN_ANSWER} 张表未展开")
    answer = (
        f"当前数据源已采集 {len(tables)} 张表，共 {total_columns} 个字段：\n"
        + "\n".join(visible_tables)
    )
    table_summaries = []
    for table in tables:
        table_name = _first_value(table, "table_name", "table", "name") or "未命名表"
        columns = _as_list(_first_value(table, "columns", "fields"))
        table_summaries.append(
            {
                "table_name": table_name,
                "table_comment": (
                    _first_value(table, "table_comment", "comment", "description") or ""
                ),
                "columns": [
                    {
                        "column_name": _first_value(column, "column_name", "column", "name") or "",
                        "data_type": _first_value(column, "data_type", "type") or "",
                    }
                    for column in columns
                ],
            }
        )
    return answer, {
        **base_metadata,
        "table_count": len(tables),
        "column_count": total_columns,
        "tables": table_summaries,
        "truncated": (
            len(tables) > MAX_TABLES_IN_ANSWER
            or any(
                len(_as_list(_first_value(t, "columns", "fields"))) > MAX_COLUMNS_PER_TABLE
                for t in tables
            )
        ),
    }


async def _answer_chat(question: str, state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Use deterministic Chinese replies first, then optionally ask the LLM."""
    kind = classify_local_chat(question)
    if kind == "greeting":
        return DEFAULT_GREETING_ANSWER, {"mode": kind, "source": "fallback", "fallback": False}
    if kind == "capability":
        return DEFAULT_CAPABILITY_ANSWER, {"mode": kind, "source": "fallback", "fallback": False}
    if kind == "thanks":
        return DEFAULT_THANKS_ANSWER, {"mode": kind, "source": "fallback", "fallback": False}
    if not question:
        return DEFAULT_EMPTY_ANSWER, {"mode": "empty", "source": "fallback", "fallback": False}

    try:
        llm = get_llm_service()
        resolver = getattr(llm, "resolve_agent_chat_kwargs", None)
        llm_kwargs = (
            await _maybe_await(resolver(state.get("agent_id")))
            if callable(resolver)
            else {}
        )
        messages = _build_chat_messages(question, state.get("chat_history") or [])
        response = await _maybe_await(llm.achat(messages, **(llm_kwargs or {})))
        text = _response_text(response).strip()
        if text:
            return text, {"mode": "llm", "source": "llm", "fallback": False}
        raise ValueError("empty model response")
    except Exception as exc:
        logger.warning(
            "conversation casual chat LLM failed agent_id=%s error=%s",
            state.get("agent_id"),
            exc.__class__.__name__,
        )
        return (
            DEFAULT_CAPABILITY_ANSWER,
            {
                "mode": "fallback",
                "source": "fallback",
                "fallback": True,
                "error_type": exc.__class__.__name__,
            },
        )


def infer_intent(question: str) -> str:
    """Infer the non-query branch when a caller did not run intent first."""
    normalized = _normalized(question)
    metadata_terms = (
        "有哪些表",
        "所有表",
        "表清单",
        "表列表",
        "表结构",
        "字段",
        "schema",
        "数据库结构",
    )
    if any(term in normalized for term in metadata_terms):
        return "metadata_query"
    return "chat"


def _normalized(question: str) -> str:
    """Normalize case and whitespace for lightweight local intent matching."""
    return re.sub(r"\s+", " ", str(question or "").strip().lower())


def is_model_config_question(question: str) -> bool:
    """Return whether a chat question asks about the active model settings."""
    normalized = _normalized(question)
    if not normalized:
        return False
    return any(term in normalized for term in MODEL_CONFIG_TERMS)


def classify_local_chat(question: str) -> str | None:
    """Classify common chat turns that do not need a model call."""
    normalized = _normalized(question)
    if not normalized:
        return None
    if any(term in normalized for term in THANKS_TERMS):
        return "thanks"
    if any(term in normalized for term in CAPABILITY_TERMS):
        return "capability"
    # Keep greeting matching strict enough not to classify a longer question
    # such as "你好，帮我查订单" as pure small talk.
    compact = re.sub(r"[，。！？!?、\s]+", "", normalized)
    if compact in {re.sub(r"[，。！？!?、\s]+", "", term) for term in GREETING_TERMS}:
        return "greeting"
    return None


def _build_chat_messages(question: str, history: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build a short, non-sensitive prompt for optional casual chat."""
    messages = [
        {
            "role": "system",
            "content": (
                "你是问渠 WenQu 的智能问数助手。只回答一般闲聊，不要生成 SQL，"
                "不要声称访问了未提供的数据；请用简洁自然的中文回答。"
            ),
        }
    ]
    for item in history[-4:]:
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    return messages


def _first_value(value: Any, *names: str) -> Any:
    """Read a field from either a mapping or a Pydantic-like object."""
    for name in names:
        if isinstance(value, Mapping):
            result = value.get(name)
        else:
            result = getattr(value, name, None)
        if result is not None and result != "":
            return result
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    content = _first_value(response, "content", "text")
    if isinstance(content, list):
        return "".join(
            item
            if isinstance(item, str)
            else str(_first_value(item, "text", "content") or "")
            for item in content
        )
    return str(content or "")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


MAX_TABLES_IN_ANSWER = 12
MAX_COLUMNS_PER_TABLE = 24


__all__ = [
    "conversation_node",
    "classify_local_chat",
    "infer_intent",
    "is_model_config_question",
]
