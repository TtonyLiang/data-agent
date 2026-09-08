"""向量存储服务 —— Milvus 本地模式的语义资产向量索引。

VectorStore 负责:
1. ``ensure_collection``:按领域、企业模型/语义快照和 embedding 版本创建 collection。
2. ``insert``:批量插入语义资产向量(概念/指标/规则/模板)。
3. ``search``:向量相似度检索,返回超过阈值的结果。
4. ``delete_by_source``:按 source_type + source_id 删除单条向量。
5. ``delete_collection``:删除指定企业模型版本或历史兼容 collection。

历史 Agent/领域 collection 只用于迁移回退，不再作为新索引的主命名空间。
向量维度和相似度阈值由系统配置决定(embedding_dimension / rag_score_threshold)。
"""

import hashlib
import logging
from dataclasses import dataclass, field

from pymilvus import DataType, MilvusClient

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class VectorRecord:
    """单条向量记录 —— 用于插入时的数据载体。"""

    content: str  # 向量化的文本内容(语义资产的 name + description)
    vector: list[float]  # embedding 向量
    source_type: str  # semantic_concept/semantic_metric/semantic_rule/logic_form_template
    source_id: int  # 来源资产 id
    agent_id: int  # 所属智能体 id
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

    def _collection_name(
        self,
        agent_id: int | None,
        domain_id: int | None = None,
        *,
        model_release_id: int | None = None,
        semantic_snapshot_id: int | None = None,
        embedding_model_config_id: int | None = None,
        embedding_model_version: str | None = None,
    ) -> str:
        """Resolve the versioned enterprise name or an old Agent namespace."""
        if domain_id is not None and (model_release_id or semantic_snapshot_id):
            if not embedding_model_version:
                raise ValueError("企业语义索引缺少 embedding 模型版本")
            release_key = (
                f"r{int(model_release_id)}"
                if model_release_id
                else f"s{int(semantic_snapshot_id or 0)}"
            )
            config_key = (
                str(int(embedding_model_config_id))
                if embedding_model_config_id is not None
                else "default"
            )
            version_key = hashlib.sha256(
                str(embedding_model_version).encode("utf-8")
            ).hexdigest()[:12]
            return (
                f"dq_semantic_d{int(domain_id)}_{release_key}_"
                f"e{config_key}_v{version_key}"
            )
        if agent_id is None:
            raise ValueError("历史向量集合缺少 agent_id")
        if domain_id is None:
            return f"dq_knowledge_{agent_id}"
        return f"dq_knowledge_{agent_id}_domain_{domain_id}"

    def ensure_collection(
        self,
        agent_id: int | None,
        domain_id: int | None = None,
        *,
        model_release_id: int | None = None,
        semantic_snapshot_id: int | None = None,
        embedding_model_config_id: int | None = None,
        embedding_model_version: str | None = None,
        embedding_dimension: int | None = None,
    ):
        """Ensure a versioned enterprise or historical collection exists."""
        name = self._collection_name(
            agent_id,
            domain_id,
            model_release_id=model_release_id,
            semantic_snapshot_id=semantic_snapshot_id,
            embedding_model_config_id=embedding_model_config_id,
            embedding_model_version=embedding_model_version,
        )
        if self._client.has_collection(name):
            return
        schema = MilvusClient.create_schema(auto_id=True)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field(
            "vector",
            DataType.FLOAT_VECTOR,
            dim=int(embedding_dimension or self._dimension),
        )
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
        logger.info(
            "vector store collection created name=%s agent_id=%s domain_id=%s "
            "model_release_id=%s semantic_snapshot_id=%s embedding_config_id=%s",
            name,
            agent_id,
            domain_id,
            model_release_id,
            semantic_snapshot_id,
            embedding_model_config_id,
        )

    def insert(
        self,
        agent_id: int | None,
        records: list[VectorRecord],
        domain_id: int | None = None,
        *,
        model_release_id: int | None = None,
        semantic_snapshot_id: int | None = None,
        embedding_model_config_id: int | None = None,
        embedding_model_version: str | None = None,
        embedding_dimension: int | None = None,
    ):
        """批量插入向量记录,自动确保 collection 存在。"""
        if not records:
            return
        self.ensure_collection(
            agent_id,
            domain_id,
            model_release_id=model_release_id,
            semantic_snapshot_id=semantic_snapshot_id,
            embedding_model_config_id=embedding_model_config_id,
            embedding_model_version=embedding_model_version,
            embedding_dimension=embedding_dimension,
        )
        name = self._collection_name(
            agent_id,
            domain_id,
            model_release_id=model_release_id,
            semantic_snapshot_id=semantic_snapshot_id,
            embedding_model_config_id=embedding_model_config_id,
            embedding_model_version=embedding_model_version,
        )
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
        logger.info(
            "vector store insert name=%s agent_id=%s domain_id=%s count=%s",
            name,
            agent_id,
            domain_id,
            len(records),
        )

    def search(
        self,
        agent_id: int,
        query_vector: list[float],
        top_k: int | None = None,
        *,
        domain_id: int | None = None,
        model_release_id: int | None = None,
        semantic_snapshot_id: int | None = None,
        embedding_model_config_id: int | None = None,
        embedding_model_version: str | None = None,
        allow_legacy_fallback: bool = True,
    ) -> list[SearchResult]:
        """向量相似度检索,返回分数超过阈值的结果。"""
        name = self._collection_name(
            agent_id,
            domain_id,
            model_release_id=model_release_id,
            semantic_snapshot_id=semantic_snapshot_id,
            embedding_model_config_id=embedding_model_config_id,
            embedding_model_version=embedding_model_version,
        )
        if not self._client.has_collection(name):
            legacy_names = []
            if allow_legacy_fallback:
                legacy_names = [
                    self._collection_name(agent_id, domain_id),
                    self._collection_name(agent_id),
                ]
            fallback_name = next(
                (
                    candidate
                    for candidate in legacy_names
                    if candidate != name and self._client.has_collection(candidate)
                ),
                None,
            )
            if fallback_name is None:
                logger.info(
                    "vector store search name=%s agent_id=%s domain_id=%s "
                    "result=empty_reason=no_collection",
                    name,
                    agent_id,
                    domain_id,
                )
                return []
            name = fallback_name
            logger.info(
                "vector store search using legacy collection name=%s agent_id=%s "
                "domain_id=%s",
                name,
                agent_id,
                domain_id,
            )
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
            "vector store search name=%s agent_id=%s domain_id=%s top_k=%s hits=%s "
            "top_score=%s",
            name,
            agent_id,
            domain_id,
            top_k,
            len(out),
            f"{out[0].score:.4f}" if out else "N/A",
        )
        return out

    def delete_by_source(
        self,
        agent_id: int,
        source_type: str,
        source_id: int,
        *,
        domain_id: int | None = None,
        model_release_id: int | None = None,
        semantic_snapshot_id: int | None = None,
        embedding_model_config_id: int | None = None,
        embedding_model_version: str | None = None,
    ):
        """按 source_type + source_id 删除单条向量。"""
        name = self._collection_name(
            agent_id,
            domain_id,
            model_release_id=model_release_id,
            semantic_snapshot_id=semantic_snapshot_id,
            embedding_model_config_id=embedding_model_config_id,
            embedding_model_version=embedding_model_version,
        )
        if not self._client.has_collection(name):
            return
        self._client.delete(
            collection_name=name,
            filter=f'source_type == "{source_type}" and source_id == {source_id}',
        )
        logger.info(
            "vector store delete_by_source agent_id=%s type=%s id=%s",
            agent_id,
            source_type,
            source_id,
        )

    def delete_collection(
        self,
        agent_id: int | None,
        domain_id: int | None = None,
        *,
        model_release_id: int | None = None,
        semantic_snapshot_id: int | None = None,
        embedding_model_config_id: int | None = None,
        embedding_model_version: str | None = None,
    ):
        """Delete one versioned enterprise or historical collection."""
        name = self._collection_name(
            agent_id,
            domain_id,
            model_release_id=model_release_id,
            semantic_snapshot_id=semantic_snapshot_id,
            embedding_model_config_id=embedding_model_config_id,
            embedding_model_version=embedding_model_version,
        )
        if self._client.has_collection(name):
            self._client.drop_collection(name)
            logger.info(
                "vector store collection dropped agent_id=%s domain_id=%s",
                agent_id,
                domain_id,
            )

    def count(
        self,
        agent_id: int | None,
        domain_id: int | None = None,
        *,
        model_release_id: int | None = None,
        semantic_snapshot_id: int | None = None,
        embedding_model_config_id: int | None = None,
        embedding_model_version: str | None = None,
    ) -> int:
        """Return the row count for one enterprise or historical collection."""
        name = self._collection_name(
            agent_id,
            domain_id,
            model_release_id=model_release_id,
            semantic_snapshot_id=semantic_snapshot_id,
            embedding_model_config_id=embedding_model_config_id,
            embedding_model_version=embedding_model_version,
        )
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
