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


async def intent_recognition_node(state: dict) -> dict:
    """意图识别节点."""
    llm = get_llm_service()
    question = state.get("question", "")

    messages = [
        {"role": "system", "content": INTENT_PROMPT},
        {"role": "user", "content": question},
    ]

    response = await llm.achat(messages)

    import json

    try:
        result = json.loads(response.strip())
        intent = result.get("intent", "chat")
    except (json.JSONDecodeError, AttributeError):
        if any(kw in question for kw in ["查询", "统计", "多少", "排名", "分析", "趋势"]):
            intent = "data_query"
        elif any(kw in question for kw in ["表", "字段", "结构", "有哪些"]):
            intent = "metadata_query"
        else:
            intent = "chat"

    return {"intent": intent, "need_analysis": intent == "data_query"}
