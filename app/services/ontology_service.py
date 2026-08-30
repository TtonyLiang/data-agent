"""Operational Ontology definition, runtime, publishing, and audit service."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text

from app.db.mysql import get_management_db
from app.models.ontology import (
    OntologyActionExecutePayload,
    OntologyActionTypePayload,
    OntologyLinkPayload,
    OntologyLinkTypePayload,
    OntologyObjectPayload,
    OntologyObjectTypePayload,
)

JSON_FIELDS = {
    "default_value",
    "parameters",
    "preconditions",
    "effects",
    "allowed_roles",
    "properties",
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
    "decision_context": {},
    "before_state": {},
    "after_state": {},
    "validation_json": {},
    "definition_json": {},
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


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
    for key in ("required", "unique", "requires_approval"):
        if key in normalized:
            normalized[key] = bool(normalized[key])
    return normalized


class OntologyService:
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
        params = payload.model_dump(exclude={"id", "properties"})
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
                "display_property = :display_property, status = :status WHERE id = :id",
                {**params, "id": payload.id},
            )
            object_type_id = payload.id
        else:
            object_type_id = await db.execute_insert(
                "INSERT INTO ontology_object_type "
                "(domain_id, object_key, name, description, primary_property, "
                "display_property, status) "
                "VALUES (:domain_id, :object_key, :name, :description, :primary_property, "
                ":display_property, :status)",
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
        return [_normalize_row(row) for row in rows]

    async def upsert_link_type(self, payload: OntologyLinkTypePayload) -> int:
        await self._require_domain(payload.domain_id)
        source = await self.get_object_type(payload.domain_id, object_key=payload.source_object_key)
        target = await self.get_object_type(payload.domain_id, object_key=payload.target_object_key)
        if not source or not target:
            raise ValueError("关系的起点和终点必须引用已存在的对象类型")
        source_key = payload.source_property or source["primary_property"]
        target_key = payload.target_property or target["primary_property"]
        if source_key not in {item["property_key"] for item in source["properties"]}:
            raise ValueError("关系起点属性不存在")
        if target_key not in {item["property_key"] for item in target["properties"]}:
            raise ValueError("关系终点属性不存在")
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
            **payload.model_dump(exclude={"id"}),
            "source_property": source_key,
            "target_property": target_key,
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

    async def build_agent_context(
        self, domain_id: int, *, role: str = "user"
    ) -> dict[str, Any]:
        """Build the bounded, runtime-facing Ontology context for an agent.

        Draft/deprecated definitions are deliberately omitted from the agent
        context.  Action visibility is additionally filtered by the caller's
        role; the execute path performs the same check again before writing.
        The payload contains definitions, not all object instances, so it is
        safe to pass as prompt/tool metadata and remains bounded as data grows.
        """
        domain = await self._require_domain(domain_id)
        object_types = [
            item for item in await self.list_object_types(domain_id)
            if item.get("status") == "active"
        ]
        object_keys = {str(item.get("object_key")) for item in object_types}
        link_types = [
            item
            for item in await self.list_link_types(domain_id)
            if item.get("status") == "active"
            and item.get("source_object_key") in object_keys
            and item.get("target_object_key") in object_keys
        ]
        action_types = [
            item
            for item in await self.list_action_types(domain_id)
            if item.get("status") == "active"
            and item.get("target_object_key") in object_keys
            and role in (item.get("allowed_roles") or [])
        ]
        release_rows = await get_management_db().execute_query(
            "SELECT id, version, name, description, created_at "
            "FROM ontology_release WHERE domain_id = :domain_id "
            "ORDER BY version DESC LIMIT 1",
            {"domain_id": domain_id},
        )
        release = _normalize_row(release_rows[0]) if release_rows else None

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
                "domain_key": domain.get("domain_key"),
                "name": domain.get("name"),
                "description": domain.get("description") or "",
            },
            "release": release,
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
            if item.get("source_property") not in {
                p["property_key"] for p in source_properties if isinstance(p, dict)
            }:
                errors.append({"asset": item["link_key"], "message": "关系起点属性不存在"})
            if item.get("target_property") not in {
                p["property_key"] for p in target_properties if isinstance(p, dict)
            }:
                errors.append({"asset": item["link_key"], "message": "关系终点属性不存在"})

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
        definition = await self.export_bundle(domain_id, include_instances=False)
        release_id = await db.execute_insert(
            "INSERT INTO ontology_release "
            "(domain_id, version, name, description, validation_json, "
            "definition_json, published_by) "
            "VALUES (:domain_id, :version, :name, :description, :validation_json, "
            ":definition_json, :published_by)",
            {
                "domain_id": domain_id,
                "version": version,
                "name": name or f"V{version}",
                "description": description,
                "validation_json": _json(validation),
                "definition_json": _json(definition),
                "published_by": published_by,
            },
        )
        return {
            "published": True,
            "id": release_id,
            "version": version,
            "validation": validation,
        }

    async def list_releases(self, domain_id: int) -> list[dict[str, Any]]:
        await self._require_domain(domain_id)
        rows = await get_management_db().execute_query(
            "SELECT id, domain_id, version, name, description, validation_json, "
            "published_by, created_at FROM ontology_release WHERE domain_id = :domain_id "
            "ORDER BY version DESC",
            {"domain_id": domain_id},
        )
        return [_normalize_row(row) for row in rows]

    async def list_objects(
        self, domain_id: int, object_type_id: int | None = None
    ) -> list[dict[str, Any]]:
        await self._require_domain(domain_id)
        sql = (
            "SELECT o.*, t.object_key AS object_type_key, t.name AS object_type_name "
            "FROM ontology_object o JOIN ontology_object_type t ON t.id = o.object_type_id "
            "WHERE o.domain_id = :domain_id"
        )
        params: dict[str, Any] = {"domain_id": domain_id}
        if object_type_id is not None:
            sql += " AND o.object_type_id = :object_type_id"
            params["object_type_id"] = object_type_id
        sql += " ORDER BY o.updated_at DESC, o.id DESC"
        rows = await get_management_db().execute_query(sql, params)
        return [_normalize_row(row) for row in rows]

    async def query_objects(
        self,
        domain_id: int,
        *,
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
        await self._require_domain(domain_id)
        safe_limit = min(max(int(limit), 1), 100)
        safe_offset = max(int(offset), 0)
        normalized_type = str(object_type_key or "").strip() or None
        normalized_search = str(search or "").strip() or None
        where = ["o.domain_id = :domain_id", "o.status = 'active'"]
        params: dict[str, Any] = {"domain_id": domain_id}
        if normalized_type:
            where.append("t.object_key = :object_type_key")
            params["object_type_key"] = normalized_type
        if normalized_search:
            where.append("(o.display_name LIKE :search OR o.primary_value LIKE :search)")
            params["search"] = f"%{normalized_search}%"
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
            "SELECT o.*, t.object_key AS object_type_key, t.name AS object_type_name "
            "FROM ontology_object o JOIN ontology_object_type t ON t.id = o.object_type_id "
            f"WHERE {where_sql} ORDER BY o.updated_at DESC, o.id DESC "
            "LIMIT :limit OFFSET :offset",
            {**params, "limit": safe_limit, "offset": safe_offset},
        )
        return {
            "objects": [_normalize_row(row) for row in rows],
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
            "has_more": safe_offset + len(rows) < total,
        }

    async def get_object(self, domain_id: int, object_id: int) -> dict[str, Any] | None:
        rows = await get_management_db().execute_query(
            "SELECT o.*, t.object_key AS object_type_key, t.name AS object_type_name "
            "FROM ontology_object o JOIN ontology_object_type t ON t.id = o.object_type_id "
            "WHERE o.id = :id AND o.domain_id = :domain_id",
            {"id": object_id, "domain_id": domain_id},
        )
        return _normalize_row(rows[0]) if rows else None

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
        params = {
            "domain_id": payload.domain_id,
            "object_type_id": payload.object_type_id,
            "primary_value": str(primary_value),
            "display_name": display_name,
            "properties": _json(values),
            "status": payload.status,
        }
        if payload.id:
            existing = await self.get_object(payload.domain_id, payload.id)
            if not existing:
                raise ValueError("对象实例不存在")
            if int(existing["object_type_id"]) != payload.object_type_id:
                raise ValueError("对象实例不能更改对象类型")
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
            await db.execute_query(
                "UPDATE ontology_object SET primary_value = :primary_value, "
                "display_name = :display_name, properties = :properties, status = :status, "
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
            await db.execute_query(
                "UPDATE ontology_object SET display_name = :display_name, "
                "properties = :properties, status = :status, version = version + 1 "
                "WHERE id = :id AND domain_id = :domain_id",
                {**params, "id": object_id},
            )
            return object_id
        return await db.execute_insert(
            "INSERT INTO ontology_object "
            "(domain_id, object_type_id, primary_value, display_name, properties, status) VALUES "
            "(:domain_id, :object_type_id, :primary_value, :display_name, :properties, :status)",
            params,
        )

    async def delete_object(self, domain_id: int, object_id: int) -> bool:
        if not await self.get_object(domain_id, object_id):
            return False
        await get_management_db().execute_transaction(
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

    async def list_links(self, domain_id: int) -> list[dict[str, Any]]:
        await self._require_domain(domain_id)
        rows = await get_management_db().execute_query(
            "SELECT l.*, t.link_key, t.name AS link_type_name, "
            "s.display_name AS source_name, s.primary_value AS source_primary_value, "
            "d.display_name AS target_name, d.primary_value AS target_primary_value "
            "FROM ontology_link l JOIN ontology_link_type t ON t.id = l.link_type_id "
            "JOIN ontology_object s ON s.id = l.source_object_id "
            "JOIN ontology_object d ON d.id = l.target_object_id "
            "WHERE l.domain_id = :domain_id ORDER BY l.id DESC",
            {"domain_id": domain_id},
        )
        return [_normalize_row(row) for row in rows]

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
    ) -> dict[str, Any]:
        action = await self.get_action_type(domain_id, action_type_id)
        if not action:
            raise ValueError("动作类型不存在")
        if action["status"] != "active":
            raise ValueError("只有 active 状态的动作可以执行")
        roles = action.get("allowed_roles") or []
        if not isinstance(roles, list):
            raise ValueError("动作允许角色配置无效")
        for definition_key in ("parameters", "preconditions", "effects"):
            if not isinstance(action.get(definition_key), list):
                raise ValueError(f"动作{definition_key}配置无效")
        if roles and user.get("role") not in roles:
            raise PermissionError("当前角色无权执行此动作")
        if action.get("requires_approval") and not payload.approval_reference:
            raise ValueError("该动作需要提供审批单号")
        release = await get_management_db().execute_query(
            "SELECT id FROM ontology_release WHERE domain_id = :domain_id "
            "ORDER BY version DESC LIMIT 1",
            {"domain_id": domain_id},
        )
        if not release:
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

        db = get_management_db()
        target_version = int(target.get("version") or 1)
        before_state = {"properties": target["properties"], "version": target_version}
        context = dict(payload.decision_context)
        if payload.approval_reference:
            context["approval_reference"] = payload.approval_reference
        run_id = await db.execute_insert(
            "INSERT INTO ontology_action_run "
            "(domain_id, action_type_id, target_object_id, user_id, status, parameters, "
            "decision_context, before_state) VALUES "
            "(:domain_id, :action_type_id, :target_object_id, :user_id, 'running', "
            ":parameters, :decision_context, :before_state)",
            {
                "domain_id": domain_id,
                "action_type_id": action_type_id,
                "target_object_id": payload.target_object_id,
                "user_id": user.get("id"),
                "parameters": _json(payload.parameters),
                "decision_context": _json(context),
                "before_state": _json(before_state),
            },
        )
        try:
            parameters = validate_action_parameters(action["parameters"], payload.parameters)
            check_preconditions(action["preconditions"], target["properties"], parameters)
            updated_properties = dict(target["properties"])
            for effect in action["effects"]:
                updated_properties[effect["property"]] = resolve_action_value(
                    effect.get("value"), parameters, target["properties"], user
                )
            object_type = await self.get_object_type(
                domain_id, object_type_id=int(target["object_type_id"])
            )
            if not object_type:
                raise ValueError("动作目标对象类型不存在")
            primary_property = object_type.get("primary_property")
            if primary_property and any(
                effect.get("property") == primary_property for effect in action["effects"]
            ):
                raise ValueError("动作不能修改对象主标识")
            updated_properties = validate_property_values(
                object_type["properties"], updated_properties
            )
            display_key = object_type.get("display_property")
            display_name = (
                str(updated_properties.get(display_key))
                if display_key and updated_properties.get(display_key) is not None
                else target["display_name"]
            )
            update_sql = (
                "UPDATE ontology_object SET properties = :properties, "
                "display_name = :display_name, version = version + 1 "
                "WHERE id = :id AND domain_id = :domain_id"
            )
            update_params = {
                "properties": _json(updated_properties),
                "display_name": display_name,
                "id": payload.target_object_id,
                "domain_id": domain_id,
            }
            if payload.expected_version is not None:
                update_sql += " AND version = :expected_version"
                update_params["expected_version"] = payload.expected_version
            if payload.expected_version is not None and hasattr(db, "execute_in_transaction"):

                async def update_with_version(session: Any) -> None:
                    result = await session.execute(text(update_sql), update_params)
                    if result.rowcount != 1:
                        raise ValueError("目标对象版本已变化，请刷新后重试")

                await db.execute_in_transaction(update_with_version)
            else:
                await db.execute_query(update_sql, update_params)
                if payload.expected_version is not None:
                    current_version = await db.execute_query(
                        "SELECT version FROM ontology_object "
                        "WHERE id = :id AND domain_id = :domain_id",
                        {"id": payload.target_object_id, "domain_id": domain_id},
                    )
                    if (
                        not current_version
                        or int(current_version[0]["version"]) != payload.expected_version + 1
                    ):
                        raise ValueError("目标对象版本已变化，请刷新后重试")
            after_state = {
                "properties": updated_properties,
                "version": target_version + 1,
            }
            await db.execute_query(
                "UPDATE ontology_action_run SET status = 'succeeded', after_state = :after_state, "
                "completed_at = CURRENT_TIMESTAMP WHERE id = :id",
                {"after_state": _json(after_state), "id": run_id},
            )
            return {
                "run_id": run_id,
                "status": "succeeded",
                "action": action["action_key"],
                "target_object_id": payload.target_object_id,
                "before_state": before_state,
                "after_state": after_state,
            }
        except Exception as exc:
            await db.execute_query(
                "UPDATE ontology_action_run SET status = 'failed', error_message = :error, "
                "completed_at = CURRENT_TIMESTAMP WHERE id = :id",
                {"error": str(exc)[:2000], "id": run_id},
            )
            raise

    async def list_action_runs(
        self, domain_id: int, *, user_id: int | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        await self._require_domain(domain_id)
        sql = (
            "SELECT r.*, a.action_key, a.name AS action_name, o.display_name AS target_name, "
            "u.display_name AS user_name, u.username "
            "FROM ontology_action_run r "
            "JOIN ontology_action_type a ON a.id = r.action_type_id "
            "LEFT JOIN ontology_object o ON o.id = r.target_object_id "
            "LEFT JOIN app_user u ON u.id = r.user_id "
            "WHERE r.domain_id = :domain_id"
        )
        params: dict[str, Any] = {"domain_id": domain_id, "limit": min(max(limit, 1), 500)}
        if user_id is not None:
            sql += " AND r.user_id = :user_id"
            params["user_id"] = user_id
        sql += " ORDER BY r.id DESC LIMIT :limit"
        rows = await get_management_db().execute_query(sql, params)
        return [_normalize_row(row) for row in rows]

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
            bundle["objects"] = await self.list_objects(domain_id)
            bundle["links"] = await self.list_links(domain_id)
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
            imported_objects[
                (object_key, object_identity(object_key, raw["primary_value"]))
            ] = object_id

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
