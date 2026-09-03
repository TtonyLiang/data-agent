import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const appSource = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
const routerSource = readFileSync(new URL('../router/index.ts', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../api/index.ts', import.meta.url), 'utf8')
const modelSource = readFileSync(new URL('./EnterpriseModelCenter.vue', import.meta.url), 'utf8')
const twinSource = readFileSync(new URL('./TwinRuntimeCenter.vue', import.meta.url), 'utf8')
const capabilitySource = readFileSync(new URL('./CapabilityPublishCenter.vue', import.meta.url), 'utf8')
const agentSource = readFileSync(new URL('./AgentList.vue', import.meta.url), 'utf8')

assert.ok(
  appSource.includes('企业本体数字孪生与智能决策平台') &&
    appSource.includes('index="/enterprise-model"') &&
    appSource.includes('index="/twin-runtime"') &&
    appSource.includes('index="/capability-center"'),
  'primary navigation should expose the platform foundation instead of separate ontology and semantic entries',
)

assert.ok(
  routerSource.includes("path: '/enterprise-model'") &&
    routerSource.includes("path: '/twin-runtime'") &&
    routerSource.includes("path: '/capability-center'") &&
    routerSource.includes("path: '/knowledge', redirect:") &&
    routerSource.includes("path: '/ontology', redirect:"),
  'platform center routes and legacy entry redirects should remain available',
)

assert.ok(
  modelSource.includes('企业模型') &&
    modelSource.includes('业务本体') &&
    modelSource.includes('语义与数据') &&
    modelSource.includes('企业空间') &&
    modelSource.includes('企业资产统一归属') &&
    modelSource.includes("route.query.section === 'semantic'") &&
    modelSource.includes('<span v-if="canManage" class="section-connector"') &&
    modelSource.includes('<button\n          v-if="canManage"\n          type="button"\n          :class="{ active: activeSection === \'semantic\' }"'),
  'enterprise model should combine ontology and semantic data under a workspace-aware entry',
)

assert.ok(
  twinSource.includes('把业务数据库中的记录同步成可识别、可关联、可追踪的企业对象') &&
    twinSource.includes('syncOntologyObjects') &&
    twinSource.includes('同步一页') &&
    twinSource.includes('当前页面是手动运行入口，不表示已经接入 CDC 或自动调度') &&
    twinSource.includes('对象身份合并与状态历史'),
  'twin runtime should expose real manual synchronization and state its current limits',
)

assert.ok(
  capabilitySource.includes('能力发布中心') &&
    capabilitySource.includes('fetchOntologyQueryCapabilities') &&
    capabilitySource.includes('fetchOntologyAgentContext') &&
    capabilitySource.includes('只读查询能力') &&
    capabilitySource.includes('受控动作能力') &&
    capabilitySource.includes('Agent 调用接口') &&
    capabilitySource.includes('权限与结果脱敏生效') &&
    capabilitySource.includes('独立能力版本、灰度发布和调用监控仍属于下一阶段'),
  'capability center should publish the actual query, action, and tool contracts exposed by the backend',
)

assert.ok(
  apiSource.includes("'/workspaces'") &&
    apiSource.includes('/agent/${agentId}/domain-ids') &&
    apiSource.includes('/ontology/domains/${domainId}/query-capabilities'),
  'frontend API should expose workspaces, agent-domain consumption, and query capability contracts',
)

assert.ok(
  agentSource.includes('<h2>应用智能体</h2>') &&
    agentSource.includes('智能体是企业模型能力的消费者') &&
    agentSource.includes('v-model="form.semantic_domain_ids"') &&
    agentSource.includes('可消费的业务领域') &&
    agentSource.includes('企业模型与业务领域资产会保留'),
  'agent management should present agents as consumers and support multiple business domains',
)
