"""数据库迁移 —— 管理库的 DDL 自动迁移与默认数据播种。

``run_management_migrations`` 在应用启动时(lifespan hook)自动执行:
1. 建表:CREATE TABLE IF NOT EXISTS,幂等执行。
2. 加列:ADD COLUMN IF NOT EXISTS,检查 INFORMATION_SCHEMA 后执行。
3. 改列类型:MODIFY COLUMN,检查当前类型后执行。
4. 播种默认数据:首次启动时插入默认模型配置和系统参数。
5. 回填关联:为旧数据建立 agent 模型配置、语义层、数据源的关联记录。

迁移脚本是幂等的,可安全重复执行。
"""

from __future__ import annotations

import hashlib
import json
import logging

from app.agent.prompts import default_prompt_templates
from app.config import get_settings
from app.db.mysql import get_management_db
from app.db.ontology_schema import ONTOLOGY_TABLE_STATEMENTS
from app.db.risk_schema import RISK_WORKFLOW_TABLE_STATEMENTS
from app.services.user_service import hash_password

logger = logging.getLogger(__name__)


async def run_management_migrations() -> None:
    """执行管理库迁移(启动时调用)。"""
    db = get_management_db()
    # 建表语句(幂等)
    statements = [
        *ONTOLOGY_TABLE_STATEMENTS,
        *RISK_WORKFLOW_TABLE_STATEMENTS,
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
            api_key_expires_at TIMESTAMP NULL DEFAULT NULL COMMENT 'API Key过期时间',
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
        CREATE TABLE IF NOT EXISTS enterprise_workspace (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            workspace_key VARCHAR(128) NOT NULL COMMENT '企业空间标识',
            name VARCHAR(256) NOT NULL COMMENT '企业空间名称',
            description TEXT COMMENT '企业空间说明',
            status VARCHAR(32) DEFAULT 'active' COMMENT 'active/disabled',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_enterprise_workspace_key (workspace_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='企业空间逻辑容器'
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_semantic_domain (
            agent_id BIGINT NOT NULL COMMENT '智能体ID',
            domain_id BIGINT NOT NULL COMMENT '企业业务领域ID',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (agent_id, domain_id),
            INDEX idx_agent_semantic_domain_domain (domain_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体与企业业务领域关联'
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
        """
        CREATE TABLE IF NOT EXISTS agent_table_permission (
            agent_id BIGINT NOT NULL COMMENT '智能体ID',
            datasource_id BIGINT NOT NULL COMMENT '数据源ID',
            table_name VARCHAR(256) NOT NULL COMMENT '物理表名',
            allowed TINYINT(1) DEFAULT 1 COMMENT '是否允许访问',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (agent_id, datasource_id, table_name),
            INDEX idx_agent_table_permission_ds (datasource_id, table_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体表级权限'
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_column_permission (
            agent_id BIGINT NOT NULL COMMENT '智能体ID',
            datasource_id BIGINT NOT NULL COMMENT '数据源ID',
            table_name VARCHAR(256) NOT NULL COMMENT '物理表名',
            column_name VARCHAR(256) NOT NULL COMMENT '物理字段名',
            allowed TINYINT(1) DEFAULT 1 COMMENT '是否允许访问',
            masking_policy VARCHAR(32) DEFAULT 'none' COMMENT 'none/redact/partial/hash',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (agent_id, datasource_id, table_name, column_name),
            INDEX idx_agent_column_permission_ds (datasource_id, table_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体列级权限与脱敏'
        """,
        """
        CREATE TABLE IF NOT EXISTS prompt_template (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            prompt_key VARCHAR(128) NOT NULL COMMENT '模板Key，如 nl2lf_generate.system',
            name VARCHAR(256) NOT NULL COMMENT '模板名称',
            description TEXT COMMENT '模板说明',
            agent_id BIGINT DEFAULT NULL COMMENT '适用智能体',
            model_config_id BIGINT DEFAULT NULL COMMENT '适用模型配置',
            semantic_domain_id BIGINT DEFAULT NULL COMMENT '适用语义层',
            template_text LONGTEXT NOT NULL COMMENT 'Prompt模板正文',
            status VARCHAR(32) DEFAULT 'active' COMMENT 'active/disabled',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_prompt_scope (
                prompt_key, agent_id, model_config_id, semantic_domain_id, status
            )
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Prompt模板配置'
        """,
        """
        CREATE TABLE IF NOT EXISTS user_feedback (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            agent_id BIGINT NOT NULL COMMENT '智能体ID',
            session_id VARCHAR(64) DEFAULT NULL COMMENT '会话ID',
            trace_id VARCHAR(64) DEFAULT NULL COMMENT '链路ID',
            rating VARCHAR(32) NOT NULL COMMENT 'positive/negative/neutral',
            comment TEXT COMMENT '反馈内容',
            payload JSON DEFAULT NULL COMMENT '上下文快照',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_feedback_agent_session (agent_id, session_id),
            INDEX idx_feedback_trace (trace_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户反馈'
        """,
        """
        CREATE TABLE IF NOT EXISTS system_parameter (
            param_key VARCHAR(128) PRIMARY KEY COMMENT '参数Key',
            name VARCHAR(256) NOT NULL COMMENT '参数名称',
            value_json JSON NOT NULL COMMENT '参数值',
            value_type VARCHAR(32) NOT NULL DEFAULT 'string' COMMENT 'int/float/bool/string/json',
            category VARCHAR(64) NOT NULL DEFAULT 'general' COMMENT '参数分组',
            description TEXT COMMENT '参数说明',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_system_parameter_category (category)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统参数'
        """,
        """
        CREATE TABLE IF NOT EXISTS app_user (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(64) NOT NULL COMMENT '登录用户名',
            password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希',
            display_name VARCHAR(128) DEFAULT NULL COMMENT '展示名称',
            role VARCHAR(32) NOT NULL DEFAULT 'user' COMMENT 'admin/user',
            status VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT 'active/disabled',
            must_change_password TINYINT(1) DEFAULT 0 COMMENT '是否建议修改初始密码',
            last_login_at TIMESTAMP NULL DEFAULT NULL COMMENT '最近登录时间',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_app_user_username (username),
            INDEX idx_app_user_role_status (role, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统用户'
        """,
        """
        CREATE TABLE IF NOT EXISTS user_agent_permission (
            user_id BIGINT NOT NULL COMMENT '用户ID',
            agent_id BIGINT NOT NULL COMMENT '智能体ID',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, agent_id),
            INDEX idx_user_agent_permission_agent (agent_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户智能体访问权限'
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_task_checkpoint (
            user_id BIGINT NOT NULL COMMENT '归属用户ID',
            agent_id BIGINT NOT NULL COMMENT '智能体ID',
            session_id VARCHAR(64) NOT NULL COMMENT '会话ID',
            task_id VARCHAR(64) NOT NULL COMMENT '持久任务ID',
            turn_id VARCHAR(64) NOT NULL COMMENT '当前轮次ID',
            revision BIGINT NOT NULL DEFAULT 1 COMMENT 'checkpoint修订号',
            status VARCHAR(32) NOT NULL DEFAULT 'running'
                COMMENT 'running/awaiting_input/completed/failed',
            turn_mode VARCHAR(32) NOT NULL DEFAULT 'new_task'
                COMMENT 'new_task/continue/refine/retry/analyze/respond',
            current_action VARCHAR(64) DEFAULT NULL COMMENT '最近执行动作',
            checkpoint_json LONGTEXT NOT NULL COMMENT '完整任务状态JSON',
            error_message TEXT DEFAULT NULL COMMENT '最近失败信息',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, agent_id, session_id),
            INDEX idx_task_checkpoint_task (task_id),
            INDEX idx_task_checkpoint_status (status, updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent持久任务checkpoint'
        """,
    ]
    for statement in statements:
        await db.execute_query(statement)

    # 加列(幂等:先检查 INFORMATION_SCHEMA)
    await add_column_if_missing(
        "agent",
        "chat_model_config_id",
        "ALTER TABLE agent ADD COLUMN chat_model_config_id BIGINT DEFAULT NULL "
        "COMMENT '大语言模型配置ID' AFTER description",
    )
    await add_column_if_missing(
        "agent",
        "embedding_model_config_id",
        "ALTER TABLE agent ADD COLUMN embedding_model_config_id BIGINT DEFAULT NULL "
        "COMMENT '向量模型配置ID' AFTER chat_model_config_id",
    )
    await add_column_if_missing(
        "agent",
        "semantic_domain_id",
        "ALTER TABLE agent ADD COLUMN semantic_domain_id BIGINT DEFAULT NULL "
        "COMMENT '默认语义领域ID' AFTER embedding_model_config_id",
    )
    await add_column_if_missing(
        "agent",
        "default_questions",
        "ALTER TABLE agent ADD COLUMN default_questions JSON DEFAULT NULL "
        "COMMENT '对话页默认推荐问题' AFTER semantic_domain_id",
    )
    await add_column_if_missing(
        "semantic_domain",
        "workspace_id",
        "ALTER TABLE semantic_domain ADD COLUMN workspace_id BIGINT DEFAULT NULL "
        "COMMENT '所属企业空间' AFTER id",
    )
    await ensure_column_nullable(
        "semantic_domain",
        "agent_id",
        "ALTER TABLE semantic_domain MODIFY COLUMN agent_id BIGINT DEFAULT NULL "
        "COMMENT '兼容字段: 原创建/归属智能体'",
    )
    await add_column_if_missing(
        "datasource",
        "status",
        "ALTER TABLE datasource ADD COLUMN status VARCHAR(32) DEFAULT 'active' COMMENT '状态'",
    )
    await add_column_if_missing(
        "model_config",
        "api_key_expires_at",
        "ALTER TABLE model_config ADD COLUMN api_key_expires_at TIMESTAMP NULL "
        "DEFAULT NULL COMMENT 'API Key过期时间' AFTER api_key_enabled",
    )
    await add_column_if_missing(
        "chat_history",
        "reasoning_trace",
        "ALTER TABLE chat_history ADD COLUMN reasoning_trace JSON DEFAULT NULL "
        "COMMENT '流式思考与节点轨迹' AFTER content",
    )
    await add_column_if_missing(
        "chat_history",
        "user_id",
        "ALTER TABLE chat_history ADD COLUMN user_id BIGINT DEFAULT NULL "
        "COMMENT '归属用户ID' AFTER agent_id",
    )
    await add_column_if_missing(
        "user_feedback",
        "user_id",
        "ALTER TABLE user_feedback ADD COLUMN user_id BIGINT DEFAULT NULL "
        "COMMENT '归属用户ID' AFTER id",
    )
    await create_index_if_missing(
        "chat_history",
        "idx_chat_user_agent_session",
        "ALTER TABLE chat_history ADD INDEX idx_chat_user_agent_session "
        "(user_id, agent_id, session_id)",
    )
    await create_index_if_missing(
        "user_feedback",
        "idx_feedback_user_agent_session",
        "ALTER TABLE user_feedback ADD INDEX idx_feedback_user_agent_session "
        "(user_id, agent_id, session_id)",
    )
    await add_column_if_missing(
        "chat_history",
        "plan_payload",
        "ALTER TABLE chat_history ADD COLUMN plan_payload JSON DEFAULT NULL "
        "COMMENT 'Phase3分析计划' AFTER execution_trace",
    )
    await add_column_if_missing(
        "chat_history",
        "semantic_check",
        "ALTER TABLE chat_history ADD COLUMN semantic_check JSON DEFAULT NULL "
        "COMMENT 'SQL前语义一致性校验结果' AFTER plan_payload",
    )
    await add_column_if_missing(
        "chat_history",
        "python_result",
        "ALTER TABLE chat_history ADD COLUMN python_result JSON DEFAULT NULL "
        "COMMENT 'Python分析结果' AFTER semantic_check",
    )
    await add_column_if_missing(
        "chat_history",
        "report_payload",
        "ALTER TABLE chat_history ADD COLUMN report_payload JSON DEFAULT NULL "
        "COMMENT '结构化分析报告' AFTER python_result",
    )
    await add_column_if_missing(
        "chat_history",
        "task_id",
        "ALTER TABLE chat_history ADD COLUMN task_id VARCHAR(64) DEFAULT NULL "
        "COMMENT '持久任务ID' AFTER report_payload",
    )
    await add_column_if_missing(
        "chat_history",
        "turn_id",
        "ALTER TABLE chat_history ADD COLUMN turn_id VARCHAR(64) DEFAULT NULL "
        "COMMENT '任务轮次ID' AFTER task_id",
    )
    await add_column_if_missing(
        "chat_history",
        "turn_mode",
        "ALTER TABLE chat_history ADD COLUMN turn_mode VARCHAR(32) DEFAULT NULL "
        "COMMENT '任务轮次模式' AFTER turn_id",
    )
    await add_column_if_missing(
        "chat_history",
        "task_status",
        "ALTER TABLE chat_history ADD COLUMN task_status VARCHAR(32) DEFAULT NULL "
        "COMMENT '任务状态' AFTER turn_mode",
    )
    await add_column_if_missing(
        "chat_history",
        "task_metadata",
        "ALTER TABLE chat_history ADD COLUMN task_metadata JSON DEFAULT NULL "
        "COMMENT '任务复用与失效摘要' AFTER task_status",
    )
    await add_column_if_missing(
        "ontology_object_type",
        "sync_enabled",
        "ALTER TABLE ontology_object_type ADD COLUMN sync_enabled TINYINT(1) DEFAULT 0 "
        "COMMENT '是否启用业务库同步' AFTER display_property",
    )
    await add_column_if_missing(
        "ontology_object_type",
        "source_query",
        "ALTER TABLE ontology_object_type ADD COLUMN source_query LONGTEXT DEFAULT NULL "
        "COMMENT '对象实例只读同步SQL' AFTER sync_enabled",
    )
    await add_column_if_missing(
        "ontology_object_type",
        "sync_limit",
        "ALTER TABLE ontology_object_type ADD COLUMN sync_limit INT DEFAULT 200 "
        "COMMENT '单次分页同步行数' AFTER source_query",
    )
    await add_column_if_missing(
        "ontology_object_type",
        "last_sync_status",
        "ALTER TABLE ontology_object_type ADD COLUMN last_sync_status VARCHAR(32) DEFAULT NULL "
        "COMMENT '最近同步状态' AFTER sync_limit",
    )
    await add_column_if_missing(
        "ontology_object_type",
        "last_sync_count",
        "ALTER TABLE ontology_object_type ADD COLUMN last_sync_count INT DEFAULT 0 "
        "COMMENT '最近同步读取行数' AFTER last_sync_status",
    )
    await add_column_if_missing(
        "ontology_object_type",
        "last_sync_total",
        "ALTER TABLE ontology_object_type ADD COLUMN last_sync_total INT DEFAULT 0 "
        "COMMENT '业务库对象总数' AFTER last_sync_count",
    )
    await add_column_if_missing(
        "ontology_object_type",
        "last_sync_error",
        "ALTER TABLE ontology_object_type ADD COLUMN last_sync_error TEXT DEFAULT NULL "
        "COMMENT '最近同步错误' AFTER last_sync_total",
    )
    await add_column_if_missing(
        "ontology_object_type",
        "last_synced_at",
        "ALTER TABLE ontology_object_type ADD COLUMN last_synced_at TIMESTAMP NULL DEFAULT NULL "
        "COMMENT '最近同步时间' AFTER last_sync_error",
    )
    await add_column_if_missing(
        "ontology_object",
        "source_kind",
        "ALTER TABLE ontology_object ADD COLUMN source_kind VARCHAR(32) DEFAULT 'manual' "
        "COMMENT 'manual/bundle/database' AFTER status",
    )
    await add_column_if_missing(
        "ontology_object",
        "source_datasource_id",
        "ALTER TABLE ontology_object ADD COLUMN source_datasource_id BIGINT DEFAULT NULL "
        "COMMENT '来源数据源ID' AFTER source_kind",
    )
    await add_column_if_missing(
        "ontology_object",
        "source_properties",
        "ALTER TABLE ontology_object ADD COLUMN source_properties JSON DEFAULT NULL "
        "COMMENT '业务库同步属性快照' AFTER source_datasource_id",
    )
    await add_column_if_missing(
        "ontology_object",
        "overlay_properties",
        "ALTER TABLE ontology_object ADD COLUMN overlay_properties JSON DEFAULT NULL "
        "COMMENT '本体动作本地覆盖属性' AFTER source_properties",
    )
    await add_column_if_missing(
        "ontology_object",
        "last_synced_at",
        "ALTER TABLE ontology_object ADD COLUMN last_synced_at TIMESTAMP NULL DEFAULT NULL "
        "COMMENT '最近业务库同步时间' AFTER overlay_properties",
    )
    await add_column_if_missing(
        "ontology_release",
        "definition_hash",
        "ALTER TABLE ontology_release ADD COLUMN definition_hash CHAR(64) DEFAULT NULL "
        "COMMENT '不可变发布定义SHA-256' AFTER definition_json",
    )
    await add_column_if_missing(
        "ontology_action_run",
        "ontology_release_id",
        "ALTER TABLE ontology_action_run ADD COLUMN ontology_release_id BIGINT DEFAULT NULL "
        "COMMENT '动作执行绑定的Ontology发布版本' AFTER domain_id",
    )
    await create_index_if_missing(
        "ontology_action_run",
        "idx_ontology_run_release",
        "ALTER TABLE ontology_action_run ADD INDEX idx_ontology_run_release "
        "(ontology_release_id, created_at)",
    )
    await backfill_ontology_release_hashes()
    await backfill_decision_audit_heads()
    # 改列类型:sql_result 从 VARCHAR 升级为 LONGTEXT(支持大结果集)
    await ensure_column_type(
        "chat_history",
        "sql_result",
        expected_type="longtext",
        statement=(
            "ALTER TABLE chat_history MODIFY COLUMN sql_result LONGTEXT DEFAULT NULL "
            "COMMENT 'SQL执行结果(JSON)'"
        ),
    )

    # 播种默认数据(首次启动时)
    await seed_default_model_configs()
    await seed_default_system_parameters()
    await seed_default_prompt_templates()
    await seed_default_admin_user()
    await seed_default_workspace()

    # 回填关联(旧数据兼容)
    await backfill_agent_model_configs()
    await backfill_semantic_domain_workspaces()
    await backfill_agent_domain_bindings()
    await cleanup_orphan_agent_domain_bindings()
    await backfill_agent_semantic_domains()
    await ensure_column_not_nullable(
        "semantic_domain",
        "workspace_id",
        "ALTER TABLE semantic_domain MODIFY COLUMN workspace_id BIGINT NOT NULL "
        "COMMENT '所属企业空间'",
    )
    await ensure_workspace_domain_unique_index()
    await backfill_agent_default_questions()
    await backfill_agent_datasources()


async def add_column_if_missing(table: str, column: str, statement: str) -> None:
    """幂等加列:先查 INFORMATION_SCHEMA,不存在时才执行 ALTER。"""
    db = get_management_db()
    exists = await db.execute_query(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column",
        {"table": table, "column": column},
    )
    if not exists:
        await db.execute_query(statement)


async def ensure_column_type(table: str, column: str, expected_type: str, statement: str) -> None:
    """幂等改列类型:先查当前类型,不匹配时才执行 ALTER。"""
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column",
        {"table": table, "column": column},
    )
    if not rows:
        return
    current = str(rows[0].get("DATA_TYPE") or rows[0].get("data_type") or "").lower()
    if current != expected_type.lower():
        await db.execute_query(statement)


async def ensure_column_nullable(table: str, column: str, statement: str) -> None:
    """幂等放宽 NOT NULL 列，供旧归属字段平滑退出强依赖。"""
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column",
        {"table": table, "column": column},
    )
    if not rows:
        return
    nullable = str(rows[0].get("IS_NULLABLE") or rows[0].get("is_nullable") or "").upper()
    if nullable != "YES":
        await db.execute_query(statement)


async def ensure_column_not_nullable(table: str, column: str, statement: str) -> None:
    """幂等收紧已完成回填的关键归属列。"""
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column",
        {"table": table, "column": column},
    )
    if not rows:
        return
    nullable = str(rows[0].get("IS_NULLABLE") or rows[0].get("is_nullable") or "").upper()
    if nullable == "YES":
        await db.execute_query(statement)


async def create_index_if_missing(table: str, index_name: str, statement: str) -> None:
    """幂等建索引:先查 INFORMATION_SCHEMA,不存在时才执行。"""
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :index_name",
        {"table": table, "index_name": index_name},
    )
    if not rows:
        await db.execute_query(statement)


async def drop_index_if_exists(table: str, index_name: str, statement: str) -> None:
    """幂等删除旧索引。"""
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :index_name",
        {"table": table, "index_name": index_name},
    )
    if rows:
        await db.execute_query(statement)


async def backfill_ontology_release_hashes() -> None:
    """Populate deterministic hashes for releases created before hash lineage existed."""
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT id, definition_json FROM ontology_release "
        "WHERE definition_hash IS NULL OR definition_hash = ''"
    )
    for row in rows:
        definition = row.get("definition_json")
        if isinstance(definition, str):
            try:
                definition = json.loads(definition)
            except json.JSONDecodeError:
                definition = definition
        canonical = json.dumps(
            definition,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        definition_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        await db.execute_query(
            "UPDATE ontology_release SET definition_hash = :definition_hash WHERE id = :id",
            {"id": row["id"], "definition_hash": definition_hash},
        )


async def backfill_decision_audit_heads() -> None:
    """Create chain-head anchors for audit domains written before the head table existed."""
    db = get_management_db()
    domains = await db.execute_query(
        "SELECT DISTINCT domain_id FROM decision_audit_event ORDER BY domain_id"
    )
    for row in domains:
        domain_id = int(row["domain_id"])
        count_rows = await db.execute_query(
            "SELECT COUNT(*) AS count FROM decision_audit_event WHERE domain_id = :domain_id",
            {"domain_id": domain_id},
        )
        head_rows = await db.execute_query(
            "SELECT event_hash FROM decision_audit_event WHERE domain_id = :domain_id "
            "ORDER BY sequence_no DESC LIMIT 1",
            {"domain_id": domain_id},
        )
        if not head_rows:
            continue
        await db.execute_query(
            "INSERT IGNORE INTO decision_audit_head (domain_id, event_count, head_hash) "
            "VALUES (:domain_id, :event_count, :head_hash)",
            {
                "domain_id": domain_id,
                "event_count": int(count_rows[0].get("count") or 0) if count_rows else 0,
                "head_hash": head_rows[0]["event_hash"],
            },
        )


async def seed_default_admin_user() -> None:
    """没有管理员时播种默认管理员账号。密码只以 bcrypt 哈希入库。

    管理员用户名和初始密码不得写死在代码中。部署时通过
    INITIAL_ADMIN_USERNAME + (INITIAL_ADMIN_PASSWORD 或 INITIAL_ADMIN_PASSWORD_HASH)
    显式提供；已有管理员时不读取这些配置。
    """
    db = get_management_db()
    count = await db.execute_scalar("SELECT COUNT(*) FROM app_user WHERE role = 'admin'")
    if count:
        logger.info("default admin seed skipped existing_admin=true")
        return
    settings = get_settings()
    username = (settings.initial_admin_username or "").strip()
    if not username:
        logger.warning("default admin seed skipped reason=missing_initial_admin_username")
        return
    password_hash = (settings.initial_admin_password_hash or "").strip()
    if not password_hash:
        initial_password = (settings.initial_admin_password or "").strip()
        if not initial_password:
            logger.warning(
                "default admin seed skipped reason=missing_initial_admin_password "
                "username=%s",
                username,
            )
            return
        password_hash = hash_password(initial_password)
    await db.execute_insert(
        "INSERT INTO app_user "
        "(username, password_hash, display_name, role, status, must_change_password) "
        "VALUES (:username, :password_hash, :display_name, 'admin', 'active', 1)",
        {
            "username": username,
            "password_hash": password_hash,
            "display_name": "默认管理员",
        },
    )
    logger.info("default admin user initialized username=%s", username)


async def seed_default_model_configs() -> None:
    """首次启动时播种默认模型配置(从环境变量读取)。"""
    db = get_management_db()
    s = get_settings()
    # 大语言模型
    chat_count = await db.execute_scalar(
        "SELECT COUNT(*) FROM model_config WHERE model_type = 'chat'"
    )
    if not chat_count:
        await db.execute_insert(
            "INSERT INTO model_config "
            "(name, model_type, provider, base_url, model_name, api_key, "
            "api_key_enabled, status) "
            "VALUES (:name, 'chat', :provider, :base_url, :model_name, :api_key, "
            ":enabled, 'active')",
            {
                "name": "默认大语言模型",
                "provider": s.llm_provider,
                "base_url": s.llm_base_url,
                "model_name": s.llm_model,
                "api_key": s.llm_api_key,
                "enabled": int(bool(s.llm_api_key)),
            },
        )
    # 向量模型
    embedding_count = await db.execute_scalar(
        "SELECT COUNT(*) FROM model_config WHERE model_type = 'embedding'"
    )
    if not embedding_count:
        await db.execute_insert(
            "INSERT INTO model_config "
            "(name, model_type, provider, base_url, model_name, api_key, "
            "api_key_enabled, embedding_dimension, status) "
            "VALUES (:name, 'embedding', :provider, :base_url, :model_name, "
            ":api_key, :enabled, :dimension, 'active')",
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


async def seed_default_workspace() -> None:
    """Ensure the single default enterprise-space container exists."""
    await get_management_db().execute_query(
        "INSERT IGNORE INTO enterprise_workspace "
        "(workspace_key, name, description, status) "
        "VALUES ('default', '默认企业空间', '企业业务领域与本体资产的默认逻辑空间', 'active')"
    )


async def seed_default_system_parameters() -> None:
    """首次启动时播种默认系统参数(数据定位阈值)。"""
    db = get_management_db()
    settings = get_settings()
    params = [
        {
            "key": "schema_recall.max_tables",
            "name": "数据定位最多候选表数",
            "value": settings.schema_recall_max_tables,
            "value_type": "int",
            "category": "schema_recall",
            "description": (
                "数据定位阶段最多保留多少张候选表。"
                "值越大上下文越全，但会增加大模型噪音。"
            ),
        },
        {
            "key": "schema_recall.required_score_ratio",
            "name": "必须召回相对分阈值",
            "value": settings.schema_recall_required_score_ratio,
            "value_type": "float",
            "category": "schema_recall",
            "description": "候选表分数达到最高分的该比例时，视为强相关表，优先召回。",
        },
        {
            "key": "schema_recall.optional_score_ratio",
            "name": "可召回相对分阈值",
            "value": settings.schema_recall_optional_score_ratio,
            "value_type": "float",
            "category": "schema_recall",
            "description": (
                "候选表分数低于该比例时剔除；介于可召回和必须召回之间时，"
                "只在表数不足时补充。"
            ),
        },
    ]
    statements = [
        (
            "INSERT IGNORE INTO system_parameter "
            "(param_key, name, value_json, value_type, category, description) "
            "VALUES (:key, :name, :value_json, :value_type, :category, :description)",
            {
                **item,
                "value_json": json.dumps(item["value"], ensure_ascii=False),
            },
        )
        for item in params
    ]
    await db.execute_transaction(statements)


async def seed_default_prompt_templates() -> None:
    """Seed editable global prompt templates from app/agent/prompts/*.md."""
    db = get_management_db()
    statements = []
    for item in default_prompt_templates():
        exists = await db.execute_scalar(
            "SELECT COUNT(*) FROM prompt_template "
            "WHERE prompt_key = :prompt_key "
            "AND agent_id IS NULL AND model_config_id IS NULL AND semantic_domain_id IS NULL",
            {"prompt_key": item["prompt_key"]},
        )
        if exists:
            continue
        statements.append(
            (
                "INSERT INTO prompt_template "
                "(prompt_key, name, description, agent_id, model_config_id, "
                "semantic_domain_id, template_text, status) "
                "VALUES (:prompt_key, :name, :description, NULL, NULL, NULL, "
                ":template_text, 'active')",
                {
                    "prompt_key": item["prompt_key"],
                    "name": item["name"],
                    "description": (
                        f"{item['description']} "
                        f"默认来源：app/agent/prompts/{item['filename']}"
                    ),
                    "template_text": item["template_text"],
                },
            )
        )
    if statements:
        await db.execute_transaction(statements)
        logger.info("seeded default prompt templates count=%s", len(statements))


async def backfill_agent_model_configs() -> None:
    """回填:为旧数据中没有 chat_model_config_id / embedding_model_config_id 的 agent 建立关联。"""
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
    """回填:为没有默认领域的 Agent 从其消费绑定中选择一个。"""
    db = get_management_db()
    await db.execute_query(
        "UPDATE agent a SET semantic_domain_id = "
        "(SELECT asd.domain_id FROM agent_semantic_domain asd WHERE asd.agent_id = a.id "
        "ORDER BY asd.domain_id DESC LIMIT 1) "
        "WHERE a.semantic_domain_id IS NULL"
    )


async def backfill_semantic_domain_workspaces() -> None:
    """回填:把历史领域归入默认企业空间，不改变其领域 ID。"""
    db = get_management_db()
    await db.execute_query(
        "UPDATE semantic_domain SET workspace_id = "
        "(SELECT id FROM enterprise_workspace WHERE workspace_key = 'default' LIMIT 1) "
        "WHERE workspace_id IS NULL"
    )


async def backfill_agent_domain_bindings() -> None:
    """回填:把历史归属字段和默认领域指针转换为多对多消费关系。"""
    db = get_management_db()
    await db.execute_query(
        "INSERT IGNORE INTO agent_semantic_domain (agent_id, domain_id) "
        "SELECT agent_id, id FROM semantic_domain WHERE agent_id IS NOT NULL"
    )
    await db.execute_query(
        "INSERT IGNORE INTO agent_semantic_domain (agent_id, domain_id) "
        "SELECT id, semantic_domain_id FROM agent WHERE semantic_domain_id IS NOT NULL"
    )


async def cleanup_orphan_agent_domain_bindings() -> None:
    """Remove stale consumer links whose Agent or enterprise domain no longer exists."""
    await get_management_db().execute_query(
        "DELETE asd FROM agent_semantic_domain asd "
        "LEFT JOIN agent a ON a.id = asd.agent_id "
        "LEFT JOIN semantic_domain sd ON sd.id = asd.domain_id "
        "WHERE a.id IS NULL OR sd.id IS NULL"
    )


async def ensure_workspace_domain_unique_index() -> None:
    """Enforce one stable domain key per enterprise space after legacy backfill."""
    db = get_management_db()
    duplicates = await db.execute_query(
        "SELECT workspace_id, domain_key, COUNT(*) AS duplicate_count "
        "FROM semantic_domain WHERE workspace_id IS NOT NULL "
        "GROUP BY workspace_id, domain_key HAVING COUNT(*) > 1 LIMIT 1"
    )
    if duplicates:
        duplicate = duplicates[0]
        raise RuntimeError(
            "企业空间内存在重复领域标识，无法建立唯一约束: "
            f"workspace_id={duplicate.get('workspace_id')}, "
            f"domain_key={duplicate.get('domain_key')}"
        )
    await create_index_if_missing(
        "semantic_domain",
        "uk_workspace_domain",
        "ALTER TABLE semantic_domain ADD UNIQUE INDEX uk_workspace_domain "
        "(workspace_id, domain_key)",
    )
    await drop_index_if_exists(
        "semantic_domain",
        "uk_agent_domain",
        "ALTER TABLE semantic_domain DROP INDEX uk_agent_domain",
    )


async def backfill_agent_default_questions() -> None:
    """回填:把旧语义层示例问法迁入 agent.default_questions,避免页面配置空白。"""
    db = get_management_db()
    agents = await db.execute_query(
        "SELECT id, semantic_domain_id, default_questions FROM agent "
        "WHERE semantic_domain_id IS NOT NULL"
    )
    for agent in agents:
        if _json_list(agent.get("default_questions")):
            continue
        domain_id = agent.get("semantic_domain_id")
        questions = await _load_domain_example_questions(domain_id)
        if not questions:
            continue
        await db.execute_query(
            "UPDATE agent SET default_questions = :default_questions WHERE id = :id",
            {
                "id": agent["id"],
                "default_questions": json.dumps(questions[:4], ensure_ascii=False),
            },
        )


async def _load_domain_example_questions(domain_id) -> list[str]:
    db = get_management_db()
    examples: list[str] = []
    templates = await db.execute_query(
        "SELECT examples FROM logic_form_template WHERE domain_id = :domain_id ORDER BY id",
        {"domain_id": domain_id},
    )
    for row in templates:
        examples.extend(str(item) for item in _json_list(row.get("examples")))
    rules = await db.execute_query(
        "SELECT expression FROM semantic_rule WHERE domain_id = :domain_id ORDER BY id",
        {"domain_id": domain_id},
    )
    for row in rules:
        expression = _json_object(row.get("expression"))
        rewrites = expression.get("rewrites")
        if not isinstance(rewrites, list):
            continue
        for item in rewrites:
            if not isinstance(item, dict):
                continue
            template = str(item.get("template") or "").strip()
            if template and "{" not in template:
                examples.append(template)
    return _unique_questions(examples)


def _json_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _unique_questions(values: list[str]) -> list[str]:
    seen: set[str] = set()
    questions: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        questions.append(text)
        seen.add(text)
    return questions


async def backfill_agent_datasources() -> None:
    """回填:为旧数据中 datasource.agent_id 有值但 agent_datasource 无记录的建立关联。"""
    db = get_management_db()
    await db.execute_query(
        "INSERT IGNORE INTO agent_datasource (agent_id, datasource_id) "
        "SELECT agent_id, id FROM datasource WHERE agent_id IS NOT NULL"
    )
