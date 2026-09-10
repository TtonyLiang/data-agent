# 核心目标一致性扫描与整改清单（2026-09-08）

> 核心目标：**让业务语义成为企业资产，让数据库成为数据来源，让 Agent 成为能力消费者。**
>
> 本清单用于记录当前代码与产品目标之间的偏差。平台路线、阶段状态和最终验收仍以 [Ontology 产品路线图](./ontology-product-roadmap.md) 为准。

## 1. 扫描范围与判断标准

本轮扫描覆盖：

- 产品路线、业务流程、项目结构和接入手册；
- 企业模型、数据源、孪生运行、能力发布、验证 Agent 和对话页面；
- Ontology、语义运行时、权限、Query Capability 和外部调用 API；
- 角色边界、页面文案、接口命名、数据库关联和自动化测试。

每一项功能按三个问题判断：

1. 是否先表达业务语义，再落到物理数据实现？
2. 企业模型是否独立于某个 Agent，可以被多个调用方复用？
3. 数据库、运行时和 SQL 是否作为来源/执行实现，而不是业务模型本身？

## 2. 偏差清单

| 编号 | 优先级 | 偏差 | 主要证据 | 整改方向 | 当前状态 |
|---|---|---|---|---|---|
| CORE-001 | P0 | 第一性目标尚未成为全部核心文档和自动化检查的统一表述 | `README*.md`、核心 `docs/*.md`、`test_product_positioning.py` | 统一文案并增加产品定位回归测试 | **已修复** |
| CORE-002 | P0 | 外部 Query Capability 成功响应仍公开物理 SQL，数据库结构可能反向成为外部合同 | `capability_access_service.py`、`test_capability_access.py` | 外部响应只返回业务结果、语义资产和 trace；SQL 仅留在内部调试 | **已修复** |
| CORE-003 | P0 | 正式外部能力仍可能复用允许 NL2SQL 兜底的查询链路 | `ontology_tools.py`、`capability_access_service.py` | 外部能力只走发布模型和确定性编译；未覆盖时结构化失败 | **已修复** |
| CORE-004 | P0 | 外部能力授权要求管理员选择内部验证 Agent 作为权限执行适配 | `CapabilityGrantUpsertPayload`、`CapabilityPublishCenter.vue` | 授权只选择领域和能力；旧 Agent 适配由平台内部兼容 | **已修复** |
| CORE-005 | P1 | Ontology 关系与查询语义关系分开维护，业务关系和 JOIN 映射可能漂移 | `KnowledgeConfig.vue`、`ontology_semantic_bridge.py`、`model_release_service.py` | Ontology 维护业务关系；查询语义只引用关系并维护物理查询路径 | **已修复**；孤立或方向不一致的查询路径在保存、校验和统一发布时阻断 |
| CORE-006 | P1 | 关系创建页将业务含义、技术标识和连接字段放在同一层 | `OntologyWorkbench.vue`、前端契约测试 | 业务关系优先；技术字段自动生成或进入高级配置 | **已修复** |
| CORE-007 | P1 | 动作创建页默认暴露表达式、前置条件和效果 DSL | `OntologyWorkbench.vue`、前端契约测试 | 基础模式表达业务意图、状态变化和输入；治理/技术规则进入高级配置 | **已修复** |
| CORE-008 | P1 | Query Capability 主要由当前运行时动态生成，能力合同没有独立持久版本和内容指纹 | `capability_grant`、`capability_access_service.py` | 授权冻结 `model_release_id + contract_hash + contract_json`，变化后要求重新授权 | **第一版完成** |
| CORE-009 | P1 | 数据源表列权限的配置主体仍是 Agent，外部调用只能借用内部 Agent 权限 | `domain_*_permission`、`permission_service.py`、`DatasourceConfig.vue` | 领域规则优先；Agent 权限仅作显式迁移兼容并记录来源 | **第一版完成** |
| CORE-010 | P1 | Chat 和内部语义运行时仍以 Agent 默认领域为主要入口 | `main.py`、`semantic_runtime_recall.py`、`ChatView.vue` | 显式 `domain_id + model_release_id` 优先；默认领域仅作兼容 | **已修复** |
| CORE-011 | P1 | 对象、指标、关系和映射页面仍让业务建模人员直接面对表、字段和 SQL | `OntologyWorkbench.vue`、`KnowledgeConfig.vue`、`ObjectDataBindingPanel.vue` | 业务定义与技术数据绑定分区；指标和规则按对象组织；表字段从 Schema 选择；SQL/LogicForm 收入高级配置 | **第一版完成**；真实业务复杂映射和影响分析仍待验收 |
| CORE-012 | P1 | Agent 级 Prompt 可以影响语义解释和 LogicForm，可能改变统一业务口径 | `prompt_service.py`、`PromptConfig.vue`、Prompt 测试 | 语义关键 Prompt 禁止 Agent 覆盖；Agent 只覆盖交互/输出类 Prompt | **已修复** |
| CORE-013 | P2 | 对象查询使用孪生快照，Query Capability 可能直接读实时业务库，缺少统一时点说明 | `capability_access_service.py`、`TwinRuntimeCenter.vue` | Query 合同声明 `live_source + invocation_time`；孪生页面明确快照/overlay 来源 | **第一版完成**；`hybrid/as_of` 查询后续建设 |
| CORE-014 | P2 | 动作只更新本地 overlay，页面可能让用户误以为业务数据库已改变 | `ontology_service.py`、`TwinRuntimeCenter.vue` | 返回并展示 `business_source_written=false`，明确尚未写回业务库 | **已修复边界表述**；外部写回仍未建设 |
| CORE-015 | P2 | 语义概念与 Ontology 对象/动作容易重复 | `KnowledgeConfig.vue` | 业务对象直接引用企业本体，语义概念仅作为对象查询词汇补充；可执行动作只在 Ontology 动作类型维护 | **已修复产品入口**；底层兼容表继续保留 |
| CORE-016 | P2 | 领域复制/导入仍可能只复制语义资产或只导入 Ontology，产生半套企业模型 | `EnterpriseModelCenter.vue`、前端契约测试 | 复制/导入导出组合语义资产与 Ontology 定义 | **第一版完成**；运行实例和审计不复制 |
| CORE-017 | P2 | 向量索引仍以 `agent_id + domain_id` 命名，语义资产被重复索引 | `vector_store.py`、`embedding_service.py`、`semantic_runtime_recall.py` | 迁移到 `domain_id + release/snapshot + embedding_model_version` | **已修复**；相同模型配置跨 Agent 共享版本化企业语义索引，版本化运行不读取旧集合 |
| CORE-018 | P2 | 关系运行时目前只支持单属性等值匹配，容易因业务 ID 重复产生误关联 | `OntologyLinkTypePayload`、`_sync_links_for_objects()` | 支持有序复合关系键、空键拒绝和稳定匹配 | **第一版完成**；有效期和跨数据源身份合并仍按真实场景后续建设 |

## 3. 本轮整改结论

本轮已完成核心目标统一、外部 Query 边界、能力合同冻结、领域级表列权限、Chat 显式领域、Prompt 作用域、业务/技术分层 UI、企业模型组合复制，以及快照/overlay 状态说明。旧字段和旧 API 只保留兼容读取，新页面、新授权和新能力不再扩大 Agent 所有权或物理 SQL 外泄。

范围校正：现有 `admin/user` 和用户到验证 Agent 的授权只用于当前系统管理、演示和回归。平台角色固定为业务人员与技术人员；当前开发者暂用 `admin` 完成两类操作，本轮不新增工作模式或普通用户独立领域授权，不把验证账号体系扩张为平台主线。

本轮进一步完成了两个运行时缺口：语义向量索引迁移到领域/发布版本/Embedding 版本主键；关系同步支持有序复合键并在前后端校验两端数量和顺序。旧 Agent 向量集合只供未携带版本的历史调用兼容，正式版本化运行不会回退读取；单字段关系配置继续兼容。

没有凭空扩建关系有效期、跨数据源身份合并、CDC 或通用图推理。这些能力需要真实业务表、身份规则和更新机制作为输入，当前只记录边界，不用预设模型替代业务确认。

## 4. 完成标准

本轮完成必须同时满足：

1. 文档首页、路线图、业务流程和项目结构使用同一第一性目标；
2. 外部 Agent 能力授权页面不要求先创建或选择内部验证 Agent；
3. 关系和动作页面先表达业务语义，技术配置不成为默认必填项；
4. 自动化测试覆盖 Agent 消费者边界、能力授权和模型复用；
5. 后端全量测试、前端测试、生产构建和 diff 检查通过。
6. CORE-001 至 CORE-017 每项都有“已修复”证据或仍然真实有效的迁移测试，不允许仅以文案代替结构修复。

## 5. 本轮验证结果

- 后端全量测试：`558 passed`。
- Python 静态检查：`uv run ruff check app tests` 通过。
- 前端契约测试：`npm test` 通过。
- 前端类型检查与生产构建：`npm run build` 通过。
- 变更格式检查：`git diff --check` 通过。

以上结果验证的是合成数据和自动化基线，不替代真实业务负责人对对象、指标口径、数据权限和标准问题集的验收。
