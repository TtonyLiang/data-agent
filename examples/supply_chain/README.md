# 供应链运营 Ontology 示例

`ontology-bundle.json` 是业务本体工作台的演示数据，覆盖供应商、物料、生产工单、对象关系、动作定义和对象实例。

使用方式：

1. 在“语义层配置”创建或选择一个领域。
2. 调用 `POST /api/ontology/domains/{domain_id}/import`，请求体为：

```json
{
  "bundle": "ontology-bundle.json 的 JSON 内容",
  "replace": false
}
```

3. 在“业务本体”工作台执行校验和发布。
4. 在“实例”中选择物料，执行“调整物料分配”，并在“活动”查看决策前后状态。
