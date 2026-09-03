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

    store = vector_store.VectorStore()

    assert FakeMilvusClient.uris[-1] == "http://milvus:19530"
    assert store._collection_name(3) == "dq_knowledge_3"
    assert store._collection_name(3, 7) == "dq_knowledge_3_domain_7"


def test_vector_search_falls_back_to_legacy_collection_before_first_resync(monkeypatch):
    class SearchClient:
        loaded = []

        def __init__(self, uri: str):
            self.uri = uri

        def has_collection(self, name):
            return name == "dq_knowledge_3"

        def load_collection(self, name):
            self.loaded.append(name)

        def search(self, **kwargs):
            return [[]]

    settings = SimpleNamespace(
        milvus_uri="http://milvus:19530",
        embedding_dimension=4,
        rag_top_k=5,
        rag_score_threshold=0.3,
    )
    monkeypatch.setattr(vector_store, "get_settings", lambda: settings)
    monkeypatch.setattr(vector_store, "MilvusClient", SearchClient)

    result = vector_store.VectorStore().search(3, [0.1] * 4, domain_id=7)

    assert result == []
    assert SearchClient.loaded == ["dq_knowledge_3"]
