# 贷款风险交付技术演示

日期：2026-09-01

这份演示在已有贷款 Ontology 之上验证“风险事项 -> 证据 -> 报告初版 -> 人工复核 -> 报告修订 -> 定稿 -> 审计验证”的技术闭环。演示中的阈值、规则、结论和处置建议均为测试数据，不代表真实信贷政策，也不能用于实际授信或催收决策。

## 1. 演示资产

| 文件 | 作用 |
|---|---|
| `examples/loan/ontology-bundle.json` | 已有贷款对象、关系、动作和演示实例 |
| `examples/loan/risk-workflow-bundle.json` | 风险事项、证据、复核和报告版本编排 |
| `scripts/verify_loan_risk_delivery_demo.py` | 针对本地 API 执行完整闭环并清理临时数据 |
| `tests/test_loan_risk_workflow_bundle.py` | 校验演示 bundle 的结构和业务覆盖 |

风险 bundle 中的 `ref`、`subject`、`issue_refs`、`version_ref` 和 `bind_current_ontology_release` 是 E2E 脚本使用的客户端引用。每个 `request` 才是发送给对应风险 API 的载荷。

## 2. 演示场景

演示绑定已有贷款 Ontology 中的两个真实对象实例：

- `LoanAccount=700001`，显示名 `LN-20250001`：当前逾期45天、剩余本金42,000元，创建 `critical` 级别的“M1+逾期催收风险”。
- `CustomerRiskSnapshot=600001`，显示名 `200001-2026年08月风险快照`：DTI 为0.62，创建 `high` 级别的“高 DTI 人工复核风险”。

每个事项包含对象快照、指标、演示规则和查询四类证据。API 类型分别使用 `ontology_object`、`metric`、`manual` 和 `query`；其中 `manual` 的内容保存本次技术演示规则。所有证据均显式保存 `trace_id`、`source_ref` 和结构化 `content`。

人工复核结果：

- M1+ 事项提交 `confirm`。
- 高 DTI 事项提交 `request_info`，要求补充收入和负债资料。

报告采用两个不可混淆的版本：

- `V1`：绑定两个事项和当前 Ontology release，记录复核前内容。
- `V2`：绑定相同事项和 release，写入人工复核结果后定稿。

## 3. API 闭环

脚本依次调用：

```text
POST /api/risk/domains/{domain_id}/issues
POST /api/risk/domains/{domain_id}/issues/{issue_id}/evidence
POST /api/risk/domains/{domain_id}/reports                            # 报告 + V1
POST /api/risk/domains/{domain_id}/issues/{issue_id}/reviews
POST /api/risk/domains/{domain_id}/reports/{report_id}/versions       # V2
POST /api/risk/domains/{domain_id}/reports/{report_id}/finalize
GET  /api/risk/domains/{domain_id}/audit
GET  /api/risk/domains/{domain_id}/audit/verify
```

运行时处理的绑定包括：

1. 从已导入的 Ontology 对象列表解析 `subject_object_id`。
2. 创建事项时注入临时领域的 `domain_id`，并用 `expected_version` 保护人工复核。
3. 将 bundle 中的事项引用转换为真实 `issue_ids`。
4. `POST /reports` 原子创建报告和 `V1`，`POST /versions` 创建 `V2`。
5. 服务端自动绑定当前 Ontology release，脚本校验两个版本返回的 `ontology_release_id`。
6. 定稿请求使用 `expected_version=2`，防止并发版本变化。

## 4. 运行验证

先启动使用同一管理数据库的本地服务：

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 4400
```

在另一个终端执行：

```bash
uv run python scripts/verify_loan_risk_delivery_demo.py
```

如本地服务使用其他端口，可显式指定地址：

```bash
WENQU_BASE_URL=http://127.0.0.1:4401 \
  uv run python scripts/verify_loan_risk_delivery_demo.py
```

脚本会创建临时管理员和临时领域，导入并发布 `examples/loan/ontology-bundle.json`，再读取风险 bundle 执行闭环。成功时只输出状态、版本和数量，不输出账号、密码或 token。无论成功或失败，`finally` 都会尝试删除临时领域、临时 agent 和临时管理员。

结构测试：

```bash
uv run pytest tests/test_loan_risk_workflow_bundle.py -q
```

预期验证项：

- 创建2个风险事项和8条证据。
- 创建1份报告及 `V1`、`V2` 两个版本。
- 完成 `confirm` 与 `request_info` 两种人工复核。
- `V2` 定稿成功。
- 审计事件不少于 bundle 声明的16条。
- `/audit/verify` 返回有效的 hash 链验证结果。

## 5. 技术边界

- 查询证据中的 SQL 是演示证据内容，E2E 脚本不会绕过权限直接执行该 SQL。
- 风险事项绑定的是导入后的 Ontology 对象 ID，不绑定源业务库中的临时行号。
- 报告版本必须绑定实际发布返回的 release ID，不能使用固定占位值。
- 本演示验证技术能力，不验证风险规则准确率、误报率、信贷政策合规性或生产审批授权。
