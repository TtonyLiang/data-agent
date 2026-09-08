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
const objectDialogSource = sourceSection('<el-dialog v-model="objectTypeDialog"', '<el-dialog v-model="linkTypeDialog"')
const linkDialogSource = sourceSection('<el-dialog v-model="linkTypeDialog"', '<el-dialog v-model="actionTypeDialog"')
const actionDialogSource = sourceSection('<el-dialog v-model="actionTypeDialog"', '<el-drawer v-model="validationDrawer"')
const linkSaveSource = sourceSection('async function saveLinkType()', 'async function removeLinkType')
const actionOpenSource = sourceSection('function openActionTypeDialog', 'function addActionParameter')
const actionSaveSource = sourceSection('async function saveActionType()', 'async function removeActionType')

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
  source.includes('function actionParameterHasInput') &&
    actionSaveSource.includes('if (!actionParameterHasInput(parameter)) continue') &&
    actionSaveSource.includes('请填写第 ${index + 1} 个动作参数的业务名称，或删除该行') &&
    actionSaveSource.includes("cleanText(parameter.parameter_key) || generatedKey('parameter'") &&
    actionSaveSource.includes('动作参数标识不能重复') &&
    actionSaveSource.includes('const parameters: any[] = []'),
  'action saving should ignore untouched blank rows, generate technical parameter keys, and validate configured parameters',
)

assert.ok(
  source.includes('function validationIssueMessage') &&
    source.includes('function validationFieldLabel') &&
    source.includes('Array.isArray(detail)') &&
    source.includes("item.type === 'string_pattern_mismatch'") &&
    source.includes("messages.slice(0, 3).join('；')"),
  'ontology API validation arrays should be rendered as readable field-level messages instead of object strings',
)

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
  source.includes('label="从业务库同步"') &&
    source.includes('label="单次读取上限"') &&
    source.includes('label="只读同步 SELECT（技术配置）"') &&
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
  objectDialogSource.includes('建议按顺序配置') &&
    objectDialogSource.includes('先确认业务含义，再完成技术映射') &&
    objectDialogSource.includes('业务人员确认') &&
    objectDialogSource.includes('管理员或数据工程师配置') &&
    objectDialogSource.indexOf('id="object-business-title"') < objectDialogSource.indexOf('id="object-property-title"') &&
    objectDialogSource.indexOf('id="object-property-title"') < objectDialogSource.indexOf('id="object-mapping-title"'),
  'object creation should separate business definition, object identity, and technical mapping in that order',
)

assert.ok(
  objectDialogSource.indexOf('对象属性') < objectDialogSource.indexOf('对象唯一标识属性（主属性）') &&
    objectDialogSource.includes(':disabled="objectPropertyOptions.length === 0"') &&
    objectDialogSource.includes('请先填写上方的属性标识') &&
    source.includes('const objectPropertyOptions = computed<OntologyProperty[]>') &&
    source.includes('function propertyOptionLabel') &&
    source.includes("if (removed?.property_key === objectTypeForm.primary_property) objectTypeForm.primary_property = ''"),
  'object properties should be defined before choosing stable identity and display fields',
)

assert.ok(
  objectDialogSource.includes('当前版本采用只读 SQL 映射') &&
    objectDialogSource.includes('AS 属性标识') &&
    objectDialogSource.includes('保存时只校验和记录配置，不执行同步') &&
    objectDialogSource.includes('再到“孪生运行”先预览、后执行') &&
    objectDialogSource.includes('保存只记录对象模型，不会直接读取或写入业务数据库'),
  'technical mapping should explain ownership and keep model saving separate from runtime synchronization',
)

assert.ok(
  linkDialogSource.includes('先定义业务关系，再处理技术关联') &&
    linkDialogSource.indexOf('关系名称') < linkDialogSource.indexOf('高级技术配置（通常无需修改）') &&
    linkDialogSource.includes('默认技术关联') &&
    linkDialogSource.includes('relationMappingSummary') &&
    linkDialogSource.includes('默认使用两端对象的唯一标识属性') &&
    linkDialogSource.includes('供 API、版本和能力引用，通常不需要业务人员填写'),
  'relationship creation should lead with business meaning and explain the automatically inferred primary-property mapping',
)

assert.ok(
  linkSaveSource.includes('source_property_keys: sourcePropertyKeys.length ? sourcePropertyKeys : null') &&
    linkSaveSource.includes('target_property_keys: targetPropertyKeys.length ? targetPropertyKeys : null') &&
    linkSaveSource.includes('复合关系两端的关联属性数量必须一致') &&
    linkDialogSource.includes('顺序必须与终点一致') &&
    linkSaveSource.includes("generatedKey('relation'") &&
    linkSaveSource.includes('关系标识需以英文字母开头') &&
    source.includes('const relationMappingSummary = computed'),
  'relationship saving should preserve compound keys, validate both sides, and auto-generate a stable technical key',
)

assert.ok(
  actionDialogSource.includes('先表达业务意图和状态变化') &&
    actionDialogSource.indexOf('动作名称') < actionDialogSource.indexOf('高级执行与治理配置') &&
    actionDialogSource.includes('业务状态变化（可选）') &&
    actionDialogSource.includes('保存时自动转换为动作的状态前置条件和状态效果') &&
    actionDialogSource.includes('只有 Agent 或业务应用需要提供的输入才添加') &&
    actionDialogSource.includes('技术标识（留空自动生成）') &&
    actionDialogSource.includes('供平台管理员配置权限、复杂条件和执行效果'),
  'action creation should expose intent, state transition, and business inputs before folded governance and execution DSL settings',
)

assert.ok(
  actionOpenSource.includes('preconditions.splice(statusConditionIndex, 1)') &&
    actionOpenSource.includes('effects.splice(statusEffectIndex, 1)') &&
    source.includes('function resetActionPropertyBindings') &&
    actionSaveSource.includes("generatedKey('action'") &&
    actionSaveSource.includes("if (!statusProperty && (fromStatus || toStatus))") &&
    actionSaveSource.includes('preconditions.unshift') &&
    actionSaveSource.includes('effects.unshift') &&
    actionSaveSource.includes('id: actionTypeForm.id') &&
    !actionSaveSource.includes('...actionTypeForm'),
  'action editing and saving should round-trip the simplified state transition into the existing backend payload without UI-only fields',
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
