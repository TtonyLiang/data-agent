from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.models.knowledge import (
    LogicForm,
    SemanticConcept,
    SemanticDomain,
    SemanticMapping,
    SemanticMetric,
    SemanticRuntime,
)
from app.models.query_capability import QueryCapability
from app.services.query_capability import QueryCapabilityFacade, QueryCapabilityRegistry


def build_runtime() -> SemanticRuntime:
    return SemanticRuntime(
        domain=SemanticDomain(
            id=1,
            agent_id=1,
            domain_key="loan_risk",
            name="贷款风控",
        ),
        concepts=[
            SemanticConcept(
                domain_id=1,
                concept_key="LoanApplication",
                concept_type="entity",
                name="贷款申请",
            )
        ],
        metrics=[
            SemanticMetric(
                domain_id=1,
                metric_key="application_count",
                name="申请笔数",
                formula_sql="COUNT(*)",
                base_table="loan_application",
                dimensions=["product_type"],
            )
        ],
        mappings=[
            SemanticMapping(
                domain_id=1,
                asset_type="dimension",
                asset_key="product_type",
                table_name="loan_application",
                column_name="product_type",
                role="dimension",
            )
        ],
    )


def test_capability_key_and_read_only_contract_are_validated():
    with pytest.raises(ValidationError):
        QueryCapability(
            key="Loan Query",
            name="贷款查询",
            target_object="LoanApplication",
            supported_metrics=["application_count"],
        )

    with pytest.raises(ValidationError):
        QueryCapability(
            key="loan_query",
            name="贷款查询",
            target_object="LoanApplication",
            read_only=False,
        )


def test_registry_can_build_and_resolve_from_logic_form_and_runtime_context():
    runtime = build_runtime()
    logic_form = LogicForm(
        domain_key="loan_risk",
        metrics=["application_count"],
        dimensions=["product_type"],
    )
    registry = QueryCapabilityRegistry()

    capability = registry.register_from_logic_form(
        "loan_application_summary",
        logic_form,
        runtime,
        {"object_types": [{"object_key": "LoanApplication"}]},
    )

    assert capability.target_object == "LoanApplication"
    assert capability.supported_metrics == ["application_count"]
    assert capability.supported_dimensions == ["product_type"]
    assert registry.resolve("loan_application_summary") == capability


def test_facade_rejects_logic_form_outside_capability_boundary():
    runtime = build_runtime()
    facade = QueryCapabilityFacade()
    facade.register_from_runtime(
        "loan_application_query",
        runtime,
        {"object_types": [{"object_key": "LoanApplication"}]},
    )

    validation = facade.validate_capability(
        "loan_application_query",
        LogicForm(metrics=["application_count"], dimensions=["unknown_dimension"]),
    )

    assert not validation.valid
    assert "Capability 不支持维度: unknown_dimension" in validation.errors


def test_facade_delegates_only_to_deterministic_compiler_after_capability_validation():
    runtime = build_runtime()
    compiler = Mock()
    compiler.compile_logic_form.return_value = "compiled-query"
    facade = QueryCapabilityFacade(semantic_runtime_service=compiler)
    facade.register_from_runtime(
        "loan_application_query",
        runtime,
        {"object_types": [{"object_key": "LoanApplication"}]},
    )
    logic_form = LogicForm(metrics=["application_count"])

    result = facade.compile_logic_form("loan_application_query", logic_form, runtime)

    assert result == "compiled-query"
    compiler.compile_logic_form.assert_called_once_with(logic_form, runtime)
    assert [item[0] for item in compiler.method_calls] == ["compile_logic_form"]
