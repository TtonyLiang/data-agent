from pathlib import Path

from app.agent.domain_rules import schema_hints_from_runtime
from app.agent.nodes import semantic_runtime_recall
from app.agent.nodes.nl2lf_generate import (
    augment_logic_form_with_physical_schema,
    build_runtime_context,
    fallback_logic_form,
    normalize_logic_form,
)
from app.agent.nodes.semantic_enhance import collect_domain_rewrites, deterministic_enhancement
from app.models.knowledge import (
    LogicForm,
    LogicFormTemplate,
    SemanticConcept,
    SemanticDomain,
    SemanticMapping,
    SemanticMetric,
    SemanticRelation,
    SemanticRule,
    SemanticRuntime,
)
from app.services.semantic_runtime import SemanticRuntimeService
from app.services.task_checkpoint_service import classify_turn_mode
from scripts import import_semantic_bundle as semantic_bundle

EXAMPLE_SEMANTIC_PATH = Path("examples/loan/semantic-domain.json")


def build_runtime() -> SemanticRuntime:
    payload = semantic_bundle.load_semantic_file(EXAMPLE_SEMANTIC_PATH)
    domain = SemanticDomain(id=1, **payload["domain"])
    return SemanticRuntime(
        domain=domain,
        concepts=[SemanticConcept(domain_id=1, **item) for item in payload["concepts"]],
        relations=[SemanticRelation(domain_id=1, **item) for item in payload["relations"]],
        metrics=[SemanticMetric(domain_id=1, **item) for item in payload["metrics"]],
        rules=[SemanticRule(domain_id=1, **item) for item in payload["rules"]],
        mappings=[SemanticMapping(domain_id=1, **item) for item in payload["mappings"]],
        templates=[LogicFormTemplate(domain_id=1, **item) for item in payload["templates"]],
    )


def build_domain_rewrites() -> list[dict]:
    runtime = build_runtime().model_dump()
    return collect_domain_rewrites(runtime.get("rules", []))


def test_loan_example_semantic_bundle_contains_core_assets():
    runtime = build_runtime()

    assert {item.concept_key for item in runtime.concepts} >= {
        "LoanApplication",
        "LoanAccount",
        "RepaymentPeriod",
        "CustomerRiskSnapshot",
        "CollectionCase",
        "CollectionStarted",
        "WriteOffConfirmed",
    }
    assert {item.metric_key for item in runtime.metrics} >= {
        "approval_rate",
        "application_count",
        "disbursement_amount",
        "outstanding_balance",
        "m1_plus_rate",
        "vintage",
        "pd",
        "dti",
        "writeoff_amount",
        "collection_recovery_rate",
    }
    assert {item.relation_key for item in runtime.relations} >= {
        "application_creates_account",
        "account_has_repayment",
        "account_has_collection_case",
        "account_has_risk_snapshot",
    }
    assert {item.rule_key for item in runtime.rules} >= {
        "m1_plus_definition",
        "vintage_grouping",
        "default_snapshot_date",
    }


def test_import_semantic_bundle_uses_explicit_example_assets(monkeypatch):
    class FakeSemanticService:
        def __init__(self):
            self.domains = []
            self.assets = []

        async def upsert_domain(self, data):
            self.domains.append(data)
            return 99

        async def upsert_asset(self, domain_id, asset_type, data):
            self.assets.append((domain_id, asset_type, data))
            return len(self.assets)

    fake = FakeSemanticService()
    monkeypatch.setattr(semantic_bundle, "get_semantic_runtime_service", lambda: fake)

    import asyncio

    result = asyncio.run(
        semantic_bundle.import_semantic_bundle(
            path=EXAMPLE_SEMANTIC_PATH,
            agent_id=7,
            datasource_id=42,
        )
    )

    assert result["semantic_domain"] == 1
    assert result["semantic_concept"] >= 18
    assert result["semantic_metric"] >= 11
    assert fake.domains[0]["agent_id"] == 7
    assert fake.domains[0]["datasource_id"] == 42
    assert {asset_type for _, asset_type, _ in fake.assets} >= {
        "concept",
        "relation",
        "metric",
        "rule",
        "mapping",
        "template",
    }


def test_semantic_runtime_recall_prefers_agent_bound_domain(monkeypatch):
    calls = []

    class FakeService:
        async def get_agent_bound_domain(self, agent_id):
            return SemanticDomain(
                id=77,
                agent_id=agent_id,
                datasource_id=42,
                domain_key="custom_loan",
                name="自定义贷款语义层",
            )

        async def build_runtime(self, **kwargs):
            calls.append(kwargs)
            return build_runtime()

    class FakeEmbedding:
        async def embed_query(self, question, agent_id=None):
            return [0.1] * 4

    class FakeVectorStore:
        def search(self, agent_id, query_vector, *, domain_id=None):
            return []

    class FakeOntologyService:
        async def build_agent_context(self, domain_id, role):
            assert domain_id == 77
            assert role == "user"
            return {
                "object_types": [
                    {"object_key": "LoanApplication", "name": "贷款申请", "properties": []}
                ],
                "link_types": [],
                "actions": [
                    {
                        "action_key": "approve_loan_application",
                        "name": "审批贷款申请",
                        "target_object_key": "LoanApplication",
                        "parameters": [],
                    }
                ],
            }

    monkeypatch.setattr(
        semantic_runtime_recall, "get_semantic_runtime_service", lambda: FakeService()
    )
    monkeypatch.setattr(semantic_runtime_recall, "get_embedding_service", lambda: FakeEmbedding())
    monkeypatch.setattr(semantic_runtime_recall, "get_vector_store", lambda: FakeVectorStore())
    monkeypatch.setattr(
        semantic_runtime_recall, "get_ontology_service", lambda: FakeOntologyService()
    )

    import asyncio

    result = asyncio.run(
        semantic_runtime_recall.semantic_runtime_recall_node(
            {
                "agent_id": 7,
                "datasource_id": 42,
                "question": "审批贷款申请进度",
            }
        )
    )

    assert calls[0]["domain_id"] == 77
    assert result["semantic_error"] is None
    assert result["semantic_runtime"]["domain"]["name"] == "贷款风控"
    assert result["ontology_evidence"]["actions"][0]["action_key"] == "approve_loan_application"


def test_m1_plus_cash_loan_logic_form_compiles_to_joined_sql():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = fallback_logic_form("本月现金贷 M1+逾期率怎么算", runtime.model_dump())

    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = svc.compile_logic_form(logic_form, runtime)

    assert validation.valid
    assert logic_form.metrics == ["m1_plus_rate"]
    assert {"field": "product_type", "operator": "=", "value": "现金贷"} in [
        item.model_dump() for item in logic_form.filters
    ]
    assert "JOIN `loan_account_indicator`" in compiled.sql
    assert "`product_type` = '现金贷'" in compiled.sql
    assert "DATE_FORMAT(CURRENT_DATE" in compiled.sql
    assert "overdue_bucket" in compiled.sql


def test_vintage_mob_logic_form_compiles_with_dimensions():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = fallback_logic_form("按 Vintage 看放款后 MOB3 的风险表现", runtime.model_dump())

    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = svc.compile_logic_form(logic_form, runtime)

    assert validation.valid
    assert logic_form.metrics == ["m1_plus_rate"]
    assert logic_form.dimensions == ["vintage", "mob"]
    assert any(item.field == "mob" and item.value == 3 for item in logic_form.filters)
    assert "`disburse_month` AS `vintage`" in compiled.sql
    assert "`mob` AS `mob`" in compiled.sql
    assert "GROUP BY" in compiled.sql


def test_pd_logic_form_allows_vintage_dimension():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = LogicForm(metrics=["pd"], dimensions=["vintage"])

    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = svc.compile_logic_form(logic_form, runtime)

    assert validation.valid
    assert "指标 pd 不支持维度: vintage" not in validation.errors
    assert "`disburse_month` AS `vintage`" in compiled.sql


def test_build_runtime_context_includes_relevant_columns():
    context = build_runtime_context(
        {"metrics": [], "mappings": [], "rules": []},
        relevant_tables=[
            {"table_name": "loan_application_indicator", "table_comment": "贷款申请审批指标表"}
        ],
        relevant_columns=[
            {
                "table_name": "loan_application_indicator",
                "column_name": "customer_age",
                "column_comment": "客户年龄",
            }
        ],
        likely_joins=[{"left": "loan_application_indicator.customer_id", "right": "customer.id"}],
        schema_scope={"mode": "semantic_guided"},
    )

    assert "customer_age" in context
    assert "客户年龄" in context
    assert "physical_schema" in context


def test_age_intent_can_attach_physical_schema_dimension():
    logic_form = LogicForm(metrics=["application_count"], dimensions=["application_product_type"])

    augmented = augment_logic_form_with_physical_schema(
        "贷款申请产品类型和客户年龄分布有什么关系",
        logic_form,
        [
            {
                "table_name": "loan_application_indicator",
                "column_name": "customer_age",
                "column_comment": "客户年龄",
            }
        ],
        build_runtime().model_dump(),
    )

    assert "customer_age" in augmented.dimensions


def test_physical_schema_dimension_requires_semantic_hint():
    logic_form = LogicForm(metrics=["application_count"], dimensions=["application_product_type"])

    augmented = augment_logic_form_with_physical_schema(
        "贷款申请产品类型和客户年龄分布有什么关系",
        logic_form,
        [
            {
                "table_name": "loan_application_indicator",
                "column_name": "customer_age",
                "column_comment": "客户年龄",
            }
        ],
        {"rules": []},
    )

    assert augmented.dimensions == ["application_product_type"]


def test_schema_hint_requires_its_match_terms():
    runtime = build_runtime().model_dump()

    assert schema_hints_from_runtime(runtime, "各催收团队催收回收率排名") == []
    hints = schema_hints_from_runtime(runtime, "按客户年龄段查看贷款申请分布")
    assert any(item.get("key") == "customer_age_dimension" for item in hints)


def test_collection_recovery_rate_logic_form_compiles_with_sort():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = fallback_logic_form("各催收团队的催收回收率排名", runtime.model_dump())

    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = svc.compile_logic_form(logic_form, runtime)

    assert validation.valid
    assert logic_form.metrics == ["collection_recovery_rate"]
    assert logic_form.dimensions == ["assigned_team"]
    assert "collection_case_indicator" in compiled.sql
    assert "`assigned_team` AS `assigned_team`" in compiled.sql
    assert "ORDER BY `collection_recovery_rate` DESC" in compiled.sql


def test_application_count_by_region_top3_logic_form_compiles_to_count():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = fallback_logic_form(
        "贷款排名前三的申请区域是什么，分别申请了多少笔", runtime.model_dump()
    )

    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = svc.compile_logic_form(logic_form, runtime)

    assert validation.valid
    assert logic_form.metrics == ["application_count"]
    assert logic_form.dimensions == ["application_region"]
    assert logic_form.sort[0].field == "application_count"
    assert logic_form.limit == 3
    assert "FROM `loan_application_indicator` t0" in compiled.sql
    assert "t0.`region` AS `application_region`" in compiled.sql
    assert "COUNT(*) AS `application_count`" in compiled.sql
    assert "ORDER BY `application_count` DESC" in compiled.sql
    assert "LIMIT 3" in compiled.sql
    assert "loan_amount" not in compiled.sql


def test_application_count_by_application_channel_uses_application_table():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    question = "根据申请渠道，分类统计当前的贷款总数"
    logic_form = fallback_logic_form(question, runtime.model_dump())

    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = svc.compile_logic_form(logic_form, runtime)

    assert validation.valid
    assert logic_form.metrics == ["application_count"]
    assert logic_form.dimensions == ["application_channel"]
    assert "FROM `loan_application_indicator` t0" in compiled.sql
    assert "t0.`channel` AS `application_channel`" in compiled.sql
    assert "JOIN `loan_account_indicator`" not in compiled.sql


def test_application_channel_alias_is_normalized_from_llm_dimension():
    runtime = build_runtime().model_dump()
    logic_form = LogicForm(
        metrics=["loan_count"],
        dimensions=["channel"],
        filters=[{"field": "current_status", "operator": "=", "value": "current"}],
    )

    normalized = normalize_logic_form(
        "根据申请渠道，分类统计当前的贷款总数",
        logic_form,
        runtime=runtime,
    )

    assert normalized.metrics == ["application_count"]
    assert normalized.dimensions == ["application_channel"]
    assert normalized.filters == []


def test_application_count_by_application_status_uses_application_table():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    question = "查看审批进度，按申请状态统计当前贷款申请数量。"
    logic_form = fallback_logic_form(question, runtime.model_dump())

    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = svc.compile_logic_form(logic_form, runtime)

    assert validation.valid
    assert logic_form.metrics == ["application_count"]
    assert logic_form.dimensions == ["application_approval_status"]
    assert "FROM `loan_application_indicator` t0" in compiled.sql
    assert "t0.`approval_status` AS `application_approval_status`" in compiled.sql
    assert "JOIN `loan_account_indicator`" not in compiled.sql


def test_application_status_alias_is_normalized_from_llm_dimension():
    runtime = build_runtime().model_dump()
    logic_form = LogicForm(
        metrics=["loan_count"],
        dimensions=["approval_status"],
        filters=[{"field": "current_status", "operator": "=", "value": "current"}],
    )

    normalized = normalize_logic_form(
        "查看审批进度，按申请状态统计当前贷款申请数量。",
        logic_form,
        runtime=runtime,
    )

    assert normalized.metrics == ["application_count"]
    assert normalized.dimensions == ["application_approval_status"]
    assert normalized.filters == []


def test_application_count_followup_corrects_amount_metric_with_history():
    logic_form = LogicForm(
        metrics=["disbursement_amount"],
        dimensions=["region"],
        sort=[{"field": "disbursement_amount", "direction": "desc"}],
        limit=3,
    )
    history = [
        {"role": "user", "content": "贷款排名前三的申请区域是什么，分别申请了多少笔"},
        {"role": "assistant", "content": "按地区返回了放款金额前三。"},
    ]

    normalized = normalize_logic_form(
        "我问的是笔数，为什么查出来的是金额",
        logic_form,
        history,
        build_runtime().model_dump(),
    )

    assert normalized.metrics == ["application_count"]
    assert normalized.dimensions == ["application_region"]
    assert normalized.sort[0].field == "application_count"
    assert normalized.limit == 3


def test_application_count_followup_top5_overrides_previous_top3():
    logic_form = LogicForm(
        metrics=["application_count"],
        dimensions=["application_region"],
        sort=[{"field": "application_count", "direction": "desc"}],
        limit=3,
    )
    history = [
        {"role": "user", "content": "贷款排名前三的申请区域是什么，分别申请了多少笔"},
        {"role": "assistant", "content": "前三个申请区域分别是华南、东北、西北。"},
    ]

    normalized = normalize_logic_form("前五呢", logic_form, history, build_runtime().model_dump())

    assert normalized.metrics == ["application_count"]
    assert normalized.dimensions == ["application_region"]
    assert normalized.sort[0].field == "application_count"
    assert normalized.limit == 5


def test_semantic_enhancement_resolves_top5_followup():
    history = [
        {"role": "user", "content": "贷款排名前三的申请区域是什么，分别申请了多少笔"},
        {"role": "assistant", "content": "前三个申请区域分别是华南、东北、西北。"},
    ]

    result = deterministic_enhancement("前五呢", history)

    assert result is not None
    assert result["rewrite_type"] == "followup_resolution"
    assert "前五" in result["enhanced_question"]
    assert "申请区域" in result["enhanced_question"]
    assert "多少笔" in result["enhanced_question"]


def test_semantic_enhancement_treats_previous_months_as_time_not_topn():
    history = [{"role": "user", "content": "查询贷款账户总余额。"}]

    result = deterministic_enhancement("换成前两个月", history)

    assert result is not None
    assert result["enhanced_question"] == "查询贷款账户总余额，时间范围改为前两个月。"
    assert result["preserved_constraints"] == ["时间范围=前两个月", "延续上一轮业务口径"]
    assert not any(item.startswith("TopN=") for item in result["preserved_constraints"])


def test_semantic_enhancement_clarifies_application_count_region_question():
    result = deterministic_enhancement(
        "贷款排名前三的申请区域是什么，分别申请了多少笔",
        [],
        build_domain_rewrites(),
        build_runtime().model_dump(),
    )

    assert result is not None
    assert "申请笔数" in result["enhanced_question"]
    assert "申请区域" in result["enhanced_question"]
    assert "金额" not in result["enhanced_question"]


def test_semantic_enhancement_clarifies_application_channel_count_question():
    result = deterministic_enhancement(
        "根据申请渠道，分类统计当前的贷款总数",
        [],
        build_domain_rewrites(),
        build_runtime().model_dump(),
    )

    assert result is not None
    assert result["enhanced_question"] == (
        "查询当前已采集的贷款申请数据，按申请渠道分组统计申请笔数。"
    )


def test_semantic_enhancement_clarifies_application_status_count_question():
    result = deterministic_enhancement(
        "查看审批进度，按申请状态统计当前贷款申请数量。",
        [],
        build_domain_rewrites(),
        build_runtime().model_dump(),
    )

    assert result is not None
    assert result["enhanced_question"] == (
        "查询当前已采集的贷款申请数据，按申请状态分组统计申请笔数。"
    )


def test_application_channel_followup_reuses_previous_count_metric():
    runtime = build_runtime().model_dump()
    previous = {
        "task_id": "task-application-status",
        "question": "查看审批进度，按申请状态统计当前贷款申请数量。",
        "enhanced_question": "查询当前已采集的贷款申请数据，按申请状态分组统计申请笔数。",
        "task_status": "completed",
        "sql_executed": True,
    }
    question = "按申请渠道统计"
    history = [{"role": "user", "content": previous["question"]}]
    rewrites = build_domain_rewrites()

    assert classify_turn_mode(question, previous) == "refine"
    enhanced = deterministic_enhancement(question, history, rewrites, runtime)
    assert enhanced is not None
    assert "按申请渠道分组" in enhanced["enhanced_question"]

    normalized = normalize_logic_form(
        question,
        LogicForm(metrics=[], dimensions=[]),
        history,
        runtime,
    )
    assert normalized.metrics == ["application_count"]
    assert normalized.dimensions == ["application_channel"]


def test_semantic_enhancement_clarifies_application_count_trend_question():
    result = deterministic_enhancement(
        "各个贷款申请量变化",
        [],
        build_domain_rewrites(),
        build_runtime().model_dump(),
    )

    assert result is not None
    assert result["enhanced_question"] == "查询贷款申请按月份统计各贷款产品类型的申请笔数变化趋势。"


def test_semantic_enhancement_preserves_explicit_balance_metric():
    result = deterministic_enhancement(
        "贷款排名前三的申请区域是什么，分别申请了多少笔，余额是多少",
        [],
        build_domain_rewrites(),
        build_runtime().model_dump(),
    )

    assert result is not None
    assert "申请笔数" in result["enhanced_question"]
    assert "余额" in result["enhanced_question"]
    assert "额外指标：余额" in result["preserved_constraints"]


def test_normalize_logic_form_preserves_explicit_balance_metric():
    runtime = build_runtime().model_dump()
    logic_form = LogicForm(
        metrics=["application_count"],
        dimensions=["application_region"],
        sort=[{"field": "application_count", "direction": "desc"}],
        limit=3,
    )

    normalized = normalize_logic_form(
        "贷款排名前三的申请区域是什么，分别申请了多少笔，余额是多少",
        logic_form,
        [],
        runtime,
    )

    assert normalized.metrics == ["application_count", "outstanding_balance"]
    assert normalized.dimensions == ["application_region"]


def test_application_count_trend_logic_form_compiles_to_monthly_sql():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = fallback_logic_form("各个贷款申请量变化", runtime.model_dump())

    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = svc.compile_logic_form(logic_form, runtime)

    assert validation.valid
    assert logic_form.metrics == ["application_count"]
    assert logic_form.dimensions == ["application_product_type"]
    assert logic_form.grain == "month"
    assert logic_form.time_range is not None
    assert "DATE_FORMAT(t0.`apply_date`, '%Y-%m') AS `month`" in compiled.sql
    assert "t0.`product_type` AS `application_product_type`" in compiled.sql
    assert "COUNT(*) AS `application_count`" in compiled.sql
    assert "GROUP BY DATE_FORMAT(t0.`apply_date`, '%Y-%m'), t0.`product_type`" in compiled.sql
    assert "ORDER BY `month` ASC, `application_product_type` ASC" in compiled.sql


def test_application_count_trend_normalize_keeps_default_recent_window():
    logic_form = LogicForm(
        metrics=["application_count"],
        dimensions=[],
        filters=[],
        time_range=None,
        grain=None,
        sort=[],
        limit=None,
    )

    normalized = normalize_logic_form(
        "各个贷款申请量变化趋势", logic_form, runtime=build_runtime().model_dump()
    )

    assert normalized.metrics == ["application_count"]
    assert normalized.dimensions == ["application_product_type"]
    assert normalized.grain == "month"
    assert normalized.time_range == {"type": "relative", "period": "recent_3_months"}


def test_high_pd_balance_and_overdue_query_compiles_cross_table_metrics():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = LogicForm(
        metrics=["pd", "outstanding_balance", "m1_plus_rate"],
        filters=[{"field": "risk_grade", "operator": "=", "value": "D"}],
        sort=[{"field": "pd", "direction": "desc"}],
    )

    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = svc.compile_logic_form(logic_form, runtime)

    assert validation.valid
    assert "CROSS JOIN" in compiled.sql
    assert "loan_application_indicator" in compiled.sql
    assert "loan_account_indicator" in compiled.sql
    assert "loan_repayment_period_indicator" in compiled.sql
    assert "`risk_grade_at_origination` = 'D'" in compiled.sql
    assert "AS `pd`" in compiled.sql
    assert "AS `outstanding_balance`" in compiled.sql
    assert "AS `m1_plus_rate`" in compiled.sql
    assert any("已忽略 sort" in warning for warning in compiled.warnings)


def test_high_pd_balance_and_overdue_logic_form_is_normalized():
    logic_form = LogicForm(
        metrics=["pd"],
        dimensions=["risk_grade"],
        filters=[],
        time_range={"type": "relative", "period": "this_month"},
        sort=[{"field": "pd", "direction": "desc"}],
    )

    normalized = normalize_logic_form(
        "高 PD 客户的余额和逾期情况", logic_form, runtime=build_runtime().model_dump()
    )

    assert normalized.metrics == ["outstanding_balance", "m1_plus_rate"]
    assert normalized.dimensions == []
    assert any(item.field == "risk_grade" and item.value == "D" for item in normalized.filters)
    assert normalized.time_range is None
    assert normalized.sort == []


def test_unknown_metric_is_rejected_before_sql_compilation():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = LogicForm(metrics=["drop_table"], dimensions=[])

    validation = svc.validate_logic_form(logic_form, runtime)

    assert not validation.valid
    assert "未知指标: drop_table" in validation.errors


def test_fallback_without_domain_runtime_does_not_guess_loan_metric():
    logic_form = fallback_logic_form("帮我看一下今天的销售情况")

    assert logic_form.metrics == []
    assert "outstanding_balance" not in logic_form.metrics
