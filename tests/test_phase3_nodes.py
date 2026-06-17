import pytest

from app.agent.nodes.phase3 import (
    planner_node,
    python_analyze_node,
    python_generate_node,
    report_generator_node,
    semantic_check_node,
)
from app.services.python_executor import PythonExecutionError, RestrictedLocalPythonExecutor


def _runtime():
    return {
        "domain": {
            "id": 1,
            "agent_id": 1,
            "datasource_id": 1,
            "domain_key": "loan_risk",
            "name": "贷款风控",
            "description": "",
            "status": "active",
        },
        "concepts": [],
        "relations": [],
        "metrics": [
            {
                "id": 1,
                "domain_id": 1,
                "metric_key": "m1_plus_rate",
                "name": "M1+逾期率",
                "formula_sql": "SUM({base}.`m1_plus_flag`) / COUNT(1)",
                "base_table": "loan_snapshot",
                "time_field": "loan_snapshot.snapshot_date",
                "dimensions": ["vintage"],
            }
        ],
        "rules": [],
        "mappings": [
            {
                "id": 1,
                "domain_id": 1,
                "asset_type": "dimension",
                "asset_key": "vintage",
                "table_name": "loan_snapshot",
                "column_name": "vintage",
                "role": "dimension",
            }
        ],
        "templates": [],
    }


@pytest.mark.asyncio
async def test_semantic_check_passes_for_valid_logic_form():
    result = await semantic_check_node(
        {
            "logic_form": {
                "metrics": ["m1_plus_rate"],
                "dimensions": ["vintage"],
                "filters": [],
                "time_range": {"type": "relative", "period": "last_3_months"},
            },
            "semantic_runtime": _runtime(),
            "compiled_sql": "SELECT `vintage`, 1 AS `m1_plus_rate` FROM `loan_snapshot`",
        }
    )

    assert result["semantic_check"]["valid"] is True
    assert result["semantic_check"]["errors"] == []


@pytest.mark.asyncio
async def test_python_analysis_and_report_are_structured():
    state = {
        "question": "按 Vintage 看 M1+",
        "logic_form": {"metrics": ["m1_plus_rate"], "dimensions": ["vintage"]},
        "compiled_sql": "SELECT vintage, m1_plus_rate FROM loan_snapshot",
        "sql_result": [
            {"vintage": "2026-01", "m1_plus_rate": 0.12},
            {"vintage": "2026-02", "m1_plus_rate": 0.18},
        ],
    }

    state.update(await planner_node(state))
    state.update(await python_generate_node(state))
    state.update(await python_analyze_node(state))
    state.update(await report_generator_node(state))

    assert state["python_result"]["status"] == "success"
    assert state["python_result"]["row_count"] == 2
    assert state["plan"]["mode"] == "local_basic_profile"
    assert state["plan"]["numeric_columns"] == ["m1_plus_rate"]
    assert "数值字段统计 1 个" in state["python_result"]["computed_items"]
    assert state["report_payload"]["mode_label"] == "本地基础画像"
    assert state["report_payload"]["title"] == "m1_plus_rate 按 vintage 分析"
    assert "执行摘要" in state["report_payload"]["executive_summary"]["title"]
    assert state["report_payload"]["analysis_process"]["steps"][0]["title"] == "步骤1：SQL 查询"
    assert state["report_payload"]["charts"]
    assert state["report_payload"]["tables"]
    assert "首位 vintage 为 2026-01" in state["report_payload"]["summary"]
    assert "合计为 0.3" in " ".join(state["report_payload"]["executive_summary"]["bullets"])
    assert "共返回 2 行数据" in state["final_answer"]


def test_restricted_executor_rejects_unapproved_imports():
    executor = RestrictedLocalPythonExecutor()

    with pytest.raises(PythonExecutionError):
        executor.execute("import os\nprint('{}')", [])
