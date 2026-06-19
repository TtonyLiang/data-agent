import pytest
from types import SimpleNamespace

import app.agent.nodes.analysis_pipeline as analysis_pipeline
from app.agent.nodes.analysis_pipeline import (
    infer_analysis_mode,
    planner_node,
    python_analyze_node,
    python_generate_node,
    report_generator_node,
    semantic_check_node,
)
from app.agent.nodes.lf_repair import repair_logic_form
from app.services import python_executor
from app.services.python_executor import (
    HighIsolationPythonExecutor,
    PythonExecutionError,
    RestrictedLocalPythonExecutor,
    WorkerPythonExecutor,
    build_python_executor,
)


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
    assert state["plan"]["mode"] == "ranking"
    assert state["plan"]["numeric_columns"] == ["m1_plus_rate"]
    assert "数值字段统计 1 个" in state["python_result"]["computed_items"]
    assert state["report_payload"]["mode_label"] == "分组对比分析"
    assert state["report_payload"]["title"] == "m1_plus_rate 按 vintage 分析"
    assert "执行摘要" in state["report_payload"]["executive_summary"]["title"]
    assert state["report_payload"]["analysis_process"]["steps"][0]["title"] == "步骤1：SQL 查询"
    assert state["report_payload"]["charts"]
    assert state["report_payload"]["charts"][0]["chart_kind"] == "bar"
    assert state["report_payload"]["charts"][0]["echarts_option"]["series"][0]["type"] == "bar"
    assert state["report_payload"]["tables"]
    assert state["report_payload"]["markdown"]
    assert state["python_result"]["charts"]
    assert state["python_result"]["insights"]
    assert "首位 vintage 为 2026-01" in state["report_payload"]["summary"]
    assert "合计为 0.3" in " ".join(state["report_payload"]["executive_summary"]["bullets"])
    assert "m1_plus_rate 按 vintage 分析" in state["final_answer"]


@pytest.mark.asyncio
async def test_python_generate_uses_llm_code_when_safe(monkeypatch):
    class FakePromptService:
        async def resolve(self, prompt_key, default_template, **kwargs):
            return default_template.format(**kwargs["variables"])

    class FakeChunk:
        def __init__(self, content):
            self.content = content
            self.additional_kwargs = {}

    class FakeLlmService:
        async def resolve_agent_chat_kwargs(self, agent_id):
            return {}

        async def achat_stream(self, messages, **kwargs):
            yield FakeChunk(
                "import json\n"
                "result = {'row_count': len(rows), 'analysis_mode': 'custom', 'insights': ['LLM脚本已执行']}\n"
                "print(json.dumps(result, ensure_ascii=False))"
            )

    monkeypatch.setattr(analysis_pipeline, "get_prompt_service", lambda: FakePromptService())
    monkeypatch.setattr(analysis_pipeline, "get_llm_service", lambda: FakeLlmService())

    result = await python_generate_node(
        {
            "agent_id": 1,
            "question": "分析申请趋势",
            "plan": {"mode": "trend"},
            "sql_result": [{"month": "2026-01", "cnt": 10}],
        }
    )

    assert result["python_result"]["generation_source"] == "llm_python_generate"
    assert "LLM脚本已执行" in result["python_code"]


@pytest.mark.asyncio
async def test_python_generate_falls_back_when_llm_code_is_unsafe(monkeypatch):
    class FakePromptService:
        async def resolve(self, prompt_key, default_template, **kwargs):
            return default_template.format(**kwargs["variables"])

    class FakeChunk:
        def __init__(self, content):
            self.content = content
            self.additional_kwargs = {}

    class FakeLlmService:
        async def resolve_agent_chat_kwargs(self, agent_id):
            return {}

        async def achat_stream(self, messages, **kwargs):
            yield FakeChunk("import os\nprint(json.dumps({'row_count': len(rows)}))")

    monkeypatch.setattr(analysis_pipeline, "get_prompt_service", lambda: FakePromptService())
    monkeypatch.setattr(analysis_pipeline, "get_llm_service", lambda: FakeLlmService())

    result = await python_generate_node(
        {
            "agent_id": 1,
            "question": "分析申请趋势",
            "plan": {"mode": "trend"},
            "sql_result": [{"month": "2026-01", "cnt": 10}],
        }
    )

    assert result["python_result"]["generation_source"] == "safe_template"
    assert result["python_result"]["generation_error"]
    assert "ANALYSIS_MODE = \"trend\"" in result["python_code"]


@pytest.mark.asyncio
async def test_python_analyze_repairs_failed_script_with_llm(monkeypatch):
    class FakePromptService:
        async def resolve(self, prompt_key, default_template, **kwargs):
            return default_template.format(**kwargs["variables"])

    class FakeChunk:
        def __init__(self, content):
            self.content = content
            self.additional_kwargs = {"reasoning_content": ""}

    class FakeLlmService:
        async def resolve_agent_chat_kwargs(self, agent_id):
            return {}

        async def achat_stream(self, messages, **kwargs):
            assert "上一次 Python 分析脚本执行失败" in messages[-1]["content"]
            yield FakeChunk(
                "import json\n"
                "result = {'row_count': len(rows), 'analysis_mode': 'repaired', 'insights': ['修复后成功']}\n"
                "print(json.dumps(result, ensure_ascii=False))"
            )

    monkeypatch.setattr(analysis_pipeline, "get_prompt_service", lambda: FakePromptService())
    monkeypatch.setattr(analysis_pipeline, "get_llm_service", lambda: FakeLlmService())

    result = await python_analyze_node(
        {
            "agent_id": 1,
            "question": "分析申请趋势",
            "plan": {"mode": "trend"},
            "sql_result": [{"month": "2026-01", "cnt": 10}],
            "python_code": "import json\nraise ValueError('boom')\nprint(json.dumps({'row_count': len(rows)}, ensure_ascii=False))",
        }
    )

    assert result["python_result"]["status"] == "success"
    assert result["python_result"]["analysis_mode"] == "repaired"
    assert result["python_result"]["repair_count"] == 1
    assert result["python_result"]["repair_attempts"][0]["ok"] is False
    assert result["python_result"]["repair_attempts"][1]["source"] == "llm_repair"
    assert "修复后成功" in result["python_result"]["insights"]
    assert "修复后成功" in result["python_code"]


@pytest.mark.asyncio
async def test_report_marks_analysis_failed_after_python_retries_exhausted(monkeypatch):
    class FakePromptService:
        async def resolve(self, prompt_key, default_template, **kwargs):
            return default_template.format(**kwargs["variables"])

    class FakeChunk:
        def __init__(self, content):
            self.content = content
            self.additional_kwargs = {}

    class FakeLlmService:
        async def resolve_agent_chat_kwargs(self, agent_id):
            return {}

        async def achat_stream(self, messages, **kwargs):
            yield FakeChunk("import json\nraise ValueError('still broken')\nprint(json.dumps({'row_count': len(rows)}))")

    monkeypatch.setattr(analysis_pipeline, "get_prompt_service", lambda: FakePromptService())
    monkeypatch.setattr(analysis_pipeline, "get_llm_service", lambda: FakeLlmService())
    monkeypatch.setattr(analysis_pipeline, "_build_analysis_code", lambda mode="profile": "import json\nraise ValueError('template broken')\nprint(json.dumps({'row_count': len(rows)}))")

    state = {
        "agent_id": 1,
        "question": "分析申请趋势",
        "logic_form": {"metrics": ["application_count"], "dimensions": ["month"]},
        "plan": {"mode": "trend", "mode_label": "趋势分析"},
        "sql_result": [{"month": "2026-01", "application_count": 10}],
        "python_code": "import json\nraise ValueError('boom')\nprint(json.dumps({'row_count': len(rows)}))",
    }

    state.update(await python_analyze_node(state))
    state.update(await report_generator_node(state))

    assert state["python_result"]["status"] == "failed"
    assert len(state["python_result"]["repair_attempts"]) >= 2
    assert state["report_payload"]["status"] == "analysis_failed"
    assert "重试后仍未成功" in state["report_payload"]["summary"]
    assert "分析执行提示" in " ".join(section["title"] for section in state["report_payload"]["sections"])


@pytest.mark.asyncio
async def test_report_accepts_structured_metric_and_dimension_items():
    state = {
        "question": "贷款排名前三的申请区域是什么，分别申请了多少笔",
        "logic_form": {"metrics": ["application_count"], "dimensions": ["application_region"]},
        "compiled_sql": "SELECT region AS application_region, COUNT(*) AS application_count FROM loan_application GROUP BY region",
        "sql_result": [
            {"application_region": "华南", "application_count": 4423},
            {"application_region": "东北", "application_count": 4358},
        ],
        "plan": {"mode": "ranking", "mode_label": "排名分析"},
        "python_result": {
            "status": "success",
            "row_count": 2,
            "metrics": [{"field": "application_count", "name": "申请笔数"}],
            "dimensions": [{"field": "application_region", "name": "申请区域"}],
            "insights": ["华南申请笔数最高。"],
            "charts": [
                {
                    "title": "申请笔数区域排名",
                    "type": "bar",
                    "data": [
                        {"label": "华南", "value": 4423},
                        {"label": "东北", "value": 4358},
                    ],
                }
            ],
        },
    }

    state.update(await report_generator_node(state))

    assert state["report_payload"]["summary"]
    assert "首位 application_region 为 华南" in state["report_payload"]["summary"]
    assert state["report_payload"]["charts"][0]["title"] == "申请笔数区域排名"
    assert state["report_payload"]["charts"][0]["chart_kind"] == "bar"


@pytest.mark.asyncio
async def test_report_chart_kind_preserves_python_declared_pie():
    state = {
        "question": "各产品申请占比如何",
        "logic_form": {"metrics": ["application_count"], "dimensions": ["application_product_type"]},
        "compiled_sql": "SELECT product_type AS application_product_type, COUNT(*) AS application_count FROM loan_application GROUP BY product_type",
        "sql_result": [
            {"application_product_type": "消费贷", "application_count": 214},
            {"application_product_type": "经营贷", "application_count": 232},
        ],
        "plan": {"mode": "distribution", "mode_label": "结构分布分析"},
        "python_result": {
            "status": "success",
            "row_count": 2,
            "metrics": [{"field": "application_count", "name": "申请笔数"}],
            "dimensions": [{"field": "application_product_type", "name": "产品类型"}],
            "charts": [
                {
                    "title": "各产品申请占比",
                    "type": "pie",
                    "data": [
                        {"label": "消费贷", "value": 214},
                        {"label": "经营贷", "value": 232},
                    ],
                    "echarts_option": {
                        "series": [{"type": "pie", "data": [{"name": "消费贷", "value": 214}, {"name": "经营贷", "value": 232}]}]
                    },
                }
            ],
        },
    }

    state.update(await report_generator_node(state))

    assert state["report_payload"]["charts"][0]["chart_kind"] == "pie"
    assert state["report_payload"]["charts"][0]["type"] == "pie"


@pytest.mark.asyncio
async def test_distribution_mode_fallback_chart_prefers_pie():
    state = {
        "question": "各贷款产品申请量占比如何",
        "enhanced_question": "各贷款产品申请量占比如何",
        "logic_form": {"metrics": ["application_count"], "dimensions": ["application_product_type"]},
        "compiled_sql": "SELECT product_type AS application_product_type, COUNT(*) AS application_count FROM loan_application GROUP BY product_type",
        "sql_result": [
            {"application_product_type": "经营贷", "application_count": 6031},
            {"application_product_type": "车贷", "application_count": 6014},
            {"application_product_type": "装修贷", "application_count": 6002},
            {"application_product_type": "消费贷", "application_count": 5982},
            {"application_product_type": "现金贷", "application_count": 5971},
        ],
        "plan": {"mode": "distribution", "mode_label": "结构分布分析"},
    }

    state.update(await python_generate_node(state))
    state.update(await python_analyze_node(state))
    state.update(await report_generator_node(state))

    assert state["python_result"]["charts"][0]["type"] == "pie"
    assert state["report_payload"]["charts"][0]["chart_kind"] == "pie"


@pytest.mark.asyncio
async def test_multi_series_trend_analysis_and_report_are_structured():
    state = {
        "question": "各个贷款申请量变化趋势",
        "enhanced_question": "查询贷款申请按月份统计各贷款产品类型的申请笔数变化趋势。",
        "logic_form": {
            "metrics": ["application_count"],
            "dimensions": ["application_product_type"],
            "grain": "month",
            "time_range": {"type": "relative", "period": "recent_3_months"},
        },
        "compiled_sql": (
            "SELECT DATE_FORMAT(apply_date, '%Y-%m') AS month, "
            "product_type AS application_product_type, COUNT(*) AS application_count "
            "FROM loan_application_indicator "
            "GROUP BY DATE_FORMAT(apply_date, '%Y-%m'), product_type "
            "ORDER BY month ASC, application_product_type ASC"
        ),
        "sql_result": [
            {"month": "2026-01", "application_product_type": "经营贷", "application_count": 80},
            {"month": "2026-01", "application_product_type": "消费贷", "application_count": 55},
            {"month": "2026-02", "application_product_type": "经营贷", "application_count": 92},
            {"month": "2026-02", "application_product_type": "消费贷", "application_count": 61},
            {"month": "2026-03", "application_product_type": "经营贷", "application_count": 108},
            {"month": "2026-03", "application_product_type": "消费贷", "application_count": 74},
        ],
    }

    state.update(await planner_node(state))
    state.update(await python_generate_node(state))
    state.update(await python_analyze_node(state))
    state.update(await report_generator_node(state))

    assert state["plan"]["mode"] == "multi_series_trend"
    assert state["plan"]["mode_label"] == "多序列趋势分析"
    assert state["python_result"]["analysis_mode"] == "multi_series_trend"
    assert state["python_result"]["series_summary"]
    assert len(state["python_result"]["series_summary"]) == 2
    assert any("时间范围覆盖 2026-01 至 2026-03" in item for item in state["python_result"]["insights"])
    assert state["python_result"]["charts"][0]["type"] == "line"
    assert len(state["python_result"]["charts"][0]["series"]) == 2
    assert state["report_payload"]["mode"] == "multi_series_trend"
    assert state["report_payload"]["title"] == "application_count 按 application_product_type 月度趋势分析"
    assert "按 application_product_type 拆分" in state["report_payload"]["summary"]
    assert state["report_payload"]["charts"][0]["chart_kind"] == "line"
    assert len(state["report_payload"]["charts"][0]["series"]) == 2
    assert state["report_payload"]["highlights"][1]["label"] == "趋势序列数"
    assert "增长最快产品类型" in " ".join(state["report_payload"]["suggestions"]["items"])


def test_restricted_executor_rejects_unapproved_imports():
    executor = RestrictedLocalPythonExecutor()

    with pytest.raises(PythonExecutionError):
        executor.execute("import os\nprint('{}')", [])


def test_python_fallback_templates_are_externalized():
    generic = analysis_pipeline.load_python_template("generic_analysis.py.tpl")
    trend = analysis_pipeline.load_python_template("multi_series_trend.py.tpl")

    assert 'ANALYSIS_MODE = "__ANALYSIS_MODE__"' in generic
    assert 'ANALYSIS_MODE = "multi_series_trend"' in trend
    assert "print(json.dumps(result, ensure_ascii=False))" in generic
    assert "print(json.dumps(result, ensure_ascii=False))" in trend


def test_lf_repair_removes_unsupported_dimension_and_time_range():
    repaired, actions = repair_logic_form(
        {
            "metrics": ["pd"],
            "dimensions": ["vintage", "region"],
            "time_range": {"type": "relative", "period": "this_month"},
        },
        ["指标 pd 不支持维度: vintage", "指标 pd 缺少默认时间字段，无法应用时间口径"],
    )

    assert repaired["dimensions"] == ["region"]
    assert repaired["time_range"] is None
    assert "移除不支持维度 vintage" in actions


def test_python_executor_blocks_local_backend_in_production(monkeypatch):
    monkeypatch.setattr(
        python_executor,
        "get_settings",
        lambda: SimpleNamespace(
            python_executor_backend="local",
            debug=False,
            allow_local_python_executor_in_production=False,
            python_worker_url="",
        ),
    )

    with pytest.raises(PythonExecutionError):
        build_python_executor()


def test_worker_python_executor_calls_worker(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": True, "stdout": "{}", "stderr": "", "payload": {"row_count": 1}}

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(python_executor.httpx, "post", fake_post)

    result = WorkerPythonExecutor("http://worker.local").execute("print('{}')", [{"id": 1}])

    assert calls[0]["url"] == "http://worker.local/execute"
    assert result.payload == {"row_count": 1}


def test_high_isolation_executor_requires_runtime_configuration():
    with pytest.raises(PythonExecutionError):
        HighIsolationPythonExecutor("firecracker").execute("print('{}')", [])


def test_docker_python_executor_builds_isolated_command(monkeypatch):
    calls = []

    class FakeProcess:
        returncode = 0
        stdout = '{"row_count": 1}'
        stderr = ''

    def fake_run(command, **kwargs):
        calls.append({"command": command, "kwargs": kwargs})
        return FakeProcess()

    monkeypatch.setattr(python_executor.subprocess, "run", fake_run)

    result = HighIsolationPythonExecutor(
        "docker",
        image="python:3.12-slim",
        timeout_seconds=9,
        memory_mb=256,
        cpus="0.5",
    ).execute("print(json.dumps({'row_count': len(rows)}))", [{"id": 1}])

    command = calls[0]["command"]
    assert command[:3] == ["docker", "run", "--rm"]
    assert "--network" in command
    assert "none" in command
    assert "--memory" in command
    assert "256m" in command
    assert "python:3.12-slim" in command
    assert calls[0]["kwargs"]["timeout"] == 9
    assert result.payload == {"row_count": 1}


def test_infer_analysis_mode_falls_back_when_trend_question_has_no_time_dimension():
    mode = infer_analysis_mode(
        {
            "question": "各个贷款产品的申请数量变化",
            "enhanced_question": "各个贷款产品的申请数量变化",
            "sql_result": [
                {"application_product_type": "经营贷", "application_count": 6031},
                {"application_product_type": "车贷", "application_count": 6014},
                {"application_product_type": "装修贷", "application_count": 6002},
                {"application_product_type": "消费贷", "application_count": 5982},
                {"application_product_type": "现金贷", "application_count": 5971},
            ],
        },
        {
            "columns": ["application_product_type", "application_count"],
            "numeric_columns": ["application_count"],
            "dimension_columns": ["application_product_type"],
        },
    )

    assert mode["mode"] == "distribution"
    assert mode["label"] == "结构分布分析"
