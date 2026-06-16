import json
import re

from app.models.knowledge import LogicForm
from app.services.llm_service import get_llm_service


NL2LF_PROMPT = """你是 Data Agent 的语义解析器。请把用户问题转换为 LogicForm JSON，禁止生成 SQL。

## 当前语义运行时
{runtime_context}

## 可用字段
- intent_type: metric_query
- domain_key: loan_risk
- metrics: 指标 key 列表
- dimensions: 维度 key 列表
- filters: {{"field": "维度或过滤字段key", "operator": "=", "value": "值"}}
- time_range: {{"type": "relative", "period": "this_month|last_month|last_3_months|recent_3_months"}}
- grain: month/day/null
- sort: [{{"field": "指标或维度key", "direction": "asc|desc"}}]
- limit: 整数或 null

只返回 JSON，不要解释，不要 markdown，不要 SQL。
"""


async def nl2lf_generate_node(state: dict) -> dict:
    """把自然语言问题转换为 LogicForm。"""
    if state.get("semantic_error"):
        return {"logic_form": None}

    question = state.get("question", "")
    runtime = state.get("semantic_runtime") or {}
    history = state.get("chat_history", [])
    runtime_context = build_runtime_context(runtime)

    try:
        llm = get_llm_service()
        llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
        messages = [
            {"role": "system", "content": NL2LF_PROMPT.format(runtime_context=runtime_context)},
            {"role": "user", "content": build_user_prompt(question, history)},
        ]
        response = await llm.achat(messages, **llm_kwargs)
        logic_form = parse_logic_form(response)
    except Exception:
        logic_form = fallback_logic_form(question)

    if not logic_form.metrics:
        logic_form = fallback_logic_form(question)

    return {"logic_form": logic_form.model_dump()}


def build_runtime_context(runtime: dict) -> str:
    metrics = [
        {
            "metric_key": item.get("metric_key"),
            "name": item.get("name"),
            "synonyms": item.get("synonyms", []),
            "dimensions": item.get("dimensions", []),
        }
        for item in runtime.get("metrics", [])
    ]
    dimensions = [
        {
            "asset_key": item.get("asset_key"),
            "role": item.get("role"),
            "table": item.get("table_name"),
            "column": item.get("column_name"),
        }
        for item in runtime.get("mappings", [])
        if item.get("role") in {"dimension", "filter", "time"}
    ]
    rules = [
        {"rule_key": item.get("rule_key"), "name": item.get("name"), "description": item.get("description")}
        for item in runtime.get("rules", [])
    ]
    return json.dumps(
        {"metrics": metrics, "dimensions_and_filters": dimensions, "rules": rules},
        ensure_ascii=False,
    )


def build_user_prompt(question: str, history: list[dict]) -> str:
    if not history:
        return question
    recent = []
    for item in history[-6:]:
        role = "用户" if item.get("role") == "user" else "助手"
        recent.append(f"{role}: {item.get('content', '')}")
    return "对话历史:\n" + "\n".join(recent) + f"\n\n当前问题: {question}"


def parse_logic_form(response: str) -> LogicForm:
    text = response.strip()
    if "```" in text:
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:].strip()
    return LogicForm(**json.loads(text))


def fallback_logic_form(question: str) -> LogicForm:
    normalized = question.lower()
    compact = normalized.replace(" ", "")
    filters = []
    dimensions = []
    metrics = ["outstanding_balance"]
    sort = []
    limit = None
    time_range = None

    if "本月" in compact:
        time_range = {"type": "relative", "period": "this_month"}
    elif "上月" in compact or "上个月" in compact:
        time_range = {"type": "relative", "period": "last_month"}
    elif "近三个月" in compact or "近3个月" in compact:
        time_range = {"type": "relative", "period": "recent_3_months"}

    if "现金贷" in question:
        filters.append({"field": "product_type", "operator": "=", "value": "现金贷"})

    mob_match = re.search(r"mob\s*(\d+)", normalized)
    if mob_match:
        filters.append({"field": "mob", "operator": "=", "value": int(mob_match.group(1))})

    if "催收" in question and "回收率" in question:
        metrics = ["collection_recovery_rate"]
        if "团队" in question:
            dimensions.append("assigned_team")
        sort = [{"field": "collection_recovery_rate", "direction": "desc"}]
        limit = 20
    elif "vintage" in normalized or "放款批次" in question or "批次" in question:
        metrics = ["m1_plus_rate"]
        dimensions = ["vintage", "mob"]
    elif "m1" in normalized or "逾期率" in question:
        metrics = ["m1_plus_rate"]
    elif "放款金额" in question or "发放金额" in question:
        metrics = ["disbursement_amount"]
    elif "审批通过率" in question or "通过率" in question:
        metrics = ["approval_rate"]
    elif "核销" in question:
        metrics = ["writeoff_amount"]
    elif "pd" in normalized or "违约概率" in question:
        metrics = ["pd"]
    elif "dti" in normalized or "负债收入比" in question:
        metrics = ["dti"]

    return LogicForm(
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        time_range=time_range,
        sort=sort,
        limit=limit,
    )
