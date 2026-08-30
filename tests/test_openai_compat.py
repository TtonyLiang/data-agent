from types import SimpleNamespace

from app.services.llm_service import LLMService
from app.utils.openai_compat import normalize_openai_base_url


def test_normalize_openai_base_url_adds_v1_for_host_only_urls():
    assert normalize_openai_base_url("https://api.example.com") == "https://api.example.com/v1"
    assert normalize_openai_base_url("https://api.example.com/") == "https://api.example.com/v1"


def test_normalize_openai_base_url_preserves_explicit_paths_without_duplication():
    assert normalize_openai_base_url("https://api.example.com/v1") == "https://api.example.com/v1"
    assert normalize_openai_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    assert normalize_openai_base_url("https://api.example.com/custom") == "https://api.example.com/custom"


def test_normalize_openai_base_url_keeps_empty_configuration_empty():
    assert normalize_openai_base_url(None) == ""
    assert normalize_openai_base_url("  ") == ""


def test_normalize_openai_base_url_does_not_rewrite_malformed_values():
    assert normalize_openai_base_url("localhost:11434") == "localhost:11434"


def test_llm_service_normalizes_base_url_before_client_creation(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.services.llm_service.ChatOpenAI", FakeChatOpenAI)
    service = LLMService()
    service._settings = SimpleNamespace(
        llm_provider="openai-compatible",
        llm_model="test-model",
        llm_base_url="https://fallback.example.com",
        llm_api_key=None,
    )

    service.get_client(
        provider="openai-compatible",
        base_url="https://api.example.com",
        model="test-model",
        api_key=None,
        streaming=False,
    )

    assert captured["base_url"] == "https://api.example.com/v1"
