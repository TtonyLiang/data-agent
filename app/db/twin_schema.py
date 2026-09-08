"""Idempotent DDL for twin-runtime synchronization records."""

TWIN_RUNTIME_TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS twin_sync_run (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        object_type_id BIGINT DEFAULT NULL,
        model_release_id BIGINT DEFAULT NULL,
        datasource_id BIGINT NOT NULL,
        caller_agent_id BIGINT DEFAULT NULL,
        trace_id VARCHAR(128) NOT NULL,
        trigger_type VARCHAR(32) NOT NULL DEFAULT 'manual',
        dry_run TINYINT(1) NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL DEFAULT 'running',
        page INT NOT NULL DEFAULT 1,
        page_size INT NOT NULL DEFAULT 200,
        sync_links TINYINT(1) NOT NULL DEFAULT 1,
        statistics_json JSON DEFAULT NULL,
        error_summary TEXT DEFAULT NULL,
        created_by BIGINT DEFAULT NULL,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP NULL DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_twin_sync_run_domain (domain_id, created_at),
        INDEX idx_twin_sync_run_status (status, created_at),
        INDEX idx_twin_sync_run_trace (trace_id),
        INDEX idx_twin_sync_run_release (model_release_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='孪生同步运行记录'
    """,
]
