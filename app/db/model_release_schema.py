"""Idempotent DDL for unified enterprise model releases."""

MODEL_RELEASE_TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS enterprise_model_release (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL COMMENT '所属业务领域',
        version INT NOT NULL COMMENT '领域内递增版本',
        name VARCHAR(256) NOT NULL COMMENT '发布名称',
        description TEXT COMMENT '发布说明',
        semantic_snapshot_id BIGINT NOT NULL COMMENT '语义资产快照ID',
        ontology_release_id BIGINT NOT NULL COMMENT 'Ontology发布版本ID',
        status VARCHAR(32) NOT NULL DEFAULT 'draft'
            COMMENT 'draft/validated/active/retired',
        semantic_snapshot_hash CHAR(64) NOT NULL COMMENT '语义资产快照SHA-256',
        ontology_definition_hash CHAR(64) NOT NULL COMMENT 'Ontology定义SHA-256',
        model_hash CHAR(64) NOT NULL COMMENT '统一企业模型SHA-256',
        validation_json JSON DEFAULT NULL COMMENT '统一校验结果',
        created_by BIGINT DEFAULT NULL COMMENT '创建用户ID',
        validated_by BIGINT DEFAULT NULL COMMENT '校验用户ID',
        activated_by BIGINT DEFAULT NULL COMMENT '激活用户ID',
        retired_by BIGINT DEFAULT NULL COMMENT '停用用户ID',
        previous_active_release_id BIGINT DEFAULT NULL COMMENT '激活前的活动版本ID',
        validated_at TIMESTAMP NULL DEFAULT NULL,
        activated_at TIMESTAMP NULL DEFAULT NULL,
        retired_at TIMESTAMP NULL DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        active_domain_id BIGINT GENERATED ALWAYS AS (
            CASE WHEN status = 'active' THEN domain_id ELSE NULL END
        ) STORED,
        UNIQUE KEY uk_enterprise_model_release_version (domain_id, version),
        UNIQUE KEY uk_enterprise_model_release_components (
            domain_id, semantic_snapshot_id, ontology_release_id
        ),
        UNIQUE KEY uk_enterprise_model_release_active (active_domain_id),
        INDEX idx_enterprise_model_release_domain (domain_id, status, version),
        INDEX idx_enterprise_model_release_semantic (semantic_snapshot_id),
        INDEX idx_enterprise_model_release_ontology (ontology_release_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='统一企业模型发布版本'
    """,
]
