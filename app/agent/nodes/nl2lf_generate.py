import json
import logging
import re

from langchain_core.callbacks.manager import adispatch_custom_event

from app.agent.prompts import load_prompt
from app.models.knowledge import LogicFilter, LogicForm, LogicSort
from app.services.llm_service import get_llm_service
from app.services.prompt_service import get_prompt_service
from app.utils.logging_helpers import (
    json_for_log,
    log_node_end,
    log_node_error,
    log_node_start,
    truncate_text,
)

NL2LF_PROMPT = load_prompt("nl2lf_generate.system.md")
logger = logging.getLogger(__name__)


async def nl2lf_generate_node(state: dict) -> dict:
    """把自然语言问题转换为 LogicForm。"""
    log_node_start(
        logger,
        "nl2lf_generate",
        state,
        keys=("trace_id", "agent_id", "question", "enhanced_question", "semantic_error"),
    )
    if state.get("semantic_error"):
        result = {"logic_form": None}
        log_node_end(logger, "nl2lf_generate", result)
        return result

    question = state.get("enhanced_question") or state.get("question", "")
    original_question = state.get("question", question)
    runtime = state.get("semantic_runtime") or {}
    history = state.get("chat_history", [])
    runtime_context = build_runtime_context(runtime)
    logger.info(
        "nl2lf runtime context chars=%s context=%s",
        len(runtime_context),
        truncate_text(runtime_context, 1600),
    )

    try:
        llm = get_llm_service()
        llm_kwargs = await llm.resolve_agent_chat_kwargs(state.get("agent_id"))
        domain = runtime.get("domain", {}) if isinstance(runtime, dict) else {}
        system_prompt = await get_prompt_service().resolve(
            "nl2lf_generate.system",
            NL2LF_PROMPT,
            agent_id=state.get("agent_id"),
            semantic_domain_id=domain.get("id") if isinstance(domain, dict) else None,
            variables={"runtime_context": runtime_context},
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_prompt(question, history, original_question)},
        ]
        response_parts: list[str] = []
        async for chunk in llm.achat_stream(messages, **llm_kwargs):
            reasoning = ""
            if hasattr(chunk, "additional_kwargs"):
                reasoning = chunk.additional_kwargs.get("reasoning_content", "")
            if reasoning:
                await emit_node_delta("nl2lf_generate", reasoning, kind="reasoning")
            content = str(getattr(chunk, "content", "") or "")
            if not content:
                continue
            response_parts.append(content)
            await emit_node_delta("nl2lf_generate", content, kind="token")
        response = "".join(response_parts)
        logger.info("nl2lf LLM raw response=%s", truncate_text(response, 2400))
        logic_form = parse_logic_form(response)
        logger.info("nl2lf parsed logic_form=%s", json_for_log(logic_form.model_dump()))
    except Exception as exc:
        log_node_error(logger, "nl2lf_generate", exc, state)
        logic_form = fallback_logic_form(question)
        logger.info("nl2lf fallback logic_form=%s", json_for_log(logic_form.model_dump()))

    if not logic_form.metrics:
        logic_form = fallback_logic_form(question)
        logger.info(
            "nl2lf empty metrics fallback logic_form=%s", json_for_log(logic_form.model_dump())
        )

    logic_form = normalize_logic_form(question, logic_form, history)
    logger.info("nl2lf normalized logic_form=%s", json_for_log(logic_form.model_dump()))

    result = {"logic_form": logic_form.model_dump()}
    log_node_end(logger, "nl2lf_generate", result)
    return result


def normalize_logic_form(
    question: str,
    logic_form: LogicForm,
    history: list[dict] | None = None,
) -> LogicForm:
    """Apply deterministic product semantics after LLM parsing."""
    compact = question.lower().replace(" ", "")
    context_text = contextual_question_text(question, history)
    context_compact = context_text.lower().replace(" ", "")
    metrics = list(logic_form.metrics)
    dimensions = list(logic_form.dimensions)
    filters = list(logic_form.filters)
    sort = list(logic_form.sort)
    time_range = logic_form.time_range
    limit = logic_form.limit
    grain = logic_form.grain

    asks_balance = "余额" in question or "balance" in compact
    asks_overdue = "逾期" in question or "m1" in compact or "overdue" in compact
    high_pd_segment = "高pd" in compact or ("高" in question and "pd" in compact)
    asks_application_count = is_application_count_question(context_text)
    asks_trend = asks_trend_question(context_text)

    if asks_balance and asks_overdue:
        metrics = ["outstanding_balance", "m1_plus_rate"]

    if asks_application_count:
        metrics = ["application_count"]
        dimensions = normalize_application_count_dimensions(dimensions)
        trend_dimension = infer_application_count_dimension(context_text, dimensions)
        if asks_trend:
            dimensions = [trend_dimension] if trend_dimension else []
            if not time_range:
                time_range = {"type": "relative", "period": "recent_3_months"}
            grain = "month"
        elif trend_dimension:
            dimensions = [trend_dimension]
        filters = normalize_application_count_filters(filters)
        if asks_ranking(context_compact):
            sort = [LogicSort(field="application_count", direction="desc")]
            limit = extract_top_limit(compact) or extract_top_limit(context_compact) or limit or 10

    if high_pd_segment and not any(item.field == "risk_grade" for item in filters):
        filters.append(LogicFilter(field="risk_grade", operator="=", value="D"))
    if high_pd_segment:
        filters = [
            item.model_copy(update={"value": normalize_risk_grade_value(item.value)})
            if item.field == "risk_grade"
            else item
            for item in filters
        ]
    if high_pd_segment:
        dimensions = [item for item in dimensions if item != "risk_grade"]

    preserve_inferred_trend_window = (
        asks_application_count and asks_trend and grain in {"month", "day"}
    )
    if time_range and not has_explicit_time_range(question) and not preserve_inferred_trend_window:
        time_range = None

    allowed_sort_fields = set(metrics + dimensions)
    sort = [item for item in sort if item.field in allowed_sort_fields]

    return logic_form.model_copy(
        update={
            "metrics": metrics,
            "dimensions": dimensions,
            "filters": filters,
            "time_range": time_range,
            "grain": grain,
            "sort": sort,
            "limit": limit,
        }
    )


async def emit_node_delta(node: str, delta: str, kind: str) -> None:
    """Emit NL2LF token or reasoning deltas to the graph event stream."""
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
        # Direct unit calls run outside a LangChain parent run. Streaming is
        # best-effort there; the graph path still emits the custom event.
        return


def contextual_question_text(question: str, history: list[dict] | None = None) -> str:
    """Combine recent dialogue with current question for follow-up-sensitive rules."""
    if not history:
        return question
    recent = " ".join(str(item.get("content", "")) for item in history[-4:])
    return f"{recent} {question}"


def is_application_count_question(text: str) -> bool:
    """Detect whether the user asks for loan-application count semantics."""
    compact = text.lower().replace(" ", "")
    has_application = any(token in compact for token in ("贷款申请", "申请", "进件"))
    asks_count = any(
        token in compact
        for token in (
            "笔数",
            "多少笔",
            "几笔",
            "申请数",
            "申请量",
            "进件量",
            "进件笔数",
            "count",
        )
    )
    asks_application_ranking = has_application and any(
        token in compact for token in ("最多", "排名", "排行", "top")
    )
    correction_to_count = any(
        token in compact
        for token in ("问的是笔数", "要的是笔数", "不是金额", "为什么查出来的是金额")
    )
    return has_application and (asks_count or asks_application_ranking or correction_to_count)


def mentions_region(text: str) -> bool:
    """Detect region dimension mentions."""
    compact = text.lower().replace(" ", "")
    return any(token in compact for token in ("地区", "区域", "region"))


def mentions_product_type(text: str) -> bool:
    """Detect product-type dimension mentions."""
    compact = text.lower().replace(" ", "")
    return any(
        token in compact for token in ("产品类型", "贷款产品", "产品", "producttype", "product")
    )


def mentions_bucketed_loan(text: str) -> bool:
    """Detect loan bucket or loan-type dimension mentions."""
    compact = text.lower().replace(" ", "")
    return any(
        token in compact
        for token in ("各个贷款", "各类贷款", "不同贷款", "每种贷款", "各贷款", "各项贷款")
    )


def asks_ranking(compact_text: str) -> bool:
    """Detect ranking or TopN intent."""
    return any(token in compact_text for token in ("最多", "排名", "排行", "top", "前"))


def asks_trend_question(text: str) -> bool:
    """Detect trend or time-series intent."""
    compact = text.lower().replace(" ", "")
    return any(
        token in compact
        for token in ("变化", "趋势", "走势", "波动", "按月", "按日", "同比", "环比", "trend")
    )


def extract_top_limit(compact_text: str) -> int | None:
    """Extract numeric or Chinese TopN limits from compact text."""
    match = re.search(r"(?:top|前)(\d{1,3})", compact_text)
    if match:
        return int(match.group(1))
    chinese_digits = {
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
    match = re.search(r"前([一二两三四五六七八九十])", compact_text)
    if match:
        return chinese_digits.get(match.group(1))
    return None


def normalize_application_count_filters(filters: list[LogicFilter]) -> list[LogicFilter]:
    """Map generic filters to application-count-specific asset keys."""
    normalized = []
    for item in filters:
        if item.field == "product_type":
            normalized.append(item.model_copy(update={"field": "application_product_type"}))
        elif item.field == "risk_grade":
            normalized.append(item.model_copy(update={"field": "application_risk_grade"}))
        else:
            normalized.append(item)
    return normalized


def normalize_application_count_dimensions(dimensions: list[str]) -> list[str]:
    """Map generic dimensions to application-count-specific asset keys."""
    normalized: list[str] = []
    mapping = {
        "region": "application_region",
        "product_type": "application_product_type",
        "risk_grade": "application_risk_grade",
    }
    for item in dimensions:
        normalized.append(mapping.get(item, item))
    return normalized


def infer_application_count_dimension(text: str, dimensions: list[str]) -> str | None:
    """Choose the best application-count dimension from question text."""
    if (
        "application_product_type" in dimensions
        or mentions_product_type(text)
        or mentions_bucketed_loan(text)
    ):
        return "application_product_type"
    if "application_region" in dimensions or mentions_region(text):
        return "application_region"
    if "application_risk_grade" in dimensions:
        return "application_risk_grade"
    return None


def has_explicit_time_range(question: str) -> bool:
    """Return true when the question explicitly states a time window."""
    return bool(
        re.search(r"\d{4}[-年]", question)
        or any(
            token in question
            for token in (
                "本月",
                "这个月",
                "当月",
                "上月",
                "上个月",
                "近",
                "最近",
                "今年",
                "去年",
                "今天",
                "昨日",
                "昨天",
            )
        )
    )


def normalize_risk_grade_value(value):
    """Normalize risk-grade synonyms to configured grade values."""
    text = str(value).strip().lower()
    if text in {"high", "高", "高风险", "d", "4"}:
        return "D"
    if text in {"medium_high", "较高", "中高", "c", "3"}:
        return "C"
    if text in {"medium", "中", "b", "2"}:
        return "B"
    if text in {"low", "低", "a", "1"}:
        return "A"
    return value


def build_runtime_context(runtime: dict) -> str:
    """Serialize the semantic runtime subset used by the NL2LF prompt."""
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
        {
            "rule_key": item.get("rule_key"),
            "name": item.get("name"),
            "description": item.get("description"),
        }
        for item in runtime.get("rules", [])
    ]
    return json.dumps(
        {"metrics": metrics, "dimensions_and_filters": dimensions, "rules": rules},
        ensure_ascii=False,
    )


def build_user_prompt(
    question: str, history: list[dict], original_question: str | None = None
) -> str:
    """Build the user message for NL2LF from history and enhanced question."""
    if not history:
        if original_question and original_question != question:
            return f"原始问题: {original_question}\n语义增强后的问题: {question}"
        return question
    recent = []
    for item in history[-6:]:
        role = "用户" if item.get("role") == "user" else "助手"
        recent.append(f"{role}: {item.get('content', '')}")
    current = f"当前问题: {question}"
    if original_question and original_question != question:
        current = f"原始问题: {original_question}\n语义增强后的问题: {question}"
    return "对话历史:\n" + "\n".join(recent) + f"\n\n{current}"


def parse_logic_form(response: str) -> LogicForm:
    """Parse a LogicForm JSON response from model output."""
    text = response.strip()
    if "```" in text:
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:].strip()
    return LogicForm(**json.loads(text))


def fallback_logic_form(question: str) -> LogicForm:
    """Produce a deterministic LogicForm when model parsing fails."""
    normalized = question.lower()
    compact = normalized.replace(" ", "")
    filters = []
    dimensions = []
    metrics = ["outstanding_balance"]
    sort = []
    limit = None
    time_range = None
    grain = None

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

    if is_application_count_question(question):
        metrics = ["application_count"]
        dimension = infer_application_count_dimension(question, dimensions)
        if asks_trend_question(question):
            dimensions = [dimension] if dimension else []
            grain = "month"
            if not time_range:
                time_range = {"type": "relative", "period": "recent_3_months"}
        elif dimension:
            dimensions = [dimension]
        sort = (
            [{"field": "application_count", "direction": "desc"}] if asks_ranking(compact) else []
        )
        limit = extract_top_limit(compact) or limit
        filters = [
            {
                **item,
                "field": "application_product_type"
                if item.get("field") == "product_type"
                else item.get("field"),
            }
            for item in filters
        ]
    elif "催收" in question and "回收率" in question:
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
        grain=grain,
        sort=sort,
        limit=limit,
    )
