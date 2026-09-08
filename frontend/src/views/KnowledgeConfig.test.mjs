import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./KnowledgeConfig.vue', import.meta.url), 'utf8')

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
  source.includes('handleDiffSnapshot') && source.includes('handleRollbackSnapshot'),
  'KnowledgeConfig should expose snapshot diff and rollback actions',
)

assert.ok(
  source.includes('snapshotDiffSummary') && source.includes('快照差异'),
  'KnowledgeConfig should render snapshot diff details before rollback',
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
    source.includes('物理数据绑定（管理员 / 数据工程师高级配置）') &&
    source.includes('SQL 计算公式') &&
    source.includes('数据库结构变化时，只调整这里，不改变上层业务语义'),
  'metric and mapping forms should separate business semantics from technical data bindings',
)

assert.ok(
  source.includes('动作词汇（不可执行）') &&
    source.includes('这里只维护动作词汇，不提供执行能力') &&
    source.includes('可执行业务动作，请在“业务本体与动作”中维护'),
  'semantic action vocabulary should be clearly separated from executable ontology actions',
)
