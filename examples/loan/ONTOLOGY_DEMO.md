# 信贷业务智能体 Ontology Demo

这份 Demo 把现有的 `loan_risk` 信贷语义域扩展成一个可运行的业务本体。它不是替换现有问数语义层，而是把“谁、申请了什么、形成了哪笔贷款、当前是否逾期、应该采取什么动作”表达成可查询、可执行、可审计的业务对象。

## 1. 两条链路如何配合

| 链路 | 负责什么 | 入口 |
|---|---|---|
| 语义问数 | 审批通过率、申请趋势、M1+ 逾期率、Vintage、催收回收率等聚合指标 | 对话页 |
| 业务 Ontology | 客户、申请、贷款、期次、风险快照、催收案件的对象状态，以及审批/催收/结案动作 | `业务本体`工作台 |

当前 MVP 会把 Ontology 定义注入信贷 Agent 的问数上下文，但聊天 ReAct 尚未自动调用 Ontology 动作工具。因此本 Demo 的“动作执行”通过工作台完成，或调用两个受控 REST 工具；不要把普通问数对话误认为已经自动审批或自动催收。

## 2. Demo 内容

导入文件：`examples/loan/ontology-bundle.json`

- 6 个对象类型：`Customer`、`LoanApplication`、`LoanAccount`、`RepaymentPeriod`、`CustomerRiskSnapshot`、`CollectionCase`
- 6 个业务库只读同步查询：每个对象类型均启用 `sync_enabled=true`，默认分页大小为 `200`
- 6 个关系类型：客户-申请、客户-贷款、申请-贷款、贷款-还款期次、贷款-风险快照、贷款-催收案件
- 3 个动作类型：`approve_application`、`start_collection`、`close_collection_case`
- 1 个演示客户：`200001`
- 1 笔人工复核申请：`APP-20260830-0001`
- 1 笔 M1 逾期贷款：`LN-20250001`，当前逾期 45 天，剩余本金 42,000
- 1 个打开状态催收案件：`COL-20260830-0001`

## 3. 准备信贷语义域

如果项目里已经有 `loan_risk` 领域，可直接从第 4 步开始。若要让对话页也能查询信贷指标，先导入现有语义问数资产：

```bash
# 只做预览，不写库（推荐先执行）
uv run python examples/loan/seed_loan_indicators.py

# 只有确认允许重建本地演示表时才执行；会 DROP/重建信贷演示表
uv run python examples/loan/seed_loan_indicators.py --write --yes-drop-existing

# 非破坏性补充 2026-08-31 的当前演示数据（不会 DROP 既有表，可重复执行）
uv run python examples/loan/seed_loan_indicators.py --append
uv run python examples/loan/seed_loan_indicators.py --append --write --yes-append

# 将现有审批率、M1+、Vintage 等问数语义导入同一个信贷智能体
uv run python scripts/import_semantic_bundle.py \
  --path examples/loan/semantic-domain.json \
  --agent-id 1 \
  --datasource-id 1
```

演示环境必须显式使用 `--agent-id 1 --datasource-id 1`，不要省略数据源参数。`import_semantic_bundle.py` 只会对语义资产执行 upsert，不会删除 bundle 中未出现的旧 `semantic_relation`；如需清理旧关系，应先备份并核对，再单独执行定向清理。

在“智能体管理”中把这个 `loan_risk` 语义域绑定到信贷智能体，并确认领域已绑定包含上述信贷表的默认数据源。对象同步沿用该智能体的数据权限，因此还要允许访问 `loan_application_indicator`、`loan_account_indicator`、`loan_repayment_period_indicator`、`customer_risk_monthly_indicator` 和 `collection_case_indicator`。

## 4. 业务库同步映射

`ontology-bundle.json` 中的 `source_query` 都是单条只读 `SELECT`，按对象主键稳定排序且不包含顶层 `LIMIT`。同步服务按 `sync_limit=200` 自动追加 `LIMIT/OFFSET`，逐页读取全部数据。

| 对象类型 | 主要来源 | 关键映射 |
|---|---|---|
| `Customer` | `customer_risk_monthly_indicator` | 每个客户只取最新月份、同月最大 `snapshot_id` 的一行；`monthly_income_estimate -> monthly_income`、`dti -> debt_income_ratio` |
| `LoanApplication` | `loan_application_indicator` | `approval_amount -> approved_amount`；审批时间由 `created_at + decision_time_minutes` 计算；黑名单状态取客户最新风险快照 |
| `LoanAccount` | `loan_account_indicator` | 按逾期天数派生 `C/M1/M2/M3/M4+`；催收动作字段提供未执行时的基础值 |
| `RepaymentPeriod` | `loan_repayment_period_indicator` | 关联贷款账户，用借据号和期数生成 `period_label` |
| `CustomerRiskSnapshot` | `customer_risk_monthly_indicator` | 用客户、统计月份生成 `snapshot_label` |
| `CollectionCase` | `collection_case_indicator` | `case_end_date -> closed_at` |

这里的“实时同步”是页面触发模式：进入“对象实例”页或点击刷新时同步当前页，切换对象类型或翻页时继续读取对应的服务端数据页；它不是数据库 CDC 或后台定时任务。业务数据库始终只读，查询结果写入对象的 `source_properties`。审批、催收和结案动作只写本体对象的 `overlay_properties`，展示和动作校验使用 `source_properties + overlay_properties`，同名字段以本地 overlay 为准，后续刷新不会覆盖已经执行的本体动作结果。

## 5. 工作台操作顺序

1. 用管理员账号打开 `/ontology`，在顶部选择 `贷款风控` 或 `贷款风控运营本体` 所属领域。
2. 点击“导入”，选择 `examples/loan/ontology-bundle.json`。这里必须导入 `format=wenqu-ontology` 文件；旧的 `semantic-domain.json` 是问数语义格式，不能直接导入本体工作台。
3. 点击“校验”。预期结果是 `6` 个对象类型、`6` 个关系类型、`3` 个动作类型，且 `valid=true`。
4. 点击“发布”。动作执行前必须至少存在一个发布快照，例如 `V1`。
5. 切换到“对象实例”。页面默认选择一个已启用同步的对象类型并读取当前页，刷新按钮重新同步当前页；切换类型或翻页会继续读取对应业务数据。点击“建立关系”可创建关系实例。图谱视图展示对象类型和动作定义，当前工作台不单独列出关系实例表，可通过导出或 REST `GET /api/ontology/domains/{domain_id}/links` 核对。
6. 在“动作类型”中执行 `审批贷款申请`：
   - 目标对象：`APP-20260830-0001`
   - 审批金额：`50000`
   - 审批说明：`风险等级C，黑名单未命中，人工复核通过`
   - 审批单号：`APR-20260830-0001`
   - 结果：`approval_status` 从 `manual_review` 变为 `approved`，对象版本号递增。
7. 执行 `发起电话催收`：
   - 目标对象：`LN-20250001`
   - 催收策略：`电话催收`
   - 决策理由：`当前逾期45天，属于M1+，未核销`
   - 结果：`collection_status` 变为 `ready`，并写入催收策略、决策说明和更新时间。
8. 执行 `结案催收案件`：
   - 目标对象：`COL-20260830-0001`
   - 回收本金：`12000`
   - 结案原因：`客户承诺还款并完成首笔回收`
   - 结果：`case_status` 变为 `closed`，并记录回收本金和结案时间。
9. 切换到“决策活动”，查看每次动作的执行人、参数、决策上下文、执行前状态和执行后状态；同一动作还会进入“风险交付 -> 决策审计”的追加式哈希链，用于跨风险、报告和动作回放。

## 6. 业务问题示例

### 纯问数问题

这些问题继续交给现有语义问数链路：

```text
最近3个月各区域申请笔数趋势
按 Vintage 看 MOB3 的 M1+ 逾期率
各催收团队回收率排名
```

### 对象查询与受控动作

```text
查客户 200001 的最新风险、在贷余额和逾期贷款；如果逾期超过30天，建议发起电话催收。
```

当前 MVP 的实际操作是：先在对象实例中查 `Customer=200001`、`CustomerRiskSnapshot=200001-2026年08月风险快照` 和 `LoanAccount=LN-20250001`，核对 `risk_grade=C`、`dti=0.62`、`remaining_principal=42000`、`current_overdue_days=45`，再由有权限的操作员在动作弹窗中确认并执行 `start_collection`。

## 7. 受控 REST 演示（可选）

登录后把 `<token>`、`<domain_id>`、`<action_type_id>` 和 `<object_id>` 替换成实际值。先查询对象，再使用对象返回的 `version` 作为乐观锁版本：

```bash
curl -H "Authorization: Bearer <token>" \
  "http://127.0.0.1:4400/api/ontology/domains/<domain_id>/query?object_type_key=LoanAccount&search=LN-20250001"

curl -X POST \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  "http://127.0.0.1:4400/api/ontology/domains/<domain_id>/actions/<action_type_id>/execute" \
  -d '{
    "target_object_id": <object_id>,
    "expected_version": 1,
    "parameters": {
      "collection_strategy": "电话催收",
      "reason": "当前逾期45天，属于M1+，未核销"
    },
    "decision_context": {
      "source_question": "查客户200001的逾期贷款",
      "reason": "M1+"
    }
  }'
```

也可以使用面向 Agent 的两个受控工具：

- `POST /api/ontology/domains/{domain_id}/agent-tools/ontology_query_objects`
- `POST /api/ontology/domains/{domain_id}/agent-tools/ontology_execute_action`

这两个工具仍然会重复执行领域权限、角色、发布状态、参数、前置条件和乐观锁校验；它们不允许 Agent 直接提交任意 SQL。

## 8. 这个 MVP 有意没有做什么

- 不自动创建外部催收工单或调用 ERP/短信系统。
- 不做数据库 CDC、消息队列订阅或后台定时同步；对象实例由进入页面和刷新操作触发分页同步。
- 不实现动态 ABAC、正式审批流、失败补偿和分布式图事务。
- 复杂聚合和“最新快照”排序仍由语义问数 SQL 处理；Ontology 查询 API 当前适合对象主键/名称检索。
- `start_collection` 只更新 `LoanAccount` 的催收状态，不自动新建 `CollectionCase`；Demo 预先放入一个催收案件，后续再扩展事务型动作编排。

这样可以先验证一个真实闭环：**定义业务对象 -> 发布口径 -> 找到风险对象 -> 人工确认动作 -> 状态变化 -> 审计复盘**。
