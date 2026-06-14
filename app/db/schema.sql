-- 管理库: 智能体配置
CREATE DATABASE IF NOT EXISTS dataquery_agent DEFAULT CHARACTER SET utf8mb4;
USE dataquery_agent;

-- 智能体表
CREATE TABLE IF NOT EXISTS agent (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL COMMENT '智能体名称',
    description TEXT COMMENT '描述',
    llm_provider VARCHAR(64) DEFAULT 'ollama' COMMENT 'LLM 提供商',
    llm_model VARCHAR(128) DEFAULT 'qwen3:14b' COMMENT 'LLM 模型名',
    api_key VARCHAR(256) DEFAULT NULL COMMENT 'API Key',
    api_key_enabled TINYINT(1) DEFAULT 0 COMMENT 'API Key 是否启用',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体';

-- 数据源表
CREATE TABLE IF NOT EXISTS datasource (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT NOT NULL COMMENT '所属智能体',
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

-- 元数据表(表信息)
CREATE TABLE IF NOT EXISTS meta_table (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    datasource_id BIGINT NOT NULL COMMENT '所属数据源',
    table_name VARCHAR(256) NOT NULL COMMENT '物理表名',
    table_comment TEXT COMMENT '表注释',
    business_name VARCHAR(256) DEFAULT NULL COMMENT '业务名称',
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
    business_name VARCHAR(256) DEFAULT NULL COMMENT '业务名称',
    synonyms TEXT COMMENT '同义词(逗号分隔)',
    is_primary_key TINYINT(1) DEFAULT 0 COMMENT '是否主键',
    is_foreign_key TINYINT(1) DEFAULT 0 COMMENT '是否外键',
    foreign_key_ref VARCHAR(512) DEFAULT NULL COMMENT '外键引用(表.字段)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_table_id (table_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='元数据-字段';

-- 语义模型表
CREATE TABLE IF NOT EXISTS semantic_model (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT NOT NULL COMMENT '所属智能体',
    table_name VARCHAR(256) NOT NULL COMMENT '物理表名',
    column_name VARCHAR(256) NOT NULL COMMENT '物理字段名',
    business_name VARCHAR(256) NOT NULL COMMENT '业务名称',
    synonyms TEXT COMMENT '同义词(逗号分隔)',
    description TEXT COMMENT '业务描述',
    data_type VARCHAR(64) DEFAULT NULL COMMENT '数据类型',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_agent_id (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义模型';

-- 业务知识表
CREATE TABLE IF NOT EXISTS business_knowledge (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT NOT NULL COMMENT '所属智能体',
    title VARCHAR(256) NOT NULL COMMENT '知识标题',
    content TEXT NOT NULL COMMENT '知识内容',
    knowledge_type VARCHAR(32) DEFAULT 'definition' COMMENT '类型: definition/formula/rule',
    synonyms TEXT COMMENT '同义词',
    is_recall TINYINT(1) DEFAULT 1 COMMENT '是否参与召回',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_agent_id (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='业务知识';

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
    sql_text TEXT DEFAULT NULL COMMENT '生成的SQL',
    sql_result TEXT DEFAULT NULL COMMENT 'SQL执行结果(JSON)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session (agent_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话历史';
