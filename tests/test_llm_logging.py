import logging

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
