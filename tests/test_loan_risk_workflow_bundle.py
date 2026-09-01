import json
from pathlib import Path

from app.models.risk_workflow import (
    EvidenceCreatePayload,
    ReportCreatePayload,
    ReportVersionCreatePayload,
    RiskIssueCreatePayload,
    RiskReviewPayload,
)

BUNDLE_PATH = Path(__file__).parents[1] / "examples/loan/risk-workflow-bundle.json"


def load_bundle():
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


def test_bundle_metadata_marks_the_scenario_as_technical_validation():
    bundle = load_bundle()

    assert bundle["format"] == "wenqu-risk-workflow"
    assert bundle["version"] == 1
    assert bundle["created_on"] == "2026-09-01"
    assert bundle["ontology"]["bundle_path"] == "examples/loan/ontology-bundle.json"
    assert "技术验证" in bundle["disclaimer"]
    assert "不代表真实信贷政策" in bundle["disclaimer"]


def test_bundle_defines_critical_and_high_risk_issues_bound_to_ontology_objects():
    issues = load_bundle()["issues"]
    by_ref = {item["ref"]: item for item in issues}

    assert set(by_ref) == {"m1_plus_collection_risk", "high_dti_manual_review_risk"}
    assert {item["request"]["severity"] for item in issues} == {"critical", "high"}
    assert by_ref["m1_plus_collection_risk"]["request"]["title"] == "M1+逾期催收风险"
    assert by_ref["high_dti_manual_review_risk"]["request"]["title"] == (
        "高 DTI 人工复核风险"
    )

    for issue in issues:
        subject = issue["subject"]
        source_context = issue["request"]["source_context"]
        assert source_context["object_type_key"] == subject["object_type_key"]
        assert source_context["primary_value"] == subject["primary_value"]
        assert source_context["display_name"]


def test_each_issue_has_snapshot_metric_rule_and_query_evidence_with_lineage():
    issues = load_bundle()["issues"]
    expected_types = {"ontology_object", "metric", "manual", "query"}

    for issue in issues:
        evidence_requests = [item["request"] for item in issue["evidence"]]
        assert {item["evidence_type"] for item in evidence_requests} == expected_types
        for evidence in evidence_requests:
            assert evidence["title"]
            assert evidence["trace_id"]
            assert len(evidence["trace_id"]) <= 64
            assert evidence["source_ref"]
            assert isinstance(evidence["content"], dict)
            assert evidence["content"]


def test_reviews_cover_confirm_and_request_info_decisions():
    issues = load_bundle()["issues"]
    reviews = {item["ref"]: item["review"]["request"] for item in issues}

    assert reviews["m1_plus_collection_risk"]["action"] == "confirm"
    assert reviews["high_dti_manual_review_risk"]["action"] == "request_info"
    assert all(review["comment"] for review in reviews.values())


def test_report_has_release_bound_v1_reviewed_v2_and_finalize_target():
    bundle = load_bundle()
    issue_refs = [item["ref"] for item in bundle["issues"]]
    report = bundle["report"]
    versions = report["versions"]

    assert report["request"]["name"] == "贷款组合风险复核报告"
    assert report["issue_refs"] == issue_refs
    assert [item["ref"] for item in versions] == ["V1", "V2"]
    assert report["finalize"]["version_ref"] == "V2"
    for version in versions:
        assert version["bind_current_ontology_release"] is True
        assert version["request"]["snapshot"]["change_summary"]
        assert version["request"]["snapshot"]["findings"]
        assert version["request"]["markdown"]
    assert versions[0]["request"]["snapshot"]["review_status"] == "pending"
    assert versions[1]["request"]["snapshot"]["review_status"] == "reviewed"


def test_api_requests_match_risk_workflow_models():
    bundle = load_bundle()
    issues = bundle["issues"]

    for index, issue in enumerate(issues, start=1):
        RiskIssueCreatePayload.model_validate(
            {**issue["request"], "domain_id": 1, "subject_object_id": index}
        )
        for evidence in issue["evidence"]:
            EvidenceCreatePayload.model_validate(evidence["request"])
        RiskReviewPayload.model_validate(issue["review"]["request"])

    report = bundle["report"]
    versions = report["versions"]
    ReportCreatePayload.model_validate(
        {
            **report["request"],
            **versions[0]["request"],
            "domain_id": 1,
            "issue_ids": [1, 2],
        }
    )
    ReportVersionCreatePayload.model_validate(
        {**versions[1]["request"], "issue_ids": [1, 2]}
    )


def test_expected_audit_count_covers_every_mutating_workflow_step():
    bundle = load_bundle()
    issues = bundle["issues"]
    expected_mutations = (
        len(issues)
        + sum(len(item["evidence"]) for item in issues)
        + len(issues)
        + 1
        + len(bundle["report"]["versions"])
        + 1
    )

    assert expected_mutations == 16
    assert bundle["expected_audit_events"] == expected_mutations
