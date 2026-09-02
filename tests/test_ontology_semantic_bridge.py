from copy import deepcopy

from app.models.knowledge import SemanticDomain, SemanticMetric, SemanticRuntime
from app.services.ontology_semantic_bridge import (
    OntologySemanticBridge,
    build_ontology_semantic_bridge,
    normalize_term,
)


def _context():
    return {
        "domain": {"id": 1, "domain_key": "loan_risk"},
        "object_types": [
            {
                "object_key": "LoanApplication",
                "name": "贷款申请",
                "description": "客户提交的贷款申请",
                "properties": [
                    {"property_key": "application_id", "name": "申请编号"},
                    {"property_key": "application_region", "name": "申请地区"},
                ],
            },
            {
                "object_key": "Customer",
                "name": "客户",
                "properties": [{"property_key": "customer_id", "name": "客户编号"}],
            },
        ],
        "link_types": [
            {
                "link_key": "customer_submits_application",
                "name": "客户提交贷款申请",
                "source_object_key": "Customer",
                "target_object_key": "LoanApplication",
            }
        ],
        "actions": [
            {
                "action_key": "approve_application",
                "name": "审批申请",
                "target_object_key": "LoanApplication",
            }
        ],
    }


def _runtime_dict():
    return {
        "concepts": [
            {
                "concept_key": "LoanApplication",
                "concept_type": "object",
                "name": "贷款申请",
                "synonyms": ["进件", "申请单"],
            },
            {
                "concept_key": "Customer",
                "concept_type": "object",
                "name": "客户",
                "synonyms": ["借款人"],
            },
        ],
        "metrics": [
            {
                "metric_key": "application_count",
                "name": "申请笔数",
                "synonyms": ["进件量"],
                "formula_sql": "COUNT(*)",
                "base_table": "loan_application_indicator",
                "metadata": {"object_key": "LoanApplication"},
                "dimensions": ["application_region", "missing_dimension"],
            }
        ],
        "mappings": [
            {
                "asset_type": "dimension",
                "asset_key": "application_region",
                "table_name": "loan_application_indicator",
                "column_name": "region",
                "role": "dimension",
            },
            {
                "asset_type": "field",
                "asset_key": "customer_id_mapping",
                "table_name": "loan_application_indicator",
                "column_name": "customer_id",
                "object_key": "Customer",
                "property_key": "customer_id",
            },
        ],
        "relations": [
            {
                "relation_key": "customer_submits_application",
                "relation_type": "join_path",
                "source_concept": "Customer",
                "target_concept": "LoanApplication",
                "name": "客户提交申请",
                "join_path": [{"left": "customer.id", "right": "application.customer_id"}],
            }
        ],
    }


def test_normalize_term_and_synonym_resolve_to_canonical_object_key():
    bridge = OntologySemanticBridge(_context(), _runtime_dict())

    assert normalize_term("  进 件  ") == "进件"
    assert bridge.resolve_object_key("进 件") == "LoanApplication"
    assert bridge.resolve_object_key("贷款申请") == "LoanApplication"


def test_object_and_metric_bridge_exposes_explicit_ownership_and_dimensions():
    result = build_ontology_semantic_bridge(_context(), _runtime_dict())

    assert result["objects"]["LoanApplication"]["concept"]["concept_key"] == "LoanApplication"
    assert result["objects"]["LoanApplication"]["metrics"] == ["application_count"]
    metric = result["metrics"]["application_count"]
    assert metric["object_keys"] == ["LoanApplication"]
    assert [item["asset_key"] for item in metric["dimensions"]] == [
        "application_region",
        "missing_dimension",
    ]
    assert metric["dimensions"][0]["mapping"]["column_name"] == "region"
    assert metric["dimensions"][1]["mapping"] is None


def test_object_property_mapping_can_be_reverse_resolved():
    bridge = OntologySemanticBridge(_context(), _runtime_dict())

    explicit = bridge.object_property_mappings("Customer", "customer_id")
    semantic_key = bridge.object_property_mappings("LoanApplication", "application_region")

    assert [item["asset_key"] for item in explicit] == ["customer_id_mapping"]
    assert [item["column_name"] for item in semantic_key] == ["region"]


def test_link_key_bridges_to_semantic_relation_without_guessing_join_path():
    bridge = OntologySemanticBridge(_context(), _runtime_dict())

    relation = bridge.relation_bridge("customer_submits_application")

    assert relation["linked"] is True
    assert relation["relation_key"] == "customer_submits_application"
    assert relation["join_path"] == [{"left": "customer.id", "right": "application.customer_id"}]


def test_missing_associations_are_explainable_warnings():
    context = _context()
    context["link_types"].append(
        {
            "link_key": "application_to_unknown",
            "name": "申请到未知对象",
            "source_object_key": "LoanApplication",
            "target_object_key": "Unknown",
        }
    )
    runtime = _runtime_dict()
    runtime["metrics"].append(
        {
            "metric_key": "unowned_metric",
            "name": "未归属指标",
            "formula_sql": "COUNT(*)",
            "base_table": "unknown_table",
        }
    )

    result = build_ontology_semantic_bridge(context, runtime)
    codes = {item["code"] for item in result["warnings"]}

    assert "object_property_mapping_missing" in codes
    assert "metric_dimension_mapping_missing" in codes
    assert "metric_object_association_missing" in codes
    assert "link_semantic_relation_missing" in codes
    assert result["relations"]["application_to_unknown"]["join_path"] == []


def test_bridge_accepts_pydantic_runtime_and_does_not_modify_inputs():
    context = _context()
    runtime_model = SemanticRuntime(
        domain=SemanticDomain(
            id=1,
            agent_id=1,
            domain_key="loan_risk",
            name="贷款风控",
        ),
        metrics=[
            SemanticMetric(
                domain_id=1,
                metric_key="application_count",
                name="申请笔数",
                formula_sql="COUNT(*)",
                base_table="loan_application_indicator",
                dimensions=["application_region"],
                metadata={"object_key": "LoanApplication"},
            )
        ],
    )
    context_before = deepcopy(context)
    runtime_before = runtime_model.model_dump(mode="python")

    result = build_ontology_semantic_bridge(context, runtime_model)
    result["objects"]["LoanApplication"]["properties"].clear()

    assert context == context_before
    assert runtime_model.model_dump(mode="python") == runtime_before
    assert result["metrics"]["application_count"]["object_keys"] == ["LoanApplication"]
