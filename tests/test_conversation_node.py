from types import SimpleNamespace

import pytest

from app.agent.nodes import conversation
from app.agent.nodes.conversation import conversation_node


class ExplodingLLM:
    async def achat(self, *args, **kwargs):
        raise AssertionError("the deterministic conversation path must not call the LLM")


@pytest.mark.asyncio
async def test_greeting_uses_natural_fallback_without_llm(monkeypatch):
    monkeypatch.setattr(conversation, "get_llm_service", lambda: ExplodingLLM())

    result = await conversation_node({"intent": "chat", "question": "你好"})

    assert result["final_answer"].startswith("你好")
    assert result["conversation"]["mode"] == "greeting"
    assert result["conversation_metadata"] is result["conversation"]
    assert result["response"] is result["conversation"]


@pytest.mark.asyncio
async def test_capability_question_uses_concise_fallback(monkeypatch):
    monkeypatch.setattr(conversation, "get_llm_service", lambda: ExplodingLLM())

    result = await conversation_node({"intent": "chat", "question": "你能做什么？"})

    assert "自然语言查询" in result["final_answer"]
    assert result["conversation"]["mode"] == "capability"
    assert result["conversation"]["source"] == "fallback"


@pytest.mark.asyncio
async def test_data_capability_question_does_not_call_llm(monkeypatch):
    monkeypatch.setattr(conversation, "get_llm_service", lambda: ExplodingLLM())

    result = await conversation_node({"intent": "chat", "question": "你能帮我查什么？"})

    assert result["conversation"]["mode"] == "capability"
    assert "自然语言查询" in result["final_answer"]


@pytest.mark.asyncio
async def test_model_question_reads_agent_bound_config_without_exposing_key(monkeypatch):
    secret = "do-not-return-this-key"

    class FakeModelConfigService:
        async def get_agent_chat_config(self, agent_id):
            assert agent_id == 7
            return SimpleNamespace(
                provider="openai-compatible",
                model_name="gpt-5.4-mini",
                base_url="https://gateway.example.com/v1",
                api_key=secret,
                status="active",
            )

    monkeypatch.setattr(
        conversation,
        "get_model_config_service",
        lambda: FakeModelConfigService(),
    )
    monkeypatch.setattr(conversation, "get_llm_service", lambda: ExplodingLLM())

    result = await conversation_node(
        {"intent": "chat", "question": "当前用的是什么模型？", "agent_id": 7}
    )

    answer = result["final_answer"]
    assert "openai-compatible" in answer
    assert "gpt-5.4-mini" in answer
    assert "https://gateway.example.com/v1" in answer
    assert secret not in repr(result)
    assert "api_key" not in repr(result)
    assert result["conversation"]["model_config"] == {
        "provider": "openai-compatible",
        "model": "gpt-5.4-mini",
        "base_url": "https://gateway.example.com/v1",
    }


@pytest.mark.asyncio
async def test_model_question_handles_missing_config(monkeypatch):
    class FakeModelConfigService:
        async def get_agent_chat_config(self, agent_id):
            return None

    monkeypatch.setattr(conversation, "get_model_config_service", lambda: FakeModelConfigService())

    result = await conversation_node({"question": "请告诉我模型配置", "agent_id": 1})

    assert "还没有配置" in result["final_answer"]
    assert result["conversation"]["mode"] == "model_config"
    assert result["conversation"]["fallback"] is True


@pytest.mark.asyncio
async def test_metadata_query_uses_authorized_schema_and_renders_fields(monkeypatch):
    calls = []

    class FakeMetadataService:
        async def get_authorized_schema(self, datasource_id, agent_id):
            calls.append((datasource_id, agent_id))
            return [
                {
                    "table_name": "orders",
                    "table_comment": "订单表",
                    "columns": [
                        {"column_name": "order_id", "data_type": "bigint"},
                        {"column_name": "amount", "data_type": "decimal"},
                    ],
                },
                {
                    "table_name": "customers",
                    "table_comment": "客户表",
                    "columns": [{"column_name": "customer_id", "data_type": "bigint"}],
                },
            ]

    monkeypatch.setattr(conversation, "get_metadata_service", lambda: FakeMetadataService())

    result = await conversation_node(
        {
            "intent": "metadata_query",
            "question": "有哪些表和字段？",
            "agent_id": 3,
            "datasource_id": 11,
        }
    )

    assert calls == [(11, 3)]
    assert "2 张表" in result["final_answer"]
    assert "orders" in result["final_answer"]
    assert "order_id（bigint）" in result["final_answer"]
    assert "customers" in result["final_answer"]
    assert result["conversation"]["table_count"] == 2
    assert result["conversation"]["column_count"] == 3
    assert result["conversation"]["tables"][0]["table_name"] == "orders"


@pytest.mark.asyncio
async def test_metadata_query_without_datasource_returns_guidance(monkeypatch):
    class ExplodingMetadata:
        async def get_schema(self, datasource_id):
            raise AssertionError("no data source means no metadata lookup")

    monkeypatch.setattr(conversation, "get_metadata_service", lambda: ExplodingMetadata())

    result = await conversation_node(
        {"intent": "metadata_query", "question": "有哪些表？", "datasource_id": None}
    )

    assert "没有选择数据源" in result["final_answer"]
    assert result["conversation"]["fallback"] is True


@pytest.mark.asyncio
async def test_metadata_query_falls_back_to_get_schema_for_legacy_service(monkeypatch):
    class LegacyMetadataService:
        async def get_schema(self, datasource_id):
            assert datasource_id == 2
            return [
                {
                    "table": "events",
                    "comment": "事件表",
                    "fields": [{"name": "event_id", "type": "varchar"}],
                }
            ]

    monkeypatch.setattr(conversation, "get_metadata_service", lambda: LegacyMetadataService())

    result = await conversation_node(
        {"intent": "metadata_query", "question": "查看表结构", "datasource_id": 2}
    )

    assert "events" in result["final_answer"]
    assert "event_id（varchar）" in result["final_answer"]


@pytest.mark.asyncio
async def test_general_chat_uses_optional_llm_and_returns_metadata(monkeypatch):
    calls = {}

    class FakeLLM:
        async def resolve_agent_chat_kwargs(self, agent_id):
            calls["agent_id"] = agent_id
            return {"model": "test-model"}

        async def achat(self, messages, **kwargs):
            calls["messages"] = messages
            calls["kwargs"] = kwargs
            return "这是模型对一般问题的简短回答。"

    monkeypatch.setattr(conversation, "get_llm_service", lambda: FakeLLM())

    result = await conversation_node(
        {
            "intent": "chat",
            "question": "为什么需要数据字典？",
            "agent_id": 9,
            "chat_history": [{"role": "user", "content": "我在了解数据治理"}],
        }
    )

    assert result["final_answer"] == "这是模型对一般问题的简短回答。"
    assert result["conversation"]["mode"] == "llm"
    assert result["conversation"]["fallback"] is False
    assert calls["agent_id"] == 9
    assert calls["kwargs"] == {"model": "test-model"}
    assert calls["messages"][-1] == {"role": "user", "content": "为什么需要数据字典？"}


@pytest.mark.asyncio
async def test_general_chat_llm_failure_uses_fallback(monkeypatch):
    class FailingLLM:
        async def achat(self, messages, **kwargs):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(conversation, "get_llm_service", lambda: FailingLLM())

    result = await conversation_node(
        {"intent": "chat", "question": "讲个和数据有关的小例子"}
    )

    assert result["final_answer"] == conversation.DEFAULT_CAPABILITY_ANSWER
    assert result["conversation"]["fallback"] is True
    assert result["conversation"]["source"] == "fallback"
