"""用户反馈数据模型 —— 定义问数结果的用户评分与备注。

反馈用于评估问数质量、定位 bad case、迭代 Prompt 与语义层资产。
一条反馈关联到具体的智能体、会话、链路 trace_id,并可携带上下文快照 payload,
便于后续复现与改进。
"""

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    """用户反馈入参 —— 用于 POST /api/feedback。

    ``payload`` 会原样入库,供后续评估脚本读取。注意 payload 中可能包含
    用户问题与部分查询结果,不应包含明文密钥(后端链路本身不会写入密钥)。
    """

    agent_id: int = Field(default=1, ge=1, description="反馈关联的智能体 id,必须大于 0")
    session_id: str | None = Field(
        default=None,
        description="会话 id,用于定位多轮对话中的具体一轮",
    )
    trace_id: str | None = Field(
        default=None,
        description="链路 trace_id,贯穿 SSE 事件与执行链路,用于精确定位某次问数",
    )
    rating: Literal["positive", "negative", "neutral"] = Field(
        default="neutral",
        description="评分:positive(满意)/negative(不满意)/neutral(中立)",
    )
    comment: str | None = Field(default=None, description="用户备注文本")
    payload: dict = Field(
        default_factory=dict,
        description="上下文快照,如 SQL/LogicForm/报告摘要,供后续评估与迭代使用",
    )
