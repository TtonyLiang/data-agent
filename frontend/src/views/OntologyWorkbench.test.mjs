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
  source.includes('class="section-heading-note"') &&
    source.includes('定义实体/业务记录、属性和数据来源') &&
    source.includes('描述对象之间的业务连接和基数') &&
    source.includes('定义可执行动作、权限和状态效果') &&
    source.includes('追踪动作执行结果、决策上下文和状态变化'),
  'ontology tabs should expose concise contextual descriptions without flattening all toolbar content',
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
  source.includes('objectPropertyEntries(row.properties)') &&
    source.includes('class="audit-field-list object-property-list object-property-trigger"') &&
    source.includes('class="audit-field-value object-property-value"') &&
    source.includes('objectPropertyPreview(row.properties)') &&
    source.includes('hiddenPropertyCount(row.properties)') &&
    source.includes('const PROPERTY_PREVIEW_LIMIT = 4') &&
    source.includes('popper-class="object-property-tooltip"') &&
    source.includes('transition="object-property-popover-fade"') &&
    source.includes('class="object-property-tooltip-heading"') &&
    source.includes('完整属性') &&
    source.includes('<template #content>') &&
    source.includes('object-property-tooltip-list') &&
    source.includes('function objectPropertyEntries') &&
    !source.includes('properties-tooltip') &&
    !source.includes('popper-class="properties-tooltip"'),
  'object properties should truncate long values and reveal the full value on hover',
)

assert.ok(
  source.includes('.object-property-trigger:hover') &&
    source.includes(':global(.object-property-tooltip.el-popper)') &&
    source.includes('border: 1px solid #98a2b3') &&
    source.includes('box-shadow: 0 16px 36px') &&
    source.includes(':global(.object-property-popover-fade-enter-active)') &&
    source.includes('translateY(6px) scale(0.98)') &&
    source.includes('max-height: min(420px, calc(100vh - 120px))'),
  'object property hover popover should have contrast, motion, and bounded scrolling for large records',
)

assert.ok(
  source.includes('role="button" tabindex="0" aria-label="查看完整属性"') &&
    source.includes('class="object-property-preview-heading"') &&
    source.includes('class="instance-toolbar-context"') &&
    source.includes('class="instance-toolbar-actions"') &&
    source.includes('class="activity-primary-cell"') &&
    source.includes('compact-audit-list') &&
    source.includes('compact-state-list'),
  'object instances and decision activities should provide keyboard-aware previews and compact primary/secondary information layers',
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
