# 问渠 WenQu 项目结构与功能边界

> 基准日期：2026-09-07
> 文档用途：给开发、业务、数据和测试人员提供一张“项目地图”。本文按**公司内部单一部署**描述项目，不设计多租户、多企业空间或企业间隔离。

## 1. 先记住一条主线

问渠的核心不是“做一个 Agent 产品”，而是把公司的业务理解和数据沉淀为可复用的企业能力：

```text
公司内部用户 / 角色与数据权限
        ↓
业务领域
        ↓
企业模型中心
（Ontology + 查询语义 + 数据映射）
        ↓
数据处理与孪生运行时
（对象实例、状态、来源、同步）
        ↓
能力发布中心
（Query / Decision / Action API / SDK）
        ↓
第三方 Agent / 业务应用
```

本项目内的对话页和 Agent 配置只是一套**调试、回归和验收客户端**，用来验证外部 Agent 能否得到同样的业务口径和结果：

```text
同一业务问题
  ├─ 本项目内置验证 Agent → 能力接口 → 结果/证据
  └─ 外部 Agent          → 同一能力接口 → 同一口径/结果/审计
```

## 2. 六层功能块

| 层 | 功能块 | 负责什么 | 主要输入 | 主要输出 | 当前口径 |
|---|---|---|---|---|---|
| 1 | 公司级治理与权限 | 用户、角色、业务领域、模型配置和数据访问边界 | 用户、协作约束、配置 | 可访问范围和运行上下文 | 公司单一部署；当前登录角色只有 `admin/user` |
| 2 | 数据接入与治理 | 连接业务库、采集 Schema、表/列权限和脱敏 | MySQL 只读库、表清单、字段说明 | `datasource`、`meta_table`、`meta_column`、显式权限规则 | 当前只支持 MySQL；表白名单默认拒绝并已有管理入口 |
| 3 | 企业模型中心 | 统一维护 Ontology 与查询语义 | 对象、关系、状态、指标、规则、字段映射 | 模型草稿、服务端校验、统一激活版本 | 产品入口和发布生命周期统一，底层资产表仍分开维护 |
| 4 | 数据处理与孪生运行时 | 建立对象身份、同步当前状态、关联来源和关系 | 激活模型、`source_query`、业务库数据 | `ontology_object`、`ontology_link`、`twin_sync_run` | 当前支持预览和管理员手动分页同步，强制校验版本/数据源漂移 |
| 5 | 能力发布与运行出口 | 把模型和数据转换为稳定、可复用的能力合同 | 企业模型、孪生对象、权限、调用方上下文 | Query API、调用凭据、授权和审计 | 外部 Query 第一版已实现；Decision/Action、SDK 和配额治理后续建设 |
| 6 | 验证客户端与垂直应用 | 验证能力效果，承载具体场景交互和交付 | 已发布能力 | 内置验证 Agent、第三方 Agent、风险交付等 | Agent 不是企业模型所有者，风险交付只是验证场景 |

### 2.1 模块边界（谁不负责什么）

| 模块 | 负责 | 不负责 |
|---|---|---|
| 公司级治理与权限 | 用户/角色、业务领域和数据访问边界 | 不创建多企业空间，不定义业务指标 |
| 数据源 / 元数据 | 连接、表清单、字段类型和物理权限 | 不决定“申请数”的业务口径 |
| 企业模型中心 | 业务定义、映射、规则、版本和动作合同 | 不负责持续拉取全库数据 |
| 孪生运行时 | 对象实例、当前状态、来源、同步结果 | 不重新定义指标和业务规则 |
| 能力发布中心 | 对外提供稳定输入/输出、权限和审计契约 | 不要求调用方先创建本项目 Agent |
| 内置验证 Agent | 调试、回归、演示和验收能力消费 | 不拥有或复制企业模型，不代表第三方 Agent 的运行形态 |
| 风险交付 | 风险事项、证据、复核、报告和审计 | 不作为平台主线或通用 Agent 管理中心 |

## 3. 产品页面与后端入口

### 3.1 前端页面

| 页面/路由 | 产品定位 | 说明 |
|---|---|---|
| `/` | 对话验证 | 验证 Agent 消费企业能力的效果，展示过程、SQL、结果和报告 |
| `/enterprise-model` | 企业模型 | 公共顶部先创建/选择业务领域，再按“业务本体 → 语义与数据 → 版本发布”维护统一模型；三个子区共享同一 `domain_id` |
| `/twin-runtime` | 孪生运行 | 预览/执行对象同步，查看对象实例、关系实例、动作执行记录、版本、统计、错误和 trace |
| `/capability-center` | 能力发布 | 查看合同，管理第三方调用方、Query 授权和调用审计 |
| `/agent` | 调试与验证智能体 | 配置本项目内置验证客户端，不是第三方 Agent 注册中心 |
| `/datasource` | 数据源 | 测试连接、发现表、采集 Schema |
| `/model-config` | 模型配置 | 大语言模型和向量模型 |
| `/system-parameter` | 系统参数 | Prompt、召回阈值和用户管理子区 |
| `/risk-delivery` | 风险交付技术切片 | 贷款/财税场景的事项、证据、报告和审计工作台 |

兼容地址 `/knowledge`、`/ontology`、`/users` 会重定向到新入口；`KnowledgeConfig.vue` 是企业模型页面的嵌入子区，不是独立产品页面。

`/api/workspaces` 和 `enterprise_workspace` 仅作为历史数据兼容的内部单例容器，不是业务人员需要理解或操作的产品功能；后续不扩展多租户能力。

### 3.2 后端 API 与服务

| API | 主要职责 | 关键实现 |
|---|---|---|
| `/api/auth`、`/api/users` | 登录、用户和验证 Agent 授权 | `app/api/auth.py`、`user.py`、`app/services/user_service.py` |
| `/api/agent` | 内置验证 Agent、数据源/领域绑定 | `app/api/agent.py` |
| `/api/datasource` | 数据源连接、Schema 采集和 Agent 表/列权限 | `app/api/datasource.py`、`datasource_service.py`、`metadata_service.py` |
| `/api/semantic` | 查询语义资产、快照和向量同步 | `app/api/semantic.py`、`semantic_runtime.py` |
| `/api/ontology` | Ontology 定义、实例与动作兼容 API；旧同步入口统一委托孪生运行治理 | `app/api/ontology.py`、`ontology_service.py` |
| `/api/model-releases` | 统一企业模型版本的创建、校验、激活、停用和回滚 | `app/api/model_release.py`、`model_release_service.py` |
| `/api/twin` | 孪生预览/同步运行与运行记录 | `app/api/twin_runtime.py`、`twin_runtime_service.py` |
| `/api/capability-clients`、`/api/v1/capabilities/*:invoke` | 第三方调用身份、Query 授权、调用和审计 | `app/api/capability_access.py`、`capability_access_service.py` |
| `/api/chat`（主入口在 `app/main.py`） | 内置验证 Agent 的流式问数和持久任务 | `app/agent/graph.py`、`react.py`、`nodes/` |
| `/api/risk` | 风险事项、证据、复核、报告、审计 | `app/api/risk_workflow.py`、`risk_workflow_service.py` |
| `/api/model-config`、`/api/prompt`、`/api/system` | 横向运行配置 | 对应 API 和 service |
| 内部能力工具 | 本项目验证客户端的对象查询、Query 和受控 Action | `app/agent/ontology_tools.py`、`app/services/query_capability.py` |

当前 `/api/ontology/*/agent-context`、`agent-tools` 等接口仍带有内部 Agent 权限兼容逻辑，属于过渡 API；第三方调用不应依赖先创建内部 Agent。

## 4. 数据库分层

管理库和业务库必须分开。平台默认只读访问业务库，配置、语义、对象运行记录和审计写入管理库。

### 4.1 管理库表分组

| 分组 | 主要表 | 说明 |
|---|---|---|
| 公司级治理与身份 | `app_user`、`user_agent_permission`、`semantic_domain`、`agent_semantic_domain`、`agent` | 公司内部用户、业务领域和验证 Agent 的访问关系 |
| 内部兼容容器 | `enterprise_workspace`、`semantic_domain.workspace_id` | 当前单公司部署的历史兼容字段；不是多企业模型 |
| 数据接入与权限 | `datasource`、`agent_datasource`、`meta_table`、`meta_column`、`agent_table_permission`、`agent_column_permission` | 连接、Schema、表白名单和列脱敏 |
| 企业模型 | `semantic_concept`、`semantic_relation`、`semantic_metric`、`semantic_rule`、`semantic_mapping`、`logic_form_template`、`semantic_domain_snapshot`、`ontology_object_type`、`ontology_property`、`ontology_link_type`、`ontology_action_type`、`ontology_release`、`enterprise_model_release` | 业务定义、映射、动作和统一激活版本 |
| 孪生运行与审计 | `ontology_object`、`ontology_link`、`ontology_action_run`、`twin_sync_run`、`decision_audit_event`、`decision_audit_head` | 对象实例、同步运行、动作结果和审计链 |
| 外部能力调用 | `capability_client`、`capability_grant`、`capability_invocation_audit` | 第三方调用身份、领域能力授权和调用摘要 |
| 应用与验证结果 | `chat_history`、`agent_task_checkpoint`、`risk_issue`、`risk_evidence`、`risk_issue_review`、`risk_report`、`risk_report_version`、`user_feedback` | 验证会话、可恢复任务和垂直应用数据；不等于平台底座资产 |
| 横向运行配置 | `prompt_template`、`system_parameter`、`model_config` | 影响多个功能块的模型、Prompt 和运行参数 |

### 4.2 重要兼容边界

1. **单公司环境。** 不新增 workspace/tenant 概念，不为第二家公司设计隔离、成员体系或组织树。现有 `enterprise_workspace` 只保留为默认单例容器，后续是否移除另行评估。
2. **产品统一入口不等于数据库已合并。** `semantic_*` 和 `ontology_*` 仍通过 `domain_id`、稳定 key 与 `app/services/ontology_semantic_bridge.py` 的显式约定桥接；没有数据库外键，也不按物理表名自动猜归属。
3. **Agent 是适配层。** `agent_id`、`agent_semantic_domain` 和 `agent_datasource` 当前用于内置验证客户端的兼容运行；新能力接口应逐步以 `domain_id + release_id + caller context` 为主，不把 `agent_id` 作为企业模型所有权。
4. **资产删除受治理。** 数据源仍被领域引用时不能删除；领域产生版本、实例、运行或审计记录后只能停用，不能级联硬删除企业资产。

## 5. 关键数据如何串起来

```text
业务库表
  → Schema 采集（meta_table / meta_column）
  → 企业模型映射（semantic_mapping / source_query）
  → 对象/指标/关系定义
  → 能力合同（Query / Decision / Action）
  → 只读 SQL / 对象同步
  → 结果、对象状态和证据
  → 内置验证 Agent 或第三方 Agent 消费
  → trace / release / decision_audit_event
```

常用关联标识：

| 标识 | 用途 |
|---|---|
| `domain_id` | 业务模型、映射、能力和数据边界 |
| `datasource_id` | 业务库连接、Schema 和 SQL 执行边界 |
| `model_release_id` / `semantic_snapshot_id` / `ontology_release_id` | 统一模型及其语义、Ontology 组成版本 |
| `caller context` | 内置用户/验证 Agent 或外部 capability client 的调用身份和权限 |
| `session_id` / `task_id` / `turn_id` | 内置验证 Agent 的多轮任务 |
| `trace_id` | 问数结果、证据和风险事项的精确血缘 |

## 6. 文档各自应该写什么

| 文档 | 唯一职责 | 不要写什么 |
|---|---|---|
| `docs/README.md` | 文档入口、权威顺序、阅读路径和维护规则 | 详细业务规则、重复路线图 |
| `docs/ontology-product-roadmap.md` | 平台方向、优先级、阶段状态、验收和迭代记录 | 某个领域的临时字段口径 |
| `docs/product-business-flow.md` | 当前业务事实、模块联动、角色流程、数据链路和权限 | 另一套进度数字 |
| `docs/project-design.md` | 代码实现、运行链路、安全和技术边界 | 产品决策和重复排期 |
| `docs/project-structure.md` | 功能块、代码、数据和调用关系地图 | 具体领域的业务规则 |
| `docs/business-data-onboarding.md` | 真实业务接入 SOP、模板和验收清单 | 平台长期路线 |
| `docs/ontology-osdk-alignment-plan.md` | OSDK 术语、能力契约和技术迁移路径 | 第二套平台路线 |
| `docs/risk-report-delivery-roadmap.md` | 贷款/财税垂直验证线 | 平台通用能力进度 |
| `docs/archive/` | 历史研究和决策记录 | 当前验收依据 |

## 7. 新增功能时的最小检查

1. 先判断功能属于底座、能力出口还是验证客户端，明确输入、输出和“不负责什么”。
2. 先更新路线图中的阶段状态和验收标准，再改业务/技术说明。
3. 新增数据库表或字段时，同时更新迁移、模型、权限和本文件的表分组。
4. 新增真实业务领域时，先完成 [业务与数据接入手册](./business-data-onboarding.md)，不要直接导入全库。
5. 新增对外能力时，优先设计与 Agent 无关的能力契约；内置验证 Agent 只作为一个调用方。
6. 验收同一标准问题经内置验证 Agent 和外部 Agent 调用时，是否命中同一 `capability/release`、保持同一业务口径，并共享必要的 trace/审计信息。
7. 任何“当前已实现”都要有页面、API、测试或手工验收证据；其余统一标为“已有基础”“计划中”或“明确不包含”。
