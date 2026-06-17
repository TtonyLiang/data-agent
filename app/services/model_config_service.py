from __future__ import annotations

from app.config import get_settings
from app.db.mysql import get_management_db
from app.models.model_config import ModelConfig, ModelConfigCreate, ModelConfigType, ModelConfigUpdate


MASKED_API_KEY_CHARS = {"*", "•"}


def _public_model_config(row: dict) -> dict:
    data = dict(row)
    data["api_key_configured"] = bool((data.get("api_key") or "").strip())
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
            "(name, model_type, provider, base_url, model_name, api_key, api_key_enabled, embedding_dimension, status) "
            "VALUES (:name, :model_type, :provider, :base_url, :model_name, :api_key, :api_key_enabled, :dimension, :status)",
            {
                "name": config.name,
                "model_type": config.model_type,
                "provider": config.provider,
                "base_url": config.base_url,
                "model_name": config.model_name,
                "api_key": _clean_api_key(config.api_key),
                "api_key_enabled": int(config.api_key_enabled),
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
        api_key = existing.api_key if _should_keep_existing_api_key(config.api_key) else _clean_api_key(config.api_key)
        await db.execute_query(
            "UPDATE model_config SET name = :name, model_type = :model_type, provider = :provider, "
            "base_url = :base_url, model_name = :model_name, api_key = :api_key, "
            "api_key_enabled = :api_key_enabled, embedding_dimension = :dimension, status = :status "
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
            "UPDATE agent SET embedding_model_config_id = NULL WHERE embedding_model_config_id = :id",
            {"id": config_id},
        )
        await db.execute_query("DELETE FROM model_config WHERE id = :id", {"id": config_id})
        return True

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
            embedding_dimension=s.embedding_dimension,
        )


_model_config_service: ModelConfigService | None = None


def get_model_config_service() -> ModelConfigService:
    global _model_config_service
    if _model_config_service is None:
        _model_config_service = ModelConfigService()
    return _model_config_service
