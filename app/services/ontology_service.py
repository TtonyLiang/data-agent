"""Operational Ontology definition, runtime, publishing, and audit service."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text

from app.db.mysql import get_datasource_db, get_management_db
from app.models.ontology import (
    OntologyActionExecutePayload,
    OntologyActionTypePayload,
    OntologyLinkPayload,
    OntologyLinkTypePayload,
    OntologyObjectPayload,
    OntologyObjectTypePayload,
)
from app.models.user import ontology_action_role
from app.services.datasource_service import get_datasource_service
from app.services.decision_audit_service import get_decision_audit_service
from app.services.model_release_service import get_model_release_service
from app.services.permission_service import (
    ColumnPolicy,
    PermissionRuntimeContext,
    PermissionService,
    get_permission_service,
    mask_value,
)
from app.utils.sql_validator import (
    extract_table_references,
    find_top_level_keyword,
    normalize_sql_for_execution,
    tokenize_sql,
)

JSON_FIELDS = {
    "default_value",
    "parameters",
    "preconditions",
    "effects",
    "allowed_roles",
    "properties",
    "source_properties",
    "overlay_properties",
    "decision_context",
    "before_state",
    "after_state",
    "validation_json",
    "definition_json",
}

JSON_FALLBACKS: dict[str, Any] = {
    "default_value": None,
    "parameters": [],
    "preconditions": [],
    "effects": [],
    "allowed_roles": [],
    "properties": {},
    "source_properties": {},
    "overlay_properties": {},
    "decision_context": {},
    "before_state": {},
    "after_state": {},
    "validation_json": {},
    "definition_json": {},
}

_OBJECT_PERMISSION_FIELDS = {
    "_permission_source_query",
    "_permission_primary_property",
    "_permission_display_property",
}

_MASKING_PRIORITY = {"none": 0, "partial": 1, "hash": 2, "redact": 3}
_RELATION_PROPERTY_SEPARATOR = ","


logger = logging.getLogger(__name__)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _content_hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_VOLATILE_DEFINITION_FIELDS = {
    "id",
    "domain_id",
    "object_type_id",
    "created_at",
    "updated_at",
    "last_sync_status",
    "last_sync_count",
    "last_sync_total",
    "last_sync_error",
    "last_synced_at",
}

_SYNC_TELEMETRY_FIELDS = (
    "last_sync_status",
    "last_sync_count",
    "last_sync_total",
    "last_sync_error",
    "last_synced_at",
)


def _stable_release_definition(bundle: dict[str, Any]) -> dict[str, Any]:
    """Remove storage/runtime fields before hashing an Ontology definition.

    Relationship key arrays are derived fields returned by the runtime.  The
    canonical representation stores the ordered compound key in the legacy
    ``*_property`` value so old and new runtime rows hash identically.
    """

    def clean_record(value: dict[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(item)
            for key, item in value.items()
            if key not in _VOLATILE_DEFINITION_FIELDS
        }

    def clean_link_type(value: dict[str, Any]) -> dict[str, Any]:
        link_type = clean_record(value)
        for side in ("source", "target"):
            plural_key = f"{side}_property_keys"
            singular_key = f"{side}_property"
            property_keys = link_type.pop(plural_key, None)
            if isinstance(property_keys, list) and property_keys:
                normalized_keys = [str(key).strip() for key in property_keys]
                if all(normalized_keys):
                    link_type[singular_key] = _RELATION_PROPERTY_SEPARATOR.join(
                        normalized_keys
                    )
        return link_type

    definition = {
        "format": bundle.get("format"),
        "version": bundle.get("version"),
        "domain": clean_record(bundle.get("domain") or {}),
        "object_types": [],
        "link_types": [clean_link_type(item) for item in bundle.get("link_types") or []],
        "action_types": [clean_record(item) for item in bundle.get("action_types") or []],
    }
    for item in bundle.get("object_types") or []:
        object_type = clean_record(item)
        object_type["properties"] = [clean_record(prop) for prop in item.get("properties") or []]
        definition["object_types"].append(object_type)
    definition["object_types"] = sorted(
        definition["object_types"], key=lambda item: str(item.get("object_key") or "")
    )
    for object_type in definition["object_types"]:
        object_type["properties"] = sorted(
            object_type.get("properties") or [],
            key=lambda item: (
                int(item.get("sort_order") or 0),
                str(item.get("property_key") or ""),
            ),
        )
    definition["link_types"] = sorted(
        definition.get("link_types") or [], key=lambda item: str(item.get("link_key") or "")
    )
    definition["action_types"] = sorted(
        definition.get("action_types") or [], key=lambda item: str(item.get("action_key") or "")
    )
    return definition


def _loads(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for key in JSON_FIELDS:
        if key in normalized:
            normalized[key] = _loads(normalized[key], JSON_FALLBACKS[key])
    for key in ("required", "unique", "requires_approval", "sync_enabled"):
        if key in normalized:
            normalized[key] = bool(normalized[key])
    return normalized


def _relation_property_keys(link_type: dict[str, Any], side: str) -> list[str]:
    """Return the ordered property tuple for one relationship endpoint.

    New definitions expose ``*_property_keys``.  Existing rows keep using the
    single ``*_property`` column; compound keys are persisted there as a
    comma-separated list because property identifiers cannot contain commas.
    """

    plural_name = f"{side}_property_keys"
    singular_name = f"{side}_property"
    raw_plural = link_type.get(plural_name)
    if raw_plural is not None:
        if not isinstance(raw_plural, list):
            raise ValueError(f"关系{side}复合属性键格式无效")
        keys = [str(value).strip() for value in raw_plural]
    else:
        raw_singular = link_type.get(singular_name)
        keys = (
            [part.strip() for part in str(raw_singular).split(_RELATION_PROPERTY_SEPARATOR)]
            if raw_singular is not None
            else []
        )
    if not keys or any(not key for key in keys):
        raise ValueError(f"关系{side}属性键不能为空")
    if len(keys) != len(set(keys)):
        raise ValueError(f"关系{side}属性键不能重复")
    return keys


def _normalize_link_type_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_row(row)
    source_keys = _relation_property_keys(normalized, "source")
    target_keys = _relation_property_keys(normalized, "target")
    if len(source_keys) != len(target_keys):
        raise ValueError("关系两端的复合属性键数量必须一致")
    normalized["source_property"] = source_keys[0]
    normalized["target_property"] = target_keys[0]
    normalized["source_property_keys"] = source_keys
    normalized["target_property_keys"] = target_keys
    return normalized


def _encode_relation_property_keys(keys: list[str], side: str) -> str:
    encoded = _RELATION_PROPERTY_SEPARATOR.join(keys)
    if len(encoded) > 128:
        raise ValueError(f"关系{side}复合属性键总长度不能超过 128 个字符")
    return encoded


class OntologyService:
    async def _append_action_audit(
        self,
        session: Any,
        *,
        domain_id: int,
        run_id: int,
        release_id: int,
        action: dict[str, Any],
        target_object_id: int,
        user: dict[str, Any],
        status: str,
        payload: dict[str, Any],
    ) -> int:
        event = await get_decision_audit_service().append_in_session(
            session,
            domain_id=domain_id,
            event_type=f"ontology.action.{status}",
            entity_type="ontology_action_run",
            entity_id=run_id,
            actor_id=int(user["id"]) if user.get("id") is not None else None,
            actor=str(
                user.get("display_name") or user.get("username") or user.get("id") or "unknown"
            ),
            ontology_release_id=release_id,
            payload={
                "action_key": action.get("action_key"),
                "target_object_id": target_object_id,
                "status": status,
                **payload,
            },
        )
        return int(event["id"])

    async def _require_domain(self, domain_id: int) -> dict[str, Any]:
        rows = await get_management_db().execute_query(
            "SELECT * FROM semantic_domain WHERE id = :id", {"id": domain_id}
        )
        if not rows:
            raise ValueError("Ontology 领域不存在")
        return rows[0]

    async def get_summary(self, domain_id: int) -> dict[str, Any]:
        domain = await self._require_domain(domain_id)
        db = get_management_db()
        tables = {
            "object_types": "ontology_object_type",
            "link_types": "ontology_link_type",
            "action_types": "ontology_action_type",
            "objects": "ontology_object",
            "links": "ontology_link",
            "action_runs": "ontology_action_run",
        }
        counts: dict[str, int] = {}
        for key, table in tables.items():
            rows = await db.execute_query(
                f"SELECT COUNT(*) AS count FROM {table} WHERE domain_id = :domain_id",
                {"domain_id": domain_id},
            )
            counts[key] = int(rows[0]["count"]) if rows else 0
        source_count_rows = await db.execute_query(
            "SELECT COALESCE(SUM(last_sync_total), 0) AS count "
            "FROM ontology_object_type WHERE domain_id = :domain_id AND sync_enabled = 1",
            {"domain_id": domain_id},
        )
        counts["source_objects"] = (
            int(source_count_rows[0].get("count") or 0) if source_count_rows else 0
        )
        release_rows = await db.execute_query(
            "SELECT id, version, name, description, published_by, created_at "
            "FROM ontology_release WHERE domain_id = :domain_id ORDER BY version DESC LIMIT 1",
            {"domain_id": domain_id},
        )
        return {
            "domain": domain,
            "counts": counts,
            "latest_release": release_rows[0] if release_rows else None,
        }

    async def list_object_types(self, domain_id: int) -> list[dict[str, Any]]:
        await self._require_domain(domain_id)
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM ontology_object_type WHERE domain_id = :domain_id ORDER BY id ASC",
            {"domain_id": domain_id},
        )
        property_rows = await db.execute_query(
            "SELECT p.* FROM ontology_property p "
            "JOIN ontology_object_type o ON o.id = p.object_type_id "
            "WHERE o.domain_id = :domain_id ORDER BY p.object_type_id, p.sort_order, p.id",
            {"domain_id": domain_id},
        )
        by_object: dict[int, list[dict[str, Any]]] = {}
        for prop in property_rows:
            normalized = _normalize_row(prop)
            by_object.setdefault(int(prop["object_type_id"]), []).append(normalized)
        return [
            {**_normalize_row(row), "properties": by_object.get(int(row["id"]), [])} for row in rows
        ]

    async def get_object_type(
        self, domain_id: int, *, object_type_id: int | None = None, object_key: str | None = None
    ) -> dict[str, Any] | None:
        object_types = await self.list_object_types(domain_id)
        for item in object_types:
            if object_type_id is not None and int(item["id"]) == object_type_id:
                return item
            if object_key is not None and item["object_key"] == object_key:
                return item
        return None

    async def prepare_release_sync_definition(
        self,
        domain_id: int,
        release_definition: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        """Bind an immutable release definition to current storage row IDs.

        The release owns business/technical behavior such as SQL, properties,
        relation keys, and action effects.  Current rows are consulted only to
        resolve the physical IDs required by the instance tables; draft values
        are never merged into the released definition.
        """
        if not isinstance(release_definition, dict):
            raise ValueError("激活企业模型关联的 Ontology 定义无效")
        live_object_types = await self.list_object_types(domain_id)
        live_link_types = await self.list_link_types(domain_id)
        live_action_types = await self.list_action_types(domain_id)
        object_by_key = {
            str(item.get("object_key")): item for item in live_object_types
        }
        link_by_key = {
            str(item.get("link_key")): item for item in live_link_types
        }
        action_by_key = {
            str(item.get("action_key")): item for item in live_action_types
        }

        def active_items(key: str) -> list[dict[str, Any]]:
            items = release_definition.get(key) or []
            if not isinstance(items, list):
                raise ValueError(f"激活企业模型的 {key} 定义无效")
            return [
                item
                for item in items
                if isinstance(item, dict)
                and str(item.get("status") or "active").lower() == "active"
            ]

        object_types: list[dict[str, Any]] = []
        for released in active_items("object_types"):
            object_key = str(released.get("object_key") or "").strip()
            live = object_by_key.get(object_key)
            if live is None:
                raise ValueError(
                    f"激活企业模型的对象类型 {object_key or '未命名'} 已不存在，不能同步"
                )
            object_types.append(
                {
                    **_normalize_row(released),
                    "id": int(live["id"]),
                    "domain_id": domain_id,
                    **{field: live.get(field) for field in _SYNC_TELEMETRY_FIELDS},
                }
            )

        link_types: list[dict[str, Any]] = []
        for released in active_items("link_types"):
            link_key = str(released.get("link_key") or "").strip()
            live = link_by_key.get(link_key)
            if live is None:
                raise ValueError(
                    f"激活企业模型的关系类型 {link_key or '未命名'} 已不存在，不能同步"
                )
            link_types.append(
                {
                    **_normalize_row(released),
                    "id": int(live["id"]),
                    "domain_id": domain_id,
                }
            )

        action_types: list[dict[str, Any]] = []
        for released in active_items("action_types"):
            action_key = str(released.get("action_key") or "").strip()
            live = action_by_key.get(action_key)
            if live is None:
                raise ValueError(
                    f"激活企业模型的动作类型 {action_key or '未命名'} 已不存在，不能运行"
                )
            action_types.append(
                {
                    **_normalize_row(released),
                    "id": int(live["id"]),
                    "domain_id": domain_id,
                }
            )

        return {
            "object_types": object_types,
            "link_types": link_types,
            "action_types": action_types,
        }

    async def get_release_scoped_definitions(
        self,
        domain_id: int,
        *,
        require_active_release: bool = True,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return runtime definitions from the active release only.

        Management screens keep using the live draft tables. Runtime screens
        call this method so edits in a draft cannot change the definitions,
        labels, mappings, or action effects used by an already active model.
        """
        _, _, _, definition, _ = await self._load_runtime_definition(
            domain_id,
            allow_compatibility_fallback=not require_active_release,
        )
        if definition is None:
            return {
                "object_types": await self.list_object_types(domain_id),
                "link_types": await self.list_link_types(domain_id),
                "action_types": await self.list_action_types(domain_id),
            }
        return await self.prepare_release_sync_definition(domain_id, definition)

    async def upsert_object_type(self, payload: OntologyObjectTypePayload) -> int:
        await self._require_domain(payload.domain_id)
        properties = [item.model_dump() for item in payload.properties]
        property_keys = [item["property_key"] for item in properties]
        if len(property_keys) != len(set(property_keys)):
            raise ValueError("对象属性标识不能重复")
        if payload.primary_property not in property_keys:
            raise ValueError("主属性必须是对象已定义的属性")
        if payload.display_property and payload.display_property not in property_keys:
            raise ValueError("显示属性必须是对象已定义的属性")
        source_query = payload.source_query.strip().rstrip(";")
        if payload.sync_enabled and not source_query:
            raise ValueError("启用业务库同步时必须配置只读 SELECT")
        if source_query:
            validation = normalize_sql_for_execution(source_query, max_limit=payload.sync_limit)
            if not validation.ok:
                raise ValueError(f"对象同步 SQL 无效: {validation.reason}")
            if find_top_level_keyword(tokenize_sql(validation.sql), "ORDER") is None:
                raise ValueError("对象同步 SQL 必须包含稳定的 ORDER BY，保证分页结果一致")

        db = get_management_db()
        duplicate = await db.execute_query(
            "SELECT id FROM ontology_object_type WHERE domain_id = :domain_id "
            "AND object_key = :object_key AND (:id IS NULL OR id <> :id)",
            {
                "domain_id": payload.domain_id,
                "object_key": payload.object_key,
                "id": payload.id,
            },
        )
        if duplicate:
            raise ValueError(f"对象标识已存在: {payload.object_key}")
        params = {
            **payload.model_dump(exclude={"id", "properties", "source_query"}),
            "source_query": source_query,
            "sync_enabled": int(payload.sync_enabled),
        }
        if payload.id:
            existing = await db.execute_query(
                "SELECT id FROM ontology_object_type WHERE id = :id AND domain_id = :domain_id",
                {"id": payload.id, "domain_id": payload.domain_id},
            )
            if not existing:
                raise ValueError("对象类型不存在")
            await db.execute_query(
                "UPDATE ontology_object_type SET object_key = :object_key, name = :name, "
                "description = :description, primary_property = :primary_property, "
                "display_property = :display_property, sync_enabled = :sync_enabled, "
                "source_query = :source_query, sync_limit = :sync_limit, status = :status "
                "WHERE id = :id",
                {**params, "id": payload.id},
            )
            object_type_id = payload.id
        else:
            object_type_id = await db.execute_insert(
                "INSERT INTO ontology_object_type "
                "(domain_id, object_key, name, description, primary_property, "
                "display_property, sync_enabled, source_query, sync_limit, status) "
                "VALUES (:domain_id, :object_key, :name, :description, :primary_property, "
                ":display_property, :sync_enabled, :source_query, :sync_limit, :status)",
                params,
            )
        statements: list[tuple[str, dict[str, Any]]] = [
            (
                "DELETE FROM ontology_property WHERE object_type_id = :object_type_id",
                {"object_type_id": object_type_id},
            )
        ]
        for index, prop in enumerate(properties):
            statements.append(
                (
                    "INSERT INTO ontology_property "
                    "(object_type_id, property_key, name, data_type, required, `unique`, "
                    "description, default_value, sort_order) VALUES "
                    "(:object_type_id, :property_key, :name, :data_type, :required, :unique, "
                    ":description, :default_value, :sort_order)",
                    {
                        **prop,
                        "object_type_id": object_type_id,
                        "required": int(prop["required"]),
                        "unique": int(prop["unique"]),
                        "default_value": _json(prop["default_value"]),
                        "sort_order": prop.get("sort_order") or index,
                    },
                )
            )
        await db.execute_transaction(statements)
        return int(object_type_id)

    async def delete_object_type(self, domain_id: int, object_type_id: int) -> bool:
        object_type = await self.get_object_type(domain_id, object_type_id=object_type_id)
        if not object_type:
            return False
        db = get_management_db()
        object_key = object_type["object_key"]
        object_rows = await db.execute_query(
            "SELECT id FROM ontology_object WHERE object_type_id = :object_type_id",
            {"object_type_id": object_type_id},
        )
        object_ids = [int(row["id"]) for row in object_rows]
        statements: list[tuple[str, dict[str, Any] | None]] = []
        for object_id in object_ids:
            statements.append(
                (
                    "DELETE FROM ontology_link WHERE source_object_id = :id "
                    "OR target_object_id = :id",
                    {"id": object_id},
                )
            )
        statements.extend(
            [
                ("DELETE FROM ontology_object WHERE object_type_id = :id", {"id": object_type_id}),
                (
                    "DELETE FROM ontology_link_type WHERE domain_id = :domain_id "
                    "AND (source_object_key = :key OR target_object_key = :key)",
                    {"domain_id": domain_id, "key": object_key},
                ),
                (
                    "DELETE FROM ontology_action_type WHERE domain_id = :domain_id "
                    "AND target_object_key = :key",
                    {"domain_id": domain_id, "key": object_key},
                ),
                (
                    "DELETE FROM ontology_property WHERE object_type_id = :id",
                    {"id": object_type_id},
                ),
                (
                    "DELETE FROM ontology_object_type WHERE id = :id AND domain_id = :domain_id",
                    {"id": object_type_id, "domain_id": domain_id},
                ),
            ]
        )
        await db.execute_transaction(statements)
        return True

    async def list_link_types(self, domain_id: int) -> list[dict[str, Any]]:
        await self._require_domain(domain_id)
        rows = await get_management_db().execute_query(
            "SELECT * FROM ontology_link_type WHERE domain_id = :domain_id ORDER BY id ASC",
            {"domain_id": domain_id},
        )
        return [_normalize_link_type_row(row) for row in rows]

    async def upsert_link_type(self, payload: OntologyLinkTypePayload) -> int:
        await self._require_domain(payload.domain_id)
        source = await self.get_object_type(payload.domain_id, object_key=payload.source_object_key)
        target = await self.get_object_type(payload.domain_id, object_key=payload.target_object_key)
        if not source or not target:
            raise ValueError("关系的起点和终点必须引用已存在的对象类型")
        source_keys = list(
            payload.source_property_keys
            or ([payload.source_property] if payload.source_property else [])
            or [source["primary_property"]]
        )
        target_keys = list(
            payload.target_property_keys
            or ([payload.target_property] if payload.target_property else [])
            or [target["primary_property"]]
        )
        if len(source_keys) != len(target_keys):
            raise ValueError("关系两端的复合属性键数量必须一致")
        source_properties = {item["property_key"] for item in source["properties"]}
        target_properties = {item["property_key"] for item in target["properties"]}
        missing_source = [key for key in source_keys if key not in source_properties]
        missing_target = [key for key in target_keys if key not in target_properties]
        if missing_source:
            raise ValueError("关系起点属性不存在: " + "、".join(missing_source))
        if missing_target:
            raise ValueError("关系终点属性不存在: " + "、".join(missing_target))
        db = get_management_db()
        duplicate = await db.execute_query(
            "SELECT id FROM ontology_link_type WHERE domain_id = :domain_id "
            "AND link_key = :link_key AND (:id IS NULL OR id <> :id)",
            {
                "domain_id": payload.domain_id,
                "link_key": payload.link_key,
                "id": payload.id,
            },
        )
        if duplicate:
            raise ValueError(f"关系标识已存在: {payload.link_key}")
        params = {
            **payload.model_dump(exclude={"id", "source_property_keys", "target_property_keys"}),
            "source_property": _encode_relation_property_keys(source_keys, "起点"),
            "target_property": _encode_relation_property_keys(target_keys, "终点"),
        }
        if payload.id:
            existing = await db.execute_query(
                "SELECT id FROM ontology_link_type WHERE id = :id AND domain_id = :domain_id",
                {"id": payload.id, "domain_id": payload.domain_id},
            )
            if not existing:
                raise ValueError("关系类型不存在")
            await db.execute_query(
                "UPDATE ontology_link_type SET link_key = :link_key, name = :name, "
                "source_object_key = :source_object_key, target_object_key = :target_object_key, "
                "source_property = :source_property, target_property = :target_property, "
                "cardinality = :cardinality, description = :description, status = :status "
                "WHERE id = :id",
                {**params, "id": payload.id},
            )
            return payload.id
        return await db.execute_insert(
            "INSERT INTO ontology_link_type "
            "(domain_id, link_key, name, source_object_key, target_object_key, source_property, "
            "target_property, cardinality, description, status) VALUES "
            "(:domain_id, :link_key, :name, :source_object_key, :target_object_key, "
            ":source_property, :target_property, :cardinality, :description, :status)",
            params,
        )

    async def delete_link_type(self, domain_id: int, link_type_id: int) -> bool:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT id FROM ontology_link_type WHERE id = :id AND domain_id = :domain_id",
            {"id": link_type_id, "domain_id": domain_id},
        )
        if not rows:
            return False
        await db.execute_transaction(
            [
                ("DELETE FROM ontology_link WHERE link_type_id = :id", {"id": link_type_id}),
                ("DELETE FROM ontology_link_type WHERE id = :id", {"id": link_type_id}),
            ]
        )
        return True

    async def list_action_types(self, domain_id: int) -> list[dict[str, Any]]:
        await self._require_domain(domain_id)
        rows = await get_management_db().execute_query(
            "SELECT * FROM ontology_action_type WHERE domain_id = :domain_id ORDER BY id ASC",
            {"domain_id": domain_id},
        )
        return [_normalize_row(row) for row in rows]

    async def _load_runtime_definition(
        self, domain_id: int, *, allow_compatibility_fallback: bool = True
    ) -> tuple[
        dict[str, Any] | None,
        dict[str, Any] | None,
        dict[str, Any] | None,
        dict[str, Any] | None,
        list[dict[str, Any]],
    ]:
        """Load the active unified model's immutable Ontology definition.

        Domains created before unified releases remain usable through an
        explicit compatibility fallback to live definitions and the latest
        Ontology release.  An active unified release is authoritative: a
        missing or malformed linked Ontology release is treated as an error
        instead of silently mixing versions.
        """
        model_release = await get_model_release_service().get_active_release(domain_id)
        if model_release is None:
            if not allow_compatibility_fallback:
                raise ValueError("当前业务领域尚未激活统一企业模型版本")
            warning = {
                "code": "enterprise_model_release_fallback",
                "message": (
                    "当前领域没有激活的企业模型版本，运行时回退到实时定义和最新 Ontology 发布。"
                ),
                "details": {"domain_id": domain_id},
            }
            logger.warning(
                "enterprise model runtime fallback domain_id=%s reason=no_active_release",
                domain_id,
            )
            release_rows = await get_management_db().execute_query(
                "SELECT id, version, name, description, definition_hash, created_at "
                "FROM ontology_release WHERE domain_id = :domain_id "
                "ORDER BY version DESC LIMIT 1",
                {"domain_id": domain_id},
            )
            ontology_release = _normalize_row(release_rows[0]) if release_rows else None
            return None, None, ontology_release, None, [warning]

        release_rows = await get_management_db().execute_query(
            "SELECT id, domain_id, version, name, description, definition_json, "
            "definition_hash, created_at FROM ontology_release "
            "WHERE id = :release_id AND domain_id = :domain_id",
            {
                "release_id": int(model_release["ontology_release_id"]),
                "domain_id": domain_id,
            },
        )
        if not release_rows:
            raise ValueError("激活企业模型版本关联的 Ontology 发布不存在")
        release_row = _normalize_row(release_rows[0])
        definition = release_row.pop("definition_json", None)
        if not isinstance(definition, dict):
            raise ValueError("激活企业模型版本关联的 Ontology 发布定义无效")
        actual_definition_hash = _content_hash(definition)
        release_definition_hash = str(release_row.get("definition_hash") or "")
        model_definition_hash = str(model_release.get("ontology_definition_hash") or "")
        if (
            not release_definition_hash
            or release_definition_hash != actual_definition_hash
            or model_definition_hash != actual_definition_hash
        ):
            raise ValueError("激活企业模型版本关联的 Ontology 发布定义完整性校验失败")
        expected_model_hash = _content_hash(
            {
                "format": "wenqu-enterprise-model-release/v1",
                "semantic_snapshot_hash": str(model_release.get("semantic_snapshot_hash") or ""),
                "ontology_definition_hash": actual_definition_hash,
            }
        )
        if str(model_release.get("model_hash") or "") != expected_model_hash:
            raise ValueError("激活企业模型版本内容哈希校验失败")
        ontology_release = {
            key: release_row.get(key)
            for key in (
                "id",
                "version",
                "name",
                "description",
                "definition_hash",
                "created_at",
            )
        }
        model_metadata = {
            key: model_release.get(key)
            for key in (
                "id",
                "version",
                "name",
                "status",
                "model_hash",
                "activated_at",
            )
        }
        semantic_snapshot = {
            "id": int(model_release["semantic_snapshot_id"]),
            "snapshot_hash": model_release.get("semantic_snapshot_hash"),
        }
        return model_metadata, semantic_snapshot, ontology_release, definition, []

    async def build_agent_context(
        self,
        domain_id: int,
        *,
        role: str = "user",
        require_active_release: bool = False,
    ) -> dict[str, Any]:
        """Build the bounded, runtime-facing Ontology context for an agent.

        Draft/deprecated definitions are deliberately omitted from the agent
        context.  Action visibility is additionally filtered by the caller's
        role; the execute path performs the same check again before writing.
        The payload contains definitions, not all object instances, so it is
        safe to pass as prompt/tool metadata and remains bounded as data grows.
        """
        domain = await self._require_domain(domain_id)
        (
            model_release,
            semantic_snapshot,
            ontology_release,
            definition,
            runtime_warnings,
        ) = await self._load_runtime_definition(
            domain_id,
            allow_compatibility_fallback=not require_active_release,
        )
        if definition is None:
            raw_object_types = await self.list_object_types(domain_id)
            raw_link_types = await self.list_link_types(domain_id)
            raw_action_types = await self.list_action_types(domain_id)
            released_domain: dict[str, Any] = {}
        else:
            raw_object_types = definition.get("object_types") or []
            raw_link_types = definition.get("link_types") or []
            raw_action_types = definition.get("action_types") or []
            released_domain = definition.get("domain") or {}
            if not all(
                isinstance(items, list)
                for items in (raw_object_types, raw_link_types, raw_action_types)
            ) or not isinstance(released_domain, dict):
                raise ValueError("激活企业模型版本关联的 Ontology 发布定义无效")

        object_types = [
            _normalize_row(item)
            for item in raw_object_types
            if isinstance(item, dict) and item.get("status") == "active"
        ]
        object_keys = {str(item.get("object_key")) for item in object_types}
        link_types = [
            _normalize_row(item)
            for item in raw_link_types
            if isinstance(item, dict)
            if item.get("status") == "active"
            and item.get("source_object_key") in object_keys
            and item.get("target_object_key") in object_keys
        ]
        action_types = [
            _normalize_row(item)
            for item in raw_action_types
            if isinstance(item, dict)
            if item.get("status") == "active"
            and item.get("target_object_key") in object_keys
            and ontology_action_role(role) in (item.get("allowed_roles") or [])
        ]

        # Keep only fields useful to query/action planning.  In particular,
        # object instances are fetched through the query tool on demand.
        compact_types = []
        for item in object_types:
            compact_types.append(
                {
                    "object_key": item.get("object_key"),
                    "name": item.get("name"),
                    "description": item.get("description") or "",
                    "primary_property": item.get("primary_property"),
                    "display_property": item.get("display_property"),
                    "properties": [
                        {
                            "property_key": prop.get("property_key"),
                            "name": prop.get("name"),
                            "data_type": prop.get("data_type"),
                            "required": bool(prop.get("required")),
                            "description": prop.get("description") or "",
                        }
                        for prop in item.get("properties", [])
                    ],
                }
            )
        compact_links = [
            {
                "link_key": item.get("link_key"),
                "name": item.get("name"),
                "source_object_key": item.get("source_object_key"),
                "target_object_key": item.get("target_object_key"),
                "source_property": item.get("source_property"),
                "target_property": item.get("target_property"),
                "source_property_keys": item.get("source_property_keys")
                or [item.get("source_property")],
                "target_property_keys": item.get("target_property_keys")
                or [item.get("target_property")],
                "cardinality": item.get("cardinality"),
                "description": item.get("description") or "",
            }
            for item in link_types
        ]
        compact_actions = [
            {
                "action_key": item.get("action_key"),
                "name": item.get("name"),
                "target_object_key": item.get("target_object_key"),
                "description": item.get("description") or "",
                "parameters": item.get("parameters") or [],
                "preconditions": item.get("preconditions") or [],
                "effects": item.get("effects") or [],
                "requires_approval": bool(item.get("requires_approval")),
            }
            for item in action_types
        ]
        return {
            "domain": {
                "id": int(domain["id"]),
                "domain_key": released_domain.get("domain_key") or domain.get("domain_key"),
                "name": released_domain.get("name") or domain.get("name"),
                "description": released_domain.get("description")
                or domain.get("description")
                or "",
            },
            "model_release": model_release,
            "semantic_snapshot": semantic_snapshot,
            "ontology_release": ontology_release,
            # Compatibility alias retained for existing query-context consumers.
            "release": ontology_release,
            "warnings": runtime_warnings,
            "role": role,
            "object_types": compact_types,
            "link_types": compact_links,
            "actions": compact_actions,
            "capabilities": {
                "query_objects": True,
                "execute_actions": bool(compact_actions),
            },
        }

    async def get_action_type(self, domain_id: int, action_type_id: int) -> dict[str, Any] | None:
        for item in await self.list_action_types(domain_id):
            if int(item["id"]) == action_type_id:
                return item
        return None

    async def get_action_type_by_key(
        self, domain_id: int, action_key: str
    ) -> dict[str, Any] | None:
        """Resolve a stable action key for application/agent tool calls."""
        normalized = str(action_key or "").strip()
        if not normalized:
            return None
        for item in await self.list_action_types(domain_id):
            if item.get("action_key") == normalized:
                return item
        return None

    async def upsert_action_type(self, payload: OntologyActionTypePayload) -> int:
        await self._require_domain(payload.domain_id)
        target = await self.get_object_type(payload.domain_id, object_key=payload.target_object_key)
        if not target:
            raise ValueError("动作目标必须引用已存在的对象类型")
        db = get_management_db()
        duplicate = await db.execute_query(
            "SELECT id FROM ontology_action_type WHERE domain_id = :domain_id "
            "AND action_key = :action_key AND (:id IS NULL OR id <> :id)",
            {
                "domain_id": payload.domain_id,
                "action_key": payload.action_key,
                "id": payload.id,
            },
        )
        if duplicate:
            raise ValueError(f"动作标识已存在: {payload.action_key}")
        data = payload.model_dump(exclude={"id"})
        params = {
            **data,
            "parameters": _json(data["parameters"]),
            "preconditions": _json(data["preconditions"]),
            "effects": _json(data["effects"]),
            "allowed_roles": _json(data["allowed_roles"]),
            "requires_approval": int(data["requires_approval"]),
        }
        if payload.id:
            existing = await db.execute_query(
                "SELECT id FROM ontology_action_type WHERE id = :id AND domain_id = :domain_id",
                {"id": payload.id, "domain_id": payload.domain_id},
            )
            if not existing:
                raise ValueError("动作类型不存在")
            await db.execute_query(
                "UPDATE ontology_action_type SET action_key = :action_key, name = :name, "
                "target_object_key = :target_object_key, description = :description, "
                "parameters = :parameters, preconditions = :preconditions, effects = :effects, "
                "allowed_roles = :allowed_roles, requires_approval = :requires_approval, "
                "status = :status WHERE id = :id",
                {**params, "id": payload.id},
            )
            return payload.id
        return await db.execute_insert(
            "INSERT INTO ontology_action_type "
            "(domain_id, action_key, name, target_object_key, description, parameters, "
            "preconditions, effects, allowed_roles, requires_approval, status) VALUES "
            "(:domain_id, :action_key, :name, :target_object_key, :description, :parameters, "
            ":preconditions, :effects, :allowed_roles, :requires_approval, :status)",
            params,
        )

    async def delete_action_type(self, domain_id: int, action_type_id: int) -> bool:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT id FROM ontology_action_type WHERE id = :id AND domain_id = :domain_id",
            {"id": action_type_id, "domain_id": domain_id},
        )
        if not rows:
            return False
        await db.execute_query(
            "DELETE FROM ontology_action_type WHERE id = :id AND domain_id = :domain_id",
            {"id": action_type_id, "domain_id": domain_id},
        )
        return True

    async def validate_domain(self, domain_id: int) -> dict[str, Any]:
        await self._require_domain(domain_id)
        object_types = await self.list_object_types(domain_id)
        link_types = await self.list_link_types(domain_id)
        action_types = await self.list_action_types(domain_id)
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        objects = {item["object_key"]: item for item in object_types}

        if not object_types:
            errors.append({"asset": "domain", "message": "至少需要一个对象类型"})
        for item in object_types:
            raw_properties = item.get("properties")
            if not isinstance(raw_properties, list):
                errors.append({"asset": item["object_key"], "message": "对象属性配置无效"})
                raw_properties = []
            props = {
                prop["property_key"]
                for prop in raw_properties
                if isinstance(prop, dict) and prop.get("property_key")
            }
            if not props:
                errors.append({"asset": item["object_key"], "message": "对象至少需要一个属性"})
            if item.get("primary_property") not in props:
                errors.append({"asset": item["object_key"], "message": "主属性不存在"})
            if item.get("display_property") and item["display_property"] not in props:
                errors.append({"asset": item["object_key"], "message": "显示属性不存在"})
            if item.get("sync_enabled"):
                source_query = str(item.get("source_query") or "").strip()
                if not source_query:
                    errors.append(
                        {
                            "asset": item["object_key"],
                            "message": "已启用同步但未配置只读 SELECT",
                        }
                    )
                else:
                    validation = normalize_sql_for_execution(
                        source_query, max_limit=int(item.get("sync_limit") or 200)
                    )
                    if not validation.ok:
                        errors.append(
                            {
                                "asset": item["object_key"],
                                "message": f"同步 SQL 无效: {validation.reason}",
                            }
                        )
            if not item.get("description"):
                warnings.append({"asset": item["object_key"], "message": "建议补充业务定义"})

        for item in link_types:
            source = objects.get(item["source_object_key"])
            target = objects.get(item["target_object_key"])
            if not source or not target:
                errors.append({"asset": item["link_key"], "message": "关系引用了不存在的对象"})
                continue
            source_properties = source.get("properties") or []
            target_properties = target.get("properties") or []
            try:
                source_keys = _relation_property_keys(item, "source")
                target_keys = _relation_property_keys(item, "target")
            except ValueError as exc:
                errors.append({"asset": item["link_key"], "message": str(exc)})
                continue
            if len(source_keys) != len(target_keys):
                errors.append(
                    {
                        "asset": item["link_key"],
                        "message": "关系两端的复合属性键数量必须一致",
                    }
                )
                continue
            source_property_keys = {
                p["property_key"] for p in source_properties if isinstance(p, dict)
            }
            target_property_keys = {
                p["property_key"] for p in target_properties if isinstance(p, dict)
            }
            missing_source = [key for key in source_keys if key not in source_property_keys]
            missing_target = [key for key in target_keys if key not in target_property_keys]
            if missing_source:
                errors.append(
                    {
                        "asset": item["link_key"],
                        "message": "关系起点属性不存在: " + "、".join(missing_source),
                    }
                )
            if missing_target:
                errors.append(
                    {
                        "asset": item["link_key"],
                        "message": "关系终点属性不存在: " + "、".join(missing_target),
                    }
                )

        for item in action_types:
            target = objects.get(item["target_object_key"])
            if not target:
                errors.append({"asset": item["action_key"], "message": "动作目标对象不存在"})
                continue
            raw_target_properties = target.get("properties")
            if not isinstance(raw_target_properties, list):
                errors.append({"asset": item["action_key"], "message": "动作目标属性配置无效"})
                raw_target_properties = []
            props = {
                prop["property_key"]
                for prop in raw_target_properties
                if isinstance(prop, dict) and prop.get("property_key")
            }
            primary_property = target.get("primary_property")
            raw_parameters = item.get("parameters")
            raw_preconditions = item.get("preconditions")
            raw_effects = item.get("effects")
            if not isinstance(raw_parameters, list):
                errors.append({"asset": item["action_key"], "message": "动作参数配置无效"})
                raw_parameters = []
            if not isinstance(raw_preconditions, list):
                errors.append({"asset": item["action_key"], "message": "动作前置条件配置无效"})
                raw_preconditions = []
            if not isinstance(raw_effects, list):
                errors.append({"asset": item["action_key"], "message": "动作效果配置无效"})
                raw_effects = []
            parameters = {
                param["parameter_key"]
                for param in raw_parameters
                if isinstance(param, dict) and param.get("parameter_key")
            }
            if len(parameters) != len(raw_parameters):
                errors.append({"asset": item["action_key"], "message": "动作参数标识不能重复"})
            if not raw_effects:
                errors.append({"asset": item["action_key"], "message": "动作至少需要一个状态效果"})
            for condition in raw_preconditions:
                if not isinstance(condition, dict):
                    errors.append({"asset": item["action_key"], "message": "动作前置条件配置无效"})
                    continue
                if condition.get("property") not in props:
                    errors.append(
                        {"asset": item["action_key"], "message": "动作前置条件属性不存在"}
                    )
            for effect in raw_effects:
                if not isinstance(effect, dict):
                    errors.append({"asset": item["action_key"], "message": "动作效果配置无效"})
                    continue
                if effect.get("property") not in props:
                    errors.append({"asset": item["action_key"], "message": "动作效果属性不存在"})
                if primary_property and effect.get("property") == primary_property:
                    errors.append(
                        {"asset": item["action_key"], "message": "动作不能修改对象主标识"}
                    )
                value = effect.get("value")
                if isinstance(value, str) and value.startswith("$param."):
                    if value.removeprefix("$param.") not in parameters:
                        errors.append(
                            {
                                "asset": item["action_key"],
                                "message": f"动作效果引用未知参数 {value}",
                            }
                        )

        if not link_types:
            warnings.append({"asset": "domain", "message": "当前领域没有定义对象关系"})
        if not action_types:
            warnings.append({"asset": "domain", "message": "当前领域还不能执行任何业务动作"})
        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "counts": {
                "object_types": len(object_types),
                "link_types": len(link_types),
                "action_types": len(action_types),
            },
        }

    async def publish_domain(
        self, domain_id: int, published_by: int, name: str | None = None, description: str = ""
    ) -> dict[str, Any]:
        validation = await self.validate_domain(domain_id)
        if not validation["valid"]:
            return {"published": False, "validation": validation}
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT COALESCE(MAX(version), 0) AS version FROM ontology_release "
            "WHERE domain_id = :domain_id",
            {"domain_id": domain_id},
        )
        version = int(rows[0]["version"] if rows else 0) + 1
        definition = _stable_release_definition(
            await self.export_bundle(domain_id, include_instances=False)
        )
        definition_hash = _content_hash(definition)
        release_id = await db.execute_insert(
            "INSERT INTO ontology_release "
            "(domain_id, version, name, description, validation_json, "
            "definition_json, definition_hash, published_by) "
            "VALUES (:domain_id, :version, :name, :description, :validation_json, "
            ":definition_json, :definition_hash, :published_by)",
            {
                "domain_id": domain_id,
                "version": version,
                "name": name or f"V{version}",
                "description": description,
                "validation_json": _json(validation),
                "definition_json": _json(definition),
                "definition_hash": definition_hash,
                "published_by": published_by,
            },
        )
        return {
            "published": True,
            "id": release_id,
            "version": version,
            "definition_hash": definition_hash,
            "validation": validation,
        }

    async def list_releases(self, domain_id: int) -> list[dict[str, Any]]:
        await self._require_domain(domain_id)
        rows = await get_management_db().execute_query(
            "SELECT id, domain_id, version, name, description, validation_json, "
            "definition_hash, published_by, created_at FROM ontology_release "
            "WHERE domain_id = :domain_id "
            "ORDER BY version DESC",
            {"domain_id": domain_id},
        )
        return [_normalize_row(row) for row in rows]

    async def _load_object_permission_context(
        self,
        domain: dict[str, Any],
        access_agent_id: int | None,
    ) -> (
        PermissionRuntimeContext
        | tuple[int, dict[str, bool], dict[tuple[str, str], ColumnPolicy]]
        | None
    ):
        datasource_id = int(domain.get("datasource_id") or 0)
        if not datasource_id:
            return None
        permission_service = get_permission_service()
        resolver = getattr(permission_service, "resolve_domain_permission_context", None)
        if callable(resolver):
            context = await resolver(
                int(domain.get("id") or 0),
                datasource_id,
                compatibility_agent_id=access_agent_id,
                allow_agent_fallback=bool(access_agent_id),
            )
            # Empty domain rules still allow platform-created objects. The
            # existing source_kind filter hides every database-backed object;
            # synchronization and SQL execution remain default-deny.
            if context.source == "agent_compatibility" and (
                not access_agent_id
                or not await get_datasource_service().belongs_to_agent(
                    datasource_id, access_agent_id
                )
            ):
                raise PermissionError("兼容权限智能体无权访问领域数据源")
            return context
        if not access_agent_id:
            raise PermissionError("对象数据访问缺少明确的权限主体")
        if not await get_datasource_service().belongs_to_agent(datasource_id, access_agent_id):
            raise PermissionError("当前权限主体无权访问领域数据源")
        return (
            datasource_id,
            await permission_service.get_table_permissions(access_agent_id, datasource_id),
            await permission_service.get_column_permissions(access_agent_id, datasource_id),
        )

    @staticmethod
    def _column_policy_for_sources(
        property_key: str,
        source_tables: list[str],
        column_permissions: dict[tuple[str, str], ColumnPolicy],
        result_column_policies: dict[str, ColumnPolicy] | None = None,
    ) -> ColumnPolicy | None:
        output_policy = (result_column_policies or {}).get(property_key.lower())
        if output_policy is not None:
            return output_policy
        policies = [
            column_permissions.get((table.lower(), property_key.lower())) for table in source_tables
        ]
        matched = [policy for policy in policies if policy is not None]
        if not matched:
            return None
        if any(not policy.allowed for policy in matched):
            return ColumnPolicy(allowed=False, masking_policy="redact")
        return max(
            matched,
            key=lambda policy: _MASKING_PRIORITY.get(policy.masking_policy, 3),
        )

    @staticmethod
    def _permission_metadata(row: dict[str, Any], object_type: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "_permission_source_query": object_type.get("source_query"),
            "_permission_primary_property": object_type.get("primary_property"),
            "_permission_display_property": object_type.get("display_property"),
        }

    @staticmethod
    def _permission_context_metadata(
        permission_context: PermissionRuntimeContext
        | tuple[int, dict[str, bool], dict[tuple[str, str], ColumnPolicy]]
        | None,
    ) -> dict[str, Any] | None:
        if isinstance(permission_context, PermissionRuntimeContext):
            return permission_context.metadata()
        return None

    @classmethod
    def _validate_sync_key_permissions(
        cls,
        object_type: dict[str, Any],
        link_types: list[dict[str, Any]],
        source_tables: list[str],
        column_permissions: dict[tuple[str, str], ColumnPolicy],
        result_column_policies: dict[str, ColumnPolicy] | None = None,
    ) -> None:
        primary_property = str(object_type.get("primary_property") or "")
        relation_properties: set[str] = set()
        for link_type in link_types:
            if link_type.get("status") != "active":
                continue
            if link_type.get("source_object_key") == object_type.get("object_key"):
                relation_properties.update(_relation_property_keys(link_type, "source"))
            if link_type.get("target_object_key") == object_type.get("object_key"):
                relation_properties.update(_relation_property_keys(link_type, "target"))
        for property_key, label in [
            (primary_property, "主标识"),
            *((property_key, "关系键") for property_key in sorted(relation_properties)),
        ]:
            if not property_key:
                continue
            policy = cls._column_policy_for_sources(
                property_key,
                source_tables,
                column_permissions,
                result_column_policies,
            )
            if policy is not None and (not policy.allowed or policy.masking_policy != "none"):
                raise ValueError(f"{label}字段 {property_key} 不得拒绝访问或脱敏")

    @classmethod
    def _protect_object_rows(
        cls,
        rows: list[dict[str, Any]],
        permission_context: tuple[
            int,
            dict[str, bool],
            dict[tuple[str, str], ColumnPolicy],
        ]
        | None,
    ) -> list[dict[str, Any]]:
        protected_rows: list[dict[str, Any]] = []
        for raw_row in rows:
            row = _normalize_row(raw_row)
            source_query = str(row.pop("_permission_source_query", "") or "")
            primary_property = str(row.pop("_permission_primary_property", "") or "")
            display_property = str(row.pop("_permission_display_property", "") or "")
            for field in _OBJECT_PERMISSION_FIELDS:
                row.pop(field, None)
            if permission_context is None:
                protected_rows.append(row)
                continue

            datasource_id, table_permissions, column_permissions = permission_context
            source_datasource_id = int(row.get("source_datasource_id") or 0)
            database_backed = (
                str(row.get("source_kind") or "").lower() == "database" or source_datasource_id > 0
            )
            if not database_backed:
                protected_rows.append(row)
                continue
            if source_datasource_id and source_datasource_id != datasource_id:
                continue

            source_tables = extract_table_references(source_query)
            if source_tables and any(
                not get_permission_service().table_allowed(table, table_permissions)
                for table in source_tables
            ):
                continue
            if not source_tables:
                continue
            try:
                result_column_policies = PermissionService.resolve_result_column_policies(
                    source_query,
                    source_tables,
                    column_permissions,
                )
            except ValueError:
                continue

            primary_policy = cls._column_policy_for_sources(
                primary_property,
                source_tables,
                column_permissions,
                result_column_policies,
            )
            if primary_policy is not None and (
                not primary_policy.allowed or primary_policy.masking_policy != "none"
            ):
                continue

            for field in ("properties", "source_properties", "overlay_properties"):
                values = row.get(field)
                if not isinstance(values, dict):
                    continue
                visible: dict[str, Any] = {}
                for key, value in values.items():
                    policy = cls._column_policy_for_sources(
                        str(key),
                        source_tables,
                        column_permissions,
                        result_column_policies,
                    )
                    if policy is not None and not policy.allowed:
                        continue
                    visible[key] = (
                        mask_value(value, policy.masking_policy)
                        if policy is not None and policy.masking_policy != "none"
                        else value
                    )
                row[field] = visible

            response_fields = {
                "primary_value": primary_property,
                "display_name": display_property or primary_property,
            }
            for response_field, property_key in response_fields.items():
                if not property_key:
                    continue
                policy = cls._column_policy_for_sources(
                    property_key,
                    source_tables,
                    column_permissions,
                    result_column_policies,
                )
                if policy is None:
                    continue
                row[response_field] = (
                    "***"
                    if not policy.allowed
                    else mask_value(row.get(response_field), policy.masking_policy)
                    if policy.masking_policy != "none"
                    else row.get(response_field)
                )
            protected_rows.append(row)
        return protected_rows

    @staticmethod
    async def _allowed_database_object_type_ids(
        domain_id: int,
        table_permissions: dict[str, bool],
        column_permissions: dict[tuple[str, str], ColumnPolicy],
    ) -> list[int] | None:
        rows = await get_management_db().execute_query(
            "SELECT id, source_query, primary_property FROM ontology_object_type "
            "WHERE domain_id = :domain_id",
            {"domain_id": domain_id},
        )
        allowed_ids: list[int] = []
        for row in rows:
            source_tables = extract_table_references(str(row.get("source_query") or ""))
            if not source_tables or any(
                not get_permission_service().table_allowed(table, table_permissions)
                for table in source_tables
            ):
                continue
            primary_policy = OntologyService._column_policy_for_sources(
                str(row.get("primary_property") or ""),
                source_tables,
                column_permissions,
            )
            if primary_policy is not None and (
                not primary_policy.allowed or primary_policy.masking_policy != "none"
            ):
                continue
            allowed_ids.append(int(row["id"]))
        return allowed_ids

    @staticmethod
    async def _allowed_database_object_type_ids_from_definitions(
        domain_id: int,
        object_types: list[dict[str, Any]],
        table_permissions: dict[str, bool],
        column_permissions: dict[tuple[str, str], ColumnPolicy],
    ) -> list[int] | None:
        object_keys = [
            str(item.get("object_key") or "").strip()
            for item in object_types
            if str(item.get("object_key") or "").strip()
        ]
        if not object_keys:
            return []
        placeholders = []
        params: dict[str, Any] = {"domain_id": domain_id}
        for index, object_key in enumerate(sorted(set(object_keys))):
            key = f"object_key_{index}"
            placeholders.append(f":{key}")
            params[key] = object_key
        rows = await get_management_db().execute_query(
            "SELECT id, object_key FROM ontology_object_type "
            "WHERE domain_id = :domain_id "
            f"AND object_key IN ({', '.join(placeholders)})",
            params,
        )
        ids_by_key = {str(row.get("object_key")): int(row["id"]) for row in rows}
        allowed_ids: list[int] = []
        for object_type in object_types:
            object_key = str(object_type.get("object_key") or "").strip()
            object_type_id = ids_by_key.get(object_key)
            if object_type_id is None:
                continue
            source_tables = extract_table_references(
                str(object_type.get("source_query") or "")
            )
            if not source_tables or any(
                not get_permission_service().table_allowed(table, table_permissions)
                for table in source_tables
            ):
                continue
            primary_policy = OntologyService._column_policy_for_sources(
                str(object_type.get("primary_property") or ""),
                source_tables,
                column_permissions,
            )
            if primary_policy is not None and (
                not primary_policy.allowed or primary_policy.masking_policy != "none"
            ):
                continue
            allowed_ids.append(object_type_id)
        return allowed_ids

    @staticmethod
    def _append_object_type_access_filter(
        where: list[str],
        params: dict[str, Any],
        allowed_type_ids: list[int] | None,
    ) -> None:
        if allowed_type_ids is None:
            return
        manual_clause = "o.source_kind IS NULL OR o.source_kind <> 'database'"
        if not allowed_type_ids:
            where.append(f"({manual_clause})")
            return
        placeholders = []
        for index, object_type_id in enumerate(allowed_type_ids):
            key = f"allowed_type_{index}"
            placeholders.append(f":{key}")
            params[key] = object_type_id
        where.append(f"({manual_clause} OR o.object_type_id IN ({', '.join(placeholders)}))")

    async def list_objects(
        self,
        domain_id: int,
        object_type_id: int | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        access_agent_id: int | None = None,
        apply_permissions: bool = True,
        release_definition: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        domain = await self._require_domain(domain_id)
        permission_context = (
            await self._load_object_permission_context(domain, access_agent_id)
            if apply_permissions
            else None
        )
        sql = (
            "SELECT o.*, t.object_key AS object_type_key, t.name AS object_type_name, "
            "t.source_query AS _permission_source_query, "
            "t.primary_property AS _permission_primary_property, "
            "t.display_property AS _permission_display_property "
            "FROM ontology_object o JOIN ontology_object_type t ON t.id = o.object_type_id "
            "WHERE "
        )
        params: dict[str, Any] = {"domain_id": domain_id}
        where = ["o.domain_id = :domain_id"]
        released_by_id: dict[int, dict[str, Any]] = {}
        if release_definition is not None:
            released_types = release_definition.get("object_types") or []
            released_by_id = {
                int(item["id"]): item
                for item in released_types
                if isinstance(item, dict) and item.get("id") is not None
            }
            if not released_by_id:
                return []
            placeholders = []
            for index, released_id in enumerate(sorted(released_by_id)):
                key = f"released_object_type_{index}"
                placeholders.append(f":{key}")
                params[key] = released_id
            where.append(f"o.object_type_id IN ({', '.join(placeholders)})")
        if object_type_id is not None:
            where.append("o.object_type_id = :object_type_id")
            params["object_type_id"] = object_type_id
        if permission_context is None:
            allowed_type_ids = None
        elif release_definition is None:
            allowed_type_ids = await self._allowed_database_object_type_ids(
                domain_id,
                permission_context[1],
                permission_context[2],
            )
        else:
            # Runtime reads are release-scoped.  Permission discovery must use
            # the frozen release mappings too; consulting the live object-type
            # rows here would let an un-published draft SQL change visibility.
            allowed_type_ids = await self._allowed_database_object_type_ids_from_definitions(
                domain_id,
                release_definition.get("object_types") or [],
                permission_context[1],
                permission_context[2],
            )
        self._append_object_type_access_filter(where, params, allowed_type_ids)
        sql += " AND ".join(where)
        sql += " ORDER BY o.updated_at DESC, o.id DESC"
        if limit is not None:
            sql += " LIMIT :limit OFFSET :offset"
            params["limit"] = min(max(int(limit), 1), 1000)
            params["offset"] = max(int(offset), 0)
        rows = await get_management_db().execute_query(sql, params)
        if released_by_id:
            scoped_rows = []
            for raw_row in rows:
                row = _normalize_row(raw_row)
                released = released_by_id.get(int(row.get("object_type_id") or 0))
                if released is None:
                    continue
                row["object_type_key"] = released.get("object_key")
                row["object_type_name"] = released.get("name") or row.get(
                    "object_type_name"
                )
                row["_permission_source_query"] = released.get("source_query")
                row["_permission_primary_property"] = released.get("primary_property")
                row["_permission_display_property"] = released.get("display_property")
                scoped_rows.append(row)
            rows = scoped_rows
        return self._protect_object_rows(rows, permission_context)

    async def sync_objects_from_datasource(
        self,
        domain_id: int,
        *,
        access_agent_id: int | None = None,
        object_type_id: int | None = None,
        page: int = 1,
        page_size: int | None = None,
        sync_links: bool = True,
        release_definition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Synchronize one source page while preserving local action overlays.

        When ``release_definition`` is supplied, all mapping and behavior
        fields come from that immutable active release.  Live rows are used
        only to resolve storage IDs, so editing the draft cannot change an
        in-flight or subsequent release-scoped sync.
        """
        domain = await self._require_domain(domain_id)
        datasource_id = int(domain.get("datasource_id") or 0)
        if not datasource_id:
            raise ValueError("当前领域没有绑定默认数据源，无法同步对象实例")
        permission_context = await self._load_object_permission_context(domain, access_agent_id)
        if permission_context is None:
            raise PermissionError("对象同步缺少明确的权限主体")
        if (
            isinstance(permission_context, PermissionRuntimeContext)
            and permission_context.source == "unconfigured"
        ):
            raise PermissionError("当前业务领域未配置数据权限")
        if release_definition is None:
            object_types = await self.list_object_types(domain_id)
            link_types = await self.list_link_types(domain_id)
            action_types = await self.list_action_types(domain_id)
        else:
            scoped_definition = await self.prepare_release_sync_definition(
                domain_id,
                release_definition,
            )
            object_types = scoped_definition["object_types"]
            link_types = scoped_definition["link_types"]
            action_types = scoped_definition["action_types"]
        if object_type_id is not None:
            object_types = [item for item in object_types if int(item["id"]) == object_type_id]
            if not object_types:
                raise ValueError("对象类型不存在或不属于当前领域")
        sync_types = [item for item in object_types if item.get("sync_enabled")]
        if not sync_types:
            raise ValueError("当前对象类型没有启用业务库同步")

        source_db = await get_datasource_db(datasource_id)
        permission_service = get_permission_service()
        page_number = max(int(page), 1)
        results: list[dict[str, Any]] = []
        raw_synced_objects: list[dict[str, Any]] = []
        total_rows = 0

        for object_type in sync_types:
            configured_limit = min(max(int(object_type.get("sync_limit") or 200), 1), 1000)
            effective_page_size = min(max(int(page_size or configured_limit), 1), 1000)
            source_query = str(object_type.get("source_query") or "").strip().rstrip(";")
            result: dict[str, Any] = {
                "object_type_id": int(object_type["id"]),
                "object_key": object_type["object_key"],
                "name": object_type["name"],
                "page": page_number,
                "page_size": effective_page_size,
                "total": 0,
                "read": 0,
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "skipped": 0,
                "errors": [],
                "objects": [],
            }
            try:
                base_query = self._validated_source_query(source_query)
                if isinstance(permission_context, PermissionRuntimeContext):
                    allowed, reason = PermissionService.validate_sql_access_with_context(
                        permission_context, base_query
                    )
                else:
                    allowed, reason = await permission_service.validate_sql_access(
                        access_agent_id, datasource_id, base_query
                    )
                if not allowed:
                    raise ValueError(reason)
                source_tables = extract_table_references(base_query)
                result_column_policies = PermissionService.resolve_result_column_policies(
                    base_query,
                    source_tables,
                    permission_context[2],
                )
                self._validate_sync_key_permissions(
                    object_type,
                    link_types,
                    source_tables,
                    permission_context[2],
                    result_column_policies,
                )
                count_rows = await source_db.execute_query(
                    f"SELECT COUNT(*) AS count FROM ({base_query}) AS ontology_source"
                )
                total = int(count_rows[0].get("count") or 0) if count_rows else 0
                offset = (page_number - 1) * effective_page_size
                rows = await source_db.execute_query(
                    f"{base_query}\nLIMIT :sync_limit OFFSET :sync_offset",
                    {"sync_limit": effective_page_size, "sync_offset": offset},
                )
                effect_keys = {
                    str(effect.get("property"))
                    for action in action_types
                    if action.get("target_object_key") == object_type["object_key"]
                    for effect in (action.get("effects") or [])
                    if isinstance(effect, dict) and effect.get("property")
                }
                for row_index, row in enumerate(rows, start=offset + 1):
                    try:
                        synced, outcome = await self._upsert_synced_object(
                            domain_id,
                            datasource_id,
                            object_type,
                            row,
                            effect_keys,
                        )
                        result[outcome] += 1
                        protected = self._protect_object_rows(
                            [self._permission_metadata(synced, object_type)],
                            permission_context,
                        )
                        result["objects"].extend(protected)
                        raw_synced_objects.append(synced)
                    except (TypeError, ValueError) as exc:
                        result["skipped"] += 1
                        result["errors"].append(f"第 {row_index} 行: {exc}")
                result["total"] = total
                result["read"] = len(rows)
                total_rows += total
                await self._record_sync_status(
                    int(object_type["id"]),
                    "succeeded" if not result["errors"] else "partial",
                    len(rows),
                    total,
                    "；".join(result["errors"][:5]),
                )
            except Exception as exc:
                result["errors"].append(str(exc))
                await self._record_sync_status(int(object_type["id"]), "failed", 0, 0, str(exc))
            results.append(result)

        link_count = 0
        relationship_errors: list[str] = []
        if sync_links and raw_synced_objects:
            try:
                link_count = await self._sync_links_for_objects(
                    domain_id, raw_synced_objects, link_types=link_types
                )
            except Exception as exc:
                logger.exception("ontology relationship sync failed domain_id=%s", domain_id)
                relationship_errors.append(str(exc))
        return {
            "domain_id": domain_id,
            "datasource_id": datasource_id,
            "permission": self._permission_context_metadata(permission_context),
            "page": page_number,
            "types": results,
            "objects": [item for result in results for item in result["objects"]],
            "total": total_rows,
            "links_synced": link_count,
            "relationship_errors": relationship_errors,
            "has_errors": any(result["errors"] for result in results) or bool(relationship_errors),
        }

    def _validated_source_query(self, source_query: str) -> str:
        if not source_query:
            raise ValueError("对象类型未配置同步 SQL")
        validation = normalize_sql_for_execution(source_query, max_limit=1000)
        if not validation.ok:
            raise ValueError(f"对象同步 SQL 无效: {validation.reason}")
        tokens = tokenize_sql(validation.sql)
        if find_top_level_keyword(tokens, "ORDER") is None:
            raise ValueError("对象同步 SQL 必须包含稳定的 ORDER BY，保证分页结果一致")
        limit_index = find_top_level_keyword(tokens, "LIMIT")
        if limit_index is None:
            return validation.sql.rstrip()
        return validation.sql[: tokens[limit_index].start].rstrip()

    async def _upsert_synced_object(
        self,
        domain_id: int,
        datasource_id: int,
        object_type: dict[str, Any],
        row: dict[str, Any],
        effect_keys: set[str],
    ) -> tuple[dict[str, Any], str]:
        definitions = object_type.get("properties") or []
        source_values = validate_synced_property_values(definitions, row)
        primary_key = str(object_type["primary_property"])
        primary_definition = property_definition(definitions, primary_key)
        primary_value = coerce_primary_value(primary_definition, source_values.get(primary_key))
        source_values[primary_key] = primary_value
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM ontology_object WHERE domain_id = :domain_id "
            "AND object_type_id = :object_type_id AND primary_value = :primary_value",
            {
                "domain_id": domain_id,
                "object_type_id": int(object_type["id"]),
                "primary_value": str(primary_value),
            },
        )
        existing = _normalize_row(rows[0]) if rows else None
        overlay: dict[str, Any] = {}
        if existing:
            if existing.get("source_kind") == "database":
                overlay = dict(existing.get("overlay_properties") or {})
            elif effect_keys:
                audit_rows = await db.execute_query(
                    "SELECT after_state FROM ontology_action_run WHERE domain_id = :domain_id "
                    "AND target_object_id = :target_object_id AND status = 'succeeded' "
                    "ORDER BY id DESC LIMIT 1",
                    {"domain_id": domain_id, "target_object_id": int(existing["id"])},
                )
                if audit_rows:
                    after_state = _loads(audit_rows[0].get("after_state"), {})
                    audit_properties = after_state.get("properties") or {}
                    overlay = {
                        key: audit_properties[key] for key in effect_keys if key in audit_properties
                    }
        overlay = {key: value for key, value in overlay.items() if source_values.get(key) != value}
        merged = validate_property_values(definitions, {**source_values, **overlay})
        merged[primary_key] = primary_value
        display_key = object_type.get("display_property")
        display_name = (
            str(merged.get(display_key))
            if display_key and merged.get(display_key) is not None
            else str(primary_value)
        )
        source_json = _json(source_values)
        overlay_json = _json(overlay)
        merged_json = _json(merged)
        if existing:
            content_changed = (
                existing.get("properties") != merged
                or existing.get("display_name") != display_name
                or existing.get("status") != "active"
            )
            await db.execute_query(
                "UPDATE ontology_object SET display_name = :display_name, "
                "properties = :properties, source_properties = :source_properties, "
                "overlay_properties = :overlay_properties, "
                "source_kind = 'database', source_datasource_id = :datasource_id, "
                "last_synced_at = CURRENT_TIMESTAMP, status = 'active', "
                "version = version + :version_increment, "
                "updated_at = IF(:version_increment = 1, CURRENT_TIMESTAMP, updated_at) "
                "WHERE id = :id AND domain_id = :domain_id",
                {
                    "id": int(existing["id"]),
                    "domain_id": domain_id,
                    "display_name": display_name,
                    "properties": merged_json,
                    "source_properties": source_json,
                    "overlay_properties": overlay_json,
                    "datasource_id": datasource_id,
                    "version_increment": int(content_changed),
                },
            )
            version = int(existing.get("version") or 1) + int(content_changed)
            object_id = int(existing["id"])
            outcome = "updated" if content_changed else "unchanged"
        else:
            object_id = await db.execute_insert(
                "INSERT INTO ontology_object "
                "(domain_id, object_type_id, primary_value, display_name, properties, version, "
                "status, source_kind, source_datasource_id, source_properties, overlay_properties, "
                "last_synced_at) VALUES "
                "(:domain_id, :object_type_id, :primary_value, :display_name, :properties, 1, "
                "'active', 'database', :datasource_id, :source_properties, :overlay_properties, "
                "CURRENT_TIMESTAMP)",
                {
                    "domain_id": domain_id,
                    "object_type_id": int(object_type["id"]),
                    "primary_value": str(primary_value),
                    "display_name": display_name,
                    "properties": merged_json,
                    "datasource_id": datasource_id,
                    "source_properties": source_json,
                    "overlay_properties": overlay_json,
                },
            )
            version = 1
            outcome = "created"
        return (
            {
                "id": object_id,
                "domain_id": domain_id,
                "object_type_id": int(object_type["id"]),
                "object_type_key": object_type["object_key"],
                "object_type_name": object_type["name"],
                "primary_value": str(primary_value),
                "display_name": display_name,
                "properties": merged,
                "source_properties": source_values,
                "overlay_properties": overlay,
                "source_kind": "database",
                "source_datasource_id": datasource_id,
                "version": version,
                "status": "active",
                "last_synced_at": datetime.now(timezone.utc).isoformat(),
            },
            outcome,
        )

    async def _record_sync_status(
        self, object_type_id: int, status: str, count: int, total: int, error: str = ""
    ) -> None:
        await get_management_db().execute_query(
            "UPDATE ontology_object_type SET last_sync_status = :status, "
            "last_sync_count = :count, last_sync_total = :total, last_sync_error = :error, "
            "last_synced_at = CURRENT_TIMESTAMP WHERE id = :id",
            {
                "id": object_type_id,
                "status": status,
                "count": count,
                "total": total,
                "error": error[:2000],
            },
        )

    async def _sync_links_for_objects(
        self,
        domain_id: int,
        synced_objects: list[dict[str, Any]],
        *,
        link_types: list[dict[str, Any]] | None = None,
    ) -> int:
        synced_ids = {int(item["id"]) for item in synced_objects}
        link_types = sorted(
            (
                item
                for item in (link_types or await self.list_link_types(domain_id))
                if item.get("status") == "active"
            ),
            key=lambda item: (int(item.get("id") or 0), str(item.get("link_key") or "")),
        )
        if not link_types:
            return 0
        synced_by_type: dict[str, list[dict[str, Any]]] = {}
        for item in synced_objects:
            synced_by_type.setdefault(str(item.get("object_type_key") or ""), []).append(item)
        statements: list[tuple[str, dict[str, Any]]] = []
        statement_keys: set[tuple[int, int, int]] = set()
        for link_type in link_types:
            source_properties = _relation_property_keys(link_type, "source")
            target_properties = _relation_property_keys(link_type, "target")
            if len(source_properties) != len(target_properties):
                raise ValueError("关系两端的复合属性键数量必须一致")
            source_property = source_properties[0]
            target_property = target_properties[0]
            source_type_key = str(link_type["source_object_key"])
            target_type_key = str(link_type["target_object_key"])
            source_objects = list(synced_by_type.get(source_type_key, []))
            target_objects = list(synced_by_type.get(target_type_key, []))
            if source_objects:
                source_values = {
                    relation_lookup_key((item.get("properties") or {})[source_property])
                    for item in source_objects
                    if relation_object_lookup_key(item.get("properties") or {}, source_properties)
                    is not None
                }
                target_objects.extend(
                    await self._load_objects_by_property_values(
                        domain_id, target_type_key, target_property, source_values
                    )
                )
            if target_objects:
                target_values = {
                    relation_lookup_key((item.get("properties") or {})[target_property])
                    for item in target_objects
                    if relation_object_lookup_key(item.get("properties") or {}, target_properties)
                    is not None
                }
                source_objects.extend(
                    await self._load_objects_by_property_values(
                        domain_id, source_type_key, source_property, target_values
                    )
                )
            targets: dict[str, list[dict[str, Any]]] = {}
            for target in unique_objects(target_objects):
                lookup_key = relation_object_lookup_key(
                    target.get("properties") or {}, target_properties
                )
                if lookup_key is not None:
                    targets.setdefault(lookup_key, []).append(target)
            for source in unique_objects(source_objects):
                lookup_key = relation_object_lookup_key(
                    source.get("properties") or {}, source_properties
                )
                if lookup_key is None:
                    continue
                for target in targets.get(lookup_key, []):
                    source_id = int(source["id"])
                    target_id = int(target["id"])
                    if source_id not in synced_ids and target_id not in synced_ids:
                        continue
                    statement_key = (int(link_type["id"]), source_id, target_id)
                    if statement_key in statement_keys:
                        continue
                    statement_keys.add(statement_key)
                    statements.append(
                        (
                            "INSERT INTO ontology_link "
                            "(domain_id, link_type_id, source_object_id, target_object_id, "
                            "properties) "
                            "VALUES (:domain_id, :link_type_id, :source_object_id, "
                            ":target_object_id, :properties) "
                            "ON DUPLICATE KEY UPDATE properties = VALUES(properties), "
                            "updated_at = CURRENT_TIMESTAMP",
                            {
                                "domain_id": domain_id,
                                "link_type_id": int(link_type["id"]),
                                "source_object_id": source_id,
                                "target_object_id": target_id,
                                "properties": _json({"source": "database_sync"}),
                            },
                        )
                    )
        if statements:
            await get_management_db().execute_transaction(statements)
        return len(statements)

    async def _load_objects_by_property_values(
        self,
        domain_id: int,
        object_type_key: str,
        property_key: str,
        values: set[str],
    ) -> list[dict[str, Any]]:
        if not values:
            return []
        rows: list[dict[str, Any]] = []
        ordered_values = sorted(values)
        for start in range(0, len(ordered_values), 300):
            chunk = ordered_values[start : start + 300]
            placeholders = ", ".join(f":value_{index}" for index in range(len(chunk)))
            params: dict[str, Any] = {
                "domain_id": domain_id,
                "object_type_key": object_type_key,
                "json_path": f'$."{property_key}"',
            }
            params.update({f"value_{index}": value for index, value in enumerate(chunk)})
            rows.extend(
                await get_management_db().execute_query(
                    "SELECT o.*, t.object_key AS object_type_key, "
                    "t.name AS object_type_name FROM ontology_object o "
                    "JOIN ontology_object_type t ON t.id = o.object_type_id "
                    "WHERE o.domain_id = :domain_id AND t.object_key = :object_type_key "
                    "AND JSON_UNQUOTE(JSON_EXTRACT(o.properties, :json_path)) "
                    f"IN ({placeholders})",
                    params,
                )
            )
        return [_normalize_row(row) for row in rows]

    async def query_objects(
        self,
        domain_id: int,
        *,
        access_agent_id: int | None = None,
        object_type_key: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search active object instances for an application or agent tool.

        Only display name and primary value are searched.  Property JSON is
        intentionally not interpolated into SQL, avoiding vendor-specific JSON
        operators and keeping this contract portable across management DB
        adapters.
        """
        domain = await self._require_domain(domain_id)
        (
            model_release,
            semantic_snapshot,
            ontology_release,
            definition,
            runtime_warnings,
        ) = await self._load_runtime_definition(
            domain_id,
            allow_compatibility_fallback=False,
        )
        if not isinstance(definition, dict):
            raise ValueError("当前业务领域尚未激活统一企业模型版本")
        released_object_types = [
            _normalize_row(item)
            for item in definition.get("object_types") or []
            if isinstance(item, dict) and item.get("status") == "active"
        ]
        released_types_by_key = {
            str(item.get("object_key")): item
            for item in released_object_types
            if str(item.get("object_key") or "").strip()
        }
        permission_context = await self._load_object_permission_context(domain, access_agent_id)
        safe_limit = min(max(int(limit), 1), 100)
        safe_offset = max(int(offset), 0)
        normalized_type = str(object_type_key or "").strip() or None
        normalized_search = str(search or "").strip() or None
        if normalized_type and normalized_type not in released_types_by_key:
            raise ValueError("对象类型未包含在当前激活的企业模型版本中")
        if not released_types_by_key:
            return {
                "objects": [],
                "total": 0,
                "limit": safe_limit,
                "offset": safe_offset,
                "has_more": False,
                "permission": self._permission_context_metadata(permission_context),
                "model_release": model_release,
                "semantic_snapshot": semantic_snapshot,
                "ontology_release": ontology_release,
                "warnings": runtime_warnings,
            }
        where = ["o.domain_id = :domain_id", "o.status = 'active'"]
        params: dict[str, Any] = {"domain_id": domain_id}
        released_placeholders = []
        for index, object_key in enumerate(sorted(released_types_by_key)):
            key = f"released_object_key_{index}"
            released_placeholders.append(f":{key}")
            params[key] = object_key
        where.append(f"t.object_key IN ({', '.join(released_placeholders)})")
        if normalized_type:
            where.append("t.object_key = :object_type_key")
            params["object_type_key"] = normalized_type
        if normalized_search:
            where.append("(o.display_name LIKE :search OR o.primary_value LIKE :search)")
            params["search"] = f"%{normalized_search}%"
        allowed_type_ids = (
            await self._allowed_database_object_type_ids_from_definitions(
                domain_id,
                released_object_types,
                permission_context[1],
                permission_context[2],
            )
            if permission_context is not None
            else None
        )
        self._append_object_type_access_filter(where, params, allowed_type_ids)
        where_sql = " AND ".join(where)
        db = get_management_db()
        count_rows = await db.execute_query(
            "SELECT COUNT(*) AS count FROM ontology_object o "
            "JOIN ontology_object_type t ON t.id = o.object_type_id "
            f"WHERE {where_sql}",
            params,
        )
        total = int(count_rows[0].get("count") or 0) if count_rows else 0
        rows = await db.execute_query(
            "SELECT o.*, t.object_key AS object_type_key, t.name AS object_type_name, "
            "t.source_query AS _permission_source_query, "
            "t.primary_property AS _permission_primary_property, "
            "t.display_property AS _permission_display_property "
            "FROM ontology_object o JOIN ontology_object_type t ON t.id = o.object_type_id "
            f"WHERE {where_sql} ORDER BY o.updated_at DESC, o.id DESC "
            "LIMIT :limit OFFSET :offset",
            {**params, "limit": safe_limit, "offset": safe_offset},
        )
        release_scoped_rows = []
        for raw_row in rows:
            row = _normalize_row(raw_row)
            released_type = released_types_by_key.get(str(row.get("object_type_key") or ""))
            if released_type is not None:
                row["object_type_name"] = released_type.get("name") or row.get(
                    "object_type_name"
                )
                row["_permission_source_query"] = released_type.get("source_query")
                row["_permission_primary_property"] = released_type.get("primary_property")
                row["_permission_display_property"] = released_type.get("display_property")
            release_scoped_rows.append(row)
        protected_rows = self._protect_object_rows(release_scoped_rows, permission_context)
        return {
            "objects": protected_rows,
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
            "has_more": safe_offset + len(protected_rows) < total,
            "permission": self._permission_context_metadata(permission_context),
            "model_release": model_release,
            "semantic_snapshot": semantic_snapshot,
            "ontology_release": ontology_release,
            "warnings": runtime_warnings,
        }

    async def get_object(
        self,
        domain_id: int,
        object_id: int,
        *,
        access_agent_id: int | None = None,
        apply_permissions: bool = False,
    ) -> dict[str, Any] | None:
        permission_context = None
        if apply_permissions:
            domain = await self._require_domain(domain_id)
            permission_context = await self._load_object_permission_context(domain, access_agent_id)
        rows = await get_management_db().execute_query(
            "SELECT o.*, t.object_key AS object_type_key, t.name AS object_type_name, "
            "t.source_query AS _permission_source_query, "
            "t.primary_property AS _permission_primary_property, "
            "t.display_property AS _permission_display_property "
            "FROM ontology_object o JOIN ontology_object_type t ON t.id = o.object_type_id "
            "WHERE o.id = :id AND o.domain_id = :domain_id",
            {"id": object_id, "domain_id": domain_id},
        )
        if not rows:
            return None
        protected = self._protect_object_rows(rows, permission_context)
        return protected[0] if protected else None

    async def _action_permission_context(
        self,
        domain_id: int,
        target: dict[str, Any],
        object_type: dict[str, Any],
        access_agent_id: int | None,
    ) -> tuple[int, dict[str, bool], dict[tuple[str, str], ColumnPolicy]] | None:
        database_backed = (
            str(target.get("source_kind") or "").lower() == "database"
            or int(target.get("source_datasource_id") or 0) > 0
        )
        if not database_backed:
            return None
        domain = await self._require_domain(domain_id)
        permission_context = await self._load_object_permission_context(domain, access_agent_id)
        if permission_context is None:
            raise PermissionError("动作执行缺少明确的权限主体")
        protected = self._protect_object_rows(
            [self._permission_metadata(target, object_type)],
            permission_context,
        )
        if not protected:
            raise PermissionError("当前权限主体无权访问目标对象")
        return permission_context

    @classmethod
    def _protect_action_result(
        cls,
        result: dict[str, Any],
        target: dict[str, Any],
        object_type: dict[str, Any],
        permission_context: tuple[
            int,
            dict[str, bool],
            dict[tuple[str, str], ColumnPolicy],
        ]
        | None,
    ) -> dict[str, Any]:
        if permission_context is None:
            return result
        protected_result = dict(result)
        metadata = cls._permission_context_metadata(permission_context)
        if metadata is not None:
            protected_result["permission"] = metadata
        for state_key in ("before_state", "after_state"):
            state = result.get(state_key)
            if not isinstance(state, dict):
                continue
            candidate = {
                **target,
                "properties": dict(state.get("properties") or {}),
                "source_properties": {},
                "overlay_properties": {},
            }
            protected = cls._protect_object_rows(
                [cls._permission_metadata(candidate, object_type)],
                permission_context,
            )
            if not protected:
                raise PermissionError("当前权限主体无权访问目标对象")
            protected_result[state_key] = {
                **state,
                "properties": protected[0].get("properties") or {},
            }
        return protected_result

    async def upsert_object(self, payload: OntologyObjectPayload) -> int:
        object_type = await self.get_object_type(
            payload.domain_id, object_type_id=payload.object_type_id
        )
        if not object_type:
            raise ValueError("对象类型不存在或不属于当前领域")
        primary_definition = property_definition(
            object_type["properties"], object_type["primary_property"]
        )
        primary_value = coerce_primary_value(primary_definition, payload.primary_value)
        values = validate_property_values(object_type["properties"], payload.properties)
        values[object_type["primary_property"]] = primary_value
        display_key = object_type.get("display_property")
        display_name = payload.display_name or (
            str(values.get(display_key))
            if display_key and values.get(display_key) is not None
            else str(primary_value)
        )
        db = get_management_db()
        params: dict[str, Any] = {
            "domain_id": payload.domain_id,
            "object_type_id": payload.object_type_id,
            "primary_value": str(primary_value),
            "display_name": display_name,
            "properties": _json(values),
            "status": payload.status,
            "source_properties": _json({}),
            "overlay_properties": _json({}),
        }
        if payload.id:
            existing = await self.get_object(payload.domain_id, payload.id)
            if not existing:
                raise ValueError("对象实例不存在")
            if int(existing["object_type_id"]) != payload.object_type_id:
                raise ValueError("对象实例不能更改对象类型")
            existing_primary_value = coerce_primary_value(
                primary_definition, existing.get("primary_value")
            )
            if existing_primary_value != primary_value:
                raise ValueError("对象主标识不可修改；如需修正身份，请重新同步或执行身份治理")
            duplicate = await db.execute_query(
                "SELECT id FROM ontology_object WHERE object_type_id = :object_type_id "
                "AND primary_value = :primary_value AND id <> :id",
                {
                    "object_type_id": payload.object_type_id,
                    "primary_value": str(primary_value),
                    "id": payload.id,
                },
            )
            if duplicate:
                raise ValueError(f"对象主标识已存在: {primary_value}")
            if existing.get("source_kind") == "database":
                source_properties = dict(existing.get("source_properties") or {})
                overlay_properties = {
                    key: value
                    for key, value in values.items()
                    if key != object_type["primary_property"]
                    and source_properties.get(key) != value
                }
                values = validate_property_values(
                    object_type["properties"], {**source_properties, **overlay_properties}
                )
                values[object_type["primary_property"]] = primary_value
                params["properties"] = _json(values)
                params["source_properties"] = _json(source_properties)
                params["overlay_properties"] = _json(overlay_properties)
            await db.execute_query(
                "UPDATE ontology_object SET primary_value = :primary_value, "
                "display_name = :display_name, properties = :properties, "
                "source_properties = :source_properties, overlay_properties = :overlay_properties, "
                "status = :status, "
                "version = version + 1 WHERE id = :id AND domain_id = :domain_id",
                {**params, "id": payload.id},
            )
            return payload.id
        existing = await db.execute_query(
            "SELECT id FROM ontology_object WHERE domain_id = :domain_id "
            "AND object_type_id = :object_type_id AND primary_value = :primary_value",
            {
                "domain_id": payload.domain_id,
                "object_type_id": payload.object_type_id,
                "primary_value": str(primary_value),
            },
        )
        if existing:
            object_id = int(existing[0]["id"])
            current = await self.get_object(payload.domain_id, object_id)
            if current and current.get("source_kind") == "database":
                source_properties = dict(current.get("source_properties") or {})
                overlay_properties = {
                    key: value
                    for key, value in values.items()
                    if key != object_type["primary_property"]
                    and source_properties.get(key) != value
                }
                values = validate_property_values(
                    object_type["properties"], {**source_properties, **overlay_properties}
                )
                values[object_type["primary_property"]] = primary_value
                params["properties"] = _json(values)
                params["source_properties"] = _json(source_properties)
                params["overlay_properties"] = _json(overlay_properties)
            await db.execute_query(
                "UPDATE ontology_object SET display_name = :display_name, "
                "properties = :properties, source_properties = :source_properties, "
                "overlay_properties = :overlay_properties, status = :status, "
                "version = version + 1 "
                "WHERE id = :id AND domain_id = :domain_id",
                {**params, "id": object_id},
            )
            return object_id
        return await db.execute_insert(
            "INSERT INTO ontology_object "
            "(domain_id, object_type_id, primary_value, display_name, properties, status, "
            "source_kind, source_properties, overlay_properties) VALUES "
            "(:domain_id, :object_type_id, :primary_value, :display_name, :properties, :status, "
            "'manual', :source_properties, :overlay_properties)",
            params,
        )

    async def delete_object(self, domain_id: int, object_id: int) -> bool:
        if not await self.get_object(domain_id, object_id):
            return False
        db = get_management_db()
        references = await db.execute_query(
            "SELECT "
            "(SELECT COUNT(*) FROM risk_issue WHERE domain_id = :domain_id "
            "AND subject_object_id = :id) AS risk_issues, "
            "(SELECT COUNT(*) FROM ontology_action_run WHERE domain_id = :domain_id "
            "AND target_object_id = :id) AS action_runs",
            {"domain_id": domain_id, "id": object_id},
        )
        reference_counts = references[0] if references else {}
        if int(reference_counts.get("risk_issues") or 0) or int(
            reference_counts.get("action_runs") or 0
        ):
            raise ValueError("对象已进入风险或动作审计，不能删除；请改为归档")
        await db.execute_transaction(
            [
                (
                    "DELETE FROM ontology_link WHERE domain_id = :domain_id "
                    "AND (source_object_id = :id OR target_object_id = :id)",
                    {"domain_id": domain_id, "id": object_id},
                ),
                (
                    "DELETE FROM ontology_object WHERE id = :id AND domain_id = :domain_id",
                    {"id": object_id, "domain_id": domain_id},
                ),
            ]
        )
        return True

    @classmethod
    def _protect_link_rows(
        cls,
        rows: list[dict[str, Any]],
        permission_context: tuple[
            int,
            dict[str, bool],
            dict[tuple[str, str], ColumnPolicy],
        ]
        | None,
    ) -> list[dict[str, Any]]:
        protected_links: list[dict[str, Any]] = []
        for raw_row in rows:
            row = _normalize_row(raw_row)
            endpoints: dict[str, dict[str, Any]] = {}
            visible = True
            for endpoint in ("source", "target"):
                endpoint_row = {
                    "source_kind": row.pop(f"_permission_{endpoint}_source_kind", None),
                    "source_datasource_id": row.pop(f"_permission_{endpoint}_datasource_id", None),
                    "primary_value": row.get(f"{endpoint}_primary_value"),
                    "display_name": row.get(f"{endpoint}_name"),
                    "properties": {},
                    "source_properties": {},
                    "overlay_properties": {},
                    "_permission_source_query": row.pop(
                        f"_permission_{endpoint}_source_query", None
                    ),
                    "_permission_primary_property": row.pop(
                        f"_permission_{endpoint}_primary_property", None
                    ),
                    "_permission_display_property": row.pop(
                        f"_permission_{endpoint}_display_property", None
                    ),
                }
                protected = cls._protect_object_rows([endpoint_row], permission_context)
                if not protected:
                    visible = False
                    break
                endpoints[endpoint] = protected[0]
            if not visible:
                continue
            for endpoint, endpoint_row in endpoints.items():
                row[f"{endpoint}_name"] = endpoint_row.get("display_name")
                row[f"{endpoint}_primary_value"] = endpoint_row.get("primary_value")
            for key in list(row):
                if key.startswith("_permission_"):
                    row.pop(key, None)
            protected_links.append(row)
        return protected_links

    async def list_links(
        self,
        domain_id: int,
        *,
        access_agent_id: int | None = None,
        apply_permissions: bool = True,
        release_definition: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        domain = await self._require_domain(domain_id)
        permission_context = (
            await self._load_object_permission_context(domain, access_agent_id)
            if apply_permissions
            else None
        )
        params: dict[str, Any] = {"domain_id": domain_id}
        release_links: dict[int, dict[str, Any]] = {}
        release_objects: dict[str, dict[str, Any]] = {}
        link_filter = ""
        if release_definition is not None:
            release_links = {
                int(item["id"]): item
                for item in release_definition.get("link_types") or []
                if isinstance(item, dict) and item.get("id") is not None
            }
            release_objects = {
                str(item.get("object_key")): item
                for item in release_definition.get("object_types") or []
                if isinstance(item, dict) and item.get("object_key")
            }
            if not release_links:
                return []
            placeholders = []
            for index, link_id in enumerate(sorted(release_links)):
                key = f"released_link_type_{index}"
                placeholders.append(f":{key}")
                params[key] = link_id
            link_filter = f" AND l.link_type_id IN ({', '.join(placeholders)})"
        rows = await get_management_db().execute_query(
            "SELECT l.*, t.link_key, t.name AS link_type_name, "
            "s.display_name AS source_name, s.primary_value AS source_primary_value, "
            "d.display_name AS target_name, d.primary_value AS target_primary_value, "
            "s.source_kind AS _permission_source_source_kind, "
            "s.source_datasource_id AS _permission_source_datasource_id, "
            "st.source_query AS _permission_source_source_query, "
            "st.primary_property AS _permission_source_primary_property, "
            "st.display_property AS _permission_source_display_property, "
            "d.source_kind AS _permission_target_source_kind, "
            "d.source_datasource_id AS _permission_target_datasource_id, "
            "dt.source_query AS _permission_target_source_query, "
            "dt.primary_property AS _permission_target_primary_property, "
            "dt.display_property AS _permission_target_display_property "
            "FROM ontology_link l JOIN ontology_link_type t ON t.id = l.link_type_id "
            "JOIN ontology_object s ON s.id = l.source_object_id "
            "JOIN ontology_object d ON d.id = l.target_object_id "
            "JOIN ontology_object_type st ON st.id = s.object_type_id "
            "JOIN ontology_object_type dt ON dt.id = d.object_type_id "
            "WHERE l.domain_id = :domain_id" + link_filter + " ORDER BY l.id DESC",
            params,
        )
        if release_links:
            scoped_rows = []
            for raw_row in rows:
                row = _normalize_row(raw_row)
                released_link = release_links.get(int(row.get("link_type_id") or 0))
                if released_link is None:
                    continue
                row["link_key"] = released_link.get("link_key")
                row["link_type_name"] = released_link.get("name") or row.get(
                    "link_type_name"
                )
                for endpoint, object_key_field in (
                    ("source", "source_object_key"),
                    ("target", "target_object_key"),
                ):
                    object_definition = release_objects.get(
                        str(released_link.get(object_key_field) or "")
                    )
                    if object_definition is None:
                        continue
                    row[f"_permission_{endpoint}_source_query"] = object_definition.get(
                        "source_query"
                    )
                    row[f"_permission_{endpoint}_primary_property"] = object_definition.get(
                        "primary_property"
                    )
                    row[f"_permission_{endpoint}_display_property"] = object_definition.get(
                        "display_property"
                    )
                scoped_rows.append(row)
            rows = scoped_rows
        return self._protect_link_rows(rows, permission_context)

    async def create_link(self, payload: OntologyLinkPayload) -> int:
        link_type = next(
            (
                item
                for item in await self.list_link_types(payload.domain_id)
                if int(item["id"]) == payload.link_type_id
            ),
            None,
        )
        if not link_type:
            raise ValueError("关系类型不存在")
        source = await self.get_object(payload.domain_id, payload.source_object_id)
        target = await self.get_object(payload.domain_id, payload.target_object_id)
        if not source or not target:
            raise ValueError("关系实例的起点或终点对象不存在")
        if source["object_type_key"] != link_type["source_object_key"]:
            raise ValueError("关系起点对象类型不匹配")
        if target["object_type_key"] != link_type["target_object_key"]:
            raise ValueError("关系终点对象类型不匹配")
        cardinality = str(link_type.get("cardinality") or "many_to_many")
        cardinality_sql = {
            "one_to_one": (
                "AND (source_object_id = :source_object_id "
                "OR target_object_id = :target_object_id)"
            ),
            "one_to_many": "AND target_object_id = :target_object_id",
            "many_to_one": "AND source_object_id = :source_object_id",
        }.get(cardinality)
        if cardinality_sql:
            existing_links = await get_management_db().execute_query(
                "SELECT source_object_id, target_object_id FROM ontology_link "
                "WHERE link_type_id = :link_type_id " + cardinality_sql + " LIMIT 1",
                {
                    "link_type_id": payload.link_type_id,
                    "source_object_id": payload.source_object_id,
                    "target_object_id": payload.target_object_id,
                },
            )
            conflict = next(
                (
                    existing_link
                    for existing_link in existing_links
                    if not (
                        int(existing_link["source_object_id"])
                        == payload.source_object_id
                        and int(existing_link["target_object_id"])
                        == payload.target_object_id
                    )
                ),
                None,
            )
            if conflict is not None:
                cardinality_label = {
                    "one_to_one": "一对一",
                    "one_to_many": "一对多",
                    "many_to_one": "多对一",
                }[cardinality]
                name = link_type.get("name") or link_type.get("link_key")
                raise ValueError(
                    f"关系 {name} 的基数为{cardinality_label}，端点已存在冲突关系"
                )
        return await get_management_db().execute_insert(
            "INSERT INTO ontology_link "
            "(domain_id, link_type_id, source_object_id, target_object_id, properties) VALUES "
            "(:domain_id, :link_type_id, :source_object_id, :target_object_id, :properties) "
            "ON DUPLICATE KEY UPDATE properties = VALUES(properties), "
            "updated_at = CURRENT_TIMESTAMP",
            {**payload.model_dump(exclude={"properties"}), "properties": _json(payload.properties)},
        )

    async def delete_link(self, domain_id: int, link_id: int) -> bool:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT id FROM ontology_link WHERE id = :id AND domain_id = :domain_id",
            {"id": link_id, "domain_id": domain_id},
        )
        if not rows:
            return False
        await db.execute_query(
            "DELETE FROM ontology_link WHERE id = :id AND domain_id = :domain_id",
            {"id": link_id, "domain_id": domain_id},
        )
        return True

    async def execute_action(
        self,
        domain_id: int,
        action_type_id: int,
        payload: OntologyActionExecutePayload,
        user: dict[str, Any],
        *,
        access_agent_id: int | None = None,
    ) -> dict[str, Any]:
        domain = await self._require_domain(domain_id)
        if str(domain.get("status") or "active").lower() != "active":
            raise ValueError("业务领域已停用，不能执行动作")
        live_action = await self.get_action_type(domain_id, action_type_id)
        if not live_action:
            raise ValueError("动作类型不存在")
        (
            model_release,
            semantic_snapshot,
            ontology_release,
            definition,
            runtime_warnings,
        ) = await self._load_runtime_definition(domain_id)
        released_object_type = None
        if definition is None:
            action = live_action
        else:
            action = next(
                (
                    _normalize_row(item)
                    for item in definition.get("action_types") or []
                    if isinstance(item, dict)
                    and item.get("action_key") == live_action.get("action_key")
                ),
                None,
            )
            if action is None:
                raise ValueError("动作未包含在当前激活的企业模型版本中")
            released_object_type = next(
                (
                    _normalize_row(item)
                    for item in definition.get("object_types") or []
                    if isinstance(item, dict)
                    and item.get("object_key") == action.get("target_object_key")
                ),
                None,
            )
            if released_object_type is None:
                raise ValueError("动作目标对象未包含在当前激活的企业模型版本中")
        if action["status"] != "active":
            raise ValueError("只有 active 状态的动作可以执行")
        roles = action.get("allowed_roles") or []
        if not isinstance(roles, list):
            raise ValueError("动作允许角色配置无效")
        for definition_key in ("parameters", "preconditions", "effects"):
            if not isinstance(action.get(definition_key), list):
                raise ValueError(f"动作{definition_key}配置无效")
        if roles and ontology_action_role(user.get("role")) not in roles:
            raise PermissionError("当前角色无权执行此动作")
        if action.get("requires_approval") and not payload.approval_reference:
            raise ValueError("该动作需要提供审批单号")
        if not ontology_release:
            raise ValueError("Ontology 尚未发布，不能执行生产动作")
        target = await self.get_object(domain_id, payload.target_object_id)
        if not target:
            raise ValueError("目标对象不存在")
        if target["object_type_key"] != action["target_object_key"]:
            raise ValueError("动作与目标对象类型不匹配")
        if (
            payload.expected_version is not None
            and int(target.get("version", 0)) != payload.expected_version
        ):
            raise ValueError("目标对象版本已变化，请刷新后重试")
        object_type = released_object_type
        if object_type is None:
            object_type = await self.get_object_type(
                domain_id, object_type_id=int(target["object_type_id"])
            )
        if not object_type:
            raise ValueError("动作目标对象类型不存在")
        permission_context = await self._action_permission_context(
            domain_id,
            target,
            object_type,
            access_agent_id,
        )

        db = get_management_db()
        target_version = int(target.get("version") or 1)
        before_state = {"properties": target["properties"], "version": target_version}
        context = dict(payload.decision_context)
        context["ontology_release"] = {
            "id": int(ontology_release["id"]),
            "version": ontology_release.get("version"),
            "definition_hash": ontology_release.get("definition_hash"),
        }
        if model_release is not None:
            context["model_release"] = model_release
        if semantic_snapshot is not None:
            context["semantic_snapshot"] = semantic_snapshot
        if runtime_warnings:
            context["warnings"] = runtime_warnings
        if payload.approval_reference:
            context["approval_reference"] = payload.approval_reference
        parameters = validate_action_parameters(action["parameters"], payload.parameters)
        check_preconditions(action["preconditions"], target["properties"], parameters)
        updated_properties = dict(target["properties"])
        updated_overlay = dict(target.get("overlay_properties") or {})
        for effect in action["effects"]:
            effect_value = resolve_action_value(
                effect.get("value"), parameters, target["properties"], user
            )
            updated_properties[effect["property"]] = effect_value
            updated_overlay[effect["property"]] = effect_value
        primary_property = object_type.get("primary_property")
        if primary_property and any(
            effect.get("property") == primary_property for effect in action["effects"]
        ):
            raise ValueError("动作不能修改对象主标识")
        updated_properties = validate_property_values(object_type["properties"], updated_properties)
        display_key = object_type.get("display_property")
        display_name = (
            str(updated_properties.get(display_key))
            if display_key and updated_properties.get(display_key) is not None
            else target["display_name"]
        )
        after_state = {
            "properties": updated_properties,
            "version": target_version + 1,
        }

        async def execute_in_transaction(session: Any) -> dict[str, Any]:
            run_insert = await session.execute(
                text(
                    "INSERT INTO ontology_action_run "
                    "(domain_id, ontology_release_id, action_type_id, target_object_id, "
                    "user_id, status, parameters, decision_context, before_state) VALUES "
                    "(:domain_id, :ontology_release_id, :action_type_id, :target_object_id, "
                    ":user_id, 'running', :parameters, :decision_context, :before_state)"
                ),
                {
                    "domain_id": domain_id,
                    "ontology_release_id": int(ontology_release["id"]),
                    "action_type_id": action_type_id,
                    "target_object_id": payload.target_object_id,
                    "user_id": user.get("id"),
                    "parameters": _json(parameters),
                    "decision_context": _json(context),
                    "before_state": _json(before_state),
                },
            )
            run_id = int(run_insert.lastrowid or 0)
            object_update = await session.execute(
                text(
                    "UPDATE ontology_object SET properties = :properties, "
                    "overlay_properties = :overlay_properties, display_name = :display_name, "
                    "version = version + 1 WHERE id = :id AND domain_id = :domain_id "
                    "AND version = :expected_version"
                ),
                {
                    "properties": _json(updated_properties),
                    "overlay_properties": _json(updated_overlay),
                    "display_name": display_name,
                    "id": payload.target_object_id,
                    "domain_id": domain_id,
                    "expected_version": target_version,
                },
            )
            if object_update.rowcount != 1:
                raise ValueError("目标对象版本已变化，请刷新后重试")
            await session.execute(
                text(
                    "UPDATE ontology_action_run SET status = 'succeeded', "
                    "after_state = :after_state, completed_at = CURRENT_TIMESTAMP "
                    "WHERE id = :id"
                ),
                {"after_state": _json(after_state), "id": run_id},
            )
            audit_event_id = await self._append_action_audit(
                session,
                domain_id=domain_id,
                run_id=run_id,
                release_id=int(ontology_release["id"]),
                action=action,
                target_object_id=payload.target_object_id,
                user=user,
                status="succeeded",
                payload={
                    "parameters": parameters,
                    "decision_context": context,
                    "before_state": before_state,
                    "after_state": after_state,
                },
            )
            return {
                "run_id": run_id,
                "status": "succeeded",
                "action": action["action_key"],
                "state_commit": {
                    "mode": (
                        "platform_overlay"
                        if str(target.get("source_kind") or "").lower() == "database"
                        else "platform_object"
                    ),
                    "business_source_written": False,
                    "message": (
                        "动作已更新平台孪生中的叠加状态，尚未写回业务数据源"
                        if str(target.get("source_kind") or "").lower() == "database"
                        else "动作已更新平台本地对象；当前没有外部业务系统写回"
                    ),
                },
                "model_release": model_release,
                "semantic_snapshot": semantic_snapshot,
                "ontology_release": context["ontology_release"],
                "warnings": runtime_warnings,
                "audit_event_id": audit_event_id,
                "target_object_id": payload.target_object_id,
                "before_state": before_state,
                "after_state": after_state,
            }

        result = await db.execute_in_transaction(execute_in_transaction)
        return self._protect_action_result(
            result,
            target,
            object_type,
            permission_context,
        )

    async def list_action_runs(
        self,
        domain_id: int,
        *,
        user_id: int | None = None,
        limit: int = 100,
        access_agent_id: int | None = None,
        apply_permissions: bool = True,
        release_definition: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        domain = await self._require_domain(domain_id)
        permission_context = (
            await self._load_object_permission_context(domain, access_agent_id)
            if apply_permissions
            else None
        )
        sql = (
            "SELECT r.*, a.action_key, a.name AS action_name, o.display_name AS target_name, "
            "o.primary_value AS _permission_target_primary_value, "
            "o.source_kind AS _permission_target_source_kind, "
            "o.source_datasource_id AS _permission_target_datasource_id, "
            "ot.source_query AS _permission_target_source_query, "
            "ot.primary_property AS _permission_target_primary_property, "
            "ot.display_property AS _permission_target_display_property, "
            "u.display_name AS user_name, u.username, rel.version AS ontology_release_version, "
            "rel.definition_hash AS ontology_release_hash "
            "FROM ontology_action_run r "
            "JOIN ontology_action_type a ON a.id = r.action_type_id "
            "LEFT JOIN ontology_object o ON o.id = r.target_object_id "
            "LEFT JOIN ontology_object_type ot ON ot.id = o.object_type_id "
            "LEFT JOIN app_user u ON u.id = r.user_id "
            "LEFT JOIN ontology_release rel ON rel.id = r.ontology_release_id "
            "WHERE r.domain_id = :domain_id"
        )
        params: dict[str, Any] = {"domain_id": domain_id, "limit": min(max(limit, 1), 500)}
        release_actions: dict[int, dict[str, Any]] = {}
        release_objects: dict[str, dict[str, Any]] = {}
        if release_definition is not None:
            release_actions = {
                int(item["id"]): item
                for item in release_definition.get("action_types") or []
                if isinstance(item, dict) and item.get("id") is not None
            }
            release_objects = {
                str(item.get("object_key")): item
                for item in release_definition.get("object_types") or []
                if isinstance(item, dict) and item.get("object_key")
            }
            if not release_actions:
                return []
            placeholders = []
            for index, action_id in enumerate(sorted(release_actions)):
                key = f"released_action_type_{index}"
                placeholders.append(f":{key}")
                params[key] = action_id
            sql += f" AND r.action_type_id IN ({', '.join(placeholders)})"
        if user_id is not None:
            sql += " AND r.user_id = :user_id"
            params["user_id"] = user_id
        sql += " ORDER BY r.id DESC LIMIT :limit"
        rows = await get_management_db().execute_query(sql, params)
        protected_runs: list[dict[str, Any]] = []
        for raw_row in rows:
            row = _normalize_row(raw_row)
            released_action = release_actions.get(int(row.get("action_type_id") or 0))
            if released_action is not None:
                row["action_key"] = released_action.get("action_key")
                row["action_name"] = released_action.get("name") or row.get("action_name")
                target_definition = release_objects.get(
                    str(released_action.get("target_object_key") or "")
                )
            else:
                target_definition = None
            target = {
                "source_kind": row.pop("_permission_target_source_kind", None),
                "source_datasource_id": row.pop("_permission_target_datasource_id", None),
                "primary_value": row.pop("_permission_target_primary_value", None),
                "display_name": row.get("target_name"),
                "properties": {},
                "source_properties": {},
                "overlay_properties": {},
            }
            object_type = {
                "source_query": row.pop("_permission_target_source_query", None),
                "primary_property": row.pop("_permission_target_primary_property", None),
                "display_property": row.pop("_permission_target_display_property", None),
            }
            if target_definition is not None:
                object_type.update(
                    {
                        "source_query": target_definition.get("source_query"),
                        "primary_property": target_definition.get("primary_property"),
                        "display_property": target_definition.get("display_property"),
                    }
                )
            protected_target = self._protect_object_rows(
                [self._permission_metadata(target, object_type)],
                permission_context,
            )
            if not protected_target:
                continue
            row["target_name"] = protected_target[0].get("display_name")
            protected_runs.append(
                self._protect_action_result(
                    row,
                    target,
                    object_type,
                    permission_context,
                )
            )
        return protected_runs

    async def export_bundle(self, domain_id: int, include_instances: bool = True) -> dict[str, Any]:
        domain = await self._require_domain(domain_id)
        bundle: dict[str, Any] = {
            "format": "wenqu-ontology",
            "version": 1,
            "domain": {
                "domain_key": domain["domain_key"],
                "name": domain["name"],
                "description": domain.get("description") or "",
            },
            "object_types": await self.list_object_types(domain_id),
            "link_types": await self.list_link_types(domain_id),
            "action_types": await self.list_action_types(domain_id),
        }
        if include_instances:
            bundle["objects"] = await self.list_objects(
                domain_id,
                access_agent_id=None,
                apply_permissions=False,
            )
            bundle["links"] = await self.list_links(
                domain_id, access_agent_id=None, apply_permissions=False
            )
        return bundle

    async def import_bundle(
        self, domain_id: int, bundle: dict[str, Any], replace: bool = False
    ) -> dict[str, int]:
        await self._require_domain(domain_id)
        if not isinstance(bundle, dict):
            raise ValueError("Ontology bundle 必须是 JSON 对象")
        try:
            bundle_version = bundle.get("version", 0)
            if isinstance(bundle_version, bool) or int(bundle_version) != 1:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("不支持的 Ontology bundle 格式") from exc
        if bundle.get("format") != "wenqu-ontology":
            raise ValueError("不支持的 Ontology bundle 格式")

        def section(name: str) -> list[dict[str, Any]]:
            values = bundle.get(name) or []
            if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
                raise ValueError(f"Ontology bundle 的 {name} 必须是对象数组")
            return values

        raw_object_types = section("object_types")
        raw_link_types = section("link_types")
        raw_action_types = section("action_types")
        raw_objects = section("objects")
        raw_links = section("links")

        # Validate all type definitions before replace can remove the current domain.
        object_payloads: list[OntologyObjectTypePayload] = []
        object_keys: set[str] = set()
        for raw in raw_object_types:
            item = dict(raw)
            item.pop("id", None)
            item["domain_id"] = domain_id
            try:
                payload = OntologyObjectTypePayload.model_validate(item)
            except ValidationError as exc:
                raise ValueError(f"对象类型定义无效: {exc}") from exc
            if payload.object_key in object_keys:
                raise ValueError(f"bundle 中对象标识重复: {payload.object_key}")
            object_keys.add(payload.object_key)
            object_payloads.append(payload)

        existing_object_types = [] if replace else await self.list_object_types(domain_id)
        known_object_keys = object_keys | {item["object_key"] for item in existing_object_types}
        link_payloads: list[OntologyLinkTypePayload] = []
        link_keys: set[str] = set()
        for raw in raw_link_types:
            item = dict(raw)
            item.pop("id", None)
            item["domain_id"] = domain_id
            try:
                payload = OntologyLinkTypePayload.model_validate(item)
            except ValidationError as exc:
                raise ValueError(f"关系类型定义无效: {exc}") from exc
            if payload.link_key in link_keys:
                raise ValueError(f"bundle 中关系标识重复: {payload.link_key}")
            if (
                payload.source_object_key not in known_object_keys
                or payload.target_object_key not in known_object_keys
            ):
                raise ValueError(f"关系 {payload.link_key} 引用了未定义对象类型")
            link_keys.add(payload.link_key)
            link_payloads.append(payload)

        action_payloads: list[OntologyActionTypePayload] = []
        action_keys: set[str] = set()
        for raw in raw_action_types:
            item = dict(raw)
            item.pop("id", None)
            item["domain_id"] = domain_id
            try:
                payload = OntologyActionTypePayload.model_validate(item)
            except ValidationError as exc:
                raise ValueError(f"动作类型定义无效: {exc}") from exc
            if payload.action_key in action_keys:
                raise ValueError(f"bundle 中动作标识重复: {payload.action_key}")
            if payload.target_object_key not in known_object_keys:
                raise ValueError(f"动作 {payload.action_key} 引用了未定义对象类型")
            action_keys.add(payload.action_key)
            action_payloads.append(payload)

        for raw in raw_objects:
            object_key = raw.get("object_type_key")
            if not isinstance(object_key, str) or not object_key:
                raise ValueError("对象实例缺少 object_type_key")
            if "primary_value" not in raw or raw["primary_value"] is None:
                raise ValueError(f"对象实例 {object_key} 缺少 primary_value")
        for raw in raw_links:
            link_key = raw.get("link_key")
            if not isinstance(link_key, str) or not link_key:
                raise ValueError("关系实例缺少 link_key")
            if raw.get("source_primary_value") is None or raw.get("target_primary_value") is None:
                raise ValueError(f"关系实例 {link_key} 缺少端点主标识")

        if replace:
            await self._clear_domain(domain_id)
        object_ids: dict[str, int] = {}
        for payload in object_payloads:
            item = payload.model_dump()
            existing = await self.get_object_type(domain_id, object_key=item["object_key"])
            if existing:
                item["id"] = existing["id"]
            try:
                object_ids[item["object_key"]] = await self.upsert_object_type(
                    OntologyObjectTypePayload.model_validate(item)
                )
            except ValidationError as exc:
                raise ValueError(f"对象类型定义无效: {exc}") from exc

        link_type_ids: dict[str, int] = {}
        for payload in link_payloads:
            item = payload.model_dump()
            existing = next(
                (
                    x
                    for x in await self.list_link_types(domain_id)
                    if x["link_key"] == item["link_key"]
                ),
                None,
            )
            if existing:
                item["id"] = existing["id"]
            link_type_ids[item["link_key"]] = await self.upsert_link_type(
                OntologyLinkTypePayload.model_validate(item)
            )

        for payload in action_payloads:
            item = payload.model_dump()
            existing = next(
                (
                    x
                    for x in await self.list_action_types(domain_id)
                    if x["action_key"] == item["action_key"]
                ),
                None,
            )
            if existing:
                item["id"] = existing["id"]
            await self.upsert_action_type(OntologyActionTypePayload.model_validate(item))

        object_type_definitions = {
            item["object_key"]: item for item in await self.list_object_types(domain_id)
        }

        def object_identity(object_key: str, value: Any) -> str:
            definition = object_type_definitions.get(object_key)
            if not definition:
                raise ValueError(f"对象实例引用了未定义对象类型: {object_key}")
            primary_definition = property_definition(
                definition["properties"], definition["primary_property"]
            )
            return str(coerce_primary_value(primary_definition, value))

        imported_objects: dict[tuple[str, str], int] = {}
        for raw in raw_objects:
            object_key = raw.get("object_type_key")
            if object_key not in object_type_definitions:
                raise ValueError(f"对象实例引用了未定义对象类型: {object_key}")
            object_type_id = object_ids.get(object_key)
            if not object_type_id:
                object_type_id = int(object_type_definitions[object_key]["id"])
            item = {
                "domain_id": domain_id,
                "object_type_id": object_type_id,
                "primary_value": raw["primary_value"],
                "display_name": raw.get("display_name"),
                "properties": raw.get("properties") or {},
                "status": raw.get("status") or "active",
            }
            try:
                object_id = await self.upsert_object(OntologyObjectPayload.model_validate(item))
            except ValidationError as exc:
                raise ValueError(f"对象实例定义无效: {exc}") from exc
            imported_objects[(object_key, object_identity(object_key, raw["primary_value"]))] = (
                object_id
            )

        for raw in raw_links:
            link_key = raw.get("link_key")
            if not isinstance(link_key, str) or link_key not in link_type_ids:
                # A bundle may contain only the definitions it owns; links must still
                # reference a type in the target domain rather than being silently lost.
                existing_type = next(
                    (
                        item
                        for item in await self.list_link_types(domain_id)
                        if item["link_key"] == link_key
                    ),
                    None,
                )
                if not existing_type:
                    raise ValueError(f"关系实例引用了未定义关系类型: {link_key}")
                link_type_id = int(existing_type["id"])
                link_type = existing_type
            else:
                link_type_id = link_type_ids[link_key]
                link_type = next(
                    item
                    for item in await self.list_link_types(domain_id)
                    if int(item["id"]) == link_type_id
                )
            source_value = raw["source_primary_value"]
            target_value = raw["target_primary_value"]
            source_id = imported_objects.get(
                (
                    link_type["source_object_key"],
                    object_identity(link_type["source_object_key"], source_value),
                )
            )
            target_id = imported_objects.get(
                (
                    link_type["target_object_key"],
                    object_identity(link_type["target_object_key"], target_value),
                )
            )
            if not source_id or not target_id:
                raise ValueError(f"关系实例 {link_key} 的端点对象不存在")
            await self.create_link(
                OntologyLinkPayload(
                    domain_id=domain_id,
                    link_type_id=link_type_id,
                    source_object_id=source_id,
                    target_object_id=target_id,
                    properties=raw.get("properties") or {},
                )
            )
        return {
            "object_types": len(object_payloads),
            "link_types": len(link_payloads),
            "action_types": len(action_payloads),
            "objects": len(imported_objects),
            "links": len(raw_links),
        }

    async def _clear_domain(self, domain_id: int) -> None:
        db = get_management_db()
        history = await db.execute_query(
            "SELECT "
            "(SELECT COUNT(*) FROM ontology_release WHERE domain_id = :id) AS releases, "
            "(SELECT COUNT(*) FROM ontology_action_run WHERE domain_id = :id) AS action_runs, "
            "(SELECT COUNT(*) FROM risk_issue WHERE domain_id = :id) AS risk_issues, "
            "(SELECT COUNT(*) FROM risk_report WHERE domain_id = :id) AS reports, "
            "(SELECT COUNT(*) FROM decision_audit_event WHERE domain_id = :id) AS audit_events",
            {"id": domain_id},
        )
        counts = history[0] if history else {}
        if any(int(counts.get(key) or 0) for key in counts):
            raise ValueError(
                "当前领域已有发布版本或决策历史，不能替换 Ontology；请新建领域或发布新版本"
            )
        await db.execute_transaction(
            [
                ("DELETE FROM ontology_action_run WHERE domain_id = :id", {"id": domain_id}),
                ("DELETE FROM ontology_link WHERE domain_id = :id", {"id": domain_id}),
                ("DELETE FROM ontology_object WHERE domain_id = :id", {"id": domain_id}),
                ("DELETE FROM ontology_release WHERE domain_id = :id", {"id": domain_id}),
                ("DELETE FROM ontology_action_type WHERE domain_id = :id", {"id": domain_id}),
                ("DELETE FROM ontology_link_type WHERE domain_id = :id", {"id": domain_id}),
                (
                    "DELETE p FROM ontology_property p JOIN ontology_object_type o "
                    "ON o.id = p.object_type_id WHERE o.domain_id = :id",
                    {"id": domain_id},
                ),
                ("DELETE FROM ontology_object_type WHERE domain_id = :id", {"id": domain_id}),
            ]
        )


def property_definition(properties: list[dict[str, Any]], key: str) -> dict[str, Any]:
    for item in properties:
        if item["property_key"] == key:
            return item
    raise ValueError(f"未知对象属性: {key}")


def coerce_primary_value(definition: dict[str, Any], value: Any) -> Any:
    """Coerce a primary value while retaining a string representation for MySQL storage.

    The object table stores primary values in a VARCHAR column, but the corresponding
    property may be numeric or temporal.  API clients commonly submit numeric keys as
    strings, so primary values get a small amount of representation-aware coercion here;
    normal properties remain deliberately strict in ``coerce_value``.
    """
    data_type = definition.get("data_type") or "string"
    if data_type == "integer" and isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{definition.get('name') or '主标识'} 必须是整数") from exc
    if data_type == "number" and isinstance(value, str):
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError(f"{definition.get('name') or '主标识'} 必须是数字") from exc
        if not math.isfinite(number):
            raise ValueError(f"{definition.get('name') or '主标识'} 必须是有限数字")
        return number
    return coerce_value(definition, value)


def coerce_value(definition: dict[str, Any], value: Any) -> Any:
    if value is None:
        if definition.get("required"):
            raise ValueError(f"缺少必填属性: {definition['name']}")
        return None
    data_type = definition.get("data_type") or "string"
    label = definition.get("name") or definition.get("property_key")
    if data_type in {"string", "text"}:
        if not isinstance(value, str):
            raise ValueError(f"{label} 必须是文本")
        return value
    if data_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} 必须是整数")
        return value
    if data_type == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{label} 必须是数字")
        return value
    if data_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{label} 必须是布尔值")
        return value
    if data_type == "date":
        if not isinstance(value, str):
            raise ValueError(f"{label} 必须是 ISO 日期")
        date.fromisoformat(value)
        return value
    if data_type == "datetime":
        if not isinstance(value, str):
            raise ValueError(f"{label} 必须是 ISO 时间")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    if data_type == "json":
        return value
    raise ValueError(f"不支持的属性类型: {data_type}")


def validate_property_values(
    definitions: list[dict[str, Any]], values: dict[str, Any]
) -> dict[str, Any]:
    known = {item["property_key"] for item in definitions}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError("存在未定义属性: " + "、".join(unknown))
    result: dict[str, Any] = {}
    for definition in definitions:
        key = definition["property_key"]
        value = values.get(key, definition.get("default_value"))
        if value is None and definition.get("required"):
            raise ValueError(f"缺少必填属性: {definition['name']}")
        if value is not None:
            result[key] = coerce_value(definition, value)
    return result


def validate_synced_property_values(
    definitions: list[dict[str, Any]], values: dict[str, Any]
) -> dict[str, Any]:
    """Coerce database row values into the stricter Ontology property contract."""
    result: dict[str, Any] = {}
    for definition in definitions:
        key = definition["property_key"]
        value = values.get(key, definition.get("default_value"))
        if value is None:
            if definition.get("required"):
                raise ValueError(f"同步结果缺少必填字段: {key}")
            continue
        result[key] = coerce_synced_value(definition, value)
    return result


def coerce_synced_value(definition: dict[str, Any], value: Any) -> Any:
    data_type = definition.get("data_type") or "string"
    label = definition.get("name") or definition.get("property_key")
    if data_type in {"string", "text"} and not isinstance(value, str):
        value = str(value)
    elif data_type == "integer" and not isinstance(value, bool):
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} 必须是整数") from exc
        if not numeric.is_integer():
            raise ValueError(f"{label} 必须是整数")
        value = int(numeric)
    elif data_type == "number" and not isinstance(value, bool):
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} 必须是数字") from exc
        if not math.isfinite(value):
            raise ValueError(f"{label} 必须是有限数字")
    elif data_type == "boolean" and not isinstance(value, bool):
        if value in (0, "0", "false", "False", "no", "No"):
            value = False
        elif value in (1, "1", "true", "True", "yes", "Yes"):
            value = True
        else:
            raise ValueError(f"{label} 必须是布尔值")
    elif data_type in {"date", "datetime"} and isinstance(value, date | datetime):
        value = value.isoformat()
    return coerce_value(definition, value)


def relation_lookup_key(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return str(value)


def relation_object_lookup_key(properties: dict[str, Any], property_keys: list[str]) -> str | None:
    """Build a collision-safe ordered key and reject incomplete endpoints."""

    if not property_keys or any(not key for key in property_keys):
        raise ValueError("关系属性键不能为空")
    values: list[str] = []
    for property_key in property_keys:
        if property_key not in properties:
            return None
        value = properties[property_key]
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        values.append(relation_lookup_key(value))
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def unique_objects(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    for item in values:
        by_id[int(item["id"])] = item
    return [by_id[object_id] for object_id in sorted(by_id)]


def validate_action_parameters(
    definitions: list[dict[str, Any]], parameters: dict[str, Any]
) -> dict[str, Any]:
    known = {item["parameter_key"] for item in definitions}
    unknown = sorted(set(parameters) - known)
    if unknown:
        raise ValueError("存在未定义动作参数: " + "、".join(unknown))
    result: dict[str, Any] = {}
    for definition in definitions:
        key = definition["parameter_key"]
        value = parameters.get(key)
        if value is None and definition.get("required"):
            raise ValueError(f"缺少必填动作参数: {definition['name']}")
        if value is None:
            continue
        coerced = coerce_value(
            {
                "property_key": key,
                "name": definition.get("name") or key,
                "data_type": definition.get("data_type") or "string",
                "required": definition.get("required", False),
            },
            value,
        )
        options = definition.get("options") or []
        if options and coerced not in options:
            raise ValueError(f"{definition.get('name') or key} 不在允许选项中")
        result[key] = coerced
    return result


def resolve_action_value(
    value: Any,
    parameters: dict[str, Any],
    target: dict[str, Any],
    user: dict[str, Any],
) -> Any:
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    if value.startswith("$param."):
        key = value.removeprefix("$param.")
        if key not in parameters:
            raise ValueError(f"动作参数未提供: {key}")
        return parameters[key]
    if value.startswith("$target."):
        return target.get(value.removeprefix("$target."))
    if value == "$now":
        return datetime.now(timezone.utc).isoformat()
    if value == "$user.id":
        return user.get("id")
    if value in {"$user.name", "$user.username"}:
        return user.get("display_name") or user.get("username")
    raise ValueError(f"不支持的动作值表达式: {value}")


def check_preconditions(
    conditions: list[dict[str, Any]], target: dict[str, Any], parameters: dict[str, Any]
) -> None:
    for condition in conditions:
        actual = target.get(condition["property"])
        expected = resolve_action_value(condition.get("value"), parameters, target, {})
        operator = condition.get("operator") or "eq"
        passed = False
        try:
            if operator == "eq":
                passed = actual == expected
            elif operator == "ne":
                passed = actual != expected
            elif operator == "in":
                passed = actual in expected
            elif operator == "not_in":
                passed = actual not in expected
            elif operator == "gt":
                passed = actual > expected
            elif operator == "gte":
                passed = actual >= expected
            elif operator == "lt":
                passed = actual < expected
            elif operator == "lte":
                passed = actual <= expected
            elif operator == "exists":
                passed = (actual is not None) == bool(expected if expected is not None else True)
        except TypeError:
            passed = False
        if not passed:
            raise ValueError(
                condition.get("message")
                or f"动作前置条件不满足: {condition['property']} {operator} {expected}"
            )


_ontology_service: OntologyService | None = None


def get_ontology_service() -> OntologyService:
    global _ontology_service
    if _ontology_service is None:
        _ontology_service = OntologyService()
    return _ontology_service
