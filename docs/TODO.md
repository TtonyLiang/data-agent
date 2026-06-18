# WenQu 智能问数 — 待办清单

> 当前路线以现有实现为准：多智能体、多数据源、多模型配置、多套语义层、LogicForm 查询链路、流式分析过程和管理台配置体验。

## Phase 1: 核心引擎 (MVP) ✅ 已完成

- [x] 项目脚手架与基础配置 (pyproject.toml, .env, docker-compose, config)
- [x] 管理库与业务库基础表结构
- [x] LLM 服务层统一接入 (MiMo / MiniMax / DeepSeek / OpenAI-compatible)
- [x] 元数据管理与数据源连接测试
- [x] FastAPI 后端服务 (端口 4400)
- [x] Vue3 + Element Plus 前端管理台 (端口 4399)
- [x] LangGraph 核心工作流升级为 LogicForm + 深度分析链路:
  `intent -> semantic_enhance -> semantic_runtime_recall -> schema_recall -> nl2lf_generate -> lf_validate -> lf_to_sql_compile -> semantic_check -> sql_execute -> planner -> python_generate -> python_analyze -> report_generator`
- [x] 端到端问数验证: 自然语言 -> LogicForm -> SQL -> 查询结果 -> 分析结论

---

## Phase 2: 语义运行时与向量召回 ✅ 已完成

- [x] Milvus / 本地向量库集成
- [x] Embedding 服务层与向量模型配置
- [x] 语义运行时模型: 领域、对象/事件/状态、关系、指标、规则、映射、LogicForm 模板
- [x] 语义资产向量同步与召回
- [x] NL2LF 节点: 自然语言生成 LogicForm
- [x] LFValidate 节点: 指标、维度、过滤、时间窗口语义校验
- [x] LFToSQLCompile 节点: LogicForm 确定性编译 SQL
- [x] LFRepair 节点: 校验或 SQL 执行失败后的修复链路
- [x] SQL 执行失败自动重试 (最多 2 次)

---

## Phase 2.5: 管理台与配置体系 ✅ 已完成

- [x] 模型配置管理: 区分大语言模型与向量模型
- [x] 智能体管理: 绑定大语言模型、向量模型、数据源和默认语义层
- [x] 数据源管理: 全局数据源连接、编辑、删除、连通性测试
- [x] 数据源 Schema 管理: 表清单读取、选择采集、字段详情、取消采集
- [x] 语义层配置: 多套语义层、语义资产表单化新增/编辑/删除/详情
- [x] 语义资产填写指引: 6 类资产的字段说明页
- [x] 会话历史: 多轮会话列表、加载、删除
- [x] 流式分析过程: 节点日志、思考过程落地、会话切换后恢复
- [x] 项目日志落盘: 后端日志、LLM prompt、流式事件日志写入 logs 目录
- [x] 分析结论展示: 业务结论、关键字段、SQL 详情和结果表分层展示

---

## Phase 2.8: 产品化收敛 ✅ 已完成

- [x] 问数体验第一批收敛:
  分析过程默认折叠、历史会话恢复思考过程、结论卡片强化、SQL/结果标签稳定切换
- [x] 结果态第一批收敛:
  右侧结果页分页、总行数/范围提示、宽表独立滚动、长单元格详情查看
- [x] 错误态第一批收敛:
  用户可读摘要、技术明细折叠、按语义校验/SQL 编译/SQL 执行等阶段展示
- [x] 管理台一致性第一批收敛:
  智能体管理补齐详情抽屉，支持查看基础信息、模型绑定、语义层和可访问数据源
- [x] 当前改动收敛:
  前端测试通过、构建通过、前后端重启并完成基础页面自测
- [x] 示例问法真实链路回归:
  修复高 PD 问法被误判为闲聊、跨事实表多指标编译为空 SQL、SQL 编译失败后错误阶段误报等问题；
  4 个前端示例问题已通过 `/api/chat/stream` 真实链路验证
- [x] 流式结论展示收敛:
  生成过程中只展示分析链路，不提前展示 Final Answer / 分析结论占位；完成后再展示最终结论与报告
- [x] 申请笔数问法收敛:
  新增申请笔数指标与申请地区维度映射，修复“贷款排名前三的申请区域/分别申请多少笔”被误判为放款金额的问题；
  支持“我问的是笔数，不是金额”这类多轮追问纠偏，并通过真实 `/api/chat/stream` 链路验证
- [x] 语义层映射中文展示修复:
  补齐申请表相关映射的中文名、表中文名、字段中文名展示，避免新增资产在管理台回退显示英文 key
- [x] 模型配置 Key 返显与保留:
  编辑模型配置时显示已配置 Key 的掩码状态；不修改 Key 直接保存会保留原密钥，输入新 Key 才覆盖

---

## Post-2 Backlog: 治理与体验增强

- [x] 查询链路增强:
  在知识召回后新增“数据定位”节点，基于已采集表、字段、中文注释、外键和语义资产召回候选 schema；
  NL2SQL 兜底优先使用候选 schema，候选为空才退回已采集 schema，减少全库噪音。
- [x] 语义层治理增强:
  支持复制语义层、导入/导出、版本快照、快照列表和变更前校验；新增 `semantic_domain_snapshot` 保存版本快照。
- [x] 数据源采集体验增强:
  表清单支持搜索和采集状态筛选；展示已采集表/字段统计与噪音提示；字段详情支持字段名/中文名搜索，取消采集后刷新状态。
- [x] 问数体验第二批收敛:
  失败态增加重新运行入口；空结果提供 SQL 查看和重新提问引导；超宽表支持列管理，导出仍保留完整结果。
- [x] 管理台一致性继续完善:
  模型配置、数据源和语义层补齐详情/只读查看入口，操作列统一保留详情、编辑、删除和危险操作确认。
- [x] 结果态设计 QA:
  已记录 Post-2 populated state QA 清单，覆盖成功、空结果、错误、NL2SQL 兜底、报告展开和历史恢复场景。
- [x] 本轮变更说明整理:
  Phase 2.8/Post-2 验收结论与后续清单已同步到 TODO 与设计 QA 记录。
- [x] 语义增强节点:
  在意图识别和知识召回之间新增 `semantic_enhance`，将原始问题改写为更清晰的业务自然语言；
  后续知识召回、数据定位、LogicForm 和 NL2SQL 兜底优先使用增强问题，原始问题保留用于历史和审计。

---

## Phase 3: 深度分析

- [x] Planner 节点: 生成 SQL 步骤、分析步骤、报告步骤
- [x] SemanticCheck 节点: SQL 执行前做语义一致性校验，指标/维度/时间口径不匹配时阻断并返回可读错误
- [x] PythonGenerate 节点: 只基于 SQL 结果生成统计、分布、趋势、异常解释代码，不直接访问业务库
- [x] PythonAnalyze 节点: 汇总 Python 执行结果，转成业务可读解释
- [x] ReportGenerator 节点: 生成结构化报告，首版输出前端可展示的 JSON 片段
- [x] Phase 3 提示词库:
  新增 `app/agent/prompts/phase3_python_generate.system.md`、`phase3_python_analyze.system.md`、`phase3_report_generator.system.md`；
  参考 DataAgent 风格，但按本项目执行器约定改成使用注入的 `rows` 变量。
- [x] LLM PythonGenerate + 安全模板兜底:
  有智能体上下文和 SQL 结果时优先调用大模型生成分析脚本；脚本必须通过 AST/导入/输出约束校验，失败时回退到默认安全模板。
- [x] 动态图表与分析模式:
  根据排名、趋势、分布、异常等语义推断分析模式；Python 输出 `insights/charts/tables/echarts_option`，安全模板也能输出排名/趋势图表 payload。
- [x] 后端流式 Markdown 报告:
  ReportGenerator 优先调用大模型流式生成不少于 300 字的中文 Markdown 报告；失败时使用增强版安全模板报告，并落地 `report_payload.markdown/body`。
- [x] 报告展示重构:
  前端报告主体改为安全 Markdown block 渲染，不使用 `v-html`；固定卡片降级为图表、表格和 Python 输出附件。
- [x] Python 安全执行器接口: 先定义可插拔执行后端，不写死 Docker
- [x] 开发执行后端: 受限本地子进程，支持超时、任务级临时目录、导入白名单和尽力 OS 资源限制
- [x] 报告持久化: chat_history 保存 plan_payload、semantic_check、python_result、report_payload，历史会话可恢复
- [x] 报告前端展示: 右侧报告 Tab 预览，支持展开到屏幕中央的大范围报告工作区
- [x] Phase 3 真实链路自测:
  使用本地 MySQL 的信贷业务分析助手跑通提问 -> 流式链路 -> SQL -> Python 分析 -> 报告 -> 历史恢复 -> 前端报告展开
- [x] NL2SQL 兜底链路:
  语义层未命中指标、LogicForm 校验失败或确定性 SQL 编译失败时，进入受限 NL2SQL 兜底；
  兜底只使用已采集 schema，生成单条只读 SELECT，经过 SQL 安全校验后再执行
- [x] 数据定位 / 表召回:
  在知识召回后召回候选表、字段和关联提示，作为 LogicForm 和 NL2SQL 兜底的物理 schema grounding 上下文。
- [x] 多轮追问语义增强:
  “前五呢”“我问的是笔数不是金额”等短追问会结合最近对话补全业务对象、指标、维度和 TopN 口径后再进入召回与生成。
- [x] SemanticCheck 自动修复增强:
  不一致时优先进入 `lf_repair`，可解释地移除不支持维度、未知指标或无法应用的时间范围；超过重试预算后再阻断。
- [x] ReportGenerator 图表增强:
  报告 payload 输出图表数据与 `echarts_option`，前端可继续升级为完整 ECharts 渲染。
- [x] 生产默认执行后端:
  Python 执行器已抽象为可插拔接口；生产默认推荐 `worker` 后端，本地执行器在非 debug 且未显式允许时会拒绝启动。
- [x] 高安全执行后端选择:
  配置层支持 `docker` / `containerd` / `firecracker` 等高隔离后端选择，占位执行器会明确提示需接入对应运行时；当前实现不再写死 Docker。

---

## Phase 4: 生产化 ✅ 已完成基础闭环

- [x] 多轮对话上下文管理 (chat_history 读写 + 上下文注入 prompt)
- [x] 前端历史会话侧边栏 (会话列表 + 加载历史 + 删除会话)
- [x] 基础可观测性: 后端日志、LLM prompt 日志、流式事件日志
- [x] API Key 基础管理: 密钥脱敏显示、更新不回显
- [x] SQL 安全加固:
  单条只读 SELECT 校验、语句分隔拦截、LIMIT 注入/截断、危险关键字/函数拦截、系统库/跨库访问拦截。
- [x] 权限控制:
  智能体级数据源授权、表级白/黑名单、列级允许/禁用和 `redact` / `partial` / `hash` 脱敏策略。
- [x] 可观测性增强:
  `trace_id` 贯穿同步/流式接口、SSE 事件、执行链路和历史结果；错误分级、慢查询耗时和 SQL 执行记录已落地。
- [x] Prompt 配置管理:
  新增 `prompt_template` 表、Prompt API、Prompt 管理页；语义增强、LogicForm 生成和 NL2SQL 兜底支持按智能体、模型、语义层覆盖系统提示词。
- [x] API Key 管理增强:
  模型连通性测试、密钥脱敏显示、更新不回显、过期时间与即将过期提醒已落地。
- [x] Human-in-the-loop:
  SQL 执行前确认节点、确认后继续执行接口、低置信度追问节点、用户反馈回流 API 和前端反馈 client 已具备基础闭环。

---

## 已知问题 / 风险收口 ✅ 已完成

- [x] 推理模型 reasoning_content 控制:
  LLM prompt 日志、SSE 日志、reasoning trace 和 streamText 都增加长度上限；历史会话恢复保留最近有效内容，避免超长思考过程拖垮日志和前端。
- [x] 超宽表和超大结果集体验:
  结果表保持当前页分页渲染、列选择和长文本弹窗；页面明确提示“表格只渲染当前页，导出保留完整结果和全部字段”，导出大结果或隐藏列时二次确认。
- [x] 语义层快照治理:
  快照支持详情、差异对比和一键回滚；回滚会覆盖当前语义层领域信息与六类资产，并刷新前端语义资产列表。
- [x] 采集表噪音控制:
  数据定位增加业务域分组和排序加权，申请/审批、放款/账户、还款/逾期、催收/回收、客户/风险等业务域会影响候选表字段优先级；
  NL2SQL 兜底上下文使用可配置表/字段上限，不再默认注入过宽 schema。
- [x] 高安全 Python 执行器:
  `local / worker / docker / containerd / firecracker` 后端均接入统一执行器接口；
  Docker/containerd 通过无网络、CPU/内存/PID 限制和只读工作目录运行，Firecracker 通过外部 runner 接入，生产仍推荐 worker 或高隔离后端。
- [x] LLM 调用耗时收敛:
  意图识别已有本地规则；语义增强对 TopN 追问、笔数纠偏、申请区域笔数等确定性场景直接规则短路；
  非流式 LLM 调用加入短 TTL 内存缓存，降低重复管理台/链路调用耗时。
- [x] 当前仓库改动范围:
  本轮收口涉及后端流式/LLM/语义层治理/数据定位/Python 执行器、前端语义层快照和结果表提示、测试与文档；
  未回滚用户或前序改动，提交前仍建议按功能域拆分 review。
