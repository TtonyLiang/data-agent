"""Embedding 服务 —— 通过 OpenAI 兼容接口调用向量模型。

EmbeddingService 负责:
1. ``embed_query``:单条文本向量化,返回指定维度的浮点向量。
2. ``embed_texts``:批量文本向量化(逐条调用,未做并行优化)。

支持按 agent_id 动态解析绑定的向量模型配置;
无绑定时回退到环境默认配置(embedding_base_url/embedding_model)。
"""

import hashlib
import json
import logging
import time

from app.config import get_settings
from app.services.embedding_adapter import request_embedding
from app.services.model_config_service import get_model_config_service

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding 向量化服务 —— 通过 OpenAI 兼容接口接入各向量模型。"""

    def __init__(self):
        s = get_settings()
        self._base_url = s.embedding_base_url.rstrip("/")
        self._api_key = s.embedding_api_key
        self._model = s.embedding_model
        self._dimension = s.embedding_dimension

    async def embed_texts(self, texts: list[str], agent_id: int | None = None) -> list[list[float]]:
        """批量文本向量化。当前逐条调用 embed_query,未做并行优化。"""
        results = []
        for text in texts:
            vec = await self.embed_query(text, agent_id=agent_id)
            results.append(vec)
        return results

    async def get_index_identity(self, agent_id: int | None = None) -> dict[str, object]:
        """Return the non-secret embedding identity used to version an index.

        Agent bindings are only a way to select an embedding configuration.
        The returned identity contains no Agent id, so Agents sharing the same
        configuration also share one enterprise semantic index.
        """
        provider = "openai-compatible"
        base_url = self._base_url
        model_name = self._model
        dimension = self._dimension
        config_id: int | None = None
        updated_at = None
        if agent_id:
            config = await get_model_config_service().get_agent_embedding_config(agent_id)
            if config is not None:
                config_id = int(config.id) if config.id is not None else None
                provider = config.provider
                base_url = config.base_url.rstrip("/")
                model_name = config.model_name
                dimension = int(config.embedding_dimension or self._dimension)
                updated_at = config.updated_at
        version_source = {
            "config_id": config_id,
            "provider": provider,
            "base_url": base_url,
            "model_name": model_name,
            "dimension": dimension,
            "updated_at": str(updated_at or ""),
        }
        version = hashlib.sha256(
            json.dumps(
                version_source,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "config_id": config_id,
            "version": version,
            "provider": provider,
            "model_name": model_name,
            "dimension": dimension,
        }

    async def embed_query(self, text: str, agent_id: int | None = None) -> list[float]:
        """单条文本向量化。

        优先使用 agent 绑定的向量模型配置;
        无绑定时回退到环境默认配置。
        """
        base_url = self._base_url
        api_key = self._api_key
        model = self._model
        provider = "openai-compatible"
        # 解析 agent 绑定的向量模型配置
        if agent_id:
            config = await get_model_config_service().get_agent_embedding_config(agent_id)
            if config is not None:
                base_url = config.base_url.rstrip("/")
                api_key = config.api_key if config.api_key_enabled else ""
                model = config.model_name
                provider = config.provider

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        started_at = time.monotonic()
        try:
            embedding, meta = await request_embedding(
                provider=provider,
                base_url=base_url,
                model=model,
                text=text,
                headers=headers,
                timeout=30,
            )
            duration_ms = round((time.monotonic() - started_at) * 1000, 2)
            logger.info(
                "embedding embed_query ok model=%s agent_id=%s dims=%s variant=%s duration_ms=%s",
                model,
                agent_id,
                len(embedding),
                meta.get("variant"),
                duration_ms,
            )
            return embedding
        except Exception as exc:
            duration_ms = round((time.monotonic() - started_at) * 1000, 2)
            logger.exception(
                "embedding embed_query FAILED model=%s agent_id=%s duration_ms=%s error=%s",
                model,
                agent_id,
                duration_ms,
                exc.__class__.__name__,
            )
            raise

    def get_dimension(self) -> int:
        """返回配置的向量维度。"""
        return self._dimension


# 全局单例
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """返回进程级 Embedding 服务单例。"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
