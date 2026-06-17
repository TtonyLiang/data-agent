from __future__ import annotations

import logging

from app.config import get_settings
from app.db.mysql import get_management_db

logger = logging.getLogger(__name__)


async def run_management_migrations() -> None:
    db = get_management_db()
    statements = [
        """
        CREATE TABLE IF NOT EXISTS model_config (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(128) NOT NULL COMMENT '配置名称',
            model_type VARCHAR(32) NOT NULL COMMENT 'chat/embedding',
            provider VARCHAR(64) DEFAULT 'ollama' COMMENT '模型提供商',
            base_url VARCHAR(512) NOT NULL COMMENT 'OpenAI兼容Base URL',
            model_name VARCHAR(128) NOT NULL COMMENT '模型名',
            api_key VARCHAR(512) DEFAULT NULL COMMENT 'API Key',
            api_key_enabled TINYINT(1) DEFAULT 0 COMMENT 'API Key是否启用',
            embedding_dimension INT DEFAULT NULL COMMENT '向量维度',
            status VARCHAR(32) DEFAULT 'active' COMMENT '状态',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_model_type (model_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模型配置'
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_datasource (
            agent_id BIGINT NOT NULL COMMENT '智能体ID',
            datasource_id BIGINT NOT NULL COMMENT '数据源ID',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (agent_id, datasource_id),
            INDEX idx_datasource_id (datasource_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体数据源关联'
        """,
        """
        CREATE TABLE IF NOT EXISTS semantic_domain_snapshot (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            domain_id BIGINT NOT NULL COMMENT '语义层ID',
            name VARCHAR(256) NOT NULL COMMENT '快照名称',
            description TEXT COMMENT '快照说明',
            snapshot_json JSON NOT NULL COMMENT '语义层快照',
            asset_counts JSON DEFAULT NULL COMMENT '资产数量',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_domain_id (domain_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义层版本快照'
        """,
    ]
    for statement in statements:
        await db.execute_query(statement)

    await add_column_if_missing(
        "agent",
        "chat_model_config_id",
        "ALTER TABLE agent ADD COLUMN chat_model_config_id BIGINT DEFAULT NULL COMMENT '大语言模型配置ID' AFTER description",
    )
    await add_column_if_missing(
        "agent",
        "embedding_model_config_id",
        "ALTER TABLE agent ADD COLUMN embedding_model_config_id BIGINT DEFAULT NULL COMMENT '向量模型配置ID' AFTER chat_model_config_id",
    )
    await add_column_if_missing(
        "agent",
        "semantic_domain_id",
        "ALTER TABLE agent ADD COLUMN semantic_domain_id BIGINT DEFAULT NULL COMMENT '默认语义领域ID' AFTER embedding_model_config_id",
    )
    await add_column_if_missing(
        "datasource",
        "status",
        "ALTER TABLE datasource ADD COLUMN status VARCHAR(32) DEFAULT 'active' COMMENT '状态'",
    )
    await add_column_if_missing(
        "chat_history",
        "reasoning_trace",
        "ALTER TABLE chat_history ADD COLUMN reasoning_trace JSON DEFAULT NULL COMMENT '流式思考与节点轨迹' AFTER content",
    )
    await add_column_if_missing(
        "chat_history",
        "plan_payload",
        "ALTER TABLE chat_history ADD COLUMN plan_payload JSON DEFAULT NULL COMMENT 'Phase3分析计划' AFTER execution_trace",
    )
    await add_column_if_missing(
        "chat_history",
        "semantic_check",
        "ALTER TABLE chat_history ADD COLUMN semantic_check JSON DEFAULT NULL COMMENT 'SQL前语义一致性校验结果' AFTER plan_payload",
    )
    await add_column_if_missing(
        "chat_history",
        "python_result",
        "ALTER TABLE chat_history ADD COLUMN python_result JSON DEFAULT NULL COMMENT 'Python分析结果' AFTER semantic_check",
    )
    await add_column_if_missing(
        "chat_history",
        "report_payload",
        "ALTER TABLE chat_history ADD COLUMN report_payload JSON DEFAULT NULL COMMENT '结构化分析报告' AFTER python_result",
    )
    await seed_default_model_configs()
    await backfill_agent_model_configs()
    await backfill_agent_semantic_domains()
    await backfill_agent_datasources()


async def add_column_if_missing(table: str, column: str, statement: str) -> None:
    db = get_management_db()
    exists = await db.execute_query(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column",
        {"table": table, "column": column},
    )
    if not exists:
        await db.execute_query(statement)


async def seed_default_model_configs() -> None:
    db = get_management_db()
    s = get_settings()
    chat_count = await db.execute_scalar(
        "SELECT COUNT(*) FROM model_config WHERE model_type = 'chat'"
    )
    if not chat_count:
        await db.execute_insert(
            "INSERT INTO model_config "
            "(name, model_type, provider, base_url, model_name, api_key, api_key_enabled, status) "
            "VALUES (:name, 'chat', :provider, :base_url, :model_name, :api_key, :enabled, 'active')",
            {
                "name": "默认大语言模型",
                "provider": s.llm_provider,
                "base_url": s.llm_base_url,
                "model_name": s.llm_model,
                "api_key": s.llm_api_key,
                "enabled": int(bool(s.llm_api_key)),
            },
        )
    embedding_count = await db.execute_scalar(
        "SELECT COUNT(*) FROM model_config WHERE model_type = 'embedding'"
    )
    if not embedding_count:
        await db.execute_insert(
            "INSERT INTO model_config "
            "(name, model_type, provider, base_url, model_name, api_key, api_key_enabled, embedding_dimension, status) "
            "VALUES (:name, 'embedding', :provider, :base_url, :model_name, :api_key, :enabled, :dimension, 'active')",
            {
                "name": "默认向量模型",
                "provider": "openai-compatible",
                "base_url": s.embedding_base_url,
                "model_name": s.embedding_model,
                "api_key": s.embedding_api_key,
                "enabled": int(bool(s.embedding_api_key)),
                "dimension": s.embedding_dimension,
            },
        )


async def backfill_agent_model_configs() -> None:
    db = get_management_db()
    await db.execute_query(
        "UPDATE agent SET chat_model_config_id = "
        "(SELECT id FROM model_config WHERE model_type = 'chat' ORDER BY id LIMIT 1) "
        "WHERE chat_model_config_id IS NULL"
    )
    await db.execute_query(
        "UPDATE agent SET embedding_model_config_id = "
        "(SELECT id FROM model_config WHERE model_type = 'embedding' ORDER BY id LIMIT 1) "
        "WHERE embedding_model_config_id IS NULL"
    )


async def backfill_agent_semantic_domains() -> None:
    db = get_management_db()
    await db.execute_query(
        "UPDATE agent a SET semantic_domain_id = "
        "(SELECT sd.id FROM semantic_domain sd WHERE sd.agent_id = a.id ORDER BY sd.id DESC LIMIT 1) "
        "WHERE a.semantic_domain_id IS NULL"
    )


async def backfill_agent_datasources() -> None:
    db = get_management_db()
    await db.execute_query(
        "INSERT IGNORE INTO agent_datasource (agent_id, datasource_id) "
        "SELECT agent_id, id FROM datasource WHERE agent_id IS NOT NULL"
    )
