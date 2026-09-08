"""Idempotent DDL for external capability clients, grants, and invocation audit."""

CAPABILITY_ACCESS_TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS capability_client (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        client_key VARCHAR(64) NOT NULL COMMENT '外部调用方公开标识',
        name VARCHAR(256) NOT NULL COMMENT '调用方名称',
        description TEXT COMMENT '调用方说明',
        secret_hash VARCHAR(128) NOT NULL COMMENT '调用密钥SHA-256摘要',
        status VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT 'active/disabled',
        created_by BIGINT DEFAULT NULL COMMENT '创建管理员ID',
        last_used_at TIMESTAMP NULL DEFAULT NULL COMMENT '最近认证成功时间',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_capability_client_key (client_key),
        INDEX idx_capability_client_status (status, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='第三方能力调用方'
    """,
    """
    CREATE TABLE IF NOT EXISTS capability_grant (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        client_id BIGINT NOT NULL COMMENT '能力调用方ID',
        domain_id BIGINT NOT NULL COMMENT '授权业务领域ID',
        capability_key VARCHAR(128) NOT NULL COMMENT '授权能力标识',
        execution_agent_id BIGINT DEFAULT NULL COMMENT '旧领域兼容的内部数据权限适配ID',
        model_release_id BIGINT DEFAULT NULL COMMENT '授权冻结的统一企业模型版本ID',
        contract_hash CHAR(64) DEFAULT NULL COMMENT '授权能力合同SHA-256',
        contract_json JSON DEFAULT NULL COMMENT '授权时冻结的Query Capability合同',
        status VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT 'active/revoked',
        created_by BIGINT DEFAULT NULL COMMENT '创建管理员ID',
        updated_by BIGINT DEFAULT NULL COMMENT '最近修改管理员ID',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_capability_grant (
            client_id, domain_id, capability_key
        ),
        INDEX idx_capability_grant_lookup (
            client_id, domain_id, capability_key, status
        ),
        INDEX idx_capability_grant_execution_agent (execution_agent_id),
        INDEX idx_capability_grant_release (model_release_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='第三方调用方能力授权'
    """,
    """
    CREATE TABLE IF NOT EXISTS capability_invocation_audit (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        trace_id VARCHAR(64) NOT NULL COMMENT '能力调用链路ID',
        client_id BIGINT NOT NULL COMMENT '能力调用方ID',
        grant_id BIGINT DEFAULT NULL COMMENT '命中的授权ID',
        domain_id BIGINT NOT NULL COMMENT '业务领域ID',
        capability_key VARCHAR(128) NOT NULL COMMENT '能力标识',
        execution_agent_id BIGINT DEFAULT NULL COMMENT '内部数据权限执行适配ID',
        model_release_id BIGINT DEFAULT NULL COMMENT '实际使用的统一企业模型版本ID',
        semantic_snapshot_id BIGINT DEFAULT NULL COMMENT '实际使用的语义快照ID',
        ontology_release_id BIGINT DEFAULT NULL COMMENT '实际使用的Ontology版本ID',
        status VARCHAR(32) NOT NULL COMMENT '调用结果状态',
        latency_ms DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT '端到端耗时毫秒',
        row_count INT NOT NULL DEFAULT 0 COMMENT '返回结果行数',
        error_category VARCHAR(64) DEFAULT NULL COMMENT '错误分类',
        error_message TEXT DEFAULT NULL COMMENT '截断后的错误摘要',
        request_summary JSON DEFAULT NULL COMMENT '不含过滤值的请求摘要',
        result_summary JSON DEFAULT NULL COMMENT '不含结果全文的执行摘要',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_capability_invocation_trace (trace_id),
        INDEX idx_capability_invocation_client (client_id, created_at),
        INDEX idx_capability_invocation_domain (domain_id, capability_key, created_at),
        INDEX idx_capability_invocation_release (model_release_id, created_at),
        INDEX idx_capability_invocation_status (status, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='能力调用审计摘要'
    """,
]
