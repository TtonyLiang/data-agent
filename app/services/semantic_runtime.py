from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.db.mysql import get_management_db
from app.models.knowledge import (
    CompiledQuery,
    LogicForm,
    LogicFormTemplate,
    LogicFormValidation,
    SemanticConcept,
    SemanticDomain,
    SemanticMapping,
    SemanticMetric,
    SemanticRelation,
    SemanticRule,
    SemanticRuntime,
)
from app.utils.logging_helpers import json_for_log, truncate_text

logger = logging.getLogger(__name__)


JSON_FIELDS: dict[str, tuple[str, ...]] = {
    "concept": ("synonyms", "metadata"),
    "relation": ("join_path", "conditions", "metadata"),
    "metric": ("synonyms", "default_filters", "dimensions", "metadata"),
    "rule": ("expression", "applies_to"),
    "mapping": ("filters",),
    "template": ("required_slots", "optional_slots", "compile_strategy", "examples"),
}

ASSET_TABLES = {
    "concept": ("semantic_concept", "concept_key", SemanticConcept),
    "relation": ("semantic_relation", "relation_key", SemanticRelation),
    "metric": ("semantic_metric", "metric_key", SemanticMetric),
    "rule": ("semantic_rule", "rule_key", SemanticRule),
    "mapping": ("semantic_mapping", "asset_key", SemanticMapping),
    "template": ("logic_form_template", "template_key", LogicFormTemplate),
}

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_ASSET_KEY = re.compile(r"^[A-Za-z0-9_]+$")
SAFE_SQL_EXPR = re.compile(r"^[A-Za-z0-9_`., ()+\-*/<>=!'\n\r\t{}%]+$")
ALLOWED_OPERATORS = {"=", "!=", "<>", ">", ">=", "<", "<=", "in", "not in", "like"}
ALLOWED_TIME_PERIODS = {"this_month", "last_month", "last_3_months", "recent_3_months"}


class SemanticRuntimeService:
    """语义运行时服务：结构化资产读取、校验和 LogicForm 编译。"""

    async def list_domains(self, agent_id: int) -> list[SemanticDomain]:
        """List semantic domains owned by an agent."""
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM semantic_domain WHERE agent_id = :aid ORDER BY id ASC",
            {"aid": agent_id},
        )
        return [SemanticDomain(**row) for row in rows]

    async def list_all_domains(self) -> list[SemanticDomain]:
        """List all semantic domains for administration screens."""
        db = get_management_db()
        rows = await db.execute_query("SELECT * FROM semantic_domain ORDER BY id ASC")
        return [SemanticDomain(**row) for row in rows]

    async def get_domain(self, domain_id: int) -> SemanticDomain | None:
        """Load one semantic domain by id."""
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM semantic_domain WHERE id = :id",
            {"id": domain_id},
        )
        return SemanticDomain(**rows[0]) if rows else None

    async def get_domain_by_key(
        self,
        agent_id: int,
        domain_key: str | None = None,
        datasource_id: int | None = None,
    ) -> SemanticDomain | None:
        """Find the best active semantic domain for agent, key, and optional datasource."""
        if not domain_key:
            return None
        db = get_management_db()
        params: dict[str, Any] = {"aid": agent_id, "domain_key": domain_key}
        datasource_filter = ""
        if datasource_id:
            datasource_filter = " AND (datasource_id = :did OR datasource_id IS NULL)"
            params["did"] = datasource_id
        rows = await db.execute_query(
            "SELECT * FROM semantic_domain "
            "WHERE agent_id = :aid AND domain_key = :domain_key"
            f"{datasource_filter} ORDER BY datasource_id DESC, id DESC LIMIT 1",
            params,
        )
        return SemanticDomain(**rows[0]) if rows else None

    async def get_agent_bound_domain(self, agent_id: int) -> SemanticDomain | None:
        """Load the semantic domain explicitly selected on an agent."""
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT sd.* FROM agent a "
            "JOIN semantic_domain sd ON sd.id = a.semantic_domain_id "
            "WHERE a.id = :agent_id",
            {"agent_id": agent_id},
        )
        return SemanticDomain(**rows[0]) if rows else None

    async def upsert_domain(self, data: dict[str, Any]) -> int:
        """Create or update a semantic domain while preserving unique domain keys per agent."""
        db = get_management_db()
        domain = SemanticDomain(**data)
        params = {
            "agent_id": domain.agent_id,
            "datasource_id": domain.datasource_id,
            "domain_key": domain.domain_key,
            "name": domain.name,
            "description": domain.description,
            "status": domain.status,
        }
        if domain.id:
            existing_by_id = await db.execute_query(
                "SELECT id FROM semantic_domain WHERE id = :id",
                {"id": domain.id},
            )
            if not existing_by_id:
                raise ValueError(f"语义领域不存在: {domain.id}")
            duplicate = await db.execute_query(
                "SELECT id FROM semantic_domain "
                "WHERE agent_id = :agent_id AND domain_key = :domain_key AND id <> :id",
                {**params, "id": domain.id},
            )
            if duplicate:
                raise ValueError(f"语义领域标识已存在: {domain.domain_key}")
            await db.execute_query(
                "UPDATE semantic_domain SET agent_id = :agent_id, datasource_id = :datasource_id, "
                "domain_key = :domain_key, name = :name, description = :description, "
                "status = :status WHERE id = :id",
                {**params, "id": domain.id},
            )
            return int(domain.id)

        existing = await db.execute_query(
            "SELECT id FROM semantic_domain "
            "WHERE agent_id = :agent_id AND domain_key = :domain_key",
            {"agent_id": domain.agent_id, "domain_key": domain.domain_key},
        )
        if existing:
            await db.execute_query(
                "UPDATE semantic_domain SET datasource_id = :datasource_id, name = :name, "
                "description = :description, status = :status WHERE id = :id",
                {**params, "id": existing[0]["id"]},
            )
            return int(existing[0]["id"])
        return await db.execute_insert(
            "INSERT INTO semantic_domain "
            "(agent_id, datasource_id, domain_key, name, description, status) "
            "VALUES (:agent_id, :datasource_id, :domain_key, :name, :description, :status)",
            params,
        )

    async def delete_domain(self, domain_id: int) -> bool:
        """Delete a semantic domain and all child semantic assets."""
        db = get_management_db()
        existing = await db.execute_query(
            "SELECT id FROM semantic_domain WHERE id = :id",
            {"id": domain_id},
        )
        if not existing:
            return False
        for table in (
            "logic_form_template",
            "semantic_mapping",
            "semantic_rule",
            "semantic_metric",
            "semantic_relation",
            "semantic_concept",
        ):
            await db.execute_query(
                f"DELETE FROM {table} WHERE domain_id = :id",
                {"id": domain_id},
            )
        await db.execute_query(
            "UPDATE agent SET semantic_domain_id = NULL WHERE semantic_domain_id = :id",
            {"id": domain_id},
        )
        await db.execute_query(
            "DELETE FROM semantic_domain WHERE id = :id",
            {"id": domain_id},
        )
        return True

    async def export_domain_bundle(self, domain_id: int) -> dict[str, Any]:
        """Export a semantic domain and its assets as a portable bundle."""
        domain = await self.get_domain(domain_id)
        if domain is None:
            raise ValueError("语义领域不存在")
        assets = await self.list_assets(domain_id)
        return {
            "version": 1,
            "domain": domain.model_dump(),
            "assets": assets,
            "asset_counts": {key: len(value) for key, value in assets.items()},
        }

    async def copy_domain(self, domain_id: int, payload: dict[str, Any]) -> int:
        """Clone a semantic domain bundle into a new domain."""
        bundle = await self.export_domain_bundle(domain_id)
        source = bundle["domain"]
        new_domain = {
            "agent_id": payload.get("agent_id") or source["agent_id"],
            "datasource_id": payload.get("datasource_id", source.get("datasource_id")),
            "domain_key": payload.get("domain_key") or f"{source['domain_key']}_copy",
            "name": payload.get("name") or f"{source['name']} 副本",
            "description": payload.get("description", source.get("description") or ""),
            "status": payload.get("status") or source.get("status") or "active",
        }
        new_id = await self.upsert_domain(new_domain)
        await self._import_assets(new_id, bundle.get("assets") or {})
        return int(new_id)

    async def import_domain_bundle(self, bundle: dict[str, Any]) -> int:
        """Import a semantic domain bundle into management storage."""
        domain = dict(bundle.get("domain") or {})
        if not domain:
            raise ValueError("导入文件缺少 domain")
        for field in ("id", "created_at", "updated_at"):
            domain.pop(field, None)
        db = get_management_db()
        duplicate = await db.execute_query(
            "SELECT id FROM semantic_domain "
            "WHERE agent_id = :agent_id AND domain_key = :domain_key",
            {"agent_id": domain.get("agent_id"), "domain_key": domain.get("domain_key")},
        )
        if duplicate:
            raise ValueError(f"语义层标识已存在: {domain.get('domain_key')}")
        new_id = await self.upsert_domain(domain)
        await self._import_assets(new_id, bundle.get("assets") or {})
        return int(new_id)

    async def validate_domain_assets(self, domain_id: int) -> dict[str, Any]:
        """Validate configured semantic assets against collected schema and references."""
        domain = await self.get_domain(domain_id)
        if domain is None:
            raise ValueError("语义领域不存在")
        assets = await self.list_assets(domain_id)
        errors: list[str] = []
        warnings: list[str] = []
        mapping_keys = {item.get("asset_key") for item in assets.get("mapping", [])}
        schema_tables: dict[str, set[str]] = {}
        if domain.datasource_id:
            from app.services.metadata_service import get_metadata_service

            schema = await get_metadata_service().get_schema(domain.datasource_id)
            schema_tables = {
                str(table.get("table_name")): {
                    str(column.get("column_name")) for column in table.get("columns", []) or []
                }
                for table in schema
            }
            if not schema_tables:
                warnings.append("当前语义层绑定的数据源没有已采集 schema，无法校验物理表字段。")
        else:
            warnings.append("当前语义层没有绑定默认数据源，无法校验物理表字段。")

        for mapping in assets.get("mapping", []):
            table_name = str(mapping.get("table_name") or "")
            column_name = str(mapping.get("column_name") or "")
            if schema_tables and table_name not in schema_tables:
                errors.append(f"映射 {mapping.get('asset_key')} 的表不存在或未采集: {table_name}")
            if (
                schema_tables
                and column_name
                and column_name not in schema_tables.get(table_name, set())
            ):
                errors.append(
                    f"映射 {mapping.get('asset_key')} 的字段不存在或未采集: "
                    f"{table_name}.{column_name}"
                )
            if not column_name and not mapping.get("expression_sql"):
                errors.append(f"映射 {mapping.get('asset_key')} 缺少字段名或表达式")

        for metric in assets.get("metric", []):
            base_table = str(metric.get("base_table") or "")
            if schema_tables and base_table not in schema_tables:
                errors.append(
                    f"指标 {metric.get('metric_key')} 的基础表不存在或未采集: {base_table}"
                )
            time_field = str(metric.get("time_field") or "")
            if time_field:
                table_name, column_name = self._safe_split_qualified(time_field)
                if (
                    schema_tables
                    and table_name
                    and column_name
                    and column_name not in schema_tables.get(table_name, set())
                ):
                    errors.append(
                        f"指标 {metric.get('metric_key')} 的时间字段不存在或未采集: {time_field}"
                    )
            for dimension in metric.get("dimensions") or []:
                if dimension not in mapping_keys:
                    errors.append(
                        f"指标 {metric.get('metric_key')} 的可用维度未配置映射: {dimension}"
                    )

        for relation in assets.get("relation", []):
            for join in relation.get("join_path") or []:
                for side in ("left", "right"):
                    table_name, column_name = self._safe_split_qualified(str(join.get(side) or ""))
                    if not table_name or not column_name:
                        errors.append(
                            f"关系 {relation.get('relation_key')} 的 JOIN 字段格式错误: "
                            f"{join.get(side)}"
                        )
                    elif schema_tables and column_name not in schema_tables.get(table_name, set()):
                        errors.append(
                            f"关系 {relation.get('relation_key')} 的 JOIN 字段不存在或未采集: "
                            f"{table_name}.{column_name}"
                        )

        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "asset_counts": {key: len(value) for key, value in assets.items()},
        }

    async def create_snapshot(
        self, domain_id: int, name: str | None = None, description: str | None = ""
    ) -> int:
        """Persist a point-in-time snapshot of a semantic domain bundle."""
        bundle = await self.export_domain_bundle(domain_id)
        db = get_management_db()
        return await db.execute_insert(
            "INSERT INTO semantic_domain_snapshot "
            "(domain_id, name, description, snapshot_json, asset_counts) "
            "VALUES (:domain_id, :name, :description, :snapshot_json, :asset_counts)",
            {
                "domain_id": domain_id,
                "name": name or f"{bundle['domain']['name']} 快照",
                "description": description or "",
                "snapshot_json": json.dumps(bundle, ensure_ascii=False, default=str),
                "asset_counts": json.dumps(bundle.get("asset_counts") or {}, ensure_ascii=False),
            },
        )

    async def list_snapshots(self, domain_id: int) -> list[dict[str, Any]]:
        """List saved snapshots for a semantic domain."""
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT id, domain_id, name, description, asset_counts, created_at "
            "FROM semantic_domain_snapshot WHERE domain_id = :domain_id ORDER BY id DESC",
            {"domain_id": domain_id},
        )
        for row in rows:
            row["asset_counts"] = self._json_load(row.get("asset_counts"))
        return rows

    async def get_snapshot(self, domain_id: int, snapshot_id: int) -> dict[str, Any]:
        """Load one semantic domain snapshot payload."""
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT id, domain_id, name, description, snapshot_json, asset_counts, created_at "
            "FROM semantic_domain_snapshot WHERE domain_id = :domain_id AND id = :id",
            {"domain_id": domain_id, "id": snapshot_id},
        )
        if not rows:
            raise ValueError("语义层快照不存在")
        row = rows[0]
        row["snapshot_json"] = self._json_load(row.get("snapshot_json"))
        row["asset_counts"] = self._json_load(row.get("asset_counts"))
        return row

    async def diff_snapshot(self, domain_id: int, snapshot_id: int) -> dict[str, Any]:
        """Compare the current semantic domain with a saved snapshot."""
        snapshot = await self.get_snapshot(domain_id, snapshot_id)
        snapshot_bundle = snapshot.get("snapshot_json") or {}
        current_bundle = await self.export_domain_bundle(domain_id)
        return {
            "snapshot": {
                "id": snapshot.get("id"),
                "name": snapshot.get("name"),
                "description": snapshot.get("description"),
                "created_at": snapshot.get("created_at"),
            },
            "summary": self._diff_summary(current_bundle, snapshot_bundle),
            "domain": self._diff_domain(
                current_bundle.get("domain") or {}, snapshot_bundle.get("domain") or {}
            ),
            "assets": self._diff_assets(
                current_bundle.get("assets") or {}, snapshot_bundle.get("assets") or {}
            ),
        }

    async def rollback_snapshot(self, domain_id: int, snapshot_id: int) -> dict[str, Any]:
        """Replace current semantic domain config with a saved snapshot."""
        snapshot = await self.get_snapshot(domain_id, snapshot_id)
        bundle = snapshot.get("snapshot_json") or {}
        domain = dict(bundle.get("domain") or {})
        if not domain:
            raise ValueError("快照缺少 domain，无法回滚")
        if await self.get_domain(domain_id) is None:
            raise ValueError("语义领域不存在")

        db = get_management_db()
        await db.execute_query(
            "UPDATE semantic_domain SET datasource_id = :datasource_id, name = :name, "
            "description = :description, status = :status WHERE id = :id",
            {
                "id": domain_id,
                "datasource_id": domain.get("datasource_id"),
                "name": domain.get("name") or "未命名语义层",
                "description": domain.get("description") or "",
                "status": domain.get("status") or "active",
            },
        )
        for table_info in reversed(list(ASSET_TABLES.values())):
            table = table_info[0]
            await db.execute_query(
                f"DELETE FROM {table} WHERE domain_id = :domain_id",
                {"domain_id": domain_id},
            )
        await self._import_assets(domain_id, bundle.get("assets") or {})
        return {
            "id": domain_id,
            "snapshot_id": snapshot_id,
            "message": "语义层已回滚到快照",
            "asset_counts": bundle.get("asset_counts") or {},
        }

    async def list_assets(
        self, domain_id: int, asset_type: str | None = None
    ) -> dict[str, list[dict]]:
        """List semantic assets for a domain, optionally limited to one asset type."""
        logger.info("semantic list_assets domain_id=%s asset_type=%s", domain_id, asset_type)
        if asset_type:
            result = {asset_type: await self._list_asset_type(domain_id, asset_type)}
        else:
            result = {key: await self._list_asset_type(domain_id, key) for key in ASSET_TABLES}
        logger.info(
            "semantic list_assets result domain_id=%s counts=%s",
            domain_id,
            json_for_log({key: len(value) for key, value in result.items()}),
        )
        return result

    async def upsert_asset(self, domain_id: int, asset_type: str, data: dict[str, Any]) -> int:
        """Create or update one semantic asset in a domain."""
        logger.info(
            "semantic upsert_asset domain_id=%s asset_type=%s data=%s",
            domain_id,
            asset_type,
            json_for_log(data, text_limit=1200),
        )
        if asset_type not in ASSET_TABLES:
            raise ValueError(f"不支持的语义资产类型: {asset_type}")
        table, key_field, model = ASSET_TABLES[asset_type]
        data = {**data, "domain_id": domain_id}
        item = model(**data)
        payload = self._model_payload(item.model_dump(exclude={"id"}), asset_type)
        key_value = payload[key_field]

        db = get_management_db()
        if item.id:
            existing_by_id = await db.execute_query(
                f"SELECT id FROM {table} WHERE id = :id AND domain_id = :domain_id",
                {"id": item.id, "domain_id": domain_id},
            )
            if not existing_by_id:
                raise ValueError(f"语义资产不存在或不属于当前领域: {item.id}")
            assignments = ", ".join(
                f"{field} = :{field}" for field in payload if field != "domain_id"
            )
            await db.execute_query(
                f"UPDATE {table} SET {assignments} WHERE id = :id AND domain_id = :domain_id",
                {**payload, "id": item.id},
            )
            logger.info(
                "semantic upsert_asset updated by id domain_id=%s asset_type=%s id=%s key=%s",
                domain_id,
                asset_type,
                item.id,
                key_value,
            )
            return int(item.id)

        existing = await db.execute_query(
            f"SELECT id FROM {table} WHERE domain_id = :domain_id AND {key_field} = :key",
            {"domain_id": domain_id, "key": key_value},
        )
        if existing:
            assignments = ", ".join(
                f"{field} = :{field}" for field in payload if field not in {"domain_id", key_field}
            )
            await db.execute_query(
                f"UPDATE {table} SET {assignments} WHERE id = :id",
                {**payload, "id": existing[0]["id"]},
            )
            logger.info(
                "semantic upsert_asset updated by key domain_id=%s asset_type=%s id=%s key=%s",
                domain_id,
                asset_type,
                existing[0]["id"],
                key_value,
            )
            return int(existing[0]["id"])

        fields = ", ".join(payload)
        values = ", ".join(f":{field}" for field in payload)
        asset_id = await db.execute_insert(
            f"INSERT INTO {table} ({fields}) VALUES ({values})",
            payload,
        )
        logger.info(
            "semantic upsert_asset inserted domain_id=%s asset_type=%s id=%s key=%s",
            domain_id,
            asset_type,
            asset_id,
            key_value,
        )
        return asset_id

    async def _import_assets(self, domain_id: int, assets: dict[str, list[dict]]) -> None:
        """Import every asset group from a domain bundle into a target domain."""
        for asset_type in ASSET_TABLES:
            for item in assets.get(asset_type, []) or []:
                payload = dict(item)
                for field in ("id", "domain_id", "created_at", "updated_at"):
                    payload.pop(field, None)
                await self.upsert_asset(domain_id, asset_type, payload)

    async def delete_asset(self, domain_id: int, asset_type: str, asset_id: int) -> bool:
        """Delete one semantic asset by type and id."""
        if asset_type not in ASSET_TABLES:
            raise ValueError(f"不支持的语义资产类型: {asset_type}")
        table, _, _ = ASSET_TABLES[asset_type]
        db = get_management_db()
        existing = await db.execute_query(
            f"SELECT id FROM {table} WHERE id = :id AND domain_id = :domain_id",
            {"id": asset_id, "domain_id": domain_id},
        )
        if not existing:
            return False
        await db.execute_query(
            f"DELETE FROM {table} WHERE id = :id AND domain_id = :domain_id",
            {"id": asset_id, "domain_id": domain_id},
        )
        return True

    async def build_runtime(
        self,
        agent_id: int,
        datasource_id: int | None = None,
        domain_key: str | None = None,
        domain_id: int | None = None,
    ) -> SemanticRuntime:
        """Load the executable semantic runtime used by graph nodes."""
        logger.info(
            "semantic build_runtime start agent_id=%s datasource_id=%s domain_key=%s domain_id=%s",
            agent_id,
            datasource_id,
            domain_key,
            domain_id,
        )
        domain = await self.get_domain(domain_id) if domain_id else None
        if domain is None:
            domain = await self.get_agent_bound_domain(agent_id)
        if domain is None:
            domain = await self.get_domain_by_key(agent_id, domain_key, datasource_id)
        if domain is None:
            raise ValueError("未找到智能体绑定的语义层")

        runtime = SemanticRuntime(
            domain=domain,
            concepts=[
                SemanticConcept(**row) for row in await self._list_asset_type(domain.id, "concept")
            ],
            relations=[
                SemanticRelation(**row)
                for row in await self._list_asset_type(domain.id, "relation")
            ],
            metrics=[
                SemanticMetric(**row) for row in await self._list_asset_type(domain.id, "metric")
            ],
            rules=[SemanticRule(**row) for row in await self._list_asset_type(domain.id, "rule")],
            mappings=[
                SemanticMapping(**row) for row in await self._list_asset_type(domain.id, "mapping")
            ],
            templates=[
                LogicFormTemplate(**row)
                for row in await self._list_asset_type(domain.id, "template")
            ],
        )
        logger.info(
            "semantic build_runtime result domain_id=%s domain_key=%s counts=%s",
            domain.id,
            domain.domain_key,
            json_for_log(
                {
                    "concepts": len(runtime.concepts),
                    "relations": len(runtime.relations),
                    "metrics": len(runtime.metrics),
                    "rules": len(runtime.rules),
                    "mappings": len(runtime.mappings),
                    "templates": len(runtime.templates),
                }
            ),
        )
        return runtime

    def validate_logic_form(
        self,
        logic_form: LogicForm,
        runtime: SemanticRuntime,
    ) -> LogicFormValidation:
        """Check that a LogicForm references known metrics, dimensions, filters, and sorts."""
        logger.info("semantic validate_logic_form input=%s", json_for_log(logic_form.model_dump()))
        metric_map = {metric.metric_key: metric for metric in runtime.metrics}
        mapping_map = {mapping.asset_key: mapping for mapping in runtime.mappings}
        errors: list[str] = []
        warnings: list[str] = []
        used_assets: list[str] = []

        if not logic_form.metrics:
            errors.append("LogicForm 至少需要一个指标")

        for metric_key in logic_form.metrics:
            metric = metric_map.get(metric_key)
            if not metric:
                errors.append(f"未知指标: {metric_key}")
                continue
            used_assets.append(f"metric:{metric_key}")
            allowed_dimensions = set(metric.dimensions or [])
            for dimension in logic_form.dimensions:
                if allowed_dimensions and dimension not in allowed_dimensions:
                    errors.append(f"指标 {metric_key} 不支持维度: {dimension}")

        if logic_form.grain:
            if logic_form.grain not in {"month", "day"}:
                errors.append(f"不支持的时间粒度: {logic_form.grain}")
            elif not logic_form.metrics:
                errors.append("时间粒度查询缺少指标")
            else:
                metrics = [
                    metric_map.get(metric_key)
                    for metric_key in logic_form.metrics
                    if metric_map.get(metric_key)
                ]
                if metrics and any(not metric.time_field for metric in metrics):
                    missing = [metric.metric_key for metric in metrics if not metric.time_field]
                    errors.append(f"以下指标缺少时间字段，无法按时间粒度分析: {', '.join(missing)}")
                used_assets.append(f"grain:{logic_form.grain}")

        for dimension in logic_form.dimensions:
            mapping = mapping_map.get(dimension)
            if not mapping or mapping.role not in {"dimension", "filter", "time"}:
                errors.append(f"未知维度: {dimension}")
            else:
                used_assets.append(f"mapping:{dimension}")

        for item in logic_form.filters:
            if item.operator.lower() not in ALLOWED_OPERATORS:
                errors.append(f"过滤操作符不允许: {item.operator}")
            mapping = mapping_map.get(item.field)
            if not mapping or mapping.role not in {"dimension", "filter", "time"}:
                errors.append(f"未知过滤字段: {item.field}")
            else:
                used_assets.append(f"mapping:{item.field}")

        for sort in logic_form.sort:
            if sort.field not in set(logic_form.metrics + logic_form.dimensions):
                errors.append(f"排序字段必须来自指标或维度: {sort.field}")

        if logic_form.time_range and logic_form.time_range.period:
            if logic_form.time_range.period not in ALLOWED_TIME_PERIODS:
                warnings.append(f"未内置识别的时间窗口: {logic_form.time_range.period}")

        result = LogicFormValidation(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            used_assets=sorted(set(used_assets)),
        )
        logger.info("semantic validate_logic_form result=%s", json_for_log(result.model_dump()))
        return result

    def compile_logic_form(self, logic_form: LogicForm, runtime: SemanticRuntime) -> CompiledQuery:
        """Compile a validated LogicForm into deterministic MySQL SELECT SQL."""
        logger.info("semantic compile_logic_form input=%s", json_for_log(logic_form.model_dump()))
        validation = self.validate_logic_form(logic_form, runtime)
        if not validation.valid:
            raise ValueError("；".join(validation.errors))

        metric_map = {metric.metric_key: metric for metric in runtime.metrics}
        mapping_map = {mapping.asset_key: mapping for mapping in runtime.mappings}
        metrics = [metric_map[key] for key in logic_form.metrics]
        base_table = metrics[0].base_table
        metric_base_tables = {metric.base_table for metric in metrics}
        if len(metric_base_tables) > 1:
            if logic_form.dimensions:
                raise ValueError("暂不支持跨事实表指标按维度分组，请减少指标或去掉分组维度")
            compiled = self._compile_scalar_multi_metric_query(
                logic_form=logic_form,
                metrics=metrics,
                runtime=runtime,
                mapping_map=mapping_map,
                used_assets=list(validation.used_assets),
                warnings=validation.warnings,
            )
            logger.info(
                "semantic compile_logic_form result scalar sql=%s",
                truncate_text(compiled.sql, 1800),
            )
            return compiled

        table_aliases = {base_table: "t0"}
        joins: list[str] = []
        used_assets = list(validation.used_assets)

        def ensure_table(table_name: str) -> str:
            """Return an alias for a table, creating the required JOIN when needed."""
            if table_name in table_aliases:
                return table_aliases[table_name]
            alias = f"t{len(table_aliases)}"
            join_condition = self._find_join_condition(
                base_table, table_name, runtime, table_aliases
            )
            table_aliases[table_name] = alias
            joins.append(f"JOIN `{table_name}` {alias} ON {join_condition.format(target=alias)}")
            return alias

        select_parts: list[str] = []
        group_parts: list[str] = []

        if logic_form.grain:
            time_field = metrics[0].time_field
            if not time_field:
                raise ValueError("当前指标缺少时间字段，无法按时间粒度分析")
            time_table, time_column = self._split_qualified(time_field)
            time_alias = ensure_table(time_table)
            if logic_form.grain == "day":
                time_expr = f"DATE_FORMAT({time_alias}.`{time_column}`, '%Y-%m-%d')"
                time_label = "day"
            else:
                time_expr = f"DATE_FORMAT({time_alias}.`{time_column}`, '%Y-%m')"
                time_label = "month"
            select_parts.append(f"{time_expr} AS `{time_label}`")
            group_parts.append(time_expr)
            used_assets.append(f"grain:{logic_form.grain}")

        for dimension in logic_form.dimensions:
            mapping = mapping_map[dimension]
            alias = ensure_table(mapping.table_name)
            expr = self._mapping_expr(mapping, alias)
            select_parts.append(f"{expr} AS `{dimension}`")
            group_parts.append(expr)

        for metric in metrics:
            if metric.base_table != base_table:
                raise ValueError("暂不支持同一 LogicForm 混用不同事实表指标")
            expr = self._format_sql_expr(metric.formula_sql, table_aliases[base_table])
            select_parts.append(f"{expr} AS `{metric.metric_key}`")
            used_assets.append(f"metric:{metric.metric_key}")

        where_parts: list[str] = []
        for metric in metrics:
            where_parts.extend(
                self._compile_filter(item, mapping_map, ensure_table)
                for item in metric.default_filters
            )

        for item in logic_form.filters:
            where_parts.append(self._compile_filter(item.model_dump(), mapping_map, ensure_table))

        if logic_form.time_range:
            time_field = metrics[0].time_field
            if time_field:
                where_parts.extend(
                    self._compile_time_range(time_field, logic_form.time_range, table_aliases)
                )

        sql_parts = [
            "SELECT " + ", ".join(select_parts),
            f"FROM `{base_table}` {table_aliases[base_table]}",
            *joins,
        ]
        if where_parts:
            sql_parts.append("WHERE " + " AND ".join(part for part in where_parts if part))
        if group_parts:
            sql_parts.append("GROUP BY " + ", ".join(group_parts))
        if logic_form.sort:
            order_parts = [f"`{sort.field}` {sort.direction.upper()}" for sort in logic_form.sort]
            sql_parts.append("ORDER BY " + ", ".join(order_parts))
        elif logic_form.grain:
            order_parts = [f"`{'day' if logic_form.grain == 'day' else 'month'}` ASC"]
            order_parts.extend(f"`{dimension}` ASC" for dimension in logic_form.dimensions)
            sql_parts.append("ORDER BY " + ", ".join(order_parts))
        if logic_form.limit:
            sql_parts.append(f"LIMIT {min(max(int(logic_form.limit), 1), 1000)}")

        compiled = CompiledQuery(
            logic_form=logic_form,
            sql="\n".join(sql_parts),
            used_assets=sorted(set(used_assets)),
            warnings=validation.warnings,
        )
        logger.info(
            "semantic compile_logic_form result sql=%s used_assets=%s warnings=%s",
            truncate_text(compiled.sql, 1800),
            json_for_log(compiled.used_assets),
            json_for_log(compiled.warnings),
        )
        return compiled

    def _compile_scalar_multi_metric_query(
        self,
        logic_form: LogicForm,
        metrics: list[SemanticMetric],
        runtime: SemanticRuntime,
        mapping_map: dict[str, SemanticMapping],
        used_assets: list[str],
        warnings: list[str],
    ) -> CompiledQuery:
        """Compile cross-table metrics into one scalar row.

        This covers questions like "高 PD 客户的余额和逾期情况", where the
        requested metrics live on different fact tables and there is no group
        dimension. Each metric gets its own semantically filtered subquery.
        """
        select_parts: list[str] = []
        subqueries: list[str] = []
        for index, metric in enumerate(metrics):
            alias_prefix = f"m{index}_"
            table_aliases = {metric.base_table: f"{alias_prefix}0"}
            joins: list[str] = []

            def ensure_table(table_name: str) -> str:
                """Return a metric-local alias for a table, adding joins for subqueries."""
                if table_name in table_aliases:
                    return table_aliases[table_name]
                alias = f"{alias_prefix}{len(table_aliases)}"
                join_condition = self._find_join_condition(
                    metric.base_table,
                    table_name,
                    runtime,
                    table_aliases,
                )
                table_aliases[table_name] = alias
                joins.append(
                    f"JOIN `{table_name}` {alias} ON {join_condition.format(target=alias)}"
                )
                return alias

            where_parts = [
                self._compile_filter(item, mapping_map, ensure_table)
                for item in metric.default_filters
            ]
            where_parts.extend(
                self._compile_filter(item.model_dump(), mapping_map, ensure_table)
                for item in logic_form.filters
            )
            if logic_form.time_range and metric.time_field:
                time_table, _ = self._split_qualified(metric.time_field)
                ensure_table(time_table)
                where_parts.extend(
                    self._compile_time_range(
                        metric.time_field, logic_form.time_range, table_aliases
                    )
                )

            metric_expr = self._format_sql_expr(
                metric.formula_sql, table_aliases[metric.base_table]
            )
            query_parts = [
                f"SELECT {metric_expr} AS `{metric.metric_key}`",
                f"FROM `{metric.base_table}` {table_aliases[metric.base_table]}",
                *joins,
            ]
            if where_parts:
                query_parts.append("WHERE " + " AND ".join(part for part in where_parts if part))

            subquery_alias = f"q{index}"
            subqueries.append("(\n" + "\n".join(query_parts) + f"\n) {subquery_alias}")
            select_parts.append(f"{subquery_alias}.`{metric.metric_key}` AS `{metric.metric_key}`")
            used_assets.append(f"metric:{metric.metric_key}")

        scalar_warnings = list(warnings)
        if logic_form.sort:
            scalar_warnings.append("跨事实表标量指标查询不应用排序，已忽略 sort")
        if logic_form.limit:
            scalar_warnings.append("跨事实表标量指标查询只返回一行，已忽略 limit")

        return CompiledQuery(
            logic_form=logic_form,
            sql="SELECT " + ", ".join(select_parts) + "\nFROM " + "\nCROSS JOIN ".join(subqueries),
            used_assets=sorted(set(used_assets)),
            warnings=scalar_warnings,
        )

    async def _list_asset_type(self, domain_id: int | None, asset_type: str) -> list[dict]:
        """Read one semantic asset table and parse JSON columns."""
        if domain_id is None:
            return []
        if asset_type not in ASSET_TABLES:
            raise ValueError(f"不支持的语义资产类型: {asset_type}")
        table, _, _ = ASSET_TABLES[asset_type]
        db = get_management_db()
        rows = await db.execute_query(
            f"SELECT * FROM {table} WHERE domain_id = :domain_id ORDER BY id",
            {"domain_id": domain_id},
        )
        return [self._parse_json_fields(row, asset_type) for row in rows]

    def _model_payload(self, data: dict[str, Any], asset_type: str) -> dict[str, Any]:
        """Prepare a Pydantic semantic asset for database storage."""
        return {
            key: self._json_dump(value) if key in JSON_FIELDS.get(asset_type, ()) else value
            for key, value in data.items()
        }

    def _parse_json_fields(self, row: dict[str, Any], asset_type: str) -> dict[str, Any]:
        """Parse JSON-encoded columns for a semantic asset row."""
        parsed = dict(row)
        for field in JSON_FIELDS.get(asset_type, ()):
            parsed[field] = self._json_load(parsed.get(field))
        return parsed

    def _json_dump(self, value: Any) -> str:
        """Serialize JSON columns with Chinese text preserved."""
        return json.dumps(value if value is not None else [], ensure_ascii=False)

    def _json_load(self, value: Any) -> Any:
        """Parse a JSON column value with a default fallback."""
        if value in (None, ""):
            return []
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return []
        return value

    def _diff_summary(
        self, current_bundle: dict[str, Any], snapshot_bundle: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a high-level diff between two semantic domain bundles."""
        assets = self._diff_assets(
            current_bundle.get("assets") or {}, snapshot_bundle.get("assets") or {}
        )
        added = sum(len(value.get("added", [])) for value in assets.values())
        removed = sum(len(value.get("removed", [])) for value in assets.values())
        changed = sum(len(value.get("changed", [])) for value in assets.values())
        domain_changed = bool(
            self._diff_domain(
                current_bundle.get("domain") or {}, snapshot_bundle.get("domain") or {}
            )
        )
        return {
            "domain_changed": domain_changed,
            "added": added,
            "removed": removed,
            "changed": changed,
            "total_changes": added + removed + changed + (1 if domain_changed else 0),
        }

    def _diff_domain(
        self, current: dict[str, Any], snapshot: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Compare domain-level fields between current and snapshot bundles."""
        fields = ("agent_id", "datasource_id", "domain_key", "name", "description", "status")
        changes = []
        for field in fields:
            if current.get(field) != snapshot.get(field):
                changes.append(
                    {
                        "field": field,
                        "current": current.get(field),
                        "snapshot": snapshot.get(field),
                    }
                )
        return changes

    def _diff_assets(
        self, current: dict[str, list[dict]], snapshot: dict[str, list[dict]]
    ) -> dict[str, dict[str, list[Any]]]:
        """Compare asset identities and payloads between current and snapshot bundles."""
        result = {}
        for asset_type, (_, key_field, _) in ASSET_TABLES.items():
            current_map = {
                self._asset_identity(asset_type, item, key_field): self._normalize_asset_for_diff(
                    item
                )
                for item in current.get(asset_type, []) or []
            }
            snapshot_map = {
                self._asset_identity(asset_type, item, key_field): self._normalize_asset_for_diff(
                    item
                )
                for item in snapshot.get(asset_type, []) or []
            }
            current_keys = set(current_map)
            snapshot_keys = set(snapshot_map)
            changed = [
                {
                    "key": key,
                    "current": current_map[key],
                    "snapshot": snapshot_map[key],
                }
                for key in sorted(current_keys & snapshot_keys)
                if current_map[key] != snapshot_map[key]
            ]
            result[asset_type] = {
                "added": sorted(current_keys - snapshot_keys),
                "removed": sorted(snapshot_keys - current_keys),
                "changed": changed,
            }
        return result

    def _asset_identity(self, asset_type: str, item: dict[str, Any], key_field: str) -> str:
        """Return the stable identity field for an asset in snapshot diffs."""
        if asset_type == "mapping":
            return "|".join(
                str(item.get(field) or "")
                for field in ("asset_type", "asset_key", "table_name", "role")
            )
        return str(item.get(key_field) or item.get("id") or "")

    def _normalize_asset_for_diff(self, item: dict[str, Any]) -> dict[str, Any]:
        """Remove volatile fields before comparing semantic assets."""
        ignored = {"id", "domain_id", "created_at", "updated_at"}
        return {key: item[key] for key in sorted(item) if key not in ignored}

    def _find_join_condition(
        self,
        base_table: str,
        target_table: str,
        runtime: SemanticRuntime,
        table_aliases: dict[str, str],
    ) -> str:
        """Find a configured relation that can join the base table to a target table."""
        for relation in runtime.relations:
            for join in relation.join_path:
                left_table, left_col = self._split_qualified(join["left"])
                right_table, right_col = self._split_qualified(join["right"])
                if left_table == base_table and right_table == target_table:
                    return f"{table_aliases[base_table]}.`{left_col}` = {{target}}.`{right_col}`"
                if right_table == base_table and left_table == target_table:
                    return f"{table_aliases[base_table]}.`{right_col}` = {{target}}.`{left_col}`"
        raise ValueError(f"未找到从 {base_table} 到 {target_table} 的唯一关系路径")

    def _split_qualified(self, value: str) -> tuple[str, str]:
        """Split a required table.column reference or raise when malformed."""
        table, column = value.split(".", 1)
        self._assert_identifier(table)
        self._assert_identifier(column)
        return table, column

    def _safe_split_qualified(self, value: str) -> tuple[str, str]:
        """Split table.column references permissively for relation discovery."""
        if "." not in value:
            return "", ""
        table, column = value.split(".", 1)
        if not SAFE_IDENTIFIER.match(table) or not SAFE_IDENTIFIER.match(column):
            return "", ""
        return table, column

    def _mapping_expr(self, mapping: SemanticMapping, alias: str) -> str:
        """Return the SQL expression for a semantic mapping on a table alias."""
        if mapping.expression_sql:
            return self._format_sql_expr(mapping.expression_sql, alias)
        if not mapping.column_name:
            raise ValueError(f"语义映射缺少字段或表达式: {mapping.asset_key}")
        self._assert_identifier(mapping.column_name)
        return f"{alias}.`{mapping.column_name}`"

    def _format_sql_expr(self, expression: str, alias: str) -> str:
        """Replace the metric base placeholder with an actual table alias."""
        if not SAFE_SQL_EXPR.match(expression):
            raise ValueError(f"SQL表达式包含非法字符: {expression}")
        return expression.format(base=alias, alias=alias)

    def _compile_filter(
        self, item: dict[str, Any], mapping_map: dict[str, SemanticMapping], ensure_table
    ) -> str:
        """Compile one LogicForm or default filter into a SQL predicate."""
        field = str(item.get("field", ""))
        operator = str(item.get("operator", "=")).lower()
        value = item.get("value")
        if operator not in ALLOWED_OPERATORS:
            raise ValueError(f"过滤操作符不允许: {operator}")
        mapping = mapping_map.get(field)
        if not mapping:
            raise ValueError(f"未知过滤字段: {field}")
        alias = ensure_table(mapping.table_name)
        expr = self._mapping_expr(mapping, alias)
        if operator in {"in", "not in"}:
            if not isinstance(value, list) or not value:
                raise ValueError(f"过滤字段 {field} 的 IN 值必须是非空列表")
            values = ", ".join(self._sql_literal(item) for item in value)
            return f"{expr} {operator.upper()} ({values})"
        return f"{expr} {operator.upper()} {self._sql_literal(value)}"

    def _compile_time_range(
        self, time_field: str, time_range, table_aliases: dict[str, str]
    ) -> list[str]:
        """Compile a relative time range into SQL date predicates."""
        table, column = self._split_qualified(time_field)
        if table not in table_aliases:
            raise ValueError(f"时间字段所在表未参与查询: {time_field}")
        expr = f"{table_aliases[table]}.`{column}`"
        if time_range.start and time_range.end:
            return [
                f"{expr} >= {self._sql_literal(time_range.start)}",
                f"{expr} < {self._sql_literal(time_range.end)}",
            ]
        if time_range.period == "this_month":
            return [
                f"{expr} >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')",
                f"{expr} < DATE_ADD(DATE_FORMAT(CURRENT_DATE, '%Y-%m-01'), INTERVAL 1 MONTH)",
            ]
        if time_range.period == "last_month":
            return [
                f"{expr} >= DATE_SUB(DATE_FORMAT(CURRENT_DATE, '%Y-%m-01'), INTERVAL 1 MONTH)",
                f"{expr} < DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')",
            ]
        if time_range.period in {"last_3_months", "recent_3_months"}:
            return [f"{expr} >= DATE_SUB(CURRENT_DATE, INTERVAL 3 MONTH)"]
        return []

    def _sql_literal(self, value: Any) -> str:
        """Render a safe SQL literal for configured filter values."""
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, int | float):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    def _assert_identifier(self, value: str) -> None:
        """Validate identifiers before interpolating them into SQL."""
        if not SAFE_IDENTIFIER.match(value):
            raise ValueError(f"非法标识符: {value}")


_semantic_runtime_service: SemanticRuntimeService | None = None


def get_semantic_runtime_service() -> SemanticRuntimeService:
    """Return the process-wide semantic runtime service singleton."""
    global _semantic_runtime_service
    if _semantic_runtime_service is None:
        _semantic_runtime_service = SemanticRuntimeService()
    return _semantic_runtime_service
