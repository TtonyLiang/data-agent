from unittest.mock import Mock

import pytest

from app.agent.nodes.lf_to_sql_compile import lf_to_sql_compile_node
from app.agent.nodes.lf_validate import lf_validate_node
from app.agent.query_capability import (
    build_query_capability_registry,
    query_capability_prompt_payload,
    resolve_query_capability_key,
)
from app.models.knowledge import LogicForm, SemanticDomain, SemanticMetric, SemanticRuntime
from app.models.query_capability import QueryCapability


def _runtime() -> dict:
    return SemanticRuntime(
        domain=SemanticDomain(id=1, agent_id=1, domain_key="loan_risk", name="贷款风控"),
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
    ).model_dump()


def _context(*capabilities: QueryCapability) -> dict:
    return {
        "ontology_context": {"object_types": [{"object_key": "LoanApplication"}]},
        "query_capabilities": [item.model_dump() for item in capabilities],
    }


def _capability(key: str = "loan_application_summary") -> QueryCapability:
    return QueryCapability(
        key=key,
        name="贷款申请汇总",
        target_object="LoanApplication",
        domain_key="loan_risk",
        supported_metrics=["application_count"],
        supported_dimensions=["product_type"],
    )


def test_registry_and_resolution_require_one_complete_match():
    context = _context(_capability())
    logic_form = LogicForm(
        domain_key="loan_risk",
        metrics=["application_count"],
        dimensions=["product_type"],
    )

    assert build_query_capability_registry(context).resolve("loan_application_summary")
    assert resolve_query_capability_key(logic_form, context) == "loan_application_summary"
    assert query_capability_prompt_payload(context)[0]["supported_metrics"] == [
        "application_count"
    ]


def test_resolution_does_not_guess_when_multiple_capabilities_match():
    context = _context(_capability("summary_a"), _capability("summary_b"))
    logic_form = LogicForm(metrics=["application_count"])

    assert resolve_query_capability_key(logic_form, context) is None


@pytest.mark.asyncio
async def test_validate_blocks_capability_boundary_before_compile():
    capability = _capability()
    result = await lf_validate_node(
        {
            "logic_form": {"metrics": ["application_count"], "dimensions": ["unknown"]},
            "semantic_runtime": _runtime(),
            "query_context": _context(capability),
            "query_capability_key": capability.key,
        }
    )

    assert not result["query_capability_validation"]["valid"]
    assert not result["lf_validation"]["valid"]
    assert "Capability 不支持维度: unknown" in result["lf_validation"]["errors"]


@pytest.mark.asyncio
async def test_compile_delegates_through_facade_and_records_read_only_trace(monkeypatch):
    capability = _capability()
    compiled = Mock()
    compiled.used_assets = ["metric:application_count"]
    compiled.warnings = []
    compiled.sql = "SELECT COUNT(*) FROM loan_application"
    compiled.model_dump.return_value = {"sql": compiled.sql}

    facade = Mock()
    facade.compile_logic_form.return_value = compiled
    monkeypatch.setattr(
        "app.agent.nodes.lf_to_sql_compile.QueryCapabilityFacade", lambda *args, **kwargs: facade
    )

    result = await lf_to_sql_compile_node(
        {
            "logic_form": {"metrics": ["application_count"]},
            "semantic_runtime": _runtime(),
            "query_context": _context(capability),
            "query_capability_key": capability.key,
            "query_capability_validation": {"capability_key": capability.key, "valid": True},
            "lf_validation": {"valid": True},
        }
    )

    facade.compile_logic_form.assert_called_once()
    assert result["execution_trace"]["query_capability_key"] == capability.key
    assert result["execution_trace"]["target_object"] == "LoanApplication"
    assert result["execution_trace"]["read_only"] is True


@pytest.mark.asyncio
async def test_compile_without_context_keeps_legacy_compiler(monkeypatch):
    service = Mock()
    compiled = Mock()
    compiled.used_assets = []
    compiled.warnings = []
    compiled.sql = "SELECT 1"
    compiled.model_dump.return_value = {"sql": compiled.sql}
    service.compile_logic_form.return_value = compiled
    monkeypatch.setattr(
        "app.agent.nodes.lf_to_sql_compile.get_semantic_runtime_service",
        lambda: service,
    )

    result = await lf_to_sql_compile_node(
        {
            "logic_form": {"metrics": ["application_count"]},
            "semantic_runtime": _runtime(),
            "lf_validation": {"valid": True},
        }
    )

    service.compile_logic_form.assert_called_once()
    assert result["execution_trace"]["compile_strategy"] == "deterministic_logic_form"
    assert "query_capability_key" not in result["execution_trace"]
