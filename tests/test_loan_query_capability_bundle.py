import asyncio
import json
from pathlib import Path

from app.models.knowledge import (
    LogicFormTemplate,
    SemanticConcept,
    SemanticDomain,
    SemanticMapping,
    SemanticMetric,
    SemanticRelation,
    SemanticRule,
    SemanticRuntime,
)
from app.services.ontology_semantic_bridge import build_ontology_semantic_bridge
from app.services.query_context import build_query_context
from app.services.semantic_runtime import SemanticRuntimeService
from scripts import import_semantic_bundle as semantic_bundle

ROOT = Path(__file__).parents[1]
SEMANTIC_PATH = ROOT / "examples/loan/semantic-domain.json"
ONTOLOGY_PATH = ROOT / "examples/loan/ontology-bundle.json"

EXPECTED_METRIC_OBJECTS = {
    "approval_rate": "LoanApplication",
    "application_count": "LoanApplication",
    "disbursement_amount": "LoanAccount",
    "outstanding_balance": "LoanAccount",
    "mob": "LoanAccount",
    "dpd": "LoanAccount",
    "vintage": "LoanAccount",
    "writeoff_amount": "LoanAccount",
    "m1_plus_rate": "RepaymentPeriod",
    "pd": "LoanApplication",
    "dti": "CustomerRiskSnapshot",
    "collection_recovery_rate": "CollectionCase",
}

EXPECTED_RELATION_KEYS = {
    "application_creates_account",
    "account_has_repayment",
    "account_has_collection_case",
    "account_has_risk_snapshot",
}

CUSTOMER_LINK_KEYS = {"customer_has_application", "customer_has_account"}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime() -> SemanticRuntime:
    payload = _load_json(SEMANTIC_PATH)
    return SemanticRuntime(
        domain=SemanticDomain(id=1, **payload["domain"]),
        concepts=[SemanticConcept(domain_id=1, **item) for item in payload["concepts"]],
        relations=[SemanticRelation(domain_id=1, **item) for item in payload["relations"]],
        metrics=[SemanticMetric(domain_id=1, **item) for item in payload["metrics"]],
        rules=[SemanticRule(domain_id=1, **item) for item in payload["rules"]],
        mappings=[SemanticMapping(domain_id=1, **item) for item in payload["mappings"]],
        templates=[
            LogicFormTemplate(domain_id=1, **item) for item in payload["templates"]
        ],
    )


def _ontology_context() -> dict:
    payload = _load_json(ONTOLOGY_PATH)
    return {
        "domain": payload["domain"],
        "object_types": payload["object_types"],
        "link_types": payload["link_types"],
        "actions": payload["action_types"],
    }


def test_loan_bundle_explicit_metric_ownership_builds_object_capabilities():
    runtime = _runtime()
    ontology = _ontology_context()

    bridge = build_ontology_semantic_bridge(ontology, runtime)
    metric_objects = {
        metric_key: bridge["metrics"][metric_key]["object_keys"]
        for metric_key in EXPECTED_METRIC_OBJECTS
    }

    assert metric_objects == {
        metric_key: [object_key]
        for metric_key, object_key in EXPECTED_METRIC_OBJECTS.items()
    }

    query_context = build_query_context("查看贷款指标", runtime, ontology)
    capabilities = {
        item["target_object"]: item for item in query_context["query_capabilities"]
    }
    expected_objects = set(EXPECTED_METRIC_OBJECTS.values())

    assert expected_objects <= set(capabilities)
    for object_key in expected_objects:
        expected_metrics = {
            metric_key
            for metric_key, target_object in EXPECTED_METRIC_OBJECTS.items()
            if target_object == object_key
        }
        assert set(capabilities[object_key]["supported_metrics"]) == expected_metrics


def test_loan_bundle_aligns_four_links_and_warns_for_unmapped_customer_links():
    bridge = build_ontology_semantic_bridge(_ontology_context(), _runtime())

    for link_key in EXPECTED_RELATION_KEYS:
        relation = bridge["relations"][link_key]
        assert relation["linked"] is True
        assert relation["relation_key"] == link_key
        assert relation["join_path"]

    for link_key in CUSTOMER_LINK_KEYS:
        relation = bridge["relations"][link_key]
        assert relation["linked"] is False
        assert relation["join_path"] == []

    missing_link_warnings = {
        item["details"]["link_key"]
        for item in bridge["warnings"]
        if item["code"] == "link_semantic_relation_missing"
    }
    assert CUSTOMER_LINK_KEYS <= missing_link_warnings


def test_import_and_runtime_round_trip_preserves_metric_metadata(monkeypatch):
    class FakeSemanticService:
        def __init__(self):
            self.metric_payloads = []

        async def upsert_domain(self, data):
            return 1

        async def upsert_asset(self, domain_id, asset_type, data):
            if asset_type == "metric":
                self.metric_payloads.append(data)
            return 1

    fake = FakeSemanticService()
    monkeypatch.setattr(semantic_bundle, "get_semantic_runtime_service", lambda: fake)

    result = asyncio.run(
        semantic_bundle.import_semantic_bundle(
            path=SEMANTIC_PATH,
            agent_id=1,
            datasource_id=1,
        )
    )

    assert result["semantic_metric"] == len(EXPECTED_METRIC_OBJECTS)
    assert len(fake.metric_payloads) == len(EXPECTED_METRIC_OBJECTS)

    imported_metric = next(
        item for item in fake.metric_payloads if item["metric_key"] == "m1_plus_rate"
    )
    assert imported_metric["metadata"] == {"object_key": "RepaymentPeriod"}

    runtime_metric = SemanticMetric(domain_id=1, **imported_metric)
    stored_payload = SemanticRuntimeService()._model_payload(
        runtime_metric.model_dump(exclude={"id"}), "metric"
    )
    assert json.loads(stored_payload["metadata"]) == {"object_key": "RepaymentPeriod"}
