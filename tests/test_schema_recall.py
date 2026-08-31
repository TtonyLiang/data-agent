import json
from pathlib import Path

import pytest

from app.agent.nodes import schema_recall
from app.agent.nodes.nl2sql_fallback import build_schema_context
from app.agent.nodes.schema_recall import select_tables_by_score
from app.models.system_parameter import SchemaRecallSettings

EXAMPLE_SEMANTIC_PATH = Path("examples/loan/semantic-domain.json")


@pytest.fixture(autouse=True)
def fake_schema_recall_settings(monkeypatch):
    class FakeSystemParameterService:
        async def get_schema_recall_settings(self):
            return SchemaRecallSettings(
                max_tables=6,
                required_score_ratio=0.35,
                optional_score_ratio=0.15,
            )

    monkeypatch.setattr(
        schema_recall,
        "get_system_parameter_service",
        lambda: FakeSystemParameterService(),
    )


def loan_recall_rules():
    payload = json.loads(EXAMPLE_SEMANTIC_PATH.read_text(encoding="utf-8"))
    return [
        item for item in payload.get("rules", []) if item.get("rule_type") == "recall"
    ]


def test_schema_recall_contains_no_domain_keyword_literals():
    """Keep business recall terms in semantic rules, not in schema recall code."""
    source = Path("app/agent/nodes/schema_recall.py").read_text(encoding="utf-8")
    forbidden = [
        "申请",
        "进件",
        "审批",
        "区域",
        "地区",
        "年龄",
        "客龄",
        "金额",
        "余额",
        "笔数",
        "数量",
        "application",
        "apply",
        "approval",
        "region",
        "area",
        "customer_age",
    ]

    assert [token for token in forbidden if token in source] == []


def test_select_tables_by_relative_score_thresholds():
    tables = [
        {"table_name": "t1", "score": 2162},
        {"table_name": "t2", "score": 821},
        {"table_name": "t3", "score": 210},
        {"table_name": "t4", "score": 166},
        {"table_name": "t5", "score": 148},
    ]

    selected, scope = select_tables_by_score(
        tables,
        tables,
        max_tables=6,
        required_score_ratio=0.35,
        optional_score_ratio=0.15,
    )

    assert [item["table_name"] for item in selected] == ["t1", "t2"]
    assert scope["required_score"] == 756.7
    assert scope["optional_score"] == 324.3
    assert scope["selection_mode"] == "relative_threshold"


class FakeMetadataService:
    async def get_schema(self, datasource_id: int):
        assert datasource_id == 42
        return [
            {
                "table_name": "loan_account_indicator",
                "table_comment": "贷款账户指标表",
                "columns": [
                    {"column_name": "region", "column_comment": "账户区域", "data_type": "varchar"},
                    {
                        "column_name": "balance",
                        "column_comment": "贷款余额",
                        "data_type": "decimal",
                    },
                ],
            },
            {
                "table_name": "loan_application_indicator",
                "table_comment": "贷款申请指标表",
                "columns": [
                    {"column_name": "region", "column_comment": "申请区域", "data_type": "varchar"},
                    {
                        "column_name": "customer_age",
                        "column_comment": "客户年龄",
                        "data_type": "int",
                    },
                    {
                        "column_name": "product_type",
                        "column_comment": "申请产品类型",
                        "data_type": "varchar",
                    },
                    {
                        "column_name": "application_id",
                        "column_comment": "申请编号",
                        "data_type": "bigint",
                    },
                ],
            },
            {
                "table_name": "loan_disbursement_indicator",
                "table_comment": "放款指标表",
                "columns": [
                    {
                        "column_name": "loan_amount",
                        "column_comment": "放款金额",
                        "data_type": "decimal",
                    },
                ],
            },
        ]


@pytest.mark.asyncio
async def test_schema_recall_matches_question_and_semantic_terms(monkeypatch):
    monkeypatch.setattr(schema_recall, "get_metadata_service", lambda: FakeMetadataService())

    result = await schema_recall.schema_recall_node(
        {
            "datasource_id": 42,
            "question": "贷款排名前三的申请区域是什么，分别申请了多少笔",
            "semantic_runtime": {
                "metrics": [
                    {
                        "metric_key": "outstanding_balance",
                        "name": "余额",
                        "base_table": "loan_account_indicator",
                        "dimensions": ["region"],
                    },
                    {
                        "metric_key": "application_count",
                        "name": "申请笔数",
                        "base_table": "loan_application_indicator",
                        "dimensions": ["application_region"],
                    },
                ],
                "mappings": [
                    {
                        "asset_key": "region",
                        "name": "区域",
                        "table_name": "loan_account_indicator",
                        "column_name": "region",
                    },
                    {
                        "asset_key": "application_region",
                        "name": "申请区域",
                        "table_name": "loan_application_indicator",
                        "column_name": "region",
                    },
                ],
                "rules": loan_recall_rules(),
            },
            "runtime_evidence": [],
        }
    )

    assert result["relevant_tables"][0]["table_name"] == "loan_application_indicator"
    assert "业务指标基础表" in result["relevant_tables"][0]["reason"]
    assert "业务域匹配: 申请/审批" in result["relevant_tables"][0]["reason"]
    assert any(item["column_name"] == "region" for item in result["relevant_columns"])
    assert result["schema_scope"]["fallback_used"] is False
    assert any(
        item.get("key") == "application"
        for item in result["schema_scope"]["business_groups"]
    )


@pytest.mark.asyncio
async def test_schema_recall_matches_customer_age_from_column_comment(monkeypatch):
    monkeypatch.setattr(schema_recall, "get_metadata_service", lambda: FakeMetadataService())

    result = await schema_recall.schema_recall_node(
        {
            "datasource_id": 42,
            "question": "贷款申请产品类型和客户年龄分布有什么关系",
            "semantic_runtime": {
                "metrics": [
                    {
                        "metric_key": "application_count",
                        "name": "申请笔数",
                        "base_table": "loan_application_indicator",
                        "dimensions": ["application_product_type"],
                    },
                ],
                "mappings": [
                    {
                        "asset_key": "application_product_type",
                        "name": "申请产品类型",
                        "table_name": "loan_application_indicator",
                        "column_name": "product_type",
                    },
                ],
                "rules": loan_recall_rules(),
            },
            "runtime_evidence": [],
        }
    )

    columns = {
        (item["table_name"], item["column_name"]): item for item in result["relevant_columns"]
    }
    assert ("loan_application_indicator", "customer_age") in columns
    age_column = columns[("loan_application_indicator", "customer_age")]
    assert "问题要求客户年龄字段" in age_column["reason"]


@pytest.mark.asyncio
async def test_schema_recall_uses_matched_ontology_to_ground_related_table(monkeypatch):
    monkeypatch.setattr(schema_recall, "get_metadata_service", lambda: FakeMetadataService())

    result = await schema_recall.schema_recall_node(
        {
            "datasource_id": 42,
            "question": "查看审批进度",
            "semantic_runtime": {"metrics": [], "mappings": [], "rules": []},
            "runtime_evidence": [],
            "ontology_context": {
                "object_types": [
                    {
                        "object_key": "LoanApplication",
                        "name": "贷款申请",
                        "description": "客户提交的贷款申请",
                        "properties": [],
                    }
                ],
                "link_types": [],
                "actions": [
                    {
                        "action_key": "approve_loan_application",
                        "name": "审批贷款申请",
                        "target_object_key": "LoanApplication",
                        "description": "完成贷款申请审批",
                        "parameters": [],
                    }
                ],
            },
        }
    )

    assert result["relevant_tables"][0]["table_name"] == "loan_application_indicator"
    assert "企业本体对象命中: 贷款申请" in result["relevant_tables"][0]["reason"]
    assert result["ontology_evidence"]["actions"][0]["action_key"] == "approve_loan_application"


@pytest.mark.asyncio
async def test_schema_recall_scopes_explicit_application_channel_query(monkeypatch):
    monkeypatch.setattr(schema_recall, "get_metadata_service", lambda: FakeMetadataService())

    result = await schema_recall.schema_recall_node(
        {
            "datasource_id": 42,
            "question": "查询贷款申请按申请渠道分组的申请笔数",
            "semantic_runtime": {
                "metrics": [
                    {
                        "metric_key": "application_count",
                        "name": "申请笔数",
                        "base_table": "loan_application_indicator",
                        "dimensions": ["application_channel"],
                    },
                    {
                        "metric_key": "outstanding_balance",
                        "name": "余额",
                        "base_table": "loan_account_indicator",
                        "dimensions": ["channel"],
                    },
                ],
                "mappings": [
                    {
                        "asset_key": "application_channel",
                        "name": "申请渠道",
                        "table_name": "loan_application_indicator",
                        "column_name": "channel",
                    },
                    {
                        "asset_key": "channel",
                        "name": "渠道",
                        "table_name": "loan_account_indicator",
                        "column_name": "channel",
                    },
                ],
                "rules": [],
            },
            "runtime_evidence": [],
        }
    )

    assert [item["table_name"] for item in result["relevant_tables"]] == [
        "loan_application_indicator"
    ]
    assert result["schema_scope"]["subject_scope_only"] is True


def test_nl2sql_schema_context_uses_recalled_tables_first():
    schema = [
        {
            "table_name": "orders",
            "table_comment": "订单表",
            "columns": [
                {"column_name": "amount", "data_type": "decimal", "column_comment": "金额"}
            ],
        },
        {
            "table_name": "customers",
            "table_comment": "客户表",
            "columns": [{"column_name": "name", "data_type": "varchar", "column_comment": "姓名"}],
        },
    ]

    context = build_schema_context(
        schema,
        relevant_tables=[{"table_name": "customers"}],
        relevant_columns=[{"table_name": "customers", "column_name": "name"}],
    )

    assert "customers" in context
    assert "orders" not in context


@pytest.mark.asyncio
async def test_schema_recall_marks_age_column_as_relevant(monkeypatch):
    monkeypatch.setattr(schema_recall, "get_metadata_service", lambda: FakeMetadataService())

    result = await schema_recall.schema_recall_node(
        {
            "datasource_id": 42,
            "question": "贷款申请产品类型和客户年龄分布有什么关系",
            "semantic_runtime": {
                "metrics": [
                    {
                        "metric_key": "application_count",
                        "name": "申请笔数",
                        "base_table": "loan_application_indicator",
                    },
                ],
                "mappings": [
                    {
                        "asset_key": "application_product_type",
                        "name": "申请产品类型",
                        "table_name": "loan_application_indicator",
                        "column_name": "product_type",
                    },
                ],
                "rules": loan_recall_rules(),
            },
            "runtime_evidence": [],
        }
    )

    assert any(
        item["column_name"] == "customer_age" and item["table_name"] == "loan_application_indicator"
        for item in result["relevant_columns"]
    )
