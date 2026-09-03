"""企业空间数据模型。

当前阶段的企业空间只是领域资产的最小逻辑容器，不承担完整多租户隔离。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class EnterpriseWorkspace(BaseModel):
    id: int | None = None
    workspace_key: str = Field(description="企业空间稳定标识")
    name: str = Field(description="企业空间名称")
    description: str | None = Field(default="", description="企业空间说明")
    status: str = Field(default="active", description="状态:active/disabled")
    created_at: datetime | None = None
    updated_at: datetime | None = None
