from app.agent.ontology_evidence import (
    build_ontology_evidence,
    ontology_schema_terms,
    score_ontology_schema_text,
    select_ontology_context,
)


def _context():
    return {
        "domain": {"id": 7, "name": "贷款风控"},
        "release": {"version": 1},
        "object_types": [
            {
                "object_key": "LoanApplication",
                "name": "贷款申请",
                "description": "客户提交的贷款申请",
                "properties": [
                    {"property_key": "application_status", "name": "申请状态"},
                    {"property_key": "application_id", "name": "申请编号"},
                ],
            },
            {
                "object_key": "Customer",
                "name": "客户",
                "description": "贷款申请人",
                "properties": [{"property_key": "customer_id", "name": "客户编号"}],
            },
        ],
        "link_types": [
            {
                "link_key": "customer_submits_application",
                "name": "客户提交贷款申请",
                "source_object_key": "Customer",
                "target_object_key": "LoanApplication",
            }
        ],
        "actions": [
            {
                "action_key": "approve_loan_application",
                "name": "审批贷款申请",
                "target_object_key": "LoanApplication",
                "description": "完成贷款申请审批",
                "parameters": [],
            }
        ],
    }


def test_action_match_brings_target_object_into_schema_evidence():
    context = _context()

    evidence = build_ontology_evidence("查看审批进度", context)

    assert [item["action_key"] for item in evidence["actions"]] == ["approve_loan_application"]
    assert [item["object_key"] for item in evidence["object_types"]] == ["LoanApplication"]

    score, reasons = score_ontology_schema_text(
        ["loan_application", "贷款申请记录"],
        ontology_schema_terms(context, evidence),
    )

    assert score > 0
    assert "企业本体对象命中: 贷款申请" in reasons


def test_logic_form_context_contains_only_matched_ontology_definitions():
    selected = select_ontology_context(
        _context(),
        build_ontology_evidence("查看审批进度", _context()),
    )

    assert [item["object_key"] for item in selected["object_types"]] == ["LoanApplication"]
    assert [item["action_key"] for item in selected["actions"]] == ["approve_loan_application"]
    assert selected["link_types"] == []
