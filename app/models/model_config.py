"""模型配置数据模型 —— 定义大语言模型与向量模型的连接配置。

模型配置统一走 OpenAI 兼容接口,``model_type`` 区分两类:
- ``chat``:大语言模型,用于意图识别、语义增强、LogicForm 生成、报告生成等。
- ``embedding``:向量模型,用于知识召回阶段的向量化。

智能体通过 ``chat_model_config_id`` / ``embedding_model_config_id`` 绑定,
未绑定时回退到环境默认配置(见 ModelConfigService.get_default)。

``api_key`` 以 ``enc:v1:`` 密文存储,编辑时不传新值会保留原密钥。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# 模型配置类型:chat=大语言模型,embedding=向量模型
ModelConfigType = Literal["chat", "embedding"]


class ModelConfig(BaseModel):
    """模型配置完整记录 —— 对应 model_config 表的完整行。

    ``api_key`` 在数据库中以密文存储,读取时由 service 层解密;
    API 出参时不返回明文,仅返回脱敏掩码与过期状态标志。
    """

    id: int | None = None
    name: str = Field(description="配置名称,如'生产对话模型'")
    model_type: ModelConfigType = Field(default="chat", description="模型类型:chat/embedding")
    provider: str = Field(
        default="ollama",
        description="供应商标识,如 ollama/deepseek/mimo/minimax/openai-compatible",
    )
    base_url: str = Field(description="OpenAI 兼容 Base URL,如 https://api.deepseek.com/v1")
    model_name: str = Field(description="模型名,如 qwen3:14b、deepseek-chat")
    api_key: str | None = Field(default=None, description="API Key(密文存储,service 层加解密)")
    api_key_enabled: bool = Field(
        default=False,
        description="是否启用 API Key;False 时走免 Key 调用(如本地 Ollama)",
    )
    api_key_expires_at: datetime | None = Field(
        default=None,
        description="API Key 过期时间;前端据此显示过期/即将过期提醒",
    )
    embedding_dimension: int | None = Field(
        default=None,
        description="向量维度,仅 embedding 类型有效,需与 Milvus collection 维度一致",
    )
    status: str = Field(default="active", description="状态:active/disabled")
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ModelConfigCreate(BaseModel):
    """模型配置创建入参 —— 用于 POST /api/model-config/create。

    ``api_key`` 传入明文,service 层负责加密落盘。
    ``embedding_dimension`` 仅当 model_type=embedding 时有意义。
    """

    name: str = Field(description="配置名称")
    model_type: ModelConfigType = Field(default="chat", description="模型类型")
    provider: str = Field(default="ollama", description="供应商标识")
    base_url: str = Field(description="OpenAI 兼容 Base URL")
    model_name: str = Field(description="模型名")
    api_key: str | None = Field(default=None, description="API Key 明文,入库前加密")
    api_key_enabled: bool = Field(default=False, description="是否启用 API Key")
    api_key_expires_at: datetime | None = Field(default=None, description="API Key 过期时间")
    embedding_dimension: int | None = Field(
        default=None, ge=1, description="向量维度,需大于 0,仅 embedding 有效"
    )
    status: str = Field(default="active", description="状态")


class ModelConfigUpdate(ModelConfigCreate):
    """模型配置更新入参 —— 继承 Create 的全部字段。

    与 service 层配合实现"不传 Key 保留原值":若传入的是掩码字符(* 或 •)
    或空值,service 层会保留数据库中原有的加密 Key。
    """

    pass
