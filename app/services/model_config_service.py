from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.db.mysql import get_management_db
from app.models.model_config import (
    ModelConfig,
    ModelConfigCreate,
    ModelConfigType,
    ModelConfigUpdate,
)

MASKED_API_KEY_CHARS = {"*", "•"}


def _public_model_config(row: dict) -> dict:
    data = dict(row)
    data["api_key_configured"] = bool((data.get("api_key") or "").strip())
    expires_at = data.get("api_key_expires_at")
    expired, expires_soon = api_key_expiry_flags(expires_at)
    data["api_key_expired"] = expired
    data["api_key_expires_soon"] = expires_soon
    data.pop("api_key", None)
    return data


def _clean_api_key(api_key: str | None) -> str | None:
    value = (api_key or "").strip()
    return value or None


def _should_keep_existing_api_key(api_key: str | None) -> bool:
    value = (api_key or "").strip()
    return not value or set(value).issubset(MASKED_API_KEY_CHARS)


class ModelConfigService:
    async def create(self, config: ModelConfigCreate) -> int:
        db = get_management_db()
        return await db.execute_insert(
            "INSERT INTO model_config "
            "(name, model_type, provider, base_url, model_name, api_key, "
            "api_key_enabled, api_key_expires_at, embedding_dimension, status) "
            "VALUES (:name, :model_type, :provider, :base_url, :model_name, "
            ":api_key, :api_key_enabled, :api_key_expires_at, :dimension, :status)",
            {
                "name": config.name,
                "model_type": config.model_type,
                "provider": config.provider,
                "base_url": config.base_url,
                "model_name": config.model_name,
                "api_key": _clean_api_key(config.api_key),
                "api_key_enabled": int(config.api_key_enabled),
                "api_key_expires_at": config.api_key_expires_at,
                "dimension": config.embedding_dimension,
                "status": config.status,
            },
        )

    async def list(self, model_type: ModelConfigType | None = None) -> list[dict]:
        db = get_management_db()
        if model_type:
            rows = await db.execute_query(
                "SELECT * FROM model_config WHERE model_type = :model_type ORDER BY id ASC",
                {"model_type": model_type},
            )
        else:
            rows = await db.execute_query("SELECT * FROM model_config ORDER BY model_type, id ASC")
        return [_public_model_config(row) for row in rows]

    async def get(self, config_id: int) -> ModelConfig | None:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM model_config WHERE id = :id",
            {"id": config_id},
        )
        return ModelConfig(**rows[0]) if rows else None

    async def update(self, config_id: int, config: ModelConfigUpdate) -> ModelConfig | None:
        db = get_management_db()
        existing = await self.get(config_id)
        if existing is None:
            return None
        api_key = (
            existing.api_key
            if _should_keep_existing_api_key(config.api_key)
            else _clean_api_key(config.api_key)
        )
        await db.execute_query(
            "UPDATE model_config SET name = :name, model_type = :model_type, provider = :provider, "
            "base_url = :base_url, model_name = :model_name, api_key = :api_key, "
            "api_key_enabled = :api_key_enabled, api_key_expires_at = :api_key_expires_at, "
            "embedding_dimension = :dimension, status = :status "
            "WHERE id = :id",
            {
                "id": config_id,
                "name": config.name,
                "model_type": config.model_type,
                "provider": config.provider,
                "base_url": config.base_url,
                "model_name": config.model_name,
                "api_key": api_key,
                "api_key_enabled": int(config.api_key_enabled),
                "api_key_expires_at": config.api_key_expires_at,
                "dimension": config.embedding_dimension,
                "status": config.status,
            },
        )
        return await self.get(config_id)

    async def delete(self, config_id: int) -> bool:
        db = get_management_db()
        await db.execute_query(
            "UPDATE agent SET chat_model_config_id = NULL WHERE chat_model_config_id = :id",
            {"id": config_id},
        )
        await db.execute_query(
            "UPDATE agent SET embedding_model_config_id = NULL "
            "WHERE embedding_model_config_id = :id",
            {"id": config_id},
        )
        await db.execute_query("DELETE FROM model_config WHERE id = :id", {"id": config_id})
        return True

    async def test_connection(self, config_id: int) -> dict:
        config = await self.get(config_id)
        if config is None:
            return {"ok": False, "message": "模型配置不存在"}
        if config.api_key_enabled and not (config.api_key or "").strip():
            return {"ok": False, "message": "API Key 已启用但未配置"}

        endpoint = "chat/completions" if config.model_type == "chat" else "embeddings"
        url = f"{config.base_url.rstrip('/')}/{endpoint}"
        headers = {"Content-Type": "application/json"}
        if config.api_key_enabled and config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        payload = (
            {
                "model": config.model_name,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
                "temperature": 0,
            }
            if config.model_type == "chat"
            else {
                "model": config.model_name,
                "input": "ping",
            }
        )
        started_at = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json=payload, headers=headers)
            latency_ms = round((time.monotonic() - started_at) * 1000, 2)
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "message": safe_response_error(response.text),
                }
            return {
                "ok": True,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "message": "连接成功",
            }
        except Exception as exc:
            return {
                "ok": False,
                "message": f"连接失败: {exc.__class__.__name__}",
                "detail": str(exc)[:200],
            }

    async def get_agent_chat_config(self, agent_id: int) -> ModelConfig | None:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT mc.* FROM agent a JOIN model_config mc ON mc.id = a.chat_model_config_id "
            "WHERE a.id = :agent_id AND mc.model_type = 'chat'",
            {"agent_id": agent_id},
        )
        if rows:
            return ModelConfig(**rows[0])
        return await self.get_default("chat")

    async def get_agent_embedding_config(self, agent_id: int) -> ModelConfig | None:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT mc.* FROM agent a JOIN model_config mc ON mc.id = a.embedding_model_config_id "
            "WHERE a.id = :agent_id AND mc.model_type = 'embedding'",
            {"agent_id": agent_id},
        )
        if rows:
            return ModelConfig(**rows[0])
        return await self.get_default("embedding")

    async def get_default(self, model_type: ModelConfigType) -> ModelConfig | None:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM model_config WHERE model_type = :model_type ORDER BY id LIMIT 1",
            {"model_type": model_type},
        )
        if rows:
            return ModelConfig(**rows[0])
        s = get_settings()
        if model_type == "chat":
            return ModelConfig(
                id=None,
                name="环境默认大语言模型",
                model_type="chat",
                provider=s.llm_provider,
                base_url=s.llm_base_url,
                model_name=s.llm_model,
                api_key=s.llm_api_key,
                api_key_enabled=bool(s.llm_api_key),
                api_key_expires_at=None,
            )
        return ModelConfig(
            id=None,
            name="环境默认向量模型",
            model_type="embedding",
            provider="openai-compatible",
            base_url=s.embedding_base_url,
            model_name=s.embedding_model,
            api_key=s.embedding_api_key,
            api_key_enabled=bool(s.embedding_api_key),
            api_key_expires_at=None,
            embedding_dimension=s.embedding_dimension,
        )


_model_config_service: ModelConfigService | None = None


def get_model_config_service() -> ModelConfigService:
    global _model_config_service
    if _model_config_service is None:
        _model_config_service = ModelConfigService()
    return _model_config_service


def safe_response_error(text: str) -> str:
    compact = " ".join((text or "").split())
    if not compact:
        return "模型服务返回错误"
    return compact[:220]


def api_key_expiry_flags(expires_at) -> tuple[bool, bool]:
    if not expires_at:
        return False, False
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False, False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return expires_at <= now, now < expires_at <= now + timedelta(days=30)
