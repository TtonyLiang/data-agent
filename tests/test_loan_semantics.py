from app.agent.nodes.nl2lf_generate import fallback_logic_form
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
from scripts import seed_loan_semantic_runtime as seed


def build_runtime() -> SemanticRuntime:
    payload = seed.load_semantic_file()
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


def test_loan_risk_semantic_file_contains_core_assets():
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
        "application_to_account",
        "account_to_repayment",
        "account_to_collection",
        "account_to_customer_risk",
    }
    assert {item.rule_key for item in runtime.rules} >= {
        "m1_plus_definition",
        "vintage_grouping",
        "default_snapshot_date",
    }


def test_seed_loan_semantic_runtime_uses_file_assets(monkeypatch):
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
    monkeypatch.setattr(seed, "get_semantic_runtime_service", lambda: fake)

    import asyncio

    result = asyncio.run(seed.seed_loan_semantic_runtime(agent_id=7, datasource_id=42))

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


def test_m1_plus_cash_loan_logic_form_compiles_to_joined_sql():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = fallback_logic_form("本月现金贷 M1+逾期率怎么算")

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
    logic_form = fallback_logic_form("按 Vintage 看放款后 MOB3 的风险表现")

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


def test_collection_recovery_rate_logic_form_compiles_with_sort():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = fallback_logic_form("各催收团队的催收回收率排名")

    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = svc.compile_logic_form(logic_form, runtime)

    assert validation.valid
    assert logic_form.metrics == ["collection_recovery_rate"]
    assert logic_form.dimensions == ["assigned_team"]
    assert "collection_case_indicator" in compiled.sql
    assert "`assigned_team` AS `assigned_team`" in compiled.sql
    assert "ORDER BY `collection_recovery_rate` DESC" in compiled.sql


def test_unknown_metric_is_rejected_before_sql_compilation():
    runtime = build_runtime()
    svc = SemanticRuntimeService()
    logic_form = LogicForm(metrics=["drop_table"], dimensions=[])

    validation = svc.validate_logic_form(logic_form, runtime)

    assert not validation.valid
    assert "未知指标: drop_table" in validation.errors
