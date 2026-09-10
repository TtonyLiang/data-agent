"""Persistence helpers for observable twin synchronization runs."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from app.db.mysql import get_datasource_db, get_management_db
from app.services.datasource_service import get_datasource_service
from app.services.decision_audit_service import canonical_sha256
from app.services.model_release_service import get_model_release_service
from app.services.ontology_service import (
    OntologyService,
    _content_hash,
    coerce_primary_value,
    get_ontology_service,
    property_definition,
    validate_property_values,
    validate_synced_property_values,
)
from app.services.permission_service import (
    PermissionRuntimeContext,
    PermissionService,
    get_permission_service,
)
from app.services.semantic_runtime import get_semantic_runtime_service
from app.utils.sql_validator import extract_table_references

logger = logging.getLogger(__name__)
STALE_RUNNING_SECONDS = 30 * 60


class TwinRuntimeService:
    async def execute_sync(
        self,
        *,
        domain_id: int,
        access_agent_id: int | None,
        created_by: int | None,
        object_type_id: int | None,
        page: int,
        page_size: int | None,
        sync_links: bool,
        dry_run: bool,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        domain = await get_semantic_runtime_service().get_domain(domain_id)
        if domain is None:
            raise ValueError("业务领域不存在")
        if str(getattr(domain, "status", "active") or "active").lower() != "active":
            raise ValueError("业务领域已停用，不能运行数据孪生")
        datasource_id = int(domain.datasource_id or 0)
        if not datasource_id:
            raise ValueError("当前领域没有绑定默认数据源")
        permission_context = (
            await get_permission_service().resolve_domain_permission_context(
                domain_id,
                datasource_id,
                compatibility_agent_id=access_agent_id,
                allow_agent_fallback=bool(access_agent_id),
            )
        )
        if permission_context.source == "unconfigured":
            raise PermissionError("当前业务领域未配置数据权限")
        if permission_context.source == "agent_compatibility" and (
            not access_agent_id
            or not await get_datasource_service().belongs_to_agent(
                datasource_id, access_agent_id
            )
        ):
            raise PermissionError("兼容权限智能体无权访问领域数据源")
        release_lineage = await self._validated_active_release(
            domain_id,
            datasource_id=datasource_id,
        )
        release_definition = release_lineage["ontology_definition"]
        release_metadata = {
            key: value
            for key, value in release_lineage.items()
            if key != "ontology_definition"
        }
        created = await self.create_run(
            domain_id=domain_id,
            datasource_id=datasource_id,
            object_type_id=object_type_id,
            model_release_id=int(release_lineage["id"]),
            release_lineage=release_metadata,
            caller_agent_id=access_agent_id,
            created_by=created_by,
            page=page,
            page_size=page_size or 200,
            sync_links=sync_links,
            dry_run=dry_run,
            trace_id=trace_id,
            trigger_type="preview" if dry_run else "manual",
        )
        run_id = int(created["id"])
        try:
            if dry_run:
                result = await self.preview_sync(
                    domain_id=domain_id,
                    access_agent_id=access_agent_id,
                    object_type_id=object_type_id,
                    page=page,
                    page_size=page_size,
                    release_definition=release_definition,
                )
            else:
                ontology = get_ontology_service()
                result = await ontology.sync_objects_from_datasource(
                    domain_id,
                    access_agent_id=access_agent_id,
                    object_type_id=object_type_id,
                    page=page,
                    page_size=page_size,
                    sync_links=sync_links,
                    release_definition=release_definition,
                )
            status = self._run_status(result)
            error_summary = self._error_summary(result)
            await self.complete_run(
                run_id,
                status=status,
                statistics={
                    **self._statistics(result),
                    "permission": permission_context.metadata(),
                    "model_release": release_metadata,
                },
                error_summary=error_summary,
            )
        except Exception as exc:
            await self.complete_run(
                run_id,
                status="failed",
                statistics={
                    "dry_run": dry_run,
                    "permission": permission_context.metadata(),
                    "model_release": release_metadata,
                },
                error_summary=str(exc),
            )
            raise
        run = await self.get_run(domain_id, run_id)
        return {"run": run or created, "result": result}

    async def preview_sync(
        self,
        *,
        domain_id: int,
        access_agent_id: int | None,
        object_type_id: int | None,
        page: int,
        page_size: int | None,
        release_definition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        semantic_domain = await get_semantic_runtime_service().get_domain(domain_id)
        if semantic_domain is None:
            raise ValueError("业务领域不存在")
        if str(getattr(semantic_domain, "status", "active") or "active").lower() != "active":
            raise ValueError("业务领域已停用，不能预览数据孪生")
        datasource_id = int(semantic_domain.datasource_id or 0)
        if not datasource_id:
            raise ValueError("当前领域没有绑定默认数据源")
        ontology = get_ontology_service()
        permission_context = await ontology._load_object_permission_context(
            {"id": domain_id, "datasource_id": datasource_id},
            access_agent_id,
        )
        if permission_context is None:
            raise PermissionError("对象同步预览缺少明确的权限主体")
        if release_definition is None:
            object_types = await ontology.list_object_types(domain_id)
            link_types = await ontology.list_link_types(domain_id)
        else:
            scoped_definition = await ontology.prepare_release_sync_definition(
                domain_id,
                release_definition,
            )
            object_types = scoped_definition["object_types"]
            link_types = scoped_definition["link_types"]
        if object_type_id is not None:
            object_types = [
                item for item in object_types if int(item["id"]) == object_type_id
            ]
            if not object_types:
                raise ValueError("对象类型不存在或不属于当前领域")
        sync_types = [item for item in object_types if item.get("sync_enabled")]
        if not sync_types:
            raise ValueError("当前对象类型没有启用业务库同步")

        source_db = await get_datasource_db(datasource_id)
        permission_service = get_permission_service()
        page_number = max(int(page), 1)
        type_results: list[dict[str, Any]] = []
        total_rows = 0
        for object_type in sync_types:
            configured_limit = min(
                max(int(object_type.get("sync_limit") or 200), 1), 1000
            )
            effective_page_size = min(
                max(int(page_size or configured_limit), 1), 1000
            )
            result = {
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
                base_query = ontology._validated_source_query(
                    str(object_type.get("source_query") or "").strip().rstrip(";")
                )
                if isinstance(permission_context, PermissionRuntimeContext):
                    allowed, reason = PermissionService.validate_sql_access_with_context(
                        permission_context, base_query
                    )
                else:
                    allowed, reason = await permission_service.validate_sql_access(
                        access_agent_id, datasource_id, base_query
                    )
                if not allowed:
                    raise PermissionError(reason)
                source_tables = extract_table_references(base_query)
                result_column_policies = (
                    await permission_service.get_result_column_policies(
                        access_agent_id,
                        datasource_id,
                        base_query,
                    )
                )
                ontology._validate_sync_key_permissions(
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
                for row_index, row in enumerate(rows, start=offset + 1):
                    try:
                        preview, outcome = await self._preview_object(
                            ontology, domain_id, object_type, row
                        )
                        protected = ontology._protect_object_rows(
                            [
                                ontology._permission_metadata(
                                    {
                                        **preview,
                                        "properties": {},
                                        "source_properties": {},
                                        "overlay_properties": {},
                                        "source_kind": "database",
                                        "source_datasource_id": datasource_id,
                                    },
                                    object_type,
                                )
                            ],
                            permission_context,
                        )
                        if not protected:
                            raise PermissionError("当前权限主体无权预览该对象")
                        preview = {
                            **preview,
                            "primary_value": protected[0].get("primary_value"),
                            "display_name": protected[0].get("display_name"),
                        }
                        result[outcome] += 1
                        result["objects"].append(preview)
                    except (TypeError, ValueError) as exc:
                        result["skipped"] += 1
                        result["errors"].append(f"第 {row_index} 行: {exc}")
                result["total"] = total
                result["read"] = len(rows)
                total_rows += total
            except Exception as exc:
                result["errors"].append(str(exc))
            type_results.append(result)
        return {
            "domain_id": domain_id,
            "datasource_id": datasource_id,
            "permission": (
                permission_context.metadata()
                if isinstance(permission_context, PermissionRuntimeContext)
                else None
            ),
            "page": page_number,
            "dry_run": True,
            "types": type_results,
            "objects": [item for result in type_results for item in result["objects"]],
            "total": total_rows,
            "links_synced": 0,
            "has_errors": any(result["errors"] for result in type_results),
        }

    async def _preview_object(
        self,
        ontology: OntologyService,
        domain_id: int,
        object_type: dict[str, Any],
        row: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        definitions = object_type.get("properties") or []
        source_values = validate_synced_property_values(definitions, row)
        primary_key = str(object_type["primary_property"])
        primary_value = coerce_primary_value(
            property_definition(definitions, primary_key),
            source_values.get(primary_key),
        )
        source_values[primary_key] = primary_value
        existing_rows = await get_management_db().execute_query(
            "SELECT * FROM ontology_object WHERE domain_id = :domain_id "
            "AND object_type_id = :object_type_id AND primary_value = :primary_value",
            {
                "domain_id": domain_id,
                "object_type_id": int(object_type["id"]),
                "primary_value": str(primary_value),
            },
        )
        existing = ontology._protect_object_rows(existing_rows, None)[0] if existing_rows else None
        overlay = dict(existing.get("overlay_properties") or {}) if existing else {}
        overlay = {
            key: value for key, value in overlay.items() if source_values.get(key) != value
        }
        merged = validate_property_values(definitions, {**source_values, **overlay})
        display_key = object_type.get("display_property")
        display_name = (
            str(merged.get(display_key))
            if display_key and merged.get(display_key) is not None
            else str(primary_value)
        )
        if existing is None:
            outcome = "created"
        elif (
            existing.get("properties") != merged
            or existing.get("display_name") != display_name
            or existing.get("status") != "active"
        ):
            outcome = "updated"
        else:
            outcome = "unchanged"
        return (
            {
                "object_type_id": int(object_type["id"]),
                "object_type_key": object_type["object_key"],
                "primary_value": str(primary_value),
                "display_name": display_name,
                "outcome": outcome,
            },
            outcome,
        )

    async def create_run(
        self,
        *,
        domain_id: int,
        datasource_id: int,
        object_type_id: int | None,
        model_release_id: int | None,
        release_lineage: dict[str, Any] | None = None,
        caller_agent_id: int | None,
        created_by: int | None,
        page: int,
        page_size: int,
        sync_links: bool,
        dry_run: bool,
        trace_id: str | None = None,
        trigger_type: str = "manual",
    ) -> dict[str, Any]:
        normalized_trace = str(trace_id or f"sync_{uuid4().hex[:16]}")
        run_id = await get_management_db().execute_insert(
            "INSERT INTO twin_sync_run "
            "(domain_id, object_type_id, model_release_id, datasource_id, "
            "caller_agent_id, trace_id, trigger_type, dry_run, status, page, "
            "page_size, sync_links, statistics_json, created_by) VALUES "
            "(:domain_id, :object_type_id, :model_release_id, :datasource_id, "
            ":caller_agent_id, :trace_id, :trigger_type, :dry_run, 'running', "
            ":page, :page_size, :sync_links, :statistics_json, :created_by)",
            {
                "domain_id": domain_id,
                "object_type_id": object_type_id,
                "model_release_id": model_release_id,
                "datasource_id": datasource_id,
                "caller_agent_id": caller_agent_id,
                "trace_id": normalized_trace,
                "trigger_type": trigger_type,
                "dry_run": int(dry_run),
                "page": page,
                "page_size": page_size,
                "sync_links": int(sync_links),
                "statistics_json": json.dumps(
                    {"model_release": release_lineage} if release_lineage else {},
                    ensure_ascii=False,
                ),
                "created_by": created_by,
            },
        )
        return {
            "id": run_id,
            "trace_id": normalized_trace,
            "status": "running",
            "dry_run": dry_run,
        }

    async def complete_run(
        self,
        run_id: int,
        *,
        status: str,
        statistics: dict[str, Any],
        error_summary: str | None = None,
    ) -> None:
        if status not in {"succeeded", "partial", "failed"}:
            raise ValueError(f"无效同步状态: {status}")
        await get_management_db().execute_query(
            "UPDATE twin_sync_run SET status = :status, statistics_json = :statistics, "
            "error_summary = :error_summary, completed_at = CURRENT_TIMESTAMP "
            "WHERE id = :id",
            {
                "id": run_id,
                "status": status,
                "statistics": json.dumps(statistics, ensure_ascii=False, default=str),
                "error_summary": (error_summary or "")[:4000] or None,
            },
        )

    async def get_run(self, domain_id: int, run_id: int) -> dict[str, Any] | None:
        await self.normalize_stale_runs(domain_id)
        rows = await get_management_db().execute_query(
            "SELECT * FROM twin_sync_run WHERE id = :id AND domain_id = :domain_id",
            {"id": run_id, "domain_id": domain_id},
        )
        return self._normalize(rows[0]) if rows else None

    async def list_runs(self, domain_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        await self.normalize_stale_runs(domain_id)
        rows = await get_management_db().execute_query(
            "SELECT * FROM twin_sync_run WHERE domain_id = :domain_id "
            "ORDER BY id DESC LIMIT :limit",
            {"domain_id": domain_id, "limit": min(max(int(limit), 1), 200)},
        )
        return [self._normalize(row) for row in rows]

    async def normalize_stale_runs(self, domain_id: int) -> None:
        """Turn abandoned running rows into explicit failed terminal records."""
        await get_management_db().execute_query(
            "UPDATE twin_sync_run SET status = 'failed', "
            "error_summary = COALESCE(NULLIF(error_summary, ''), :error_summary), "
            "completed_at = CURRENT_TIMESTAMP WHERE domain_id = :domain_id "
            "AND status = 'running' AND started_at < "
            f"DATE_SUB(CURRENT_TIMESTAMP, INTERVAL {STALE_RUNNING_SECONDS} SECOND)",
            {
                "domain_id": domain_id,
                "error_summary": "同步进程中断或超过30分钟未完成，已自动归一为失败",
            },
        )

    async def _validated_active_release(
        self,
        domain_id: int,
        *,
        datasource_id: int,
    ) -> dict[str, Any]:
        """Load and validate the immutable active release used by sync."""
        release = await get_model_release_service().get_active_release(
            domain_id,
            required=True,
        )
        assert release is not None
        semantic_snapshot = await get_semantic_runtime_service().get_snapshot(
            domain_id,
            int(release["semantic_snapshot_id"]),
        )
        snapshot_payload = semantic_snapshot.get("snapshot_json") or {}
        semantic_hash = canonical_sha256(snapshot_payload)
        if semantic_hash != str(release.get("semantic_snapshot_hash") or ""):
            raise ValueError("激活企业模型关联的语义快照内容已变化，拒绝同步")
        snapshot_domain = (
            snapshot_payload.get("domain")
            if isinstance(snapshot_payload, dict)
            else None
        )
        snapshot_datasource_id = (
            snapshot_domain.get("datasource_id")
            if isinstance(snapshot_domain, dict)
            else None
        )
        try:
            release_datasource_id = int(snapshot_datasource_id or 0)
        except (TypeError, ValueError):
            release_datasource_id = 0
        if release_datasource_id != datasource_id:
            raise ValueError("当前数据源已偏离激活企业模型版本，请重新生成快照并发布")

        rows = await get_management_db().execute_query(
            "SELECT id, definition_json, definition_hash FROM ontology_release "
            "WHERE id = :release_id AND domain_id = :domain_id",
            {
                "release_id": int(release["ontology_release_id"]),
                "domain_id": domain_id,
            },
        )
        if not rows:
            raise ValueError("激活企业模型关联的 Ontology 发布不存在，拒绝同步")
        stored_definition = rows[0].get("definition_json") or {}
        if isinstance(stored_definition, str):
            try:
                stored_definition = json.loads(stored_definition)
            except json.JSONDecodeError as exc:
                raise ValueError("Ontology 发布定义无法校验，拒绝同步") from exc
        if not isinstance(stored_definition, dict):
            raise ValueError("Ontology 发布定义无效，拒绝同步")
        actual_ontology_hash = _content_hash(stored_definition)
        stored_ontology_hash = str(rows[0].get("definition_hash") or "")
        expected_ontology_hash = str(release.get("ontology_definition_hash") or "")
        if stored_ontology_hash and stored_ontology_hash != actual_ontology_hash:
            raise ValueError("激活企业模型关联的 Ontology 发布内容已变化，拒绝同步")
        if not expected_ontology_hash or actual_ontology_hash != expected_ontology_hash:
            raise ValueError("激活企业模型关联的 Ontology 发布内容哈希校验失败，拒绝同步")

        model_hash = canonical_sha256(
            {
                "format": "wenqu-enterprise-model-release/v1",
                "semantic_snapshot_hash": semantic_hash,
                "ontology_definition_hash": expected_ontology_hash,
            }
        )
        if model_hash != str(release.get("model_hash") or ""):
            raise ValueError("激活企业模型版本哈希校验失败，拒绝同步")
        return {
            "id": int(release["id"]),
            "version": int(release["version"]),
            "model_hash": model_hash,
            "semantic_snapshot_id": int(release["semantic_snapshot_id"]),
            "semantic_snapshot_hash": semantic_hash,
            "ontology_release_id": int(release["ontology_release_id"]),
            "ontology_definition_hash": expected_ontology_hash,
            "definition_mode": "active_release_immutable",
            "datasource_id": datasource_id,
            "ontology_definition": stored_definition,
        }

    @classmethod
    def _run_status(cls, result: dict[str, Any]) -> str:
        types = result.get("types") or []
        if types and all(cls._object_type_failed(item) for item in types):
            return "failed"
        if not types and result.get("has_errors"):
            return "failed"
        if result.get("has_errors") or result.get("relationship_errors"):
            return "partial"
        return "succeeded"

    @staticmethod
    def _object_type_failed(item: dict[str, Any]) -> bool:
        processed = sum(
            int(item.get(key) or 0)
            for key in ("created", "updated", "unchanged")
        )
        return bool(item.get("errors")) and int(item.get("read") or 0) == 0 and not processed

    @staticmethod
    def _statistics(result: dict[str, Any]) -> dict[str, Any]:
        totals = {
            "read": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped": 0,
            "errors": 0,
            "links_synced": int(result.get("links_synced") or 0),
            "dry_run": bool(result.get("dry_run")),
            "object_types": len(result.get("types") or []),
            "failed_object_types": 0,
            "relationship_errors": len(result.get("relationship_errors") or []),
        }
        for item in result.get("types") or []:
            for key in ("read", "created", "updated", "unchanged", "skipped"):
                totals[key] += int(item.get(key) or 0)
            totals["errors"] += len(item.get("errors") or [])
            if TwinRuntimeService._object_type_failed(item):
                totals["failed_object_types"] += 1
        return totals

    @staticmethod
    def _error_summary(result: dict[str, Any]) -> str | None:
        errors = [
            str(error)
            for item in result.get("types") or []
            for error in item.get("errors") or []
        ]
        errors.extend(str(error) for error in result.get("relationship_errors") or [])
        return "；".join(errors[:10]) or None

    @staticmethod
    def _normalize(row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        raw_statistics = normalized.get("statistics_json")
        if isinstance(raw_statistics, str):
            try:
                normalized["statistics_json"] = json.loads(raw_statistics)
            except json.JSONDecodeError:
                normalized["statistics_json"] = {}
        elif not isinstance(raw_statistics, dict):
            normalized["statistics_json"] = {}
        normalized["dry_run"] = bool(normalized.get("dry_run"))
        normalized["sync_links"] = bool(normalized.get("sync_links"))
        return normalized


_service: TwinRuntimeService | None = None


def get_twin_runtime_service() -> TwinRuntimeService:
    global _service
    if _service is None:
        _service = TwinRuntimeService()
    return _service
