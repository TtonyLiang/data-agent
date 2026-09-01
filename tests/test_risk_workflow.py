import json
from datetime import date

import pytest
from pydantic import ValidationError

from app.models.risk_workflow import (
    EvidenceCreatePayload,
    ReportCreatePayload,
    ReportVersionCreatePayload,
    RiskIssueCreatePayload,
    RiskReviewPayload,
)
from app.services import decision_audit_service, risk_workflow_service
from app.services.decision_audit_service import (
    DecisionAuditService,
    canonical_sha256,
)
from app.services.risk_workflow_service import (
    RiskWorkflowConflict,
    RiskWorkflowService,
    review_target_status,
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


def issue_row(**overrides):
    row = {
        "id": 11,
        "domain_id": 4,
        "ontology_release_id": 7,
        "subject_object_id": 22,
        "issue_key": "loan.high_debt_ratio",
        "category": "credit_risk",
        "severity": "high",
        "status": "open",
        "title": "借款人负债率偏高",
        "description": "负债收入比超过策略阈值",
        "rule_key": "debt_ratio_limit",
        "detected_value": json.dumps({"ratio": 0.72}),
        "expected_value": json.dumps({"max_ratio": 0.55}),
        "source_context": json.dumps({"trace_id": "trace-1"}),
        "assignee": "reviewer-a",
        "version": 1,
    }
    row.update(overrides)
    return row


def evidence_row(**overrides):
    content = {"metric": "debt_ratio", "value": 0.72}
    row = {
        "id": 31,
        "domain_id": 4,
        "issue_id": 11,
        "ontology_release_id": 9,
        "ontology_release_version": 3,
        "ontology_release_hash": "a" * 64,
        "evidence_type": "metric",
        "title": "负债收入比指标",
        "description": "",
        "source_ref": "metric://debt_ratio/L-001",
        "content": json.dumps(content),
        "trace_id": "trace-1",
        "checksum": canonical_sha256(content),
        "created_by": 8,
        "created_at": "2026-09-01T10:00:00",
    }
    row.update(overrides)
    return row


def review_row(**overrides):
    before_state = {"status": "open", "version": 1}
    after_state = {"status": "confirmed", "version": 2}
    row = {
        "id": 41,
        "domain_id": 4,
        "issue_id": 11,
        "ontology_release_id": 9,
        "ontology_release_version": 3,
        "ontology_release_hash": "a" * 64,
        "review_action": "confirm",
        "before_status": "open",
        "after_status": "confirmed",
        "before_state": json.dumps(before_state),
        "after_state": json.dumps(after_state),
        "reviewer_id": 9,
        "reviewer": "reviewer",
        "comment": "已核对收入证明",
        "created_at": "2026-09-01T10:05:00",
    }
    row.update(overrides)
    return row


class RecordingAudit:
    def __init__(self):
        self.events = []

    async def append_in_session(self, _session, **kwargs):
        self.events.append(kwargs)
        return {"id": len(self.events), **kwargs}


class WorkflowSession:
    def __init__(self, *, release=True, issues=None, evidence=None, reviews=None):
        self.release = (
            {
                "id": 9,
                "version": 3,
                "name": "贷款风控 V3",
                "definition_hash": "a" * 64,
            }
            if release
            else None
        )
        self.issues = {int(row["id"]): dict(row) for row in (issues or [])}
        self.evidence = [dict(row) for row in (evidence or [])]
        self.reviews = [dict(row) for row in (reviews or [])]
        self.executed = []
        self.next_id = 100

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}
        self.executed.append((sql, dict(params)))
        if sql.startswith(
            "SELECT id, version, name, definition_hash, created_at FROM ontology_release"
        ):
            return FakeResult([self.release] if self.release else [])
        if sql.startswith("SELECT id FROM risk_issue WHERE domain_id"):
            return FakeResult([])
        if sql.startswith("SELECT id FROM risk_report WHERE domain_id"):
            return FakeResult([])
        if sql.startswith("SELECT id FROM ontology_object"):
            return FakeResult([{"id": params["object_id"]}])
        if "FROM risk_issue i LEFT JOIN ontology_release" in sql and "i.id =" in sql:
            row = self.issues.get(int(params["issue_id"]))
            return FakeResult(
                [
                    {
                        **row,
                        "ontology_release_version": 2,
                        "ontology_release_hash": "b" * 64,
                    }
                ]
                if row
                else []
            )
        if "FROM risk_issue i LEFT JOIN ontology_release" in sql and "i.id IN" in sql:
            rows = [
                {
                    **row,
                    "ontology_release_version": 2,
                    "ontology_release_hash": "b" * 64,
                }
                for issue_id, row in self.issues.items()
                if issue_id in {value for key, value in params.items() if key.startswith("issue_")}
            ]
            return FakeResult(rows)
        if "FROM risk_evidence e LEFT JOIN ontology_release" in sql:
            issue_ids = {
                value for key, value in params.items() if key.startswith("snapshot_issue_")
            }
            return FakeResult(
                [dict(row) for row in self.evidence if row["issue_id"] in issue_ids]
            )
        if "FROM risk_issue_review v LEFT JOIN ontology_release" in sql:
            issue_ids = {
                value for key, value in params.items() if key.startswith("snapshot_issue_")
            }
            return FakeResult(
                [dict(row) for row in self.reviews if row["issue_id"] in issue_ids]
            )
        if sql.startswith("UPDATE risk_issue SET status"):
            row = self.issues[int(params["issue_id"])]
            if int(row["version"]) != int(params["version"]):
                return FakeResult(rowcount=0)
            row["status"] = params["status"]
            row["version"] = int(row["version"]) + 1
            return FakeResult(rowcount=1)
        if sql.startswith("INSERT INTO"):
            inserted_id = self.next_id
            self.next_id += 1
            return FakeResult(lastrowid=inserted_id, rowcount=1)
        raise AssertionError(f"unexpected SQL: {sql}")


class WorkflowDB:
    def __init__(self, session):
        self.session = session

    async def execute_in_transaction(self, callback):
        return await callback(self.session)


def test_payload_validation_and_review_state_machine():
    with pytest.raises(ValidationError, match="开始日期"):
        ReportCreatePayload(
            domain_id=4,
            report_key="loan.risk_report",
            name="贷款风险报告",
            report_type="loan_risk",
            period_start=date(2026, 8, 31),
            period_end=date(2026, 8, 1),
            issue_ids=[11],
        )
    with pytest.raises(ValidationError, match="不能重复"):
        ReportCreatePayload(
            domain_id=4,
            report_key="loan.risk_report",
            name="贷款风险报告",
            report_type="loan_risk",
            issue_ids=[11, 11],
        )
    with pytest.raises(ValidationError):
        ReportCreatePayload(
            domain_id=4,
            report_key="loan.empty_report",
            name="空报告",
            report_type="loan_risk",
            issue_ids=[],
        )
    with pytest.raises(ValidationError):
        ReportVersionCreatePayload(issue_ids=[])

    assert review_target_status("open", "start_review") == "in_review"
    assert review_target_status("in_review", "confirm") == "confirmed"
    assert review_target_status("confirmed", "resolve") == "resolved"
    assert review_target_status("resolved", "reopen") == "open"
    with pytest.raises(RiskWorkflowConflict, match="不允许"):
        review_target_status("open", "resolve")


def test_canonical_checksum_is_stable_and_order_independent():
    first = {"metric": "debt_ratio", "value": 0.72, "sources": ["query-1", "ledger"]}
    second = {"sources": ["query-1", "ledger"], "value": 0.72, "metric": "debt_ratio"}

    assert canonical_sha256(first) == canonical_sha256(second)
    assert len(canonical_sha256(first)) == 64


@pytest.mark.asyncio
async def test_issue_creation_requires_a_published_release(monkeypatch):
    session = WorkflowSession(release=False)
    service = RiskWorkflowService()
    service.audit = RecordingAudit()
    monkeypatch.setattr(
        risk_workflow_service, "get_management_db", lambda: WorkflowDB(session)
    )

    with pytest.raises(ValueError, match="尚未发布 Ontology release"):
        await service.create_issue(
            RiskIssueCreatePayload(
                domain_id=4,
                issue_key="loan.high_debt_ratio",
                category="credit_risk",
                severity="high",
                title="借款人负债率偏高",
            ),
            {"id": 8, "username": "analyst"},
        )

    assert not any(sql.startswith("INSERT INTO risk_issue") for sql, _ in session.executed)


@pytest.mark.asyncio
async def test_review_records_before_after_state_and_increments_version(monkeypatch):
    session = WorkflowSession(issues=[issue_row()])
    service = RiskWorkflowService()
    audit = RecordingAudit()
    service.audit = audit
    monkeypatch.setattr(
        risk_workflow_service, "get_management_db", lambda: WorkflowDB(session)
    )

    result = await service.review_issue(
        4,
        11,
        RiskReviewPayload(action="confirm", comment="收入证明已复核", expected_version=1),
        {"id": 8, "username": "reviewer-a", "role": "user"},
    )

    assert result["issue"]["status"] == "confirmed"
    assert result["issue"]["version"] == 2
    assert result["review"]["before_status"] == "open"
    assert result["review"]["after_status"] == "confirmed"
    assert result["review"]["ontology_release_id"] == 9
    assert result["review"]["before_state"]["ontology_release_version"] == 2
    assert result["review"]["after_state"]["ontology_release_hash"] == "b" * 64
    review_params = next(
        params
        for sql, params in session.executed
        if sql.startswith("INSERT INTO risk_issue_review")
    )
    assert json.loads(review_params["before_state"])["version"] == 1
    assert json.loads(review_params["after_state"])["version"] == 2
    assert audit.events[0]["event_type"] == "issue.reviewed"


@pytest.mark.asyncio
async def test_regular_user_cannot_self_review_or_review_another_assignee(monkeypatch):
    service = RiskWorkflowService()
    service.audit = RecordingAudit()

    for issue, user, message in (
        (
            issue_row(created_by=8, assignee="reviewer-a"),
            {"id": 8, "username": "reviewer-a", "role": "user"},
            "不能复核自己的事项",
        ),
        (
            issue_row(created_by=7, assignee="reviewer-b"),
            {"id": 8, "username": "reviewer-a", "role": "user"},
            "不是该风险事项的指派复核人",
        ),
    ):
        session = WorkflowSession(issues=[issue])
        monkeypatch.setattr(
            risk_workflow_service, "get_management_db", lambda: WorkflowDB(session)
        )
        with pytest.raises(PermissionError, match=message):
            await service.review_issue(
                4,
                11,
                RiskReviewPayload(action="start_review", expected_version=1),
                user,
            )


@pytest.mark.asyncio
async def test_admin_can_review_unassigned_issue(monkeypatch):
    session = WorkflowSession(issues=[issue_row(created_by=8, assignee=None)])
    service = RiskWorkflowService()
    service.audit = RecordingAudit()
    monkeypatch.setattr(
        risk_workflow_service, "get_management_db", lambda: WorkflowDB(session)
    )

    result = await service.review_issue(
        4,
        11,
        RiskReviewPayload(action="start_review", comment="管理员接管", expected_version=1),
        {"id": 8, "username": "admin", "role": "admin"},
    )

    assert result["issue"]["status"] == "in_review"


@pytest.mark.asyncio
async def test_evidence_checksum_uses_canonical_content(monkeypatch):
    session = WorkflowSession(issues=[issue_row()])
    service = RiskWorkflowService()
    service.audit = RecordingAudit()
    monkeypatch.setattr(
        risk_workflow_service, "get_management_db", lambda: WorkflowDB(session)
    )
    content = {"sql": "SELECT debt_ratio", "row": {"application_id": "L-001"}}

    evidence = await service.add_evidence(
        4,
        11,
        EvidenceCreatePayload(
            evidence_type="query",
            title="负债率查询结果",
            content=content,
            trace_id="trace-1",
        ),
        {"id": 8, "username": "analyst"},
    )

    assert evidence["checksum"] == canonical_sha256(content)
    insert_params = next(
        params for sql, params in session.executed if sql.startswith("INSERT INTO risk_evidence")
    )
    assert json.loads(insert_params["content"]) == content
    assert insert_params["ontology_release_id"] == 9


@pytest.mark.asyncio
async def test_report_creation_freezes_issue_snapshot_and_creates_v1(monkeypatch):
    session = WorkflowSession(
        issues=[issue_row()], evidence=[evidence_row()], reviews=[review_row()]
    )
    service = RiskWorkflowService()
    audit = RecordingAudit()
    service.audit = audit
    monkeypatch.setattr(
        risk_workflow_service, "get_management_db", lambda: WorkflowDB(session)
    )

    result = await service.create_report(
        ReportCreatePayload(
            domain_id=4,
            report_key="loan.august_risk_report",
            name="8 月贷款风险报告",
            report_type="loan_risk",
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            issue_ids=[11],
            snapshot={"portfolio": {"applications": 120}},
            markdown="# 贷款风险报告\n\n发现 1 项高风险事项。",
        ),
        {"id": 8, "username": "analyst"},
    )

    assert result["report"]["current_version"] == 1
    version = result["version"]
    assert version["version"] == 1
    assert version["ontology_release_id"] == 9
    assert version["issue_ids"] == [11]
    snapshot = version["snapshot_json"]
    assert snapshot["ontology_release"] == {
        "id": 9,
        "version": 3,
        "definition_hash": "a" * 64,
    }
    assert snapshot["issues"][0]["status"] == "open"
    assert snapshot["issues"][0]["detected_value"] == {"ratio": 0.72}
    assert snapshot["issues"][0]["evidence"][0]["source_ref"] == (
        "metric://debt_ratio/L-001"
    )
    assert snapshot["issues"][0]["evidence"][0]["content"]["value"] == 0.72
    assert snapshot["issues"][0]["evidence"][0]["checksum"] == evidence_row()["checksum"]
    assert snapshot["issues"][0]["reviews"][0]["review_action"] == "confirm"
    assert snapshot["issues"][0]["reviews"][0]["before_state"]["status"] == "open"
    assert snapshot["issues"][0]["reviews"][0]["after_state"]["status"] == "confirmed"
    assert snapshot["issues"][0]["reviews"][0]["reviewer"] == "reviewer"
    assert version["snapshot_json"]["context"]["portfolio"]["applications"] == 120
    assert len(version["content_hash"]) == 64
    version_params = next(
        params
        for sql, params in session.executed
        if sql.startswith("INSERT INTO risk_report_version")
    )
    assert json.loads(version_params["snapshot_json"])["issues"][0]["id"] == 11
    assert [event["event_type"] for event in audit.events] == [
        "report.created",
        "report.version.created",
    ]
    assert audit.events[1]["payload"]["ontology_release"]["definition_hash"] == "a" * 64


class WorkflowReadDB:
    async def execute_query(self, sql, params=None):
        if "FROM risk_issue i LEFT JOIN ontology_release" in sql:
            return [
                {
                    **issue_row(),
                    "ontology_release_version": 2,
                    "ontology_release_hash": "b" * 64,
                }
            ]
        if "FROM risk_evidence e LEFT JOIN ontology_release" in sql:
            return [evidence_row()]
        if "FROM risk_issue_review v LEFT JOIN ontology_release" in sql:
            return [review_row()]
        if sql.startswith("SELECT id, version, name, definition_hash, created_at"):
            return [
                {
                    "id": 9,
                    "version": 3,
                    "name": "贷款风控 V3",
                    "definition_hash": "a" * 64,
                }
            ]
        if "GROUP BY status, severity" in sql:
            return [
                {"status": "open", "severity": "high", "count": 2},
                {"status": "confirmed", "severity": "critical", "count": 1},
                {"status": "needs_info", "severity": "medium", "count": 3},
            ]
        if "FROM risk_report" in sql and "GROUP BY status" in sql:
            return [
                {"status": "draft", "count": 1},
                {"status": "finalized", "count": 1},
            ]
        if "COUNT(*) AS count FROM decision_audit_event" in sql:
            return [{"count": 16}]
        raise AssertionError(f"unexpected read SQL: {sql}")


@pytest.mark.asyncio
async def test_issue_detail_and_summary_response_contract(monkeypatch):
    monkeypatch.setattr(
        risk_workflow_service, "get_management_db", lambda: WorkflowReadDB()
    )
    service = RiskWorkflowService()

    detail = await service.get_issue(4, 11)
    assert detail["id"] == 11
    assert detail["ontology_release_version"] == 2
    assert detail["evidence"][0]["content"]["metric"] == "debt_ratio"
    assert detail["reviews"][0]["review_action"] == "confirm"
    assert "issue" not in detail

    summary = await service.get_summary(4)
    assert summary["latest_release"]["definition_hash"] == "a" * 64
    assert summary["counts"] == {
        "issues": 6,
        "open_issues": 2,
        "high_risk_issues": 3,
        "pending_review": 5,
        "reports": 2,
        "audit_events": 16,
    }
    assert summary["status_counts"] == {"open": 2, "confirmed": 1, "needs_info": 3}
    assert summary["severity_counts"] == {"high": 2, "critical": 1, "medium": 3}
    assert summary["report_status_counts"] == {"draft": 1, "finalized": 1}


class AuditSession:
    def __init__(self, events, head):
        self.events = events
        self.head = head

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}
        if sql.startswith("SELECT id FROM semantic_domain"):
            return FakeResult([{"id": params["domain_id"]}])
        if sql.startswith("SELECT event_count, head_hash FROM decision_audit_head"):
            value = self.head.get(params["domain_id"])
            return FakeResult([dict(value)] if value else [])
        if sql.startswith("INSERT INTO decision_audit_event"):
            event = {
                "id": len(self.events) + 1,
                "domain_id": params["domain_id"],
                "sequence_no": params["sequence_no"],
                "event_type": params["event_type"],
                "entity_type": params["entity_type"],
                "entity_id": params["entity_id"],
                "actor_id": params["actor_id"],
                "actor": params["actor"],
                "ontology_release_id": params["ontology_release_id"],
                "payload_json": params["payload_json"],
                "previous_hash": params["previous_hash"],
                "event_hash": params["event_hash"],
            }
            self.events.append(event)
            return FakeResult(lastrowid=event["id"], rowcount=1)
        if sql.startswith("INSERT INTO decision_audit_head"):
            self.head[params["domain_id"]] = {
                "event_count": params["event_count"],
                "head_hash": params["head_hash"],
            }
            return FakeResult(rowcount=1)
        raise AssertionError(f"unexpected audit SQL: {sql}")


class AuditDB:
    def __init__(self):
        self.events = []
        self.head = {}
        self.session = AuditSession(self.events, self.head)

    async def execute_in_transaction(self, callback):
        return await callback(self.session)

    async def execute_query(self, sql, params=None):
        if "FROM decision_audit_event" in sql:
            return [dict(event) for event in self.events]
        if "FROM decision_audit_head" in sql:
            value = self.head.get((params or {})["domain_id"])
            return [dict(value)] if value else []
        raise AssertionError(f"unexpected audit query: {sql}")


@pytest.mark.asyncio
async def test_decision_audit_chain_verifies_and_detects_tampering(monkeypatch):
    db = AuditDB()
    monkeypatch.setattr(decision_audit_service, "get_management_db", lambda: db)
    service = DecisionAuditService()

    first = await service.append(
        domain_id=4,
        event_type="issue.created",
        entity_type="risk_issue",
        entity_id=11,
        actor_id=8,
        actor="analyst",
        ontology_release_id=9,
        payload={"status": "open"},
    )
    second = await service.append(
        domain_id=4,
        event_type="issue.reviewed",
        entity_type="risk_issue",
        entity_id=11,
        actor_id=9,
        actor="reviewer",
        ontology_release_id=9,
        payload={"before": "open", "after": "confirmed"},
    )

    assert first["previous_hash"] is None
    assert second["previous_hash"] == first["event_hash"]
    assert first["recorded_at"].endswith("+00:00")
    assert await service.verify_chain(4) == {
        "valid": True,
        "checked_events": 2,
        "head_hash": second["event_hash"],
        "broken_event_id": None,
        "reason": None,
    }
    listed = await service.list_events(4)
    assert listed[0]["payload"] == {"status": "open"}
    assert listed[0]["recorded_at"] == first["recorded_at"]

    tampered = json.loads(db.events[0]["payload_json"])
    tampered["payload"]["status"] = "dismissed"
    db.events[0]["payload_json"] = json.dumps(tampered)
    verification = await service.verify_chain(4)
    assert verification["valid"] is False
    assert verification["broken_event_id"] == 1
    assert verification["reason"] == "event_hash 校验失败"


@pytest.mark.asyncio
async def test_decision_audit_head_detects_tail_deletion(monkeypatch):
    db = AuditDB()
    monkeypatch.setattr(decision_audit_service, "get_management_db", lambda: db)
    service = DecisionAuditService()

    for event_type in ("issue.created", "issue.reviewed"):
        await service.append(
            domain_id=4,
            event_type=event_type,
            entity_type="risk_issue",
            entity_id=11,
            actor_id=8,
            actor="reviewer",
            ontology_release_id=9,
            payload={"event_type": event_type},
        )

    db.events.pop()
    verification = await service.verify_chain(4)

    assert verification["valid"] is False
    assert verification["reason"] == "审计事件数量与链头锚点不一致: 1 != 2"
