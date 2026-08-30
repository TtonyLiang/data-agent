"""模型配置管理服务 —— 大语言模型与向量模型的连接配置 CRUD。

ModelConfigService 负责:
1. 模型配置 CRUD(create/list/get/update/delete)。
2. 连通性测试(test_connection):chat 走 /chat/completions,embedding 走 /embeddings。
3. API Key 生命周期:加密落盘、掩码保护(不回显明文)、过期/即将过期提醒。
4. 按 agent 解析绑定的模型配置(get_agent_chat_config/get_agent_embedding_config)。

API Key 保护机制:
- 读取时解密,出参时去掉明文,只返回 api_key_configured(是否有值)和过期状态。
- 编辑时不传 Key 或传掩码字符(*•)时保留原密钥,避免误清空。
- api_key_expires_at 用于前端过期提醒,30 天内过期显示"即将过期"。

模型配置创建时会自动加密 api_key 落盘(通过 SecretService)。
"""

from __future__ import annotations

import json
import logging
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
from app.services.embedding_adapter import (
    EmbeddingProviderError,
    friendly_embedding_error_message,
    request_embedding,
)
from app.services.secret_service import get_secret_service
from app.utils.openai_compat import normalize_openai_base_url

logger = logging.getLogger(__name__)

# 掩码字符集:当 api_key 仅由这些字符组成时视为"未修改"
MASKED_API_KEY_CHARS = {"*", "•"}


def _public_model_config(row: dict) -> dict:
    """把数据库行转为 API 出参(去掉明文 api_key,添加脱敏标志)。"""
    data = dict(row)
    api_key = get_secret_service().decrypt(data.get("api_key"))
    data["api_key_configured"] = bool((api_key or "").strip())
    expires_at = data.get("api_key_expires_at")
    expired, expires_soon = api_key_expiry_flags(expires_at)
    data["api_key_expired"] = expired
    data["api_key_expires_soon"] = expires_soon
    data.pop("api_key", None)  # 去掉明文
    return data


def _clean_api_key(api_key: str | None) -> str | None:
    """清理 api_key:去空白,空值返回 None。"""
    value = (api_key or "").strip()
    return value or None


def _should_keep_existing_api_key(api_key: str | None) -> bool:
    """判断是否应保留原密钥:空值或掩码字符时保留。"""
    value = (api_key or "").strip()
    return not value or set(value).issubset(MASKED_API_KEY_CHARS)


class ModelConfigService:
    """模型配置管理服务。"""

    async def create(self, config: ModelConfigCreate) -> int:
        """创建模型配置,api_key 加密落盘。"""
        logger.info(
            "model_config create name=%s type=%s provider=%s",
            config.name, config.model_type, config.provider,
        )
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
                "api_key": get_secret_service().encrypt(_clean_api_key(config.api_key)),
                "api_key_enabled": int(config.api_key_enabled),
                "api_key_expires_at": config.api_key_expires_at,
                "dimension": config.embedding_dimension,
                "status": config.status,
            },
        )

    async def list(self, model_type: ModelConfigType | None = None) -> list[dict]:
        """列出模型配置,可按类型过滤。"""
        logger.info("model_config list type=%s", model_type)
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
        """按 id 加载模型配置(含解密 api_key)。"""
        logger.info("model_config get id=%s", config_id)
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM model_config WHERE id = :id",
            {"id": config_id},
        )
        return self._from_row(rows[0]) if rows else None

    async def update(self, config_id: int, config: ModelConfigUpdate) -> ModelConfig | None:
        """更新模型配置。api_key 为空或掩码时保留原密钥。"""
        logger.info("model_config update id=%s name=%s", config_id, config.name)
        db = get_management_db()
        existing = await self.get(config_id)
        if existing is None:
            return None

        # 决定 api_key:掩码或空值保留原密钥,否则用新值
        if _should_keep_existing_api_key(config.api_key):
            api_key = existing.api_key
            logger.info("model_config update id=%s api_key action=keep_existing", config_id)
        else:
            api_key = _clean_api_key(config.api_key)
            logger.info("model_config update id=%s api_key action=overwrite", config_id)

        encrypted_api_key = get_secret_service().encrypt(api_key)
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
                "api_key": encrypted_api_key,
                "api_key_enabled": int(config.api_key_enabled),
                "api_key_expires_at": config.api_key_expires_at,
                "dimension": config.embedding_dimension,
                "status": config.status,
            },
        )
        return await self.get(config_id)

    async def delete(self, config_id: int) -> bool:
        """删除模型配置,先清空引用再删记录。"""
        logger.info("model_config delete id=%s", config_id)
        db = get_management_db()
        # 先清空 agent 表中的外键引用,避免级联问题
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
        """测试模型连通性:chat 发 /chat/completions,embedding 走 provider adapter。"""
        config = await self.get(config_id)
        if config is None:
            return {"ok": False, "message": "模型配置不存在"}
        if config.api_key_enabled and not (config.api_key or "").strip():
            return {"ok": False, "message": "API Key 已启用但未配置"}

        normalized_base_url = normalize_openai_base_url(config.base_url)
        if not normalized_base_url:
            return {
                "ok": False,
                "message": "Base URL 未配置，请填写 OpenAI 兼容接口地址（通常以 /v1 结尾）",
            }

        headers = {"Content-Type": "application/json"}
        if config.api_key_enabled and config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        started_at = time.monotonic()
        try:
            if config.model_type == "embedding":
                vector, meta = await request_embedding(
                    provider=config.provider,
                    base_url=normalized_base_url,
                    model=config.model_name,
                    text="ping",
                    headers=headers,
                    timeout=10,
                )
                latency_ms = round((time.monotonic() - started_at) * 1000, 2)
                logger.info(
                    "model_config test_connection id=%s ok=true variant=%s dims=%s latency_ms=%s",
                    config_id,
                    meta.get("variant"),
                    len(vector),
                    latency_ms,
                )
                return {
                    "ok": True,
                    "status_code": meta.get("status_code", 200),
                    "latency_ms": latency_ms,
                    "message": f"连接成功（{len(vector)} 维，{meta.get('variant')}）",
                    "variant": meta.get("variant"),
                }

            url = f"{normalized_base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": config.model_name,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
                "temperature": 0,
            }
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json=payload, headers=headers)
            latency_ms = round((time.monotonic() - started_at) * 1000, 2)
            if response.status_code >= 400:
                logger.warning(
                    "model_config test_connection id=%s status=%s latency_ms=%s",
                    config_id, response.status_code, latency_ms,
                )
                return {
                    "ok": False,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "message": safe_response_error(response.text),
                }
            valid, validation_message = validate_chat_completion_response(response)
            if not valid:
                logger.warning(
                    "model_config test_connection id=%s invalid_response status=%s message=%s",
                    config_id,
                    response.status_code,
                    validation_message,
                )
                return {
                    "ok": False,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "message": validation_message,
                }
            logger.info(
                "model_config test_connection id=%s ok=true status=%s latency_ms=%s",
                config_id, response.status_code, latency_ms,
            )
            return {
                "ok": True,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "message": "连接成功",
            }
        except EmbeddingProviderError as exc:
            latency_ms = round((time.monotonic() - started_at) * 1000, 2)
            logger.warning(
                "model_config test_connection id=%s embedding failed "
                "status=%s latency_ms=%s attempts=%s",
                config_id,
                exc.status_code,
                latency_ms,
                len(exc.attempts),
            )
            return {
                "ok": False,
                "status_code": exc.status_code,
                "latency_ms": latency_ms,
                "message": friendly_embedding_error_message(exc),
                "detail": safe_response_error(exc.response_text),
                "attempts": [
                    {
                        k: v
                        for k, v in attempt.items()
                        if k in {"variant", "status_code", "message", "error"}
                    }
                    for attempt in exc.attempts
                ],
            }
        except Exception as exc:
            latency_ms = round((time.monotonic() - started_at) * 1000, 2)
            logger.exception(
                "model_config test_connection id=%s ok=false error=%s latency_ms=%s",
                config_id, exc.__class__.__name__, latency_ms,
            )
            return {
                "ok": False,
                "message": f"连接失败: {exc.__class__.__name__}",
                "detail": str(exc)[:200],
            }

    async def get_agent_chat_config(self, agent_id: int) -> ModelConfig | None:
        """解析 agent 绑定的大语言模型配置,无绑定时回退到默认配置。"""
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT mc.* FROM agent a JOIN model_config mc ON mc.id = a.chat_model_config_id "
            "WHERE a.id = :agent_id AND mc.model_type = 'chat'",
            {"agent_id": agent_id},
        )
        if rows:
            return self._from_row(rows[0])
        return await self.get_default("chat")

    async def get_agent_embedding_config(self, agent_id: int) -> ModelConfig | None:
        """解析 agent 绑定的向量模型配置,无绑定时回退到默认配置。"""
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT mc.* FROM agent a JOIN model_config mc ON mc.id = a.embedding_model_config_id "
            "WHERE a.id = :agent_id AND mc.model_type = 'embedding'",
            {"agent_id": agent_id},
        )
        if rows:
            return self._from_row(rows[0])
        return await self.get_default("embedding")

    async def get_default(self, model_type: ModelConfigType) -> ModelConfig | None:
        """获取默认模型配置:优先从数据库取第一个,不存在则用环境变量构建。"""
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM model_config WHERE model_type = :model_type ORDER BY id LIMIT 1",
            {"model_type": model_type},
        )
        if rows:
            return ModelConfig(**rows[0])
        # 数据库无配置时,用环境变量兜底
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

    def _from_row(self, row: dict) -> ModelConfig:
        """数据库行转 ModelConfig,解密 api_key。"""
        data = dict(row)
        data["api_key"] = get_secret_service().decrypt(data.get("api_key"))
        return ModelConfig(**data)


# 全局单例
_model_config_service: ModelConfigService | None = None


def get_model_config_service() -> ModelConfigService:
    """返回进程级模型配置服务单例。"""
    global _model_config_service
    if _model_config_service is None:
        _model_config_service = ModelConfigService()
    return _model_config_service


def safe_response_error(text: str) -> str:
    """把 HTTP 错误响应体压缩为简短摘要,避免日志过长。"""
    compact = " ".join((text or "").split())
    if not compact:
        return "模型服务返回错误"
    return compact[:220]


def validate_chat_completion_response(response: httpx.Response) -> tuple[bool, str]:
    """Validate the minimal OpenAI Chat Completions response contract.

    A reverse proxy may return its HTML landing page with HTTP 200, which would
    otherwise make a connectivity check report a false success.  Requiring a
    JSON object with at least one choice catches that configuration error before
    the agent attempts a real query.
    """
    headers = getattr(response, "headers", {}) or {}
    content_type = ""
    for key, value in headers.items():
        if str(key).lower() == "content-type":
            content_type = str(value).lower()
            break
    if "text/html" in content_type:
        return (
            False,
            "模型服务返回了 HTML 页面，不是 OpenAI 兼容接口；请检查 Base URL，通常应包含 /v1。",
        )

    try:
        payload = response.json()
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return (
            False,
            "模型服务返回的不是有效 JSON；请检查 Base URL 是否指向 OpenAI "
            "Chat Completions 接口（通常包含 /v1）。",
        )

    if not isinstance(payload, dict):
        return (
            False,
            "模型服务返回格式不兼容；请确认 Base URL 指向 OpenAI Chat Completions 接口。",
        )
    if payload.get("error"):
        return (
            False,
            f"模型服务返回错误：{safe_response_error(getattr(response, 'text', ''))}".strip(),
        )

    choices = payload.get("choices")
    if not isinstance(choices, list):
        return (
            False,
            "模型服务返回格式不兼容，缺少 choices；请确认 Base URL 和模型名称正确。",
        )
    if not choices:
        return (
            False,
            "模型服务返回格式不兼容，choices 为空；请确认模型名称有效且服务端已配置可用模型。",
        )
    return True, ""


def api_key_expiry_flags(expires_at) -> tuple[bool, bool]:
    """判断 API Key 是否已过期或即将过期(30 天内)。

    返回 (expired, expires_soon):
    - expired:已过期(True 时应阻止调用)
    - expires_soon:30 天内过期(True 时前端显示提醒)
    """
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
    expired = expires_at <= now
    expires_soon = now < expires_at <= now + timedelta(days=30)
    return expired, expires_soon
