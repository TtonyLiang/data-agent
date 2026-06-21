import asyncio
import logging
from types import SimpleNamespace

from app.services.llm_service import LLMService


def test_llm_service_logs_prompt_messages(caplog):
    service = LLMService()
    service._settings = SimpleNamespace(
        llm_model="qwen3:14b",
        max_llm_prompt_log_chars=8000,
        llm_cache_enabled=False,
        detailed_data_logging_enabled=False,
        llm_prompt_logging_enabled=True,
    )
    messages = [
        {"role": "system", "content": "系统提示词"},
        {"role": "user", "content": "用户问题"},
    ]

    with caplog.at_level(logging.INFO, logger="app.services.llm_service"):
        service.log_prompt_messages(messages, model="qwen3:14b", streaming=False)

    log_text = caplog.text
    assert "LLM request" in log_text
    assert "model=qwen3:14b" in log_text
    assert '"role": "system"' in log_text
    assert '"chars": 5' in log_text
    assert "[system] 系统提示词" not in log_text
    assert "[user] 用户问题" not in log_text


def test_llm_service_logs_prompt_preview_when_detailed_logging_enabled(caplog):
    service = LLMService()
    service._settings = SimpleNamespace(
        llm_model="qwen3:14b",
        max_llm_prompt_log_chars=8000,
        llm_cache_enabled=False,
        detailed_data_logging_enabled=True,
        llm_prompt_logging_enabled=True,
    )
    messages = [
        {"role": "system", "content": "系统提示词"},
        {"role": "user", "content": "用户问题"},
    ]

    with caplog.at_level(logging.INFO, logger="app.services.llm_service"):
        service.log_prompt_messages(messages, model="qwen3:14b", streaming=False)

    assert "[system] 系统提示词" in caplog.text
    assert "[user] 用户问题" in caplog.text


def test_llm_service_truncates_prompt_logs_when_detailed_logging_enabled(caplog):
    service = LLMService()
    service._settings = SimpleNamespace(
        llm_model="qwen3:14b",
        max_llm_prompt_log_chars=24,
        llm_cache_enabled=False,
        detailed_data_logging_enabled=True,
        llm_prompt_logging_enabled=True,
    )

    with caplog.at_level(logging.INFO, logger="app.services.llm_service"):
        service.log_prompt_messages(
            [{"role": "user", "content": "很长" * 40}],
            model="qwen3:14b",
            streaming=False,
        )

    assert "[truncated" in caplog.text


def test_llm_service_uses_placeholder_api_key_for_keyless_compatible_models(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.services.llm_service.ChatOpenAI", FakeChatOpenAI)
    service = LLMService()

    client = service.get_client(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3:14b",
        api_key=None,
        streaming=False,
    )

    assert isinstance(client, FakeChatOpenAI)
    assert captured["api_key"] == service.API_KEY_PLACEHOLDER


async def _run_blocking_achat(service: LLMService):
    task = asyncio.create_task(service.achat([{"role": "user", "content": "hi"}]))
    await asyncio.sleep(0.01)
    still_tickable = not task.done()
    response = await task
    return still_tickable, response


def test_llm_service_achat_does_not_block_event_loop(monkeypatch):
    class FakeResponse:
        content = "ok"

    class FakeClient:
        async def ainvoke(self, messages):
            await asyncio.sleep(0.03)
            return FakeResponse()

    service = LLMService()
    monkeypatch.setattr(service, "get_client", lambda **kwargs: FakeClient())

    still_tickable, response = asyncio.run(_run_blocking_achat(service))

    assert still_tickable is True
    assert response == "ok"


def test_llm_service_achat_uses_short_ttl_cache(monkeypatch):
    class FakeResponse:
        content = "cached-ok"

    class FakeClient:
        calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            return FakeResponse()

    fake_client = FakeClient()
    service = LLMService()
    service._settings = SimpleNamespace(
        llm_provider="ollama",
        llm_model="qwen3:14b",
        llm_cache_enabled=True,
        llm_cache_ttl_seconds=300,
        llm_cache_max_items=16,
        max_llm_prompt_log_chars=8000,
        detailed_data_logging_enabled=False,
        llm_prompt_logging_enabled=True,
    )
    monkeypatch.setattr(service, "get_client", lambda **kwargs: fake_client)

    async def run():
        first = await service.achat([{"role": "user", "content": "同一个问题"}])
        second = await service.achat([{"role": "user", "content": "同一个问题"}])
        return first, second

    first, second = asyncio.run(run())

    assert first == "cached-ok"
    assert second == "cached-ok"
    assert fake_client.calls == 1
