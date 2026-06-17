import logging
import asyncio
import time

from app.services.llm_service import LLMService


def test_llm_service_logs_prompt_messages(caplog):
    service = LLMService()
    messages = [
        {"role": "system", "content": "系统提示词"},
        {"role": "user", "content": "用户问题"},
    ]

    with caplog.at_level(logging.INFO, logger="app.services.llm_service"):
        service.log_prompt_messages(messages, model="qwen3:14b", streaming=False)

    log_text = caplog.text
    assert "LLM request" in log_text
    assert "model=qwen3:14b" in log_text
    assert "[system] 系统提示词" in log_text
    assert "[user] 用户问题" in log_text


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
        def invoke(self, messages):
            time.sleep(0.03)
            return FakeResponse()

    service = LLMService()
    monkeypatch.setattr(service, "get_client", lambda **kwargs: FakeClient())

    still_tickable, response = asyncio.run(_run_blocking_achat(service))

    assert still_tickable is True
    assert response == "ok"
