import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./OntologyWorkbench.vue', import.meta.url), 'utf8')
const templateSource = source.split('<script setup')[0]
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

function sourceSection(start, end) {
  const startIndex = source.indexOf(start)
  const endIndex = source.indexOf(end, startIndex + start.length)
  assert.ok(startIndex >= 0 && endIndex > startIndex, `source section should exist: ${start}`)
  return source.slice(startIndex, endIndex)
}

const refreshAllSource = sourceSection('async function refreshAll()', 'async function handleTabChange')
const domainWatchSource = sourceSection('watch(domainId, () => {', 'onMounted(async () => {')

assert.ok(
  source.includes('defineProps') &&
    source.includes('domainId: number | null') &&
    source.includes('currentDomain: SemanticDomain | null') &&
    !source.includes('fetchOntologyDomains') &&
    !source.includes('class="domain-select"'),
  'ontology workbench should consume the shared enterprise-model domain context',
)

assert.ok(
  refreshAllSource.includes('Promise.all([') &&
    refreshAllSource.includes('fetchOntologySummary(id)') &&
    refreshAllSource.includes('fetchOntologyObjectTypes(id)') &&
    refreshAllSource.includes('fetchOntologyLinkTypes(id)') &&
    refreshAllSource.includes('fetchOntologyActionTypes(id)') &&
    refreshAllSource.includes('fetchOntologyReleases(id)') &&
    domainWatchSource.includes("activeTab.value = 'graph'"),
  'ontology refresh should load definition assets and reset domain changes to the graph tab',
)

for (const tab of ['本体图谱', '对象类型', '关系类型', '动作类型']) {
  assert.ok(templateSource.includes(`label="${tab}"`), `Ontology workbench should include ${tab}`)
}
for (const runtimeTab of ['对象实例', '关系实例', '动作执行记录', '决策活动']) {
  assert.ok(
    !templateSource.includes(`<el-tab-pane label="${runtimeTab}"`),
    `Ontology workbench should not retain the runtime tab ${runtimeTab}`,
  )
}

assert.ok(
  source.includes("{ label: '对象实例'") &&
    source.includes("{ label: '动作执行记录'") &&
    source.includes("target: 'twin-instances'") &&
    source.includes("target: 'twin-audit'") &&
    source.includes("path: '/twin-runtime'") &&
    source.includes("view: target === 'twin-instances' ? 'instances' : 'audit'"),
  'runtime metrics should navigate to the corresponding twin-runtime views',
)

assert.ok(
    !source.includes('fetchOntologyObjects') &&
    !source.includes('fetchOntologyLinks') &&
    !source.includes('fetchOntologyActionRuns') &&
    !source.includes('saveOntologyObject,') &&
    !source.includes('saveOntologyLink,') &&
    !source.includes('executeOntologyAction'),
  'ontology workbench should only manage model definitions, not runtime records',
)

assert.ok(
  appSource.includes('问渠 WenQu') &&
    appSource.includes('企业本体数字孪生与智能决策平台') &&
    appSource.includes('企业模型') &&
    appSource.includes('风险交付') &&
    source.includes('<h2>业务本体与动作</h2>'),
  'product branding should present enterprise modeling as the platform foundation and retain risk delivery',
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
  'handleValidate',
  'handlePublish',
  'handleImport',
  'handleExport',
]) {
  assert.ok(source.includes(workflow), `Ontology workbench should expose ${workflow}`)
}

assert.ok(
  source.includes('校验模型') &&
    source.includes('发布本体版本') &&
    source.includes('更多') &&
    source.includes('导入本体包') &&
    source.includes('导出本体包') &&
    source.includes('@command="handleModelCommand"') &&
    !templateSource.includes('>导入</el-button>') &&
    !templateSource.includes('>导出</el-button>'),
  'ontology workbench should keep validate and publish visible while grouping package import/export under more',
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
  source.includes(':aria-busy="loading"') &&
    source.includes('aria-label="企业模型资产概览"') &&
    source.includes(':aria-label="`${metric.label} ${metric.value}`"') &&
    source.includes('role="img" :aria-label="graphAriaLabel"') &&
    source.includes('const graphAriaLabel = computed') &&
    source.includes('详细定义可通过对象类型、关系类型和动作类型页签查看'),
  'ontology overview and graph should expose a useful non-visual description',
)

assert.ok(
  source.includes('tabindex="0"') &&
    source.includes('无需审批单号，执行时仍受角色、状态和前置条件限制') &&
    source.includes(':aria-label="`移除属性 ${property.name || property.property_key || index + 1}`"') &&
    source.includes(':aria-label="`移除动作参数 ${parameter.name || parameter.parameter_key || index + 1}`"') &&
    source.includes(':aria-label="`移除前置条件 ${index + 1}`"') &&
    source.includes(':aria-label="`移除状态效果 ${index + 1}`"') &&
    source.includes('role="status" aria-live="polite"') &&
    source.includes('@opened="focusControl(objectKeyInput)"') &&
    source.includes('@opened="focusControl(linkKeyInput)"') &&
    source.includes('@opened="focusControl(actionKeyInput)"') &&
    source.includes('requestAnimationFrame(() => control?.focus())'),
  'ontology builders and validation output should remain operable and understandable by keyboard',
)

assert.ok(
  source.includes('class="section-heading-note"') &&
    source.includes('定义实体/业务记录、属性和数据来源') &&
    source.includes('描述对象之间的业务连接和基数') &&
    source.includes('定义可执行动作、权限和状态效果'),
  'definition tabs should expose concise contextual descriptions',
)

assert.ok(
  source.includes('label="关系路径"') &&
    source.includes('class="relation-flow"') &&
    source.includes('class="relation-endpoint"') &&
    source.includes('class="relation-arrow"') &&
    source.includes('label="配置概览"') &&
    source.includes('class="action-counts"') &&
    source.includes('class="role-tags"'),
  'relationship endpoints and action configuration counts should read as structured business information',
)

assert.ok(
  source.includes('.ontology-table :deep(.el-table__body tr:hover > td.el-table__cell)') &&
    source.includes('.table-action-btn:active') &&
    source.includes('@media (max-width: 760px)') &&
    source.includes('overflow-x: auto') &&
    source.includes('@media (prefers-reduced-motion: reduce)'),
  'ontology tables should provide row feedback, tactile action states, mobile overflow, and reduced-motion fallbacks',
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
  'object types should expose sync configuration and source totals without hosting runtime instances',
)

assert.ok(
  routerSource.includes("path: '/enterprise-model'") &&
    routerSource.includes("path: '/twin-runtime'") &&
    routerSource.includes("path: '/capability-center'") &&
    routerSource.includes("path: '/ontology'") &&
    routerSource.includes("path: '/risk-delivery'") &&
    appSource.includes('index="/enterprise-model"') &&
    appSource.includes('index="/twin-runtime"') &&
    appSource.includes('index="/capability-center"') &&
    appSource.includes('index="/risk-delivery"'),
  'enterprise model, twin runtime, capability publishing, and risk delivery should be routable from primary navigation',
)

assert.ok(
  source.includes('ResizeObserver') && source.includes('graphSize'),
  'ontology graph should react to container size changes before rendering',
)

assert.ok(
  source.includes('这里只画对象类型和业务动作，不是审批流程图') &&
    source.includes('实体或业务记录，如客户、贷款申请单') &&
    source.includes('贷款申请单 = 对象') &&
    source.includes('审批状态 = 状态') &&
    source.includes('审批贷款申请 = 动作') &&
    source.includes('对象类型（实体/业务记录）') &&
    source.includes('业务动作（处理行为）') &&
    source.includes('事件/状态') &&
    source.includes('记录发生过什么、现在到哪一步'),
  'ontology graph should explain the boundary between object types, states, actions, and business process',
)

assert.ok(
  source.includes('流程步骤请配置为动作或事件') &&
    source.includes('动作建议使用动词描述') &&
    source.includes('const graphTooltip ='),
  'ontology modeling forms and graph tooltips should guide business-friendly modeling semantics',
)

assert.ok(
  source.includes("initLayout: 'circular'") &&
    source.includes('top: 24, right: 24, bottom: 60, left: 24') &&
    source.includes('height: 100%; min-height: 0; overflow: hidden;'),
  'ontology graph should use a stable centered layout and remain inside the workspace',
)

assert.ok(
  siblingPageSources.every((page) => page.includes('height: 100%;') && page.includes('min-height: 0;')) &&
    themeSource.includes('--wq-page-bottom-gap: 32px'),
  'sibling second-level pages should use the available app height and share a bottom gap',
)

assert.ok(
  !source.includes('height="calc(100vh - 312px)"') &&
    source.includes('class="ontology-table"') &&
    source.includes('.table-section { height: 100%; min-height: 0; display: grid;'),
  'ontology definition tables should stay within the tab viewport',
)
