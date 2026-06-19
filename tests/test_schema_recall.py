import pytest

from app.agent.nodes import schema_recall
from app.agent.nodes.nl2sql_fallback import build_schema_context


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
            },
            "runtime_evidence": [],
        }
    )

    assert result["relevant_tables"][0]["table_name"] == "loan_application_indicator"
    assert "业务指标基础表" in result["relevant_tables"][0]["reason"]
    assert "业务域匹配: 申请/审批" in result["relevant_tables"][0]["reason"]
    assert any(item["column_name"] == "region" for item in result["relevant_columns"])
    assert result["schema_scope"]["fallback_used"] is False
    assert "application" in result["schema_scope"]["business_groups"]


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
