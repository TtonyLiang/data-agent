from __future__ import annotations

import json
import time
from typing import Any

from app.config import get_settings
from app.db.mysql import get_management_db
from app.models.system_parameter import SchemaRecallSettings, SystemParameterUpdate


SCHEMA_RECALL_MAX_TABLES = "schema_recall.max_tables"
SCHEMA_RECALL_REQUIRED_RATIO = "schema_recall.required_score_ratio"
SCHEMA_RECALL_OPTIONAL_RATIO = "schema_recall.optional_score_ratio"


class SystemParameterService:
    def __init__(self) -> None:
        self._cache: tuple[float, dict[str, dict[str, Any]]] | None = None
        self._cache_ttl_seconds = 30

    async def list(self, category: str | None = None) -> list[dict[str, Any]]:
        rows = await self._load_rows()
        params = list(rows.values())
        if category:
            params = [item for item in params if item.get("category") == category]
        return sorted(params, key=lambda item: (item.get("category") or "", item.get("key") or ""))

    async def update_many(self, updates: list[SystemParameterUpdate]) -> list[dict[str, Any]]:
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
        if statements:
            await db.execute_transaction(statements)
        self.clear_cache()
        return await self.list()

    async def get_schema_recall_settings(self) -> SchemaRecallSettings:
        rows = await self._load_rows()
        defaults = get_settings()
        return SchemaRecallSettings(
            max_tables=int(
                _param_value(
                    rows,
                    SCHEMA_RECALL_MAX_TABLES,
                    defaults.schema_recall_max_tables,
                )
            ),
            required_score_ratio=float(
                _param_value(
                    rows,
                    SCHEMA_RECALL_REQUIRED_RATIO,
                    defaults.schema_recall_required_score_ratio,
                )
            ),
            optional_score_ratio=float(
                _param_value(
                    rows,
                    SCHEMA_RECALL_OPTIONAL_RATIO,
                    defaults.schema_recall_optional_score_ratio,
                )
            ),
        )

    async def _load_rows(self, *, force: bool = False) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        if (
            not force
            and self._cache is not None
            and now - self._cache[0] <= self._cache_ttl_seconds
        ):
            return self._cache[1]
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT param_key, name, value_json, value_type, category, description, "
            "created_at, updated_at FROM system_parameter ORDER BY category, param_key"
        )
        indexed = {str(row["param_key"]): public_row(row) for row in rows}
        self._cache = (now, indexed)
        return indexed

    def clear_cache(self) -> None:
        self._cache = None


def public_row(row: dict[str, Any]) -> dict[str, Any]:
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
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        return bool(value)
    return value


def _param_value(rows: dict[str, dict[str, Any]], key: str, fallback: Any) -> Any:
    row = rows.get(key)
    if not row:
        return fallback
    value = row.get("value")
    return fallback if value is None else value


_system_parameter_service: SystemParameterService | None = None


def get_system_parameter_service() -> SystemParameterService:
    global _system_parameter_service
    if _system_parameter_service is None:
        _system_parameter_service = SystemParameterService()
    return _system_parameter_service
