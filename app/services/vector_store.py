from dataclasses import dataclass, field

from pymilvus import DataType, MilvusClient

from app.config import get_settings


@dataclass
class VectorRecord:
    content: str
    vector: list[float]
    source_type: str  # semantic_concept | semantic_metric | semantic_rule | logic_form_template
    source_id: int
    agent_id: int
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    content: str
    score: float
    source_type: str
    source_id: int
    metadata: dict = field(default_factory=dict)


class VectorStore:
    """Milvus 向量存储服务 (MilvusClient 本地模式)."""

    def __init__(self):
        s = get_settings()
        self._client = MilvusClient(uri=s.milvus_uri)
        self._dimension = s.embedding_dimension
        self._top_k = s.rag_top_k
        self._score_threshold = s.rag_score_threshold

    def _collection_name(self, agent_id: int) -> str:
        return f"dq_knowledge_{agent_id}"

    def ensure_collection(self, agent_id: int):
        name = self._collection_name(agent_id)
        if self._client.has_collection(name):
            return
        schema = MilvusClient.create_schema(auto_id=True)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self._dimension)
        schema.add_field("content", DataType.VARCHAR, max_length=8192)
        schema.add_field("source_type", DataType.VARCHAR, max_length=32)
        schema.add_field("source_id", DataType.INT64)
        schema.add_field("agent_id", DataType.INT64)
        schema.add_field("metadata", DataType.JSON)

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="vector", index_type="AUTOINDEX", metric_type="COSINE"
        )
        self._client.create_collection(
            collection_name=name,
            schema=schema,
            index_params=index_params,
        )

    def insert(self, agent_id: int, records: list[VectorRecord]):
        if not records:
            return
        self.ensure_collection(agent_id)
        name = self._collection_name(agent_id)
        data = [
            {
                "vector": r.vector,
                "content": r.content,
                "source_type": r.source_type,
                "source_id": r.source_id,
                "agent_id": r.agent_id,
                "metadata": r.metadata,
            }
            for r in records
        ]
        self._client.insert(collection_name=name, data=data)

    def search(
        self, agent_id: int, query_vector: list[float], top_k: int | None = None
    ) -> list[SearchResult]:
        name = self._collection_name(agent_id)
        if not self._client.has_collection(name):
            return []
        self._client.load_collection(name)
        top_k = top_k or self._top_k
        results = self._client.search(
            collection_name=name,
            data=[query_vector],
            limit=top_k,
            output_fields=["content", "source_type", "source_id", "metadata"],
        )
        out = []
        for hit in results[0]:
            entity = hit.get("entity", {})
            score = hit.get("distance", 0.0)
            if score < self._score_threshold:
                continue
            out.append(
                SearchResult(
                    content=entity.get("content", ""),
                    score=score,
                    source_type=entity.get("source_type", ""),
                    source_id=entity.get("source_id", 0),
                    metadata=entity.get("metadata", {}),
                )
            )
        return out

    def delete_by_source(self, agent_id: int, source_type: str, source_id: int):
        name = self._collection_name(agent_id)
        if not self._client.has_collection(name):
            return
        self._client.delete(
            collection_name=name,
            filter=f'source_type == "{source_type}" and source_id == {source_id}',
        )

    def delete_collection(self, agent_id: int):
        name = self._collection_name(agent_id)
        if self._client.has_collection(name):
            self._client.drop_collection(name)

    def count(self, agent_id: int) -> int:
        name = self._collection_name(agent_id)
        if not self._client.has_collection(name):
            return 0
        return self._client.get_collection_stats(name).get("row_count", 0)


_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
