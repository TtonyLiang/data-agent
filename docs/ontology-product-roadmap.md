# 问渠 WenQu 企业本体产品需求与排期

## 1. 项目目标

在问渠 WenQu 企业本体智能平台上持续建设本体建模与运行能力，使业务和技术团队可以共同完成：

1. 用对象、属性和关系表达公司的统一业务语义。
2. 用动作定义可执行的业务操作及其权限、参数、前置条件和状态变更。
3. 对本体进行校验、发布和版本留痕。
4. 录入或接入业务对象实例，并通过动作形成可审计的决策闭环。
5. 将已发布 Ontology 作为问数、应用和 AI Agent 的统一业务上下文。

本期不建设通用 RDF/OWL 推理引擎。产品定位是 Palantir 风格的运营本体：业务语义、决策逻辑、动作和治理共同组成可运行的业务模型。

## 2. 用户与核心流程

| 角色 | 核心任务 |
|---|---|
| 业务领域负责人 | 定义对象、关系、业务动作并确认业务口径 |
| 数据工程师 | 配置对象属性与物理数据映射，治理对象身份 |
| 应用/Agent 开发者 | 基于已发布对象和动作构建应用与 Agent 工具 |
| 安全管理员 | 配置动作角色、审批边界并审计执行记录 |
| 业务操作员 | 浏览业务对象、提交动作、查看执行结果 |

主流程：选择领域 -> 建对象与属性 -> 建关系 -> 建动作 -> 校验 -> 发布 -> 录入/同步实例 -> 执行动作 -> 审计决策。

## 3. 本轮 V1 原型需求与实现状态

V1 定位为“可验证的本地运营本体闭环”，用于业务试点和产品验证，不等同于已经具备生产级外部系统写回、动态 ABAC 或分布式图运行时。

| 需求编号 | 功能 | V1 验收标准 | 验收证据 | 当前状态 |
|---|---|---|---|---|
| ONT-001 | Ontology 工作空间 | 复用语义领域；切换领域并查看本体概览 | `app/api/ontology.py`、`frontend/src/router/index.ts`、工作台 summary | 已验证 |
| ONT-002 | 对象与属性建模 | 对象 CRUD；类型、必填、主属性、显示字段可配置 | `app/models/ontology.py`、`app/services/ontology_service.py`、服务测试 | 已验证 |
| ONT-003 | 关系建模 | 定义 1:1、1:N、N:1、N:N 元数据；创建匹配类型的关系实例 | `app/services/ontology_service.py`、工作台图谱视图 | 已开发；基数强制约束列入 S3 |
| ONT-004 | 动作建模 | 配置目标对象、参数、前置条件、状态效果、角色和审批标记 | `app/models/ontology.py`、工作台动作编辑器 | 已开发；正式审批流列入 S4 |
| ONT-005 | 本体校验 | 检查主属性、对象/属性引用、动作效果和参数引用 | validate API、校验抽屉、`tests/test_ontology_service.py` | 已验证 |
| ONT-006 | 发布快照 | 校验通过后生成递增发布快照 | `ontology_release`、publish/releases API、发布阻断测试 | 原型完成；运行版本隔离/回滚列入 S2 |
| ONT-007 | 对象实例运行时 | 手工或 bundle 创建、更新、查询实例；校验类型和必填项 | object API、实例动态表单、幂等导入测试 | 已开发；批量同步/身份解析列入 S3 |
| ONT-008 | 动作执行 | 校验角色、审批引用、参数和前置条件；更新对象并保留前后状态 | execute API、动作弹窗、`tests/test_ontology_service.py` | 原型完成；事务/幂等/补偿列入 S4 |
| ONT-009 | 决策审计 | 查看执行人、参数、上下文、前后状态、结果和时间 | action-runs API、决策活动视图、E2E 回放 | 已开发；完整 release/trace 血缘列入 S4 |
| ONT-010 | Ontology 工作台 | 概览、图谱、对象、关系、动作、实例、活动七个视图 | `frontend/src/views/OntologyWorkbench.vue`、前端测试与构建 | 已验证（桌面/移动端） |
| ONT-011 | 导入导出与示例 | UI 导入/导出 bundle；供应链样例覆盖对象、关系、动作和实例 | `examples/supply_chain/ontology-bundle.json`、`scripts/verify_ontology_e2e.py` | 已验证（真实 API 回放） |
| ONT-012 | 自动化验证 | 后端单测、API 路由、前端契约、类型检查和生产构建通过 | `pytest`、`ruff`、`npm test`、`npm run build` | 已通过 |
| ONT-013 | Agent/应用上下文 | 为应用和 Agent 提供已发布对象定义、对象查询和受控动作工具 | `app/agent/ontology_tools.py`、`/agent-context` 和 `/agent-tools` API、`tests/test_ontology_tools.py` | 已验证 |

## 4. V1 技术架构

| 层次 | 现有复用 | 本期新增 |
|---|---|---|
| 接入与数据 | 数据源、Schema 采集、MySQL 客户端 | 对象实例和关系实例运行时 |
| 语义 | 语义领域、概念、指标、映射 | 对象类型、属性、关系类型 |
| 逻辑与动作 | 语义规则、LangGraph、权限角色 | 动作参数、前置条件、效果和执行器 |
| 治理 | JWT、管理员权限、语义快照 | 本体校验、发布快照、动作审计 |
| 体验 | Vue、Element Plus、ECharts | 企业本体工作台和本体图谱 |

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
| 可维护性 | Ontology 代码独立于现有问数运行时，领域删除时级联清理 |
| 可用性 | 所有核心操作可在工作台完成，不要求直接编辑 JSON |
| 可测试性 | 声明式校验和动作效果有单元测试；前端通过类型检查和生产构建 |

## 7. 公司级产品化排期

以下按 2 人产品研发小组估算。V1 原型是 S1 的实现基础；S2~S6 是进入公司生产业务前不能跳过的工程阶段。

| 阶段 | 周期 | 交付内容 | 硬验收标准 | 当前状态 |
|---|---:|---|---|---|
| S0 决策设计 | 1 周 | 试点决策画布、术语、角色、权限、数据契约 | 业务负责人确认一个可量化决策闭环 | 需结合真实业务开展 |
| S1 本体原型 | 2 周 | 对象/关系/动作 CRUD、图谱、实例、执行审计、bundle、最小 Agent 工具 | UI 完成“建模 -> 校验 -> 发布 -> 执行 -> 审计”；自动化测试通过 | 原型完成 |
| S2 发布治理 | 2 周 | draft/release 激活指针、diff/回滚、并发发布、变更影响 | 运行时绑定 release；并发发布和回滚集成测试通过 | 未开始 |
| S3 数据运行时 | 2 周 | 物理映射、分页搜索、CSV/API 同步、身份解析、唯一/基数约束 | 10 万对象导入回放；冲突和坏数据报告可追溯 | 未开始 |
| S4 生产动作 | 2 周 | 事务、乐观锁、幂等、HITL 审批、Webhook/ERP 写回、失败补偿 | 重复请求不重复执行；写回失败可补偿；全链路 release/trace 审计 | 未开始 |
| S5 Agent 集成 | 2 周 | Ontology context、对象查询工具、受控 Action 工具、Function 注册 | Agent 可查询对象并在权限内暂存/执行动作；越权用例阻断 | 未开始 |
| S6 业务试点 | 2 周 | 真实数据接入、UAT、运行指标、应急与回滚手册 | 连续两周稳定运行；决策时间/人工步骤有基线和改善数据 | 未开始 |

## 8. 开源复用策略

GitHub 调研结论是保留现有 FastAPI/MySQL 运营运行时，按边界引入成熟项目，而不是整体替换产品层。

| 项目 | 许可证 | 适用能力 | 决策 |
|---|---|---|---|
| LinkML | Apache-2.0 | YAML 模型、JSON Schema/Pydantic/SQL/SHACL/OWL 生成与 CI 校验 | S2 做 schema source-of-truth PoC，优先采用 |
| OpenMetadata / DataHub | Apache-2.0 | 技术元数据、Glossary、血缘、Ownership、连接器 | S3 二选一作为治理侧车，不嵌入核心运行时 |
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
