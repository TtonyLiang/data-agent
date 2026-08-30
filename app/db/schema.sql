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
    default_questions JSON DEFAULT NULL COMMENT '对话页默认推荐问题',
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
    api_key_expires_at TIMESTAMP NULL DEFAULT NULL COMMENT 'API Key过期时间',
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

-- 智能体表级权限；未配置时默认沿用数据源授权，配置后按白名单/黑名单生效
CREATE TABLE IF NOT EXISTS agent_table_permission (
    agent_id BIGINT NOT NULL COMMENT '智能体ID',
    datasource_id BIGINT NOT NULL COMMENT '数据源ID',
    table_name VARCHAR(256) NOT NULL COMMENT '物理表名',
    allowed TINYINT(1) DEFAULT 1 COMMENT '是否允许访问',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (agent_id, datasource_id, table_name),
    INDEX idx_agent_table_permission_ds (datasource_id, table_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体表级权限';

-- 智能体列级权限与脱敏策略；未配置列默认允许且不脱敏
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体列级权限与脱敏';

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

-- 语义层版本快照
CREATE TABLE IF NOT EXISTS semantic_domain_snapshot (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    domain_id BIGINT NOT NULL COMMENT '语义层ID',
    name VARCHAR(256) NOT NULL COMMENT '快照名称',
    description TEXT COMMENT '快照说明',
    snapshot_json JSON NOT NULL COMMENT '语义层快照',
    asset_counts JSON DEFAULT NULL COMMENT '资产数量',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_domain_id (domain_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='语义层版本快照';

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

-- 运营本体: 对象类型
CREATE TABLE IF NOT EXISTS ontology_object_type (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    domain_id BIGINT NOT NULL COMMENT '所属语义领域',
    object_key VARCHAR(128) NOT NULL COMMENT '对象类型标识',
    name VARCHAR(256) NOT NULL COMMENT '业务名称',
    description TEXT COMMENT '业务定义',
    primary_property VARCHAR(128) NOT NULL COMMENT '业务主属性',
    display_property VARCHAR(128) DEFAULT NULL COMMENT '显示属性',
    status VARCHAR(32) DEFAULT 'draft' COMMENT 'draft/active/deprecated',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ontology_object_type (domain_id, object_key),
    INDEX idx_ontology_object_domain (domain_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology对象类型';

-- 运营本体: 对象属性
CREATE TABLE IF NOT EXISTS ontology_property (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    object_type_id BIGINT NOT NULL COMMENT '对象类型ID',
    property_key VARCHAR(128) NOT NULL COMMENT '属性标识',
    name VARCHAR(256) NOT NULL COMMENT '属性名称',
    data_type VARCHAR(32) NOT NULL COMMENT '属性数据类型',
    required TINYINT(1) DEFAULT 0 COMMENT '是否必填',
    `unique` TINYINT(1) DEFAULT 0 COMMENT '是否业务唯一',
    description TEXT COMMENT '属性说明',
    default_value JSON DEFAULT NULL COMMENT '默认值',
    sort_order INT DEFAULT 0 COMMENT '展示顺序',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ontology_property (object_type_id, property_key),
    INDEX idx_ontology_property_object (object_type_id, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology对象属性';

-- 运营本体: 关系类型
CREATE TABLE IF NOT EXISTS ontology_link_type (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    domain_id BIGINT NOT NULL COMMENT '所属语义领域',
    link_key VARCHAR(128) NOT NULL COMMENT '关系标识',
    name VARCHAR(256) NOT NULL COMMENT '关系名称',
    source_object_key VARCHAR(128) NOT NULL COMMENT '起点对象类型',
    target_object_key VARCHAR(128) NOT NULL COMMENT '终点对象类型',
    source_property VARCHAR(128) NOT NULL COMMENT '起点连接属性',
    target_property VARCHAR(128) NOT NULL COMMENT '终点连接属性',
    cardinality VARCHAR(32) NOT NULL COMMENT '关系基数',
    description TEXT COMMENT '关系说明',
    status VARCHAR(32) DEFAULT 'draft' COMMENT 'draft/active/deprecated',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ontology_link_type (domain_id, link_key),
    INDEX idx_ontology_link_domain (domain_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology关系类型';

-- 运营本体: 动作类型
CREATE TABLE IF NOT EXISTS ontology_action_type (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    domain_id BIGINT NOT NULL COMMENT '所属语义领域',
    action_key VARCHAR(128) NOT NULL COMMENT '动作标识',
    name VARCHAR(256) NOT NULL COMMENT '动作名称',
    target_object_key VARCHAR(128) NOT NULL COMMENT '目标对象类型',
    description TEXT COMMENT '业务动作说明',
    parameters JSON DEFAULT NULL COMMENT '动作参数定义',
    preconditions JSON DEFAULT NULL COMMENT '执行前置条件',
    effects JSON DEFAULT NULL COMMENT '对象状态效果',
    allowed_roles JSON DEFAULT NULL COMMENT '允许执行的角色',
    requires_approval TINYINT(1) DEFAULT 0 COMMENT '是否需要审批单号',
    status VARCHAR(32) DEFAULT 'draft' COMMENT 'draft/active/deprecated',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ontology_action_type (domain_id, action_key),
    INDEX idx_ontology_action_domain (domain_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology动作类型';

-- 运营本体: 对象实例
CREATE TABLE IF NOT EXISTS ontology_object (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    domain_id BIGINT NOT NULL COMMENT '所属语义领域',
    object_type_id BIGINT NOT NULL COMMENT '对象类型ID',
    primary_value VARCHAR(512) NOT NULL COMMENT '业务主键值',
    display_name VARCHAR(512) NOT NULL COMMENT '显示名称',
    properties JSON NOT NULL COMMENT '对象属性值',
    version BIGINT NOT NULL DEFAULT 1 COMMENT '乐观版本',
    status VARCHAR(32) DEFAULT 'active' COMMENT 'active/archived',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ontology_object (object_type_id, primary_value),
    INDEX idx_ontology_object_domain (domain_id, object_type_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology对象实例';

-- 运营本体: 关系实例
CREATE TABLE IF NOT EXISTS ontology_link (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    domain_id BIGINT NOT NULL COMMENT '所属语义领域',
    link_type_id BIGINT NOT NULL COMMENT '关系类型ID',
    source_object_id BIGINT NOT NULL COMMENT '起点对象ID',
    target_object_id BIGINT NOT NULL COMMENT '终点对象ID',
    properties JSON DEFAULT NULL COMMENT '关系属性',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ontology_link (link_type_id, source_object_id, target_object_id),
    INDEX idx_ontology_link_domain (domain_id, link_type_id),
    INDEX idx_ontology_link_source (source_object_id),
    INDEX idx_ontology_link_target (target_object_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology关系实例';

-- 运营本体: 动作执行审计
CREATE TABLE IF NOT EXISTS ontology_action_run (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    domain_id BIGINT NOT NULL COMMENT '所属语义领域',
    action_type_id BIGINT NOT NULL COMMENT '动作类型ID',
    target_object_id BIGINT DEFAULT NULL COMMENT '目标对象ID',
    user_id BIGINT DEFAULT NULL COMMENT '执行用户ID',
    status VARCHAR(32) NOT NULL COMMENT 'running/succeeded/failed',
    parameters JSON DEFAULT NULL COMMENT '执行参数',
    decision_context JSON DEFAULT NULL COMMENT '决策上下文',
    before_state JSON DEFAULT NULL COMMENT '执行前对象状态',
    after_state JSON DEFAULT NULL COMMENT '执行后对象状态',
    error_message TEXT COMMENT '失败原因',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL DEFAULT NULL,
    INDEX idx_ontology_run_domain (domain_id, created_at),
    INDEX idx_ontology_run_user (user_id, created_at),
    INDEX idx_ontology_run_action (action_type_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology动作与决策审计';

-- 运营本体: 发布快照
CREATE TABLE IF NOT EXISTS ontology_release (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    domain_id BIGINT NOT NULL COMMENT '所属语义领域',
    version INT NOT NULL COMMENT '递增发布版本',
    name VARCHAR(256) NOT NULL COMMENT '版本名称',
    description TEXT COMMENT '发布说明',
    validation_json JSON NOT NULL COMMENT '发布校验结果',
    definition_json JSON NOT NULL COMMENT '不可变定义快照',
    published_by BIGINT DEFAULT NULL COMMENT '发布用户ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ontology_release (domain_id, version),
    INDEX idx_ontology_release_domain (domain_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ontology发布版本';

-- Prompt 模板: 可按智能体、模型配置、语义层覆盖各节点系统提示词
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
    INDEX idx_prompt_scope (prompt_key, agent_id, model_config_id, semantic_domain_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Prompt模板配置';

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
    plan_payload JSON DEFAULT NULL COMMENT 'Phase3分析计划',
    semantic_check JSON DEFAULT NULL COMMENT 'SQL前语义一致性校验结果',
    python_result JSON DEFAULT NULL COMMENT 'Python分析结果',
    report_payload JSON DEFAULT NULL COMMENT '结构化分析报告',
    task_id VARCHAR(64) DEFAULT NULL COMMENT '持久任务ID',
    turn_id VARCHAR(64) DEFAULT NULL COMMENT '任务轮次ID',
    turn_mode VARCHAR(32) DEFAULT NULL COMMENT '任务轮次模式',
    task_status VARCHAR(32) DEFAULT NULL COMMENT '任务状态',
    task_metadata JSON DEFAULT NULL COMMENT '任务复用与失效摘要',
    sql_text TEXT DEFAULT NULL COMMENT '兼容字段: 生成的SQL',
    sql_result LONGTEXT DEFAULT NULL COMMENT 'SQL执行结果(JSON)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session (agent_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话历史';

-- Agent 持久任务 checkpoint；聊天历史用于展示，本表用于跨请求/重启续跑
CREATE TABLE IF NOT EXISTS agent_task_checkpoint (
    user_id BIGINT NOT NULL COMMENT '归属用户ID',
    agent_id BIGINT NOT NULL COMMENT '智能体ID',
    session_id VARCHAR(64) NOT NULL COMMENT '会话ID',
    task_id VARCHAR(64) NOT NULL COMMENT '持久任务ID',
    turn_id VARCHAR(64) NOT NULL COMMENT '当前轮次ID',
    revision BIGINT NOT NULL DEFAULT 1 COMMENT 'checkpoint修订号',
    status VARCHAR(32) NOT NULL DEFAULT 'running' COMMENT 'running/awaiting_input/completed/failed',
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent持久任务checkpoint';

-- 用户反馈回流
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户反馈';
