"""Agent-level datasource permission configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MaskingPolicy = Literal["none", "redact", "partial", "hash"]


class TablePermissionRule(BaseModel):
    """One explicit table access rule."""

    table_name: str = Field(min_length=1, max_length=256)
    allowed: bool = True

    @field_validator("table_name")
    @classmethod
    def strip_table_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("表名不能为空")
        return value


class ColumnPermissionRule(BaseModel):
    """One explicit column visibility and masking rule."""

    table_name: str = Field(min_length=1, max_length=256)
    column_name: str = Field(min_length=1, max_length=256)
    allowed: bool = True
    masking_policy: MaskingPolicy = "none"

    @field_validator("table_name", "column_name")
    @classmethod
    def strip_names(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("表名和字段名不能为空")
        return value


class DatasourcePermissionReplace(BaseModel):
    """Complete replacement payload for one Agent and datasource pair."""

    table_permissions: list[TablePermissionRule] = Field(default_factory=list)
    column_permissions: list[ColumnPermissionRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_rules(self) -> "DatasourcePermissionReplace":
        table_keys = [rule.table_name.lower() for rule in self.table_permissions]
        if len(table_keys) != len(set(table_keys)):
            raise ValueError("同一张表不能重复配置权限")

        column_keys = [
            (rule.table_name.lower(), rule.column_name.lower())
            for rule in self.column_permissions
        ]
        if len(column_keys) != len(set(column_keys)):
            raise ValueError("同一个字段不能重复配置权限")
        return self


class DatasourcePermissionConfig(DatasourcePermissionReplace):
    """Stored permission configuration returned by the management API."""

    agent_id: int = Field(gt=0)
    datasource_id: int = Field(gt=0)
