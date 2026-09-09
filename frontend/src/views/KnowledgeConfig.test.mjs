import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./KnowledgeConfig.vue', import.meta.url), 'utf8')
const objectBindingSource = readFileSync(new URL('./ObjectDataBindingPanel.vue', import.meta.url), 'utf8')

assert.ok(
  source.includes('defineProps') &&
    source.includes('domainId: number | null') &&
    source.includes("(event: 'domain-updated')") &&
    !source.includes('openCreateDomain') &&
    !source.includes('upsertSemanticDomain') &&
    !source.includes('v-model="domainId"'),
  'semantic configuration should consume the enterprise-model domain instead of owning domain CRUD',
)

assert.ok(
  !source.includes('_labelMap') && !source.includes('loan_application_indicator:'),
  'KnowledgeConfig should not carry hidden credit-domain label maps',
)

assert.ok(
  source.includes('metric.name') && source.includes('mapping.description'),
  'KnowledgeConfig should resolve labels from semantic assets and mapping descriptions',
)

assert.ok(
  source.includes('semanticLabel') && source.includes('columnNameLabel'),
  'KnowledgeConfig should keep dynamic label helpers for detail pages',
)

assert.ok(
  source.includes('fetchOntologyLinkTypes') &&
    source.includes('已有本体业务关系') &&
    source.includes('@change="handleOntologyLinkSelect"') &&
    source.includes('引用本体关系，不重复定义业务关系') &&
    source.includes("relation_type: ontologyLink ? 'join_path'") &&
    source.includes('source_concept: ontologyLink?.source_object_key') &&
    !source.includes('<el-input v-model="assetDraft.source_concept"') &&
    !source.includes('<el-input v-model="assetDraft.target_concept"'),
  'semantic relations should reference an existing ontology link instead of defining a second business relationship',
)

assert.ok(
  source.includes('指标业务口径') &&
    source.includes('业务人员确认') &&
    source.includes('物理数据绑定（技术工程师高级配置）') &&
    source.includes('SQL 计算公式') &&
    source.includes('数据库结构变化时，只调整这里，不改变上层业务语义'),
  'metric and mapping forms should separate business semantics from technical data bindings',
)

assert.ok(
  source.includes('业务对象直接引用企业本体') &&
    source.includes('不再创建第二套对象') &&
    source.includes('补充查询词汇'),
  'semantic concepts should be presented as query vocabulary attached to ontology objects',
)

assert.ok(
  source.includes("mode?: 'business' | 'binding'") &&
    source.includes('business-object-layout') &&
    source.includes('selectedObjectKey') &&
    source.includes('指标与业务规则') &&
    source.includes('领域级指标') &&
    !source.includes('v-for="tab in assetTabs"'),
  'business semantics should be organized around ontology objects instead of six storage-shaped tabs',
)

assert.ok(
  source.includes('ObjectDataBindingPanel') &&
    source.includes('对象数据源') &&
    source.includes('指标计算') &&
    source.includes('关系连接') &&
    source.includes('字段映射') &&
    source.includes('高级查询配置'),
  'data binding should follow technical tasks while keeping LogicForm and rewrite rules in advanced configuration',
)

assert.ok(
  source.includes('fetchDatasourceSchema') &&
    source.includes('tableOptions') &&
    source.includes('qualifiedColumnOptions') &&
    source.includes('mappingColumnOptions') &&
    source.includes('选择已采集表') &&
    source.includes('选择已采集字段'),
  'technical bindings should prefer collected schema choices over manual table and column transcription',
)

assert.ok(
  objectBindingSource.includes('选择表和字段') &&
    objectBindingSource.includes('高级 SQL') &&
    objectBindingSource.includes('fetchDatasourceSchema') &&
    objectBindingSource.includes('autoMapFields') &&
    objectBindingSource.includes('buildGuidedSourceQuery') &&
    objectBindingSource.includes('AS ${quoteIdentifier(item.property.property_key)}') &&
    objectBindingSource.includes('previewOntologyObjectMapping') &&
    objectBindingSource.includes('properties: cloneValue(objectDefinition.properties || [])'),
  'object data binding should generate a safe read-only query from schema selections while preserving the full object definition',
)

assert.ok(
  source.includes('metadata: isPlainObject(row.metadata) ? row.metadata : {}') &&
    source.includes('object_keys: metricObjectKeys(row)') &&
    source.includes('metadata.object_keys = objectKeys') &&
    source.includes('metadata: isPlainObject(draft.metadata) ? draft.metadata : {}'),
  'editing a metric should preserve one or more ontology object associations',
)

assert.ok(
  source.includes('_original_expression: expression') &&
    source.includes('return originalExpression') &&
    source.includes('const expression = { ...originalExpression }') &&
    source.includes('expression[key] = parseExpressionValue(draft.expression_value)') &&
    source.includes('return JSON.parse(text)'),
  'editing a rule should preserve untouched nested expression data and parse edited JSON values',
)

assert.ok(
  source.includes('_original_join_path') &&
    source.includes('return originalPath') &&
    source.includes('_original_default_filters') &&
    source.includes('return originalFilters'),
  'editing simplified forms should preserve multi-hop joins and additional default filters',
)
