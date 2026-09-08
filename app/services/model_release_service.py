"""Lifecycle service for unified enterprise model releases.

A release binds one immutable semantic snapshot to one immutable Ontology
release. Runtime consumers are intentionally not changed here; this service is
the management foundation for selecting a stable model version later.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db.mysql import get_management_db
from app.models.knowledge import SemanticRuntime
from app.models.model_release import (
    EnterpriseModelReleaseCreatePayload,
    EnterpriseModelValidationPayload,
)
from app.models.ontology import (
    OntologyActionTypePayload,
    OntologyLinkTypePayload,
    OntologyObjectTypePayload,
)
from app.services.decision_audit_service import canonical_sha256
from app.services.query_context import build_query_context


class ModelReleaseNotFound(ValueError):
    pass


class ModelReleaseConflict(ValueError):
    pass


RELEASE_COLUMNS = (
    "id, domain_id, version, name, description, semantic_snapshot_id, "
    "ontology_release_id, status, semantic_snapshot_hash, "
    "ontology_definition_hash, model_hash, validation_json, created_by, "
    "validated_by, activated_by, retired_by, previous_active_release_id, "
    "validated_at, activated_at, retired_at, created_at, updated_at"
)
COMPONENT_HASH_FIELDS = (
    "semantic_snapshot_hash",
    "ontology_definition_hash",
    "model_hash",
)


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


def normalize_model_release(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["validation"] = _loads(normalized.pop("validation_json", None), None)
    return normalized


def _first(result: Any) -> dict[str, Any] | None:
    row = result.mappings().first()
    return dict(row) if row is not None else None


def _validate_component_payloads(
    domain_id: int,
    semantic_snapshot: Any,
    ontology_definition: Any,
) -> dict[str, Any]:
    """Validate the immutable semantic and Ontology payloads bound to a release."""
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    runtime: SemanticRuntime | None = None

    if not isinstance(semantic_snapshot, dict):
        errors.append("语义资产快照格式无效")
    else:
        snapshot_domain = semantic_snapshot.get("domain")
        assets = semantic_snapshot.get("assets")
        if not isinstance(snapshot_domain, dict) or not isinstance(assets, dict):
            errors.append("语义资产快照缺少 domain 或 assets")
        else:
            snapshot_domain_id = snapshot_domain.get("id")
            if snapshot_domain_id is not None:
                try:
                    belongs_to_domain = int(snapshot_domain_id) == domain_id
                except (TypeError, ValueError):
                    belongs_to_domain = False
                if not belongs_to_domain:
                    errors.append("语义资产快照内容不属于当前业务领域")
            try:
                runtime = SemanticRuntime.model_validate(
                    {
                        "domain": snapshot_domain,
                        "concepts": assets.get("concept") or [],
                        "relations": assets.get("relation") or [],
                        "metrics": assets.get("metric") or [],
                        "rules": assets.get("rule") or [],
                        "mappings": assets.get("mapping") or [],
                        "templates": assets.get("template") or [],
                    }
                )
            except Exception as exc:
                errors.append(f"语义资产快照无法构建运行时: {exc}")
            else:
                semantic_assets = [
                    *runtime.concepts,
                    *runtime.relations,
                    *runtime.metrics,
                    *runtime.rules,
                    *runtime.mappings,
                    *runtime.templates,
                ]
                if any(int(item.domain_id) != domain_id for item in semantic_assets):
                    errors.append("语义资产快照包含其他业务领域的资产")
                mapping_keys = {item.asset_key for item in runtime.mappings}
                for mapping in runtime.mappings:
                    if not mapping.column_name and not mapping.expression_sql:
                        errors.append(f"语义映射 {mapping.asset_key} 缺少字段或表达式")
                for metric in runtime.metrics:
                    missing_dimensions = [
                        item for item in metric.dimensions if item not in mapping_keys
                    ]
                    if missing_dimensions:
                        errors.append(
                            f"指标 {metric.metric_key} 缺少维度映射: "
                            + "、".join(missing_dimensions)
                        )
                checks["semantic_snapshot"] = {
                    "parsed": True,
                    "metrics": len(runtime.metrics),
                    "mappings": len(runtime.mappings),
                }

    object_types: list[dict[str, Any]] = []
    link_types: list[dict[str, Any]] = []
    action_types: list[dict[str, Any]] = []
    ontology_domain: dict[str, Any] = {}
    if not isinstance(ontology_definition, dict):
        errors.append("Ontology 发布定义格式无效")
    else:
        ontology_domain = ontology_definition.get("domain") or {}
        raw_objects = ontology_definition.get("object_types")
        raw_links = ontology_definition.get("link_types")
        raw_actions = ontology_definition.get("action_types")
        if not isinstance(ontology_domain, dict) or not all(
            isinstance(items, list) for items in (raw_objects, raw_links, raw_actions)
        ):
            errors.append("Ontology 发布定义缺少对象、关系或动作列表")
        else:
            for label, raw_items, model in (
                ("对象", raw_objects, OntologyObjectTypePayload),
                ("关系", raw_links, OntologyLinkTypePayload),
                ("动作", raw_actions, OntologyActionTypePayload),
            ):
                for index, item in enumerate(raw_items, start=1):
                    if not isinstance(item, dict):
                        errors.append(f"Ontology {label} #{index} 格式无效")
                        continue
                    try:
                        normalized = model.model_validate(
                            {**item, "domain_id": domain_id}
                        ).model_dump(mode="python")
                    except Exception as exc:
                        errors.append(f"Ontology {label} #{index} 定义无效: {exc}")
                        continue
                    if label == "对象":
                        object_types.append(normalized)
                    elif label == "关系":
                        link_types.append(normalized)
                    else:
                        action_types.append(normalized)

            active_objects = {
                item["object_key"]: item
                for item in object_types
                if item.get("status") == "active"
            }
            if not active_objects:
                errors.append("Ontology 发布至少需要一个生效对象")
            if len({item["object_key"] for item in object_types}) != len(object_types):
                errors.append("Ontology 发布包含重复对象标识")
            for item in object_types:
                properties = item.get("properties") or []
                property_keys = [prop.get("property_key") for prop in properties]
                if not property_keys:
                    errors.append(f"对象 {item['object_key']} 至少需要一个属性")
                    continue
                if len(set(property_keys)) != len(property_keys):
                    errors.append(f"对象 {item['object_key']} 包含重复属性标识")
                if item.get("primary_property") not in property_keys:
                    errors.append(f"对象 {item['object_key']} 的主属性不存在")
                if (
                    item.get("display_property")
                    and item.get("display_property") not in property_keys
                ):
                    errors.append(f"对象 {item['object_key']} 的显示属性不存在")
            for item in link_types:
                if item.get("status") != "active":
                    continue
                source = active_objects.get(item.get("source_object_key"))
                target = active_objects.get(item.get("target_object_key"))
                if source is None or target is None:
                    errors.append(f"关系 {item['link_key']} 引用了未生效或不存在的对象")
                    continue
                source_keys = {
                    prop.get("property_key") for prop in source.get("properties") or []
                }
                target_keys = {
                    prop.get("property_key") for prop in target.get("properties") or []
                }
                source_relation_keys = list(
                    item.get("source_property_keys")
                    or [item.get("source_property")]
                )
                target_relation_keys = list(
                    item.get("target_property_keys")
                    or [item.get("target_property")]
                )
                if len(source_relation_keys) != len(target_relation_keys):
                    errors.append(f"关系 {item['link_key']} 的两端复合属性数量不一致")
                    continue
                missing_source = [
                    key for key in source_relation_keys if key not in source_keys
                ]
                missing_target = [
                    key for key in target_relation_keys if key not in target_keys
                ]
                if missing_source:
                    errors.append(
                        f"关系 {item['link_key']} 的起点属性不存在: "
                        + "、".join(str(key) for key in missing_source)
                    )
                if missing_target:
                    errors.append(
                        f"关系 {item['link_key']} 的终点属性不存在: "
                        + "、".join(str(key) for key in missing_target)
                    )
            for item in action_types:
                if item.get("status") != "active":
                    continue
                target = active_objects.get(item.get("target_object_key"))
                if target is None:
                    errors.append(f"动作 {item['action_key']} 引用了未生效或不存在的对象")
                    continue
                property_keys = {
                    prop.get("property_key") for prop in target.get("properties") or []
                }
                if not item.get("effects"):
                    errors.append(f"动作 {item['action_key']} 至少需要一个状态效果")
                for condition in item.get("preconditions") or []:
                    if condition.get("property") not in property_keys:
                        errors.append(f"动作 {item['action_key']} 的前置条件属性不存在")
                for effect in item.get("effects") or []:
                    if effect.get("property") not in property_keys:
                        errors.append(f"动作 {item['action_key']} 的效果属性不存在")
                    if effect.get("property") == target.get("primary_property"):
                        errors.append(f"动作 {item['action_key']} 不能修改对象主标识")
            checks["ontology_release"] = {
                "parsed": True,
                "object_types": len(object_types),
                "link_types": len(link_types),
                "action_types": len(action_types),
            }

    if runtime is not None and object_types:
        if ontology_domain.get("domain_key") and (
            str(ontology_domain.get("domain_key")) != runtime.domain.domain_key
        ):
            errors.append("语义快照与 Ontology 发布的业务领域标识不一致")
        active_object_keys = {
            item["object_key"]
            for item in object_types
            if item.get("status") == "active"
        }
        for metric in runtime.metrics:
            metadata = metric.metadata or {}
            declared = metadata.get("object_key") or metadata.get("object_type_key")
            if declared and str(declared) not in active_object_keys:
                errors.append(
                    f"指标 {metric.metric_key} 关联的本体对象 {declared} 不存在或未生效"
                )
        query_context = build_query_context(
            "",
            runtime,
            {
                "domain": ontology_domain,
                "object_types": [
                    item for item in object_types if item.get("status") == "active"
                ],
                "link_types": [
                    item for item in link_types if item.get("status") == "active"
                ],
                "actions": [
                    item for item in action_types if item.get("status") == "active"
                ],
            },
        )
        warnings.extend(
            str(item.get("message") or "")
            for item in query_context.get("warnings") or []
            if isinstance(item, dict) and item.get("message")
        )
        bridge = query_context.get("bridge") or {}
        bridge_errors = (
            bridge.get("errors") or [] if isinstance(bridge, dict) else []
        )
        errors.extend(
            str(item.get("message") or "")
            for item in bridge_errors
            if isinstance(item, dict) and item.get("message")
        )
        checks["ontology_semantic_bridge"] = {
            "valid": not bridge_errors,
            "relation_binding_errors": len(bridge_errors),
            "query_capabilities": len(query_context.get("query_capabilities") or []),
        }

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


class ModelReleaseService:
    async def get_active_release(
        self, domain_id: int, *, required: bool = False
    ) -> dict[str, Any] | None:
        """Return the domain's single active enterprise model release."""
        await self._require_domain(domain_id)
        rows = await get_management_db().execute_query(
            f"SELECT {RELEASE_COLUMNS} FROM enterprise_model_release "
            "WHERE domain_id = :domain_id AND status = 'active' LIMIT 1",
            {"domain_id": domain_id},
        )
        if rows:
            return normalize_model_release(rows[0])
        if required:
            raise ModelReleaseConflict("当前业务领域没有激活的企业模型版本")
        return None

    async def list_releases(self, domain_id: int) -> list[dict[str, Any]]:
        await self._require_domain(domain_id)
        rows = await get_management_db().execute_query(
            f"SELECT {RELEASE_COLUMNS} FROM enterprise_model_release "
            "WHERE domain_id = :domain_id ORDER BY version DESC",
            {"domain_id": domain_id},
        )
        return [normalize_model_release(row) for row in rows]

    async def get_release(self, domain_id: int, release_id: int) -> dict[str, Any]:
        rows = await get_management_db().execute_query(
            f"SELECT {RELEASE_COLUMNS} FROM enterprise_model_release "
            "WHERE domain_id = :domain_id AND id = :release_id",
            {"domain_id": domain_id, "release_id": release_id},
        )
        if not rows:
            raise ModelReleaseNotFound("企业模型版本不存在")
        return normalize_model_release(rows[0])

    async def create_draft(
        self,
        domain_id: int,
        payload: EnterpriseModelReleaseCreatePayload,
        created_by: int,
    ) -> dict[str, Any]:
        async def callback(session: Any) -> int:
            await self._lock_domain(session, domain_id)
            components = await self._load_components(
                session,
                domain_id,
                payload.semantic_snapshot_id,
                payload.ontology_release_id,
            )
            if not components["ontology_release_hash_valid"]:
                raise ModelReleaseConflict("Ontology 发布定义内容哈希与发布记录不一致")
            duplicate = _first(
                await session.execute(
                    text(
                        "SELECT id FROM enterprise_model_release "
                        "WHERE domain_id = :domain_id "
                        "AND semantic_snapshot_id = :semantic_snapshot_id "
                        "AND ontology_release_id = :ontology_release_id FOR UPDATE"
                    ),
                    {
                        "domain_id": domain_id,
                        "semantic_snapshot_id": payload.semantic_snapshot_id,
                        "ontology_release_id": payload.ontology_release_id,
                    },
                )
            )
            if duplicate is not None:
                raise ModelReleaseConflict("相同语义快照和 Ontology 版本已建立发布记录")
            version_row = _first(
                await session.execute(
                    text(
                        "SELECT COALESCE(MAX(version), 0) AS version "
                        "FROM enterprise_model_release WHERE domain_id = :domain_id"
                    ),
                    {"domain_id": domain_id},
                )
            )
            version = int(version_row["version"] if version_row else 0) + 1
            inserted = await session.execute(
                text(
                    "INSERT INTO enterprise_model_release "
                    "(domain_id, version, name, description, semantic_snapshot_id, "
                    "ontology_release_id, status, semantic_snapshot_hash, "
                    "ontology_definition_hash, model_hash, created_by) VALUES "
                    "(:domain_id, :version, :name, :description, :semantic_snapshot_id, "
                    ":ontology_release_id, 'draft', :semantic_snapshot_hash, "
                    ":ontology_definition_hash, :model_hash, :created_by)"
                ),
                {
                    "domain_id": domain_id,
                    "version": version,
                    "name": payload.name or f"V{version}",
                    "description": payload.description,
                    "semantic_snapshot_id": payload.semantic_snapshot_id,
                    "ontology_release_id": payload.ontology_release_id,
                    "semantic_snapshot_hash": components["semantic_snapshot_hash"],
                    "ontology_definition_hash": components["ontology_definition_hash"],
                    "model_hash": components["model_hash"],
                    "created_by": created_by,
                },
            )
            return int(inserted.lastrowid or 0)

        release_id = await get_management_db().execute_in_transaction(callback)
        return await self.get_release(domain_id, release_id)

    async def validate_release(
        self,
        domain_id: int,
        release_id: int,
        payload: EnterpriseModelValidationPayload,
        validated_by: int,
    ) -> dict[str, Any]:
        async def callback(session: Any) -> None:
            await self._lock_domain(session, domain_id)
            release = await self._load_release(session, domain_id, release_id)
            if release["status"] not in {"draft", "validated"}:
                raise ModelReleaseConflict(f"状态 {release['status']} 的企业模型版本不能重新校验")
            components = await self._load_components(
                session,
                domain_id,
                int(release["semantic_snapshot_id"]),
                int(release["ontology_release_id"]),
            )
            integrity_errors = []
            if not components["ontology_release_hash_valid"]:
                integrity_errors.append("Ontology 发布定义内容哈希与发布记录不一致")
            component_hashes = {
                field: components[field] for field in COMPONENT_HASH_FIELDS
            }
            for field, label in (
                ("semantic_snapshot_hash", "语义资产快照"),
                ("ontology_definition_hash", "Ontology 发布定义"),
                ("model_hash", "统一企业模型"),
            ):
                if str(release.get(field) or "") != component_hashes[field]:
                    integrity_errors.append(f"{label}内容哈希与草稿创建时不一致")
            server_validation = _validate_component_payloads(
                domain_id,
                components["semantic_snapshot"],
                components["ontology_definition"],
            )
            errors = integrity_errors + list(server_validation["errors"]) + [
                str(item).strip() for item in payload.errors if str(item).strip()
            ]
            warnings = list(server_validation["warnings"]) + [
                str(item).strip() for item in payload.warnings if str(item).strip()
            ]
            validation = {
                "valid": not errors,
                "errors": errors,
                "warnings": warnings,
                "checks": {
                    **server_validation["checks"],
                    "component_integrity": {"valid": not integrity_errors},
                    "client_checks": payload.checks,
                },
                "components": {
                    "semantic_snapshot_id": int(release["semantic_snapshot_id"]),
                    "ontology_release_id": int(release["ontology_release_id"]),
                    **component_hashes,
                },
            }
            status = "validated" if validation["valid"] else "draft"
            await session.execute(
                text(
                    "UPDATE enterprise_model_release SET status = :status, "
                    "validation_json = :validation_json, "
                    "validated_by = :validated_by, "
                    "validated_at = CURRENT_TIMESTAMP WHERE id = :release_id"
                ),
                {
                    "release_id": release_id,
                    "status": status,
                    "validation_json": json.dumps(validation, ensure_ascii=False),
                    "validated_by": validated_by,
                },
            )

        await get_management_db().execute_in_transaction(callback)
        return await self.get_release(domain_id, release_id)

    async def activate_release(
        self, domain_id: int, release_id: int, activated_by: int
    ) -> dict[str, Any]:
        await self._activate(
            domain_id,
            release_id,
            activated_by,
            allowed_statuses={"validated"},
            action_name="激活",
        )
        return await self.get_release(domain_id, release_id)

    async def deactivate_release(
        self, domain_id: int, release_id: int, retired_by: int
    ) -> dict[str, Any]:
        async def callback(session: Any) -> None:
            await self._lock_domain(session, domain_id)
            release = await self._load_release(session, domain_id, release_id)
            if release["status"] == "retired":
                return
            if release["status"] != "active":
                raise ModelReleaseConflict(f"状态 {release['status']} 的企业模型版本不能停用")
            await session.execute(
                text(
                    "UPDATE enterprise_model_release SET status = 'retired', "
                    "retired_by = :retired_by, retired_at = CURRENT_TIMESTAMP "
                    "WHERE id = :release_id"
                ),
                {"release_id": release_id, "retired_by": retired_by},
            )

        await get_management_db().execute_in_transaction(callback)
        return await self.get_release(domain_id, release_id)

    async def rollback_release(
        self, domain_id: int, release_id: int, activated_by: int
    ) -> dict[str, Any]:
        await self._activate(
            domain_id,
            release_id,
            activated_by,
            allowed_statuses={"retired"},
            action_name="回滚",
        )
        return await self.get_release(domain_id, release_id)

    async def _activate(
        self,
        domain_id: int,
        release_id: int,
        actor_id: int,
        *,
        allowed_statuses: set[str],
        action_name: str,
    ) -> None:
        async def callback(session: Any) -> None:
            await self._lock_domain(session, domain_id)
            release = await self._load_release(session, domain_id, release_id)
            if release["status"] == "active":
                return
            if release["status"] not in allowed_statuses:
                raise ModelReleaseConflict(
                    f"状态 {release['status']} 的企业模型版本不能{action_name}"
                )
            validation = _loads(release.get("validation_json"), {})
            if not isinstance(validation, dict) or validation.get("valid") is not True:
                raise ModelReleaseConflict("企业模型版本尚未通过校验")
            components = await self._load_components(
                session,
                domain_id,
                int(release["semantic_snapshot_id"]),
                int(release["ontology_release_id"]),
            )
            if not components["ontology_release_hash_valid"]:
                raise ModelReleaseConflict("Ontology 发布定义内容哈希与发布记录不一致")
            for field, label in (
                ("semantic_snapshot_hash", "语义资产快照"),
                ("ontology_definition_hash", "Ontology 发布定义"),
                ("model_hash", "统一企业模型"),
            ):
                if str(release.get(field) or "") != components[field]:
                    raise ModelReleaseConflict(f"{label}内容哈希与已校验版本不一致")
            active = _first(
                await session.execute(
                    text(
                        f"SELECT {RELEASE_COLUMNS} FROM enterprise_model_release "
                        "WHERE domain_id = :domain_id AND status = 'active' FOR UPDATE"
                    ),
                    {"domain_id": domain_id},
                )
            )
            previous_active_id = int(active["id"]) if active else None
            if active and previous_active_id != release_id:
                await session.execute(
                    text(
                        "UPDATE enterprise_model_release SET status = 'retired', "
                        "retired_by = :actor_id, retired_at = CURRENT_TIMESTAMP "
                        "WHERE id = :active_release_id"
                    ),
                    {"active_release_id": previous_active_id, "actor_id": actor_id},
                )
            await session.execute(
                text(
                    "UPDATE enterprise_model_release SET status = 'active', "
                    "activated_by = :actor_id, activated_at = CURRENT_TIMESTAMP, "
                    "retired_by = NULL, retired_at = NULL, "
                    "previous_active_release_id = :previous_active_release_id "
                    "WHERE id = :release_id"
                ),
                {
                    "release_id": release_id,
                    "actor_id": actor_id,
                    "previous_active_release_id": previous_active_id,
                },
            )

        await get_management_db().execute_in_transaction(callback)

    async def _require_domain(self, domain_id: int) -> None:
        rows = await get_management_db().execute_query(
            "SELECT id FROM semantic_domain WHERE id = :domain_id",
            {"domain_id": domain_id},
        )
        if not rows:
            raise ModelReleaseNotFound("业务领域不存在")

    async def _lock_domain(self, session: Any, domain_id: int) -> None:
        row = _first(
            await session.execute(
                text("SELECT id FROM semantic_domain WHERE id = :domain_id FOR UPDATE"),
                {"domain_id": domain_id},
            )
        )
        if row is None:
            raise ModelReleaseNotFound("业务领域不存在")

    async def _load_release(self, session: Any, domain_id: int, release_id: int) -> dict[str, Any]:
        row = _first(
            await session.execute(
                text(
                    f"SELECT {RELEASE_COLUMNS} FROM enterprise_model_release "
                    "WHERE domain_id = :domain_id AND id = :release_id FOR UPDATE"
                ),
                {"domain_id": domain_id, "release_id": release_id},
            )
        )
        if row is None:
            raise ModelReleaseNotFound("企业模型版本不存在")
        return row

    async def _load_components(
        self,
        session: Any,
        domain_id: int,
        semantic_snapshot_id: int,
        ontology_release_id: int,
    ) -> dict[str, Any]:
        snapshot = _first(
            await session.execute(
                text(
                    "SELECT id, domain_id, snapshot_json FROM semantic_domain_snapshot "
                    "WHERE id = :semantic_snapshot_id"
                ),
                {"semantic_snapshot_id": semantic_snapshot_id},
            )
        )
        if snapshot is None:
            raise ModelReleaseNotFound("语义资产快照不存在")
        if int(snapshot["domain_id"]) != domain_id:
            raise ModelReleaseConflict("语义资产快照不属于当前业务领域")
        ontology = _first(
            await session.execute(
                text(
                    "SELECT id, domain_id, definition_json, definition_hash "
                    "FROM ontology_release WHERE id = :ontology_release_id"
                ),
                {"ontology_release_id": ontology_release_id},
            )
        )
        if ontology is None:
            raise ModelReleaseNotFound("Ontology 发布版本不存在")
        if int(ontology["domain_id"]) != domain_id:
            raise ModelReleaseConflict("Ontology 发布版本不属于当前业务领域")
        semantic_snapshot = _loads(snapshot.get("snapshot_json"), {})
        ontology_definition = _loads(ontology.get("definition_json"), {})
        semantic_hash = canonical_sha256(semantic_snapshot)
        ontology_hash = canonical_sha256(ontology_definition)
        stored_ontology_hash = str(ontology.get("definition_hash") or "").strip()
        model_hash = canonical_sha256(
            {
                "format": "wenqu-enterprise-model-release/v1",
                "semantic_snapshot_hash": semantic_hash,
                "ontology_definition_hash": ontology_hash,
            }
        )
        return {
            "semantic_snapshot_hash": semantic_hash,
            "ontology_definition_hash": ontology_hash,
            "model_hash": model_hash,
            "ontology_release_hash_valid": (
                bool(stored_ontology_hash) and stored_ontology_hash == ontology_hash
            ),
            "semantic_snapshot": semantic_snapshot,
            "ontology_definition": ontology_definition,
        }


_service: ModelReleaseService | None = None


def get_model_release_service() -> ModelReleaseService:
    global _service
    if _service is None:
        _service = ModelReleaseService()
    return _service
