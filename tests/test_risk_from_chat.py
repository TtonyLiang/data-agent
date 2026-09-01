import json

import pytest

from app.api.risk_workflow import router
from app.models.risk_workflow import ChatRiskIssueCreatePayload
from app.services import risk_workflow_service
from app.services.decision_audit_service import canonical_sha256
from app.services.risk_workflow_service import (
    RiskWorkflowConflict,
    RiskWorkflowNotFound,
    RiskWorkflowService,
)


class FakeResult:
    def __init__(self, rows=None, *, lastrowid=0, rowcount=0):
        self.rows = rows or []
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class RecordingAudit:
    def __init__(self):
        self.events = []

    async def append_in_session(self, _session, **kwargs):
        self.events.append(kwargs)
        return {"id": len(self.events), **kwargs}


class ChatWorkflowSession:
    def __init__(
        self,
        *,
        assistants=None,
        questions=None,
        domain_agent_id=12,
        subject=None,
        duplicate=False,
    ):
        self.assistants = [dict(row) for row in (assistants or [])]
        self.questions = [dict(row) for row in (questions or [])]
        self.domain_agent_id = domain_agent_id
        self.subject = subject
        self.duplicate = duplicate
        self.executed = []
        self.inserts = []
        self.next_id = 1000

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}
        self.executed.append((sql, dict(params)))
        if sql.startswith("SELECT id, agent_id FROM semantic_domain"):
            return FakeResult([{"id": params["domain_id"], "agent_id": self.domain_agent_id}])
        if sql.startswith(
            "SELECT id, version, name, definition_hash, created_at FROM ontology_release"
        ):
            return FakeResult(
                [
                    {
                        "id": 33,
                        "version": 4,
                        "name": "贷款风控 V4",
                        "definition_hash": "a" * 64,
                    }
                ]
            )
        if sql.startswith("SELECT id FROM risk_issue WHERE domain_id"):
            return FakeResult([{"id": 1}] if self.duplicate else [])
        if "FROM chat_history WHERE" in sql and "role = 'assistant'" in sql:
            rows = [
                row
                for row in self.assistants
                if int(row["agent_id"]) == int(params["agent_id"])
                and row["session_id"] == params["session_id"]
                and (
                    "user_id" not in params
                    or int(row["user_id"]) == int(params["user_id"])
                )
            ]
            return FakeResult(sorted(rows, key=lambda row: int(row["id"]), reverse=True))
        if "FROM chat_history WHERE" in sql and "role = 'user'" in sql:
            rows = [
                row
                for row in self.questions
                if int(row["agent_id"]) == int(params["agent_id"])
                and row["session_id"] == params["session_id"]
                and int(row["id"]) < int(params["assistant_id"])
                and (
                    "question_user_id" not in params
                    or int(row["user_id"]) == int(params["question_user_id"])
                )
            ]
            return FakeResult(sorted(rows, key=lambda row: int(row["id"]), reverse=True)[:1])
        if sql.startswith("SELECT o.id, o.primary_value"):
            if self.subject is None or int(self.subject["id"]) != int(params["object_id"]):
                return FakeResult([])
            return FakeResult([dict(self.subject)])
        if sql.startswith("INSERT INTO risk_issue") or sql.startswith(
            "INSERT INTO risk_evidence"
        ):
            inserted_id = self.next_id
            self.next_id += 1
            self.inserts.append((sql, dict(params)))
            return FakeResult(lastrowid=inserted_id, rowcount=1)
        raise AssertionError(f"unexpected SQL: {sql}")


class WorkflowDB:
    def __init__(self, session):
        self.session = session
        self.transaction_count = 0

    async def execute_in_transaction(self, callback):
        self.transaction_count += 1
        return await callback(self.session)


def assistant_row(
    *,
    history_id=20,
    user_id=8,
    trace_id="trace-owned",
    sql_result=None,
    with_analysis=True,
):
    report_payload = {
        "title": "高负债客户分析",
        "summary": "发现负债率超过阈值的贷款申请。",
        "status": "completed",
        "row_count": 75,
        "limitations": ["仅基于当前快照"],
        "markdown": "x" * 50_000,
    }
    python_result = {
        "status": "success",
        "analysis_mode": "ranking",
        "metrics": [{"key": "debt_ratio", "label": "负债率"}],
        "insights": ["最高负债率为 0.82"],
        "raw_rows": [{"large": "y" * 20_000}],
    }
    plan_payload = {
        "mode": "ranking",
        "analysis_steps": ["排序", "阈值比较"],
        "raw_prompt": "z" * 20_000,
    }
    return {
        "id": history_id,
        "agent_id": 12,
        "user_id": user_id,
        "session_id": "session-loan-risk",
        "content": "共发现 75 条高负债贷款申请。",
        "logic_form": json.dumps({"metrics": ["debt_ratio"]}, ensure_ascii=False),
        "compiled_sql": "SELECT application_id, debt_ratio FROM loan_application",
        "sql_text": "SELECT application_id, debt_ratio FROM loan_application",
        "sql_result": json.dumps(
            sql_result
            if sql_result is not None
            else [{"application_id": f"L-{index:03d}", "debt_ratio": 0.7} for index in range(75)],
            ensure_ascii=False,
        ),
        "execution_trace": json.dumps({"trace_id": trace_id}),
        "plan_payload": json.dumps(plan_payload) if with_analysis else None,
        "semantic_check": json.dumps({"valid": True}),
        "python_result": json.dumps(python_result) if with_analysis else None,
        "report_payload": json.dumps(report_payload) if with_analysis else None,
        "task_id": "task-loan-risk",
        "turn_id": "turn-loan-risk",
        "created_at": "2026-09-01T10:00:00",
    }


def question_row(*, history_id=19, user_id=8, content="查询负债率超过 70% 的贷款"):
    return {
        "id": history_id,
        "agent_id": 12,
        "user_id": user_id,
        "session_id": "session-loan-risk",
        "content": content,
        "created_at": "2026-09-01T09:59:00",
    }


def payload(**overrides):
    data = {
        "domain_id": 4,
        "agent_id": 12,
        "session_id": "session-loan-risk",
        "subject_object_id": 51,
        "issue_key": "loan.chat.high_debt_ratio",
        "category": "credit_risk",
        "severity": "high",
        "title": "贷款申请负债率偏高",
        "description": "由问数结果转入人工复核。",
        "rule_key": "debt_ratio_limit",
        "expected_value": {"max_ratio": 0.7},
        "assignee": "reviewer-a",
    }
    data.update(overrides)
    return ChatRiskIssueCreatePayload(**data)


@pytest.mark.asyncio
async def test_regular_user_creates_issue_with_three_evidence_types_in_one_transaction(
    monkeypatch,
):
    session = ChatWorkflowSession(
        assistants=[
            assistant_row(history_id=21, user_id=9, trace_id="trace-other"),
            assistant_row(),
        ],
        questions=[
            question_row(history_id=18, user_id=9, content="其他用户问题"),
            question_row(),
        ],
        subject={
            "id": 51,
            "object_type_key": "LoanApplication",
            "object_type_name": "贷款申请",
            "primary_value": "L-001",
            "display_name": "贷款申请 L-001",
            "properties": json.dumps({"debt_ratio": 0.82}),
            "version": 3,
        },
    )
    db = WorkflowDB(session)
    service = RiskWorkflowService()
    audit = RecordingAudit()
    service.audit = audit
    monkeypatch.setattr(risk_workflow_service, "get_management_db", lambda: db)

    result = await service.create_issue_from_chat(
        payload(),
        {"id": 8, "username": "analyst", "role": "user"},
    )

    assert db.transaction_count == 1
    assert result["source"]["chat_history_id"] == 20
    assert result["issue"]["detected_value"]["row_count"] == 75
    assert [item["evidence_type"] for item in result["evidence"]] == [
        "query",
        "metric",
        "ontology_object",
    ]
    query_content = result["evidence"][0]["content"]
    assert query_content["question"] == "查询负债率超过 70% 的贷款"
    assert len(query_content["result_preview"]) == 50
    assert query_content["chat_history_id"] == 20
    metric_content = result["evidence"][1]["content"]
    assert metric_content["report"]["title"] == "高负债客户分析"
    assert metric_content["analysis"]["metrics"][0]["key"] == "debt_ratio"
    assert "report_payload" not in metric_content
    assert "python_result" not in metric_content
    assert "plan_payload" not in metric_content
    assert len(json.dumps(metric_content, ensure_ascii=False)) < 32_000
    assert result["evidence"][2]["content"]["properties"] == {"debt_ratio": 0.82}
    assert all(
        evidence["checksum"] == canonical_sha256(evidence["content"])
        for evidence in result["evidence"]
    )
    assert [event["event_type"] for event in audit.events] == [
        "issue.created",
        "evidence.created",
        "evidence.created",
        "evidence.created",
    ]
    assistant_query = next(
        (sql, params)
        for sql, params in session.executed
        if "role = 'assistant'" in sql
    )
    assert "user_id = :user_id" in assistant_query[0]
    assert assistant_query[1]["user_id"] == 8


@pytest.mark.asyncio
async def test_admin_trace_match_uses_compact_result_row_count_and_preview(monkeypatch):
    compact_result = {
        "row_count": 500,
        "truncated": True,
        "preview_rows": [{"application_id": f"L-{index:03d}"} for index in range(120)],
    }
    session = ChatWorkflowSession(
        assistants=[
            assistant_row(history_id=31, trace_id="trace-latest", with_analysis=False),
            assistant_row(
                history_id=30,
                trace_id="trace-target",
                sql_result=compact_result,
                with_analysis=False,
            ),
        ],
        questions=[question_row(history_id=29)],
    )
    db = WorkflowDB(session)
    service = RiskWorkflowService()
    service.audit = RecordingAudit()
    monkeypatch.setattr(risk_workflow_service, "get_management_db", lambda: db)

    result = await service.create_issue_from_chat(
        payload(trace_id="trace-target", subject_object_id=None),
        {"id": 1, "username": "admin", "role": "admin"},
    )

    assert result["source"]["chat_history_id"] == 30
    assert result["source"]["trace_id"] == "trace-target"
    assert result["issue"]["detected_value"]["row_count"] == 500
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["content"]["row_count"] == 500
    assert len(result["evidence"][0]["content"]["result_preview"]) == 50
    assistant_params = next(
        params for sql, params in session.executed if "role = 'assistant'" in sql
    )
    assert "user_id" not in assistant_params


@pytest.mark.asyncio
async def test_regular_user_cannot_read_another_users_session(monkeypatch):
    session = ChatWorkflowSession(
        assistants=[assistant_row(user_id=9)],
        questions=[question_row(user_id=9)],
    )
    db = WorkflowDB(session)
    service = RiskWorkflowService()
    service.audit = RecordingAudit()
    monkeypatch.setattr(risk_workflow_service, "get_management_db", lambda: db)

    with pytest.raises(RiskWorkflowNotFound, match="没有可用"):
        await service.create_issue_from_chat(
            payload(subject_object_id=None),
            {"id": 8, "username": "analyst", "role": "user"},
        )

    assert not session.inserts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql_result",
    [None, [], {"row_count": 0, "truncated": True, "preview_rows": []}],
)
async def test_missing_or_empty_query_result_is_rejected(monkeypatch, sql_result):
    assistant = assistant_row(with_analysis=False)
    assistant["sql_result"] = json.dumps(sql_result) if sql_result is not None else None
    session = ChatWorkflowSession(
        assistants=[assistant],
        questions=[question_row()],
    )
    db = WorkflowDB(session)
    service = RiskWorkflowService()
    service.audit = RecordingAudit()
    monkeypatch.setattr(risk_workflow_service, "get_management_db", lambda: db)

    with pytest.raises(ValueError, match="没有查询结果"):
        await service.create_issue_from_chat(
            payload(subject_object_id=None),
            {"id": 8, "username": "analyst", "role": "user"},
        )

    assert not session.inserts


@pytest.mark.asyncio
async def test_domain_agent_mismatch_and_duplicate_issue_key_are_rejected(monkeypatch):
    mismatch_session = ChatWorkflowSession(domain_agent_id=99)
    mismatch_db = WorkflowDB(mismatch_session)
    service = RiskWorkflowService()
    service.audit = RecordingAudit()
    monkeypatch.setattr(
        risk_workflow_service, "get_management_db", lambda: mismatch_db
    )

    with pytest.raises(ValueError, match="智能体不一致"):
        await service.create_issue_from_chat(
            payload(subject_object_id=None),
            {"id": 8, "username": "analyst", "role": "user"},
        )

    duplicate_session = ChatWorkflowSession(duplicate=True)
    duplicate_db = WorkflowDB(duplicate_session)
    monkeypatch.setattr(
        risk_workflow_service, "get_management_db", lambda: duplicate_db
    )
    with pytest.raises(RiskWorkflowConflict, match="标识已存在"):
        await service.create_issue_from_chat(
            payload(subject_object_id=None),
            {"id": 8, "username": "analyst", "role": "user"},
        )


def test_from_chat_endpoint_is_registered_before_dynamic_issue_route():
    paths = [route.path for route in router.routes]

    assert "/domains/{domain_id}/issues/from-chat" in paths
    assert paths.index("/domains/{domain_id}/issues/from-chat") < paths.index(
        "/domains/{domain_id}/issues/{issue_id}"
    )
