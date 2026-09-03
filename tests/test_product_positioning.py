from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_primary_product_position_is_enterprise_ontology_digital_twin():
    chinese_readme = (ROOT / "README_CN.md").read_text(encoding="utf-8")
    app_shell = (ROOT / "frontend/src/App.vue").read_text(encoding="utf-8")
    project_design = (ROOT / "docs/project-design.md").read_text(encoding="utf-8")

    expected = "Ontology 驱动的企业运营数字孪生与智能决策平台"
    assert expected in chinese_readme
    assert "企业本体数字孪生与智能决策平台" in app_shell
    assert "企业智能中枢和决策引擎" in project_design
    assert "Agent 负责在具体场景中与用户交互和调用能力" in project_design
    assert "财税报告交付、贷款风控和智能问数" in project_design


def test_loan_risk_demo_is_explicitly_non_production():
    roadmap = (ROOT / "docs/risk-report-delivery-roadmap.md").read_text(encoding="utf-8")
    demo = (ROOT / "examples/loan/RISK_DELIVERY_DEMO.md").read_text(encoding="utf-8")

    assert "合成演示" in roadmap
    assert "不构成真实" in roadmap
    assert "验证技术能力" in demo
