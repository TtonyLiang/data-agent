from unittest.mock import AsyncMock, Mock

import pytest

from app.agent import ontology_tools
from app.models.knowledge import (
    SemanticDomain,
    SemanticMapping,
    SemanticMetric,
    SemanticRuntime,
)


def _runtime(datasource_id: int | None = 23) -> SemanticRuntime:
    return SemanticRuntime(
        domain=SemanticDomain(
            id=9,
            agent_id=17,
            datasource_id=datasource_id,
            domain_key="loan_risk",
            name="贷款风控",
        ),
        metrics=[
            SemanticMetric(
                domain_id=9,
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
                domain_id=9,
                asset_type="dimension",
                asset_key="product_type",
                table_name="loan_application",
                column_name="product_type",
                role="dimension",
            )
        ],
    )


def _context() -> dict:
    return {
        "domain": {"id": 9, "domain_key": "loan_risk", "name": "贷款风控"},
        "release": {"id": 4, "version": 2, "definition_hash": "a" * 64},
        "object_types": [
            {
                "object_key": "LoanApplication",
                "name": "贷款申请",
                "status": "active",
                "properties": [],
            }
        ],
        "link_types": [],
        "actions": [],
    }


def _arguments(**overrides) -> dict:
    arguments = {
        "capability_key": "query_loan_application",
        "metrics": ["application_count"],
        "dimensions": ["product_type"],
    }
    arguments.update(overrides)
    return arguments


def _service() -> Mock:
    service = Mock()
    service.execute_action = AsyncMock(side_effect=AssertionError("Query must not write"))
    return service


@pytest.mark.asyncio
async def test_query_capability_executes_compiled_sql_with_domain_identity(monkeypatch):
    safe_sql = (
        "SELECT `product_type`, COUNT(*) AS application_count "
        "FROM loan_application LIMIT 1000"
    )
    executor = AsyncMock(
        return_value={
            "sql_result": [{"product_type": "信用贷", "application_count": 8}],
            "sql_error": None,
            "compiled_sql": safe_sql,
            "sql_text": safe_sql,
            "final_answer": "信用贷的申请笔数为 8。",
            "execution_trace": {"trace_id": "trace-query-execution"},
        }
    )
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)

    runtime = _runtime()
    service = _service()
    result = await ontology_tools.invoke_ontology_tool(
        service,
        9,
        ontology_tools.QUERY_CAPABILITY_TOOL,
        _arguments(),
        {"id": 5, "role": "user"},
        ontology_context=_context(),
        semantic_runtime=runtime,
    )

    executor.assert_awaited_once()
    execution_state = executor.await_args.args[0]
    assert execution_state["agent_id"] == runtime.domain.agent_id
    assert execution_state["datasource_id"] == runtime.domain.datasource_id
    assert execution_state["trace_id"] == result["execution_trace"]["trace_id"]
    assert execution_state["compiled_sql"] == result["compiled_plan"]["sql"]
    assert execution_state["sql_text"] == result["compiled_plan"]["sql"]
    assert result["capability"]["target_object"] == "LoanApplication"
    assert result["validation"]["valid"] is True
    assert result["execution"]["executed"] is True
    assert result["execution"]["attempted"] is True
    assert result["execution"]["status"] == "succeeded"
    assert result["execution"]["mode"] == "deterministic_read_only_sql"
    assert result["execution"]["message"] == "已通过现有只读 SQL 安全、权限和脱敏链路执行。"
    assert result["sql_result"] == [{"product_type": "信用贷", "application_count": 8}]
    assert result["sql_error"] is None
    assert result["executed_sql"] == safe_sql
    assert result["compiled_plan"]["executed_sql"] == safe_sql
    assert result["final_answer"] == "信用贷的申请笔数为 8。"
    assert result["execution_trace"]["trace_id"].startswith("trc_")
    assert result["execution_trace"]["trace_id"] != "trace-query-execution"
    assert result["execution_trace"]["domain_id"] == 9
    assert result["execution_trace"]["datasource_id"] == 23
    assert result["execution_trace"]["ontology_release"] == _context()["release"]
    assert result["execution_trace"]["release"] == _context()["release"]
    assert result["execution_trace"]["executed_sql"] == safe_sql
    assert result["execution_trace"]["query_capability_execution"] == {
        "executed": True,
        "attempted": True,
        "status": "succeeded",
        "mode": "deterministic_read_only_sql",
        "error_category": None,
    }
    assert result["execution_trace"]["query_capability_key"] == "query_loan_application"
    service.execute_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_capability_validation_blocks_execution(monkeypatch):
    executor = AsyncMock(side_effect=AssertionError("invalid query must not execute"))
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)

    result = await ontology_tools.invoke_ontology_tool(
        _service(),
        9,
        ontology_tools.QUERY_CAPABILITY_TOOL,
        _arguments(dimensions=["secret_dimension"]),
        {"id": 5, "role": "user"},
        ontology_context=_context(),
        semantic_runtime=_runtime(),
    )

    executor.assert_not_awaited()
    assert result["validation"]["valid"] is False
    assert result["execution"]["executed"] is False
    assert result["execution"]["attempted"] is False
    assert result["execution"]["status"] == "validation_blocked"
    assert result["execution"]["mode"] == "validation_blocked"
    assert result["execution_trace"]["trace_id"].startswith("trc_")
    assert result["execution_trace"]["domain_id"] == 9
    assert result["execution_trace"]["datasource_id"] == 23
    assert result["execution_trace"]["ontology_release"] == _context()["release"]
    assert result["execution_trace"]["query_capability_execution"] == {
        "executed": False,
        "attempted": False,
        "status": "validation_blocked",
        "mode": "validation_blocked",
    }
    assert "compiled_plan" not in result
    assert "Capability 不支持维度: secret_dimension" in result["sql_error"]
    assert "查询未执行" in result["final_answer"]


@pytest.mark.asyncio
async def test_query_capability_never_calls_execute_action(monkeypatch):
    executor = AsyncMock(
        return_value={
            "sql_result": [],
            "sql_error": None,
            "final_answer": "查询结果为空，没有匹配的数据。",
            "execution_trace": {},
        }
    )
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)
    service = _service()

    await ontology_tools.invoke_ontology_tool(
        service,
        9,
        ontology_tools.QUERY_CAPABILITY_TOOL,
        _arguments(),
        {"id": 5, "role": "user"},
        ontology_context=_context(),
        semantic_runtime=_runtime(),
    )

    service.execute_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_capability_rejects_unknown_argument_before_execution(monkeypatch):
    executor = AsyncMock(side_effect=AssertionError("unknown argument must not execute"))
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)

    with pytest.raises(ValueError, match="未知参数: sql"):
        await ontology_tools.invoke_ontology_tool(
            _service(),
            9,
            ontology_tools.QUERY_CAPABILITY_TOOL,
            _arguments(sql="SELECT 1"),
            {"id": 5, "role": "user"},
            ontology_context=_context(),
            semantic_runtime=_runtime(),
        )

    executor.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sql_error", "expected_status", "expected_category"),
    [
        ("安全拦截: 禁止执行写操作", "security_blocked", "security"),
        ("权限拦截: 无权访问表", "permission_blocked", "permission"),
    ],
)
async def test_query_capability_reports_security_and_permission_blocks(
    monkeypatch, sql_error, expected_status, expected_category
):
    executor = AsyncMock(
        return_value={
            "sql_result": [],
            "sql_error": sql_error,
            "final_answer": sql_error,
            "execution_trace": {"trace_id": "node-must-not-own-trace"},
        }
    )
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)

    result = await ontology_tools.invoke_ontology_tool(
        _service(),
        9,
        ontology_tools.QUERY_CAPABILITY_TOOL,
        _arguments(),
        {"id": 5, "role": "user"},
        ontology_context=_context(),
        semantic_runtime=_runtime(),
    )

    executor.assert_awaited_once()
    assert result["execution"]["executed"] is False
    assert result["execution"]["attempted"] is True
    assert result["execution"]["status"] == expected_status
    assert result["execution"]["error_category"] == expected_category
    assert result["sql_error"] == sql_error
    assert result["executed_sql"] is None
    assert result["compiled_plan"]["executed_sql"] is None
    assert result["execution_trace"]["query_capability_execution"]["executed"] is False
    assert (
        result["execution_trace"]["query_capability_execution"]["status"]
        == expected_status
    )
    assert result["execution_trace"]["trace_id"] != "node-must-not-own-trace"


@pytest.mark.asyncio
async def test_query_capability_reports_database_exception_as_not_executed(monkeypatch):
    executor = AsyncMock(side_effect=RuntimeError("database connection failed"))
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)

    result = await ontology_tools.invoke_ontology_tool(
        _service(),
        9,
        ontology_tools.QUERY_CAPABILITY_TOOL,
        _arguments(),
        {"id": 5, "role": "user"},
        ontology_context=_context(),
        semantic_runtime=_runtime(),
    )

    executor.assert_awaited_once()
    assert result["execution"]["executed"] is False
    assert result["execution"]["attempted"] is True
    assert result["execution"]["status"] == "database_error"
    assert result["execution"]["error_category"] == "database"
    assert result["sql_error"] == "database connection failed"
    assert result["final_answer"] == "SQL执行失败: database connection failed"
    assert result["executed_sql"] is None
    assert result["compiled_plan"]["executed_sql"] is None
    assert result["execution_trace"]["query_capability_execution"] == {
        "executed": False,
        "attempted": True,
        "status": "database_error",
        "mode": "deterministic_read_only_sql",
        "error_category": "database",
    }


@pytest.mark.asyncio
async def test_query_capability_does_not_accept_model_supplied_trace_id(monkeypatch):
    executor = AsyncMock(side_effect=AssertionError("must not execute"))
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)

    with pytest.raises(ValueError, match="未知参数: trace_id"):
        await ontology_tools.invoke_ontology_tool(
            _service(),
            9,
            ontology_tools.QUERY_CAPABILITY_TOOL,
            _arguments(trace_id="model-forged-trace"),
            {"id": 5, "role": "user"},
            ontology_context=_context(),
            semantic_runtime=_runtime(),
        )

    executor.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("datasource_id", [None, 0, -1])
async def test_query_capability_rejects_invalid_datasource_without_execution(
    monkeypatch, datasource_id
):
    executor = AsyncMock(side_effect=AssertionError("invalid datasource must not execute"))
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)

    result = await ontology_tools.invoke_ontology_tool(
        _service(),
        9,
        ontology_tools.QUERY_CAPABILITY_TOOL,
        _arguments(),
        {"id": 5, "role": "user"},
        ontology_context=_context(),
        semantic_runtime=_runtime(datasource_id),
    )

    executor.assert_not_awaited()
    assert result["validation"]["valid"] is False
    assert result["execution"]["executed"] is False
    assert result["execution"]["attempted"] is False
    assert result["execution"]["status"] == "validation_blocked"
    assert result["execution"]["error_category"] == "datasource"
    assert result["execution_trace"]["datasource_id"] == datasource_id
    assert result["execution_trace"]["query_capability_execution"] == {
        "executed": False,
        "attempted": False,
        "status": "validation_blocked",
        "mode": "validation_blocked",
        "error_category": "datasource",
    }


@pytest.mark.asyncio
async def test_query_capability_trace_fields_are_not_overwritten_by_node(
    monkeypatch,
):
    safe_sql = "SELECT COUNT(*) AS application_count FROM loan_application LIMIT 1000"
    executor = AsyncMock(
        return_value={
            "sql_result": [],
            "sql_error": None,
            "compiled_sql": safe_sql,
            "sql_text": safe_sql,
            "final_answer": "查询完成。",
            "execution_trace": {
                "query_capability_key": "forged_capability",
                "target_object": "ForgedObject",
                "read_only": False,
                "used_assets": ["forged_asset"],
                "warnings": ["forged_warning"],
            },
        }
    )
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)

    result = await ontology_tools.invoke_ontology_tool(
        _service(),
        9,
        ontology_tools.QUERY_CAPABILITY_TOOL,
        _arguments(),
        {"id": 5, "role": "user"},
        ontology_context=_context(),
        semantic_runtime=_runtime(),
    )

    executor.assert_awaited_once()
    node_input_trace = executor.await_args.args[0]["execution_trace"]
    result_trace = result["execution_trace"]
    assert result_trace["query_capability_key"] == node_input_trace["query_capability_key"]
    assert result_trace["target_object"] == node_input_trace["target_object"]
    assert result_trace["read_only"] is True
    assert result_trace["used_assets"] == node_input_trace["used_assets"]
    assert result_trace["warnings"] == node_input_trace["warnings"]
    assert result_trace["query_capability_key"] != "forged_capability"
    assert result_trace["target_object"] != "ForgedObject"
    assert result_trace["used_assets"] != ["forged_asset"]
    assert result_trace["warnings"] != ["forged_warning"]


@pytest.mark.asyncio
async def test_query_capability_rejects_non_object_logic_form(monkeypatch):
    executor = AsyncMock(side_effect=AssertionError("invalid LogicForm must not execute"))
    monkeypatch.setattr(ontology_tools, "sql_execute_node", executor)

    with pytest.raises(ValueError, match="LogicForm 必须是对象"):
        await ontology_tools.invoke_ontology_tool(
            _service(),
            9,
            ontology_tools.QUERY_CAPABILITY_TOOL,
            _arguments(logic_form=1),
            {"id": 5, "role": "user"},
            ontology_context=_context(),
            semantic_runtime=_runtime(),
        )

    executor.assert_not_awaited()
