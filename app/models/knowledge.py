"""语义层数据模型 —— 定义知识库资产、LogicForm 与编译产物。

本模块是 WenQu 语义层的"契约层",所有语义资产(领域/概念/指标/映射/规则/
关系/模板)、结构化查询意图(LogicForm)、校验结果与编译产物都在这里定义。

核心概念:
- ``SemanticDomain``:一个业务领域(例如"贷款风控"),归属企业空间并可被多个智能体消费。
- ``SemanticMetric`` / ``SemanticMapping`` / ``SemanticRelation`` / ``SemanticRule``
  / ``SemanticConcept`` / ``LogicFormTemplate``:语义资产,唯一真相源是管理库,
  运行时由 ``SemanticRuntimeService`` 加载。
- ``LogicForm``:把自然语言问题转成的结构化查询意图(指标/维度/过滤/排序/限制)。
- ``SemanticRuntime``:一次查询装载的完整语义上下文,贯穿校验、编译、修复链路。
- ``CompiledQuery``:LogicForm 经确定性编译产出的 SQL 与命中资产清单。

这些模型同时用于:
1. Pydantic 入参/出参校验(API 层)。
2. 数据库行映射(服务层)。
3. LangGraph 工作流状态字段(agent 节点)。
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# 语义资产类型,贯穿向量召回、CRUD、快照导入导出。
# 对应 ASSET_TABLES 中的 6 张物理表。
AssetType = Literal["concept", "relation", "metric", "rule", "mapping", "template"]


class SemanticDomain(BaseModel):
    """语义领域 —— 归属企业空间、可被多个智能体消费的业务知识域。

    一个 domain 聚合该业务域下的全部概念、指标、映射、规则、关系和模板,
    并可选地绑定一个默认数据源(用于资产物理字段校验)。领域通过
    ``agent_semantic_domain`` 与智能体建立多对多消费关系；
    ``agent.semantic_domain_id`` 继续表示智能体的默认领域。
    """

    id: int | None = None
    workspace_id: int | None = Field(
        default=None,
        description="所属企业空间;为空时由服务归入默认企业空间",
    )
    agent_id: int | None = Field(
        default=None,
        description="兼容字段:历史创建/归属智能体;领域实际通过关联表供多个智能体消费",
    )
    datasource_id: int | None = Field(
        default=None,
        description="默认绑定的数据源,用于校验资产中的物理表/字段是否已采集",
    )
    domain_key: str = Field(description="领域唯一标识(同一企业空间下唯一),用于 API 引用")
    name: str = Field(description="领域展示名称,例如'贷款风控'")
    description: str | None = Field(default="", description="领域业务说明,供配置页展示")
    status: str = Field(default="active", description="状态:active/disabled")
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SemanticConcept(BaseModel):
    """语义概念 —— 业务名词的统一定义。

    用于消歧与向量召回,例如把"不良贷款""逾期 90+"统一映射为同一个概念。
    概念本身不参与 SQL 编译,主要供指标、规则引用。
    """

    id: int | None = None
    domain_id: int = Field(description="所属语义领域")
    concept_key: str = Field(description="概念唯一标识")
    concept_type: str = Field(description="概念分类,如 entity/measure/attribute")
    name: str = Field(description="概念展示名称")
    description: str | None = Field(default="", description="概念业务说明")
    synonyms: list[str] = Field(default_factory=list, description="同义词列表,提升召回与改写命中率")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SemanticRelation(BaseModel):
    """语义关系 —— 两个概念/表之间的可JOIN路径。

    LogicForm 编译多表查询时,通过 ``join_path`` 自动推导 JOIN 条件,
    避免让模型自由拼接 JOIN。``conditions`` 可附加过滤条件。
    """

    id: int | None = None
    domain_id: int = Field(description="所属语义领域")
    relation_key: str = Field(description="关系唯一标识")
    relation_type: str = Field(description="关系类型,如 one_to_many/many_to_one")
    source_concept: str = Field(description="关系起点概念 key")
    target_concept: str = Field(description="关系终点概念 key")
    name: str = Field(description="关系展示名称")
    description: str | None = Field(default="", description="关系业务说明")
    join_path: list[dict[str, str]] = Field(
        default_factory=list,
        description=(
            "JOIN 路径,每项形如 {'left': 'table.col', 'right': 'table.col'},"
            "由编译器按顺序生成 JOIN ... ON"
        ),
    )
    conditions: list[dict[str, Any]] = Field(
        default_factory=list, description="附加 JOIN 过滤条件"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SemanticMetric(BaseModel):
    """语义指标 —— 可计算的业务度量,LogicForm 的核心槽位。

    指标描述"算什么",例如贷款申请笔数、不良率。``formula_sql`` 是相对
    ``base_table`` 的 SQL 片段,编译器会注入表别名并拼接聚合。``dimensions``
    列出该指标允许按哪些维度拆分,用于 LogicForm 校验。
    """

    id: int | None = None
    domain_id: int = Field(description="所属语义领域")
    metric_key: str = Field(description="指标唯一标识,LogicForm 中通过它引用")
    name: str = Field(description="指标展示名称")
    description: str | None = Field(default="", description="指标业务口径说明")
    synonyms: list[str] = Field(default_factory=list, description="同义词,提升召回命中率")
    metric_type: str = Field(default="measure", description="指标类型:measure(度量)/其他")
    formula_sql: str = Field(
        description=(
            "指标 SQL 表达式,可使用 {base} 占位代表 base_table 的别名,"
            "例如 'COUNT(*)' 或 'SUM({base}.`amount`)'"
        ),
    )
    aggregation: str | None = Field(
        default=None, description="聚合方式提示,如 SUM/COUNT/AVG,供前端展示"
    )
    base_table: str = Field(description="指标所在的事实表名,编译时作为 FROM 起点")
    time_field: str | None = Field(
        default=None,
        description=(
            "时间字段,形如 'table.col',用于时间粒度查询与相对时间窗口过滤;"
            "为空表示该指标不支持按时间拆分"
        ),
    )
    default_filters: list[dict[str, Any]] = Field(
        default_factory=list,
        description="指标默认过滤条件,编译时会自动拼到 WHERE,例如风控指标默认只算存量",
    )
    dimensions: list[str] = Field(
        default_factory=list,
        description="该指标允许的维度 asset_key 列表,LogicForm 引用未列入的维度会校验失败",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SemanticRule(BaseModel):
    """语义规则 —— 影响 LogicForm 生成与归一化的业务规则。

    通过 ``rule_type`` 区分用途,例如:
    - ``rewrite``:语义增强阶段的业务问法改写规则(见 ``expression.rewrites``)。
    - ``normalization``:过滤值归一化(如风险等级别名映射)。
    - ``logic_form``:LogicForm 后处理(增删指标/维度/排序等)。
    """

    id: int | None = None
    domain_id: int = Field(description="所属语义领域")
    rule_key: str = Field(description="规则唯一标识")
    rule_type: str = Field(description="规则类型:rewrite/normalization/logic_form 等")
    name: str = Field(description="规则展示名称")
    description: str | None = Field(default="", description="规则业务说明")
    expression: dict[str, Any] = Field(
        default_factory=dict,
        description="规则表达式,结构因 rule_type 而异(见各消费节点的解析逻辑)",
    )
    applies_to: list[str] = Field(
        default_factory=list, description="规则适用的 asset_key 或 metric_key 列表"
    )
    severity: str = Field(default="info", description="严重程度,预留扩展,当前仅作展示")


class SemanticMapping(BaseModel):
    """语义映射 —— 把 asset_key 映射到物理表字段或表达式。

    LogicForm 中的维度/过滤字段通过 asset_key 引用,编译器借助 mapping 把它
    解析成实际的 ``table.column`` 或 ``expression_sql``。是 LogicForm 与
    物理 schema 之间的桥梁。
    """

    id: int | None = None
    domain_id: int = Field(description="所属语义领域")
    asset_type: str = Field(description="映射对象类型,如 dimension/filter/time")
    asset_key: str = Field(description="映射唯一标识,LogicForm 通过它引用字段")
    table_name: str = Field(description="物理表名")
    column_name: str | None = Field(
        default=None, description="物理字段名;为空时必须提供 expression_sql"
    )
    expression_sql: str | None = Field(
        default=None,
        description=(
            "字段表达式,可使用 {base}/{alias} 占位,例如 'DATE({base}.`created_at`)';"
            "提供时优先于 column_name"
        ),
    )
    data_type: str | None = Field(default=None, description="字段数据类型,供前端展示")
    role: str = Field(
        default="field", description="字段角色:dimension/filter/time/field,影响校验规则"
    )
    filters: list[dict[str, Any]] = Field(
        default_factory=list, description="该映射附带的默认过滤条件"
    )


class LogicFormTemplate(BaseModel):
    """LogicForm 模板 —— 预定义的查询意图骨架。

    用于把高频问法(例如"本月不良率排名 Top10")直接映射为 LogicForm 槽位,
    减少对模型的依赖。``compile_strategy`` 描述如何填充槽位,
    ``examples`` 提供样例问句供召回匹配。
    """

    id: int | None = None
    domain_id: int = Field(description="所属语义领域")
    template_key: str = Field(description="模板唯一标识")
    intent_type: str = Field(description="意图类型,如 metric_query/ranking/trend")
    name: str = Field(description="模板展示名称")
    description: str | None = Field(default="", description="模板业务说明")
    required_slots: list[str] = Field(
        default_factory=list, description="必填槽位,如 metrics/dimensions"
    )
    optional_slots: list[str] = Field(default_factory=list, description="可选槽位")
    compile_strategy: dict[str, Any] = Field(
        default_factory=dict, description="编译策略,描述如何把模板填充成 LogicForm"
    )
    examples: list[str] = Field(default_factory=list, description="样例问句,供召回匹配")


class SemanticAssetPayload(BaseModel):
    """语义资产通用载荷 —— 用于资产 upsert/import 时的统一封装。"""

    asset_type: AssetType = Field(description="资产类型")
    data: dict[str, Any] = Field(description="资产字段,结构随 asset_type 变化")


class LogicFilter(BaseModel):
    """LogicForm 过滤条件 —— 单个 WHERE 谓词。

    ``field`` 是 asset_key(不是物理字段),编译时通过 mapping 解析。
    支持的 operator 见 ``semantic_runtime.ALLOWED_OPERATORS``。
    """

    field: str = Field(description="过滤字段 asset_key")
    operator: str = Field(default="=", description="操作符:=/!=/</>/in/like 等")
    value: Any = Field(description="过滤值,in 操作符时为列表")


class LogicSort(BaseModel):
    """LogicForm 排序项 —— 单个 ORDER BY 字段。"""

    field: str = Field(description="排序字段,必须来自 metrics 或 dimensions")
    direction: Literal["asc", "desc"] = Field(default="desc", description="排序方向")


class LogicTimeRange(BaseModel):
    """LogicForm 时间窗口 —— 支持相对周期或显式起止时间。

    相对周期(本月/上月/近三个月)由编译器转换为 DATE 表达式;
    显式 start/end 用于自定义时间区间。
    """

    type: str = Field(default="relative", description="时间类型:relative(相对)/absolute(绝对)")
    period: str | None = Field(
        default=None,
        description="相对周期标识,如 this_month/last_month/recent_3_months",
    )
    start: str | None = Field(default=None, description="绝对起始时间,ISO 字符串")
    end: str | None = Field(default=None, description="绝对结束时间,ISO 字符串")


class LogicForm(BaseModel):
    """LogicForm —— 自然语言问题的结构化查询意图。

    由 ``nl2lf_generate`` 节点生成,贯穿校验/编译/修复链路。它是模型输出与
    确定性 SQL 编译之间的中间表示,避免让模型直接写 SQL。

    - ``metrics``/``dimensions``/``filters`` 均引用 asset_key,不直接写物理字段。
    - ``grain`` 为 month/day 时,要求指标配置了 ``time_field``。
    - ``sort``/``limit`` 控制结果排序与截断。
    """

    intent_type: str = Field(default="metric_query", description="意图类型")
    domain_key: str | None = Field(default=None, description="领域 key,留痕用")
    metrics: list[str] = Field(default_factory=list, description="指标 metric_key 列表,至少一个")
    dimensions: list[str] = Field(default_factory=list, description="分组维度 asset_key 列表")
    filters: list[LogicFilter] = Field(default_factory=list, description="过滤条件列表")
    time_range: LogicTimeRange | None = Field(default=None, description="时间窗口")
    grain: str | None = Field(
        default=None, description="时间粒度:month/day,要求指标有 time_field"
    )
    sort: list[LogicSort] = Field(default_factory=list, description="排序项列表")
    limit: int | None = Field(default=None, description="结果行数限制,编译时会被截断到 1000")


class SemanticRuntime(BaseModel):
    """语义运行时 —— 一次查询装载的完整语义上下文。

    由 ``SemanticRuntimeService.build_runtime`` 构造,作为 graph state 的
    ``semantic_runtime`` 字段贯穿后续所有节点(校验、编译、修复、Schema 召回)。
    资产唯一真相源是管理库,不读取本地 JSON 或 seed 脚本。
    """

    domain: SemanticDomain = Field(description="当前语义领域")
    concepts: list[SemanticConcept] = Field(default_factory=list, description="概念资产")
    relations: list[SemanticRelation] = Field(default_factory=list, description="关系资产")
    metrics: list[SemanticMetric] = Field(default_factory=list, description="指标资产")
    rules: list[SemanticRule] = Field(default_factory=list, description="规则资产")
    mappings: list[SemanticMapping] = Field(default_factory=list, description="字段映射资产")
    templates: list[LogicFormTemplate] = Field(default_factory=list, description="模板资产")


class LogicFormValidation(BaseModel):
    """LogicForm 校验结果 —— 校验节点产出,决定是否进入编译或兜底。

    ``valid`` 为 False 时,``errors`` 会进入 NL2SQL 兜底或触发 LF 修复。
    ``used_assets`` 记录本次校验命中的资产,用于执行追踪。
    """

    valid: bool = Field(description="是否通过校验")
    errors: list[str] = Field(default_factory=list, description="错误清单,阻断编译")
    warnings: list[str] = Field(default_factory=list, description="警告清单,不阻断")
    used_assets: list[str] = Field(default_factory=list, description="命中的资产引用清单")


class CompiledQuery(BaseModel):
    """编译产物 —— LogicForm 经确定性编译后的 SQL 与追踪信息。

    由 ``SemanticRuntimeService.compile_logic_form`` 产出,``sql`` 可直接执行。
    ``used_assets``/``warnings`` 进入 execution_trace 供排障与前端展示。
    """

    logic_form: LogicForm = Field(description="编译所用的 LogicForm")
    sql: str = Field(description="编译产出的 MySQL SELECT 语句")
    used_assets: list[str] = Field(default_factory=list, description="命中的资产引用清单")
    warnings: list[str] = Field(default_factory=list, description="编译期警告")


class AgentKnowledge(BaseModel):
    """智能体知识文档 —— 旧版文档型知识条目,保留兼容。

    当前主链路使用语义层资产(指标/映射/规则等),此模型用于历史数据兼容。
    """

    id: int | None = None
    agent_id: int = Field(description="所属智能体")
    title: str = Field(description="文档标题")
    content: str = Field(description="文档正文")
    knowledge_type: str = Field(default="document", description="知识类型")
    chunk_count: int = Field(default=0, description="分块数量,预留向量索引用")
    created_at: datetime | None = None
