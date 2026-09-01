from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_primary_product_position_is_risk_report_delivery():
    chinese_readme = (ROOT / "README_CN.md").read_text(encoding="utf-8")
    app_shell = (ROOT / "frontend/src/App.vue").read_text(encoding="utf-8")
    project_design = (ROOT / "docs/project-design.md").read_text(encoding="utf-8")

    expected = "财税 AI 报告交付与风险决策平台"
    assert expected in chinese_readme
    assert "AI报告交付与风险决策平台" in app_shell
    assert "风险事项 -> 证据 -> 人工复核" in project_design
    assert "Ontology" in project_design


def test_loan_risk_demo_is_explicitly_non_production():
    roadmap = (ROOT / "docs/risk-report-delivery-roadmap.md").read_text(encoding="utf-8")
    demo = (ROOT / "examples/loan/RISK_DELIVERY_DEMO.md").read_text(encoding="utf-8")

    assert "合成演示" in roadmap
    assert "不构成真实" in roadmap
    assert "验证技术能力" in demo
