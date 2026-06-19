import pytest

from app.agent.nodes import nl2sql_fallback
from app.agent.nodes.nl2sql_fallback import nl2sql_fallback_node


class FakeMetadataService:
    async def get_schema(self, datasource_id):
        assert datasource_id == 2
        return [
            {
                "table_name": "loan_application_indicator",
                "table_comment": "贷款申请审批指标表",
                "columns": [
                    {
                        "column_name": "application_id",
                        "data_type": "bigint",
                        "column_comment": "申请ID",
                    },
                    {"column_name": "region", "data_type": "varchar", "column_comment": "区域"},
                ],
            }
        ]


class FakeLlmService:
    async def resolve_agent_chat_kwargs(self, agent_id):
        return {"model": "fake"}

    async def achat_stream(self, messages, **kwargs):
        class Chunk:
            def __init__(self, content):
                self.content = content

        response = (
            '{"sql": "SELECT region AS application_region, COUNT(*) AS application_count '
            "FROM loan_application_indicator GROUP BY region "
            'ORDER BY application_count DESC LIMIT 3"}'
        )
        yield Chunk(response)


@pytest.mark.asyncio
async def test_nl2sql_fallback_generates_safe_select(monkeypatch):
    monkeypatch.setattr(nl2sql_fallback, "get_metadata_service", lambda: FakeMetadataService())
    monkeypatch.setattr(nl2sql_fallback, "get_llm_service", lambda: FakeLlmService())

    result = await nl2sql_fallback_node(
        {
            "question": "我问的是笔数，为什么查出来的是金额",
            "agent_id": 2,
            "datasource_id": 2,
            "chat_history": [
                {"role": "user", "content": "贷款排名前三的申请区域是什么，分别申请了多少笔"},
            ],
            "lf_validation": {"valid": False, "errors": ["未知指标: loan_count"]},
        }
    )

    assert result["sql_error"] is None
    assert result["compiled_sql"].startswith("SELECT region AS application_region")
    assert "COUNT(*) AS application_count" in result["compiled_sql"]
    assert result["execution_trace"]["compile_strategy"] == "nl2sql_fallback"
