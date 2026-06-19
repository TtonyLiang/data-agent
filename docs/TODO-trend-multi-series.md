# 趋势分析增强 TODO

## 背景

当前系统在处理“各个贷款申请量变化趋势”这类问题时，已经能识别出“申请笔数 + 趋势”语义，但最终结果仍偏向“总体趋势”或“单一聚合趋势”，没有稳定产出“按贷款产品类型分别观察趋势”的多序列分析结果。

这会导致一个明显体验问题：

- 用户问的是“各个贷款”的变化趋势
- 最终只看到“贷款申请总量”的变化
- 报告缺少“不同贷款产品类型之间趋势差异”的核心信息

## 目标

先实现一版**单 SQL 的多序列趋势分析**，让以下类型问题能正确回答：

- 各个贷款申请量变化趋势
- 各贷款产品申请量趋势
- 不同贷款产品近几个月申请量变化

这一版优先解决“答不对题”的问题，不先引入完整的多 SQL 查询计划。

---

## 方案选择

### 方案 A：单 SQL 多序列趋势

推荐先执行这一版。

思路：

- 语义层把“各个贷款”优先解释成“各贷款产品类型”
- LogicForm 同时表达：
  - `metric = application_count`
  - `dimension = application_product_type`
  - `grain = month`
- SQL 编译生成：
  - `month x application_product_type x application_count`
- PythonAnalyze 输出多序列趋势洞察
- ReportGenerator 输出多条线趋势图和对比结论
- 前端忠实渲染后端给出的多 series 图表

示例 SQL：

```sql
SELECT
  DATE_FORMAT(t0.`apply_date`, '%Y-%m') AS `month`,
  t0.`product_type` AS `application_product_type`,
  COUNT(*) AS `application_count`
FROM `loan_application_indicator` t0
WHERE t0.`apply_date` >= DATE_SUB(CURRENT_DATE, INTERVAL 3 MONTH)
GROUP BY DATE_FORMAT(t0.`apply_date`, '%Y-%m'), t0.`product_type`
ORDER BY `month` ASC, `application_count` DESC
```

### 方案 B：多 SQL 查询计划

作为后续增强，不在本轮先做。

适用场景：

- 不仅要看趋势
- 还要同时看总览、排名、异常、补充对比

示例：

1. 主查询：按月 + 产品类型趋势明细
2. 补充查询：整体月度申请量趋势
3. 补充查询：各产品累计申请量排名
4. 补充查询：波动最大月份 / 增长最快产品

这一版需要把当前 `single SQL -> single result` 链路升级成 `query plan -> multi SQL -> multi result`，改动面明显更大，所以放在第二阶段。

---

## 本轮执行范围

当前进度：

- [x] 语义增强已把“各个贷款申请量变化/趋势”优先改写为“按月份统计各贷款产品类型申请笔数变化趋势”
- [x] LogicForm 已支持 `application_count + application_product_type + grain=month + recent_3_months`
- [x] SQL 编译已支持 `month + application_product_type` 的稳定分组输出
- [x] PythonAnalyze 已增加 `multi_series_trend` 模式
- [x] ReportGenerator / 前端已支持多序列折线图渲染
- [ ] 真实链路自测与样例问题回归仍需继续完成

### 1. 语义理解增强

- 把“各个贷款”“各贷款产品”“不同贷款产品”识别为产品类型维度意图
- 当问题同时包含：
  - 申请量 / 申请笔数
  - 变化 / 趋势 / 按月
  - 各个 / 各类 / 不同贷款
  时，优先增强为：
  - “查询各贷款产品类型按月份的申请笔数变化趋势”

注意：

- 如果用户明确问“总体申请量趋势”，不能擅自加产品维度
- 如果用户明确问“各区域趋势”“各渠道趋势”，优先使用对应维度，不强行落到产品类型

### 2. LogicForm 表达能力补强

当前趋势分析已经支持 `grain = month`，本轮要补的是：

- 趋势模式下允许同时保留一个分类维度
- 对这类问题稳定生成：
  - `metrics = ["application_count"]`
  - `dimensions = ["application_product_type"]`
  - `grain = "month"`
  - `time_range = recent_3_months` 或其他默认趋势窗口

### 3. SQL 编译增强

当前 `grain` 已能生成时间维度，但要确认支持：

- `grain + dimension` 同时 group by
- 输出字段顺序稳定为：
  - `month`
  - `application_product_type`
  - `application_count`

目标 SQL 结构：

- `GROUP BY month, application_product_type`
- `ORDER BY month ASC`

必要时可附加次排序，但不能破坏前端趋势分析读取。

### 4. PythonAnalyze 多序列趋势模式

新增或细化一种分析模式：

- `multi_series_trend`

输入特征：

- 存在时间维度
- 存在一个分类维度
- 存在一个数值指标

输出目标：

- 每个产品类型一条时间序列
- 识别：
  - 哪个产品整体最高
  - 哪个产品增长最快
  - 哪个产品波动最大
  - 是否存在趋势分化
- 输出更适合报告的 `insights`
- 输出多序列 line 图所需的 `echarts_option`

### 5. ReportGenerator 报告增强

报告需要从“总体趋势”升级为“分产品趋势对比报告”。

建议新增以下表达：

- 执行摘要：
  - 总体趋势
  - 头部产品
  - 增长/下滑最明显产品
- 结果解读：
  - 各产品走势差异
  - 是否有分化、交叉或拐点
- 图表：
  - 一张多条线的趋势图
- 表格：
  - 保留月度 x 产品类型明细

### 6. 前端图表渲染增强

当前前端报告图表更偏单序列渲染，本轮需要支持：

- 后端传入 `echarts_option.series[]`
- 多 series line 忠实渲染
- 图例展示
- 不再把多序列压扁成单条数据流

前端原则：

- 图表类型由后端决定
- 前端不自己猜“这是不是多序列趋势”
- 前端只负责忠实渲染

---

## 暂不执行的内容

- 不做完整多 SQL 查询计划
- 不改成 Planner 自动拆多个独立 SQL
- 不在本轮处理“趋势 + 归因分析”的复杂组合任务
- 不为所有领域泛化，只先把贷款申请量趋势这类典型问题做稳

---

## 验收标准

### 功能验收

以下问题能稳定得到“按贷款产品类型拆开的趋势结果”，而不是总趋势：

- 各个贷款申请量变化趋势
- 各贷款产品申请量趋势
- 不同贷款产品近三个月申请笔数变化

### LogicForm 验收

应稳定生成类似结构：

```json
{
  "metrics": ["application_count"],
  "dimensions": ["application_product_type"],
  "grain": "month",
  "time_range": {"type": "relative", "period": "recent_3_months"}
}
```

### SQL 验收

应稳定生成：

- 含 `month`
- 含 `application_product_type`
- 含 `application_count`
- `GROUP BY month, application_product_type`

### 报告验收

报告中应明确出现：

- 分产品趋势图
- 各产品趋势差异说明
- 不再只有“总体趋势”结论

### 前端验收

主对话与报告弹窗里：

- 多条折线都能显示
- 图例可读
- 报告文字与图表一致

---

## 推荐实施顺序

1. 语义增强规则补强
2. LogicForm 趋势 + 产品维度稳定生成
3. SQL 编译验证
4. PythonAnalyze 多序列趋势模式
5. ReportGenerator 文案与图表增强
6. 前端多 series line 渲染
7. 真实链路自测

---

## 第二阶段预留

当方案 A 稳定后，再评估是否推进：

- `query_plan`
- `compiled_queries[]`
- `sql_results[]`
- 多 SQL 执行链路
- 更完整的深度分析报告编排

这一阶段更适合处理：

- 趋势 + 排名 + 总览 + 异常
- 趋势 + 补充对比
- 更像分析师报告的复杂任务
