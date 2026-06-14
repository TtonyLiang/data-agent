from app.services.llm_service import get_llm_service

ENHANCE_PROMPT = """你是查询改写专家。根据对话历史、用户原始问题和检索到的业务知识，将问题改写为独立的、完整的查询表述。

## 对话历史
{history_text}

## 检索到的业务知识
{evidence_text}

## 规则
- 将代词(那、这个、它等)替换为具体指代对象
- 将业务术语替换为对应的数据库字段含义
- 补充隐含的过滤条件（如 GMV 对应 status=1 的订单）
- 如果是追问(如"那环比呢"), 需要结合上一轮的问题和结果补全语义
- 保持原意不变，不要添加多余信息
- 如果没有历史且没有相关知识，直接返回原始问题

只返回改写后的查询文本，不要其他内容。
"""


async def query_enhance_node(state: dict) -> dict:
    """查询增强节点：根据 evidence 和对话历史改写用户问题."""
    question = state.get("question", "")
    evidence = state.get("evidence", [])
    history = state.get("chat_history", [])

    # 无历史且无知识，直接返回
    if not evidence and not history:
        return {"enhanced_query": question}

    # 构建历史文本
    history_parts = []
    for h in history[-6:]:  # 最近3轮
        role = "用户" if h["role"] == "user" else "助手"
        content = h["content"]
        if h.get("sql"):
            content += f" [SQL: {h['sql'][:80]}]"
        history_parts.append(f"{role}: {content}")
    history_text = "\n".join(history_parts) if history_parts else "无历史对话"

    # 构建 evidence 文本
    evidence_parts = []
    for e in evidence:
        meta = e.get("metadata", {})
        label = meta.get("title", meta.get("business_name", e["source_type"]))
        evidence_parts.append(f"- [{label}] {e['content']}")
    evidence_text = "\n".join(evidence_parts) if evidence_parts else "无相关知识"

    llm = get_llm_service()
    messages = [
        {"role": "system", "content": ENHANCE_PROMPT.format(
            history_text=history_text, evidence_text=evidence_text
        )},
        {"role": "user", "content": question},
    ]

    response = await llm.achat(messages)
    enhanced = response.strip()

    if not enhanced or len(enhanced) < 2:
        enhanced = question

    return {"enhanced_query": enhanced}
