"""Pre-publish validation and read-only preview for Ontology object mappings.

The Ontology editor stores a source ``SELECT`` as a mapping contract.  This
service lets a modeler test that contract against the configured business
datasource before publishing a release or writing any twin objects.
"""

from __future__ import annotations

from typing import Any

from app.db.mysql import get_datasource_db
from app.models.ontology import OntologyObjectTypePayload
from app.services.ontology_service import (
    OntologyService,
    coerce_primary_value,
    get_ontology_service,
    property_definition,
    validate_synced_property_values,
)
from app.services.permission_service import (
    PermissionRuntimeContext,
    PermissionService,
    get_permission_service,
)
from app.utils.sql_validator import extract_table_references


class OntologyMappingPreviewService:
    """Run a bounded, non-mutating check for one object type mapping."""

    async def preview(
        self,
        payload: OntologyObjectTypePayload,
        *,
        access_agent_id: int | None = None,
    ) -> dict[str, Any]:
        ontology = get_ontology_service()
        domain = await ontology._require_domain(payload.domain_id)
        object_type = payload.model_dump()
        self._validate_object_definition(payload)

        if not payload.sync_enabled:
            raise ValueError("启用业务库同步后才能测试对象映射")
        source_query = str(payload.source_query or "").strip().rstrip(";")
        if not source_query:
            raise ValueError("测试对象映射时必须配置只读 SELECT")

        datasource_id = int(domain.get("datasource_id") or 0)
        if not datasource_id:
            raise ValueError("当前领域没有绑定默认数据源")

        permission_context = await ontology._load_object_permission_context(
            domain,
            access_agent_id,
        )
        self._require_configured_permission(permission_context)

        base_query = ontology._validated_source_query(source_query)
        source_tables = extract_table_references(base_query)
        if not source_tables:
            raise ValueError("对象映射 SQL 必须引用至少一张业务表")

        permission_service = get_permission_service()
        if isinstance(permission_context, PermissionRuntimeContext):
            allowed, reason = PermissionService.validate_sql_access_with_context(
                permission_context,
                base_query,
            )
            result_column_policies = PermissionService.resolve_result_column_policies(
                base_query,
                source_tables,
                permission_context.column_permissions,
            )
        else:
            allowed, reason = await permission_service.validate_sql_access(
                access_agent_id,
                datasource_id,
                base_query,
            )
            result_column_policies = await permission_service.get_result_column_policies(
                access_agent_id,
                datasource_id,
                base_query,
            )
        if not allowed:
            raise PermissionError(reason)

        link_types = await ontology.list_link_types(payload.domain_id)
        OntologyService._validate_sync_key_permissions(
            object_type,
            link_types,
            source_tables,
            permission_context[2],
            result_column_policies,
        )

        source_db = await get_datasource_db(datasource_id)
        statistics, statistics_warning = await self._read_statistics(
            source_db,
            base_query,
            payload.primary_property,
        )
        sample_limit = min(max(int(payload.sync_limit or 200), 1), 50)
        rows = await source_db.execute_query(
            f"{base_query}\nLIMIT :preview_limit",
            {"preview_limit": sample_limit},
        )
        columns = self._columns_from_rows(rows)
        properties = payload.properties
        expected_keys = [item.property_key for item in properties]
        expected_lower = {key.lower(): key for key in expected_keys}
        present_lower = {str(key).lower(): key for key in columns}
        missing = [
            self._property_summary(item)
            for item in properties
            if item.property_key.lower() not in present_lower
        ]
        mapped = [
            self._property_summary(item)
            for item in properties
            if item.property_key.lower() in present_lower
        ]
        unmapped_columns = [
            str(column)
            for column in columns
            if str(column).lower() not in expected_lower
        ]

        row_errors: list[dict[str, Any]] = []
        converted_rows: list[dict[str, Any]] = []
        primary_values: list[str] = []
        for row_number, row in enumerate(rows, start=1):
            mapped_row = self._map_row(row, expected_lower)
            raw_primary = mapped_row.get(payload.primary_property)
            if self._is_empty_primary(raw_primary):
                row_errors.append(
                    {
                        "row": row_number,
                        "code": "empty_primary",
                        "message": f"第 {row_number} 行主属性 {payload.primary_property} 为空",
                    }
                )
                continue
            try:
                converted = validate_synced_property_values(
                    [item.model_dump() for item in properties],
                    mapped_row,
                )
                converted[payload.primary_property] = coerce_primary_value(
                    property_definition(
                        [item.model_dump() for item in properties],
                        payload.primary_property,
                    ),
                    converted.get(payload.primary_property),
                )
                converted_rows.append(converted)
                primary_values.append(self._identity_value(converted[payload.primary_property]))
            except (TypeError, ValueError) as exc:
                row_errors.append(
                    {
                        "row": row_number,
                        "code": "type_conversion",
                        "message": str(exc),
                    }
                )

        duplicate_sample_count = len(primary_values) - len(set(primary_values))
        if isinstance(permission_context, PermissionRuntimeContext):
            safe_rows, masked_columns = PermissionService.mask_rows_with_context(
                permission_context,
                converted_rows,
                result_column_policies=result_column_policies,
            )
        else:
            safe_rows, masked_columns = await permission_service.mask_rows(
                access_agent_id,
                datasource_id,
                converted_rows,
                result_column_policies=result_column_policies,
            )

        errors: list[dict[str, Any]] = list(row_errors)
        warnings: list[dict[str, Any]] = []
        if statistics_warning:
            warnings.append(statistics_warning)
        if not rows:
            warnings.append(
                {
                    "code": "no_sample_rows",
                    "message": "查询没有返回样例数据，暂时无法从结果行确认列名和类型。",
                }
            )
        for item in missing:
            if item["required"]:
                errors.append(
                    {
                        "code": "missing_required_property",
                        "property_key": item["property_key"],
                        "message": f"查询结果缺少必填属性列: {item['property_key']}",
                    }
                )
            else:
                warnings.append(
                    {
                        "code": "missing_optional_property",
                        "property_key": item["property_key"],
                        "message": (
                            f"查询结果未返回可选属性列 {item['property_key']}，"
                            + (
                                "将使用默认值。"
                                if item["has_default"]
                                else "对象属性将保持为空。"
                            )
                        ),
                    }
                )
        if unmapped_columns:
            warnings.append(
                {
                    "code": "unmapped_columns",
                    "columns": unmapped_columns,
                    "message": "查询返回了未映射到对象属性的列: " + "、".join(unmapped_columns),
                }
            )
        if duplicate_sample_count:
            warnings.append(
                {
                    "code": "duplicate_sample_primary",
                    "message": f"样例数据中发现 {duplicate_sample_count} 条重复主属性记录。",
                }
            )

        empty_primary_rows = int(statistics.get("empty_primary_rows") or 0)
        duplicate_primary_rows = statistics.get("duplicate_primary_rows")
        if empty_primary_rows:
            errors.append(
                {
                    "code": "empty_primary_values",
                    "message": f"数据中有 {empty_primary_rows} 条记录的主属性为空。",
                }
            )
        if duplicate_primary_rows:
            errors.append(
                {
                    "code": "duplicate_primary_values",
                    "message": f"数据中有 {duplicate_primary_rows} 条重复主属性记录。",
                }
            )
        if not statistics.get("available"):
            warnings.append(
                {
                    "code": "statistics_unavailable",
                    "message": "未能完整统计源数据数量和主属性唯一性，请核对数据源查询。",
                }
            )

        return {
            "valid": not errors,
            "domain_id": payload.domain_id,
            "datasource_id": datasource_id,
            "object_type_id": payload.id,
            "object_key": payload.object_key,
            "name": payload.name,
            "permission": self._permission_metadata(permission_context),
            "query": {
                "tables": source_tables,
                "columns": columns,
                "sample_limit": sample_limit,
            },
            "mapping": {
                "mapped": mapped,
                "missing": missing,
                "unmapped_columns": unmapped_columns,
            },
            "statistics": {
                **statistics,
                "sample_rows": len(rows),
                "valid_sample_rows": len(converted_rows),
                "sample_errors": len(row_errors),
            },
            "sample_rows": safe_rows,
            "masked_columns": masked_columns,
            "errors": errors,
            "warnings": warnings,
        }

    @staticmethod
    def _validate_object_definition(payload: OntologyObjectTypePayload) -> None:
        properties = payload.properties
        property_keys = [item.property_key for item in properties]
        if len(property_keys) != len(set(property_keys)):
            raise ValueError("对象属性标识不能重复")
        if payload.primary_property not in property_keys:
            raise ValueError("主属性必须是对象已定义的属性")
        if payload.display_property and payload.display_property not in property_keys:
            raise ValueError("显示属性必须是对象已定义的属性")

    @staticmethod
    def _require_configured_permission(permission_context: Any) -> None:
        if permission_context is None:
            raise PermissionError("对象映射预览缺少明确的数据权限主体")
        if isinstance(permission_context, PermissionRuntimeContext):
            if permission_context.source == "unconfigured":
                raise PermissionError("当前业务领域未配置数据权限")
            return
        if len(permission_context) < 2 or not permission_context[1]:
            raise PermissionError("当前业务领域未配置数据权限")

    async def _read_statistics(
        self,
        source_db: Any,
        base_query: str,
        primary_property: str,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        identifier = "`" + primary_property.replace("`", "``") + "`"
        statistics_sql = (
            "SELECT COUNT(*) AS total_rows, "
            f"SUM(CASE WHEN {identifier} IS NULL OR TRIM(CAST({identifier} AS CHAR)) = '' "
            "THEN 1 ELSE 0 END) AS empty_primary_rows, "
            f"COUNT(DISTINCT NULLIF(TRIM(CAST({identifier} AS CHAR)), '')) "
            "AS distinct_primary_rows "
            f"FROM ({base_query}) AS ontology_source"
        )
        try:
            rows = await source_db.execute_query(statistics_sql)
            row = rows[0] if rows else {}
            total = row.get("total_rows", row.get("count"))
            if total is None:
                raise ValueError("统计结果缺少 total_rows")
            total_rows = int(total or 0)
            empty_rows = int(row.get("empty_primary_rows") or 0)
            distinct_rows = row.get("distinct_primary_rows")
            duplicate_rows = (
                max(total_rows - empty_rows - int(distinct_rows), 0)
                if distinct_rows is not None
                else None
            )
            return (
                {
                    "available": True,
                    "total_rows": total_rows,
                    "empty_primary_rows": empty_rows,
                    "distinct_primary_rows": (
                        int(distinct_rows) if distinct_rows is not None else None
                    ),
                    "duplicate_primary_rows": duplicate_rows,
                },
                None,
            )
        except Exception as exc:  # pragma: no cover - driver-specific SQL errors
            return (
                {
                    "available": False,
                    "total_rows": None,
                    "empty_primary_rows": 0,
                    "distinct_primary_rows": None,
                    "duplicate_primary_rows": None,
                },
                {
                    "code": "statistics_query_failed",
                    "message": f"主属性和数量统计失败: {exc}",
                },
            )

    @staticmethod
    def _columns_from_rows(rows: list[dict[str, Any]]) -> list[str]:
        columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                normalized = str(key).lower()
                if normalized in seen:
                    continue
                seen.add(normalized)
                columns.append(str(key))
        return columns

    @staticmethod
    def _map_row(row: dict[str, Any], expected_lower: dict[str, str]) -> dict[str, Any]:
        actual = {str(key).lower(): value for key, value in row.items()}
        return {
            property_key: actual[column_key]
            for column_key, property_key in expected_lower.items()
            if column_key in actual
        }

    @staticmethod
    def _property_summary(property_: Any) -> dict[str, Any]:
        return {
            "property_key": property_.property_key,
            "name": property_.name,
            "data_type": property_.data_type,
            "required": bool(property_.required),
            "has_default": property_.default_value is not None,
        }

    @staticmethod
    def _is_empty_primary(value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    @staticmethod
    def _identity_value(value: Any) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    @staticmethod
    def _permission_metadata(permission_context: Any) -> dict[str, Any] | None:
        if isinstance(permission_context, PermissionRuntimeContext):
            return permission_context.metadata()
        return None


_service: OntologyMappingPreviewService | None = None


def get_ontology_mapping_preview_service() -> OntologyMappingPreviewService:
    global _service
    if _service is None:
        _service = OntologyMappingPreviewService()
    return _service
