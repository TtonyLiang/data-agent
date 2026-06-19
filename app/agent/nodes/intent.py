from app.agent.prompts import load_prompt
from app.services.llm_service import get_llm_service
from app.services.prompt_service import get_prompt_service

INTENT_PROMPT = load_prompt("intent_recognition.system.md")


DATA_QUERY_KEYWORDS = (
    "查询",
    "统计",
    "多少",
    "排名",
    "分析",
    "趋势",
    "分布",
    "对比",
    "同比",
    "环比",
    "占比",
    "指标",
    "报表",
    "金额",
    "余额",
    "本金",
    "放款",
    "审批",
    "逾期",
    "回收",
    "催收",
    "核销",
    "风险",
    "客户",
    "团队",
    "vintage",
    "mob",
    "pd",
    "dpd",
    "dti",
    "m1",
    "m1+",
    "m2",
    "m3",
)

FOLLOWUP_DATA_QUERY_KEYWORDS = (
    "前",
    "后",
    "再看",
    "换成",
    "改成",
    "呢",
    "继续",
    "上面",
    "刚才",
    "不是金额",
    "笔数",
    "数量",
)

METADATA_QUERY_KEYWORDS = (
    "有哪些表",
    "所有表",
    "表清单",
    "表列表",
    "表结构",
    "字段",
    "schema",
    "数据库结构",
)


def rule_based_intent(question: str) -> str | None:
    """Return an obvious intent before trusting model classification."""
    normalized = (question or "").strip().lower()
    if not normalized:
        return "chat"

    has_data_signal = any(keyword in normalized for keyword in DATA_QUERY_KEYWORDS)
    has_metadata_signal = any(keyword in normalized for keyword in METADATA_QUERY_KEYWORDS)

    if has_metadata_signal and not has_data_signal:
        return "metadata_query"
    if has_data_signal:
        return "data_query"
    return None


def rule_based_intent_with_history(question: str, history: list[dict] | None = None) -> str | None:
    """Resolve short follow-up questions against recent data-query context."""
    direct = rule_based_intent(question)
    if direct:
        return direct
    normalized = (question or "").strip().lower().replace(" ", "")
    if not normalized or not history:
        return direct
    has_followup_signal = any(keyword in normalized for keyword in FOLLOWUP_DATA_QUERY_KEYWORDS)
    if not has_followup_signal:
        return direct
    if recent_history_has_data_context(history):
        return "data_query"
    return direct


def recent_history_has_data_context(history: list[dict]) -> bool:
    for item in reversed(history[-8:]):
        content = str(item.get("content") or "")
        if item.get("logic_form") or item.get("sql") or rule_based_intent(content) == "data_query":
            return True
    return False


async def intent_recognition_node(state: dict) -> dict:
    """意图识别节点."""
    llm = get_llm_service()
    question = state.get("question", "")
    history = state.get("chat_history") or []

    deterministic_intent = rule_based_intent_with_history(question, history)
    if deterministic_intent:
        return {
            "intent": deterministic_intent,
            "need_analysis": deterministic_intent == "data_query",
        }

    system_prompt = await get_prompt_service().resolve(
        "intent_recognition.system",
        INTENT_PROMPT,
        agent_id=state.get("agent_id"),
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
    response = await llm.achat(messages, **llm_kwargs)

    import json

    try:
        result = json.loads(response.strip())
        intent = result.get("intent", "chat")
    except (json.JSONDecodeError, AttributeError):
        intent = rule_based_intent_with_history(question, history) or "chat"

    if intent == "chat":
        intent = rule_based_intent_with_history(question, history) or intent

    return {"intent": intent, "need_analysis": intent == "data_query"}
