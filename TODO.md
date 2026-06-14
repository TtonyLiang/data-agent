# WenQu 智能问数 — 待办清单

## Phase 1: 核心引擎 (MVP) ✅ 已完成

- [x] 项目脚手架 (pyproject.toml, .env, docker-compose, config)
- [x] 数据库建库建表 (管理库8表 + 业务库3表)
- [x] LLM 服务层 (MiMo/MiniMax/DeepSeek 统一接入)
- [x] 元数据管理 (Schema 自动采集)
- [x] LangGraph 核心工作流 (4节点: intent → schema_recall → sql_generate → sql_execute)
- [x] FastAPI 后端 (19个API, 端口4400)
- [x] Vue3 前端 (4页面, 端口4399)
- [x] 端到端验证通过 (MiMo生成SQL并正确执行)

---

## Phase 2: RAG 知识库增强 ✅ 已完成

- [x] Milvus 向量库集成 (pymilvus MilvusClient 本地模式)
- [x] Embedding 服务层 (Ollama 本地 qwen3-embedding:0.6b, 1024维)
- [x] 知识入库管道 (语义模型 + 业务知识 → 向量化 → 存入 Milvus)
- [x] EvidenceRecall 节点 (RAG 检索业务知识/术语)
- [x] QueryEnhance 节点 (根据 evidence 改写用户查询)
- [x] 更新 LangGraph 工作流 (6节点: intent → evidence → enhance → schema → sql_gen → sql_exec)
- [x] 验证: GMV 查询自动带 WHERE status=1 过滤条件

---

## Phase 2.5: Schema 召回增强 ✅ 已完成

- [x] TableRelation 节点 (schema_recall prompt 增强: PK/FK/同义词标注)
- [x] likely_joins 传递到 sql_generate (join 提示注入 prompt)
- [x] SQL 执行失败自动重试 (最多2次)
- [x] sql_generate 注入表级元数据 (table_comment, business_name)

---

## Phase 3: 深度分析

- [ ] Planner 节点 (多步骤计划生成: SQL步骤/Python步骤/报告步骤)
- [ ] SemanticCheck 节点 (SQL 语义一致性校验 + 自动纠错)
- [ ] Python 代码执行器 (Docker 沙箱)
- [ ] PythonGenerate 节点 (统计分析代码生成)
- [ ] PythonAnalyze 节点 (分析结果汇总)
- [ ] ReportGenerator 节点 (HTML 报告 + ECharts 图表)

---

## Phase 4: 生产化 🔄 进行中

- [x] 多轮对话上下文管理 (chat_history 读写 + 上下文注入 prompt)
- [x] 前端历史会话侧边栏 (会话列表 + 加载历史 + 删除会话)
- [ ] Human-in-the-loop 人工反馈机制
- [ ] SQL 注入防护加固 (ANTLR4 AST 解析)
- [ ] 权限控制 (RBAC + 列级脱敏)
- [ ] 可观测性 (日志 + 链路追踪)
- [ ] Prompt 配置管理 (按 agent 自定义 prompt)
- [ ] API Key 管理

---

## 已知问题

- [ ] MiMo 是推理模型, reasoning_content 会消耗额外 token
- [ ] SQL 执行结果无分页, 大结果集可能溢出
- [ ] 前端 AgentList 页面 /api/agent/list 接口未验证
