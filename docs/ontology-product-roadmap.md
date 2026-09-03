# 问渠 WenQu 企业本体数字孪生平台产品路线图

> 基准日期：2026-09-03

## 1. 项目目标

问渠 WenQu 的目标是建设 **Ontology 驱动的企业运营数字孪生与智能决策平台**。近期优先把企业本体、数据运行时和能力发布中心做扎实，使业务和技术团队可以共同完成：

1. 用对象、属性和关系表达公司的统一业务语义。
2. 用动作定义可执行的业务操作及其权限、参数、前置条件和状态变更。
3. 对本体进行校验、发布和版本留痕。
4. 录入或接入业务对象实例，并通过动作形成可审计的决策闭环。
5. 将已发布企业模型转化为 Query / Decision / Action Capability，供多个应用和 AI Agent 复用。

财税报告交付、贷款风控和智能问数是平台上的垂直应用与验证场景。Agent 是平台能力的消费者，不是本体资产的所有者；当前对话功能以演示为主。

本期不建设通用 RDF/OWL 推理引擎，也不建设复杂多 Agent 编排。产品定位是 Palantir 风格的运营本体：业务语义、数据状态、决策逻辑、动作和治理共同组成可运行的企业数字孪生。

## 2. 用户与核心流程

| 角色 | 核心任务 |
|---|---|
| 企业空间管理员 | 管理企业资产边界、成员、数据源和审计范围 |
| 业务领域负责人 | 定义对象、关系、业务动作并确认业务口径 |
| 数据工程师 | 配置对象属性与物理数据映射，治理对象身份 |
| 应用/Agent 开发者 | 订阅已发布领域，基于标准查询、决策和动作能力构建垂直应用 |
| 安全管理员 | 配置动作角色、审批边界并审计执行记录 |
| 业务操作员 | 浏览业务对象、提交动作、查看执行结果 |

主流程：进入企业空间 -> 选择业务领域 -> 建企业模型与数据映射 -> 校验发布 -> 同步对象状态 -> 发布业务能力 -> Agent/应用按授权调用 -> 审计与反馈。

### 2.1 企业空间与业务领域为什么必要

- **企业空间**解决资产归属和安全边界：模型、数据连接、能力和审计属于哪家企业。
- **业务领域**解决可管理范围：哪些对象、指标、规则、数据和能力可以由一组负责人独立发布。
- **Agent**解决场景交互：哪个 Agent 需要消费哪些已发布领域能力。

目标关系是“一份企业模型被多个 Agent 复用”，而不是“每个 Agent 私有一份本体”。P0 只提供默认企业空间、领域归属和 Agent-领域多对多兼容，不引入复杂组织树。

## 3. 已有 Ontology V1 原型基线

V1 定位为“可验证的本地运营本体闭环”，用于业务试点和产品验证，不等同于已经具备生产级外部系统写回、动态 ABAC 或分布式图运行时。

| 需求编号 | 功能 | V1 验收标准 | 验收证据 | 当前状态 |
|---|---|---|---|---|
| ONT-001 | Ontology 工作空间 | 复用语义领域；切换领域并查看本体概览 | `app/api/ontology.py`、`frontend/src/router/index.ts`、工作台 summary | 已验证 |
| ONT-002 | 对象与属性建模 | 对象 CRUD；类型、必填、主属性、显示字段可配置 | `app/models/ontology.py`、`app/services/ontology_service.py`、服务测试 | 已验证 |
| ONT-003 | 关系建模 | 定义 1:1、1:N、N:1、N:N 元数据；创建匹配类型的关系实例 | `app/services/ontology_service.py`、工作台图谱视图 | 已开发；基数强制约束列入 P2 |
| ONT-004 | 动作建模 | 配置目标对象、参数、前置条件、状态效果、角色和审批标记 | `app/models/ontology.py`、工作台动作编辑器 | 已开发；正式审批流列入 P3 |
| ONT-005 | 本体校验 | 检查主属性、对象/属性引用、动作效果和参数引用 | validate API、校验抽屉、`tests/test_ontology_service.py` | 已验证 |
| ONT-006 | 发布快照 | 校验通过后生成递增发布快照 | `ontology_release`、publish/releases API、发布阻断测试 | 原型完成；运行版本隔离/回滚列入 P1 |
| ONT-007 | 对象实例运行时 | 手工或 bundle 创建、更新、查询实例；校验类型和必填项 | object API、实例动态表单、幂等导入测试 | 已开发；批量同步/身份解析列入 P2 |
| ONT-008 | 动作执行 | 校验角色、审批引用、参数和前置条件；更新对象并保留前后状态 | execute API、动作弹窗、`tests/test_ontology_service.py` | 原型完成；事务/幂等/补偿列入 P3 |
| ONT-009 | 决策审计 | 查看执行人、参数、上下文、前后状态、结果和时间 | action-runs API、决策活动视图、E2E 回放 | 已开发；完整 release/trace 血缘列入 P3 |
| ONT-010 | Ontology 工作台 | 概览、图谱、对象、关系、动作、实例、活动七个视图 | `frontend/src/views/OntologyWorkbench.vue`、前端测试与构建 | 已验证（桌面/移动端） |
| ONT-011 | 导入导出与示例 | UI 导入/导出 bundle；供应链样例覆盖对象、关系、动作和实例 | `examples/supply_chain/ontology-bundle.json`、`scripts/verify_ontology_e2e.py` | 已验证（真实 API 回放） |
| ONT-012 | 自动化验证 | 后端单测、API 路由、前端契约、类型检查和生产构建通过 | `pytest`、`ruff`、`npm test`、`npm run build` | 已通过 |
| ONT-013 | Agent/应用上下文 | 为应用和 Agent 提供已发布对象定义、对象查询和受控动作工具 | `app/agent/ontology_tools.py`、`/agent-context` 和 `/agent-tools` API、`tests/test_ontology_tools.py` | 已验证 |

### 3.1 P0 平台兼容骨架

P0 不重写现有 Ontology、查询语义和问数链路，只调整产品主从关系并提供统一入口：

| 能力 | P0 第一版 | 明确不包含 |
|---|---|---|
| 企业空间与领域归属 | 默认企业空间、旧领域兼容归属、Agent-领域多对多消费关系 | 完整多租户组织树、领域负责人审批、跨领域依赖治理 |
| 企业模型中心 | 在同一入口管理原查询语义和本体建模资产 | 一次性合并所有底层表和服务 |
| 孪生运行 | 集中展示对象类型、实例和现有触发式同步能力 | 后台定时任务、CDC、身份解析、完整状态历史 |
| 能力发布中心 | 集中展示和调用现有对象查询、Query Capability、Action 工具 | 生产级网关、订阅、灰度、配额、SLA 和完整发布审批 |
| Agent 消费 | Agent 可绑定并消费一个或多个业务领域，保留旧默认领域兼容 | 复杂多 Agent 编排、长期记忆和大规模对话体验优化 |

## 4. V1 技术架构

| 层次 | 现有复用 | 本期新增 |
|---|---|---|
| 接入与数据 | 数据源、Schema 采集、MySQL 客户端 | 对象实例和关系实例运行时 |
| 资产归属 | 现有语义领域与 Agent 配置 | 默认企业空间、领域归属和 Agent-领域多对多兼容 |
| 企业模型 | 语义领域、概念、指标、映射、Ontology 对象和动作 | 统一产品入口和稳定关联边界 |
| 逻辑与动作 | 语义规则、LangGraph、权限角色 | 动作参数、前置条件、效果和执行器 |
| 治理 | JWT、管理员权限、语义快照 | 本体校验、发布快照、动作审计 |
| 体验 | Vue、Element Plus、ECharts | 企业模型、孪生运行和能力发布中心统一入口 |

### OSDK 术语边界

本项目借鉴 Palantir OSDK 的类型化能力访问思想，但不把 OSDK 当作本体建模层。当前开发统一采用以下边界：

- `Query Capability`：只读对象查询、过滤、关联、聚合、排名、趋势和指标计算；可由 `LogicForm` 与确定性 SQL 编译链路承载。
- `Action Capability`：创建、修改、审批、状态变更或其他有业务副作用的操作；由 `OntologyActionType` 和受控动作执行器承载。
- `Typed Capability Facade`：为 Chat、Agent、报告和风险流程提供统一的类型化访问契约，底层可以继续复用现有 SQL/API 和 Ontology 服务。

第一阶段优先建设 `Query Capability`，已有动作模型继续保留并作为后续写入能力；只读查询不得命名或实现为写入 Action。详细的对齐和增量开发计划见 [Ontology / OSDK 对齐与 DataQueryAgent 增量改造计划](./ontology-osdk-alignment-plan.md)。

## 5. 数据与动作契约

### 对象类型

- `object_key`：领域内稳定且唯一的英文标识。
- `primary_property`：实例业务主键，发布前必须存在。
- `display_property`：实例的人类可读展示字段。
- `properties`：支持 string、text、integer、number、boolean、date、datetime、json。

### 动作类型

- `parameters`：动作输入及 required/type/options 约束。
- `preconditions`：声明式条件，支持 eq/ne/in/not_in/gt/gte/lt/lte/exists。
- `effects`：把常量、动作参数、当前时间或当前用户写入目标对象属性。
- `allowed_roles`：当前支持 admin/user 角色约束。
- `requires_approval`：V1 记录审批要求；自动审批流在后续版本接入。

### 决策血缘

每次动作执行记录 Ontology 领域、动作、目标对象、执行人、参数、决策上下文、执行前状态、执行后状态、结果和时间。

## 6. 非功能验收

| 类别 | V1 标准 |
|---|---|
| 安全 | 定义管理和发布仅管理员可操作；动作执行按 allowed_roles 校验 |
| 一致性 | 实例更新使用版本号递增；动作执行保留 before/after 快照 |
| 可维护性 | 企业模型独立于 Agent 生命周期；删除或更换 Agent 不应删除领域资产 |
| 可用性 | 所有核心操作可在工作台完成，不要求直接编辑 JSON |
| 可测试性 | 声明式校验和动作效果有单元测试；前端通过类型检查和生产构建 |

## 7. 公司级产品化排期

以下周期是 2 人产品研发小组的粗略参考，需在真实数据源和首个领域确定后重新估算。当前优先级不是继续扩展对话，而是依次夯实企业模型、孪生运行和能力发布。

| 阶段 | 周期 | 交付内容 | 硬验收标准 | 当前状态 |
|---|---:|---|---|---|
| P0 兼容骨架 | 1 周 | 默认企业空间、领域归属、Agent 多对多绑定、三个统一入口 | 旧数据可用；现有问数和贷款演示不回归；页面不夸大能力 | 第一版已实现 |
| P1 企业模型中心 | 2-3 周 | 统一对象/指标/规则/映射/动作视图，模型校验、版本 diff/回滚和影响分析 | 一个真实领域完成建模、映射测试、发布和回滚；Agent 固定消费发布版本 | 已有基础，需产品化 |
| P2 孪生运行时 | 3-4 周 | 定时/增量同步、身份解析、当前/历史状态、数据质量、血缘和运行监控 | 真实数据稳定增量更新；冲突、坏数据、来源和更新时间可追溯 | 仅有触发式同步原型 |
| P3 能力发布中心 | 2-3 周 | Query / Decision / Action 契约、版本、权限、审计、限流和错误模型 | 外部 Agent 能按版本和权限稳定调用；越权和失败用例被阻断并留痕 | 已有 Query/Action 技术种子 |
| P4 垂直场景验证 | 4-6 周 | 真实领域、历史案例影子运行、受控动作和结果反馈 | 至少一个领域连续稳定运行；准确率、效率和可追溯性有基线与改善数据 | 未开始 |

## 8. 开源复用策略

GitHub 调研结论是保留现有 FastAPI/MySQL 运营运行时，按边界引入成熟项目，而不是整体替换产品层。

| 项目 | 许可证 | 适用能力 | 决策 |
|---|---|---|---|
| LinkML | Apache-2.0 | YAML 模型、JSON Schema/Pydantic/SQL/SHACL/OWL 生成与 CI 校验 | P1 做 schema source-of-truth PoC，优先采用 |
| OpenMetadata / DataHub | Apache-2.0 | 技术元数据、Glossary、血缘、Ownership、连接器 | P2 二选一作为治理侧车，不嵌入核心运行时 |
| TypeDB | MPL-2.0 | 强类型实体/关系、TypeQL、多跳图事务 | 只有图查询规模被验证后才做 sidecar benchmark |
| TerminusDB | Apache-2.0 | JSON-LD、版本 diff、Git-for-data | 借鉴发布/分支设计；有强版本化需求时 PoC |
| Ontop / RMLMapper | Apache-2.0 / MIT | R2RML、SPARQL-to-SQL、RDF/JSON-LD 导出 | 作为标准交换和离线迁移工具 |
| OpenSPG | Apache-2.0 | 中文知识构建、实体对齐、规则推理 | 后续知识抽取/符号推理专项 PoC |
| NocoDB | Sustainable Use License | 表格化实例编辑 UX | 不复用代码，许可证不适合商业产品嵌入 |

任何依赖进入主干前必须完成许可证确认、SBOM、安全扫描和最小 benchmark。

## 9. 上线指标

- 首个业务域从建模到发布不超过 5 个工作日。
- 一个已发布领域至少包含 3 个对象、2 个关系和 1 个可执行动作。
- 关键动作执行记录完整率 100%。
- 本体校验未通过时发布阻断率 100%。
- 试点流程人工切换系统次数和平均决策时长可被持续度量。

## 10. 本轮验收记录

2026-09-03 完成 P0 平台兼容骨架验证：

- 默认企业空间、业务领域归属、Agent-领域多对多绑定、孤立绑定清理和删除 Agent 保留企业资产的定向测试：`12 passed`；后端全量回归：`391 passed`，Ruff 通过。
- 企业模型、孪生运行和能力发布中心前端契约测试与生产构建通过。
- 孪生运行仍明确为手动分页同步；能力中心仍明确为现有 Query/Action 合同集中展示。

2026-08-29 在本地 MySQL 环境完成以下验证：

- `uv run pytest -q`：249 passed。
- `uv run pytest -q tests/test_ontology_tools.py`：3 passed。
- `npm test`：前端契约、视图和 Ontology 工作台测试通过。
- `npm run build`：`vue-tsc` 与 Vite 生产构建通过；仅有既有 chunk size 提示。
- `uv run ruff check app/api/ontology.py app/db/ontology_schema.py app/models/ontology.py app/services/ontology_service.py scripts/verify_ontology_e2e.py tests/test_ontology_service.py`：通过。
- `scripts/verify_ontology_e2e.py`：bundle 导入、校验、发布 V1、动作执行、审计查询和导出回放通过。
- 浏览器验收：桌面端图谱/对象表/动作弹窗和 390px 移动端布局通过。

上述验收针对 V1 本地运营本体 MVP；事务级外部系统写回、正式审批流、动态 ABAC、批量同步和多跳图运行时仍属于后续阶段，不作为当前小团队 MVP 的前置条件。

## 11. 信贷智能体 Demo

结合现有 `loan_risk` 语义问数域的可运行 Ontology 示例见：

- `examples/loan/ontology-bundle.json`：6 个信贷对象、6 条关系、3 个受控动作和演示实例。
- `examples/loan/ONTOLOGY_DEMO.md`：工作台逐步操作、问数与动作边界、REST 示例。
- `scripts/verify_loan_ontology_demo.py`：导入、校验、发布、审批、催收、结案和审计回放。
