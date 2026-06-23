# 抖音带货电商演示域

这个目录用于显式初始化第二个演示智能体：`抖音带货电商分析助手`。

运行脚本：

```bash
.venv/bin/python examples/douyin_ecommerce/seed_douyin_ecommerce.py
```

脚本会在本地 MySQL 创建独立业务库 `douyin_ecommerce_demo`，并在管理台配置：

- 智能体：抖音带货电商分析助手
- 数据源：抖音带货电商业务库
- 语义层：抖音带货电商
- 表采集：8 张核心业务表
- 语义资产：概念、关系、指标、规则、映射、模板

## 业务表

每张表约 10,000 行演示数据：

- `dim_douyin_creator`：抖音达人维表
- `dim_douyin_shop`：抖音店铺维表
- `dim_douyin_product`：抖音商品维表
- `fact_live_session`：直播场次事实表
- `fact_short_video`：短视频种草事实表
- `fact_douyin_order`：抖音订单事实表
- `fact_ad_spend`：千川投放消耗事实表
- `fact_after_sale`：售后退款事实表

## 可问示例

- 最近三个月各个类目的 GMV 变化趋势是什么？
- GMV 排名前 10 的达人是谁，分别成交了多少？
- 不同成交渠道的订单量和 GMV 分别是多少？
- 各投放类型的消耗、归因 GMV 和 ROI 表现如何？
- 退款金额最高的商品类目有哪些，主要售后原因是什么？
- 直播间观看人数和直播 GMV 按达人等级对比一下。

## 说明

这个脚本是显式演示初始化工具，不会被运行时自动读取。业务口径仍然会落到管理库语义层配置里，可在页面查看和修改。
