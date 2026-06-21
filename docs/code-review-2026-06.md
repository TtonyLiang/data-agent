# WenQu 智能问数项目 — 代码审查报告

> 审查日期：2026-06-19
> 审查范围：后端（FastAPI + LangGraph）、服务层、SQL / Python 安全沙箱、API 层、前端关键代码、工程化配置
> 结论：整体设计思路（语义层 + LogicForm 确定性编译 + NL2SQL 兜底 + Python 安全执行 + 流式报告）合理，但存在若干**安全问题、健壮性缺陷和逻辑 bug**。下面按严重程度分级列出，并给出解决方案与代码位置。

---

## 🔴 一、严重问题（安全 / 数据正确性）

### 1.1 CORS 完全开放 + 凭证允许 — 生产级 CSRF / 凭证泄露风险

**位置**：`app/main.py:94-100`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,   # ← 与 * 同存是危险组合
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**问题**：`allow_origins=["*"]` 与 `allow_credentials=True` 同时存在。浏览器虽然会拒绝这种组合的凭证请求，但它表达了错误的意图，且一旦未来改成具体域名 + credentials，任意站点都能携带用户 cookie 调用你的 API。本系统所有 `/api/*` 端点都无鉴权（见 1.2），等于完全裸奔。

**解决方案**：从 `.env` 读取白名单，并明确是否允许凭证：

```python
allow_origins=settings.cors_allowed_origins,  # ["http://localhost:5173", "https://your.domain"]
allow_credentials=False,  # 当前没有 cookie 鉴权，应关闭
```

---

### 1.2 所有 API 无任何鉴权 — 任何人可读 / 写数据源密码、模型 Key

**位置**：`app/api/*.py` 全部端点；`app/main.py` 所有 chat 端点

搜索 `Depends`、`get_current_user`、`JWT` —— **零命中**。这意味着：

- `GET /api/datasource/list` 虽然排除了 `password` 字段，但 `POST /api/datasource/{id}/test`、`PUT /api/datasource/{id}` 可以读到完整配置。
- `DELETE /api/agent/{id}` 会级联删除语义层、会话历史（`app/api/agent.py:83-104`）—— 任何访问到端口的人都能清空数据。
- 模型配置里的 API Key 虽然在 list 接口脱敏，但数据库里是**明文存储**（`migrations.py:22` `api_key VARCHAR(512)`，无加密）。
- `chat` 接口可被无限调用，直接消耗你的 LLM API 配额（见 1.3）。

**解决方案**：

- 至少接入一个最小鉴权中间件（API Key Header / JWT / OAuth），用 FastAPI `Depends`。
- 数据源密码、模型 Key 在 DB 中应使用对称加密（如 Fernet）存储，密钥从环境变量读。
- 提供 `/api/health` 之外的端点要求 `Authorization` Header。

---

### 1.3 无限流 / 无配额保护 — LLM 成本和 DoS 风险

**位置**：整个应用

`chat` / `chat/stream` 每次都调用多次 LLM（语义增强 + NL2LF + 兜底 + Python 生成 + 报告生成）。搜索 `rate_limit | slowapi | throttle` —— **零命中**。

**解决方案**：

- 引入 `slowapi` 或网关层限流（按 IP / 用户 / agent_id）。
- 对单个会话 / trace 增加并发控制（避免一个用户并行触发多个流）。

---

### 1.4 NL2SQL 兜底是 Prompt Injection 的主战场，但沙箱不够

**位置**：`app/agent/nodes/nl2sql_fallback.py`、`app/utils/sql_validator.py`

`sql_validator.py` 的关键字黑名单是**词法级**的，容易被绕过。例如：

- 注释绕过：`SELECT * FROM users;` 在 `--` 后藏 Payload —— 当前能处理单条 SELECT，但…
- 多语句拼接的边界条件：`enforce_top_level_limit` 通过 `find_top_level_keyword` 找 LIMIT，但对 CTE、子查询里的 LIMIT 没有处理（虽然这不会造成注入，但会错误改写 SQL）。
- **`INTO` 被禁止是对的**，但 `SELECT ... INTO OUTFILE '/tmp/x'` 这类 MySQL 特性需要确认 `OUTFILE` 也被拦截 —— 当前 `FORBIDDEN_KEYWORDS` 没有 `OUTFILE`、`INFILE`、`DUMPFILE`。

**解决方案**：

```python
FORBIDDEN_KEYWORDS = {..., "OUTFILE", "INFILE", "DUMPFILE", "HANDLER", "XA", "PREPARE", "EXECUTE"}
```

更稳妥的是引入 `sqlglot` / `sqlparse` 做 AST 级校验（项目设计文档第 374 行也提到了这一演进方向）。

---

### 1.5 Python 沙箱 AST 校验可被绕过

**位置**：`app/services/python_executor.py:86-114`、`app/agent/nodes/analysis_pipeline.py:846-888`

`_validate_code` 靠遍历 AST 拦截 `open/exec/eval/compile/__import__` 和危险属性。但：

- `getattr(obj, "sys" + "tem")` 字符串拼接可绕过 `node.attr == "system"` 的字面量检查。
- `(1).__class__.__bases__[0].__subclasses__()` 走的是属性访问，当前只拦 `"system","popen",...` 这几个具体名字，**不拦 `__class__`、`__bases__`、`__subclasses__`、`__globals__`、`__builtins__`**。
- 子进程虽然用了 `-I`（isolated）和 `RLIMIT_AS`，但子进程**以主进程相同用户身份运行**，能读 `~/.env`、`/etc/passwd` 等；`preexec_fn` 只在 fork 系统上生效（`hasattr(os, "fork")`），**macOS 上 Python 子进程不走 preexec_fn 这条路径也会运行**——但 darwin 上 `os.fork` 实际存在，所以会执行；Linux 容器里 OK。

**解决方案**（优先级从高到低）：

1. 生产**强制**使用 worker / docker 后端（代码已有 `allow_local_python_executor_in_production=False`，要确保生产 `DEBUG=false`）。
2. AST 黑名单加上所有 `__dunder__` 属性访问：

   ```python
   elif isinstance(node, ast.Attribute):
       if node.attr.startswith("__") or node.attr in {...}:
           raise PythonExecutionError(...)
   ```

3. 考虑 seccomp / bwrap 真正隔离，而不是依赖 AST 字面量匹配。

---

### 1.6 数据库密码与 API Key 落盘明文

**位置**：`app/services/datasource_service.py:30-33`、`app/db/migrations.py:22`

`datasource.password`、`model_config.api_key` 都是明文写入 MySQL。任何拿到管理库 dump 的人立即获得所有业务库密码和 LLM Key。

**解决方案**：引入 `cryptography.fernet`，在 service 层加解密，密钥从 K8s Secret / 环境变量读。

---

## 🟠 二、重要 Bug 与逻辑缺陷

### 2.1 `route_after_sql_execute` 失败时仍路由到 success，违反重试语义

**位置**：`app/agent/graph.py:234-239`

```python
def route_after_sql_execute(state: AgentState) -> str:
    if state.get("sql_result"):
        return "success"
    if state.get("sql_error") and state.get("sql_retry_count", 0) < MAX_SQL_RETRIES:
        return "retry"
    return "success"   # ← bug：超过重试次数后，sql_error 仍然存在，却返回 success
```

当 `sql_error` 非空但已用完重试次数时，会跳到 `planner` → `python_generate`，但此时 `sql_result` 是空的，`planner` 会基于空结果生成报告，用户得到一份"分析失败但流程成功"的报告，掩盖了错误。

**解决方案**：

```python
def route_after_sql_execute(state: AgentState) -> str:
    if state.get("sql_result"):
        return "success"
    if state.get("sql_error") and state.get("sql_retry_count", 0) < MAX_SQL_RETRIES:
        return "retry"
    return "failed"   # 新增一条边：failed → END
```

并在 `build_mvp_graph` 里加：

```python
graph.add_conditional_edges(
    "sql_execute", ...,
    {"success": "planner", "retry": "lf_repair", "failed": END}
)
```

---

### 2.2 `route_after_semantic_check` 与图定义的 edge 集合不匹配

**位置**：`app/agent/graph.py:167-176`

图定义里 `semantic_check` 的条件边字典是 `{"valid", "confirm", "repair", "invalid"}`，但 `route_after_semantic_check` 没有显式返回 `"failed"` 这类。结合 2.1，这条链路上任何错误最终都会"成功生成报告"，**这是报告里出现"假装成功"的根本原因**。`analysis_pipeline.py:1125-1131` 虽然有 `analysis_failed` 状态分支，但前提是 Python 节点失败；SQL 失败却完全不会标记。

**解决方案**：在 `planner` 节点开头检查 `sql_error`，若存在则生成"查询失败报告"并跳过后续节点直接 END，或如 2.1 修复路由。

---

### 2.3 `execute_query` 对 INSERT/UPDATE/DELETE 也用 `execute_query`，事务语义混乱

**位置**：`app/db/mysql.py:40-76`、`app/services/datasource_service.py:108-111` 等

`MySQLClient.execute_query` 在 `returns_rows=False` 时 `await session.commit()`，但调用方大量用它执行 `UPDATE datasource SET ...`（`datasource_service.py:108`）、`DELETE FROM agent_datasource`（`datasource_service.py:210`）。问题：

- `set_agent_datasources`（`datasource_service.py:200-223`）先 `DELETE` 再循环 `INSERT`，**每条语句各自一个 session 各自 commit**。如果中间崩溃，会出现"删除了旧绑定但没插入新绑定"的不一致状态。
- 同样的模式出现在 `metadata_service.collect_schema:252-317`：每张表 / 每列都是独立 session，失败时部分采集。

**解决方案**：引入事务封装：

```python
async def execute_transaction(self, statements: list[tuple[str, dict]]):
    async with self._session_factory() as session:
        async with session.begin():
            for sql, params in statements:
                await session.execute(text(sql), params)
```

把 `set_agent_datasources`、`collect_schema` 改成单事务。

---

### 2.4 `asyncio.to_thread(client.invoke, ...)` 在高并发下阻塞 worker

**位置**：`app/services/llm_service.py:266, 335`

```python
resp = await asyncio.to_thread(client.invoke, lc_messages)
```

`ChatOpenAI.invoke` 是同步 HTTP 调用，`to_thread` 把它丢到默认线程池（Python 默认 `min(32, os.cpu_count() + 4)`）。在 SSE 流式场景下，单个 chat 会话会触发 4–6 次 LLM 调用，并发 10 个用户就能打满线程池，导致整个进程（包括 DB 操作）卡顿。

**解决方案**：直接用 `await client.ainvoke(lc_messages)`（langchain-openai 原生支持 async），删除 `to_thread`。

---

### 2.5 `ast.parse(code)` 未捕获 `IndentationError` / 其他语法异常

**位置**：`app/services/python_executor.py:88-90`、`app/agent/nodes/analysis_pipeline.py:855`

```python
try:
    tree = ast.parse(code)
except SyntaxError as exc:
```

`ast.parse` 还会抛 `ValueError`（null bytes）、`TabError`、`IndentationError`（后者其实继承自 `SyntaxError`，OK）。但 LLM 生成的代码里可能包含 null byte，会抛 `ValueError`，导致整个 generate 节点 500。

**解决方案**：`except (SyntaxError, ValueError) as exc`。

---

### 2.6 `parse_logic_form` JSON 解析无防御

**位置**：`app/agent/nodes/nl2lf_generate.py:418-425`

```python
def parse_logic_form(response: str) -> LogicForm:
    text = response.strip()
    if "```" in text:
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:].strip()
    return LogicForm(**json.loads(text))   # ← 抛异常会被上层 try 捕获，但...
```

虽然外层 `try/except` 会 fallback，但 `text.split("```", 2)[1]` 在模型输出只有开头 ``` 而无结尾时可能切错；且 `json.loads` 失败时错误信息会暴露完整 prompt。

**解决方案**：用更鲁棒的提取（参考 `extract_sql_from_response` 的实现），并统一在日志里 redact。

---

### 2.7 `sql_execute_node` 缺少超时控制

**位置**：`app/agent/nodes/sql_execute.py:97-106`

```python
db = await get_datasource_db(datasource_id) if datasource_id else get_business_db()
results = await db.execute_query(safe_sql)
```

`MySQLClient` 的 `create_async_engine` 没有设置 `connect_args={"connect_timeout": ...}` 也没有 statement timeout。虽然 `normalize_sql_for_execution` 强制了 `LIMIT 1000`，但 `SELECT * FROM huge_table WHERE unindexed_col = ... LIMIT 1000` 仍可能扫全表，阻塞数十秒。

**解决方案**：

```python
create_async_engine(db_url, pool_size=5, max_overflow=10,
    connect_args={"connect_timeout": 10})
# 执行前：SET SESSION MAX_EXECUTION_TIME=10000
```

或在 `execute_query` 前 `SET STATEMENT max_execution_time=10000 FOR <sql>`。

---

## 🟡 三、设计与可维护性问题

### 3.1 `main.py` 单文件 1580 行，承担过多职责

**位置**：`app/main.py`

一个文件里塞了：FastAPI app、SSE 编解码、节点 trace 构造、所有 chat 端点、history 持久化、`compact_json_text`、`_extract_node_output` 等 30+ 辅助函数。

**解决方案**：拆分：

- `app/api/chat.py`（chat 端点 + SSE）
- `app/services/chat_history_service.py`（`save_turn` / `load_history` / `compact_*`）
- `app/services/sse_helpers.py`（`sse_event` / `hold_node_for_display` / `_extract_node_output` / `node_progress_message` / `summarize_trace_step`）

### 3.2 全局单例 + 模块级 `lru_cache` 使测试和热更新困难

**位置**：`app/config.py:97`、`app/db/mysql.py:141-143`、所有 `_service` 单例

`get_settings` 用 `@lru_cache`，`get_business_db` 用模块级 `_business_db` 全局变量。测试里只能 monkeypatch，无法注入；生产里改配置必须重启进程。`get_datasource_db` 的缓存 `_datasource_dbs` 永不清理（只有显式 `invalidate_datasource_db` 才清），如果数据源被频繁增删，会**内存泄露 + 连接泄露**。

**解决方案**：

- 用 FastAPI 的 `Depends` + lifespan 管理生命周期。
- 给 `_datasource_dbs` 加 LRU 或 TTL，或在 `delete_datasource` 时统一 invalidate（目前 `delete` 调了 `invalidate_datasource_db`，但 `update` 改了 host/port 后才 invalidate，如果只改了 agent 绑定关系则不会清——OK，但建议补 audit log）。

### 3.3 业务规则硬编码在 `nl2lf_generate.py`，扩展性差

**位置**：`app/agent/nodes/nl2lf_generate.py:113-170, 428-507`

`normalize_logic_form`、`fallback_logic_form` 把"贷款申请笔数"、"高 PD 分客群 = risk_grade D"等业务知识写死在代码里。换一个业务领域（比如电商）就要改 Python 代码 redeploy。

**解决方案**：把这些规则挪到语义层 `semantic_rule` 表，让 `normalize_logic_form` 读规则做归一化（设计文档里也提到了 rule 资产，但代码没充分利用）。

### 3.4 `fallback_logic_form` 默认指标是 `outstanding_balance`

**位置**：`app/agent/nodes/nl2lf_generate.py:434`

```python
metrics = ["outstanding_balance"]
```

模型解析失败时，所有无法识别的问题都会去查"贷款余额"，这在非贷款业务里会产生奇怪的 SQL。这是一个**领域耦合到核心算法**的坏味道。

**解决方案**：fallback 时返回空 metrics，强制走 NL2SQL 兜底，而不是猜一个指标。

### 3.5 日志敏感信息脱敏不完整

**位置**：`app/utils/logging_helpers.py`

`SENSITIVE_KEYWORDS` 没有覆盖 `dsn`、`connection_string`、`private_key`；`redact_text` 的正则只处理手机号 / 身份证 / 卡号 / 邮箱 / Bearer，但 SQL 里出现的实际业务数据（身份证号、手机号）会被写入 `logs/`（`sql_sample_logging_enabled` 默认 `False`，OK，但 `detailed_data_logging_enabled=True` 时会完整记录 SQL 结果）。

**解决方案**：扩展关键字白名单，并在 `detailed_data_logging_enabled=True` 时强制走 `redact_text`（目前已经走了，但只针对字符串顶层，嵌套结构里 JSON 序列化后的字符串不会被二次匹配）。

### 3.6 测试覆盖不均

- 后端有 25 个测试文件，覆盖了关键节点（SQL 校验、权限、NL2SQL 兜底）。
- 但 `tests/` 里**没有**测试 `route_after_sql_execute` 的失败路径（2.1 的 bug 就是因为没有测试覆盖）、没有测试 Python 执行器的安全绕过场景、没有并发 / 限流测试。
- 前端测试是纯 Node 字符串断言（`ChatView.test.mjs` 检查 `!source.includes('v-html')`），不是真正的渲染测试。

**解决方案**：补 route 函数的单元测试，给 Python 执行器加"绕过用例"测试（红队回归）。

---

## 🟢 四、次要问题 / 代码质量

### 4.1 `.env.example` 与 `config.py` 默认值不一致

`.env.example:27` 写 `MILVUS_URI=http://127.0.0.1:19530`，但 `config.py:35` 默认 `milvus_uri: str = "./data/milvus.db"`（本地 Lite 模式）。新人按 example 配置可能跑不通。

**解决方案**：统一成同一种模式（推荐保留 `./data/milvus.db` 降低部署门槛），或在 example 里注释清楚两种模式区别。

### 4.2 `intent_recognition_node` 在函数内 `import json`

**位置**：`app/agent/nodes/intent.py:154`

```python
import json  # 函数内导入
try:
    result = json.loads(response.strip())
```

应移到模块顶部。`pyproject.toml` 里 `ruff` 已配置 `E402` 但函数内 import 不会被 E402 抓到。

### 4.3 `Lifespan` 启动时迁移失败会直接 `raise`，但没有降级

**位置**：`app/main.py:46-53`

```python
try:
    await run_management_migrations()
except Exception:
    logger.exception("management database migration failed")
    raise
```

迁移失败导致整个服务无法启动。在 K8s 里会陷入 CrashLoopBackOff。建议：迁移失败时仅禁用写入功能，保留 `/health` 可用，便于排查。

### 4.4 SSE 事件无序列号，前端乱序处理依赖 buffer

**位置**：`app/main.py:232-627`

`event_generator` 里 `reasoning` / `token` / `node_progress` 都是无序号事件，前端靠 `append_trace_stream_text` 顺序追加。但 `hold_node_for_display` 会 `await asyncio.sleep(remaining)`，期间 producer 仍在往 queue 写事件，**节点结束后才一次性吐出**，导致前端看到"卡 N 秒后突然刷一大片"。`MIN_NODE_DISPLAY_SECONDS = 1.0` 这个 UX 延迟在生产里建议移除或改为可配置。

### 4.5 `compact_report_payload_text` 截断后 JSON 可能不可解析

**位置**：`app/main.py:1509-1527`

```python
return f"{compacted_text[:max_chars]}... [truncated ...]"  # ← 截断后不是合法 JSON
```

写入 `chat_history.report_payload` 后，`get_history` 端点会 `json.loads` 它（`main.py:1324-1329`），截断过的字符串会解析失败被设为 `None`，**用户切换会话后报告消失**。

**解决方案**：在 `compact_json_text` 里截断前先尝试解析 → 截断字段 → 重新 dump，保证落盘的始终是合法 JSON。当前 `compact_report_payload_text` 已部分这么做了（先 dump 再判断长度），但 fallback 分支 `return f"{compacted_text[:max_chars]}..."` 仍会破坏 JSON。

### 4.6 `_datasource_dbs` 缓存 key 是 int，但 `get_datasource_db` 是 async，并发初始化会重复创建

**位置**：`app/db/mysql.py:191-220`

```python
async def get_datasource_db(datasource_id: int) -> MySQLClient:
    if datasource_id not in _datasource_dbs:   # ← check
        ds = await get_datasource_service().get(datasource_id)  # ← await 期间另一个协程也进来
        ...
        _datasource_dbs[datasource_id] = MySQLClient(...)  # ← set
```

两个并发请求同时进来，都会通过 `not in` 检查，各自创建一个 `MySQLClient`，最后一个覆盖前面的，**前面的 engine 泄露（永不 dispose）**。

**解决方案**：用 `asyncio.Lock` 或 `_pending: dict[int, asyncio.Future]` 模式：

```python
_datasource_locks: dict[int, asyncio.Lock] = {}
async def get_datasource_db(datasource_id: int):
    if datasource_id in _datasource_dbs:
        return _datasource_dbs[datasource_id]
    lock = _datasource_locks.setdefault(datasource_id, asyncio.Lock())
    async with lock:
        if datasource_id in _datasource_dbs:  # double-check
            return _datasource_dbs[datasource_id]
        # ...create...
```

### 4.7 `lru_cache` 装饰的 `load_prompt` 在测试中难以重置

**位置**：`app/agent/prompts/__init__.py:9-11`

`@lru_cache(maxsize=64)` 让 prompt 文件修改后必须重启进程。开发体验差，且测试中若 mock 文件系统需 `load_prompt.cache_clear()`。

**解决方案**：去掉 `lru_cache`，prompt 文件本身很小，IO 成本可忽略；或加显式 `reload_prompt(filename)` 函数。

### 4.8 前端 `ChatView.vue` 4487 行，难以维护

**位置**：`frontend/src/views/ChatView.vue`

单个 Vue 文件包含模板 + script + style 接近 4500 行，违反单一职责。建议拆分为 `ChatHeader.vue` / `ChatMessage.vue` / `ReasoningTrace.vue` / `ReportPanel.vue` / `SqlResultTable.vue` 等子组件，并按模块组织 composables（`useChatStream.ts`、`useMarkdownRender.ts`）。

### 4.9 `.env.example` 默认数据库密码 `root/root`

业务库和管理库默认密码都是 `root/root`，部署时如果忘记改，等于数据库公开。建议在 `config.py` 里加启动校验：`debug=true` 时允许默认密码，否则拒绝启动。

---

## 📊 优先级建议

| 优先级 | 问题 | 影响 |
|---|---|---|
| **P0 立即修复** | 1.2 (无鉴权)、1.6 (密码明文)、2.1 (路由 bug)、2.4 (线程池阻塞) | 安全 / 在线稳定性 |
| **P1 本迭代** | 1.1 (CORS)、1.4 (SQL 注入面)、1.5 (Python 沙箱)、2.2 (失败被掩盖)、2.3 (事务)、4.5 (历史 JSON 截断)、4.6 (DB 缓存并发) | 安全 / 数据正确性 |
| **P2 近期** | 1.3 (限流)、2.5/2.6 (异常未捕获)、2.7 (SQL 超时)、3.5 (日志脱敏) | 健壮性 |
| **P3 中期** | 3.1-3.4 (架构重构)、4.1-4.4 (代码质量)、4.8 (前端拆分) | 可维护性 |

---

## ✅ 做得好的地方（值得保留）

1. **SQL 执行前的多层校验**：`normalize_sql_for_execution` + `validate_sql_access` + `mask_rows`，权限和脱敏贯穿 schema 召回、NL2SQL、执行、结果四个环节。
2. **流式 trace 的设计**：`reasoning_trace` 同时落盘，会话切换后能恢复完整思考过程，体验比同类产品好。
3. **Prompt 模板的优先级解析**：`find_best` 用 `agent + model + domain` 三维度打分排序，配置化能力强。
4. **测试意识**：25 个后端测试文件，包括 `test_security_regressions.py` 这种专门的"回归用例"。
5. **设计文档完整**：`docs/project-design.md` 把每个节点的职责、是否调用模型、失败兜底都写清楚了，是难得的好实践。
6. **日志规范**：`log_node_start/end/error` + `redact_text`，结构化日志和敏感信息处理都有考虑。

---

## 附：修复路径建议

建议按以下顺序推进，每批可独立成 PR：

1. **PR-1（P0 安全）**：加鉴权中间件 + 密码 / Key 加密 + 修 `route_after_sql_execute` + LLM 调用改 `ainvoke`。
2. **PR-2（P1 健壮性）**：CORS 收紧 + SQL 黑名单补齐 + Python 沙箱 AST 加固 + DB 缓存并发锁 + 历史报告 JSON 截断修复。
3. **PR-3（P2 稳定性）**：接入 slowapi 限流 + SQL 超时 + 异常捕获补全 + 日志脱敏扩展。
4. **PR-4（P3 重构）**：`main.py` 拆分 + 业务规则下沉语义层 + 前端组件化。
