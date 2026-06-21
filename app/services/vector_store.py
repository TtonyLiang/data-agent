"""向量存储服务 —— Milvus 本地模式的语义资产向量索引。

VectorStore 负责:
1. ``ensure_collection``:按 agent_id 创建独立的 Milvus collection。
2. ``insert``:批量插入语义资产向量(概念/指标/规则/模板)。
3. ``search``:向量相似度检索,返回超过阈值的结果。
4. ``delete_by_source``:按 source_type + source_id 删除单条向量。
5. ``delete_collection``:删除整个 collection(智能体删除时)。

每个 agent 拥有独立的 collection(``dq_knowledge_{agent_id}``),避免跨 agent 数据污染。
向量维度和相似度阈值由系统配置决定(embedding_dimension / rag_score_threshold)。
"""

from dataclasses import dataclass, field
import logging

from pymilvus import DataType, MilvusClient

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class VectorRecord:
    """单条向量记录 —— 用于插入时的数据载体。"""

    content: str             # 向量化的文本内容(语义资产的 name + description)
    vector: list[float]      # embedding 向量
    source_type: str         # 来源类型:semantic_concept/semantic_metric/semantic_rule/logic_form_template
    source_id: int           # 来源资产 id
    agent_id: int            # 所属智能体 id
    metadata: dict = field(default_factory=dict)  # 扩展元数据


@dataclass
class SearchResult:
    """向量检索结果。"""

    content: str
    score: float             # 相似度分数,越高越相关
    source_type: str
    source_id: int
    metadata: dict = field(default_factory=dict)


class VectorStore:
    """Milvus 向量存储服务(MilvusClient 本地模式)。"""

    def __init__(self):
        s = get_settings()
        self._client = MilvusClient(uri=s.milvus_uri)
        self._dimension = s.embedding_dimension
        self._top_k = s.rag_top_k
        self._score_threshold = s.rag_score_threshold

    def _collection_name(self, agent_id: int) -> str:
        """每个 agent 独立一个 collection,避免跨 agent 数据污染。"""
        return f"dq_knowledge_{agent_id}"

    def ensure_collection(self, agent_id: int):
        """确保 agent 的 collection 存在,不存在时自动创建(含向量索引)。"""
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
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        self._client.create_collection(
            collection_name=name,
            schema=schema,
            index_params=index_params,
        )
        logger.info("vector store collection created agent_id=%s", agent_id)

    def insert(self, agent_id: int, records: list[VectorRecord]):
        """批量插入向量记录,自动确保 collection 存在。"""
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
        logger.info("vector store insert agent_id=%s count=%s", agent_id, len(records))

    def search(
        self, agent_id: int, query_vector: list[float], top_k: int | None = None
    ) -> list[SearchResult]:
        """向量相似度检索,返回分数超过阈值的结果。"""
        name = self._collection_name(agent_id)
        if not self._client.has_collection(name):
            logger.info("vector store search agent_id=%s result=empty_reason=no_collection", agent_id)
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
        logger.info(
            "vector store search agent_id=%s top_k=%s hits=%s top_score=%s",
            agent_id,
            top_k,
            len(out),
            f"{out[0].score:.4f}" if out else "N/A",
        )
        return out

    def delete_by_source(self, agent_id: int, source_type: str, source_id: int):
        """按 source_type + source_id 删除单条向量。"""
        name = self._collection_name(agent_id)
        if not self._client.has_collection(name):
            return
        self._client.delete(
            collection_name=name,
            filter=f'source_type == "{source_type}" and source_id == {source_id}',
        )
        logger.info("vector store delete_by_source agent_id=%s type=%s id=%s", agent_id, source_type, source_id)

    def delete_collection(self, agent_id: int):
        """删除 agent 的整个 collection(智能体删除时调用)。"""
        name = self._collection_name(agent_id)
        if self._client.has_collection(name):
            self._client.drop_collection(name)
            logger.info("vector store collection dropped agent_id=%s", agent_id)

    def count(self, agent_id: int) -> int:
        """返回 agent collection 中的向量总数。"""
        name = self._collection_name(agent_id)
        if not self._client.has_collection(name):
            return 0
        return self._client.get_collection_stats(name).get("row_count", 0)


# 全局单例
_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """返回进程级向量存储服务单例。"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
