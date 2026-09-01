import json

import pytest

from examples.loan import seed_loan_risk_delivery as seed


def demo_objects(*, overdue_days=45, remaining_principal=42000, dti=0.62):
    return [
        {
            "id": 71,
            "object_type_key": "LoanAccount",
            "primary_value": "700001",
            "display_name": "LN-20250001",
            "properties": json.dumps(
                {
                    "loan_id": 700001,
                    "loan_no": "LN-20250001",
                    "customer_id": 200001,
                    "current_status": "overdue",
                    "remaining_principal": remaining_principal,
                    "current_overdue_days": overdue_days,
                    "overdue_bucket": "M2" if overdue_days > 60 else "M1",
                    "is_written_off": 0,
                }
            ),
        },
        {
            "id": 61,
            "object_type_key": "CustomerRiskSnapshot",
            "primary_value": "600001",
            "display_name": "200001-2026年08月风险快照",
            "properties": {
                "snapshot_id": 600001,
                "snapshot_label": "200001-2026年08月风险快照",
                "customer_id": 200001,
                "stat_month": "2026-08-01",
                "outstanding_principal": remaining_principal,
                "dti": dti,
                "max_dpd_12m": overdue_days,
                "risk_grade": "C",
                "model_pd": 0.071,
                "fraud_risk_level": "low",
                "is_blacklist_hit": False,
            },
        },
    ]


class FakeDB:
    def __init__(
        self,
        *,
        domains=None,
        release=True,
        actor=True,
        objects=None,
        existing=None,
    ):
        self.domains = domains or [
            {"id": 4, "domain_key": "loan_risk", "name": "贷款风控", "status": "active"}
        ]
        self.release = (
            {
                "id": 9,
                "version": 3,
                "name": "贷款风控 V3",
                "definition_hash": "a" * 64,
                "created_at": "2026-09-01T09:00:00",
            }
            if release
            else None
        )
        self.actor = (
            {
                "id": 8,
                "username": "wenqu_demo_admin",
                "display_name": "问渠演示管理员",
                "role": "admin",
                "status": "active",
            }
            if actor
            else None
        )
        self.objects = demo_objects() if objects is None else objects
        self.existing = existing or []
        self.queries = []

    async def execute_query(self, sql, params=None):
        self.queries.append((sql, params or {}))
        if "FROM semantic_domain" in sql:
            return list(self.domains)
        if "FROM ontology_release" in sql:
            return [self.release] if self.release else []
        if "FROM app_user" in sql:
            return [self.actor] if self.actor else []
        if "FROM ontology_object o" in sql:
            return list(self.objects)
        if "FROM risk_issue i" in sql:
            return list(self.existing)
        raise AssertionError(f"unexpected query: {sql}")


class FakeWorkflow:
    def __init__(self):
        self.calls = []
        self.next_issue_id = 100

    async def create_issue(self, payload, user):
        issue_id = self.next_issue_id
        self.next_issue_id += 1
        self.calls.append(("create_issue", payload, user))
        return {"id": issue_id, "version": 1, **payload.model_dump()}

    async def add_evidence(self, domain_id, issue_id, payload, user):
        self.calls.append(("add_evidence", domain_id, issue_id, payload, user))
        return {"id": len(self.calls), **payload.model_dump()}

    async def review_issue(self, domain_id, issue_id, payload, user):
        self.calls.append(("review_issue", domain_id, issue_id, payload, user))
        return {
            "issue": {
                "id": issue_id,
                "status": seed.review_target_status("open", payload.action),
                "version": 2,
            }
        }


def plans_from_rows(rows):
    objects = {
        (row["object_type_key"], str(row["primary_value"])): {
            **row,
            "properties": seed._json_object(row["properties"], "properties"),
        }
        for row in rows
    }
    return seed.build_issue_plans(4, objects)


def test_build_issue_plans_derives_values_and_uses_stable_idempotency_keys():
    plans = plans_from_rows(
        demo_objects(overdue_days=61, remaining_principal=12345.67, dti=0.73)
    )
    m1, high_dti = plans

    assert m1.issue.issue_key == "demo_m1_collection_700001"
    assert m1.issue.detected_value == {
        "current_overdue_days": 61,
        "remaining_principal": 12345.67,
        "is_written_off": False,
    }
    assert m1.issue.severity == "critical"
    assert m1.issue.assignee == "wenqu_demo_admin"
    assert {item.evidence_type for item in m1.evidence} == {
        "ontology_object",
        "query",
        "metric",
    }
    m1_query = next(item for item in m1.evidence if item.evidence_type == "query")
    assert m1_query.content["row"]["current_overdue_days"] == 61
    assert m1_query.content["row"]["remaining_principal"] == 12345.67
    assert m1.target_status == "in_review"
    assert m1.review.action == "start_review"

    assert high_dti.issue.issue_key == "demo_high_dti_600001"
    assert high_dti.issue.detected_value["dti"] == 0.73
    assert high_dti.issue.severity == "high"
    dti_metric = next(
        item for item in high_dti.evidence if item.evidence_type == "metric"
    )
    assert dti_metric.content["value"] == 0.73
    assert dti_metric.content["policy_status"] == "technical_demo_only"
    assert high_dti.target_status == "needs_info"
    assert high_dti.review.action == "request_info"


@pytest.mark.asyncio
async def test_load_seed_context_rejects_missing_release():
    with pytest.raises(RuntimeError, match="尚无 Ontology release"):
        await seed.load_seed_context(FakeDB(release=False))


@pytest.mark.asyncio
async def test_load_seed_context_rejects_missing_required_object():
    with pytest.raises(RuntimeError, match="CustomerRiskSnapshot/600001"):
        await seed.load_seed_context(FakeDB(objects=demo_objects()[:1]))


@pytest.mark.asyncio
async def test_preview_only_reads_and_reports_review_plan():
    db = FakeDB()
    workflow = FakeWorkflow()

    summary = await seed.seed_loan_risk_delivery(
        preview=True,
        db=db,
        workflow=workflow,
    )

    assert summary["domain_id"] == 4
    assert summary["created"] == 0
    assert summary["skipped"] == 0
    assert summary["planned"] == 2
    assert [item["status"] for item in summary["issues"]] == [
        "in_review",
        "needs_info",
    ]
    assert [item["evidence_count"] for item in summary["issues"]] == [3, 3]
    assert workflow.calls == []
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in db.queries)


@pytest.mark.asyncio
async def test_existing_issue_keys_skip_all_service_writes():
    existing = [
        {
            "id": 101,
            "issue_key": "demo_m1_collection_700001",
            "status": "in_review",
            "version": 2,
            "evidence_count": 3,
        },
        {
            "id": 102,
            "issue_key": "demo_high_dti_600001",
            "status": "needs_info",
            "version": 2,
            "evidence_count": 3,
        },
    ]
    workflow = FakeWorkflow()

    summary = await seed.seed_loan_risk_delivery(
        db=FakeDB(existing=existing),
        workflow=workflow,
    )

    assert summary["created"] == 0
    assert summary["skipped"] == 2
    assert summary["planned"] == 0
    assert [item["issue_id"] for item in summary["issues"]] == [101, 102]
    assert [item["evidence_count"] for item in summary["issues"]] == [3, 3]
    assert workflow.calls == []


@pytest.mark.asyncio
async def test_write_executes_three_evidence_items_and_planned_review_per_issue():
    workflow = FakeWorkflow()

    summary = await seed.seed_loan_risk_delivery(db=FakeDB(), workflow=workflow)

    assert summary["created"] == 2
    assert summary["skipped"] == 0
    assert [item["issue_id"] for item in summary["issues"]] == [100, 101]
    assert [item["status"] for item in summary["issues"]] == [
        "in_review",
        "needs_info",
    ]
    assert [call[0] for call in workflow.calls].count("create_issue") == 2
    assert [call[0] for call in workflow.calls].count("add_evidence") == 6
    review_calls = [call for call in workflow.calls if call[0] == "review_issue"]
    assert [call[3].action for call in review_calls] == ["start_review", "request_info"]
    assert [call[3].expected_version for call in review_calls] == [1, 1]


def test_cli_defaults_to_write_mode():
    assert seed.parse_args([]).preview is False
    assert seed.parse_args(["--preview"]).preview is True
