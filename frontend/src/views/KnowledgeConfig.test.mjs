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
