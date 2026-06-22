source visual truth: generated design reference image, retained outside the repository.
implementation screenshot evidence: local QA artifact, excluded from Git.
full-view comparison evidence: local QA artifact, excluded from Git.
focused region comparison evidence: not needed; the selected mock and implementation are primarily layout, typography, navigation, form, tab, and table surfaces with no custom image assets beyond the product mark.
viewport: 1440 x 1024 desktop; responsive smoke check at 390 x 844
state: source mock shows a populated result state; implementation evidence shows the local empty state because the running local environment did not return configured datasource/agent data. State mismatch is noted and excluded from data-content fidelity scoring.

**Findings**
- No actionable P0/P1/P2 findings.

**Required Fidelity Surfaces**
- Fonts and typography: implementation uses a system/Inter-style product font stack, compact 13-22px hierarchy, normal letter spacing, and dense table/control typography consistent with the Analyst Studio direction.
- Spacing and layout rhythm: implementation preserves the chosen top navigation, left history rail, central query workspace, docked composer, and right analysis panel. Desktop and mobile checks show no horizontal overflow.
- Colors and visual tokens: implementation uses a restrained white/cool-gray base, blue primary actions, green status accents, and muted gray copy. It avoids the previous heavy dark sidebar and Element Plus default-blue dominance.
- Image quality and asset fidelity: no custom product imagery is required by the source mock. Icons are Element Plus icon components, not CSS or handcrafted SVG stand-ins.
- Copy and content: primary Chinese labels are preserved: 对话, 智能体管理, 数据源, 知识库, 历史会话, 新对话, 分析链路, SQL, 结果, 发送. Empty-state copy is implementation-specific and appropriate for the unavailable local data state.

**Patches Made**
- Replaced the global shell with a top product bar and horizontal route navigation.
- Rebuilt ChatView into a three-column Analyst Studio workbench with session rail, query workspace, docked composer, and right-side analysis/result tabs.
- Added functional right-panel actions for rerun, SQL copy, and CSV result export.
- Unified Agent, Datasource, and Knowledge pages with a consistent page header, action region, and table surface.
- Added responsive rules for tablet/mobile, hiding side panels and tightening top navigation without horizontal overflow.

**Open Questions**
- A populated query-result visual comparison should be repeated once the local backend has usable agent, datasource, and sample data available.
- The current QA pass validates layout and interaction structure, but not yet the final density of a real result state with wide tables, populated SQL, and semantic labels.

**Implementation Checklist**
- Desktop layout checked at 1440 x 1024.
- Mobile layout checked at 390 x 844.
- Frontend build passed.
- Frontend tests passed.

**Follow-up Polish**
- Re-run the visual QA with a populated query result state after agent, datasource, and sample data are fully available.
- Revisit result-state density after a live query returns SQL and table data, especially for wide tables and long semantic labels.
- Align this work with `TODO.md` Phase 2.8 priorities: result explanation readability, wide-table pagination, clearer error states, and management-page consistency.

**Next Priority Alignment**
- Phase 2.8 should be treated as the immediate productization pass for the current UI shell rather than a new feature phase.
- The highest-value UI follow-up is not another redesign; it is tightening the populated result state, table ergonomics, and error/readability surfaces on top of the current Analyst Studio layout.

final result: passed

---

## Post-2 Backlog QA — 2026-06-16

**Scope**
- 查询链路新增“数据定位”节点，作为知识召回后的 schema grounding。
- 语义层治理增加复制、导入/导出、快照、快照列表和校验入口。
- 数据源采集增加搜索、状态筛选、已采集字段统计和噪音提示。
- 问数结果态增加失败重试、空结果引导和超宽表列管理。
- 模型配置、数据源、语义层补齐只读详情入口。

**Populated State Checklist**
- 成功结果: 右侧结果表分页保留，列管理默认展示前 12 列，导出仍使用完整结果。
- 空结果: 结果 Tab 展示 0 行原因提示，并提供查看 SQL / 重新提问入口。
- 语义校验失败: 错误卡保留阶段、摘要、技术明细和重新运行入口。
- NL2SQL 兜底: 分析过程展示“数据定位”候选表、候选字段和关联提示。
- SQL 执行失败: 失败态可重新运行，技术明细仍可展开。
- 报告展开: 现有大范围报告工作区未改动。
- 历史恢复: `reasoning_trace` 会保存新增 `schema_recall` 步骤输出并在历史会话恢复。

**Verification**
- Backend: `rtk .venv/bin/pytest -q` passed, 72 tests.
- Frontend tests: `rtk npm --prefix frontend test -- --run` passed.
- Frontend build: `rtk npm --prefix frontend run build` passed.

**Residual Visual QA**
- 仍建议在本地真实信贷业务库里重新跑一次：
  “贷款排名前三的申请区域是什么，分别申请了多少笔”
  并目测“数据定位”候选表是否优先定位到申请表、结果是否为笔数。

---

## Phase 3 / Phase 4 收口 QA — 2026-06-18

**Scope**
- Phase 3: SemanticCheck 自动修复、报告 ECharts payload、Python 可插拔执行器、本地/worker/高隔离后端选择。
- Phase 4: SQL 安全、智能体/表/列权限与脱敏、trace_id 和错误分级、Prompt 模板管理、API Key 连通性与过期提醒、HITL/反馈回流。
- 前端补齐 Prompt 配置页，支持按智能体、模型和语义层维护节点系统提示词。

**Verification**
- Backend full regression: `rtk .venv/bin/python -m pytest -q` passed, 108 tests.
- Frontend tests: `rtk npm --prefix frontend test -- --run` passed.
- Frontend build: `rtk npm --prefix frontend run build` passed.

**Covered Cases**
- SQL 安全：单条 SELECT、危险函数/关键字、跨库/系统库、LIMIT 注入与截断。
- 权限：授权 schema 过滤、SQL 表访问拦截、列级脱敏。
- HITL：SQL 执行前确认、确认后继续执行、低置信度追问、反馈 payload 校验与落库。
- Prompt：模板解析、变量回退、前端 CRUD 入口和作用域选择。
- Phase 3：LF 修复、Python worker 后端、生产拒绝无隔离本地执行、报告图表 `echarts_option`。

**Residual Risks**
- 高安全 Python 执行器的 Docker/containerd/Firecracker 后端已完成代码路径和命令封装，仍需按生产部署环境接入对应运行时或 worker。
- SQL 安全当前采用保守词法/结构化校验；复杂 SQL 场景后续可接入专用 SQL AST 解析库增强覆盖。
