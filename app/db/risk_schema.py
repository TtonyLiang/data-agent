"""Idempotent DDL for the risk workflow and decision audit module."""

RISK_WORKFLOW_TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS risk_issue (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        ontology_release_id BIGINT NOT NULL,
        subject_object_id BIGINT DEFAULT NULL,
        issue_key VARCHAR(128) NOT NULL,
        category VARCHAR(128) NOT NULL,
        severity VARCHAR(16) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'open',
        title VARCHAR(256) NOT NULL,
        description TEXT,
        rule_key VARCHAR(128) DEFAULT NULL,
        detected_value JSON DEFAULT NULL,
        expected_value JSON DEFAULT NULL,
        source_context JSON NOT NULL,
        assignee VARCHAR(128) DEFAULT NULL,
        version BIGINT NOT NULL DEFAULT 1,
        created_by BIGINT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_risk_issue (domain_id, issue_key),
        INDEX idx_risk_issue_domain_status (domain_id, status, severity),
        INDEX idx_risk_issue_subject (subject_object_id),
        INDEX idx_risk_issue_release (ontology_release_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='风险事项'
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_evidence (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        issue_id BIGINT NOT NULL,
        ontology_release_id BIGINT NOT NULL,
        evidence_type VARCHAR(32) NOT NULL,
        title VARCHAR(256) NOT NULL,
        description TEXT,
        source_ref VARCHAR(1024) DEFAULT NULL,
        content JSON NOT NULL,
        trace_id VARCHAR(128) DEFAULT NULL,
        checksum CHAR(64) NOT NULL,
        created_by BIGINT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_risk_evidence_issue (domain_id, issue_id, created_at),
        INDEX idx_risk_evidence_trace (trace_id),
        INDEX idx_risk_evidence_checksum (checksum)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='风险证据链'
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_issue_review (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        issue_id BIGINT NOT NULL,
        ontology_release_id BIGINT NOT NULL,
        review_action VARCHAR(32) NOT NULL,
        before_status VARCHAR(32) NOT NULL,
        after_status VARCHAR(32) NOT NULL,
        before_state JSON NOT NULL,
        after_state JSON NOT NULL,
        reviewer_id BIGINT DEFAULT NULL,
        reviewer VARCHAR(128) NOT NULL,
        comment TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_risk_review_issue (domain_id, issue_id, created_at),
        INDEX idx_risk_review_reviewer (reviewer_id, created_at),
        INDEX idx_risk_review_release (ontology_release_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='风险人工复核记录'
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_report (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        report_key VARCHAR(128) NOT NULL,
        name VARCHAR(256) NOT NULL,
        report_type VARCHAR(128) NOT NULL,
        period_start DATE DEFAULT NULL,
        period_end DATE DEFAULT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'draft',
        current_version INT NOT NULL DEFAULT 1,
        created_by BIGINT DEFAULT NULL,
        finalized_by BIGINT DEFAULT NULL,
        finalized_at TIMESTAMP NULL DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_risk_report (domain_id, report_key),
        INDEX idx_risk_report_domain (domain_id, status, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='风险与财税交付报告'
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_report_version (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        report_id BIGINT NOT NULL,
        domain_id BIGINT NOT NULL,
        version INT NOT NULL,
        ontology_release_id BIGINT NOT NULL,
        issue_ids JSON NOT NULL,
        snapshot_json JSON NOT NULL,
        markdown LONGTEXT NOT NULL,
        content_hash CHAR(64) NOT NULL,
        created_by BIGINT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_risk_report_version (report_id, version),
        INDEX idx_risk_report_version_domain (domain_id, report_id, version),
        INDEX idx_risk_report_version_release (ontology_release_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='不可变报告版本'
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_audit_event (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        sequence_no BIGINT NOT NULL,
        event_type VARCHAR(64) NOT NULL,
        entity_type VARCHAR(64) NOT NULL,
        entity_id BIGINT DEFAULT NULL,
        actor_id BIGINT DEFAULT NULL,
        actor VARCHAR(128) DEFAULT NULL,
        ontology_release_id BIGINT DEFAULT NULL,
        payload_json JSON NOT NULL,
        previous_hash CHAR(64) DEFAULT NULL,
        event_hash CHAR(64) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_decision_audit_sequence (domain_id, sequence_no),
        INDEX idx_decision_audit_domain (domain_id, created_at),
        INDEX idx_decision_audit_entity (domain_id, entity_type, entity_id),
        INDEX idx_decision_audit_hash (event_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='追加式决策审计哈希链'
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_audit_head (
        domain_id BIGINT PRIMARY KEY,
        event_count BIGINT NOT NULL DEFAULT 0,
        head_hash CHAR(64) DEFAULT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='决策审计链头锚点'
    """,
]
