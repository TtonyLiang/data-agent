"""Apply semantic-runtime management DB migrations idempotently."""

from __future__ import annotations

import asyncio

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from app.db.mysql import get_management_db


CREATE_TABLES: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS semantic_domain (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        agent_id BIGINT NOT NULL COMMENT '所属智能体',
        datasource_id BIGINT DEFAULT NULL COMMENT '默认数据源',
        domain_key VARCHAR(128) NOT NULL COMMENT '领域标识',
        name VARCHAR(256) NOT NULL COMMENT '领域名称',
        description TEXT COMMENT '领域描述',
        status VARCHAR(32) DEFAULT 'active' COMMENT '状态',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_agent_domain (agent_id, domain_key),
        INDEX idx_agent_id (agent_id),
        INDEX idx_datasource_id (datasource_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义领域'
    """,
    """
    CREATE TABLE IF NOT EXISTS semantic_concept (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL COMMENT '所属语义领域',
        concept_key VARCHAR(128) NOT NULL COMMENT '概念标识',
        concept_type VARCHAR(32) NOT NULL COMMENT 'object/event/state/dimension/action',
        name VARCHAR(256) NOT NULL COMMENT '业务名称',
        description TEXT COMMENT '业务描述',
        synonyms JSON DEFAULT NULL COMMENT '同义词',
        metadata JSON DEFAULT NULL COMMENT '扩展信息',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_domain_concept (domain_id, concept_key),
        INDEX idx_domain_type (domain_id, concept_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义概念'
    """,
    """
    CREATE TABLE IF NOT EXISTS semantic_relation (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL COMMENT '所属语义领域',
        relation_key VARCHAR(128) NOT NULL COMMENT '关系标识',
        relation_type VARCHAR(32) NOT NULL COMMENT 'relationship/event_flow/state_transition/join_path',
        source_concept VARCHAR(128) NOT NULL COMMENT '源概念',
        target_concept VARCHAR(128) NOT NULL COMMENT '目标概念',
        name VARCHAR(256) NOT NULL COMMENT '关系名称',
        description TEXT COMMENT '关系描述',
        join_path JSON DEFAULT NULL COMMENT '物理JOIN路径',
        conditions JSON DEFAULT NULL COMMENT '关系条件',
        metadata JSON DEFAULT NULL COMMENT '扩展信息',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_domain_relation (domain_id, relation_key),
        INDEX idx_domain_relation_type (domain_id, relation_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义关系'
    """,
    """
    CREATE TABLE IF NOT EXISTS semantic_metric (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL COMMENT '所属语义领域',
        metric_key VARCHAR(128) NOT NULL COMMENT '指标标识',
        name VARCHAR(256) NOT NULL COMMENT '指标名称',
        description TEXT COMMENT '指标描述',
        synonyms JSON DEFAULT NULL COMMENT '同义词',
        metric_type VARCHAR(32) DEFAULT 'measure' COMMENT 'measure/ratio/count/dimension_metric',
        formula_sql TEXT NOT NULL COMMENT '受控SQL表达式',
        aggregation VARCHAR(32) DEFAULT NULL COMMENT '默认聚合',
        base_table VARCHAR(256) NOT NULL COMMENT '事实表',
        time_field VARCHAR(256) DEFAULT NULL COMMENT '默认时间字段',
        default_filters JSON DEFAULT NULL COMMENT '默认过滤条件',
        dimensions JSON DEFAULT NULL COMMENT '可用维度',
        metadata JSON DEFAULT NULL COMMENT '扩展信息',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_domain_metric (domain_id, metric_key),
        INDEX idx_domain_metric (domain_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义指标'
    """,
    """
    CREATE TABLE IF NOT EXISTS semantic_rule (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL COMMENT '所属语义领域',
        rule_key VARCHAR(128) NOT NULL COMMENT '规则标识',
        rule_type VARCHAR(32) NOT NULL COMMENT 'filter/time/permission/action/definition',
        name VARCHAR(256) NOT NULL COMMENT '规则名称',
        description TEXT COMMENT '规则描述',
        expression JSON DEFAULT NULL COMMENT '规则表达式',
        applies_to JSON DEFAULT NULL COMMENT '适用资产',
        severity VARCHAR(32) DEFAULT 'info' COMMENT 'info/warn/block',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_domain_rule (domain_id, rule_key),
        INDEX idx_domain_rule_type (domain_id, rule_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义规则'
    """,
    """
    CREATE TABLE IF NOT EXISTS semantic_mapping (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL COMMENT '所属语义领域',
        asset_type VARCHAR(32) NOT NULL COMMENT 'concept/metric/dimension/filter',
        asset_key VARCHAR(128) NOT NULL COMMENT '语义资产标识',
        table_name VARCHAR(256) NOT NULL COMMENT '物理表名',
        column_name VARCHAR(256) DEFAULT NULL COMMENT '物理字段名',
        expression_sql TEXT DEFAULT NULL COMMENT '受控SQL表达式',
        data_type VARCHAR(64) DEFAULT NULL COMMENT '数据类型',
        role VARCHAR(32) DEFAULT 'field' COMMENT 'measure/dimension/filter/time/key',
        filters JSON DEFAULT NULL COMMENT '映射内置过滤',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_domain_mapping (domain_id, asset_type, asset_key, table_name, role),
        INDEX idx_domain_mapping (domain_id, asset_type, asset_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义物理映射'
    """,
    """
    CREATE TABLE IF NOT EXISTS logic_form_template (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL COMMENT '所属语义领域',
        template_key VARCHAR(128) NOT NULL COMMENT '模板标识',
        intent_type VARCHAR(64) NOT NULL COMMENT '意图类型',
        name VARCHAR(256) NOT NULL COMMENT '模板名称',
        description TEXT COMMENT '模板描述',
        required_slots JSON DEFAULT NULL COMMENT '必填槽位',
        optional_slots JSON DEFAULT NULL COMMENT '可选槽位',
        compile_strategy JSON DEFAULT NULL COMMENT '编译策略',
        examples JSON DEFAULT NULL COMMENT '样例问法',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_domain_template (domain_id, template_key),
        INDEX idx_domain_intent (domain_id, intent_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='LogicForm模板'
    """,
)

CHAT_HISTORY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("logic_form", "ALTER TABLE chat_history ADD COLUMN logic_form JSON DEFAULT NULL COMMENT '语义中间表达' AFTER content"),
    ("compiled_sql", "ALTER TABLE chat_history ADD COLUMN compiled_sql TEXT DEFAULT NULL COMMENT '确定性编译SQL' AFTER logic_form"),
    ("execution_trace", "ALTER TABLE chat_history ADD COLUMN execution_trace JSON DEFAULT NULL COMMENT '执行轨迹' AFTER compiled_sql"),
)


async def column_exists(table_name: str, column_name: str) -> bool:
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name AND COLUMN_NAME = :column_name",
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(rows)


async def migrate_semantic_runtime() -> dict[str, int]:
    db = get_management_db()
    for statement in CREATE_TABLES:
        await db.execute_query(statement)

    added_columns = 0
    for column_name, statement in CHAT_HISTORY_COLUMNS:
        if not await column_exists("chat_history", column_name):
            await db.execute_query(statement)
            added_columns += 1

    return {"tables": len(CREATE_TABLES), "chat_history_columns_added": added_columns}


async def async_main() -> None:
    if load_dotenv:
        load_dotenv()
    result = await migrate_semantic_runtime()
    await get_management_db().close()
    print(
        "Semantic runtime migration complete: "
        f"{result['tables']} tables ensured, "
        f"{result['chat_history_columns_added']} chat_history columns added"
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
