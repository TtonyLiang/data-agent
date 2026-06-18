import json

from langchain_core.callbacks.manager import adispatch_custom_event

from app.config import get_settings
from app.services.llm_service import get_llm_service
from app.services.metadata_service import get_metadata_service
from app.services.prompt_service import get_prompt_service
from app.utils.sql_validator import extract_sql_from_llm, normalize_sql_for_execution


NL2SQL_FALLBACK_PROMPT = """你是 Data Agent 的 NL2SQL 兜底生成器。

当语义层没有命中可执行指标时，请根据已采集 schema 生成一条安全的 MySQL SELECT。

要求：
- 只能使用提供的表和字段
- 只能生成单条 SELECT，禁止 INSERT/UPDATE/DELETE/DDL
- 排名、明细、TopN 查询必须加 LIMIT，默认不超过 100
- 如果用户问“笔数/数量/多少笔/申请数”，优先使用 COUNT(*)
- 如果用户追问“我问的是笔数，不是金额”，需要结合对话历史修正上一轮问题
- 只返回 JSON：{{"sql": "SELECT ..."}}

已采集 schema：
{schema_context}
"""


async def nl2sql_fallback_node(state: dict) -> dict:
    """Generate a restricted SELECT from collected schema when semantic parsing fails."""
    datasource_id = state.get("datasource_id")
    if not datasource_id:
        return _failed("缺少数据源，无法执行 NL2SQL 兜底。")

    metadata_service = get_metadata_service()
    if hasattr(metadata_service, "get_authorized_schema"):
        schema = await metadata_service.get_authorized_schema(datasource_id, state.get("agent_id"))
    else:
        schema = await metadata_service.get_schema(datasource_id)
    if not schema:
        return _failed("当前数据源没有已采集 schema，无法执行 NL2SQL 兜底。")
    schema_context = build_schema_context(
        schema,
        state.get("relevant_tables") or [],
        state.get("relevant_columns") or [],
    )

    question = state.get("enhanced_question") or state.get("question", "")
    original_question = state.get("question", question)
    prompt = build_fallback_user_prompt(question, state.get("chat_history") or [], original_question)
    llm = get_llm_service()
    llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
    system_prompt = await get_prompt_service().resolve(
        "nl2sql_fallback.system",
        NL2SQL_FALLBACK_PROMPT,
        agent_id=state.get("agent_id"),
        variables={"schema_context": schema_context},
    )
    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {"role": "user", "content": prompt},
    ]
    response_parts: list[str] = []
    async for chunk in llm.achat_stream(messages, **llm_kwargs):
        reasoning = ""
        if hasattr(chunk, "additional_kwargs"):
            reasoning = chunk.additional_kwargs.get("reasoning_content", "")
        if reasoning:
            await emit_node_delta("nl2sql_fallback", reasoning, kind="reasoning")
        content = str(getattr(chunk, "content", "") or "")
        if not content:
            continue
        response_parts.append(content)
        await emit_node_delta("nl2sql_fallback", content, kind="token")
    response = "".join(response_parts)
    sql = extract_sql_from_response(response)
    validation = normalize_sql_for_execution(sql)
    if not validation.ok:
        return _failed(f"NL2SQL 兜底生成的 SQL 未通过安全校验: {validation.reason}")

    return {
        "compiled_sql": validation.sql,
        "sql_text": validation.sql,
        "sql_error": None,
        "execution_trace": {
            "compile_strategy": "nl2sql_fallback",
            "fallback_reason": fallback_reason(state),
        },
    }


def build_schema_context(
    schema: list[dict],
    relevant_tables: list[dict] | None = None,
    relevant_columns: list[dict] | None = None,
) -> str:
    table_names = {
        str(item.get("table_name") or item.get("table") or "")
        for item in (relevant_tables or [])
        if item.get("table_name") or item.get("table")
    }
    column_names_by_table: dict[str, set[str]] = {}
    for item in relevant_columns or []:
        table_name = str(item.get("table_name") or item.get("table") or "")
        column_name = str(item.get("column_name") or item.get("column") or "")
        if table_name and column_name:
            column_names_by_table.setdefault(table_name, set()).add(column_name)
            table_names.add(table_name)

    scoped_schema = [
        table for table in schema
        if not table_names or str(table.get("table_name") or "") in table_names
    ]
    if not scoped_schema:
        scoped_schema = schema

    settings = get_settings()
    max_tables = max(1, settings.nl2sql_schema_context_max_tables)
    max_columns = max(1, settings.nl2sql_schema_context_max_columns)
    tables = []
    for table in scoped_schema[:max_tables]:
        table_name = str(table.get("table_name") or "")
        preferred_columns = column_names_by_table.get(table_name, set())
        columns = []
        all_columns = table.get("columns") or []
        if preferred_columns:
            ranked_columns = [
                column for column in all_columns
                if str(column.get("column_name") or "") in preferred_columns
            ] + [
                column for column in all_columns
                if str(column.get("column_name") or "") not in preferred_columns
            ]
        else:
            ranked_columns = all_columns
        for column in ranked_columns[:max_columns]:
            columns.append(
                {
                    "name": column.get("column_name"),
                    "type": column.get("data_type"),
                    "comment": column.get("column_comment"),
                }
            )
        tables.append(
            {
                "table": table_name,
                "comment": table.get("table_comment"),
                "columns": columns,
            }
        )
    return json.dumps(tables, ensure_ascii=False)


async def emit_node_delta(node: str, delta: str, kind: str) -> None:
    try:
        await adispatch_custom_event(
            "wenqu_token",
            {
                "node": node,
                "kind": kind,
                "delta": delta,
            },
        )
    except RuntimeError:
        return


def build_fallback_user_prompt(question: str, history: list[dict], original_question: str | None = None) -> str:
    current = question
    if original_question and original_question != question:
        current = f"原始问题: {original_question}\n语义增强后的问题: {question}"
    if not history:
        return current
    recent = []
    for item in history[-6:]:
        role = "用户" if item.get("role") == "user" else "助手"
        recent.append(f"{role}: {item.get('content', '')}")
    return "对话历史:\n" + "\n".join(recent) + f"\n\n当前问题: {current}"


def extract_sql_from_response(response: str) -> str:
    text = response.strip()
    try:
        payload = json.loads(strip_code_fence(text))
        if isinstance(payload, dict) and payload.get("sql"):
            return str(payload["sql"]).strip().rstrip(";")
    except json.JSONDecodeError:
        pass
    return extract_sql_from_llm(text).strip().rstrip(";")


def strip_code_fence(text: str) -> str:
    if "```" not in text:
        return text
    body = text.split("```", 2)[1].strip()
    if body.startswith("json"):
        return body[4:].strip()
    return body


def fallback_reason(state: dict) -> str:
    validation = state.get("lf_validation") or {}
    if validation.get("errors"):
        return "语义校验未通过: " + "；".join(validation.get("errors") or [])
    return state.get("sql_error") or "语义层未生成可执行 SQL"


def _failed(reason: str) -> dict:
    return {
        "compiled_sql": "",
        "sql_text": "",
        "sql_error": reason,
        "final_answer": reason,
        "execution_trace": {
            "compile_strategy": "nl2sql_fallback",
            "fallback_error": reason,
        },
    }
