"""Prompt 模板数据模型 —— 定义节点提示词的配置化覆盖。

Prompt 模板用于把节点提示词从代码常量中抽出来,允许针对不同业务场景覆盖。
业务语义关键模板只按 model + semantic_domain + 全局解析；交互和输出类模板
仍可叠加 agent 作用域。
模板变量渲染失败时自动回退到代码内默认模板,避免配置错误打断问数链路。

当前支持的 prompt_key(见各节点 load_prompt 调用):
- intent_recognition.system:意图识别系统提示词
- semantic_enhance.system:语义增强系统提示词
- nl2lf_generate.system:LogicForm 生成系统提示词
- nl2sql_fallback.system:NL2SQL 兜底系统提示词
- phase3_python_generate.system:深度分析 Python 脚本生成提示词
- phase3_report_generator.system:深度分析 Markdown 报告生成提示词
"""

from pydantic import BaseModel, Field

# These prompts can change the business interpretation, query contract, or
# executable analysis. Existing Agent-scoped rows remain readable, but runtime
# resolution ignores them and new writes are rejected.
BUSINESS_SEMANTIC_PROMPT_KEYS = frozenset(
    {
        "intent_recognition.system",
        "semantic_enhance.system",
        "nl2lf_generate.system",
        "nl2sql_fallback.system",
        "phase3_python_generate.system",
        "phase3_python_generate.user",
    }
)
AGENT_SCOPED_INTERACTION_OUTPUT_PROMPT_KEYS = frozenset(
    {
        "phase3_python_analyze.system",
        "phase3_report_generator.system",
        "phase3_report_generator.user",
    }
)


def prompt_allows_agent_scope(prompt_key: str) -> bool:
    """Return whether a prompt may vary by the built-in validation Agent."""
    key = str(prompt_key or "").strip()
    if key in BUSINESS_SEMANTIC_PROMPT_KEYS:
        return False
    return key in AGENT_SCOPED_INTERACTION_OUTPUT_PROMPT_KEYS


class PromptTemplateBase(BaseModel):
    """Prompt 模板基础字段 —— Create/Update/Prompt 共用的字段定义。

    ``model_config_id`` / ``semantic_domain_id`` 可用于所有模板；``agent_id``
    仅用于交互或输出类模板，业务语义关键模板会由 service 层拒绝该组合。
    """

    prompt_key: str = Field(description="模板 key,如 nl2lf_generate.system")
    name: str = Field(description="模板展示名称")
    description: str | None = Field(default=None, description="模板说明")
    agent_id: int | None = Field(
        default=None,
        description="交互/输出类模板的适用智能体;业务语义关键模板不允许设置",
    )
    model_config_id: int | None = Field(
        default=None, description="适用模型配置;为空表示对所有模型生效"
    )
    semantic_domain_id: int | None = Field(
        default=None, description="适用语义层;为空表示对所有语义层生效"
    )
    template_text: str = Field(description="模板正文,支持 {variable} 占位符")
    status: str = Field(default="active", description="状态:active/disabled")


class PromptTemplateCreate(PromptTemplateBase):
    """Prompt 模板创建/更新入参。

    ``id`` 由调用方提供时表示更新,否则为新增。service 层会按
    (prompt_key, agent_id, model_config_id, semantic_domain_id) 唯一性去重。
    """

    id: int | None = Field(default=None, description="模板 id;提供时表示更新")


class PromptTemplateUpdate(PromptTemplateBase):
    """Prompt 模板更新入参 —— 用于 PUT 接口,需配合 path 中的 id 使用。"""

    pass


class PromptTemplate(PromptTemplateBase):
    """Prompt 模板完整记录 —— 对应 prompt_template 表的完整行。

    用于列表与详情查询返回。``created_at`` / ``updated_at`` 为字符串,
    因为直接透传数据库返回的 MySQL 时间戳格式。
    """

    id: int = Field(description="模板 id")
    created_at: str | None = Field(default=None, description="创建时间(数据库字符串格式)")
    updated_at: str | None = Field(default=None, description="更新时间(数据库字符串格式)")
