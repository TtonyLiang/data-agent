"""权限服务 —— 智能体级表/列权限控制与结果脱敏。

PermissionService 负责:
1. ``filter_schema``:在 schema 读取后叠加表/列权限规则,移除或标记脱敏策略。
2. ``validate_sql_access``:在 SQL 执行前检查引用的表是否被允许,否则拦截。
3. ``mask_rows``:在 SQL 执行结果返回后,对配置了脱敏策略的列进行脱敏处理。

权限规则存储:
- ``agent_table_permission``:表级允许/拒绝。
- ``agent_column_permission``:列级允许/拒绝 + 脱敏策略(redact/partial/hash)。

脱敏策略:
- ``redact``:直接替换为 "***"
- ``partial``:保留首尾各 2 字符,中间替换为 *
- ``hash``:SHA256 取前 12 位
- ``none``:不脱敏

权限同时作用于数据定位、NL2SQL 兜底上下文和 SQL 执行结果,
避免模型看到或返回不该暴露的表字段。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from app.db.mysql import get_management_db
from app.utils.sql_validator import extract_table_references

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ColumnPolicy:
    """列级权限策略 —— allowed 控制可见性,masking_policy 控制脱敏方式。"""

    allowed: bool = True
    masking_policy: str = "none"


class PermissionService:
    """智能体级表/列权限与结果脱敏服务。"""

    async def filter_schema(
        self, agent_id: int | None, datasource_id: int | None, schema: list[dict]
    ) -> list[dict]:
        """在 schema 上叠加权限规则:移除被拒的表/列,标记脱敏策略。

        返回过滤后的 schema(结构不变),用于数据定位和 NL2SQL 兜底。
        """
        if not agent_id or not datasource_id:
            return schema

        table_permissions = await self.get_table_permissions(agent_id, datasource_id)
        column_permissions = await self.get_column_permissions(agent_id, datasource_id)

        filtered = []
        for table in schema:
            table_name = str(table.get("table_name") or "")
            # 表级权限:不在白名单中的表整体移除
            if not self.table_allowed(table_name, table_permissions):
                continue
            table_data = dict(table)
            columns = []
            for column in table.get("columns") or []:
                column_name = str(column.get("column_name") or "")
                policy = column_permissions.get((table_name.lower(), column_name.lower()))
                # 列级权限:allowed=False 的列移除
                if policy and not policy.allowed:
                    continue
                column_data = dict(column)
                # 标记脱敏策略(供前端展示或执行结果脱敏)
                if policy and policy.masking_policy != "none":
                    column_data["masking_policy"] = policy.masking_policy
                columns.append(column_data)
            table_data["columns"] = columns
            filtered.append(table_data)

        logger.info(
            "permission filter_schema agent_id=%s datasource_id=%s "
            "original_tables=%s filtered_tables=%s",
            agent_id,
            datasource_id,
            len(schema),
            len(filtered),
        )
        return filtered

    async def validate_sql_access(
        self, agent_id: int | None, datasource_id: int | None, sql: str
    ) -> tuple[bool, str]:
        """SQL 执行前权限检查:验证 SQL 引用的表是否全部被允许。

        返回 (allowed, reason)。reason 为 "OK" 时表示通过。
        """
        if not agent_id or not datasource_id:
            return True, "OK"

        table_permissions = await self.get_table_permissions(agent_id, datasource_id)
        if not table_permissions:
            return True, "OK"

        # 提取 SQL 中 FROM/JOIN 引用的表名
        denied = [
            table
            for table in extract_table_references(sql)
            if not self.table_allowed(table, table_permissions)
        ]
        if denied:
            logger.warning(
                "permission validate_sql_access BLOCKED agent_id=%s datasource_id=%s denied_tables=%s",
                agent_id,
                datasource_id,
                denied,
            )
            return False, "无权访问表: " + "、".join(denied)
        return True, "OK"

    async def mask_rows(
        self,
        agent_id: int | None,
        datasource_id: int | None,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """对 SQL 执行结果中配置了脱敏策略的列进行脱敏。

        返回 (脱敏后的结果行, 被脱敏的字段及策略)。
        """
        if not agent_id or not datasource_id or not rows:
            return rows, {}

        column_permissions = await self.get_column_permissions(agent_id, datasource_id)
        # 构建需要脱敏的字段映射
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

        if applied:
            logger.info(
                "permission mask_rows agent_id=%s datasource_id=%s masked_columns=%s",
                agent_id,
                datasource_id,
                applied,
            )
        return masked_rows, applied

    async def get_table_permissions(self, agent_id: int, datasource_id: int) -> dict[str, bool]:
        """加载 agent 的表级权限规则。返回 {table_name_lower: allowed}。"""
        rows = await get_management_db().execute_query(
            "SELECT table_name, allowed FROM agent_table_permission "
            "WHERE agent_id = :aid AND datasource_id = :did",
            {"aid": agent_id, "did": datasource_id},
        )
        return {str(row["table_name"]).lower(): bool(row.get("allowed", 1)) for row in rows}

    async def get_column_permissions(
        self, agent_id: int, datasource_id: int
    ) -> dict[tuple[str, str], ColumnPolicy]:
        """加载 agent 的列级权限规则。返回 {(table_lower, col_lower): ColumnPolicy}。"""
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
        """判断表是否在白名单内。无白名单时默认允许。"""
        if not table_permissions:
            return True
        return bool(table_permissions.get(table_name.lower(), False))


def mask_value(value: Any, policy: str) -> Any:
    """按策略对单个值进行脱敏处理。"""
    if value is None:
        return None
    text = str(value)
    if policy == "hash":
        # SHA256 取前 12 位,不可逆但可比对
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    if policy == "partial":
        # 保留首尾各 2 字符,中间替换为 *
        if len(text) <= 4:
            return "*" * len(text)
        return f"{text[:2]}{'*' * max(len(text) - 4, 1)}{text[-2:]}"
    # redact:直接替换
    return "***"


# 全局单例
_permission_service: PermissionService | None = None


def get_permission_service() -> PermissionService:
    """返回进程级权限服务单例。"""
    global _permission_service
    if _permission_service is None:
        _permission_service = PermissionService()
    return _permission_service
