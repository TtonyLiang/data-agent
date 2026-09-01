from app.db.risk_schema import RISK_WORKFLOW_TABLE_STATEMENTS
from app.main import app


def test_risk_workflow_tables_cover_the_delivery_loop():
    ddl = "\n".join(RISK_WORKFLOW_TABLE_STATEMENTS)

    for table in (
        "risk_issue",
        "risk_evidence",
        "risk_issue_review",
        "risk_report",
        "risk_report_version",
        "decision_audit_event",
        "decision_audit_head",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl
    assert "ontology_release_id" in ddl
    assert "previous_hash" in ddl and "event_hash" in ddl
    assert "event_count" in ddl and "head_hash" in ddl


def test_risk_workflow_router_is_registered():
    paths = {route.path for route in app.routes}

    assert "/api/risk/domains/{domain_id}/issues" in paths
    assert "/api/risk/domains/{domain_id}/reports" in paths
    assert "/api/risk/domains/{domain_id}/audit/verify" in paths
