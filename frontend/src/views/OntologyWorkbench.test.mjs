import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./OntologyWorkbench.vue', import.meta.url), 'utf8')
const themeSource = readFileSync(new URL('../theme.css', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../api/index.ts', import.meta.url), 'utf8')
const routerSource = readFileSync(new URL('../router/index.ts', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
const siblingPageSources = [
  'AgentList.vue',
  'ModelConfig.vue',
  'DatasourceConfig.vue',
  'KnowledgeConfig.vue',
  'PromptConfig.vue',
].map((name) => readFileSync(new URL(`./${name}`, import.meta.url), 'utf8'))

for (const tab of ['本体图谱', '对象类型', '关系类型', '动作类型', '对象实例', '决策活动']) {
  assert.ok(source.includes(tab), `Ontology workbench should include ${tab}`)
}

assert.ok(
  appSource.includes('问渠 WenQu') &&
    appSource.includes('AI报告交付与风险决策平台') &&
    appSource.includes('风险交付') &&
    appSource.includes('本体建模') &&
    source.includes('<h2>企业本体建模</h2>'),
  'product branding should present risk delivery as the primary workflow and retain ontology modeling',
)

assert.ok(
  !source.includes('title-icon') &&
    source.includes('.title-group h2 { color: var(--wq-text); font-size: 22px;') &&
    source.includes('.title-group p { margin-top: 8px;') &&
    source.includes('font-size: 14px;'),
  'ontology page heading should match the plain typography used by other management pages',
)

for (const workflow of [
  'saveObjectType',
  'saveLinkType',
  'saveActionType',
  'saveObjectInstance',
  'runAction',
  'handleValidate',
  'handlePublish',
  'handleImport',
  'handleExport',
]) {
  assert.ok(source.includes(workflow), `Ontology workbench should expose ${workflow}`)
}

assert.ok(
  source.includes('before_state') && source.includes('after_state') && source.includes('decision_context'),
  'decision activity should render context and before/after state',
)

assert.ok(
  source.includes('label="审批要求"') &&
    source.includes('需审批单号') &&
    source.includes('无需审批单号') &&
    source.includes('执行时不要求审批单号，但仍受角色、状态和前置条件限制') &&
    source.includes('class="table-actions"') &&
    source.includes('flex-wrap: nowrap'),
  'action table should clarify approval-number semantics and keep operation buttons aligned',
)

assert.ok(
  source.includes('objectPropertyEntries(row.properties)') &&
    source.includes('class="audit-field-list object-property-list"') &&
    source.includes('class="audit-field-value object-property-value"') &&
    source.includes('objectPropertyPreview(row.properties)') &&
    source.includes('hiddenPropertyCount(row.properties)') &&
    source.includes('const PROPERTY_PREVIEW_LIMIT = 4') &&
    source.includes('popper-class="object-property-tooltip"') &&
    source.includes('<template #content>') &&
    source.includes('object-property-tooltip-list') &&
    source.includes('function objectPropertyEntries') &&
    !source.includes('properties-tooltip') &&
    !source.includes('popper-class="properties-tooltip"'),
  'object properties should truncate long values and reveal the full value on hover',
)

assert.ok(
    source.includes('max-width: var(--wq-page-max-width)') &&
    source.includes('margin: 0 auto') &&
    source.includes('padding-inline: var(--wq-page-gutter)') &&
    source.includes('padding-bottom: var(--wq-page-bottom-gap)') &&
    source.includes('height="100%"') &&
    themeSource.includes('--wq-page-max-width: 1600px') &&
    themeSource.includes('--wq-page-gutter: clamp(16px, 2vw, 32px)') &&
    themeSource.includes('--wq-page-bottom-gap: 32px') &&
    themeSource.includes('height: 100% !important') &&
    themeSource.includes('.page-shell.embedded') &&
    themeSource.includes('padding: 0 !important'),
  'functional pages should share centered width, bottom spacing, and height-safe table sizing',
)

assert.ok(
  source.includes("function formatStateValue(value: unknown, key = '')") &&
    source.includes("value === undefined || value === null") &&
    source.includes("return '未设置'") &&
    source.includes("return formatDateTime(value, '未设置')"),
  'decision activity should render missing before/after values as unset instead of undefined',
)

assert.ok(
  source.includes('decisionContextEntries(row.decision_context)') &&
    source.includes('stateChangeEntries(row.before_state, row.after_state)') &&
    source.includes('audit-field-key') &&
    source.includes('tone-status') &&
    source.includes('state-value is-after'),
  'decision activity should render context and state fields as color-coded structured entries',
)

assert.ok(
  source.includes('format="YYYY-MM-DD HH:mm:ss"') &&
    source.includes('formatDateTime(row.created_at)') &&
    source.includes("formatStateValue(change.after, change.key)"),
  'ontology timestamps should display consistently to seconds in forms and audit records',
)

assert.ok(
  apiSource.includes('/ontology/domains/${domainId}/publish') &&
    apiSource.includes('/ontology/domains/${domainId}/actions/${actionTypeId}/execute'),
  'frontend API should include publish and action execution contracts',
)

assert.ok(
  apiSource.includes('sync_enabled: boolean') &&
    apiSource.includes('source_query?: string | null') &&
    apiSource.includes('sync_limit: number') &&
    apiSource.includes('last_sync_total?: number') &&
    apiSource.includes('source_objects?: number') &&
    apiSource.includes('export interface OntologySyncRequest') &&
    apiSource.includes('/ontology/domains/${domainId}/sync'),
  'frontend API should model object-type sync configuration, source totals, and the sync endpoint',
)

assert.ok(
  source.includes('label="业务库同步"') &&
    source.includes('label="默认分页大小"') &&
    source.includes('label="只读同步 SELECT"') &&
    source.includes('syncStatusLabel(row)') &&
    source.includes('row.last_sync_total || row.last_sync_count') &&
    source.includes('counts.source_objects || summary.value?.counts.objects'),
  'object types should expose sync configuration and prefer source totals while retaining cached-object compatibility',
)

assert.ok(
  source.includes("if (name === 'instances')") &&
    source.includes('@change="handleInstanceTypeChange"') &&
    source.includes('@click="syncAndLoadInstances(true)"') &&
    source.includes('@current-change="handleInstancePageChange"') &&
    source.includes('@size-change="handleInstancePageSizeChange"') &&
    source.includes('object_type_id: objectType.id') &&
    source.includes('page: instancePage.value') &&
    source.includes('page_size: instancePageSize.value') &&
    source.includes('sync_links: true'),
  'entering, refreshing, switching types, and paging should synchronize exactly one server-side page',
)

assert.ok(
  source.includes('class="instance-table"') &&
    source.includes('<section class="table-section instance-table-section">') &&
    source.includes('height="100%"') &&
    source.includes('.instance-table-section { grid-template-rows: auto minmax(0, 1fr) auto;') &&
    source.includes('.instance-pagination { position: relative; z-index: 2; min-height: 62px;'),
  'the instance table should reserve visible space for pagination inside the tab viewport',
)

assert.ok(
  !source.includes('fetchOntologyObjects(id)') &&
    source.includes('fetchOntologyObjects(domainId.value, instanceTypeId.value, pageSize, offset)') &&
    source.includes('const INSTANCE_CHOICE_LIMIT = 200') &&
    source.includes('fetchOntologyObjects(domainId.value!, typeId, INSTANCE_CHOICE_LIMIT, 0)'),
  'the workbench should avoid loading every object into the browser and keep auxiliary choices bounded',
)

assert.ok(
  source.includes("row.source_kind === 'database'") &&
    source.includes('>业务库</el-tag>') &&
    source.includes('>本地</el-tag>') &&
    source.includes('>本地覆盖</el-tag>') &&
    source.includes('row.overlay_properties'),
  'object instances should distinguish database, local, and local-overlay data',
)

assert.ok(
  routerSource.includes("path: '/ontology'") &&
    routerSource.includes("path: '/risk-delivery'") &&
    appSource.includes('index="/ontology"') &&
    appSource.includes('index="/risk-delivery"'),
  'risk delivery and ontology workbenches should be routable from primary navigation',
)

assert.ok(
  source.includes('ResizeObserver') && source.includes('graphSize'),
  'ontology graph should react to container size changes before rendering',
)

assert.ok(
  source.includes("initLayout: 'circular'"),
  'ontology graph should use a stable centered initial layout',
)

assert.ok(
  source.includes('top: 24, right: 24, bottom: 60, left: 24') &&
    source.includes('height: 100%; min-height: 0; overflow: hidden;'),
  'ontology graph should keep the legend and bottom labels inside the visible workspace',
)

assert.ok(
  siblingPageSources.every((page) => page.includes('height: 100%;') && page.includes('min-height: 0;')) &&
    themeSource.includes('--wq-page-bottom-gap: 32px'),
  'sibling second-level pages should use the available app height and share a bottom gap',
)

assert.ok(
  !source.includes('height="calc(100vh - 312px)"') &&
    source.includes('class="ontology-table"') &&
    source.includes('.table-section { height: 100%; min-height: 0; display: grid;') &&
    source.includes('.instance-table-section { grid-template-rows: auto minmax(0, 1fr) auto;'),
  'ontology tables should stay within the tab viewport instead of overflowing below it',
)
