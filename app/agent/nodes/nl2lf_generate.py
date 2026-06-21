"""NL2LF 生成节点 —— 把自然语言问题转为结构化 LogicForm。

NL2LFGenerateNode 是问数链路的核心节点,负责:
1. LLM 生成:调用大语言模型输出 JSON 格式的 LogicForm(metrics/dimensions/filters/sort/limit)。
2. 配置化后处理:从 semantic_runtime 读取 normalization 规则,做指标/维度/过滤的归一化。
3. 物理 Schema 增强:把 LogicForm 中的 asset_key 映射到物理表字段,补充缺失维度。
4. 显式指标补全:用户明确提到的指标名(如"申请金额和申请笔数")必须出现在 LogicForm 中。

LogicForm 是模型输出与确定性 SQL 编译之间的中间表示,避免让模型直接写 SQL。
"""

import json
import logging
import re
from typing import Any

from langchain_core.callbacks.manager import adispatch_custom_event

from app.agent.domain_rules import (
    canonicalize_field,
    contains_any,
    extract_top_limit as extract_configured_top_limit,
    explicitly_mentioned_metrics,
    find_logic_form_rules,
    schema_hints_from_runtime,
)
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
    relevant_tables = state.get("relevant_tables") or []
    relevant_columns = state.get("relevant_columns") or []
    likely_joins = state.get("likely_joins") or []
    schema_scope = state.get("schema_scope") or {}
    runtime_context = build_runtime_context(
        runtime,
        relevant_tables=relevant_tables,
        relevant_columns=relevant_columns,
        likely_joins=likely_joins,
        schema_scope=schema_scope,
    )
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
        logic_form = fallback_logic_form(question, runtime)
        logger.info("nl2lf fallback logic_form=%s", json_for_log(logic_form.model_dump()))

    if not logic_form.metrics:
        logic_form = fallback_logic_form(question, runtime)
        logger.info(
            "nl2lf empty metrics fallback logic_form=%s", json_for_log(logic_form.model_dump())
        )

    logic_form = normalize_logic_form(question, logic_form, history, runtime)
    logic_form = augment_logic_form_with_physical_schema(
        question,
        logic_form,
        relevant_columns,
        runtime,
    )
    logger.info("nl2lf normalized logic_form=%s", json_for_log(logic_form.model_dump()))

    result = {"logic_form": logic_form.model_dump()}
    if relevant_tables or relevant_columns or likely_joins:
        result["schema_scope"] = {
            "relevant_tables": relevant_tables,
            "relevant_columns": relevant_columns,
            "likely_joins": likely_joins,
            "schema_scope": schema_scope,
        }
    log_node_end(logger, "nl2lf_generate", result)
    return result


def normalize_logic_form(
    question: str,
    logic_form: LogicForm,
    history: list[dict] | None = None,
    runtime: dict[str, Any] | None = None,
) -> LogicForm:
    """LLM 输出后处理:应用配置化规则,归一化 LogicForm 各槽位。"""
    compact = question.lower().replace(" ", "")
    context_text = contextual_question_text(question, history)
    context_compact = context_text.lower().replace(" ", "")
    # 初始化各槽位(LLM 输出的原始值)
    metrics = list(logic_form.metrics)
    dimensions = list(logic_form.dimensions)
    filters = list(logic_form.filters)
    sort = list(logic_form.sort)
    time_range = logic_form.time_range
    limit = logic_form.limit
    grain = logic_form.grain
    initial_metrics = list(metrics)
    asks_trend = asks_trend_question(context_text)

    # 第1步:从 semantic_runtime 中匹配适用的 normalization 规则
    matched_rules = find_logic_form_rules(
        runtime,
        question,
        history_text=contextual_question_text("", history),
    )
    # 第2步:提取用户显式提及的指标(用于最终补全)
    explicit_metrics = [
        item
        for item in explicitly_mentioned_metrics(runtime, question)
        if item not in set(initial_metrics)
    ]
    preserve_inferred_trend_window = False

    # 第3步:逐条应用匹配到的规则
    for actions in matched_rules:
        # 3a:字段别名映射(如 region → application_region)
        action_aliases = {
            str(source): str(target)
            for source, target in (actions.get("field_aliases") or {}).items()
            if source and target
        }
        # 3b:指标动作(追加或替换)
        if actions.get("metrics"):
            configured_metrics = [
                str(item) for item in actions.get("metrics") or [] if str(item or "")
            ]
            metrics = (
                unique_strings([*metrics, *configured_metrics])
                if actions.get("merge_metrics")
                else configured_metrics
            )
        # 3c:维度动作(增删)
        dimensions = apply_dimension_actions(
            context_text,
            dimensions,
            actions.get("dimensions"),
        )
        # 3d:过滤条件动作(追加固定过滤 + 正则匹配过滤)
        filters = apply_filter_actions(filters, actions.get("filters"))
        filters = apply_regex_filter_actions(context_text, filters, actions.get("regex_filters"))
        # 3e:字段别名全局替换(指标/维度/过滤/排序)
        if action_aliases:
            metrics = [canonicalize_field(item, action_aliases) for item in metrics]
            dimensions = [canonicalize_field(item, action_aliases) for item in dimensions]
            filters = [
                item.model_copy(update={"field": canonicalize_field(item.field, action_aliases)})
                for item in filters
            ]
            sort = [
                item.model_copy(update={"field": canonicalize_field(item.field, action_aliases)})
                for item in sort
            ]
        # 3f:时间粒度动作
        if actions.get("grain"):
            grain = str(actions.get("grain"))
        # 3g:时间窗口动作(仅当 LLM 未输出 time_range 时才应用规则默认值)
        if actions.get("time_range") and not time_range:
            time_range = actions.get("time_range")
            preserve_inferred_trend_window = True
        # 3h:排名动作(追加排序和 TopN 限制)
        if asks_ranking(context_compact):
            sort_field = str(actions.get("sort_field") or (metrics[0] if metrics else ""))
            if sort_field:
                sort = [LogicSort(field=sort_field, direction=str(actions.get("sort_direction") or "desc"))]
            limit = (
                extract_configured_top_limit(compact)
                or extract_configured_top_limit(context_compact)
                or limit
                or actions.get("default_limit")
            )
        # 3i:移除维度动作
        if actions.get("remove_dimensions"):
            remove = set(actions.get("remove_dimensions") or [])
            dimensions = [item for item in dimensions if item not in remove]

    # 第4步:补全用户显式提及的指标
    if explicit_metrics:
        metrics = unique_strings([*metrics, *explicit_metrics])

    filters = normalize_filter_values(filters, runtime)

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


def augment_logic_form_with_physical_schema(
    question: str,
    logic_form: LogicForm,
    relevant_columns: list[dict[str, Any]] | None,
    runtime: dict[str, Any] | None = None,
) -> LogicForm:
    """Attach configured physical-schema hints so fallback can ground unresolved fields."""
    hints = schema_hints_from_runtime(runtime, question)
    if not hints:
        return logic_form
    dimensions = list(logic_form.dimensions)
    for hint in hints:
        if str(hint.get("dimension_mode") or "append") not in {"append", "replace"}:
            continue
        matched_columns = infer_schema_hint_columns(relevant_columns or [], hint)
        if not matched_columns:
            continue
        if str(hint.get("dimension_mode") or "append") == "replace":
            dimensions = matched_columns
        else:
            dimensions = unique_strings([*dimensions, *matched_columns])
    return logic_form.model_copy(update={"dimensions": dimensions})


def infer_schema_hint_columns(
    relevant_columns: list[dict[str, Any]],
    hint: dict[str, Any],
) -> list[str]:
    """Pick physical columns that match a configured schema hint."""
    terms = [str(item) for item in hint.get("column_terms") or [] if str(item or "")]
    if not terms:
        return []
    matched: list[str] = []
    for item in relevant_columns:
        column_name = str(item.get("column_name") or item.get("column") or "")
        column_comment = str(item.get("column_comment") or item.get("comment") or "")
        label = f"{column_name} {column_comment}".lower()
        if contains_any(label, terms):
            matched.append(column_name)
    return unique_strings(matched)


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


def apply_dimension_actions(
    question: str,
    current_dimensions: list[str],
    action: Any,
) -> list[str]:
    """Apply configured dimension replacement or inference actions."""
    if not isinstance(action, dict):
        return current_dimensions
    mode = str(action.get("mode") or "replace")
    values = [str(item) for item in action.get("values") or [] if str(item or "")]
    if action.get("infer_from_terms"):
        inferred = infer_configured_dimension(question, action.get("infer_from_terms") or {})
        if inferred:
            values = [inferred]
    if mode == "append":
        return unique_strings([*current_dimensions, *values])
    if mode == "replace":
        return values
    return current_dimensions


def infer_configured_dimension(question: str, candidates: dict[str, Any]) -> str | None:
    """Infer a configured dimension key from user wording."""
    for dimension, terms in candidates.items():
        if contains_any(question, [str(item) for item in terms or []]):
            return str(dimension)
    return None


def apply_filter_actions(
    current_filters: list[LogicFilter],
    configured_filters: Any,
) -> list[LogicFilter]:
    """Merge configured filters into the LogicForm filters."""
    filters = list(current_filters)
    if not isinstance(configured_filters, list):
        return filters
    existing_fields = {item.field for item in filters}
    for item in configured_filters:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "")
        if not field or field in existing_fields:
            continue
        filters.append(
            LogicFilter(
                field=field,
                operator=str(item.get("operator") or "="),
                value=item.get("value"),
            )
        )
        existing_fields.add(field)
    return filters


def apply_regex_filter_actions(
    question: str,
    current_filters: list[LogicFilter],
    regex_filters: Any,
) -> list[LogicFilter]:
    """Extract configured regex filters from the question."""
    filters = list(current_filters)
    if not isinstance(regex_filters, list):
        return filters
    existing_fields = {item.field for item in filters}
    for item in regex_filters:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "")
        pattern = str(item.get("pattern") or "")
        if not field or not pattern or field in existing_fields:
            continue
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if not match:
            continue
        group = int(item.get("group") or 1)
        value: Any = match.group(group)
        if item.get("value_type") == "int":
            value = int(value)
        filters.append(
            LogicFilter(
                field=field,
                operator=str(item.get("operator") or "="),
                value=value,
            )
        )
        existing_fields.add(field)
    return filters


def normalize_filter_values(
    filters: list[LogicFilter],
    runtime: dict[str, Any] | None,
) -> list[LogicFilter]:
    """Normalize configured filter values such as risk-grade aliases."""
    value_aliases: dict[str, dict[str, Any]] = {}
    for rule in (runtime or {}).get("rules", []) if isinstance(runtime, dict) else []:
        if rule.get("rule_type") != "normalization":
            continue
        expression = rule.get("expression") or {}
        if isinstance(expression, dict):
            for field, aliases in (expression.get("value_aliases") or {}).items():
                if isinstance(aliases, dict):
                    value_aliases[str(field)] = aliases
    normalized = []
    for item in filters:
        aliases = value_aliases.get(item.field) or {}
        key = str(item.value).strip().lower()
        value = aliases.get(key, item.value)
        normalized.append(item.model_copy(update={"value": value}))
    return normalized


def unique_strings(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def build_runtime_context(
    runtime: dict,
    *,
    relevant_tables: list[dict] | None = None,
    relevant_columns: list[dict] | None = None,
    likely_joins: list[dict] | None = None,
    schema_scope: dict | None = None,
) -> str:
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
    physical_schema = {
        "scope": schema_scope or {},
        "tables": [
            {
                "table_name": item.get("table_name") or item.get("table"),
                "table_comment": item.get("table_comment") or item.get("comment"),
                "score": item.get("score"),
                "reason": item.get("reason"),
                "column_count": item.get("column_count"),
            }
            for item in (relevant_tables or [])
        ],
        "columns": [
            {
                "table_name": item.get("table_name") or item.get("table"),
                "column_name": item.get("column_name") or item.get("column"),
                "column_comment": item.get("column_comment") or item.get("comment"),
                "data_type": item.get("data_type"),
                "score": item.get("score"),
                "reason": item.get("reason"),
            }
            for item in (relevant_columns or [])
        ],
        "joins": [
            {
                "left": item.get("left"),
                "right": item.get("right"),
                "reason": item.get("reason"),
            }
            for item in (likely_joins or [])
        ],
    }
    return json.dumps(
        {
            "metrics": metrics,
            "dimensions_and_filters": dimensions,
            "rules": rules,
            "physical_schema": physical_schema,
        },
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
    text = extract_json_object(response)
    return LogicForm(**json.loads(text))


def extract_json_object(response: str) -> str:
    text = (response or "").strip()
    if not text:
        raise ValueError("模型未返回 LogicForm JSON")
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型返回中未找到 JSON 对象")
    return text[start : end + 1]


def fallback_logic_form(question: str, runtime: dict[str, Any] | None = None) -> LogicForm:
    """Produce a minimal configured LogicForm when model parsing fails."""
    normalized = question.lower()
    compact = normalized.replace(" ", "")
    filters = []
    dimensions = []
    metrics = []
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

    for actions in find_logic_form_rules(runtime, question):
        action_aliases = {
            str(source): str(target)
            for source, target in (actions.get("field_aliases") or {}).items()
            if source and target
        }
        if actions.get("metrics"):
            configured_metrics = [
                str(item) for item in actions.get("metrics") or [] if str(item or "")
            ]
            metrics = (
                unique_strings([*metrics, *configured_metrics])
                if actions.get("merge_metrics")
                else configured_metrics
            )
        dimensions = apply_dimension_actions(question, dimensions, actions.get("dimensions"))
        configured_filters = actions.get("filters")
        filters = [
            item.model_dump()
            for item in apply_filter_actions(
                [LogicFilter(**item) for item in filters],
                configured_filters,
            )
        ]
        filters = [
            item.model_dump()
            for item in apply_regex_filter_actions(
                question,
                [LogicFilter(**item) for item in filters],
                actions.get("regex_filters"),
            )
        ]
        if action_aliases:
            metrics = [canonicalize_field(item, action_aliases) for item in metrics]
            dimensions = [canonicalize_field(item, action_aliases) for item in dimensions]
            filters = [
                {**item, "field": canonicalize_field(str(item.get("field") or ""), action_aliases)}
                for item in filters
            ]
        if actions.get("grain"):
            grain = str(actions.get("grain"))
        if actions.get("time_range") and not time_range:
            time_range = actions.get("time_range")
        if asks_ranking(compact):
            sort_field = str(actions.get("sort_field") or (metrics[0] if metrics else ""))
            if sort_field:
                sort = [{"field": sort_field, "direction": str(actions.get("sort_direction") or "desc")}]
            limit = extract_configured_top_limit(compact) or actions.get("default_limit") or limit
        if actions.get("remove_dimensions"):
            remove = set(actions.get("remove_dimensions") or [])
            dimensions = [item for item in dimensions if item not in remove]

    return LogicForm(
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        time_range=time_range,
        grain=grain,
        sort=sort,
        limit=limit,
    )
