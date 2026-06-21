from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from langchain_core.callbacks.manager import adispatch_custom_event

from app.agent.domain_rules import contains_any
from app.agent.prompts import load_prompt
from app.services.llm_service import get_llm_service
from app.services.prompt_service import get_prompt_service
from app.services.semantic_runtime import get_semantic_runtime_service
from app.utils.logging_helpers import (
    json_for_log,
    log_node_end,
    log_node_error,
    log_node_start,
    truncate_text,
)

SEMANTIC_ENHANCE_PROMPT = load_prompt("semantic_enhance.system.md")
logger = logging.getLogger(__name__)
DOMAIN_REWRITE_CACHE_TTL_SECONDS = 300
_domain_rewrite_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}


async def semantic_enhance_node(state: dict) -> dict:
    """Rewrite the original user question into a clearer business question."""
    log_node_start(logger, "semantic_enhance", state, keys=("trace_id", "agent_id", "question"))
    question = str(state.get("question") or "").strip()
    history = state.get("chat_history") or []
    if not question:
        result = _build_result(question, question, "no_change", [], "原始问题为空，跳过语义增强。")
        log_node_end(logger, "semantic_enhance", result)
        return result

    domain_rewrites = await load_domain_rewrites(state.get("agent_id"))
    deterministic = deterministic_enhancement(question, history, domain_rewrites)
    if deterministic:
        logger.info("semantic enhance deterministic candidate=%s", json_for_log(deterministic))
    if deterministic and should_short_circuit_enhancement(question, deterministic):
        result = _build_result(
            question,
            deterministic["enhanced_question"],
            deterministic.get("rewrite_type", "clarified"),
            deterministic.get("preserved_constraints", []),
            deterministic.get("reason", "命中规则增强，跳过大模型调用。"),
        )
        log_node_end(logger, "semantic_enhance", result)
        return result
    try:
        llm = get_llm_service()
        llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
        system_prompt = await get_prompt_service().resolve(
            "semantic_enhance.system",
            SEMANTIC_ENHANCE_PROMPT,
            agent_id=state.get("agent_id"),
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_enhancement_user_prompt(question, history)},
        ]
        content, reasoning = await llm.achat_with_reasoning(messages, **llm_kwargs)
        logger.info(
            "semantic enhance LLM response content=%s reasoning=%s",
            truncate_text(content, 1600),
            truncate_text(reasoning, 1600),
        )
        if reasoning:
            await emit_enhancement_reasoning(reasoning)
        payload = parse_enhancement_response(content)
        logger.info("semantic enhance parsed payload=%s", json_for_log(payload))
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
        result = _build_result(question, enhanced, rewrite_type, preserved, reason)
        log_node_end(logger, "semantic_enhance", result)
        return result
    except Exception as exc:
        log_node_error(logger, "semantic_enhance", exc, state)
        if deterministic:
            result = _build_result(
                question,
                deterministic["enhanced_question"],
                deterministic.get("rewrite_type", "clarified"),
                deterministic.get("preserved_constraints", []),
                f"大模型语义增强失败，使用规则兜底: {exc}",
            )
            log_node_end(logger, "semantic_enhance", result)
            return result
        result = _build_result(
            question,
            question,
            "no_change",
            extract_preserved_constraints(question, question),
            f"大模型语义增强失败，保留原问题: {exc}",
        )
        log_node_end(logger, "semantic_enhance", result)
        return result


def build_enhancement_user_prompt(question: str, history: list[dict]) -> str:
    """Assemble recent dialogue and the raw question for the semantic enhancement model."""
    history_text = render_recent_history(history)
    return f"最近对话：\n{history_text}\n\n当前原始问题：{question}"


def render_recent_history(history: list[dict], limit: int = 6) -> str:
    """Render recent turns into compact text while preserving SQL and LogicForm markers."""
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
    """Parse model output as JSON, falling back to treating plain text as the rewrite."""
    text = strip_code_fence(str(response or "").strip())
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {"enhanced_question": clean_enhanced_question(text)}


def strip_code_fence(text: str) -> str:
    """Remove a Markdown code fence around model output when present."""
    if "```" not in text:
        return text
    body = text.split("```", 2)[1].strip()
    if body.startswith("json"):
        return body[4:].strip()
    return body


def deterministic_enhancement(
    question: str,
    history: list[dict],
    domain_rewrites: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Handle common follow-up and domain rewrite cases with deterministic rules."""
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

    business_rewrite = common_business_rewrite(question, domain_rewrites or [])
    if business_rewrite and business_rewrite != question:
        return {
            "enhanced_question": business_rewrite,
            "rewrite_type": "clarified",
            "preserved_constraints": extract_preserved_constraints(question, business_rewrite),
            "reason": "命中常见业务问法，已补全指标、维度和排序口径。",
            "source": "semantic_rule",
        }
    return None


def should_short_circuit_enhancement(question: str, deterministic: dict[str, Any]) -> bool:
    """Decide whether a deterministic rewrite is reliable enough to skip the model."""
    rewrite_type = str(deterministic.get("rewrite_type") or "")
    constraints = set(deterministic.get("preserved_constraints") or [])
    if rewrite_type == "followup_resolution":
        return True
    if "数量/笔数口径" in constraints and "区域/地区维度" in constraints:
        return True
    return deterministic.get("source") == "semantic_rule"


def guard_enhanced_question(
    question: str,
    history: list[dict],
    candidate: str,
    deterministic: dict[str, Any] | None,
) -> str:
    """Validate the model rewrite and fall back if it emits SQL or loses constraints."""
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
        if (
            previous_limit
            and previous_limit != top_limit
            and contains_top_limit(cleaned, previous_limit)
        ):
            return deterministic["enhanced_question"]

    if is_count_correction(question) and not contains_count_intent(cleaned):
        return (
            deterministic["enhanced_question"]
            if deterministic
            else f"{cleaned}，统计口径为笔数/数量，不是金额。"
        )
    return cleaned


def clean_enhanced_question(text: str) -> str:
    """Normalize a candidate enhanced question into a compact natural-language sentence."""
    cleaned = str(text or "").strip().strip('"').strip("'")
    cleaned = re.sub(r"^增强后的?问题[:：]\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def common_business_rewrite(
    question: str,
    domain_rewrites: list[dict[str, Any]],
) -> str | None:
    """Rewrite high-confidence business patterns without waiting for an LLM."""
    for item in domain_rewrites:
        if not rewrite_rule_matches(question, item.get("match") or {}):
            continue
        template = str(item.get("template") or "").strip()
        if not template:
            continue
        top_limit = extract_top_limit(question)
        return template.format(
            top_n=f"前{number_to_chinese(top_limit)}" if top_limit else "",
            top_n_suffix=f"，取前{number_to_chinese(top_limit)}个" if top_limit else "",
        )
    return None


async def load_domain_rewrites(agent_id: int | None) -> list[dict[str, Any]]:
    """Load semantic-enhancement rewrite rules from the agent-bound domain with a small cache."""
    if not agent_id:
        return []
    now = time.monotonic()
    cached = _domain_rewrite_cache.get(int(agent_id))
    if cached and now - cached[0] < DOMAIN_REWRITE_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        svc = get_semantic_runtime_service()
        domain = await svc.get_agent_bound_domain(int(agent_id))
        if not domain or not domain.id:
            _domain_rewrite_cache[int(agent_id)] = (now, [])
            return []
        assets = await svc.list_assets(domain.id, "rule")
        rewrites: list[dict[str, Any]] = []
        for rule in assets.get("rule", []):
            if rule.get("rule_type") != "rewrite":
                continue
            expression = rule.get("expression") or {}
            if isinstance(expression, dict):
                rewrites.extend(
                    item for item in expression.get("rewrites") or [] if isinstance(item, dict)
                )
        _domain_rewrite_cache[int(agent_id)] = (now, rewrites)
        return rewrites
    except Exception as exc:
        logger.warning("semantic enhance domain rewrite load failed agent_id=%s error=%s", agent_id, exc)
        return []


def rewrite_rule_matches(question: str, match: dict[str, Any]) -> bool:
    """Evaluate lightweight semantic-enhancement rewrite matchers."""
    if not isinstance(match, dict):
        return False
    if match.get("any") and not contains_any(question, match.get("any") or []):
        return False
    if match.get("all") and not all(contains_any(question, [term]) for term in match.get("all") or []):
        return False
    intents = set(match.get("intents") or [])
    if "count" in intents and not contains_count_intent(question):
        return False
    if "trend" in intents and not contains_trend_intent(question):
        return False
    if "region" in intents and not contains_region_intent(question):
        return False
    if "product" in intents and not (
        contains_product_type_intent(question) or contains_bucketed_loan_intent(question)
    ):
        return False
    return True


def replace_top_limit(previous_question: str, limit: int) -> str:
    """Apply a new TopN limit to the previous full data question."""
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
    """Force a previous question to use count/volume semantics instead of amount."""
    text = str(previous_question or "").strip()
    if not text:
        return "延续上一轮问题，但统计口径改为笔数/数量，不是金额。"
    if contains_count_intent(text):
        return text
    return f"{text}。本次统计口径必须是笔数/数量，不是金额。"


def extract_preserved_constraints(question: str, enhanced: str) -> list[str]:
    """Collect key constraints that should remain visible after question rewriting."""
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
    """Extract TopN from short follow-ups such as 前五呢."""
    compact = compact_text(question)
    limit = extract_top_limit(compact)
    if not limit:
        return None
    return limit if len(compact) <= 16 or compact.endswith("呢") else None


def extract_top_limit(text: str) -> int | None:
    """Extract numeric or Chinese TopN limits from text."""
    compact = compact_text(text)
    match = re.search(r"(?:top|前)(\d{1,3})", compact, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"前([一二两三四五六七八九十]+)", compact)
    if match:
        return chinese_number_to_int(match.group(1))
    return None


def contains_top_limit(text: str, limit: int) -> bool:
    """Return true when text contains the expected TopN value."""
    compact = compact_text(text)
    chinese = number_to_chinese(limit)
    return f"前{limit}" in compact or f"top{limit}" in compact or f"前{chinese}" in compact


def last_user_data_question(history: list[dict]) -> str:
    """Return the latest user message that appears to contain a data query."""
    for item in reversed(history or []):
        if item.get("role") != "user":
            continue
        content = str(item.get("content") or "").strip()
        if content and looks_like_data_context(content):
            return content
    for item in reversed(history or []):
        content = str(item.get("content") or "").strip()
        if content and (
            item.get("logic_form") or item.get("sql") or looks_like_data_context(content)
        ):
            return content
    return ""


def looks_like_data_context(text: str) -> bool:
    """Heuristically identify whether text carries data-query context."""
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
    """Detect user corrections that clarify they wanted count rather than amount."""
    compact = compact_text(question)
    return (
        "不是金额" in compact
        or "问的是笔数" in compact
        or "要的是笔数" in compact
        or ("笔数" in compact and "金额" in compact)
    )


def contains_count_intent(text: str) -> bool:
    """Detect words that indicate count or quantity semantics."""
    compact = compact_text(text)
    return any(
        token in compact
        for token in ("笔数", "多少笔", "几笔", "数量", "申请数", "申请量", "进件量", "count")
    )


def contains_region_intent(text: str) -> bool:
    """Detect region or area grouping intent."""
    compact = compact_text(text)
    return any(token in compact for token in ("区域", "地区", "region", "area"))


def contains_product_type_intent(text: str) -> bool:
    """Detect product-type grouping or filtering intent."""
    compact = compact_text(text)
    return any(
        token in compact for token in ("产品类型", "贷款产品", "产品", "producttype", "product")
    )


def contains_bucketed_loan_intent(text: str) -> bool:
    """Detect bucketed loan-amount grouping intent."""
    compact = compact_text(text)
    return any(
        token in compact
        for token in ("各个贷款", "各类贷款", "不同贷款", "每种贷款", "各贷款", "各项贷款")
    )


def contains_trend_intent(text: str) -> bool:
    """Detect trend or time-series wording."""
    compact = compact_text(text)
    return any(
        token in compact
        for token in ("变化", "趋势", "走势", "波动", "按月", "按日", "同比", "环比", "trend")
    )


def chinese_number_to_int(text: str) -> int | None:
    """Convert small Chinese numerals used in TopN expressions into integers."""
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
    """Render a small integer as Chinese text for natural rewritten questions."""
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
    """Lowercase and remove whitespace to simplify mixed Chinese/English keyword checks."""
    return re.sub(r"\s+", "", str(text or "")).lower()


def unique_list(values: list[str]) -> list[str]:
    """Deduplicate strings while preserving their first-seen order."""
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


async def emit_enhancement_reasoning(delta: str) -> None:
    """Emit semantic-enhancement reasoning chunks to the LangGraph custom event stream."""
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
    """Build the graph state update produced by semantic enhancement."""
    payload = {
        "original_question": original_question,
        "enhanced_question": enhanced_question or original_question,
        "rewrite_type": rewrite_type,
        "preserved_constraints": [
            str(item) for item in preserved_constraints if str(item or "").strip()
        ],
        "reason": reason,
    }
    return {
        "enhanced_question": payload["enhanced_question"],
        "semantic_enhancement": payload,
    }
