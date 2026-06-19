from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.db.mysql import get_management_db
from app.utils.sql_validator import extract_table_references


@dataclass(frozen=True)
class ColumnPolicy:
    allowed: bool = True
    masking_policy: str = "none"


class PermissionService:
    """Agent-level table/column permission and result masking service."""

    async def filter_schema(
        self, agent_id: int | None, datasource_id: int | None, schema: list[dict]
    ) -> list[dict]:
        if not agent_id or not datasource_id:
            return schema
        table_permissions = await self.get_table_permissions(agent_id, datasource_id)
        column_permissions = await self.get_column_permissions(agent_id, datasource_id)

        filtered = []
        for table in schema:
            table_name = str(table.get("table_name") or "")
            if not self.table_allowed(table_name, table_permissions):
                continue
            table_data = dict(table)
            columns = []
            for column in table.get("columns") or []:
                column_name = str(column.get("column_name") or "")
                policy = column_permissions.get((table_name.lower(), column_name.lower()))
                if policy and not policy.allowed:
                    continue
                column_data = dict(column)
                if policy and policy.masking_policy != "none":
                    column_data["masking_policy"] = policy.masking_policy
                columns.append(column_data)
            table_data["columns"] = columns
            filtered.append(table_data)
        return filtered

    async def validate_sql_access(
        self, agent_id: int | None, datasource_id: int | None, sql: str
    ) -> tuple[bool, str]:
        if not agent_id or not datasource_id:
            return True, "OK"
        table_permissions = await self.get_table_permissions(agent_id, datasource_id)
        if not table_permissions:
            return True, "OK"
        denied = [
            table
            for table in extract_table_references(sql)
            if not self.table_allowed(table, table_permissions)
        ]
        if denied:
            return False, "无权访问表: " + "、".join(denied)
        return True, "OK"

    async def mask_rows(
        self,
        agent_id: int | None,
        datasource_id: int | None,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        if not agent_id or not datasource_id or not rows:
            return rows, {}
        column_permissions = await self.get_column_permissions(agent_id, datasource_id)
        masking_by_column = {
            column: (policy.masking_policy if policy.allowed else "redact")
            for (_table, column), policy in column_permissions.items()
            if not policy.allowed or policy.masking_policy != "none"
        }
        if not masking_by_column:
            return rows, {}
        masked_rows = []
        applied: dict[str, str] = {}
        for row in rows:
            masked = dict(row)
            for key, value in row.items():
                policy = masking_by_column.get(str(key).lower())
                if not policy:
                    continue
                masked[key] = mask_value(value, policy)
                applied[str(key)] = policy
            masked_rows.append(masked)
        return masked_rows, applied

    async def get_table_permissions(self, agent_id: int, datasource_id: int) -> dict[str, bool]:
        rows = await get_management_db().execute_query(
            "SELECT table_name, allowed FROM agent_table_permission "
            "WHERE agent_id = :aid AND datasource_id = :did",
            {"aid": agent_id, "did": datasource_id},
        )
        return {str(row["table_name"]).lower(): bool(row.get("allowed", 1)) for row in rows}

    async def get_column_permissions(
        self, agent_id: int, datasource_id: int
    ) -> dict[tuple[str, str], ColumnPolicy]:
        rows = await get_management_db().execute_query(
            "SELECT table_name, column_name, allowed, masking_policy FROM agent_column_permission "
            "WHERE agent_id = :aid AND datasource_id = :did",
            {"aid": agent_id, "did": datasource_id},
        )
        policies: dict[tuple[str, str], ColumnPolicy] = {}
        for row in rows:
            policy = str(row.get("masking_policy") or "none").lower()
            if policy not in {"none", "redact", "partial", "hash"}:
                policy = "redact"
            policies[(str(row["table_name"]).lower(), str(row["column_name"]).lower())] = (
                ColumnPolicy(allowed=bool(row.get("allowed", 1)), masking_policy=policy)
            )
        return policies

    @staticmethod
    def table_allowed(table_name: str, table_permissions: dict[str, bool]) -> bool:
        if not table_permissions:
            return True
        return bool(table_permissions.get(table_name.lower(), False))


def mask_value(value: Any, policy: str) -> Any:
    if value is None:
        return None
    text = str(value)
    if policy == "hash":
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    if policy == "partial":
        if len(text) <= 4:
            return "*" * len(text)
        return f"{text[:2]}{'*' * max(len(text) - 4, 1)}{text[-2:]}"
    return "***"


_permission_service: PermissionService | None = None


def get_permission_service() -> PermissionService:
    global _permission_service
    if _permission_service is None:
        _permission_service = PermissionService()
    return _permission_service
