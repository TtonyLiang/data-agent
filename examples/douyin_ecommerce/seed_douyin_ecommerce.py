"""Seed a Douyin live-commerce demo agent, datasource, data, and semantic layer.

This is an explicit demo initializer. It creates a separate business database
``douyin_ecommerce_demo`` and visible management-console configuration, without
touching the existing loan agent.
"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db.mysql import build_mysql_async_url, get_management_db, invalidate_datasource_db
from app.models.datasource import DatasourceCreate
from app.services.datasource_service import get_datasource_service
from app.services.metadata_service import get_metadata_service
from app.services.secret_service import get_secret_service
from app.services.semantic_runtime import get_semantic_runtime_service

DEMO_DATABASE = "douyin_ecommerce_demo"
AGENT_NAME = "抖音带货电商分析助手"
DOMAIN_KEY = "douyin_ecommerce"

RANDOM_SEED = 20260621
ROW_COUNT = 10_000
BATCH_SIZE = 1_000


async def main() -> None:
    try:
        random.seed(RANDOM_SEED)
        settings = get_settings()
        await create_business_database(settings)
        await create_demo_tables(settings)
        config = await configure_management_console(settings)
        await seed_semantic_layer(config["agent_id"], config["datasource_id"])
        await print_summary(config)
    finally:
        await get_management_db().close()


async def create_business_database(settings) -> None:
    """Create the isolated demo database."""

    root_url = build_mysql_async_url(
        settings.management_mysql_user,
        settings.management_mysql_password,
        settings.management_mysql_host,
        settings.management_mysql_port,
        "mysql",
    )
    engine = create_async_engine(root_url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{DEMO_DATABASE}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    await engine.dispose()


async def create_demo_tables(settings) -> None:
    """Drop/recreate demo tables and insert deterministic demo data."""

    db_url = build_mysql_async_url(
        settings.management_mysql_user,
        settings.management_mysql_password,
        settings.management_mysql_host,
        settings.management_mysql_port,
        DEMO_DATABASE,
    )
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in reversed(TABLE_ORDER):
            await conn.execute(text(f"DROP TABLE IF EXISTS `{table}`"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        for ddl in DDL_STATEMENTS:
            await conn.execute(text(ddl))

    async with engine.begin() as conn:
        await insert_table(conn, "dim_douyin_creator", creator_rows())
        await insert_table(conn, "dim_douyin_shop", shop_rows())
        await insert_table(conn, "dim_douyin_product", product_rows())
        await insert_table(conn, "fact_live_session", live_session_rows())
        await insert_table(conn, "fact_short_video", short_video_rows())
        await insert_table(conn, "fact_douyin_order", order_rows())
        await insert_table(conn, "fact_ad_spend", ad_spend_rows())
        await insert_table(conn, "fact_after_sale", after_sale_rows())
    await engine.dispose()


async def insert_table(conn, table_name: str, rows: list[dict[str, Any]]) -> None:
    """Insert rows in batches."""

    if not rows:
        return
    columns = list(rows[0].keys())
    column_sql = ", ".join(f"`{column}`" for column in columns)
    value_sql = ", ".join(f":{column}" for column in columns)
    statement = text(f"INSERT INTO `{table_name}` ({column_sql}) VALUES ({value_sql})")
    for start in range(0, len(rows), BATCH_SIZE):
        await conn.execute(statement, rows[start : start + BATCH_SIZE])


async def configure_management_console(settings) -> dict[str, int]:
    """Create/update agent, datasource, bindings, and collected schema."""

    db = get_management_db()
    chat_model_id = await resolve_preferred_model_id("chat", preferred_names=("小米mimo", "本地qwen3:14b"))
    embedding_model_id = await resolve_preferred_model_id(
        "embedding",
        preferred_names=("豆包embedding", "百炼embedding", "qwen3-embedding:0.6b"),
    )

    agent_rows = await db.execute_query("SELECT id FROM agent WHERE name = :name", {"name": AGENT_NAME})
    if agent_rows:
        agent_id = int(agent_rows[0]["id"])
        await db.execute_query(
            "UPDATE agent SET description = :description, chat_model_config_id = :chat_model_id, "
            "embedding_model_config_id = :embedding_model_id, llm_provider = :provider, "
            "llm_model = :model WHERE id = :id",
            {
                "id": agent_id,
                "description": "面向抖音直播带货、短视频种草、商品成交、投放转化和售后表现的分析助手",
                "chat_model_id": chat_model_id,
                "embedding_model_id": embedding_model_id,
                "provider": "xiaomi",
                "model": "mimo-v2.5",
            },
        )
    else:
        agent_id = await db.execute_insert(
            "INSERT INTO agent "
            "(name, description, chat_model_config_id, embedding_model_config_id, llm_provider, llm_model) "
            "VALUES (:name, :description, :chat_model_id, :embedding_model_id, :provider, :model)",
            {
                "name": AGENT_NAME,
                "description": "面向抖音直播带货、短视频种草、商品成交、投放转化和售后表现的分析助手",
                "chat_model_id": chat_model_id,
                "embedding_model_id": embedding_model_id,
                "provider": "xiaomi",
                "model": "mimo-v2.5",
            },
        )

    ds_rows = await db.execute_query(
        "SELECT id FROM datasource WHERE database_name = :database_name AND name = :name",
        {"database_name": DEMO_DATABASE, "name": "抖音带货电商业务库"},
    )
    if ds_rows:
        datasource_id = int(ds_rows[0]["id"])
        await db.execute_query(
            "UPDATE datasource SET agent_id = :agent_id, host = :host, port = :port, "
            "username = :username, password = :password, status = 'active' WHERE id = :id",
            {
                "id": datasource_id,
                "agent_id": agent_id,
                "host": settings.management_mysql_host,
                "port": settings.management_mysql_port,
                "username": settings.management_mysql_user,
                "password": get_secret_service().encrypt(settings.management_mysql_password),
            },
        )
    else:
        datasource_id = await get_datasource_service().create(
            DatasourceCreate(
                agent_id=agent_id,
                name="抖音带货电商业务库",
                db_type="mysql",
                host=settings.management_mysql_host,
                port=settings.management_mysql_port,
                username=settings.management_mysql_user,
                password=settings.management_mysql_password,
                database_name=DEMO_DATABASE,
            )
        )

    await get_datasource_service().set_agent_datasources(agent_id, [datasource_id])
    await invalidate_datasource_db(datasource_id)
    await get_metadata_service().collect_schema(datasource_id, TABLE_ORDER)
    return {"agent_id": agent_id, "datasource_id": datasource_id}


async def resolve_preferred_model_id(model_type: str, preferred_names: tuple[str, ...]) -> int | None:
    """Return the first preferred active model config id."""

    rows = await get_management_db().execute_query(
        "SELECT id, name FROM model_config WHERE model_type = :model_type AND status = 'active' ORDER BY id ASC",
        {"model_type": model_type},
    )
    by_name = {str(row["name"]): int(row["id"]) for row in rows}
    for name in preferred_names:
        if name in by_name:
            return by_name[name]
    return int(rows[0]["id"]) if rows else None


async def seed_semantic_layer(agent_id: int, datasource_id: int) -> None:
    """Create/update the visible semantic layer for the Douyin demo."""

    svc = get_semantic_runtime_service()
    domain_id = await svc.upsert_domain(
        {
            "agent_id": agent_id,
            "datasource_id": datasource_id,
            "domain_key": DOMAIN_KEY,
            "name": "抖音带货电商",
            "description": "抖音直播带货、短视频种草、商品成交、投放转化和售后分析语义层",
            "status": "active",
        }
    )
    await clear_semantic_assets(domain_id)
    for asset_type, items in semantic_assets().items():
        for item in items:
            await svc.upsert_asset(domain_id, asset_type, item)
    await get_management_db().execute_query(
        "UPDATE agent SET semantic_domain_id = :domain_id WHERE id = :agent_id",
        {"domain_id": domain_id, "agent_id": agent_id},
    )
    validation = await svc.validate_domain_assets(domain_id)
    if validation.get("errors"):
        raise RuntimeError(f"semantic validation failed: {validation['errors']}")


async def clear_semantic_assets(domain_id: int) -> None:
    """Clear existing demo semantic assets before reseeding."""

    db = get_management_db()
    for table in (
        "logic_form_template",
        "semantic_mapping",
        "semantic_rule",
        "semantic_metric",
        "semantic_relation",
        "semantic_concept",
    ):
        await db.execute_query(f"DELETE FROM {table} WHERE domain_id = :domain_id", {"domain_id": domain_id})


async def print_summary(config: dict[str, int]) -> None:
    """Print a concise setup summary."""

    db = get_management_db()
    counts = {}
    for table in TABLE_ORDER:
        rows = await db.execute_query(
            f"SELECT COUNT(*) AS cnt FROM `{DEMO_DATABASE}`.`{table}`"
        )
        counts[table] = rows[0]["cnt"]
    domain = await db.execute_query(
        "SELECT id FROM semantic_domain WHERE agent_id = :agent_id AND domain_key = :domain_key",
        {"agent_id": config["agent_id"], "domain_key": DOMAIN_KEY},
    )
    domain_id = int(domain[0]["id"])
    asset_counts = {}
    for asset_name, table in {
        "concept": "semantic_concept",
        "relation": "semantic_relation",
        "metric": "semantic_metric",
        "rule": "semantic_rule",
        "mapping": "semantic_mapping",
        "template": "logic_form_template",
    }.items():
        rows = await db.execute_query(f"SELECT COUNT(*) AS cnt FROM {table} WHERE domain_id = :domain_id", {"domain_id": domain_id})
        asset_counts[asset_name] = rows[0]["cnt"]
    print(
        json.dumps(
            {
                "agent_id": config["agent_id"],
                "datasource_id": config["datasource_id"],
                "domain_id": domain_id,
                "database": DEMO_DATABASE,
                "row_counts": counts,
                "semantic_asset_counts": asset_counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


TABLE_ORDER = [
    "dim_douyin_creator",
    "dim_douyin_shop",
    "dim_douyin_product",
    "fact_live_session",
    "fact_short_video",
    "fact_douyin_order",
    "fact_ad_spend",
    "fact_after_sale",
]


DDL_STATEMENTS = [
    """
    CREATE TABLE dim_douyin_creator (
        creator_id BIGINT PRIMARY KEY COMMENT '达人ID',
        creator_name VARCHAR(128) NOT NULL COMMENT '达人名称',
        creator_level VARCHAR(32) NOT NULL COMMENT '达人等级',
        content_category VARCHAR(64) NOT NULL COMMENT '内容垂类',
        follower_count INT NOT NULL COMMENT '粉丝数',
        province VARCHAR(32) NOT NULL COMMENT '达人省份',
        city VARCHAR(32) NOT NULL COMMENT '达人城市',
        signed_status VARCHAR(32) NOT NULL COMMENT '签约状态',
        start_date DATE NOT NULL COMMENT '合作开始日期'
    ) COMMENT='抖音达人维表'
    """,
    """
    CREATE TABLE dim_douyin_shop (
        shop_id BIGINT PRIMARY KEY COMMENT '店铺ID',
        shop_name VARCHAR(128) NOT NULL COMMENT '店铺名称',
        shop_type VARCHAR(32) NOT NULL COMMENT '店铺类型',
        merchant_level VARCHAR(32) NOT NULL COMMENT '商家等级',
        province VARCHAR(32) NOT NULL COMMENT '店铺省份',
        city VARCHAR(32) NOT NULL COMMENT '店铺城市',
        open_date DATE NOT NULL COMMENT '开店日期'
    ) COMMENT='抖音店铺维表'
    """,
    """
    CREATE TABLE dim_douyin_product (
        product_id BIGINT PRIMARY KEY COMMENT '商品ID',
        shop_id BIGINT NOT NULL COMMENT '店铺ID',
        product_name VARCHAR(160) NOT NULL COMMENT '商品名称',
        category_lv1 VARCHAR(64) NOT NULL COMMENT '一级类目',
        category_lv2 VARCHAR(64) NOT NULL COMMENT '二级类目',
        brand_name VARCHAR(96) NOT NULL COMMENT '品牌名称',
        list_price DECIMAL(12,2) NOT NULL COMMENT '标价',
        cost_price DECIMAL(12,2) NOT NULL COMMENT '成本价',
        launch_date DATE NOT NULL COMMENT '上架日期',
        status VARCHAR(32) NOT NULL COMMENT '商品状态',
        INDEX idx_product_shop (shop_id),
        CONSTRAINT fk_product_shop FOREIGN KEY (shop_id) REFERENCES dim_douyin_shop(shop_id)
    ) COMMENT='抖音商品维表'
    """,
    """
    CREATE TABLE fact_live_session (
        session_id BIGINT PRIMARY KEY COMMENT '直播场次ID',
        creator_id BIGINT NOT NULL COMMENT '达人ID',
        shop_id BIGINT NOT NULL COMMENT '店铺ID',
        session_date DATE NOT NULL COMMENT '直播日期',
        start_hour TINYINT NOT NULL COMMENT '开播小时',
        duration_minutes INT NOT NULL COMMENT '直播时长分钟',
        traffic_source VARCHAR(64) NOT NULL COMMENT '主要流量来源',
        viewer_count INT NOT NULL COMMENT '观看人数',
        peak_online INT NOT NULL COMMENT '最高在线人数',
        like_count INT NOT NULL COMMENT '点赞数',
        comment_count INT NOT NULL COMMENT '评论数',
        new_follower_count INT NOT NULL COMMENT '新增粉丝数',
        cart_click_count INT NOT NULL COMMENT '商品点击次数',
        order_count INT NOT NULL COMMENT '直播成交订单数',
        gmv DECIMAL(14,2) NOT NULL COMMENT '直播成交GMV',
        INDEX idx_live_date (session_date),
        INDEX idx_live_creator (creator_id),
        INDEX idx_live_shop (shop_id),
        CONSTRAINT fk_live_creator FOREIGN KEY (creator_id) REFERENCES dim_douyin_creator(creator_id),
        CONSTRAINT fk_live_shop FOREIGN KEY (shop_id) REFERENCES dim_douyin_shop(shop_id)
    ) COMMENT='直播场次事实表'
    """,
    """
    CREATE TABLE fact_short_video (
        video_id BIGINT PRIMARY KEY COMMENT '短视频ID',
        creator_id BIGINT NOT NULL COMMENT '达人ID',
        product_id BIGINT NOT NULL COMMENT '挂载商品ID',
        publish_date DATE NOT NULL COMMENT '发布日期',
        content_type VARCHAR(64) NOT NULL COMMENT '内容类型',
        traffic_source VARCHAR(64) NOT NULL COMMENT '主要流量来源',
        play_count INT NOT NULL COMMENT '播放量',
        complete_play_rate DECIMAL(6,4) NOT NULL COMMENT '完播率',
        like_count INT NOT NULL COMMENT '点赞数',
        comment_count INT NOT NULL COMMENT '评论数',
        share_count INT NOT NULL COMMENT '分享数',
        product_click_count INT NOT NULL COMMENT '商品点击次数',
        order_count INT NOT NULL COMMENT '短视频成交订单数',
        gmv DECIMAL(14,2) NOT NULL COMMENT '短视频成交GMV',
        INDEX idx_video_date (publish_date),
        INDEX idx_video_creator (creator_id),
        INDEX idx_video_product (product_id),
        CONSTRAINT fk_video_creator FOREIGN KEY (creator_id) REFERENCES dim_douyin_creator(creator_id),
        CONSTRAINT fk_video_product FOREIGN KEY (product_id) REFERENCES dim_douyin_product(product_id)
    ) COMMENT='短视频种草事实表'
    """,
    """
    CREATE TABLE fact_douyin_order (
        order_id BIGINT PRIMARY KEY COMMENT '订单ID',
        order_date DATE NOT NULL COMMENT '下单日期',
        order_hour TINYINT NOT NULL COMMENT '下单小时',
        product_id BIGINT NOT NULL COMMENT '商品ID',
        shop_id BIGINT NOT NULL COMMENT '店铺ID',
        creator_id BIGINT NOT NULL COMMENT '归因达人ID',
        channel VARCHAR(32) NOT NULL COMMENT '成交渠道',
        traffic_source VARCHAR(64) NOT NULL COMMENT '流量来源',
        buyer_province VARCHAR(32) NOT NULL COMMENT '买家省份',
        buyer_city_tier VARCHAR(32) NOT NULL COMMENT '买家城市等级',
        quantity INT NOT NULL COMMENT '购买件数',
        pay_amount DECIMAL(12,2) NOT NULL COMMENT '支付金额',
        discount_amount DECIMAL(12,2) NOT NULL COMMENT '优惠金额',
        commission_amount DECIMAL(12,2) NOT NULL COMMENT '达人佣金',
        platform_fee DECIMAL(12,2) NOT NULL COMMENT '平台技术服务费',
        order_status VARCHAR(32) NOT NULL COMMENT '订单状态',
        is_new_customer TINYINT(1) NOT NULL COMMENT '是否新客',
        INDEX idx_order_date (order_date),
        INDEX idx_order_product (product_id),
        INDEX idx_order_shop (shop_id),
        INDEX idx_order_creator (creator_id),
        CONSTRAINT fk_order_product FOREIGN KEY (product_id) REFERENCES dim_douyin_product(product_id),
        CONSTRAINT fk_order_shop FOREIGN KEY (shop_id) REFERENCES dim_douyin_shop(shop_id),
        CONSTRAINT fk_order_creator FOREIGN KEY (creator_id) REFERENCES dim_douyin_creator(creator_id)
    ) COMMENT='抖音订单事实表'
    """,
    """
    CREATE TABLE fact_ad_spend (
        spend_id BIGINT PRIMARY KEY COMMENT '投放记录ID',
        spend_date DATE NOT NULL COMMENT '投放日期',
        shop_id BIGINT NOT NULL COMMENT '店铺ID',
        product_id BIGINT NOT NULL COMMENT '商品ID',
        campaign_type VARCHAR(64) NOT NULL COMMENT '投放类型',
        traffic_source VARCHAR(64) NOT NULL COMMENT '投放流量来源',
        impressions INT NOT NULL COMMENT '曝光量',
        clicks INT NOT NULL COMMENT '点击量',
        spend_amount DECIMAL(12,2) NOT NULL COMMENT '投放消耗',
        attributed_order_count INT NOT NULL COMMENT '归因订单数',
        attributed_gmv DECIMAL(14,2) NOT NULL COMMENT '归因GMV',
        INDEX idx_spend_date (spend_date),
        INDEX idx_spend_product (product_id),
        CONSTRAINT fk_spend_shop FOREIGN KEY (shop_id) REFERENCES dim_douyin_shop(shop_id),
        CONSTRAINT fk_spend_product FOREIGN KEY (product_id) REFERENCES dim_douyin_product(product_id)
    ) COMMENT='千川投放消耗事实表'
    """,
    """
    CREATE TABLE fact_after_sale (
        after_sale_id BIGINT PRIMARY KEY COMMENT '售后ID',
        order_id BIGINT NOT NULL COMMENT '订单ID',
        after_sale_date DATE NOT NULL COMMENT '售后申请日期',
        product_id BIGINT NOT NULL COMMENT '商品ID',
        shop_id BIGINT NOT NULL COMMENT '店铺ID',
        after_sale_type VARCHAR(32) NOT NULL COMMENT '售后类型',
        reason_category VARCHAR(64) NOT NULL COMMENT '售后原因分类',
        refund_amount DECIMAL(12,2) NOT NULL COMMENT '退款金额',
        status VARCHAR(32) NOT NULL COMMENT '售后状态',
        handle_hours INT NOT NULL COMMENT '处理时长小时',
        INDEX idx_after_sale_date (after_sale_date),
        INDEX idx_after_sale_order (order_id),
        CONSTRAINT fk_after_sale_order FOREIGN KEY (order_id) REFERENCES fact_douyin_order(order_id),
        CONSTRAINT fk_after_sale_product FOREIGN KEY (product_id) REFERENCES dim_douyin_product(product_id),
        CONSTRAINT fk_after_sale_shop FOREIGN KEY (shop_id) REFERENCES dim_douyin_shop(shop_id)
    ) COMMENT='售后退款事实表'
    """,
]


def creator_rows() -> list[dict[str, Any]]:
    levels = ["头部达人", "腰部达人", "成长达人", "素人达人"]
    categories = ["美妆护肤", "食品饮料", "服饰鞋包", "母婴用品", "家清个护", "数码家电", "运动户外", "珠宝配饰"]
    provinces = ["广东", "浙江", "江苏", "上海", "北京", "四川", "山东", "河南", "福建", "湖南"]
    signed = ["签约", "非签约", "机构达人"]
    return [
        {
            "creator_id": i,
            "creator_name": f"抖音达人{i:05d}",
            "creator_level": weighted_choice(levels, [0.08, 0.22, 0.45, 0.25]),
            "content_category": random.choice(categories),
            "follower_count": random.randint(5_000, 8_000_000),
            "province": random.choice(provinces),
            "city": f"{random.choice(provinces)}核心城市",
            "signed_status": random.choice(signed),
            "start_date": random_date(date(2023, 1, 1), date(2026, 5, 31)),
        }
        for i in range(1, ROW_COUNT + 1)
    ]


def shop_rows() -> list[dict[str, Any]]:
    shop_types = ["品牌旗舰店", "专营店", "产业带店铺", "达人小店", "自营店"]
    levels = ["S", "A", "B", "C"]
    provinces = ["广东", "浙江", "江苏", "上海", "北京", "四川", "山东", "河南", "福建", "湖南"]
    return [
        {
            "shop_id": i,
            "shop_name": f"抖音小店{i:05d}",
            "shop_type": weighted_choice(shop_types, [0.18, 0.24, 0.28, 0.18, 0.12]),
            "merchant_level": weighted_choice(levels, [0.08, 0.24, 0.42, 0.26]),
            "province": random.choice(provinces),
            "city": f"{random.choice(provinces)}核心城市",
            "open_date": random_date(date(2022, 1, 1), date(2026, 5, 31)),
        }
        for i in range(1, ROW_COUNT + 1)
    ]


def product_rows() -> list[dict[str, Any]]:
    categories = {
        "美妆护肤": ["面膜", "精华", "防晒", "彩妆"],
        "食品饮料": ["休闲零食", "冲调饮品", "生鲜", "地方特产"],
        "服饰鞋包": ["女装", "男装", "鞋靴", "箱包"],
        "母婴用品": ["纸尿裤", "婴童食品", "玩具", "童装"],
        "家清个护": ["洗护", "清洁", "纸品", "香氛"],
        "数码家电": ["小家电", "手机配件", "智能设备", "厨房电器"],
        "运动户外": ["健身装备", "户外服饰", "运动鞋", "骑行"],
        "珠宝配饰": ["黄金", "银饰", "腕表", "饰品"],
    }
    rows = []
    for i in range(1, ROW_COUNT + 1):
        lv1 = random.choice(list(categories.keys()))
        lv2 = random.choice(categories[lv1])
        price = Decimal(str(round(random.uniform(19, 699), 2)))
        cost = (price * Decimal(str(random.uniform(0.35, 0.72)))).quantize(Decimal("0.01"))
        rows.append(
            {
                "product_id": i,
                "shop_id": random.randint(1, ROW_COUNT),
                "product_name": f"{lv2}爆款商品{i:05d}",
                "category_lv1": lv1,
                "category_lv2": lv2,
                "brand_name": f"品牌{random.randint(1, 800):03d}",
                "list_price": price,
                "cost_price": cost,
                "launch_date": random_date(date(2023, 1, 1), date(2026, 5, 31)),
                "status": weighted_choice(["在售", "下架", "新品", "清仓"], [0.72, 0.08, 0.12, 0.08]),
            }
        )
    return rows


def live_session_rows() -> list[dict[str, Any]]:
    sources = ["自然推荐", "直播广场", "短视频引流", "千川投放", "搜索", "粉丝召回"]
    rows = []
    for i in range(1, ROW_COUNT + 1):
        viewers = random.randint(800, 180_000)
        clicks = int(viewers * random.uniform(0.03, 0.28))
        orders = int(clicks * random.uniform(0.02, 0.18))
        avg_price = Decimal(str(round(random.uniform(49, 329), 2)))
        rows.append(
            {
                "session_id": i,
                "creator_id": random.randint(1, ROW_COUNT),
                "shop_id": random.randint(1, ROW_COUNT),
                "session_date": random_date(date(2025, 1, 1), date(2026, 6, 20)),
                "start_hour": random.randint(6, 23),
                "duration_minutes": random.randint(45, 480),
                "traffic_source": random.choice(sources),
                "viewer_count": viewers,
                "peak_online": max(1, int(viewers * random.uniform(0.03, 0.18))),
                "like_count": int(viewers * random.uniform(0.08, 1.4)),
                "comment_count": int(viewers * random.uniform(0.005, 0.09)),
                "new_follower_count": int(viewers * random.uniform(0.002, 0.05)),
                "cart_click_count": clicks,
                "order_count": orders,
                "gmv": (avg_price * orders).quantize(Decimal("0.01")),
            }
        )
    return rows


def short_video_rows() -> list[dict[str, Any]]:
    content_types = ["测评种草", "剧情挂车", "直播切片", "教程攻略", "达人开箱", "品牌广告"]
    sources = ["自然推荐", "搜索", "同城", "粉丝推荐", "千川投放"]
    rows = []
    for i in range(1, ROW_COUNT + 1):
        plays = random.randint(1_000, 1_200_000)
        clicks = int(plays * random.uniform(0.005, 0.08))
        orders = int(clicks * random.uniform(0.01, 0.12))
        avg_price = Decimal(str(round(random.uniform(39, 399), 2)))
        rows.append(
            {
                "video_id": i,
                "creator_id": random.randint(1, ROW_COUNT),
                "product_id": random.randint(1, ROW_COUNT),
                "publish_date": random_date(date(2025, 1, 1), date(2026, 6, 20)),
                "content_type": random.choice(content_types),
                "traffic_source": random.choice(sources),
                "play_count": plays,
                "complete_play_rate": Decimal(str(round(random.uniform(0.08, 0.72), 4))),
                "like_count": int(plays * random.uniform(0.006, 0.11)),
                "comment_count": int(plays * random.uniform(0.0005, 0.025)),
                "share_count": int(plays * random.uniform(0.0008, 0.035)),
                "product_click_count": clicks,
                "order_count": orders,
                "gmv": (avg_price * orders).quantize(Decimal("0.01")),
            }
        )
    return rows


def order_rows() -> list[dict[str, Any]]:
    channels = ["直播间", "短视频", "商品橱窗", "搜索", "商城推荐"]
    sources = ["自然推荐", "短视频引流", "直播广场", "千川投放", "搜索", "粉丝召回"]
    provinces = ["广东", "浙江", "江苏", "上海", "北京", "四川", "山东", "河南", "福建", "湖南", "湖北", "安徽"]
    tiers = ["一线", "新一线", "二线", "三线", "四线及以下"]
    statuses = ["已支付", "已发货", "已完成", "已取消", "已退款"]
    rows = []
    for i in range(1, ROW_COUNT + 1):
        qty = weighted_choice([1, 2, 3, 4, 5], [0.62, 0.22, 0.09, 0.05, 0.02])
        unit = Decimal(str(round(random.uniform(29, 599), 2)))
        discount = (unit * qty * Decimal(str(random.uniform(0, 0.18)))).quantize(Decimal("0.01"))
        amount = (unit * qty - discount).quantize(Decimal("0.01"))
        rows.append(
            {
                "order_id": i,
                "order_date": random_date(date(2025, 1, 1), date(2026, 6, 20)),
                "order_hour": random.randint(0, 23),
                "product_id": random.randint(1, ROW_COUNT),
                "shop_id": random.randint(1, ROW_COUNT),
                "creator_id": random.randint(1, ROW_COUNT),
                "channel": weighted_choice(channels, [0.42, 0.28, 0.12, 0.08, 0.10]),
                "traffic_source": random.choice(sources),
                "buyer_province": random.choice(provinces),
                "buyer_city_tier": weighted_choice(tiers, [0.12, 0.22, 0.26, 0.24, 0.16]),
                "quantity": qty,
                "pay_amount": amount,
                "discount_amount": discount,
                "commission_amount": (amount * Decimal(str(random.uniform(0.03, 0.18)))).quantize(Decimal("0.01")),
                "platform_fee": (amount * Decimal(str(random.uniform(0.005, 0.04)))).quantize(Decimal("0.01")),
                "order_status": weighted_choice(statuses, [0.18, 0.25, 0.43, 0.05, 0.09]),
                "is_new_customer": 1 if random.random() < 0.38 else 0,
            }
        )
    return rows


def ad_spend_rows() -> list[dict[str, Any]]:
    campaign_types = ["直播间成交", "商品托管", "短视频引流", "搜索广告", "人群定向"]
    sources = ["巨量千川", "品牌广告", "DOU+", "搜索推广"]
    rows = []
    for i in range(1, ROW_COUNT + 1):
        clicks = random.randint(80, 80_000)
        impressions = int(clicks / random.uniform(0.01, 0.12))
        spend = Decimal(str(round(clicks * random.uniform(0.15, 3.5), 2)))
        orders = int(clicks * random.uniform(0.01, 0.16))
        rows.append(
            {
                "spend_id": i,
                "spend_date": random_date(date(2025, 1, 1), date(2026, 6, 20)),
                "shop_id": random.randint(1, ROW_COUNT),
                "product_id": random.randint(1, ROW_COUNT),
                "campaign_type": random.choice(campaign_types),
                "traffic_source": random.choice(sources),
                "impressions": impressions,
                "clicks": clicks,
                "spend_amount": spend,
                "attributed_order_count": orders,
                "attributed_gmv": (Decimal(str(round(random.uniform(45, 360), 2))) * orders).quantize(Decimal("0.01")),
            }
        )
    return rows


def after_sale_rows() -> list[dict[str, Any]]:
    types = ["仅退款", "退货退款", "换货", "补发"]
    reasons = ["不喜欢/效果不好", "尺码不合适", "质量问题", "物流问题", "七天无理由", "错发漏发"]
    statuses = ["处理中", "已同意", "已拒绝", "已完成"]
    rows = []
    for i in range(1, ROW_COUNT + 1):
        order_id = random.randint(1, ROW_COUNT)
        refund = Decimal(str(round(random.uniform(9, 499), 2)))
        rows.append(
            {
                "after_sale_id": i,
                "order_id": order_id,
                "after_sale_date": random_date(date(2025, 1, 2), date(2026, 6, 20)),
                "product_id": random.randint(1, ROW_COUNT),
                "shop_id": random.randint(1, ROW_COUNT),
                "after_sale_type": weighted_choice(types, [0.52, 0.34, 0.08, 0.06]),
                "reason_category": random.choice(reasons),
                "refund_amount": refund,
                "status": weighted_choice(statuses, [0.12, 0.24, 0.08, 0.56]),
                "handle_hours": random.randint(1, 168),
            }
        )
    return rows


def semantic_assets() -> dict[str, list[dict[str, Any]]]:
    common_dims = [
        "order_date",
        "month",
        "channel",
        "traffic_source",
        "category_lv1",
        "category_lv2",
        "brand_name",
        "product_name",
        "shop_name",
        "creator_name",
        "creator_level",
        "buyer_province",
        "buyer_city_tier",
    ]
    return {
        "concept": [
            concept("order", "event", "订单", "用户在抖音完成支付的成交订单", ["成交", "支付订单", "下单"]),
            concept("gmv", "measure", "GMV", "支付金额口径的成交总额", ["成交额", "销售额", "支付金额"]),
            concept("live", "event", "直播场次", "直播带货场次表现", ["直播间", "场观", "开播"]),
            concept("video", "event", "短视频", "短视频种草和挂车转化表现", ["种草视频", "挂车视频"]),
            concept("ad", "measure", "投放", "千川、DOU+ 等投放消耗与归因转化", ["千川", "广告", "投流"]),
            concept("refund", "measure", "售后退款", "退款、退货、换货等售后表现", ["售后", "退款", "退货"]),
        ],
        "mapping": mappings(),
        "metric": [
            metric("gmv", "GMV", "订单支付金额合计，剔除已取消订单", ["成交额", "销售额", "支付金额"], "SUM({base}.`pay_amount`)", "SUM", "fact_douyin_order", "fact_douyin_order.order_date", common_dims),
            metric("order_count", "订单量", "成交订单笔数，剔除已取消订单", ["订单数", "成交笔数", "销量", "下单量"], "COUNT(*)", "COUNT", "fact_douyin_order", "fact_douyin_order.order_date", common_dims),
            metric("buyer_count", "买家数", "按订单ID模拟买家去重的成交人数", ["购买人数", "成交人数"], "COUNT(DISTINCT {base}.`order_id`)", "COUNT_DISTINCT", "fact_douyin_order", "fact_douyin_order.order_date", common_dims),
            metric("new_customer_order_count", "新客订单量", "新客订单笔数", ["新客订单", "新客成交"], "SUM(CASE WHEN {base}.`is_new_customer` = 1 THEN 1 ELSE 0 END)", "SUM", "fact_douyin_order", "fact_douyin_order.order_date", common_dims),
            metric("commission_amount", "达人佣金", "订单产生的达人佣金合计", ["佣金", "达人分佣"], "SUM({base}.`commission_amount`)", "SUM", "fact_douyin_order", "fact_douyin_order.order_date", common_dims),
            metric("live_gmv", "直播GMV", "直播场次成交GMV", ["直播成交额", "直播销售额"], "SUM({base}.`gmv`)", "SUM", "fact_live_session", "fact_live_session.session_date", ["session_date", "month", "traffic_source", "creator_name", "creator_level", "shop_name"]),
            metric("live_viewer_count", "直播观看人数", "直播场次观看人数合计", ["场观", "观看人数"], "SUM({base}.`viewer_count`)", "SUM", "fact_live_session", "fact_live_session.session_date", ["session_date", "month", "traffic_source", "creator_name", "creator_level", "shop_name"]),
            metric("live_conversion_rate", "直播点击成交转化率", "直播订单数 / 商品点击次数", ["直播转化率", "点击成交率"], "SUM({base}.`order_count`) / NULLIF(SUM({base}.`cart_click_count`), 0)", "RATIO", "fact_live_session", "fact_live_session.session_date", ["session_date", "month", "traffic_source", "creator_name", "creator_level", "shop_name"]),
            metric("video_gmv", "短视频GMV", "短视频挂车成交GMV", ["短视频成交额", "种草GMV"], "SUM({base}.`gmv`)", "SUM", "fact_short_video", "fact_short_video.publish_date", ["publish_date", "month", "traffic_source", "content_type", "creator_name", "category_lv1", "product_name"]),
            metric("video_play_count", "短视频播放量", "短视频播放量合计", ["播放量", "VV"], "SUM({base}.`play_count`)", "SUM", "fact_short_video", "fact_short_video.publish_date", ["publish_date", "month", "traffic_source", "content_type", "creator_name", "category_lv1", "product_name"]),
            metric("ad_spend", "投放消耗", "广告投放花费合计", ["消耗", "广告花费", "投流费用"], "SUM({base}.`spend_amount`)", "SUM", "fact_ad_spend", "fact_ad_spend.spend_date", ["spend_date", "month", "campaign_type", "traffic_source", "category_lv1", "product_name", "shop_name"]),
            metric("ad_roi", "投放ROI", "归因GMV / 投放消耗", ["ROI", "投产比"], "SUM({base}.`attributed_gmv`) / NULLIF(SUM({base}.`spend_amount`), 0)", "RATIO", "fact_ad_spend", "fact_ad_spend.spend_date", ["spend_date", "month", "campaign_type", "traffic_source", "category_lv1", "product_name", "shop_name"]),
            metric("refund_amount", "退款金额", "售后退款金额合计", ["退款额", "售后金额"], "SUM({base}.`refund_amount`)", "SUM", "fact_after_sale", "fact_after_sale.after_sale_date", ["after_sale_date", "month", "after_sale_type", "reason_category", "category_lv1", "shop_name", "product_name"]),
            metric("refund_count", "售后单量", "售后申请数量", ["退款单量", "售后数量"], "COUNT(*)", "COUNT", "fact_after_sale", "fact_after_sale.after_sale_date", ["after_sale_date", "month", "after_sale_type", "reason_category", "category_lv1", "shop_name", "product_name"]),
        ],
        "relation": relations(),
        "rule": rules(),
        "template": templates(),
    }


def concept(key: str, concept_type: str, name: str, description: str, synonyms: list[str]) -> dict[str, Any]:
    return {
        "concept_key": key,
        "concept_type": concept_type,
        "name": name,
        "description": description,
        "synonyms": synonyms,
        "metadata": {},
    }


def metric(key: str, name: str, description: str, synonyms: list[str], formula: str, aggregation: str, base_table: str, time_field: str, dimensions: list[str]) -> dict[str, Any]:
    return {
        "metric_key": key,
        "name": name,
        "description": description,
        "synonyms": synonyms,
        "metric_type": "ratio" if aggregation == "RATIO" else "measure",
        "formula_sql": formula,
        "aggregation": aggregation,
        "base_table": base_table,
        "time_field": time_field,
        "default_filters": [{"field": "order_status", "operator": "!=", "value": "已取消"}] if base_table == "fact_douyin_order" else [],
        "dimensions": dimensions,
        "metadata": {"unit": "元" if any(token in key for token in ("gmv", "amount", "spend", "commission")) else "count"},
    }


def mappings() -> list[dict[str, Any]]:
    return [
        mapping("time", "order_date", "fact_douyin_order", "order_date", "date", "下单日期"),
        mapping("time", "session_date", "fact_live_session", "session_date", "date", "直播日期"),
        mapping("time", "publish_date", "fact_short_video", "publish_date", "date", "短视频发布日期"),
        mapping("time", "spend_date", "fact_ad_spend", "spend_date", "date", "投放日期"),
        mapping("time", "after_sale_date", "fact_after_sale", "after_sale_date", "date", "售后申请日期"),
        mapping("time", "month", "fact_douyin_order", None, "varchar", "月份", "DATE_FORMAT({base}.`order_date`, '%Y-%m')"),
        mapping("dimension", "channel", "fact_douyin_order", "channel", "varchar", "成交渠道"),
        mapping("dimension", "traffic_source", "fact_douyin_order", "traffic_source", "varchar", "流量来源"),
        mapping("dimension", "buyer_province", "fact_douyin_order", "buyer_province", "varchar", "买家省份"),
        mapping("dimension", "buyer_city_tier", "fact_douyin_order", "buyer_city_tier", "varchar", "买家城市等级"),
        mapping("dimension", "order_status", "fact_douyin_order", "order_status", "varchar", "订单状态"),
        mapping("dimension", "product_name", "dim_douyin_product", "product_name", "varchar", "商品名称"),
        mapping("dimension", "category_lv1", "dim_douyin_product", "category_lv1", "varchar", "一级类目"),
        mapping("dimension", "category_lv2", "dim_douyin_product", "category_lv2", "varchar", "二级类目"),
        mapping("dimension", "brand_name", "dim_douyin_product", "brand_name", "varchar", "品牌名称"),
        mapping("dimension", "shop_name", "dim_douyin_shop", "shop_name", "varchar", "店铺名称"),
        mapping("dimension", "shop_type", "dim_douyin_shop", "shop_type", "varchar", "店铺类型"),
        mapping("dimension", "creator_name", "dim_douyin_creator", "creator_name", "varchar", "达人名称"),
        mapping("dimension", "creator_level", "dim_douyin_creator", "creator_level", "varchar", "达人等级"),
        mapping("dimension", "content_category", "dim_douyin_creator", "content_category", "varchar", "达人内容垂类"),
        mapping("dimension", "content_type", "fact_short_video", "content_type", "varchar", "短视频内容类型"),
        mapping("dimension", "campaign_type", "fact_ad_spend", "campaign_type", "varchar", "投放类型"),
        mapping("dimension", "after_sale_type", "fact_after_sale", "after_sale_type", "varchar", "售后类型"),
        mapping("dimension", "reason_category", "fact_after_sale", "reason_category", "varchar", "售后原因"),
    ]


def mapping(asset_type: str, key: str, table: str, column: str | None, data_type: str, description: str, expression_sql: str | None = None) -> dict[str, Any]:
    return {
        "asset_type": asset_type,
        "asset_key": key,
        "table_name": table,
        "column_name": column,
        "expression_sql": expression_sql,
        "data_type": data_type,
        "role": asset_type,
        "filters": [{"description": description}],
    }


def relations() -> list[dict[str, Any]]:
    return [
        relation("order_product", "order", "product", "订单关联商品", "fact_douyin_order.product_id", "dim_douyin_product.product_id"),
        relation("order_shop", "order", "shop", "订单关联店铺", "fact_douyin_order.shop_id", "dim_douyin_shop.shop_id"),
        relation("order_creator", "order", "creator", "订单归因达人", "fact_douyin_order.creator_id", "dim_douyin_creator.creator_id"),
        relation("product_shop", "product", "shop", "商品所属店铺", "dim_douyin_product.shop_id", "dim_douyin_shop.shop_id"),
        relation("live_creator", "live", "creator", "直播场次关联达人", "fact_live_session.creator_id", "dim_douyin_creator.creator_id"),
        relation("live_shop", "live", "shop", "直播场次关联店铺", "fact_live_session.shop_id", "dim_douyin_shop.shop_id"),
        relation("video_creator", "video", "creator", "短视频关联达人", "fact_short_video.creator_id", "dim_douyin_creator.creator_id"),
        relation("video_product", "video", "product", "短视频挂载商品", "fact_short_video.product_id", "dim_douyin_product.product_id"),
        relation("ad_product", "ad", "product", "投放关联商品", "fact_ad_spend.product_id", "dim_douyin_product.product_id"),
        relation("after_sale_order", "refund", "order", "售后关联订单", "fact_after_sale.order_id", "fact_douyin_order.order_id"),
    ]


def relation(key: str, source: str, target: str, name: str, left: str, right: str) -> dict[str, Any]:
    return {
        "relation_key": key,
        "relation_type": "join_path",
        "source_concept": source,
        "target_concept": target,
        "name": name,
        "description": name,
        "join_path": [{"left": left, "right": right}],
        "conditions": [],
        "metadata": {},
    }


def rules() -> list[dict[str, Any]]:
    return [
        {
            "rule_key": "douyin_rewrite_rules",
            "rule_type": "rewrite",
            "name": "抖音电商问法改写",
            "description": "把口语化的带货、电商、投流问法补充为可查询口径",
            "expression": {
                "rewrites": [
                    {"terms": ["销售额", "成交额", "GMV"], "append": "按GMV口径统计支付金额"},
                    {"terms": ["销量", "订单量", "卖了多少单"], "append": "按订单量口径统计订单笔数"},
                    {"terms": ["投产比", "ROI"], "append": "按归因GMV除以投放消耗计算投放ROI"},
                    {"terms": ["退款", "售后"], "append": "结合售后单量、退款金额和售后原因分析"},
                    {"terms": ["达人", "主播"], "append": "可按达人名称或达人等级拆分"},
                    {"terms": ["趋势", "变化"], "append": "优先按月份或日期展示时间趋势"},
                ]
            },
            "applies_to": [],
            "severity": "info",
        },
        {
            "rule_key": "recommend_questions",
            "rule_type": "examples",
            "name": "推荐问题",
            "description": "聊天页可展示的抖音电商示例问题",
            "expression": {
                "examples": [
                    "最近三个月各个类目的GMV变化趋势是什么？",
                    "GMV排名前10的达人是谁，分别成交了多少？",
                    "不同成交渠道的订单量和GMV分别是多少？",
                    "各投放类型的消耗、归因GMV和ROI表现如何？",
                    "退款金额最高的商品类目有哪些，主要售后原因是什么？",
                    "直播间观看人数和直播GMV按达人等级对比一下",
                ]
            },
            "applies_to": [],
            "severity": "info",
        },
    ]


def templates() -> list[dict[str, Any]]:
    return [
        lf_template("gmv_trend", "trend", "GMV趋势分析", ["gmv"], ["month", "category_lv1"], ["最近三个月各类目的GMV趋势", "各个类目成交额变化趋势"]),
        lf_template("creator_rank", "ranking", "达人带货排名", ["gmv", "order_count"], ["creator_name"], ["GMV排名前10的达人", "带货最好的主播是谁"]),
        lf_template("ad_roi", "metric_query", "投放ROI分析", ["ad_spend", "ad_roi"], ["campaign_type"], ["各投放类型ROI表现", "千川投产比怎么样"]),
        lf_template("refund_reason", "ranking", "售后原因分析", ["refund_amount", "refund_count"], ["reason_category", "category_lv1"], ["退款原因排名", "哪些类目售后最多"]),
    ]


def lf_template(key: str, intent_type: str, name: str, metrics: list[str], dimensions: list[str], examples: list[str]) -> dict[str, Any]:
    return {
        "template_key": key,
        "intent_type": intent_type,
        "name": name,
        "description": name,
        "required_slots": ["metrics"],
        "optional_slots": ["dimensions", "time_range", "limit", "sort"],
        "compile_strategy": {"default_metrics": metrics, "default_dimensions": dimensions},
        "examples": examples,
    }


def weighted_choice(values, weights):
    return random.choices(values, weights=weights, k=1)[0]


def random_date(start: date, end: date) -> date:
    return start + timedelta(days=random.randint(0, (end - start).days))


if __name__ == "__main__":
    asyncio.run(main())
