# DataQueryAgent Ontology / OSDK 对齐与增量改造计划

> 文档基准日期：2026-09-02
>
> 文档状态：增量开发中的架构与功能计划；作为当前实现和后续验收基线
>
> 当前范围：L1 Ontology Model、L2 Semantic Mapping、L3 Query Capability / Action Capability
>
> 后续范围：L4 MCP Hub、L5 Governance

本文把视频中“从专家维护到语义工程”的理念，与 Palantir 官方 Ontology SDK（OSDK）的职责边界进行对照，并落实为 `dataqueryAgent` 的增量改造计划。

本文采用的官方参考：

- [Palantir Ontology SDK Overview](https://www.palantir.com/docs/foundry/ontology-sdk/overview)
- [Palantir Ontology Functions and Query Functions](https://www.palantir.com/docs/foundry/functions/query-functions)
- [Palantir Ontology Type Reference](https://www.palantir.com/docs/foundry/object-link-types/type-reference)

本文不要求 `dataqueryAgent` 直接依赖 Palantir Foundry。若项目未接入 Foundry，则借鉴 OSDK 的设计思想，建设本项目自己的类型化语义访问层；只有在存在 Foundry Ontology 后端时，才讨论实际生成和接入 Palantir OSDK。

## 1. 决策摘要

### 1.1 总体判断

本项目不需要推翻已有问数、SQL 编译、报告和 Ontology 业务功能。改造采用增量方式：在现有自然语言问数链路和数据执行器之间增加统一的业务语义契约与能力适配层。

```text
保留现有：
前端、对话、LLM、LangGraph、LogicForm、确定性 SQL 编译、SQL 安全、权限、脱敏、报告

新增或重组：
标准业务对象 → 语义映射 → 查询能力契约 → 校验/确定性编译 → 现有只读执行器

后续扩展：
写入 Action、统一 Agent 能力出口、完整 capability 级人工确认、影子运行、灰度发布和治理
```

### 1.2 必须统一的术语

| 本项目概念 | 对齐后的职责 |
|---|---|
| Ontology Model | 定义对象类型、属性、关系和行为契约 |
| Semantic Mapping | 把标准语义绑定到现有表、字段、编码、指标和查询路径 |
| Generated OSDK / Typed Client | 面向应用和 Agent 的类型化访问层；不是对象建模层 |
| Query Capability | 校验并执行只读查询、过滤、关联、聚合和指标计算 |
| Action Capability | 创建、修改、审批等有业务副作用的写入操作 |

当前文档中将 L1 命名为 “Ontology SDK” 以及将只读查询称为 “Action” 的表述，需要按上表修正。

### 1.3 当前阶段的核心结论

当前 `dataqueryAgent` 重点不是重新建设一套对象 CRUD，而是：

1. 把已有的语义资产和 Ontology 对象建立稳定关联。
2. 把已有的 LogicForm / 确定性 SQL 编译提升为标准 Query Capability。
3. 保留已有 Ontology Action 作为写入能力，不与只读查询混用。
4. 让 Agent 先选择标准业务能力，再由适配层完成校验、确定性编译，并调用现有只读 SQL 执行器。

### 1.4 当前第一版 Query Capability 执行口径

`ontology_query_capability` 第一版直接完成一次受控的只读查询执行；查询计划和编译后的 SQL 是执行过程中的可解释信息：

```text
capability key + 业务参数
  → capability 解析与参数校验
  → LogicForm 校验
  → 确定性 SQL 编译
  → 复用现有 sql_execute_node 的简化只读流程
  → 返回查询结果、语义证据和执行 trace
```

第一版执行边界：

- 沿用现有 SQL 安全校验、数据源/表列权限和结果脱敏，不另起一套安全链路。
- 只允许受控的单条只读查询；Query Capability 不调用 `execute_action()`，也不写入对象或外部系统。
- 独立 Query Capability API 要求当前语义域的 `datasource_id` 非空且数据源属于该域所属 Agent；缺失时返回 400，跨 Agent 时返回 403，避免回退到默认 `business DB`。
- `execution.status` 取 `validation_blocked`、`security_blocked`、`permission_blocked`、`database_error` 或 `succeeded`；校验阻断时 `attempted=false`，进入 SQL 执行节点后 `attempted=true`，只有 `succeeded` 才设置 `executed=true`。
- 结果返回 `executed_sql`（SQL 执行节点规范化后的实际语句；未实际执行或失败时可能为空）和 `execution_trace`，其中保留服务端 `trace_id`、`domain_id`、`datasource_id`、Query Capability 及 Ontology `release`。
- 现有 Chat 图的 SQL 确认开关和 HITL 门禁继续保留；独立 `ontology_query_capability` 第一版不进入该确认门禁，而是按简化流程直接执行只读 SQL。本版本不新增完整的 capability 级人工确认、影子运行或发布治理。

## 2. 面向业务和管理层的价值

本项目的汇报重点不应是“引入 SDK”或“增加本体表”，而应是把问数能力从一次性问答工具升级为可复用的企业业务语义基础设施。

### 2.1 业务人员能看到的变化

| 当前问题 | 改造后的可见结果 |
|---|---|
| 需要知道数据在哪个系统 | 直接使用“客户、订单、库存、风险率”等业务语言提问 |
| 同一指标可能有不同算法 | 指标口径集中定义，结果更一致 |
| 新问题经常需要 IT 重写 SQL | 复用已有对象、指标、映射和 Query Capability |
| CRM、业务库、报表数据彼此割裂 | 通过统一对象和关系形成跨系统业务视图 |
| 查询结果难以说明依据 | 返回数据来源、时间范围、指标口径和执行轨迹 |
| 专家经验依赖个人 | 业务术语、对象定义和查询规则沉淀为团队资产 |

### 2.2 当前阶段可承诺的收益

L1-L3 阶段先承诺可验证的只读问数收益：

```text
用户可以用业务语言提问
同一指标使用同一口径
高频问题可以复用已有查询能力
跨对象和跨数据源问题有明确的查询路径
查询结果能够解释来源和使用的语义资产
```

L4-L5 的多 Agent 统一调用、集中审计、版本治理和持续发布属于后续收益，不作为当前第一阶段的交付承诺。

### 2.3 建议的业务验收指标

先建立现状基线，再比较改造后的变化：

- 高频问题一次查询成功率。
- 指标口径一致率。
- 跨系统问题覆盖数量。
- 新增一个业务问题的平均交付时间。
- 人工改写 SQL 或人工补充字段的次数。
- 能返回来源和口径说明的查询比例。
- 语义路径命中后进入 NL2SQL 兜底的比例。

## 3. 官方 OSDK 思想的准确边界

### 3.1 Ontology Model、OSDK 和应用不是同一层

官方 OSDK 的核心定位是：根据已定义的 Ontology 生成面向应用的类型化访问接口。应用通过这些接口访问对象、链接、函数和动作；对象类型、属性、链接类型和 Action 类型属于 Ontology 模型本身。

因此，在 `dataqueryAgent` 中应保持以下关系：

```text
Ontology Model
    ├── Object Type / Property
    ├── Link Type
    ├── Query Function / Function Contract
    └── Action Type
             ↓
Typed Capability Facade（本项目的 OSDK-like 适配层）
             ↓
DataQueryAgent / Report / Risk Workflow
```

本项目现有的 `app/models/ontology.py` 和 `app/services/ontology_service.py` 已经承担了部分 Ontology Model 与运行时职责；它们不需要被 OSDK 概念替换。

### 3.2 Query Capability 与 Action Capability 必须分开

当前项目有两种不同的能力：

```text
只读：
查询对象、筛选、按关系关联、指标聚合、生成 SQL、返回结果

写入：
创建工单、更新对象、发起审批、改变状态、产生外部副作用
```

前者应归入 `Query Capability`，后者才归入 `Action Capability`。对 `dataqueryAgent` 当前阶段，先建设只读 Query Capability；已有 `ontology_action_type` 和 `execute_action()` 作为后续写入能力保留。

### 3.3 Semantic Mapping 不是大模型临时猜字段

语义映射的作用是预先声明：标准对象、属性、指标和关系如何落到物理数据。运行时 Agent 应消费已经定义的映射和能力，不应每次根据问题临时猜表名、字段名或 JOIN 路径。

本项目现有的 `semantic_mapping`、`semantic_relation`、`semantic_metric` 和已采集 schema 已经具备这类基础能力，但目前它们与 Ontology 对象类型之间仍是松散并列关系，需要增加稳定的桥接语义。

## 4. 当前项目基线

### 4.1 已有能力与对应层级

| 现有能力 | 主要位置 | 对应层级 | 当前判断 |
|---|---|---|---|
| 语义领域、概念、指标、规则、映射、模板 | `app/models/knowledge.py`、`app/services/semantic_runtime.py` | L1/L2 | 已有查询语义资产 |
| LogicForm | `app/models/knowledge.py`、`app/agent/nodes/nl2lf_generate.py` | L3 Query | 已有查询中间表示 |
| LogicForm 校验 | `app/agent/nodes/lf_validate.py`、`SemanticRuntimeService.validate_logic_form()` | L3 Query | 已有确定性校验 |
| 确定性 SQL 编译 | `app/agent/nodes/lf_to_sql_compile.py`、`compile_logic_form()` | L3 Query | 应直接复用 |
| 对象类型和属性 | `app/models/ontology.py`、`ontology_object_type` | L1 | 已有基础对象模型 |
| 关系类型和关系实例 | `ontology_link_type`、`ontology_link` | L1/L2 | 已有关系模型与实例 |
| 动作类型和动作执行 | `ontology_action_type`、`execute_action()` | L3 Action | 已有写入原型，边界较清晰 |
| 发布快照 | `ontology_release`、`publish_domain()` | L5 前置能力 | 已有原型，运行绑定仍需完善 |
| Agent 本体上下文 | `build_agent_context()`、`ontology_evidence.py` | Agent 适配 | 已有上下文压缩和召回 |
| Agent 工具 | `app/agent/ontology_tools.py` | L3/L4 前置 | 已有对象查询、只读 Query Capability 和 Action 工具 |
| Schema 召回 | `app/agent/nodes/schema_recall.py` | L2 适配 | 仍以物理 schema 召回为主 |
| 持久任务和动作路由 | `app/agent/graph.py`、`app/agent/react.py` | 横向运行时 | 可继续复用 |

### 4.2 当前最重要的结构性问题

项目并不是缺少 Ontology，而是存在两套语义资产体系：

```text
语义运行时：
SemanticConcept / SemanticMetric / SemanticMapping / SemanticRelation
                 ↓
LogicForm → 确定性 SQL

Ontology 运行时：
OntologyObjectType / OntologyProperty / OntologyLinkType / OntologyActionType
                 ↓
对象实例查询 → Action 执行
```

当前 `semantic_runtime_recall_node` 会同时加载两套上下文，`nl2lf_generate` 也能看到二者，但二者尚未形成一个明确的统一契约。下一阶段的目标不是立即合并数据库表，而是先建立如下桥接：

```text
Ontology Object Type
    ↔ Semantic Concept
    ↔ Metric / Mapping / Relation
    ↔ Query Capability
```

### 4.3 贷款演示域第一版指标对象归属

贷款演示域的 12 个指标统一采用显式 `object_key` 声明业务归属。`object_key` 表示指标所描述的标准业务对象，不能由物理 `base_table`、表名相似度或模型临时推断替代；物理数据来源仍由 L2 mapping 和指标表达式负责。

| `metric_key` | 第一版 `object_key` | 第一版口径说明 |
|---|---|---|
| `approval_rate` | `LoanApplication` | 审批通过申请数占申请总数 |
| `application_count` | `LoanApplication` | 按贷款申请笔数统计 |
| `disbursement_amount` | `LoanAccount` | 按贷款账户实际放款本金统计 |
| `outstanding_balance` | `LoanAccount` | 按贷款账户当前未偿本金统计 |
| `m1_plus_rate` | `RepaymentPeriod` | 按还款期次的 M1+ 逾期表现统计 |
| `mob` | `LoanAccount` | 表示贷款账户放款后的账龄 |
| `dpd` | `LoanAccount` | 表示贷款账户当前逾期天数 |
| `vintage` | `LoanAccount` | 按贷款账户放款月份/批次观察表现 |
| `pd` | `LoanApplication` | 表示申请阶段的预测违约概率 `model_pd` |
| `dti` | `CustomerRiskSnapshot` | 表示客户月度风险快照中的负债收入比 |
| `writeoff_amount` | `LoanAccount` | 按贷款账户核销金额统计 |
| `collection_recovery_rate` | `CollectionCase` | 按催收案件的回收本金与入催本金统计 |

上述归属是**合成演示数据的第一版口径**，用于先跑通 Ontology → Mapping → Query Capability 的闭环，不代表真实贷款或财税业务的最终定义。后续接入真实数据时，仍需由业务负责人确认指标粒度、分母分子、时间口径和跨对象关系，并通过发布/治理流程替换或确认该口径。

## 5. 目标架构

### 5.1 L1：Ontology Model / Semantic Contract

L1 定义企业业务世界中的稳定概念：

- 对象类型，例如 `Customer`、`LoanApplication`、`LoanAccount`、`RiskIssue`。
- 对象属性、数据类型、主标识和展示属性。
- 对象之间的链接类型和基数。
- 对象别名、业务术语和消歧信息。
- 指标、状态和业务口径所引用的对象。
- 查询能力和写入 Action 的目标对象。

L1 的核心问题是：

> 用户说的业务概念，在系统中到底对应哪个标准对象？

### 5.2 L2：Semantic Mapping / Backing Data Mapping

L2 把 L1 语义绑定到真实数据：

- 对象属性到物理字段的映射。
- 对象主标识和跨系统身份映射。
- 链接类型到外键或关联路径的映射。
- 指标到受控表达式、事实表和时间字段的映射。
- 编码、单位、枚举和默认过滤条件。
- 数据源、表、字段、时效和质量说明。

L2 的核心问题是：

> 这个标准业务对象和指标，如何稳定地从现有数据库或接口取到真实数据？

### 5.3 横向：Typed Capability Facade

这是本项目借鉴 OSDK 思想新增的适配边界，不是新的数据存储层。

它负责：

- 根据稳定的 capability key 暴露查询或 Action。
- 校验输入参数和输出结构。
- 调用现有 `SemanticRuntimeService`、`OntologyService` 或其他执行器。
- 返回标准化结果和执行元数据。
- 隔离底层 SQL、数据库和接口实现。

### 5.4 L3a：Query Capability

只读查询能力包括：

- 对象实例查询。
- 属性过滤和排序。
- 关系关联和路径查询。
- 指标聚合、排名、趋势和对比。
- 时间窗口和组织范围查询。
- Query Function 风格的固定业务查询。

当前第一版 Query Capability 的最小执行闭环直接包裹现有查询链路：

```text
LogicForm
  → validate_logic_form()
  → compile_logic_form()
  → sql_execute_node（简化只读执行流程）
  → 查询结果与执行 trace
```

第一版不需要重写 SQL 编译器，也不新增独立的数据库访问实现。结果中的 `compiled_plan.sql` 保留确定性编译输出，`executed_sql` 记录 `sql_execute_node` 返回的规范化实际语句（未实际执行或失败时可能为空）；Query Capability 成功的语义是已通过安全/权限检查并完成只读执行。

### 5.5 L3b：Action Capability

写入能力包括：

- 创建或更新对象。
- 修改对象状态。
- 创建风险事项或维修工单。
- 发起审批。
- 调用外部业务系统。

现有 `OntologyActionTypePayload`、`execute_action()`、角色校验、审批引用、乐观版本校验和动作审计继续作为基础实现。只读查询不得复用写入 Action 的命名和执行语义。

## 6. 兼容性和增量改造原则

### 6.1 保留既有业务入口

以下接口和体验在第一阶段保持不变：

- ChatView 和 SSE 流式问数。
- 现有 Agent 配置、数据源绑定和语义域绑定。
- LogicForm 结构和确定性 SQL 编译。
- SQL 安全校验、权限和脱敏；现有 Chat 图的 SQL 执行确认继续由其 HITL 门禁处理。
- 独立 Query Capability 第一版按简化流程直接执行只读 SQL，不等待 Chat 图的 SQL 确认；完整 capability 级人工确认后置。
- Python 分析和报告生成。
- Ontology 工作台的对象、关系、动作和发布功能。

### 6.2 采用适配而不是平行重建

新增能力优先通过 facade / adapter 包装现有服务：

```text
QueryCapabilityExecutor
    → SemanticRuntimeService.compile_logic_form()
    → 现有 SQL 执行链路

ActionCapabilityExecutor
    → OntologyService.execute_action()
    → 现有权限、事务和审计链路
```

### 6.3 先复用现有执行链路，再扩展影子切换

第一版先把 Query Capability 接入现有只读执行链路，同时保留旧链路作为兜底：

1. 新语义层解析 capability、校验业务参数和 LogicForm。
2. 使用确定性编译器生成 SQL，并复用 `sql_execute_node` 的简化只读执行流程获取结果。
3. 记录命中的对象、指标、映射、capability、SQL 和执行 trace。
4. 对话主链路仍按现有规则决定是否进入受限 NL2SQL 兜底；独立 Query Capability 调用直接返回可解释的校验/权限/执行错误，不在工具内部绕过只读边界。
5. 后续影子运行阶段再对新旧路径分别执行并比较结果，不把影子运行作为第一版 Query Capability 的前置条件。

### 6.4 不提前引入真实 Palantir OSDK 依赖

当前项目没有 Foundry Ontology 后端时，直接引入 Palantir OSDK 不会自动解决本项目的 MySQL、语义资产和权限问题。第一阶段建设本项目自己的 OSDK-like typed facade，等数据后端和业务边界明确后再评估外部 SDK 或标准交换格式。

## 7. 增量改造功能点

以下功能点是下一步代码开发的边界。优先级分为：

- `P0`：第一轮代码开发必须完成，包含 Query Capability 的实际只读执行闭环。
- `P1`：第一轮验证后接入。
- `P2`：L4/L5 或写入能力扩展。

### 7.1 P0：统一语义上下文

| 功能点 | 现有复用 | 增量工作 | 验收标准 |
|---|---|---|---|
| 统一运行时上下文 | `semantic_runtime_recall_node`、`build_agent_context()` | 定义统一 `query_context` 结构，明确对象、属性、关系、指标、映射和能力的来源 | 一次查询可以明确列出命中的 Ontology 对象和语义资产 |
| 对象与概念桥接 | `SemanticConcept`、`OntologyObjectType` | 为概念增加可选 canonical object key 或等价映射，不立即合并表 | “客户/借款人/Customer”能归一到同一标准对象 |
| 别名和术语入口 | `synonyms`、Ontology description | 统一别名召回和消歧字段，避免分别在多个节点维护词表 | 别名在语义召回、LogicForm 生成和 schema 召回中一致生效 |
| 发布版本标记 | `ontology_release`、语义快照 | 在查询上下文和执行 trace 中同时记录语义域与 Ontology release | 结果可以定位到使用的语义定义版本 |

### 7.2 P0：把现有查询链路提升为 Query Capability

| 功能点 | 现有复用 | 增量工作 | 验收标准 |
|---|---|---|---|
| Query Capability 契约 | `LogicForm`、`LogicFormTemplate`、`SemanticMetric` | 定义 capability key、目标对象、支持指标/维度、输入槽位、输出结构和执行策略 | 每个高频查询都有稳定 capability key |
| 查询能力注册表 | 现有语义领域资产 | 第一版可从现有模板和指标组合生成内存注册表，暂不强制新增数据库表 | Agent 能按 capability key 找到可执行查询 |
| Query Capability 执行器 | `compile_logic_form()`、`lf_to_sql_compile_node`、`sql_execute_node` | 增加 facade，统一调用 capability/LogicForm 校验、确定性编译和现有简化只读执行链路 | 成功调用返回真实只读结果和 `executed=true`；阻断或失败返回明确状态，且不改变既有 SQL 安全、权限和脱敏行为 |
| 只读查询工具 | `ontology_query_objects`、现有 SQL 执行流程 | 新增独立的 `ontology_query_capability` 执行入口；对象实例查询工具继续保留 | Query 工具校验通过后执行只读 SQL，不能修改对象，未知参数被拒绝 |
| 结果契约 | `CompiledQuery`、`execution_trace` | 增加 capability、对象、指标、来源、口径和 warnings 字段 | 前端和审计可以解释一次查询用了什么能力 |

### 7.3 P0：让 Agent 按语义选择能力

| 功能点 | 现有复用 | 增量工作 | 验收标准 |
|---|---|---|---|
| NL2LF 语义约束 | `nl2lf_generate.py`、`nl2lf_generate.system.md` | Prompt 明确要求只输出 canonical asset key，不输出物理表字段作为业务语义 | LogicForm 的指标/维度/过滤仍引用语义 key |
| 对象和关系上下文 | `ontology_evidence.py` | 把命中的对象和关系以受控上下文提供给 NL2LF | 生成结果能标注目标对象和关系路径 |
| 查询能力选择 | `react.py`、`graph.py` | 在查询前增加 capability resolution；仍由代码白名单控制最终动作 | Agent 选择只读能力时不调用写入 Action |
| 语义校验扩展 | `validate_logic_form()` | 校验对象范围、指标支持的维度、关系路径和 capability 参数 | 不支持的组合在 SQL 执行前被阻断 |
| 旧链路兜底 | `nl2sql_fallback.py` | 明确只有语义未命中或编译失败才进入兜底，并记录原因 | 新链路失败不影响现有可用问数能力 |

### 7.4 P0：把 L2 映射从“召回提示”提升为“执行依据”

| 功能点 | 现有复用 | 增量工作 | 验收标准 |
|---|---|---|---|
| 对象属性映射 | `semantic_mapping`、`SemanticMapping` | 增加对象属性与 mapping 的明确关系 | 对象属性可反查物理字段或受控表达式 |
| 关系路径映射 | `semantic_relation.join_path`、`OntologyLinkType` | 建立业务链接与 SQL join path 的桥接 | 多表查询不依赖模型自由拼接 JOIN |
| 指标对象归属 | `SemanticMetric`、`SemanticConcept` | 为指标声明适用对象和维度边界 | 指标只能在支持的对象/维度上使用 |
| Schema 召回定位 | `schema_recall.py` | Ontology/mapping 命中优先，文本 schema 召回作为补充和验证 | 本体已明确映射时不因表名相似度被替换 |
| 数据质量提示 | `schema_scope`、执行 trace | 记录缺失映射、字段冲突、无数据和过期信息 | 用户看到可理解的限制说明，不是裸 SQL 错误 |

### 7.5 P0/P1：统一 Agent 工具和应用访问层

`ontology_query_capability` 的最小可执行闭环属于 P0；其余应用访问层标准化、扩展错误模型和跨应用复用属于后续 P1 工作。

| 功能点 | 目标 |
|---|---|
| `ontology_query_capability` | 以 capability key 和业务参数完成校验、确定性编译并执行只读查询；成功结果标识 `executed=true` |
| `ontology_query_objects` | 保留为对象实例搜索工具，不承担指标查询 |
| `ontology_execute_action` | 保留为写入 Action 工具，权限、审批和版本校验不交给模型 |
| `agent-context` 扩展 | 同时返回 object types、link types、query capabilities 和按角色过滤的 actions |
| Typed facade | 为 Chat、Agent、报告和风险流程提供统一调用入口 |
| 统一错误模型 | 区分语义不匹配、无数据、权限不足、参数错误、执行失败和系统错误 |

独立 Query Capability API 在进入工具执行前校验 `datasource_id` 非空且属于当前领域所属 Agent；执行结果使用 `validation_blocked`、`security_blocked`、`permission_blocked`、`database_error` 和 `succeeded` 区分阶段，成功时才返回 `executed=true`，并保留 `executed_sql`、`trace_id`、领域/数据源及 Ontology `release` 信息。

### 7.6 P1：影子运行和切流控制

这是第一版执行闭环稳定后的后续控制能力，不是当前 Query Capability 能否执行的前置条件：

- 对同一批问题分别执行旧路径和新 Query Capability 路径。
- 比较对象、指标、维度、过滤、SQL、结果摘要和执行耗时。
- 记录差异原因，而不是只记录成功或失败。
- 先对低风险只读问题开启新路径。
- 提供按 Agent、语义域和 capability 的开关。
- 保留旧路径回退，直到新路径达到验收指标。

### 7.7 P1：测试和评估

新增一组以业务问题为中心的语义测试集，每条测试至少包含：

```text
原始问题
预期标准对象
预期指标/维度/关系
预期 capability key
预期数据源或表范围
预期 LogicForm
结果校验规则
```

测试重点：

- 同义词和别名是否归一。
- 多轮追问是否复用正确语义而不复用过期 SQL。
- 指标和维度不兼容时是否阻断。
- 跨表关系是否使用已定义 join path。
- Query Capability 是否永远只读。
- Query Capability 是否在校验和确定性编译后真正执行只读 SQL，并返回正确的执行状态。
- 贷款演示域 12 个指标是否均声明了预期的 `object_key`，其中 `m1_plus_rate` 为 `RepaymentPeriod`、`pd` 为 `LoanApplication`。
- Action Capability 是否仍通过角色、审批和版本校验。
- 新旧路径结果差异是否可解释。

### 7.8 P2：写入 Action 扩展

已有 Action 原型不需要在第一轮重写。后续只做边界增强：

- 将 Action Type 与目标对象、状态转换和业务结果绑定。
- 增加外部系统写回适配器。
- 增加幂等键、重试和失败补偿。
- 将审批、权限和完整 capability 级人工确认接入统一能力出口。
- 保持 Action 与 Query Capability 的工具、错误和审计模型分离。

## 8. 分阶段开发计划

### 阶段 0：文档和契约冻结

状态：已完成，作为当前代码开发和验收的文档基线。

交付：

- L1 改名为 Ontology Model / Semantic Contract。
- L2 明确为 Semantic Mapping / Backing Data Mapping。
- L3 拆分 Query Capability 和 Action Capability。
- 明确当前 Query Capability 在校验、确定性编译后执行只读 SQL，写入 Action 后置。
- 固定贷款演示域 12 个指标的第一版显式 `object_key` 归属。
- 冻结 `query_context`、Query Capability 和结果契约的字段范围。

### 阶段 1：统一语义上下文

目标：让一次问数任务同时拥有一致的对象语义和查询语义。

主要范围：

- `app/models/knowledge.py`：增加或整理查询能力相关的契约模型。
- `app/models/ontology.py`：补充对象语义关联所需的最小字段。
- `app/services/semantic_runtime.py`：提供统一上下文组装入口。
- `app/services/ontology_service.py`：提供稳定的已发布对象/关系/动作上下文。
- `app/agent/nodes/semantic_runtime_recall.py`：输出统一 `query_context`。
- `app/agent/ontology_evidence.py`：按统一上下文生成受控证据。

完成标准：

- 同一请求中对象、指标、映射和关系的 key 可互相追踪。
- Draft/deprecated 定义不会进入执行上下文。
- 现有 LogicForm 和 Ontology 工具测试不回归。

### 阶段 2：Query Capability 适配层

目标：把现有确定性 SQL 链路包装为可校验、可解释、可实际执行的只读业务能力。

主要范围：

- 新增 Query Capability registry/facade。
- 将 `LogicFormTemplate`、`SemanticMetric`、`SemanticMapping` 和 `SemanticRelation` 组合为查询能力定义。
- 将 `compile_logic_form()` 与 `sql_execute_node` 的简化流程组合为第一版执行器。
- 扩展 `execution_trace` 和历史结果中的语义证据。
- 增加并接通 `ontology_query_capability` 只读 Query 工具。

完成标准：

- 至少一组高频业务问题可以通过 capability key 执行。
- Chat 图生成 SQL 仍经过现有 SQL 安全、权限、脱敏和 SQL 确认门禁；独立 `ontology_query_capability` 按简化流程直接执行只读 SQL，但仍经过 SQL 安全、权限和脱敏校验。
- `ontology_query_capability` 成功时返回实际查询结果和 `executed=true`；校验失败或执行失败时返回明确状态和错误，不伪装成成功计划。
- Query 能力不会调用 `execute_action()`。

### 阶段 3：Agent 选择和影子切流

目标：让 Agent 按标准语义选择已可执行的查询能力，并在后续影子阶段验证新旧结果。

主要范围：

- `nl2lf_generate` 使用对象、指标、关系和 capability 上下文。
- `lf_validate` 增加 capability 级校验。
- `schema_recall` 使用 mapping 作为优先依据。
- ReAct 控制器增加 Query Capability resolution 动作或等价内部步骤。
- 在后续影子运行中分别执行新旧路径、比较结果、记录差异并按 Agent 切换。

完成标准：

- 高频问题的对象、指标、维度和 SQL 结果与基线一致。
- 语义命中问题的 NL2SQL 兜底率下降或原因更加清晰。
- 旧路径仍可作为回退。

### 阶段 4：Action Capability 收敛

目标：在查询能力稳定后，统一写入 Action 的调用契约。

主要范围：

- 保留现有 `OntologyActionType` 和执行事务。
- 统一 Agent 工具中的 Query/Action 错误模型。
- 接入审批、幂等、外部写回和补偿。
- 将动作结果纳入统一业务上下文和审计。

完成标准：

- Query 和 Action 在名称、权限、执行器和审计上完全分离。
- 未授权或未审批 Action 在模型无法绕过的服务层被阻断。

### 阶段 5：L4/L5 后续能力

以下能力保留为后续完整治理边界，不因第一版只读执行而提前承诺：

- 多 Agent 统一能力网关。
- MCP Hub / Ontology MCP 适配。
- Ontology、语义资产和 Query Capability 的分支审核、灰度发布和 CI/CD。
- 更细粒度的权限、调用审计和运营指标。
- 完整的 capability 级人工确认、审批编排和影子运行控制。

## 9. 建议的代码开发入口

第一轮代码开发不从数据库重构开始，而从一条可回放的只读查询闭环开始：

```text
一个业务域
  → 3 个核心对象
  → 2 条对象关系
  → 2～3 个核心指标 Query Capability（12 个演示指标先全部完成 `object_key` 归属声明）
  → 3 个 Query Capability
  → 10 条真实业务问题
  → 新旧路径结果对比
```

建议第一轮优先选择已有贷款风控演示域，因为它已经具备语义资产、LogicForm、确定性 SQL、Ontology 对象和测试数据；完成后再迁移到真实财税业务域。

第一轮拟涉及的代码边界：

| 模块 | 作用 |
|---|---|
| `app/models/knowledge.py` | 查询能力、查询上下文和结果契约 |
| `app/models/ontology.py` | 对象语义关联的最小扩展 |
| `app/services/semantic_runtime.py` | 语义资产与 Query Capability 的组装、校验和编译复用 |
| `app/services/ontology_service.py` | 已发布对象/关系上下文与 Action 运行时复用 |
| `app/agent/nodes/semantic_runtime_recall.py` | 生成统一查询上下文 |
| `app/agent/ontology_evidence.py` | 对象、关系和 capability 证据筛选 |
| `app/agent/nodes/nl2lf_generate.py` | 使用 canonical 语义 key 生成 LogicForm |
| `app/agent/nodes/lf_validate.py` | Query Capability 级校验 |
| `app/agent/nodes/schema_recall.py` | mapping 优先、schema 召回补充 |
| `app/agent/ontology_tools.py` | 增加可执行的只读 Query Capability 工具，保留 Action 工具 |
| `app/agent/graph.py` / `app/agent/react.py` | 将能力选择纳入受控路由 |
| `tests/` | 语义闭环、兼容性、只读边界和新旧结果对比 |

第一轮明确不改：

- 前端页面结构。
- MySQL 业务表结构。
- 现有 SQL 编译算法。
- 现有报告和 Python 分析链路。
- L4 MCP Hub 和 L5 完整治理。

## 10. 第一轮验收清单

### 语义一致性

- [ ] 用户业务别名能归一到标准对象。
- [ ] 指标、维度和关系使用 canonical key。
- [ ] 贷款演示域 12 个指标均有显式 `object_key`；`m1_plus_rate → RepaymentPeriod`、`pd → LoanApplication` 的第一版口径已固定并可追溯。
- [ ] Query Capability 能说明目标对象和使用的语义资产。
- [ ] 物理表名和字段名不会成为 Agent 的业务语义真相源。

### 查询正确性

- [ ] LogicForm 校验通过后才能进入 Query Capability 执行。
- [ ] SQL 由现有确定性编译器生成或经过现有受控兜底。
- [ ] `ontology_query_capability` 在校验和确定性编译后复用 `sql_execute_node` 的简化流程执行只读 SQL，并返回实际结果与执行状态。
- [ ] 查询结果与当前基线一致或差异有明确解释。
- [ ] 多轮 refine 不会错误复用旧 SQL。

### 只读边界

- [ ] Query Capability 不能写入对象或外部系统。
- [ ] Query 工具与 Action 工具名称和参数完全分离。
- [ ] Query Capability 沿用现有 SQL 安全校验、权限和脱敏；不得通过 `execute_action()` 绕过这些边界。
- [ ] Action 仍经过角色、审批、版本和事务校验。

### 兼容性

- [ ] 现有 Chat、SSE、SQL 确认、报告和风险流程不回归；独立 Query Capability 按简化流程直接执行只读 SQL。
- [ ] 语义未命中时旧 NL2SQL 兜底仍可用。
- [ ] 新路径失败可以回退，且 trace 中记录回退原因。

### 可解释性

- [ ] 结果包含对象、指标、维度、映射和 capability 信息。
- [ ] 结果包含语义域、发布版本或定义 hash。
- [ ] 无数据、无权限、语义不匹配和执行错误能区分。

## 11. 非目标

当前改造不追求：

- 让模型通过微调记住全部企业数据。
- 用 Ontology 替代业务数据库、数据仓库或 BI 系统。
- 一次性建立全企业完整本体。
- 立即接入 Palantir Foundry 或强制使用 Palantir OSDK。
- 立即重写所有 SQL、Prompt、前端和报告逻辑。
- 在 Query Capability 稳定前扩展大量写入 Action。
- 在第一版就完成完整 capability 级人工确认、影子运行、灰度发布和治理闭环。

## 12. 最终架构表述

对外和对内统一使用以下表述：

> `dataqueryAgent` 在保留既有问数和业务功能的基础上，引入企业 Ontology 的对象语义、语义映射和业务能力契约。第一阶段将现有 LogicForm 与确定性 SQL 编译提升为经过校验后可实际执行的只读 Query Capability，复用现有安全、权限、脱敏和 SQL 执行链路；现有 Chat 图的 SQL 确认继续保留，独立 Query Capability 第一版按简化流程直接执行只读 SQL；完整的 capability 级人工确认、影子运行和治理发布在后续阶段逐步补齐。
