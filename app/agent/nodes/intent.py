from app.services.llm_service import get_llm_service

INTENT_PROMPT = """你是一个意图识别助手。根据用户的输入，判断用户意图属于以下哪一类：

1. **data_query** - 用户想要查询数据、统计分析、生成报表。例如：
   - "上个月的总销售额是多少？"
   - "各地区订单量排名前10"
   - "分析一下今年的用户增长趋势"

2. **chat** - 用户在闲聊、打招呼、问与数据无关的问题。例如：
   - "你好"
   - "你是谁？"
   - "今天天气怎么样？"

3. **metadata_query** - 用户想了解数据库结构、表信息。例如：
   - "有哪些表？"
   - "订单表有哪些字段？"

请只返回以下JSON格式，不要返回其他内容：
{{"intent": "data_query|chat|metadata_query", "reason": "简要说明判断理由"}}
"""


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


async def intent_recognition_node(state: dict) -> dict:
    """意图识别节点."""
    llm = get_llm_service()
    question = state.get("question", "")

    deterministic_intent = rule_based_intent(question)
    if deterministic_intent:
        return {
            "intent": deterministic_intent,
            "need_analysis": deterministic_intent == "data_query",
        }

    messages = [
        {"role": "system", "content": INTENT_PROMPT},
        {"role": "user", "content": question},
    ]

    llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
    response = await llm.achat(messages, **llm_kwargs)

    import json

    try:
        result = json.loads(response.strip())
        intent = result.get("intent", "chat")
    except (json.JSONDecodeError, AttributeError):
        intent = rule_based_intent(question) or "chat"

    if intent == "chat":
        intent = rule_based_intent(question) or intent

    return {"intent": intent, "need_analysis": intent == "data_query"}
