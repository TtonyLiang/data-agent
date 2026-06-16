-- 管理库: 智能体配置
CREATE DATABASE IF NOT EXISTS dataquery_agent DEFAULT CHARACTER SET utf8mb4;
USE dataquery_agent;

-- 智能体表
CREATE TABLE IF NOT EXISTS agent (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL COMMENT '智能体名称',
    description TEXT COMMENT '描述',
    chat_model_config_id BIGINT DEFAULT NULL COMMENT '大语言模型配置ID',
    embedding_model_config_id BIGINT DEFAULT NULL COMMENT '向量模型配置ID',
    semantic_domain_id BIGINT DEFAULT NULL COMMENT '默认语义领域ID',
    llm_provider VARCHAR(64) DEFAULT 'ollama' COMMENT 'LLM 提供商',
    llm_model VARCHAR(128) DEFAULT 'qwen3:14b' COMMENT 'LLM 模型名',
    api_key VARCHAR(256) DEFAULT NULL COMMENT 'API Key',
    api_key_enabled TINYINT(1) DEFAULT 0 COMMENT 'API Key 是否启用',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体';

-- 模型配置表
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模型配置';

-- 数据源表
CREATE TABLE IF NOT EXISTS datasource (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT DEFAULT NULL COMMENT '兼容字段: 原所属智能体',
    name VARCHAR(128) NOT NULL COMMENT '数据源名称',
    db_type VARCHAR(32) DEFAULT 'mysql' COMMENT '数据库类型',
    host VARCHAR(256) NOT NULL COMMENT '主机',
    port INT NOT NULL COMMENT '端口',
    username VARCHAR(128) NOT NULL COMMENT '用户名',
    password VARCHAR(256) NOT NULL COMMENT '密码(加密存储)',
    database_name VARCHAR(128) NOT NULL COMMENT '数据库名',
    status VARCHAR(32) DEFAULT 'active' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_agent_id (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据源';

-- 智能体与数据源关联
CREATE TABLE IF NOT EXISTS agent_datasource (
    agent_id BIGINT NOT NULL COMMENT '智能体ID',
    datasource_id BIGINT NOT NULL COMMENT '数据源ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (agent_id, datasource_id),
    INDEX idx_datasource_id (datasource_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体数据源关联';

-- 元数据表(表信息)
CREATE TABLE IF NOT EXISTS meta_table (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    datasource_id BIGINT NOT NULL COMMENT '所属数据源',
    table_name VARCHAR(256) NOT NULL COMMENT '物理表名',
    table_comment TEXT COMMENT '表注释',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_datasource_id (datasource_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='元数据-表';

-- 元数据表(字段信息)
CREATE TABLE IF NOT EXISTS meta_column (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    table_id BIGINT NOT NULL COMMENT '所属表',
    column_name VARCHAR(256) NOT NULL COMMENT '物理字段名',
    data_type VARCHAR(64) NOT NULL COMMENT '数据类型',
    column_comment TEXT COMMENT '字段注释',
    is_primary_key TINYINT(1) DEFAULT 0 COMMENT '是否主键',
    is_foreign_key TINYINT(1) DEFAULT 0 COMMENT '是否外键',
    foreign_key_ref VARCHAR(512) DEFAULT NULL COMMENT '外键引用(表.字段)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_table_id (table_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='元数据-字段';

-- 语义领域
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义领域';

-- 语义概念: 对象、事件、状态、维度、动作
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义概念';

-- 语义关系: 对象关系、事件链路、状态变化、JOIN路径
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义关系';

-- 语义指标
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义指标';

-- 语义规则
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义规则';

-- 语义到物理映射
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义物理映射';

-- LogicForm 模板
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='LogicForm模板';

-- 智能体知识库(文档)
CREATE TABLE IF NOT EXISTS agent_knowledge (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT NOT NULL COMMENT '所属智能体',
    title VARCHAR(256) NOT NULL COMMENT '文档标题',
    content LONGTEXT NOT NULL COMMENT '文档内容',
    knowledge_type VARCHAR(32) DEFAULT 'document' COMMENT '类型: document/qa',
    chunk_count INT DEFAULT 0 COMMENT '分块数量',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_agent_id (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体知识库';

-- 对话历史表
CREATE TABLE IF NOT EXISTS chat_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT NOT NULL COMMENT '所属智能体',
    session_id VARCHAR(64) NOT NULL COMMENT '会话ID',
    role VARCHAR(16) NOT NULL COMMENT '角色: user/assistant',
    content LONGTEXT NOT NULL COMMENT '消息内容',
    reasoning_trace JSON DEFAULT NULL COMMENT '流式思考与节点轨迹',
    logic_form JSON DEFAULT NULL COMMENT '语义中间表达',
    compiled_sql TEXT DEFAULT NULL COMMENT '确定性编译SQL',
    execution_trace JSON DEFAULT NULL COMMENT '执行轨迹',
    sql_text TEXT DEFAULT NULL COMMENT '兼容字段: 生成的SQL',
    sql_result TEXT DEFAULT NULL COMMENT 'SQL执行结果(JSON)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session (agent_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话历史';
