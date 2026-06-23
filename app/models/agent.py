"""智能体数据模型 —— 定义智能体配置与创建入参。

智能体是问数链路的运行入口,决定可用数据源、绑定的大语言模型/向量模型、
以及默认语义层。本模块的模型用于 API 入参校验与数据库行映射。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """智能体完整配置 —— 对应 agent 表的完整行,用于详情查询返回。

    包含绑定关系(模型配置、语义层)的展示名称字段(由 JOIN 查询填充),
    供前端列表与详情页直接展示,无需二次查询。
    """

    id: int | None = None
    name: str = Field(description="智能体名称")
    description: str = Field(default="", description="智能体业务说明")
    chat_model_config_id: int | None = Field(
        default=None,
        description="绑定的大语言模型配置 id,决定问数链路使用哪个对话模型",
    )
    embedding_model_config_id: int | None = Field(
        default=None,
        description="绑定的向量模型配置 id,决定知识召回阶段使用哪个 embedding 模型",
    )
    semantic_domain_id: int | None = Field(
        default=None,
        description="绑定的默认语义层 id,决定问数链路使用的业务口径资产",
    )
    # 以下三个 *_name 字段由 JOIN 查询填充,仅用于前端展示,不入库
    chat_model_config_name: str | None = Field(default=None, description="大语言模型配置名(JOIN 填充,仅展示)")
    embedding_model_config_name: str | None = Field(default=None, description="向量模型配置名(JOIN 填充,仅展示)")
    semantic_domain_name: str | None = Field(default=None, description="语义层名称(JOIN 填充,仅展示)")
    semantic_domain_key: str | None = Field(default=None, description="语义层 key(JOIN 填充,仅展示)")
    default_questions: list[str] = Field(
        default_factory=list,
        description="智能体默认推荐问题,用于对话页快捷问题展示",
    )
    # 兼容旧字段:部分链路仍读取 agent.llm_provider/llm_model 作为兜底
    llm_provider: str = Field(default="ollama", description="兜底模型供应商,优先级低于 chat_model_config_id")
    llm_model: str = Field(default="qwen3:14b", description="兜底模型名,优先级低于 chat_model_config_id")
    api_key: str | None = Field(default=None, description="兜底 API Key(密文存储),优先级低于模型配置")
    api_key_enabled: bool = Field(default=False, description="是否启用兜底 API Key")
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentCreate(BaseModel):
    """智能体创建入参 —— 用于 POST /api/agent/create。

    与 AgentConfig 相比省略了 id/时间戳/JOIN 展示名,新增 ``datasource_ids``
    用于一次性绑定该智能体可访问的数据源集合。
    """

    name: str = Field(description="智能体名称")
    description: str = Field(default="", description="智能体业务说明")
    chat_model_config_id: int | None = Field(default=None, description="绑定的大语言模型配置 id")
    embedding_model_config_id: int | None = Field(default=None, description="绑定的向量模型配置 id")
    semantic_domain_id: int | None = Field(default=None, description="绑定的默认语义层 id")
    default_questions: list[str] = Field(
        default_factory=list,
        description="智能体默认推荐问题,用于对话页快捷问题展示",
    )
    datasource_ids: list[int] = Field(
        default_factory=list,
        description="该智能体可访问的数据源 id 列表,创建时一次性绑定",
    )
    llm_provider: str = Field(default="ollama", description="兜底模型供应商")
    llm_model: str = Field(default="qwen3:14b", description="兜底模型名")
