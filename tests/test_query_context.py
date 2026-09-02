from copy import deepcopy
from unittest.mock import Mock

import pytest

from app.agent.nodes import semantic_runtime_recall
from app.models.knowledge import (
    SemanticConcept,
    SemanticDomain,
    SemanticMapping,
    SemanticMetric,
    SemanticRuntime,
)
from app.services.query_context import build_query_context


def _runtime() -> SemanticRuntime:
    return SemanticRuntime(
        domain=SemanticDomain(id=1, agent_id=7, domain_key="loan_risk", name="贷款风控"),
        concepts=[
            SemanticConcept(
                domain_id=1,
                concept_key="LoanApplication",
                concept_type="entity",
                name="贷款申请",
            ),
            SemanticConcept(
                domain_id=1,
                concept_key="Customer",
                concept_type="entity",
                name="客户",
            ),
        ],
        metrics=[
            SemanticMetric(
                domain_id=1,
                metric_key="application_count",
                name="申请笔数",
                formula_sql="COUNT(*)",
                base_table="loan_application",
                dimensions=["application_region"],
                metadata={"object_key": "LoanApplication"},
            ),
            SemanticMetric(
                domain_id=1,
                metric_key="customer_count",
                name="客户数",
                formula_sql="COUNT(DISTINCT customer_id)",
                base_table="customer",
                metadata={"object_key": "Customer"},
            ),
            SemanticMetric(
                domain_id=1,
                metric_key="unowned_metric",
                name="未归属指标",
                formula_sql="COUNT(*)",
                base_table="unknown_table",
            ),
        ],
        mappings=[
            SemanticMapping(
                domain_id=1,
                asset_type="dimension",
                asset_key="application_region",
                table_name="loan_application",
                column_name="region",
                role="dimension",
            )
        ],
    )


def _ontology_context() -> dict:
    return {
        "domain": {"id": 1, "domain_key": "loan_risk", "name": "贷款风控"},
        "release": {"id": 3, "version": 2},
        "object_types": [
            {
                "object_key": "LoanApplication",
                "name": "贷款申请",
                "properties": [],
            },
            {"object_key": "Customer", "name": "客户", "properties": []},
        ],
        "link_types": [],
        "actions": [],
    }


def test_build_query_context_has_unified_fields_and_stable_grouped_capabilities():
    result = build_query_context(
        "查看贷款申请和客户数量",
        _runtime(),
        _ontology_context(),
        {"object_types": [], "link_types": [], "actions": [], "count": 0},
    )

    assert set(
        [
            "domain",
            "ontology",
            "ontology_context",
            "bridge",
            "query_capabilities",
            "release",
            "evidence",
            "warnings",
        ]
    ).issubset(result)
    capabilities = {item["key"]: item for item in result["query_capabilities"]}
    assert set(capabilities) == {"query_loan_application", "query_customer"}
    assert capabilities["query_loan_application"]["supported_metrics"] == [
        "application_count"
    ]
    assert capabilities["query_loan_application"]["supported_dimensions"] == [
        "application_region"
    ]


def test_unowned_metric_only_produces_warning_and_is_not_exposed():
    result = build_query_context("查看指标", _runtime(), _ontology_context())

    assert all(
        "unowned_metric" not in capability["supported_metrics"]
        for capability in result["query_capabilities"]
    )
    warning_codes = {item["code"] for item in result["warnings"]}
    assert "metric_object_association_missing" in warning_codes


def test_build_query_context_does_not_modify_inputs():
    runtime = _runtime()
    ontology = _ontology_context()
    runtime_before = deepcopy(runtime.model_dump(mode="python"))
    ontology_before = deepcopy(ontology)

    result = build_query_context("查询", runtime, ontology)
    result["ontology"]["object_types"].clear()
    result["bridge"]["objects"].clear()
    result["query_capabilities"].clear()

    assert runtime.model_dump(mode="python") == runtime_before
    assert ontology == ontology_before


@pytest.mark.asyncio
async def test_recall_node_preserves_legacy_fields_and_adds_query_context(monkeypatch):
    runtime = _runtime()

    class FakeSemanticService:
        async def get_agent_bound_domain(self, agent_id):
            return None

        async def build_runtime(self, **kwargs):
            return runtime

    class FakeEmbedding:
        async def embed_query(self, question, agent_id=None):
            return [0.1]

    class FakeVectorStore:
        def search(self, agent_id, query_vector):
            return []

    class FakeOntologyService:
        async def build_agent_context(self, domain_id, role):
            return _ontology_context()

    monkeypatch.setattr(
        semantic_runtime_recall,
        "get_semantic_runtime_service",
        lambda: FakeSemanticService(),
    )
    monkeypatch.setattr(semantic_runtime_recall, "get_embedding_service", lambda: FakeEmbedding())
    monkeypatch.setattr(semantic_runtime_recall, "get_vector_store", lambda: FakeVectorStore())
    monkeypatch.setattr(
        semantic_runtime_recall, "get_ontology_service", lambda: FakeOntologyService()
    )

    result = await semantic_runtime_recall.semantic_runtime_recall_node(
        {"agent_id": 7, "question": "查看贷款申请数量"}
    )

    assert result["semantic_runtime"]["domain"]["domain_key"] == "loan_risk"
    assert "runtime_evidence" in result
    assert "ontology_context" in result
    assert "ontology_evidence" in result
    assert result["query_context"]["query_capabilities"][0]["key"] == "query_loan_application"


@pytest.mark.asyncio
async def test_recall_node_query_context_failure_keeps_old_recall_output(monkeypatch):
    runtime = _runtime()

    class FakeSemanticService:
        async def get_agent_bound_domain(self, agent_id):
            return None

        async def build_runtime(self, **kwargs):
            return runtime

    class FakeEmbedding:
        async def embed_query(self, question, agent_id=None):
            return [0.1]

    class FakeVectorStore:
        def search(self, agent_id, query_vector):
            return []

    class FakeOntologyService:
        async def build_agent_context(self, domain_id, role):
            return _ontology_context()

    monkeypatch.setattr(
        semantic_runtime_recall,
        "get_semantic_runtime_service",
        lambda: FakeSemanticService(),
    )
    monkeypatch.setattr(semantic_runtime_recall, "get_embedding_service", lambda: FakeEmbedding())
    monkeypatch.setattr(semantic_runtime_recall, "get_vector_store", lambda: FakeVectorStore())
    monkeypatch.setattr(
        semantic_runtime_recall, "get_ontology_service", lambda: FakeOntologyService()
    )
    monkeypatch.setattr(
        semantic_runtime_recall,
        "build_query_context",
        Mock(side_effect=RuntimeError("context failed")),
    )

    result = await semantic_runtime_recall.semantic_runtime_recall_node(
        {"agent_id": 7, "question": "查看贷款申请数量"}
    )

    assert result["semantic_error"] is None
    assert result["semantic_runtime"]
    assert result["runtime_evidence"]
    assert result["ontology_evidence"]
    assert result["query_context"]["warnings"][0]["code"] == "query_context_build_failed"


@pytest.mark.asyncio
async def test_recall_node_runtime_failure_returns_structured_context_warning(monkeypatch):
    class FakeSemanticService:
        async def get_agent_bound_domain(self, agent_id):
            return None

        async def build_runtime(self, **kwargs):
            raise RuntimeError("runtime failed")

    monkeypatch.setattr(
        semantic_runtime_recall,
        "get_semantic_runtime_service",
        lambda: FakeSemanticService(),
    )

    result = await semantic_runtime_recall.semantic_runtime_recall_node(
        {"agent_id": 7, "question": "查看贷款申请数量"}
    )

    assert result["semantic_runtime"] is None
    assert result["runtime_evidence"] == []
    assert result["query_context"]["warnings"][0]["code"] == "semantic_runtime_unavailable"
