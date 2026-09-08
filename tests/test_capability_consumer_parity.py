import json
from unittest.mock import AsyncMock, Mock

import pytest

from app.agent import ontology_tools
from app.models.capability_access import CapabilityInvokePayload
from app.models.knowledge import (
    LogicForm,
    SemanticDomain,
    SemanticMapping,
    SemanticMetric,
    SemanticRuntime,
)
from app.services import capability_access_service as access_module
from app.services.capability_access_service import CapabilityAccessService

DOMAIN_ID = 9
EXECUTION_AGENT_ID = 17
MODEL_RELEASE_ID = 40
CAPABILITY_KEY = "query_loan_application"


def _runtime() -> SemanticRuntime:
    return SemanticRuntime(
        domain=SemanticDomain(
            id=DOMAIN_ID,
            agent_id=EXECUTION_AGENT_ID,
            datasource_id=23,
            domain_key="loan_risk",
            name="贷款风控",
        ),
        metrics=[
            SemanticMetric(
                domain_id=DOMAIN_ID,
                metric_key="application_count",
                name="申请笔数",
                formula_sql="COUNT(*)",
                base_table="loan_application",
                dimensions=["channel"],
                metadata={"object_key": "LoanApplication"},
            )
        ],
        mappings=[
            SemanticMapping(
                domain_id=DOMAIN_ID,
                asset_type="dimension",
                asset_key="channel",
                table_name="loan_application",
                column_name="channel",
                role="dimension",
            )
        ],
    )


def _ontology_context() -> dict:
    ontology_release = {
        "id": 4,
        "version": 2,
        "definition_hash": "a" * 64,
    }
    return {
        "domain": {
            "id": DOMAIN_ID,
            "domain_key": "loan_risk",
            "name": "贷款风控",
        },
        "model_release": {
            "id": MODEL_RELEASE_ID,
            "version": 5,
            "model_hash": "c" * 64,
            "status": "active",
        },
        "semantic_snapshot": {"id": 30, "snapshot_hash": "b" * 64},
        "ontology_release": ontology_release,
        "release": ontology_release,
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
        "warnings": [],
    }


def _logic_form() -> LogicForm:
    return LogicForm(
        domain_key="loan_risk",
        metrics=["application_count"],
        dimensions=["channel"],
    )


class AuditDB:
    def __init__(self, grant: dict):
        self.grant = grant
        self.audit_inserts: list[dict] = []
        self.grant_updates: list[dict] = []

    async def execute_query(self, sql, params=None):
        if "FROM capability_grant" in sql:
            return [dict(self.grant)]
        if sql.startswith("UPDATE capability_grant SET model_release_id"):
            self.grant_updates.append(dict(params or {}))
            self.grant.update(
                {
                    "model_release_id": params["model_release_id"],
                    "contract_hash": params["contract_hash"],
                    "contract_json": params["contract_json"],
                }
            )
            return []
        raise AssertionError(f"unexpected query: {sql}")

    async def execute_insert(self, sql, params=None):
        if "INSERT INTO capability_invocation_audit" not in sql:
            raise AssertionError(f"unexpected insert: {sql}")
        self.audit_inserts.append(dict(params or {}))
        return len(self.audit_inserts)


@pytest.mark.asyncio
async def test_internal_and_external_consumers_have_query_capability_parity(monkeypatch):
    context = _ontology_context()
    runtime = _runtime()
    logic_form = _logic_form()
    safe_sql = (
        "SELECT `channel`, COUNT(*) AS application_count "
        "FROM loan_application GROUP BY `channel` LIMIT 1000"
    )
    rows = [
        {"channel": "APP", "application_count": 8},
        {"channel": "WEB", "application_count": 5},
    ]
    execution_states: list[dict] = []

    async def execute_sql(state):
        execution_states.append(dict(state))
        return {
            "sql_result": rows,
            "sql_error": None,
            "compiled_sql": safe_sql,
            "sql_text": safe_sql,
            "final_answer": "查询完成，共 2 条结果。详细数据已在结果表中展示。",
            "execution_trace": dict(state["execution_trace"]),
        }

    monkeypatch.setattr(ontology_tools, "sql_execute_node", execute_sql)
    ontology_service = Mock()
    ontology_service.execute_action = AsyncMock(
        side_effect=AssertionError("read-only parity test must not execute actions")
    )

    internal_result = await ontology_tools.invoke_ontology_tool(
        ontology_service,
        DOMAIN_ID,
        ontology_tools.QUERY_CAPABILITY_TOOL,
        {
            "capability_key": CAPABILITY_KEY,
            "logic_form": logic_form.model_dump(mode="python"),
        },
        {"id": 7, "username": "validator", "role": "user"},
        ontology_context=context,
        semantic_runtime=runtime,
    )

    grant = {
        "id": 19,
        "client_id": 8,
        "domain_id": DOMAIN_ID,
        "capability_key": CAPABILITY_KEY,
        "execution_agent_id": EXECUTION_AGENT_ID,
        "status": "active",
    }
    audit_db = AuditDB(grant)
    access_service = CapabilityAccessService()
    load_context = AsyncMock(return_value=(context, runtime))
    monkeypatch.setattr(access_module, "get_management_db", lambda: audit_db)
    monkeypatch.setattr(access_module, "get_ontology_service", lambda: ontology_service)
    monkeypatch.setattr(access_service, "_load_execution_context", load_context)

    external_response = await access_service.invoke(
        {"id": 8, "client_key": "cap_external", "name": "外部贷款助手"},
        CAPABILITY_KEY,
        CapabilityInvokePayload(
            domain_id=DOMAIN_ID,
            model_release_id=MODEL_RELEASE_ID,
            logic_form=logic_form,
        ),
    )
    external_result = external_response["result"]

    load_context.assert_awaited_once_with(
        DOMAIN_ID,
        EXECUTION_AGENT_ID,
        CAPABILITY_KEY,
        model_release_id=MODEL_RELEASE_ID,
    )
    assert len(execution_states) == 2
    assert {state["domain_id"] for state in execution_states} == {DOMAIN_ID}
    assert {state["agent_id"] for state in execution_states} == {EXECUTION_AGENT_ID}

    assert internal_result["capability"] == external_result["capability"]
    assert internal_result["validation"] == external_result["validation"]
    assert internal_result["compiled_plan"]["sql"] == execution_states[0]["compiled_sql"]
    assert internal_result["executed_sql"] == safe_sql
    assert "sql" not in external_result["compiled_plan"]
    assert "executed_sql" not in external_result["compiled_plan"]
    assert "executed_sql" not in external_result
    assert internal_result["sql_result"] == external_result["sql_result"] == rows
    assert internal_result["final_answer"] == external_result["final_answer"]

    internal_trace = internal_result["execution_trace"]
    external_trace = external_result["execution_trace"]
    assert internal_trace["trace_id"] != external_trace["trace_id"]
    assert external_response["trace_id"] == external_trace["trace_id"]
    for field in ("model_release", "semantic_snapshot", "ontology_release"):
        assert internal_trace[field] == external_trace[field] == context[field]
    assert internal_trace["query_capability_key"] == CAPABILITY_KEY
    assert external_trace["query_capability_key"] == CAPABILITY_KEY
    assert internal_trace["executed_sql"] == safe_sql
    assert "executed_sql" not in external_trace

    assert len(audit_db.audit_inserts) == 1
    assert len(audit_db.grant_updates) == 1
    assert audit_db.grant_updates[0]["model_release_id"] == MODEL_RELEASE_ID
    frozen_contract = json.loads(audit_db.grant_updates[0]["contract_json"])
    assert frozen_contract["data_policy"]["strategy"] == "live_source"
    assert frozen_contract["data_policy"]["as_of"] == {"mode": "invocation_time"}
    assert frozen_contract["data_policy"]["uses_twin_snapshot"] is False
    audit = audit_db.audit_inserts[0]
    assert audit["trace_id"] == external_trace["trace_id"]
    assert audit["client_id"] == 8
    assert audit["grant_id"] == 19
    assert audit["domain_id"] == DOMAIN_ID
    assert audit["capability_key"] == CAPABILITY_KEY
    assert audit["execution_agent_id"] == EXECUTION_AGENT_ID
    assert audit["model_release_id"] == MODEL_RELEASE_ID
    assert audit["semantic_snapshot_id"] == 30
    assert audit["ontology_release_id"] == 4
    assert audit["status"] == "succeeded"
    assert audit["row_count"] == 2
    assert json.loads(audit["request_summary"])["metrics"] == ["application_count"]
    assert json.loads(audit["request_summary"])["dimensions"] == ["channel"]
    assert json.loads(audit["result_summary"])["columns"] == [
        "channel",
        "application_count",
    ]
    ontology_service.execute_action.assert_not_awaited()
