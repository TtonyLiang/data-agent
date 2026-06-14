from types import SimpleNamespace

from app.services import vector_store


class FakeMilvusClient:
    uris = []

    def __init__(self, uri: str):
        self.uris.append(uri)


def test_vector_store_uses_configured_milvus_uri(monkeypatch):
    settings = SimpleNamespace(
        milvus_uri="http://milvus:19530",
        embedding_dimension=1024,
        rag_top_k=5,
        rag_score_threshold=0.3,
    )

    monkeypatch.setattr(vector_store, "get_settings", lambda: settings)
    monkeypatch.setattr(vector_store, "MilvusClient", FakeMilvusClient)

    vector_store.VectorStore()

    assert FakeMilvusClient.uris[-1] == "http://milvus:19530"
