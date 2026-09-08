import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./DatasourceConfig.vue', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../api/index.ts', import.meta.url), 'utf8')

assert.ok(
  source.includes('访问权限') &&
    source.includes('openPermissionDrawer') &&
    source.includes('验证权限适配（过渡）') &&
    source.includes('permissionEligibleAgents') &&
    source.includes('fetchAgentDatasourceIds') &&
    source.includes('表白名单强制生效') &&
    source.includes('saveDatasourcePermissions'),
  'datasource management should select the transitional permission adapter only inside the permission editor',
)

assert.ok(
  !source.includes('placeholder="初始关联智能体"') &&
    source.includes('agent_id: null as number | null') &&
    source.includes('agent_id: null,') &&
    !source.includes('form.value.agent_id = agentId.value'),
  'datasource creation should remain independent from validation Agent configuration',
)

assert.ok(
  source.includes('平台管理 > 调试与验证智能体') &&
    source.includes('数据源绑定仍在“调试与验证智能体”中维护'),
  'missing permission adapters should direct administrators to the correct binding surface',
)

assert.ok(
  source.includes('未勾选和后续新接入的表默认不可访问') &&
    source.includes('新接入的表默认不可访问') &&
    source.includes('完全隐藏') &&
    source.includes('部分隐藏') &&
    source.includes('哈希处理'),
  'the permission editor should explain table defaults and expose masking choices',
)

assert.ok(
  apiSource.includes('fetchDatasourcePermissions') &&
    apiSource.includes('updateDatasourcePermissions') &&
    apiSource.includes('/permissions/${agentId}'),
  'frontend API should expose read and replacement operations for datasource permissions',
)
