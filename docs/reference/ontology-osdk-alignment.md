# 问渠 WenQu Ontology / OSDK 对齐技术参考

> 基准日期：2026-09-10
>
> 文档性质：稳定技术参考，不维护产品排期和项目进度。
>
> 产品方向、优先级和验收状态唯一以 [产品路线图](../ontology-product-roadmap.md) 为准。

## 1. 这份文档解决什么问题

本项目借鉴 Palantir Ontology / OSDK 的核心思想，在 Agent 与数据库之间建立一层可复用的企业业务模型和类型化能力接口，但不要求接入 Palantir Foundry，也不把 SDK 本身当成产品目标。

本文只统一四件事：

1. Ontology、数据映射、孪生运行时和能力接口各自负责什么。
2. Query、Decision、Action 三类能力如何区分。
3. 当前代码如何映射到这些技术层级。
4. 后续实现必须遵守哪些稳定边界。

## 2. 技术分层

```text
业务领域
  ↓
企业模型（对象、属性、关系、状态、指标、规则、动作）
  ↓
数据映射（表、字段、关联路径、编码和计算口径）
  ↓
孪生运行时（对象实例、关系实例、当前状态、来源和运行记录）
  ↓
能力接口（Query / Decision / Action）
  ↓
内置验证 Agent / 第三方 Agent / 业务应用
```

| 层级 | 核心职责 | 不负责什么 |
|---|---|---|
| 业务领域 | 管理公司内部一组可独立建模、映射、发布和复用的业务范围 | 不是租户或企业空间 |
| 企业模型 | 用业务语言定义对象、关系、状态、指标、规则和动作合同 | 不直接等同于数据库表结构 |
| 数据映射 | 把企业模型稳定绑定到物理数据和计算实现 | 不重新定义业务含义 |
| 孪生运行时 | 将源数据转成有身份、有状态、有来源的业务对象实例 | 不替代生产业务数据库 |
| 能力接口 | 对调用方隐藏 SQL 和内部存储，提供稳定输入、输出和审计 | 不要求调用方先创建本项目 Agent |
| Agent / 应用 | 组合并消费已发布能力，处理具体场景 | 不拥有企业模型资产 |

## 3. Ontology 与 OSDK 的边界

Ontology Model 定义企业业务世界，包括：

- Object Type：客户、贷款账户、贷款申请单、风险事项等可稳定识别的业务对象。
- Property：对象的业务属性、主标识和展示属性。
- Link Type：对象之间的业务关系和基数。
- Metric / Rule / State：指标口径、业务规则和状态含义。
- Action Type：允许对对象执行的业务操作及其约束。

OSDK 的核心作用是让应用通过类型化接口访问已经定义好的对象、关系、函数和动作。因此本项目中的 OSDK-like 层是能力访问层，不是第二套对象建模层。

```text
Enterprise Model
    ├── Object / Property
    ├── Link
    ├── Metric / Rule / State
    └── Action
             ↓
Typed Capability Facade
             ↓
Agent / Report / Risk Workflow / External Application
```

“贷款申请”可以建模为对象，因为它代表一笔有唯一标识、属性、状态、关系和生命周期的业务记录；“提交申请”“审批通过”才是事件或动作。Ontology 对象不限于静态物理实体，也包括可独立追踪的业务记录、案件、订单和流程实例。

## 4. Query、Decision、Action 必须分开

| 能力 | 回答的问题 | 是否产生业务副作用 | 示例 |
|---|---|---:|---|
| Query Capability | 发生了什么、当前是什么状态、指标是多少 | 否 | 按申请状态统计数量 |
| Decision Capability | 应如何判断、原因和建议是什么 | 默认否 | 判断是否需要人工复核并返回依据 |
| Action Capability | 要执行什么业务操作 | 是 | 更新状态、创建事项、发起审批 |

稳定边界：

- Query 只能执行受控只读查询，不调用写入 Action。
- Decision 必须返回规则或模型版本、理由、置信度和人工边界，不能暗中产生写入。
- Action 必须在服务端校验参数、权限、审批引用、对象版本和前置条件。
- 三类能力使用不同的合同、错误和审计语义，不能为了方便全部命名为 Action。

## 5. 数据映射不是“给字段翻译”

语义映射要预先声明：

- 标准对象属性对应哪个表和字段。
- 对象主标识如何形成，跨系统身份如何对应。
- 业务关系通过哪个外键或受控 JOIN 路径实现。
- 指标使用什么事实粒度、计算表达式、时间字段和默认过滤条件。
- 枚举、单位、敏感字段、数据时效和质量边界是什么。

业务人员确认“它在业务上代表什么”；技术人员（包含数据库工程师）确认“如何从真实数据稳定取得”。SQL、物理字段和 LogicForm 是技术实现，不应成为业务定义本身。

运行时应优先消费已发布映射，不应每次依赖模型临时猜测表名、字段名或 JOIN 路径。只有语义未覆盖的调试场景，才允许进入受控 NL2SQL 兜底，并明确记录回退原因。

## 6. 当前代码对应关系

| 技术职责 | 当前主要实现 |
|---|---|
| 业务领域与统一模型版本 | `semantic_domain`、`model_release_service.py` |
| 查询语义资产 | `app/models/knowledge.py`、`semantic_runtime.py` |
| Ontology 定义与实例 | `app/models/ontology.py`、`ontology_service.py` |
| Ontology 与查询语义桥接 | `ontology_semantic_bridge.py` |
| LogicForm 校验与确定性 SQL 编译 | `lf_validate.py`、`lf_to_sql_compile.py` |
| 孪生同步与运行记录 | `twin_runtime_service.py`、`twin_sync_run` |
| Query Capability | `ontology_tools.py`、`capability_access_service.py` |
| Action 执行 | `execute_action()`、动作运行与审计记录 |
| 内置验证 Agent | `app/agent/`、`/agent`、`/chat` |

底层仍保留 `semantic_*` 与 `ontology_*` 两组兼容存储，但产品入口、领域归属、对象稳定 key 和统一发布版本必须保持一致。不能因为底层表尚未合并，就在产品上重新暴露两套平行业务模型。

## 7. 能力合同的最小要求

每个正式能力至少应固定：

- `domain_id` 与明确的 `model_release_id`。
- 稳定的 `capability_key`、输入 Schema 和输出 Schema。
- 目标对象、允许的指标/维度/关系或动作目标。
- 调用方身份、数据源、表列权限和脱敏规则。
- 标准错误类型和不泄露物理 SQL 的外部响应。
- `trace_id`、模型版本、调用结果和必要审计信息。

外部 Agent 或应用不需要创建内部验证 Agent。内置 Agent 只是一种参考调用方，用来证明同一能力合同可被不同客户端复用。

## 8. 实现时必须保持的不变量

- 企业模型独立于 Agent 生命周期；删除或更换 Agent 不删除领域资产。
- 物理表名和字段名不是对外业务合同。
- 正式查询固定使用已发布模型和确定性映射；不能静默读取未发布草稿。
- Query 不写数据，Action 不绕过服务端权限、审批、版本和事务校验。
- 对象主标识稳定且不可被普通实例编辑修改。
- `source_properties` 与本地动作形成的 `overlay_properties` 保持来源分离。
- 外部能力调用与内置验证调用应能定位到同一模型版本和业务口径。
- 当前项目不建设多租户、多企业空间，也不把风险交付或对话 Agent 反向定义为平台主线。

## 9. 官方参考

- [Palantir Ontology SDK Overview](https://www.palantir.com/docs/foundry/ontology-sdk/overview)
- [Palantir Ontology Functions and Query Functions](https://www.palantir.com/docs/foundry/functions/query-functions)
- [Palantir Ontology Type Reference](https://www.palantir.com/docs/foundry/object-link-types/type-reference)

本文不维护 P0/P1 等排期、完成数量或迭代记录。相关信息统一进入 [产品路线图](../ontology-product-roadmap.md)，当前技术实现以 [总体设计](../project-design.md) 和代码为准。
