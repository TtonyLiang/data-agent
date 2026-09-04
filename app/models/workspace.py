"""单公司部署的历史兼容容器数据模型。

它不是面向用户的多租户/多企业空间模型，业务资产实际按业务领域管理。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class EnterpriseWorkspace(BaseModel):
    id: int | None = None
    workspace_key: str = Field(description="内部兼容容器稳定标识")
    name: str = Field(description="内部兼容容器名称")
    description: str | None = Field(default="", description="内部兼容容器说明")
    status: str = Field(default="active", description="状态:active/disabled")
    created_at: datetime | None = None
    updated_at: datetime | None = None
