"""领域规则工具 —— 配置化语义匹配、意图判定与辅助召回。

本模块提供一套纯函数,用于从已加载的 semantic_runtime 字典中读取配置化规则,
并执行语义匹配、意图判定、字段归一化、TopN 提取、中文数字转换等辅助逻辑。
它不依赖数据库或模型调用,被以下节点直接调用:

- ``semantic_enhance``:``contains_any`` / ``extract_top_limit`` / ``GENERIC_*_TERMS``
- ``nl2lf_generate``:``find_logic_form_rules`` / ``canonicalize_field`` /
  ``schema_hints_from_runtime``
- ``schema_recall``:``business_groups_from_runtime`` / ``recall_profiles_from_runtime``
- ``semantic_runtime_recall``:``recall_profiles_from_runtime``

核心概念:
- ``GENERIC_*_TERMS``:通用意图词表,用于粗粒度判定用户问题是否属于某类意图
  (笔数/金额/排名/趋势/区域/产品),不需要配置化规则即可工作。
- ``_rule_matches``:规则匹配器,同时使用通用词表和配置化词表,
  通过 any/all/none/intents 条件组合实现灵活的意图判定。
- ``metric_terms_are_negated``:否定词检测,用于在"不是金额"等表述下排除指标。
"""

from __future__ import annotations

import re
from typing import Any

# ============================================================
# 通用意图词表 —— 覆盖最常见的业务问法关键词
# 用途:在 _rule_matches 中作为 intents 对应的兜底词表,
#       以及 semantic_enhance/nl2lf_generate 中的粗粒度意图判定。
# ============================================================

# 笔数/数量意图词表 —— 用户问"有多少笔""总数""贷款总量"等
GENERIC_COUNT_TERMS = (
    "笔数",
    "多少笔",
    "几笔",
    "数量",
    "总数",
    "总量",
    "总计",
    "多少个",
    "件数",
    "次数",
    "count",
)
# 金额/余额意图词表 —— 用户问"金额多少""余额排名"等
GENERIC_AMOUNT_TERMS = ("金额", "余额", "amount", "balance")
# 排名/TopN 意图词表 —— 用户问"最多""排名前""Top10"等
GENERIC_RANKING_TERMS = ("最多", "排名", "排行", "top", "前", "最高", "最低")
# 趋势/时间序列意图词表 —— 用户问"变化趋势""按月""同比""走势"等
GENERIC_TREND_TERMS = ("变化", "趋势", "走势", "波动", "按月", "按日", "同比", "环比", "trend")
# 区域/地区意图词表 —— 用户问"各区域""按地区"等
GENERIC_REGION_TERMS = ("区域", "地区", "region", "area")
# 产品类型意图词表 —— 用户问"按产品类型""各产品"等
GENERIC_PRODUCT_TERMS = ("产品类型", "产品", "producttype", "product")


# ============================================================
# 文本处理工具
# ============================================================


def compact_text(text: str) -> str:
    """去除空白并转小写,用于中文/英文混合关键词匹配。

    例如 "Top 10" 和 "top10" 经 compact 后一致,简化匹配逻辑。
    """
    return re.sub(r"\s+", "", str(text or "")).lower()


def contains_any(text: str, values: list[str] | tuple[str, ...]) -> bool:
    """判断 text 中是否包含 values 中的任何一个关键词。

    用于规则匹配、意图判定、向量召回词表命中等场景。
    空字符串或 None 会被跳过,避免误命中。
    """
    compact = compact_text(text)
    return any(str(value or "").lower() in compact for value in values if str(value or ""))


# ============================================================
# TopN 提取与中文数字转换
# 用于从用户问题中提取"前10""前五""Top3"等排名限制。
# ============================================================


def extract_top_limit(text: str) -> int | None:
    """从用户文本中提取 TopN 数值,支持阿拉伯数字和中文数字。

    匹配规则:
    - "top5"/"前5" → 5
    - "前五"/"前十" → 5/10
    - 不区分大小写
    """
    compact = strip_temporal_windows(compact_text(text))
    # 先尝试阿拉伯数字:top5 或 前5
    match = re.search(r"(?:top|前)(\d{1,3})", compact, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    # 再尝试中文数字:前五、前十、前十二
    match = re.search(r"前([一二两三四五六七八九十]+)", compact)
    if match:
        return chinese_number_to_int(match.group(1))
    return None


def strip_temporal_windows(text: str) -> str:
    """Remove time windows such as ``前两个月`` before parsing ranking limits."""
    return re.sub(
        r"前(?:\d{1,3}|[一二两三四五六七八九十]+)(?:个)?(?:月|周|天|季度|年)",
        "",
        str(text or ""),
    )


def chinese_number_to_int(text: str) -> int | None:
    """将小中文数字(一~十二)转换为整数。

    支持:
    - 单字:一~十
    - 十 + X:十一、十二
    - X + 十:二十、三十
    - X + 十 + Y:二十一、三十五

    超过范围(如"一百")返回 None。
    """
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
    # 单字:一~十
    if text in digits:
        return digits[text]
    # 十X:十一、十二
    if text.startswith("十") and len(text) == 2:
        return 10 + digits.get(text[1], 0)
    # X十:二十、三十
    if text.endswith("十") and len(text) == 2:
        return digits.get(text[0], 0) * 10
    # X十Y:二十一、三十五
    if "十" in text and len(text) == 3:
        left, right = text.split("十", 1)
        return digits.get(left, 0) * 10 + digits.get(right, 0)
    return None


# ============================================================
# 语义资产查询工具 —— 从 runtime 字典中提取配置化规则
# ============================================================


def semantic_rules(runtime: dict[str, Any] | None, rule_type: str | None = None) -> list[dict]:
    """从已加载的 runtime payload 中提取语义规则列表。

    参数:
        runtime:SemanticRuntime.model_dump() 产出的字典
        rule_type:可选过滤,如 'rewrite'/'normalization'/'logic_form'/'recall'
    """
    if not isinstance(runtime, dict):
        return []
    rules = [item for item in runtime.get("rules", []) or [] if isinstance(item, dict)]
    if rule_type:
        return [item for item in rules if item.get("rule_type") == rule_type]
    return rules


def field_aliases(runtime: dict[str, Any] | None) -> dict[str, str]:
    """从 normalization 类型规则中构建字段别名映射。

    用途:把通用字段名映射为语义层配置的规范字段名,
    例如 {'region': 'application_region'}。
    """
    aliases: dict[str, str] = {}
    for rule in semantic_rules(runtime, "normalization"):
        expression = rule.get("expression") or {}
        if not isinstance(expression, dict):
            continue
        for source, target in (expression.get("field_aliases") or {}).items():
            if source and target:
                aliases[str(source)] = str(target)
    return aliases


def canonicalize_field(field: str, aliases: dict[str, str]) -> str:
    """把通用字段名映射为领域规范字段名;无映射时原样返回。"""
    return aliases.get(field, field)


def metric_by_key(runtime: dict[str, Any] | None) -> dict[str, dict]:
    """把 runtime.metrics 按 metric_key 索引,方便按 key 直接查找。"""
    if not isinstance(runtime, dict):
        return {}
    return {
        str(item.get("metric_key")): item
        for item in runtime.get("metrics", []) or []
        if isinstance(item, dict) and item.get("metric_key")
    }


# ============================================================
# 指标显式提及检测 —— 用于 LogicForm 后处理补全
# 当用户明确提到某个指标名/同义词时,确保 LogicForm 包含它。
# ============================================================


def explicitly_mentioned_metrics(runtime: dict[str, Any] | None, text: str) -> list[str]:
    """识别用户文本中显式提及的语义指标(按 metric_key / name / 同义词匹配)。

    用于 LogicForm 后处理:如果用户明确问了"申请金额和申请笔数",
    但模型只输出了申请金额,此函数能识别出还缺申请笔数,然后补上。
    """
    if not isinstance(runtime, dict):
        return []
    compact = compact_text(text)
    if not compact:
        return []
    matches: list[str] = []
    for metric in runtime.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        metric_key = str(metric.get("metric_key") or "")
        if not metric_key:
            continue
        terms = metric_terms(metric)
        # 排除否定表述:用户说"不是金额"时不应该命中"金额"指标
        if metric_terms_are_negated(terms, compact):
            continue
        if contains_any(compact, [str(term) for term in terms if str(term or "").strip()]):
            matches.append(metric_key)
    return _unique_strings(matches)


def metric_terms(metric: dict[str, Any]) -> list[str]:
    """提取一个指标的全部可搜索词:metric_key + name + synonyms。"""
    return [
        str(metric.get("metric_key") or ""),
        str(metric.get("name") or ""),
        *[str(item) for item in metric.get("synonyms") or []],
    ]


def metric_terms_are_negated(terms: list[str], compact: str) -> bool:
    """检测用户文本中是否对任意指标词存在否定前缀。

    例如"不是金额""别查余额"会排除"金额""余额"指标,避免误命中。
    否定词列表覆盖常见口语化表达:不是/非/不要/无需/不看/不查/别查/别看。
    """
    clean_terms = [compact_text(term) for term in terms if str(term or "").strip()]
    negation_prefixes = ("不是", "非", "不要", "无需", "不看", "不查", "别查", "别看")
    return any(
        f"{prefix}{term}" in compact
        for term in clean_terms
        for prefix in negation_prefixes
    )


# ============================================================
# 映射与标签工具
# ============================================================


def mapping_by_key(runtime: dict[str, Any] | None) -> dict[str, dict]:
    """把 runtime.mappings 按 asset_key 索引。"""
    if not isinstance(runtime, dict):
        return {}
    return {
        str(item.get("asset_key")): item
        for item in runtime.get("mappings", []) or []
        if isinstance(item, dict) and item.get("asset_key")
    }


def display_label_map(runtime: dict[str, Any] | None) -> dict[str, str]:
    """从 runtime 中提取指标和映射的展示标签,用于前端展示或日志。"""
    labels: dict[str, str] = {}
    if not isinstance(runtime, dict):
        return labels
    for metric in runtime.get("metrics", []) or []:
        key = str(metric.get("metric_key") or "")
        name = str(metric.get("name") or "")
        if key and name:
            labels[key] = name
    for mapping in runtime.get("mappings", []) or []:
        key = str(mapping.get("asset_key") or "")
        name = str(mapping.get("name") or "")
        if key and name:
            labels[key] = name
    return labels


# ============================================================
# 配置化 LogicForm 规则匹配 —— 用于 nl2lf_generate 节点的后处理
# 从 normalization 类型规则中匹配 logic_form.actions,
# 决定指标、维度、过滤、排序等槽位的增删替换。
# ============================================================


def find_logic_form_rules(
    runtime: dict[str, Any] | None,
    question: str,
    *,
    history_text: str = "",
) -> list[dict[str, Any]]:
    """匹配当前问题适用的 LogicForm 归一化规则。

    遍历 normalization 类型规则,若其 match 条件命中当前问题,
    则返回对应的 logic_form.actions,供调用方(如 nl2lf_generate)应用。
    """
    text = f"{history_text} {question}"
    matched: list[dict[str, Any]] = []
    for rule in semantic_rules(runtime, "normalization"):
        expression = rule.get("expression") or {}
        if not isinstance(expression, dict):
            continue
        actions = expression.get("logic_form") or {}
        if not isinstance(actions, dict):
            continue
        if _rule_matches(expression.get("match") or {}, text):
            matched.append(actions)
    return matched


# ============================================================
# 召回类规则匹配 —— 用于 schema_recall 节点
# 从 recall 类型规则中提取业务分组、schema hints、recall profiles,
# 用于数据定位阶段的候选表打分加权。
# ============================================================


def business_groups_from_runtime(
    runtime: dict[str, Any] | None,
    question: str,
) -> list[dict[str, Any]]:
    """从 recall 规则中匹配适用的业务分组,用于 schema_recall 候选表加权。

    例如配置了"贷款"分组,当用户问"贷款申请"时,贷款相关的表会获得额外加分。
    """
    groups: list[dict[str, Any]] = []
    for rule in semantic_rules(runtime, "recall"):
        expression = rule.get("expression") or {}
        if not isinstance(expression, dict):
            continue
        for group in expression.get("business_groups") or []:
            if not isinstance(group, dict):
                continue
            aliases = [str(item) for item in group.get("aliases") or []]
            if contains_any(question, aliases):
                groups.append(group)
    return _unique_groups(groups)


def schema_hints_from_runtime(
    runtime: dict[str, Any] | None,
    question: str,
) -> list[dict[str, Any]]:
    """从 recall 规则中提取与当前问题匹配的物理 schema 提示。

    schema_hints 用于给 NL2LF 和 NL2SQL 兜底提供额外的字段候选,
    例如当用户提到"风险等级"时,把 risk_level 相关字段推入候选。
    """
    hints: list[dict[str, Any]] = []
    for rule in semantic_rules(runtime, "recall"):
        expression = rule.get("expression") or {}
        if not isinstance(expression, dict):
            continue
        for hint in expression.get("schema_hints") or []:
            if not isinstance(hint, dict):
                continue
            match = hint.get("match")
            # 只有存在实际条件时才走规则匹配器；空 match 不能代表无条件命中。
            if isinstance(match, dict) and match:
                if _rule_matches(match, question):
                    hints.append(hint)
                continue
            # match_terms 为简单关键词列表时走 contains_any
            match_terms = [str(item) for item in hint.get("match_terms") or []]
            if match_terms and contains_any(question, match_terms):
                hints.append(hint)
    return _unique_groups(hints)


def recall_profiles_from_runtime(
    runtime: dict[str, Any] | None,
    question: str,
) -> list[dict[str, Any]]:
    """从 recall 规则中提取与当前问题匹配的召回画像(profiles)。

    profiles 用于在 schema_recall 阶段对候选表/字段进行额外加权或排除,
    例如"贷款风险"问题时优先加权含 risk 字段的表。
    """
    profiles: list[dict[str, Any]] = []
    for rule in semantic_rules(runtime, "recall"):
        expression = rule.get("expression") or {}
        if not isinstance(expression, dict):
            continue
        for profile in expression.get("recall_profiles") or []:
            if not isinstance(profile, dict):
                continue
            match = profile.get("match") or {}
            if isinstance(match, dict) and match:
                if _rule_matches(match, question):
                    profiles.append(profile)
                continue
            match_terms = [str(item) for item in profile.get("match_terms") or []]
            if match_terms and contains_any(question, match_terms):
                profiles.append(profile)
    return _unique_groups(profiles)


# ============================================================
# 规则匹配器 —— 通用条件组合引擎
# 支持 any/all/none/intents 四种条件组合方式。
# ============================================================


def _rule_matches(match: dict[str, Any], text: str) -> bool:
    """评估 declarative 规则的 match 条件。

    match 支持 4 种条件组合,全部满足才返回 True:
    - ``any``:文本中包含任意一个词则满足(列表)
    - ``all``:文本中包含所有词才满足(列表)
    - ``none``:文本中不能包含任意一个词(列表)
    - ``intents``:文本中必须匹配对应意图的词表(字符串列表)
      支持的 intent 类型:count/amount/ranking/trend/region/product

    当 match 为空 dict 或 None 时返回 False(无条件不匹配)。
    """
    if not isinstance(match, dict):
        return False

    # --- 基础关键词条件 ---
    any_terms = match.get("any") or []      # 任一命中即可
    all_terms = match.get("all") or []      # 全部必须命中
    none_terms = match.get("none") or []    # 任一命中则排除

    if any_terms and not contains_any(text, any_terms):
        return False
    if all_terms and not all(contains_any(text, [term]) for term in all_terms):
        return False
    if none_terms and contains_any(text, none_terms):
        return False

    # --- 意图条件 ---
    # intents 列出需要命中的意图类型,每个意图对应一个词表:
    # 通用词表(GENERIC_*_TERMS) + 规则配置化词表(match.xxx_terms)。
    intents = set(match.get("intents") or [])

    # 组装每个意图的词表:通用词表 + 配置化扩展词
    count_terms = [*GENERIC_COUNT_TERMS, *(match.get("count_terms") or [])]
    amount_terms = [*GENERIC_AMOUNT_TERMS, *(match.get("amount_terms") or [])]
    ranking_terms = [*GENERIC_RANKING_TERMS, *(match.get("ranking_terms") or [])]
    trend_terms = [*GENERIC_TREND_TERMS, *(match.get("trend_terms") or [])]
    region_terms = [*GENERIC_REGION_TERMS, *(match.get("region_terms") or [])]
    product_terms = [*GENERIC_PRODUCT_TERMS, *(match.get("product_terms") or [])]

    # 各意图判定:只在意图被声明时才检查,未声明则跳过(不阻断)
    if "count" in intents and not contains_any(text, count_terms):
        return False
    if "amount" in intents and not contains_any(text, amount_terms):
        return False
    if "ranking" in intents and not contains_any(text, ranking_terms):
        return False
    if "trend" in intents and not contains_any(text, trend_terms):
        return False
    if "region" in intents and not contains_any(text, region_terms):
        return False
    if "product" in intents and not contains_any(text, product_terms):
        return False

    return True


# ============================================================
# 内部去重工具
# ============================================================


def _unique_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 key/label 去重,保留首次出现的顺序。"""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for group in groups:
        key = str(group.get("key") or group.get("label") or "")
        if key and key not in seen:
            seen.add(key)
            result.append(group)
    return result


def _unique_strings(values: list[str]) -> list[str]:
    """按字符串去重,保留首次出现的顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
