"""Idempotent DDL used by the application startup migration."""

ONTOLOGY_TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ontology_object_type (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        object_key VARCHAR(128) NOT NULL,
        name VARCHAR(256) NOT NULL,
        description TEXT,
        primary_property VARCHAR(128) NOT NULL,
        display_property VARCHAR(128) DEFAULT NULL,
        status VARCHAR(32) DEFAULT 'draft',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_ontology_object_type (domain_id, object_key),
        INDEX idx_ontology_object_domain (domain_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology对象类型'
    """,
    """
    CREATE TABLE IF NOT EXISTS ontology_property (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        object_type_id BIGINT NOT NULL,
        property_key VARCHAR(128) NOT NULL,
        name VARCHAR(256) NOT NULL,
        data_type VARCHAR(32) NOT NULL,
        required TINYINT(1) DEFAULT 0,
        `unique` TINYINT(1) DEFAULT 0,
        description TEXT,
        default_value JSON DEFAULT NULL,
        sort_order INT DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_ontology_property (object_type_id, property_key),
        INDEX idx_ontology_property_object (object_type_id, sort_order)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology对象属性'
    """,
    """
    CREATE TABLE IF NOT EXISTS ontology_link_type (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        link_key VARCHAR(128) NOT NULL,
        name VARCHAR(256) NOT NULL,
        source_object_key VARCHAR(128) NOT NULL,
        target_object_key VARCHAR(128) NOT NULL,
        source_property VARCHAR(128) NOT NULL,
        target_property VARCHAR(128) NOT NULL,
        cardinality VARCHAR(32) NOT NULL,
        description TEXT,
        status VARCHAR(32) DEFAULT 'draft',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_ontology_link_type (domain_id, link_key),
        INDEX idx_ontology_link_domain (domain_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology关系类型'
    """,
    """
    CREATE TABLE IF NOT EXISTS ontology_action_type (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        action_key VARCHAR(128) NOT NULL,
        name VARCHAR(256) NOT NULL,
        target_object_key VARCHAR(128) NOT NULL,
        description TEXT,
        parameters JSON DEFAULT NULL,
        preconditions JSON DEFAULT NULL,
        effects JSON DEFAULT NULL,
        allowed_roles JSON DEFAULT NULL,
        requires_approval TINYINT(1) DEFAULT 0,
        status VARCHAR(32) DEFAULT 'draft',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_ontology_action_type (domain_id, action_key),
        INDEX idx_ontology_action_domain (domain_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology动作类型'
    """,
    """
    CREATE TABLE IF NOT EXISTS ontology_object (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        object_type_id BIGINT NOT NULL,
        primary_value VARCHAR(512) NOT NULL,
        display_name VARCHAR(512) NOT NULL,
        properties JSON NOT NULL,
        version BIGINT NOT NULL DEFAULT 1,
        status VARCHAR(32) DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_ontology_object (object_type_id, primary_value),
        INDEX idx_ontology_object_domain (domain_id, object_type_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology对象实例'
    """,
    """
    CREATE TABLE IF NOT EXISTS ontology_link (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        link_type_id BIGINT NOT NULL,
        source_object_id BIGINT NOT NULL,
        target_object_id BIGINT NOT NULL,
        properties JSON DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_ontology_link (link_type_id, source_object_id, target_object_id),
        INDEX idx_ontology_link_domain (domain_id, link_type_id),
        INDEX idx_ontology_link_source (source_object_id),
        INDEX idx_ontology_link_target (target_object_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology关系实例'
    """,
    """
    CREATE TABLE IF NOT EXISTS ontology_action_run (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        action_type_id BIGINT NOT NULL,
        target_object_id BIGINT DEFAULT NULL,
        user_id BIGINT DEFAULT NULL,
        status VARCHAR(32) NOT NULL,
        parameters JSON DEFAULT NULL,
        decision_context JSON DEFAULT NULL,
        before_state JSON DEFAULT NULL,
        after_state JSON DEFAULT NULL,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP NULL DEFAULT NULL,
        INDEX idx_ontology_run_domain (domain_id, created_at),
        INDEX idx_ontology_run_user (user_id, created_at),
        INDEX idx_ontology_run_action (action_type_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology动作与决策审计'
    """,
    """
    CREATE TABLE IF NOT EXISTS ontology_release (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        version INT NOT NULL,
        name VARCHAR(256) NOT NULL,
        description TEXT,
        validation_json JSON NOT NULL,
        definition_json JSON NOT NULL,
        published_by BIGINT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_ontology_release (domain_id, version),
        INDEX idx_ontology_release_domain (domain_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology发布版本'
    """,
]
