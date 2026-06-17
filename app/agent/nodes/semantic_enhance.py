from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.callbacks.manager import adispatch_custom_event

from app.services.llm_service import get_llm_service


SEMANTIC_ENHANCE_PROMPT = """你是智能问数系统中的“语义增强器”。

你的任务是把用户的当前问题改写成更完整、更清晰、更适合后续知识召回、LogicForm 生成和 NL2SQL 兜底理解的自然语言问题。

要求：
- 保留用户原意，不要扩展不存在的筛选条件。
- 补全省略的业务对象、指标、维度、排序、TopN、时间范围。
- 如果当前问题是追问，例如“前五呢”“换成上个月”“我问的是笔数不是金额”，必须结合最近对话补全完整问题。
- 如果用户问“笔数/多少笔/数量/申请数”，增强后必须明确是数量口径，不要改成金额口径。
- 只输出 JSON，不要输出 SQL、Markdown 或额外解释。

JSON 格式：
{{
  "enhanced_question": "增强后的完整自然语言问题",
  "rewrite_type": "clarified|followup_resolution|no_change",
  "preserved_constraints": ["保留下来的关键约束"],
  "reason": "为什么这样改写"
}}
"""


async def semantic_enhance_node(state: dict) -> dict:
    """Rewrite the original user question into a clearer business question."""
    question = str(state.get("question") or "").strip()
    history = state.get("chat_history") or []
    if not question:
        return _build_result(question, question, "no_change", [], "原始问题为空，跳过语义增强。")

    deterministic = deterministic_enhancement(question, history)
    try:
        llm = get_llm_service()
        llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
        messages = [
            {"role": "system", "content": SEMANTIC_ENHANCE_PROMPT},
            {"role": "user", "content": build_enhancement_user_prompt(question, history)},
        ]
        content, reasoning = await llm.achat_with_reasoning(messages, **llm_kwargs)
        if reasoning:
            await emit_enhancement_reasoning(reasoning)
        payload = parse_enhancement_response(content)
        enhanced = guard_enhanced_question(
            question,
            history,
            str(payload.get("enhanced_question") or "").strip(),
            deterministic,
        )
        rewrite_type = str(payload.get("rewrite_type") or "clarified")
        reason = str(payload.get("reason") or "大模型完成语义增强。")
        preserved = payload.get("preserved_constraints")
        if not isinstance(preserved, list):
            preserved = extract_preserved_constraints(question, enhanced)
        if deterministic and enhanced == deterministic["enhanced_question"]:
            rewrite_type = deterministic.get("rewrite_type", "followup_resolution")
            reason = deterministic.get("reason", reason)
            preserved = deterministic.get("preserved_constraints", preserved)
        return _build_result(question, enhanced, rewrite_type, preserved, reason)
    except Exception as exc:
        if deterministic:
            return _build_result(
                question,
                deterministic["enhanced_question"],
                deterministic.get("rewrite_type", "clarified"),
                deterministic.get("preserved_constraints", []),
                f"大模型语义增强失败，使用规则兜底: {exc}",
            )
        return _build_result(
            question,
            question,
            "no_change",
            extract_preserved_constraints(question, question),
            f"大模型语义增强失败，保留原问题: {exc}",
        )


def build_enhancement_user_prompt(question: str, history: list[dict]) -> str:
    history_text = render_recent_history(history)
    return f"最近对话：\n{history_text}\n\n当前原始问题：{question}"


def render_recent_history(history: list[dict], limit: int = 6) -> str:
    if not history:
        return "无"
    lines = []
    for item in history[-limit:]:
        role = "用户" if item.get("role") == "user" else "助手"
        content = str(item.get("content") or "").strip()
        extras = []
        if item.get("logic_form"):
            extras.append(f"LogicForm={item.get('logic_form')}")
        if item.get("sql"):
            extras.append("已生成SQL")
        suffix = f" ({'；'.join(extras)})" if extras else ""
        if content:
            lines.append(f"{role}: {content}{suffix}")
    return "\n".join(lines) if lines else "无"


def parse_enhancement_response(response: str) -> dict[str, Any]:
    text = strip_code_fence(str(response or "").strip())
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {"enhanced_question": clean_enhanced_question(text)}


def strip_code_fence(text: str) -> str:
    if "```" not in text:
        return text
    body = text.split("```", 2)[1].strip()
    if body.startswith("json"):
        return body[4:].strip()
    return body


def deterministic_enhancement(question: str, history: list[dict]) -> dict[str, Any] | None:
    top_limit = extract_followup_top_limit(question)
    previous = last_user_data_question(history)
    if top_limit and previous:
        enhanced = replace_top_limit(previous, top_limit)
        return {
            "enhanced_question": enhanced,
            "rewrite_type": "followup_resolution",
            "preserved_constraints": [f"TopN={top_limit}", "延续上一轮业务口径"],
            "reason": "当前问题是 TopN 追问，已结合上一轮问题补全完整问法。",
        }

    if is_count_correction(question) and previous:
        enhanced = force_count_metric(previous)
        return {
            "enhanced_question": enhanced,
            "rewrite_type": "followup_resolution",
            "preserved_constraints": ["数量/笔数口径", "延续上一轮业务对象和维度"],
            "reason": "当前问题在纠正金额口径，已明确改为数量/笔数口径。",
        }

    business_rewrite = common_business_rewrite(question)
    if business_rewrite and business_rewrite != question:
        return {
            "enhanced_question": business_rewrite,
            "rewrite_type": "clarified",
            "preserved_constraints": extract_preserved_constraints(question, business_rewrite),
            "reason": "命中常见业务问法，已补全指标、维度和排序口径。",
        }
    return None


def guard_enhanced_question(
    question: str,
    history: list[dict],
    candidate: str,
    deterministic: dict[str, Any] | None,
) -> str:
    cleaned = clean_enhanced_question(candidate)
    if not cleaned:
        return deterministic["enhanced_question"] if deterministic else question
    lowered = cleaned.lower()
    if "select " in lowered or "```" in cleaned:
        return deterministic["enhanced_question"] if deterministic else question

    top_limit = extract_followup_top_limit(question)
    if top_limit and deterministic:
        if not contains_top_limit(cleaned, top_limit):
            return deterministic["enhanced_question"]
        previous_limit = extract_top_limit(last_user_data_question(history) or "")
        if previous_limit and previous_limit != top_limit and contains_top_limit(cleaned, previous_limit):
            return deterministic["enhanced_question"]

    if is_count_correction(question) and not contains_count_intent(cleaned):
        return deterministic["enhanced_question"] if deterministic else f"{cleaned}，统计口径为笔数/数量，不是金额。"
    return cleaned


def clean_enhanced_question(text: str) -> str:
    cleaned = str(text or "").strip().strip('"').strip("'")
    cleaned = re.sub(r"^增强后的?问题[:：]\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def common_business_rewrite(question: str) -> str | None:
    compact = compact_text(question)
    top_limit = extract_top_limit(question)
    if "申请" in compact and contains_count_intent(question) and contains_region_intent(question):
        suffix = f"，取前{number_to_chinese(top_limit)}个区域" if top_limit else ""
        return f"查询贷款申请按申请区域分组的申请笔数，并按申请笔数降序排序{suffix}。"
    return None


def replace_top_limit(previous_question: str, limit: int) -> str:
    marker = f"前{number_to_chinese(limit)}"
    text = str(previous_question or "").strip()
    if not text:
        return f"查询上一轮相同口径下排名{marker}的结果。"
    if re.search(r"前\s*(?:\d{1,3}|[一二两三四五六七八九十]+)", text):
        return re.sub(r"前\s*(?:\d{1,3}|[一二两三四五六七八九十]+)", marker, text, count=1)
    if re.search(r"top\s*\d{1,3}", text, flags=re.IGNORECASE):
        return re.sub(r"top\s*\d{1,3}", f"Top {limit}", text, count=1, flags=re.IGNORECASE)
    if "排名" in text:
        return text.replace("排名", f"排名{marker}", 1)
    return f"{text}，请返回{marker}项。"


def force_count_metric(previous_question: str) -> str:
    text = str(previous_question or "").strip()
    if not text:
        return "延续上一轮问题，但统计口径改为笔数/数量，不是金额。"
    if contains_count_intent(text):
        return text
    return f"{text}。本次统计口径必须是笔数/数量，不是金额。"


def extract_preserved_constraints(question: str, enhanced: str) -> list[str]:
    text = f"{question} {enhanced}"
    constraints = []
    top_limit = extract_top_limit(text)
    if top_limit:
        constraints.append(f"TopN={top_limit}")
    if contains_count_intent(text):
        constraints.append("数量/笔数口径")
    if contains_region_intent(text):
        constraints.append("区域/地区维度")
    for token in ("本月", "上月", "近三个月", "近3个月", "今年", "去年"):
        if token in text:
            constraints.append(token)
    return unique_list(constraints)


def extract_followup_top_limit(question: str) -> int | None:
    compact = compact_text(question)
    limit = extract_top_limit(compact)
    if not limit:
        return None
    return limit if len(compact) <= 16 or compact.endswith("呢") else None


def extract_top_limit(text: str) -> int | None:
    compact = compact_text(text)
    match = re.search(r"(?:top|前)(\d{1,3})", compact, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"前([一二两三四五六七八九十]+)", compact)
    if match:
        return chinese_number_to_int(match.group(1))
    return None


def contains_top_limit(text: str, limit: int) -> bool:
    compact = compact_text(text)
    chinese = number_to_chinese(limit)
    return f"前{limit}" in compact or f"top{limit}" in compact or f"前{chinese}" in compact


def last_user_data_question(history: list[dict]) -> str:
    for item in reversed(history or []):
        if item.get("role") != "user":
            continue
        content = str(item.get("content") or "").strip()
        if content and looks_like_data_context(content):
            return content
    for item in reversed(history or []):
        content = str(item.get("content") or "").strip()
        if content and (item.get("logic_form") or item.get("sql") or looks_like_data_context(content)):
            return content
    return ""


def looks_like_data_context(text: str) -> bool:
    compact = compact_text(text)
    return any(
        token in compact
        for token in (
            "查询",
            "统计",
            "多少",
            "排名",
            "分析",
            "趋势",
            "分布",
            "金额",
            "余额",
            "贷款",
            "申请",
            "逾期",
            "回收",
            "核销",
            "vintage",
            "mob",
            "pd",
            "dti",
            "m1",
            "top",
        )
    )


def is_count_correction(question: str) -> bool:
    compact = compact_text(question)
    return (
        "不是金额" in compact
        or "问的是笔数" in compact
        or "要的是笔数" in compact
        or ("笔数" in compact and "金额" in compact)
    )


def contains_count_intent(text: str) -> bool:
    compact = compact_text(text)
    return any(token in compact for token in ("笔数", "多少笔", "几笔", "数量", "申请数", "申请量", "进件量", "count"))


def contains_region_intent(text: str) -> bool:
    compact = compact_text(text)
    return any(token in compact for token in ("区域", "地区", "region", "area"))


def chinese_number_to_int(text: str) -> int | None:
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if text in digits:
        return digits[text]
    if text.startswith("十") and len(text) == 2:
        return 10 + digits.get(text[1], 0)
    if text.endswith("十") and len(text) == 2:
        return digits.get(text[0], 0) * 10
    if "十" in text and len(text) == 3:
        left, right = text.split("十", 1)
        return digits.get(left, 0) * 10 + digits.get(right, 0)
    return None


def number_to_chinese(value: int | None) -> str:
    if value is None:
        return ""
    digits = {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }
    if value in digits:
        return digits[value]
    return str(value)


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def unique_list(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


async def emit_enhancement_reasoning(delta: str) -> None:
    try:
        await adispatch_custom_event(
            "wenqu_token",
            {
                "node": "semantic_enhance",
                "kind": "reasoning",
                "delta": delta,
            },
        )
    except RuntimeError:
        return


def _build_result(
    original_question: str,
    enhanced_question: str,
    rewrite_type: str,
    preserved_constraints: list[Any],
    reason: str,
) -> dict[str, Any]:
    payload = {
        "original_question": original_question,
        "enhanced_question": enhanced_question or original_question,
        "rewrite_type": rewrite_type,
        "preserved_constraints": [str(item) for item in preserved_constraints if str(item or "").strip()],
        "reason": reason,
    }
    return {
        "enhanced_question": payload["enhanced_question"],
        "semantic_enhancement": payload,
    }
