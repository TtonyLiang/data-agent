"""系统参数服务 —— 运行时可调参数的读取与更新。

SystemParameterService 负责:
1. ``list``:列出所有系统参数,可按 category 过滤。
2. ``update_many``:批量更新参数值,只允许更新已有参数。
3. ``get_schema_recall_settings``:读取数据定位阈值配置。

参数缓存:
``_load_rows`` 内部维护 30 秒进程内缓存,避免每次查询都读数据库。
``update_many`` 写入后主动清缓存,下次读取时从数据库重新加载。

当前支持的参数(由 migrations.py seed):
- schema_recall.max_tables:最多候选表数(默认 6)
- schema_recall.required_score_ratio:必须召回相对分阈值(默认 0.35)
- schema_recall.optional_score_ratio:可召回相对分阈值(默认 0.15)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import get_settings
from app.db.mysql import get_management_db
from app.models.system_parameter import SchemaRecallSettings, SystemParameterUpdate

logger = logging.getLogger(__name__)

# 数据定位参数 key 常量
SCHEMA_RECALL_MAX_TABLES = "schema_recall.max_tables"
SCHEMA_RECALL_REQUIRED_RATIO = "schema_recall.required_score_ratio"
SCHEMA_RECALL_OPTIONAL_RATIO = "schema_recall.optional_score_ratio"


class SystemParameterService:
    """系统参数管理服务。"""

    def __init__(self) -> None:
        self._cache: tuple[float, dict[str, dict[str, Any]]] | None = None
        self._cache_ttl_seconds = 30

    async def list(self, category: str | None = None) -> list[dict[str, Any]]:
        """列出系统参数,可按 category 过滤。"""
        rows = await self._load_rows()
        params = list(rows.values())
        if category:
            params = [item for item in params if item.get("category") == category]
        return sorted(params, key=lambda item: (item.get("category") or "", item.get("key") or ""))

    async def update_many(self, updates: list[SystemParameterUpdate]) -> list[dict[str, Any]]:
        """批量更新系统参数值。只允许更新已存在的 key。"""
        db = get_management_db()
        rows = await self._load_rows(force=True)

        statements: list[tuple[str, dict | None]] = []
        for update in updates:
            if update.key not in rows:
                raise ValueError(f"未知系统参数: {update.key}")
            row = rows[update.key]
            value = normalize_value(update.value, row.get("value_type") or "string")
            statements.append(
                (
                    "UPDATE system_parameter SET value_json = :value_json WHERE param_key = :key",
                    {
                        "key": update.key,
                        "value_json": json.dumps(value, ensure_ascii=False),
                    },
                )
            )

        logger.info("system_parameter update_many keys=%s", [u.key for u in updates])
        if statements:
            await db.execute_transaction(statements)
        self.clear_cache()
        return await self.list()

    async def get_schema_recall_settings(self) -> SchemaRecallSettings:
        """读取数据定位阈值配置,无配置时使用 settings 默认值。"""
        rows = await self._load_rows()
        defaults = get_settings()
        settings = SchemaRecallSettings(
            max_tables=int(
                _param_value(rows, SCHEMA_RECALL_MAX_TABLES, defaults.schema_recall_max_tables)
            ),
            required_score_ratio=float(
                _param_value(rows, SCHEMA_RECALL_REQUIRED_RATIO, defaults.schema_recall_required_score_ratio)
            ),
            optional_score_ratio=float(
                _param_value(rows, SCHEMA_RECALL_OPTIONAL_RATIO, defaults.schema_recall_optional_score_ratio)
            ),
        )
        logger.info(
            "system_parameter schema_recall max_tables=%s required=%s optional=%s",
            settings.max_tables, settings.required_score_ratio, settings.optional_score_ratio,
        )
        return settings

    async def _load_rows(self, *, force: bool = False) -> dict[str, dict[str, Any]]:
        """加载全部系统参数(带 30 秒缓存)。force=True 时跳过缓存。"""
        now = time.monotonic()
        if (
            not force
            and self._cache is not None
            and now - self._cache[0] <= self._cache_ttl_seconds
        ):
            logger.debug("system_parameter _load_rows cache_hit")
            return self._cache[1]

        logger.info("system_parameter _load_rows loading_from_db")
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT param_key, name, value_json, value_type, category, description, "
            "created_at, updated_at FROM system_parameter ORDER BY category, param_key"
        )
        indexed = {str(row["param_key"]): public_row(row) for row in rows}
        self._cache = (now, indexed)
        return indexed

    def clear_cache(self) -> None:
        """清空缓存,下次 _load_rows 时重新读取数据库。"""
        self._cache = None


def public_row(row: dict[str, Any]) -> dict[str, Any]:
    """把数据库行转为 API 出参格式(value_json 解析为 Python 对象)。"""
    value = row.get("value_json")
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        parsed = value
    return {
        "key": row.get("param_key"),
        "name": row.get("name"),
        "value": parsed,
        "value_type": row.get("value_type") or "string",
        "category": row.get("category") or "general",
        "description": row.get("description") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def normalize_value(value: Any, value_type: str) -> Any:
    """按 value_type 把字符串值转换为对应类型。"""
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        return bool(value)
    return value


def _param_value(rows: dict[str, dict[str, Any]], key: str, fallback: Any) -> Any:
    """从 rows 中取参数值,key 不存在或值为 None 时返回 fallback。"""
    row = rows.get(key)
    if not row:
        return fallback
    value = row.get("value")
    return fallback if value is None else value


# 全局单例
_system_parameter_service: SystemParameterService | None = None


def get_system_parameter_service() -> SystemParameterService:
    """返回进程级系统参数服务单例。"""
    global _system_parameter_service
    if _system_parameter_service is None:
        _system_parameter_service = SystemParameterService()
    return _system_parameter_service
