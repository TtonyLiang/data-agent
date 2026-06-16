import pytest

from app.services import embedding_service


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"data": [{"embedding": [0.1, 0.2]}]}


class FakeAsyncClient:
    last_headers = None

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json, headers=None):
        FakeAsyncClient.last_headers = headers or {}
        return FakeResponse()


@pytest.mark.asyncio
async def test_embedding_service_sends_bearer_token_when_configured(monkeypatch):
    settings = type(
        "Settings",
        (),
        {
            "embedding_base_url": "https://embeddings.example/v1",
            "embedding_api_key": "embed-secret",
            "embedding_model": "embedding-3",
            "embedding_dimension": 1024,
        },
    )()
    monkeypatch.setattr(embedding_service, "get_settings", lambda: settings)
    monkeypatch.setattr(embedding_service.httpx, "AsyncClient", FakeAsyncClient)

    service = embedding_service.EmbeddingService()
    assert await service.embed_query("hello") == [0.1, 0.2]

    assert FakeAsyncClient.last_headers["Authorization"] == "Bearer embed-secret"
