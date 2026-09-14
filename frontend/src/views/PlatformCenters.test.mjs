import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const appSource = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
const routerSource = readFileSync(new URL('../router/index.ts', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../api/index.ts', import.meta.url), 'utf8')
const modelSource = readFileSync(new URL('./EnterpriseModelCenter.vue', import.meta.url), 'utf8')
const releaseSource = readFileSync(new URL('./ModelReleaseCenter.vue', import.meta.url), 'utf8')
const twinSource = readFileSync(new URL('./TwinRuntimeCenter.vue', import.meta.url), 'utf8')
const capabilitySource = readFileSync(new URL('./CapabilityPublishCenter.vue', import.meta.url), 'utf8')
const agentSource = readFileSync(new URL('./AgentList.vue', import.meta.url), 'utf8')

assert.equal((twinSource.match(/fetchTwinSyncRuns,/g) || []).length, 1)
assert.equal(
  (twinSource.match(/JSON\.stringify\(oldValues\[key\]\) !== JSON\.stringify\(newValues\[key\]\)/g) || []).length,
  1,
)

assert.ok(
  appSource.includes('企业本体数字孪生与智能决策平台') &&
    appSource.includes('index="/enterprise-model"') &&
    appSource.includes('index="/twin-runtime"') &&
    appSource.includes('index="/capability-center"') &&
    appSource.includes('index="validation-apps"') &&
    appSource.includes('对话验证') &&
    appSource.includes('风险交付验证') &&
    appSource.includes('index="platform-management"') &&
    appSource.includes('调试与验证智能体'),
  'primary navigation should expose the platform foundation instead of separate ontology and semantic entries',
)

assert.ok(
  routerSource.includes("path: '/', redirect: '/enterprise-model'") &&
    routerSource.includes("path: '/chat'") &&
    routerSource.includes("path: '/enterprise-model'") &&
    routerSource.includes("path: '/twin-runtime'") &&
    routerSource.includes("path: '/capability-center'") &&
    routerSource.includes("path: '/knowledge', redirect:") &&
    routerSource.includes("path: '/ontology', redirect:") &&
    routerSource.includes("path: '/register', redirect: '/login'") &&
    routerSource.includes("return { path: '/enterprise-model' }") &&
    appSource.includes('index="/chat"') &&
    appSource.includes("activateRoute('/chat')") &&
    !appSource.includes("activateRoute('/')"),
  'root path should open the enterprise model, with chat remaining a validation client',
)

assert.ok(
  modelSource.includes('企业模型') &&
    modelSource.includes('围绕业务对象完成建模、数据绑定和版本发布') &&
    modelSource.includes('v-model="domainId"') &&
    modelSource.includes('新建领域') &&
    modelSource.includes('领域管理') &&
    modelSource.includes('upsertSemanticDomain') &&
    modelSource.includes('业务模型') &&
    modelSource.includes('数据绑定') &&
    modelSource.includes('校验发布') &&
    modelSource.includes('v-if="canConfigureData"') &&
    modelSource.includes('const canConfigureData = computed(() => isTechnicalUser())') &&
    modelSource.includes("import { canEditModel, isTechnicalUser } from '../stores/auth'") &&
    modelSource.includes('业务对象与动作') &&
    modelSource.includes('指标与业务规则') &&
    modelSource.includes('class="business-model-switch-heading"') &&
    modelSource.includes('当前工作区') &&
    modelSource.includes('class="business-model-switch-options"') &&
    modelSource.includes('business-model-tab-index') &&
    modelSource.includes('business-model-tab-indicator') &&
    modelSource.includes('定义对象、关系、状态与动作') &&
    modelSource.includes('维护指标口径、阈值与业务判断') &&
    modelSource.includes('mode="business"') &&
    modelSource.includes('mode="binding"') &&
    modelSource.includes('ModelReleaseCenter') &&
    modelSource.includes('复制企业模型') &&
    modelSource.includes('导入企业模型包') &&
    modelSource.includes('导出企业模型包') &&
    modelSource.includes('exportOntologyBundle') &&
    modelSource.includes('importOntologyBundle') &&
    modelSource.includes("format: 'wenqu-enterprise-model'") &&
    modelSource.includes('运行实例、发布版本和审计记录不会复制') &&
    !modelSource.includes('此操作复制语义资产，不复制业务本体') &&
    modelSource.includes(':aria-busy="domainLoading"') &&
    modelSource.includes('aria-label="选择业务领域"') &&
    modelSource.includes('<section class="model-center-workspace" aria-label="企业模型工作区">') &&
    modelSource.includes('tabindex="-1"') &&
    modelSource.includes('aria-hidden="true"') &&
    modelSource.includes('@opened="focusDomainName"') &&
    modelSource.includes('ref="domainNameInput"') &&
    modelSource.includes('domainNameInput.value?.focus()') &&
    !modelSource.includes('更多领域操作') &&
    !modelSource.includes('domain-index') &&
    !modelSource.includes('section-index') &&
    !modelSource.includes('section-connector') &&
    !modelSource.includes('model-center-outcome') &&
    !modelSource.includes('企业空间') &&
    !modelSource.includes('默认企业空间') &&
    !modelSource.includes('fetchEnterpriseWorkspaces') &&
    !modelSource.includes('fetchWorkspaceDomains') &&
    modelSource.includes("route.query.section === 'semantic' || route.query.section === 'release'") &&
    modelSource.includes(':domain-id="domainId"') &&
    modelSource.includes(':current-domain="currentDomain"'),
  'enterprise model should expose concise domain management before its three modeling steps',
)

assert.ok(
  releaseSource.includes('校验发布与企业模型版本') &&
    releaseSource.includes('defineProps') &&
    !releaseSource.includes('fetchAllSemanticDomains') &&
    releaseSource.includes('创建统一版本') &&
    releaseSource.includes('业务语义校验') &&
    releaseSource.includes('查询运行时检查') &&
    releaseSource.includes('创建语义快照') &&
    releaseSource.includes('更新验证检索索引') &&
    releaseSource.includes('buildSemanticRuntime') &&
    releaseSource.includes('syncSemanticVector') &&
    releaseSource.includes('validateEnterpriseModelRelease') &&
    releaseSource.includes('activateEnterpriseModelRelease') &&
    releaseSource.includes('rollbackEnterpriseModelRelease') &&
    releaseSource.includes('v-if="canPublishModelRole"') &&
    releaseSource.includes('handleRollbackSnapshot') &&
    !releaseSource.includes(':disabled="!canEditModelRole" @click="handleRollbackSnapshot') &&
    apiSource.includes('/model-releases/domains/${domainId}/releases'),
  'enterprise model should expose one lifecycle for binding, validating, activating, and rolling back releases',
)

assert.ok(
  twinSource.includes('把业务数据库中的记录同步成可识别、可关联、可追踪的企业对象') &&
    twinSource.includes(':aria-busy="loading"') &&
    twinSource.includes('aria-label="选择业务领域"') &&
    twinSource.includes('const loading = ref(true)') &&
    twinSource.includes('if (!domainId.value) loading.value = false') &&
    twinSource.includes('createTwinSyncRun') &&
    twinSource.includes('fetchTwinSyncRuns') &&
    twinSource.includes('最近同步记录') &&
    twinSource.includes('预览不会写入对象') &&
    twinSource.includes(':scrollbar-tabindex="-1"') &&
    twinSource.includes('activeModelRelease') &&
    twinSource.includes('runtimeError') &&
    twinSource.includes('去企业模型校验发布') &&
    twinSource.includes('只有技术人员可以执行写入型同步') &&
    twinSource.includes('当前领域没有激活的统一企业模型版本') &&
    twinSource.includes('当前页面是手动运行入口，不表示已经接入 CDC 或自动调度') &&
    twinSource.includes('对象身份合并与状态历史'),
  'twin runtime should expose real manual synchronization without an unnamed scrollbar stop and state its current limits',
)

assert.ok(
  twinSource.includes('<el-tab-pane label="对象实例" name="instances">') &&
    twinSource.includes('<el-tab-pane label="关系实例" name="links">') &&
    twinSource.includes('<el-tab-pane label="动作执行记录" name="audit">') &&
    twinSource.includes('fetchOntologyObjects') &&
    twinSource.includes('fetchOntologyLinks') &&
    twinSource.includes('fetchOntologyActionRuns') &&
    twinSource.includes('executeOntologyAction') &&
    twinSource.includes('平台动作记录') &&
    twinSource.includes('当前属于平台叠加状态，不代表业务数据库已经写回') &&
    twinSource.includes('业务库快照 + 平台变更') &&
    twinSource.includes('尚未写回业务库') &&
    twinSource.includes('function objectStateSourceLabel') &&
    twinSource.includes('不代表通用 Decision Capability 已完成'),
  'twin runtime should own runtime records without overstating a generic decision capability',
)

assert.ok(
  twinSource.includes('queryOntologyObjects') &&
    twinSource.includes('const instancePageSize = ref(50)') &&
    twinSource.includes('limit: pageSize') &&
    twinSource.includes('offset,') &&
    twinSource.includes('v-model:current-page="instancePage"') &&
    twinSource.includes('v-model:page-size="instancePageSize"') &&
    twinSource.includes('@current-change="handleInstancePageChange"') &&
    twinSource.includes('@size-change="handleInstancePageSizeChange"') &&
    twinSource.includes('const INSTANCE_CHOICE_LIMIT = 200') &&
    twinSource.includes('fetchOntologyObjects(') &&
    twinSource.includes('{ strictRelease: true }') &&
    !twinSource.includes('fetchOntologyObjects(domainId.value!, typeId, 1000, 0)'),
  'object instances should use server-side pagination while auxiliary choices remain bounded',
)

assert.ok(
  twinSource.includes('const PROPERTY_PREVIEW_LIMIT = 2') &&
    twinSource.includes('class="immutable-property-field"') &&
    twinSource.includes('对象身份 · 只读') &&
    twinSource.includes('用于同步、去重和关系定位；编辑时不可修改。') &&
    twinSource.includes('对象主标识') &&
    twinSource.includes('role="note"') &&
    twinSource.includes('function objectPropertyValue') &&
    twinSource.includes('function isEditingObjectIdentity') &&
    twinSource.includes('objectPropertyPreview(row.properties)') &&
    twinSource.includes('popper-class="object-property-tooltip"') &&
    twinSource.includes('role="note"') &&
    twinSource.includes(':aria-label="objectPropertyAriaLabel(row.properties)"') &&
    twinSource.includes('function objectPropertyAriaLabel') &&
    twinSource.includes(':role="row.sync_enabled && activeModelRelease ? undefined : \'note\'"') &&
    twinSource.includes(':aria-label="row.sync_enabled && activeModelRelease ? undefined : syncActionHint(row, true)"') &&
    twinSource.includes('@opened="focusControl(objectTypeSelect)"') &&
    twinSource.includes('@opened="focusControl(linkTypeSelect)"') &&
    twinSource.includes('@opened="focusControl(actionTypeSelect)"') &&
    twinSource.includes('requestAnimationFrame(() => control?.focus())') &&
    twinSource.includes('object-property-tooltip-list') &&
    twinSource.includes('decisionContextEntries(row.decision_context)') &&
    twinSource.includes('stateChangeEntries(row.before_state, row.after_state)') &&
    twinSource.includes('compact-audit-list') &&
    twinSource.includes('compact-state-list') &&
    twinSource.includes('state-value is-after') &&
    twinSource.includes('@media (prefers-reduced-motion: reduce)') &&
    !twinSource.includes('formatJson(row.properties)') &&
    !twinSource.includes('formatStateChange(row)'),
  'runtime attributes and action records should retain structured previews, full hover details, and accessible motion behavior',
)

assert.ok(
  (twinSource.match(/class="runtime-table-viewport"/g) || []).length >= 5 &&
    twinSource.includes('.runtime-table-viewport {') &&
    twinSource.includes('overflow-x: auto;') &&
    twinSource.includes('.runtime-table-viewport :deep(.el-table__inner-wrapper)') &&
    twinSource.includes('height: auto;') &&
    twinSource.includes('.runtime-table-panel {') &&
    twinSource.includes('.sync-history-panel {') &&
    twinSource.includes('.runtime-entity-panel {') &&
    twinSource.includes('overflow: visible;'),
  'twin runtime tables should keep their natural bottom edge visible and delegate horizontal scrolling to a dedicated viewport',
)

assert.ok(
  twinSource.includes('class="object-property-preview-items"') &&
    twinSource.includes('class="audit-field-row object-property-preview-row"') &&
    twinSource.includes('min-height: 34px;') &&
    twinSource.includes('object-property-tooltip-list') &&
    twinSource.includes('const PROPERTY_PREVIEW_LIMIT = 2'),
  'object instance properties should use a compact inline preview while keeping the complete property list in the tooltip',
)

assert.ok(
  twinSource.includes('class="relation-endpoint"') &&
    twinSource.includes('class="relation-endpoint-role">起点</span>') &&
    twinSource.includes('class="relation-endpoint-role">终点</span>') &&
    twinSource.includes('relationIdentifier(row.source_primary_value)') &&
    twinSource.includes('relationIdentifier(row.target_primary_value)') &&
    twinSource.includes('class="relation-endpoint-id"') &&
    twinSource.includes('.relation-endpoint-id {') &&
    twinSource.includes('text-overflow: ellipsis;'),
  'relation endpoints should separate source and target labels and expose full long identifiers through tooltip text',
)

assert.ok(
  capabilitySource.includes('能力发布中心') &&
    capabilitySource.includes(':aria-busy="loading"') &&
    capabilitySource.includes('aria-label="选择业务领域"') &&
    capabilitySource.includes('const loading = ref(true)') &&
    capabilitySource.includes('if (!domainId.value) loading.value = false') &&
    capabilitySource.includes('fetchOntologyQueryCapabilities') &&
    capabilitySource.includes('fetchOntologyAgentContext') &&
    capabilitySource.includes('外部只读 Query 能力') &&
    capabilitySource.includes('内部受控动作验证') &&
    capabilitySource.includes('内部 Agent 验证工具') &&
    capabilitySource.includes('外部 Agent') &&
    capabilitySource.includes('Action 尚未作为外部能力发布') &&
    capabilitySource.includes('权限与结果脱敏生效') &&
    capabilitySource.includes('第三方调用方') &&
    capabilitySource.includes('Client Secret 只展示本次') &&
    capabilitySource.includes('能力调用审计') &&
    capabilitySource.includes('fetchCapabilityInvocationAudits') &&
    capabilitySource.includes('activeModelRelease') &&
    capabilitySource.includes('POST /api/v1/capabilities/${capability.key}:invoke') &&
    capabilitySource.includes('GET /api/v1/capabilities?domain_id=') &&
    capabilitySource.includes('业务词典') &&
    capabilitySource.includes('不必复制内置验证智能体的提示词') &&
    capabilitySource.includes('完整约定 JSON') &&
    capabilitySource.includes('X-Capability-Key 与 X-Capability-Secret') &&
    capabilitySource.includes('业务领域权限') &&
    capabilitySource.includes('旧权限兼容适配') &&
    capabilitySource.includes('数据源、表和字段权限由平台按业务领域自动适配') &&
    capabilitySource.includes('无需选择或创建内部验证 Agent') &&
    capabilitySource.includes('授权约定') &&
    capabilitySource.includes('grant-summary-text') &&
    capabilitySource.includes('activeGrantPreview') &&
    capabilitySource.includes('未授权') &&
    capabilitySource.includes('首次调用时兼容绑定') &&
    !capabilitySource.includes('grantForm.execution_agent_id') &&
    !capabilitySource.includes('fetchAgents') &&
    capabilitySource.includes("query: { section: 'release' }") &&
    capabilitySource.includes('独立能力版本、灰度与配额治理仍属于后续建设'),
  'capability center should publish the actual query, action, and tool contracts exposed by the backend',
)

assert.ok(
  capabilitySource.includes(':aria-label="`查看 Query 能力约定：${row.name}`"') &&
    capabilitySource.includes(':aria-label="`查看内部动作约定：${row.name}`"') &&
    capabilitySource.includes(':aria-label="`管理调用方授权：${row.name}`"') &&
    capabilitySource.includes(':aria-label="`撤销能力授权：${row.capability_key}`"') &&
    capabilitySource.includes('@opened="focusControl(clientNameInput)"') &&
    capabilitySource.includes('@opened="focusControl(copyCredentialButton)"') &&
    capabilitySource.includes('@opened="focusControl(grantCapabilitySelect)"') &&
    capabilitySource.includes('requestAnimationFrame(() => control?.focus())'),
  'capability table actions and dialogs should expose contextual keyboard labels and predictable initial focus',
)

assert.ok(
  capabilitySource.includes('class="capability-content"') &&
    capabilitySource.includes('border height="100%" class="capability-table"') &&
    capabilitySource.includes('.capability-content {') &&
    capabilitySource.includes('.capability-surface :deep(.el-tabs__content)') &&
    capabilitySource.includes('overflow: hidden;'),
  'capability tables should scroll inside the remaining workbench height without clipping the final row',
)

assert.ok(
  capabilitySource.includes('.grant-toolbar {') &&
    capabilitySource.includes('justify-content: flex-start;') &&
    capabilitySource.includes('.grant-toolbar > .el-button {') &&
    capabilitySource.includes('margin-left: 4px;'),
  'grant drawer action should align with the Client Key content instead of being pushed to the far right',
)

assert.ok(
  capabilitySource.includes('class="grant-table"') &&
    capabilitySource.includes('table-layout="fixed"') &&
    capabilitySource.includes('class-name="grant-action-column"') &&
    capabilitySource.includes('label="操作" width="72"') &&
    capabilitySource.includes('.grant-table {') &&
    capabilitySource.includes('min-width: 0;'),
  'grant drawer table should fit the drawer width so revoke stays visible without horizontal scrolling',
)

assert.ok(
  apiSource.includes('/agent/${agentId}/domain-ids') &&
    apiSource.includes('/ontology/domains/${domainId}/query-capabilities') &&
    apiSource.includes("'/capability-clients'") &&
    apiSource.includes("'/capability-invocations'"),
  'frontend API should expose model consumption and external capability access contracts',
)

assert.ok(
  agentSource.includes('<h2>调试与验证智能体</h2>') &&
    agentSource.includes('只用于验收平台能力是否达标') &&
    agentSource.includes('第三方 Agent 应得到同样的业务结果') &&
    agentSource.includes('v-model="form.semantic_domain_ids"') &&
    agentSource.includes('可消费的业务领域') &&
    agentSource.includes('企业模型与业务领域资产会保留'),
  'agent management should present agents as consumers and support multiple business domains',
)
