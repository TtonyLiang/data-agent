import pytest

from app.services import embedding_adapter
from app.services import embedding_service


class FakeResponse:
    status_code = 200
    text = '{"data":[{"embedding":[0.1,0.2]}]}'

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": [{"embedding": [0.1, 0.2]}]}


class FakeAsyncClient:
    last_headers = None
    last_url = None
    last_json = None
    calls = []

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json, headers=None):
        FakeAsyncClient.last_url = url
        FakeAsyncClient.last_json = json
        FakeAsyncClient.last_headers = headers or {}
        FakeAsyncClient.calls.append({"url": url, "json": json, "headers": headers or {}})
        return FakeResponse()


@pytest.mark.asyncio
async def test_embedding_service_sends_bearer_token_when_configured(monkeypatch):
    FakeAsyncClient.calls = []
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
    monkeypatch.setattr(embedding_adapter.httpx, "AsyncClient", FakeAsyncClient)

    service = embedding_service.EmbeddingService()
    assert await service.embed_query("hello") == [0.1, 0.2]

    assert FakeAsyncClient.last_headers["Authorization"] == "Bearer embed-secret"
    assert FakeAsyncClient.last_url == "https://embeddings.example/v1/embeddings"
    assert FakeAsyncClient.last_json == {
        "model": "embedding-3",
        "input": ["hello"],
        "encoding_format": "float",
    }


@pytest.mark.asyncio
async def test_embedding_adapter_falls_back_to_volcengine_multimodal(monkeypatch):
    class NotFoundResponse:
        status_code = 404
        text = '{"error":{"code":"InvalidEndpointOrModel.NotFound"}}'

        def json(self):
            return {}

    class OkResponse(FakeResponse):
        pass

    class VolcengineFakeClient(FakeAsyncClient):
        calls = []

        async def post(self, url, json, headers=None):
            self.calls.append({"url": url, "json": json, "headers": headers or {}})
            if url.endswith("/embeddings"):
                return NotFoundResponse()
            return OkResponse()

    monkeypatch.setattr(embedding_adapter.httpx, "AsyncClient", VolcengineFakeClient)

    vector, meta = await embedding_adapter.request_embedding(
        provider="test-embedding-provider",
        base_url="https://api.example-embedding.com/v3",
        model="doubao-embedding-text-240515",
        text="hello",
        headers={"Authorization": "Bearer secret"},
    )

    assert vector == [0.1, 0.2]
    assert meta["variant"] == "volcengine_multimodal_embeddings"
    assert VolcengineFakeClient.calls[0]["url"].endswith("/embeddings")
    assert VolcengineFakeClient.calls[1]["url"].endswith("/embeddings/multimodal")
    assert VolcengineFakeClient.calls[1]["json"]["input"] == [{"type": "text", "text": "hello"}]
