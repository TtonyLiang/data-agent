from unittest.mock import AsyncMock

import pytest

from app.agent.ontology_tools import (
    ACTION_TOOL,
    QUERY_CAPABILITY_TOOL,
    QUERY_TOOL,
    build_ontology_tool_definitions,
    build_query_capability_definitions,
    invoke_ontology_tool,
)
from app.api import ontology as ontology_api
from app.models.knowledge import (
    SemanticDomain,
    SemanticMapping,
    SemanticMetric,
    SemanticRuntime,
)
from app.models.user import PublicUser
from app.services.query_context import build_query_context


def runtime() -> SemanticRuntime:
    return SemanticRuntime(
        domain=SemanticDomain(
            id=7,
            agent_id=11,
            datasource_id=42,
            domain_key="loan_risk",
            name="贷款风控",
        ),
        metrics=[
            SemanticMetric(
                domain_id=7,
                metric_key="application_count",
                name="申请笔数",
                formula_sql="COUNT(*)",
                base_table="loan_application",
                dimensions=["product_type"],
                metadata={"object_key": "LoanApplication"},
            )
        ],
        mappings=[
            SemanticMapping(
                domain_id=7,
                asset_type="dimension",
                asset_key="product_type",
                table_name="loan_application",
                column_name="product_type",
                role="dimension",
            )
        ],
    )


def context() -> dict:
    return {
        "domain": {"id": 7, "domain_key": "loan_risk", "name": "贷款风控"},
        "release": {"id": 6, "version": 3, "definition_hash": "b" * 64},
        "object_types": [
            {
                "object_key": "LoanApplication",
                "name": "贷款申请",
                "status": "active",
                "properties": [],
            }
        ],
        "link_types": [],
        "actions": [{"action_key": "approve", "target_object_key": "LoanApplication"}],
    }


def user() -> dict:
    return {"id": 1, "role": "user"}


def public_user() -> PublicUser:
    return PublicUser(
        id=1,
        username="tester",
        role="user",
        status="active",
    )


def test_new_query_tool_is_isolated_while_legacy_default_list_stays_compatible():
    legacy_names = [item["name"] for item in build_ontology_tool_definitions()]
    assert legacy_names == [QUERY_TOOL, ACTION_TOOL]

    tools = build_ontology_tool_definitions(include_query_capability=True)
    query_tool = next(item for item in tools if item["name"] == QUERY_CAPABILITY_TOOL)
    assert query_tool["parameters"]["additionalProperties"] is False
    assert query_tool["parameters"]["required"] == ["capability_key"]
    assert "execute_action" not in query_tool["description"]
    assert "compiled_plan_only" not in query_tool["description"]
    assert "真实业务数据" in query_tool["description"]
    assert "安全、权限和脱敏链路" in query_tool["description"]


@pytest.mark.asyncio
async def test_query_capability_executes_read_only_query_without_action_execution(monkeypatch):
    execution_states = []
    safe_sql = (
        "SELECT `product_type`, COUNT(*) AS application_count "
        "FROM loan_application LIMIT 1000"
    )

    async def fake_sql_execute_node(state):
        execution_states.append(state)
        return {
            "sql_result": [{"product_type": "信用贷", "application_count": 3}],
            "sql_error": None,
            "compiled_sql": safe_sql,
            "sql_text": safe_sql,
            "final_answer": "信用贷的 申请笔数为 3。",
            "execution_trace": {"trace_id": "trace-query-capability"},
        }

    monkeypatch.setattr(
        "app.agent.ontology_tools.sql_execute_node",
        fake_sql_execute_node,
    )

    class FakeService:
        execute_action = AsyncMock(side_effect=AssertionError("must not write"))

    result = await invoke_ontology_tool(
        FakeService(),
        7,
        QUERY_CAPABILITY_TOOL,
        {
            "capability_key": "query_loan_application",
            "metrics": ["application_count"],
            "dimensions": ["product_type"],
        },
        user(),
        ontology_context=context(),
        semantic_runtime=runtime(),
    )

    assert result["tool"] == QUERY_CAPABILITY_TOOL
    assert result["read_only"] is True
    assert result["execution"]["executed"] is True
    assert result["execution"]["attempted"] is True
    assert result["execution"]["status"] == "succeeded"
    assert result["execution"]["mode"] == "deterministic_read_only_sql"
    assert result["compiled_plan"]["sql"].startswith("SELECT")
    assert result["compiled_plan"]["executed_sql"] == safe_sql
    assert result["sql_result"] == [{"product_type": "信用贷", "application_count": 3}]
    assert result["sql_error"] is None
    assert result["executed_sql"] == safe_sql
    assert result["final_answer"] == "信用贷的 申请笔数为 3。"
    assert result["execution_trace"]["trace_id"].startswith("trc_")
    assert result["execution_trace"]["trace_id"] != "trace-query-capability"
    assert result["execution_trace"]["domain_id"] == 7
    assert result["execution_trace"]["datasource_id"] == 42
    assert result["execution_trace"]["ontology_release"] == context()["release"]
    assert len(execution_states) == 1
    assert execution_states[0]["agent_id"] == runtime().domain.agent_id
    assert execution_states[0]["datasource_id"] == runtime().domain.datasource_id
    assert execution_states[0]["trace_id"] == result["execution_trace"]["trace_id"]
    assert execution_states[0]["compiled_sql"] == result["compiled_plan"]["sql"]
    FakeService.execute_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_capability_rejects_unknown_top_level_and_logic_form_arguments():
    class FakeService:
        pass

    with pytest.raises(ValueError, match="未知参数"):
        await invoke_ontology_tool(
            FakeService(),
            7,
            QUERY_CAPABILITY_TOOL,
            {"capability_key": "query_loan_application", "sql": "SELECT 1"},
            user(),
            ontology_context=context(),
            semantic_runtime=runtime(),
        )

    with pytest.raises(ValueError, match="LogicForm 包含未知参数"):
        await invoke_ontology_tool(
            FakeService(),
            7,
            QUERY_CAPABILITY_TOOL,
            {
                "capability_key": "query_loan_application",
                "logic_form": {"metrics": ["application_count"], "table": "loan_application"},
            },
            user(),
            ontology_context=context(),
            semantic_runtime=runtime(),
        )


def test_capability_definitions_are_read_only_and_explicitly_object_bound():
    capabilities = build_query_capability_definitions(runtime(), context())

    assert len(capabilities) == 1
    capability = capabilities[0]
    assert capability["key"] == "query_loan_application"
    assert capability["target_object"] == "LoanApplication"
    assert capability["supported_metrics"] == ["application_count"]
    assert capability["read_only"] is True
    assert capabilities == build_query_context("", runtime(), context())["query_capabilities"]


@pytest.mark.asyncio
async def test_query_capability_api_and_agent_context_expose_same_contract(monkeypatch):
    fake_service = object()
    monkeypatch.setattr(ontology_api, "require_domain_access", AsyncMock())
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: fake_service)
    monkeypatch.setattr(
        ontology_api,
        "_load_query_runtime_context",
        AsyncMock(return_value=(context(), runtime())),
    )

    capabilities_response = await ontology_api.list_query_capabilities(7, public_user())
    context_response = await ontology_api.get_agent_context(7, public_user())

    assert capabilities_response["query_capabilities"] == context_response["query_capabilities"]
    assert {item["name"] for item in context_response["tools"]} == {
        QUERY_TOOL,
        ACTION_TOOL,
        QUERY_CAPABILITY_TOOL,
    }
    assert context_response["object_types"] == context()["object_types"]
    assert context_response["link_types"] == context()["link_types"]
    assert context_response["actions"] == context()["actions"]
