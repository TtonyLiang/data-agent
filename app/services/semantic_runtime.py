from __future__ import annotations

import json
import re
from typing import Any

from app.db.mysql import get_management_db
from app.models.knowledge import (
    CompiledQuery,
    LogicFilter,
    LogicForm,
    LogicFormTemplate,
    LogicFormValidation,
    LogicSort,
    SemanticConcept,
    SemanticDomain,
    SemanticMapping,
    SemanticMetric,
    SemanticRelation,
    SemanticRule,
    SemanticRuntime,
)


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
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM semantic_domain WHERE agent_id = :aid ORDER BY id ASC",
            {"aid": agent_id},
        )
        return [SemanticDomain(**row) for row in rows]

    async def list_all_domains(self) -> list[SemanticDomain]:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM semantic_domain ORDER BY id ASC"
        )
        return [SemanticDomain(**row) for row in rows]

    async def get_domain(self, domain_id: int) -> SemanticDomain | None:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM semantic_domain WHERE id = :id",
            {"id": domain_id},
        )
        return SemanticDomain(**rows[0]) if rows else None

    async def get_domain_by_key(
        self,
        agent_id: int,
        domain_key: str = "loan_risk",
        datasource_id: int | None = None,
    ) -> SemanticDomain | None:
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
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT sd.* FROM agent a "
            "JOIN semantic_domain sd ON sd.id = a.semantic_domain_id "
            "WHERE a.id = :agent_id",
            {"agent_id": agent_id},
        )
        return SemanticDomain(**rows[0]) if rows else None

    async def upsert_domain(self, data: dict[str, Any]) -> int:
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
            "SELECT id FROM semantic_domain WHERE agent_id = :agent_id AND domain_key = :domain_key",
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

    async def list_assets(self, domain_id: int, asset_type: str | None = None) -> dict[str, list[dict]]:
        if asset_type:
            return {asset_type: await self._list_asset_type(domain_id, asset_type)}
        return {
            key: await self._list_asset_type(domain_id, key)
            for key in ASSET_TABLES
        }

    async def upsert_asset(self, domain_id: int, asset_type: str, data: dict[str, Any]) -> int:
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
                f"{field} = :{field}"
                for field in payload
                if field != "domain_id"
            )
            await db.execute_query(
                f"UPDATE {table} SET {assignments} WHERE id = :id AND domain_id = :domain_id",
                {**payload, "id": item.id},
            )
            return int(item.id)

        existing = await db.execute_query(
            f"SELECT id FROM {table} WHERE domain_id = :domain_id AND {key_field} = :key",
            {"domain_id": domain_id, "key": key_value},
        )
        if existing:
            assignments = ", ".join(
                f"{field} = :{field}"
                for field in payload
                if field not in {"domain_id", key_field}
            )
            await db.execute_query(
                f"UPDATE {table} SET {assignments} WHERE id = :id",
                {**payload, "id": existing[0]["id"]},
            )
            return int(existing[0]["id"])

        fields = ", ".join(payload)
        values = ", ".join(f":{field}" for field in payload)
        return await db.execute_insert(
            f"INSERT INTO {table} ({fields}) VALUES ({values})",
            payload,
        )

    async def delete_asset(self, domain_id: int, asset_type: str, asset_id: int) -> bool:
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
        domain_key: str = "loan_risk",
        domain_id: int | None = None,
    ) -> SemanticRuntime:
        domain = await self.get_domain(domain_id) if domain_id else None
        if domain is None:
            domain = await self.get_agent_bound_domain(agent_id)
        if domain is None:
            domain = await self.get_domain_by_key(agent_id, domain_key, datasource_id)
        if domain is None:
            raise ValueError(f"未找到语义领域: {domain_key}")

        return SemanticRuntime(
            domain=domain,
            concepts=[SemanticConcept(**row) for row in await self._list_asset_type(domain.id, "concept")],
            relations=[
                SemanticRelation(**row) for row in await self._list_asset_type(domain.id, "relation")
            ],
            metrics=[SemanticMetric(**row) for row in await self._list_asset_type(domain.id, "metric")],
            rules=[SemanticRule(**row) for row in await self._list_asset_type(domain.id, "rule")],
            mappings=[SemanticMapping(**row) for row in await self._list_asset_type(domain.id, "mapping")],
            templates=[
                LogicFormTemplate(**row) for row in await self._list_asset_type(domain.id, "template")
            ],
        )

    def validate_logic_form(
        self,
        logic_form: LogicForm,
        runtime: SemanticRuntime,
    ) -> LogicFormValidation:
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

        return LogicFormValidation(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            used_assets=sorted(set(used_assets)),
        )

    def compile_logic_form(self, logic_form: LogicForm, runtime: SemanticRuntime) -> CompiledQuery:
        validation = self.validate_logic_form(logic_form, runtime)
        if not validation.valid:
            raise ValueError("；".join(validation.errors))

        metric_map = {metric.metric_key: metric for metric in runtime.metrics}
        mapping_map = {mapping.asset_key: mapping for mapping in runtime.mappings}
        metrics = [metric_map[key] for key in logic_form.metrics]
        base_table = metrics[0].base_table
        table_aliases = {base_table: "t0"}
        joins: list[str] = []
        used_assets = list(validation.used_assets)

        def ensure_table(table_name: str) -> str:
            if table_name in table_aliases:
                return table_aliases[table_name]
            alias = f"t{len(table_aliases)}"
            join_condition = self._find_join_condition(base_table, table_name, runtime, table_aliases)
            table_aliases[table_name] = alias
            joins.append(f"JOIN `{table_name}` {alias} ON {join_condition.format(target=alias)}")
            return alias

        select_parts: list[str] = []
        group_parts: list[str] = []

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
                where_parts.extend(self._compile_time_range(time_field, logic_form.time_range, table_aliases))

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
            order_parts = [
                f"`{sort.field}` {sort.direction.upper()}"
                for sort in logic_form.sort
            ]
            sql_parts.append("ORDER BY " + ", ".join(order_parts))
        if logic_form.limit:
            sql_parts.append(f"LIMIT {min(max(int(logic_form.limit), 1), 1000)}")

        return CompiledQuery(
            logic_form=logic_form,
            sql="\n".join(sql_parts),
            used_assets=sorted(set(used_assets)),
            warnings=validation.warnings,
        )

    async def _list_asset_type(self, domain_id: int | None, asset_type: str) -> list[dict]:
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
        return {
            key: self._json_dump(value) if key in JSON_FIELDS.get(asset_type, ()) else value
            for key, value in data.items()
        }

    def _parse_json_fields(self, row: dict[str, Any], asset_type: str) -> dict[str, Any]:
        parsed = dict(row)
        for field in JSON_FIELDS.get(asset_type, ()):
            parsed[field] = self._json_load(parsed.get(field))
        return parsed

    def _json_dump(self, value: Any) -> str:
        return json.dumps(value if value is not None else [], ensure_ascii=False)

    def _json_load(self, value: Any) -> Any:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return []
        return value

    def _find_join_condition(
        self,
        base_table: str,
        target_table: str,
        runtime: SemanticRuntime,
        table_aliases: dict[str, str],
    ) -> str:
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
        table, column = value.split(".", 1)
        self._assert_identifier(table)
        self._assert_identifier(column)
        return table, column

    def _mapping_expr(self, mapping: SemanticMapping, alias: str) -> str:
        if mapping.expression_sql:
            return self._format_sql_expr(mapping.expression_sql, alias)
        if not mapping.column_name:
            raise ValueError(f"语义映射缺少字段或表达式: {mapping.asset_key}")
        self._assert_identifier(mapping.column_name)
        return f"{alias}.`{mapping.column_name}`"

    def _format_sql_expr(self, expression: str, alias: str) -> str:
        if not SAFE_SQL_EXPR.match(expression):
            raise ValueError(f"SQL表达式包含非法字符: {expression}")
        return expression.format(base=alias, alias=alias)

    def _compile_filter(self, item: dict[str, Any], mapping_map: dict[str, SemanticMapping], ensure_table) -> str:
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

    def _compile_time_range(self, time_field: str, time_range, table_aliases: dict[str, str]) -> list[str]:
        table, column = self._split_qualified(time_field)
        if table not in table_aliases:
            raise ValueError(f"时间字段所在表未参与查询: {time_field}")
        expr = f"{table_aliases[table]}.`{column}`"
        if time_range.start and time_range.end:
            return [f"{expr} >= {self._sql_literal(time_range.start)}", f"{expr} < {self._sql_literal(time_range.end)}"]
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
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, int | float):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    def _assert_identifier(self, value: str) -> None:
        if not SAFE_IDENTIFIER.match(value):
            raise ValueError(f"非法标识符: {value}")


_semantic_runtime_service: SemanticRuntimeService | None = None


def get_semantic_runtime_service() -> SemanticRuntimeService:
    global _semantic_runtime_service
    if _semantic_runtime_service is None:
        _semantic_runtime_service = SemanticRuntimeService()
    return _semantic_runtime_service
