"""系统参数数据模型 —— 定义运行时可调的参数与数据定位阈值。

系统参数运行时可调(无需重启),当前主要用于控制数据定位(schema_recall)
的召回行为。参数唯一真相源是 system_parameter 表,由
``SystemParameterService`` 加载并提供 30 秒进程内缓存。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SystemParameter(BaseModel):
    """系统参数完整记录 —— 对应 system_parameter 表的一行。

    ``value`` 字段按 ``value_type`` 解释:int/float/bool/string/json。
    供配置页展示与回写,实际运行时通过 ``SystemParameterService`` 取用。
    """

    key: str = Field(description="参数 key,如 schema_recall.max_tables")
    name: str = Field(description="参数展示名称")
    value: Any = Field(description="参数值,类型由 value_type 决定")
    value_type: str = Field(default="string", description="值类型:int/float/bool/string/json")
    category: str = Field(default="general", description="参数分组,如 schema_recall")
    description: str = Field(default="", description="参数业务说明")
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SystemParameterUpdate(BaseModel):
    """系统参数更新入参 —— 用于批量更新接口。

    只允许更新已有参数的值,不允许新增 key(service 层会校验)。
    """

    key: str = Field(description="要更新的参数 key")
    value: Any = Field(description="新的参数值")


class SchemaRecallSettings(BaseModel):
    """数据定位召回调参 —— 控制候选表的筛选行为。

    数据定位阶段先给所有候选表打分,再按相对阈值筛选:
    - 分数达到 ``required_score_ratio`` × 最高分的表为"必须召回",优先保留;
    - 介于 ``optional_score_ratio`` 与 ``required_score_ratio`` 之间的表,
      仅在名额不足时补充;
    - 低于 ``optional_score_ratio`` 的表不进入上下文;
    - 最终保留不超过 ``max_tables`` 张表。
    """

    max_tables: int = Field(
        default=6,
        ge=1,
        le=50,
        description="最多保留的候选表数量,过大会增加模型噪音",
    )
    required_score_ratio: float = Field(
        default=0.35,
        ge=0,
        le=1,
        description="必须召回相对分阈值(占最高分的比例),达到此阈值的表优先召回",
    )
    optional_score_ratio: float = Field(
        default=0.15,
        ge=0,
        le=1,
        description="可召回相对分阈值,低于此值的表不进入上下文",
    )

    @field_validator("optional_score_ratio")
    @classmethod
    def optional_not_above_required(cls, value: float, info):
        """校验可召回阈值不能大于必须召回阈值,避免筛选区间倒挂。"""
        required = (info.data or {}).get("required_score_ratio")
        if required is not None and value > required:
            raise ValueError("可召回阈值不能大于必须召回阈值")
        return value
