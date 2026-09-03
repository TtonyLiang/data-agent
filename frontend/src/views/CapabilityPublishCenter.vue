<template>
  <div class="page-shell capability-page" v-loading="loading">
    <header class="page-header">
      <div>
        <h2>能力发布中心</h2>
        <p>把企业模型转换成边界清晰、可被 Agent 和业务应用调用的标准能力。</p>
      </div>
      <div class="header-actions">
        <el-select v-model="domainId" class="domain-select" placeholder="选择业务领域">
          <el-option
            v-for="domain in domains"
            :key="domain.id"
            :label="`${domain.name} · ${domain.domain_key}`"
            :value="domain.id"
          />
        </el-select>
        <el-button :disabled="!domainId" @click="loadCapabilities">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
        <el-button v-if="canManage" type="primary" @click="openModelRelease">模型发布</el-button>
      </div>
    </header>

    <el-empty v-if="!loading && domains.length === 0" description="暂无可用业务领域" />

    <template v-else-if="currentDomain">
      <section class="publish-chain" aria-label="能力发布链路">
        <div>
          <span>企业模型</span>
          <strong>对象、指标、规则与动作</strong>
        </div>
        <i aria-hidden="true">→</i>
        <div>
          <span>能力合同</span>
          <strong>输入、输出、权限与版本</strong>
        </div>
        <i aria-hidden="true">→</i>
        <div>
          <span>能力消费者</span>
          <strong>垂直 Agent 与业务应用</strong>
        </div>
      </section>

      <section class="capability-summary">
        <div>
          <span>当前模型版本</span>
          <strong>{{ releaseVersion }}</strong>
          <small>{{ releaseName }}</small>
        </div>
        <div>
          <span>只读查询能力</span>
          <strong>{{ queryCapabilities.length }}</strong>
          <small>确定性编译与受控执行</small>
        </div>
        <div>
          <span>业务动作能力</span>
          <strong>{{ actions.length }}</strong>
          <small>按当前角色过滤</small>
        </div>
        <div>
          <span>标准调用工具</span>
          <strong>{{ tools.length }}</strong>
          <small>对象查询 / 业务查询 / 动作</small>
        </div>
      </section>

      <el-alert
        v-if="!summary?.latest_release"
        class="publish-alert"
        type="warning"
        :closable="false"
        title="当前领域尚未发布本体版本；可以检查能力合同，但动作执行需要先发布模型。"
      />

      <section class="capability-surface">
        <el-tabs v-model="activeTab">
          <el-tab-pane :label="`查询能力 ${queryCapabilities.length}`" name="queries">
            <div class="tab-heading">
              <div>
                <h3>只读查询能力</h3>
                <p>由本体对象与明确绑定的语义指标生成，不允许越过已声明的指标和维度。</p>
              </div>
            </div>
            <el-table v-if="queryCapabilities.length" :data="queryCapabilities" border class="capability-table">
              <el-table-column label="能力" min-width="230">
                <template #default="{ row }">
                  <div class="primary-cell">
                    <strong>{{ row.name }}</strong>
                    <code>{{ row.key }}</code>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="目标对象" min-width="150">
                <template #default="{ row }"><code>{{ row.target_object }}</code></template>
              </el-table-column>
              <el-table-column label="支持范围" min-width="320">
                <template #default="{ row }">
                  <div class="scope-cell">
                    <span><b>{{ row.supported_metrics.length }}</b> 个指标</span>
                    <span><b>{{ row.supported_dimensions.length }}</b> 个维度</span>
                    <span>最多 <b>{{ row.execution.max_limit }}</b> 行</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="安全边界" min-width="170">
                <template #default>
                  <el-tag type="success" effect="plain">只读</el-tag>
                  <span class="cell-note">权限与结果脱敏生效</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="110" fixed="right" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" @click="showQueryContract(row)">查看合同</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无查询能力：请先为本体对象绑定语义指标和维度" />
          </el-tab-pane>

          <el-tab-pane :label="`动作能力 ${actions.length}`" name="actions">
            <div class="tab-heading">
              <div>
                <h3>受控动作能力</h3>
                <p>只展示当前角色可见的生效动作；执行时仍会校验角色、对象版本、前置条件与审批单号。</p>
              </div>
            </div>
            <el-table v-if="actions.length" :data="actions" border class="capability-table">
              <el-table-column label="动作" min-width="230">
                <template #default="{ row }">
                  <div class="primary-cell">
                    <strong>{{ row.name }}</strong>
                    <code>{{ row.action_key }}</code>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="目标对象" min-width="170">
                <template #default="{ row }"><code>{{ row.target_object_key }}</code></template>
              </el-table-column>
              <el-table-column label="合同组成" min-width="260">
                <template #default="{ row }">
                  <div class="scope-cell">
                    <span><b>{{ row.parameters?.length || 0 }}</b> 个参数</span>
                    <span><b>{{ row.preconditions?.length || 0 }}</b> 个前置条件</span>
                    <span><b>{{ row.effects?.length || 0 }}</b> 个状态效果</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="执行边界" min-width="180">
                <template #default="{ row }">
                  <el-tag :type="row.requires_approval ? 'warning' : 'info'" effect="plain">
                    {{ row.requires_approval ? '需审批单号' : '无需审批单号' }}
                  </el-tag>
                  <span class="cell-note">始终执行权限与条件校验</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="110" fixed="right" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" @click="showActionContract(row)">查看合同</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="当前角色没有可调用的生效动作" />
          </el-tab-pane>

          <el-tab-pane :label="`调用接口 ${tools.length}`" name="tools">
            <div class="tab-heading">
              <div>
                <h3>Agent 调用接口</h3>
                <p>Agent 通过稳定工具调用平台能力，不需要自行猜测数据库表和字段。</p>
              </div>
            </div>
            <div class="tool-list">
              <article v-for="tool in tools" :key="tool.name">
                <div>
                  <strong>{{ toolLabel(tool.name) }}</strong>
                  <code>{{ tool.name }}</code>
                </div>
                <p>{{ tool.description }}</p>
                <el-button text type="primary" @click="showToolContract(tool)">查看参数</el-button>
              </article>
            </div>
          </el-tab-pane>
        </el-tabs>
      </section>

      <el-alert
        class="version-boundary"
        type="info"
        :closable="false"
        title="第一版能力随企业模型生效；独立能力版本、灰度发布和调用监控仍属于下一阶段。"
      />
    </template>

    <el-drawer v-model="contractVisible" title="能力调用合同" size="560px" append-to-body>
      <div v-if="selectedContract" class="contract-detail">
        <div class="contract-identity">
          <span>{{ selectedContract.kind }}</span>
          <strong>{{ selectedContract.name }}</strong>
          <code>{{ selectedContract.key }}</code>
        </div>
        <p v-if="selectedContract.description" class="contract-description">{{ selectedContract.description }}</p>
        <section>
          <h4>调用入口</h4>
          <code class="endpoint">POST /api/ontology/domains/{{ domainId }}/agent-tools/{{ selectedContract.tool }}</code>
        </section>
        <section>
          <h4>请求示例</h4>
          <pre>{{ JSON.stringify(selectedContract.example, null, 2) }}</pre>
        </section>
        <section>
          <h4>完整合同</h4>
          <pre>{{ JSON.stringify(selectedContract.raw, null, 2) }}</pre>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  fetchOntologyAgentContext,
  fetchOntologyDomains,
  fetchOntologyQueryCapabilities,
  fetchOntologySummary,
  type OntologyAgentContext,
  type OntologyAgentToolDefinition,
  type OntologyQueryCapability,
  type OntologySummary,
  type SemanticDomain,
} from '../api'
import { isAdmin } from '../stores/auth'

interface ContractView {
  kind: string
  name: string
  key: string
  description: string
  tool: string
  example: Record<string, unknown>
  raw: Record<string, unknown>
}

const router = useRouter()
const domains = ref<SemanticDomain[]>([])
const domainId = ref<number | null>(null)
const summary = ref<OntologySummary | null>(null)
const context = ref<OntologyAgentContext | null>(null)
const queryCapabilities = ref<OntologyQueryCapability[]>([])
const activeTab = ref('queries')
const loading = ref(false)
const contractVisible = ref(false)
const selectedContract = ref<ContractView | null>(null)

const currentDomain = computed(() => domains.value.find((item) => item.id === domainId.value) || null)
const actions = computed(() => context.value?.actions || [])
const tools = computed(() => context.value?.tools || [])
const canManage = computed(() => isAdmin())
const releaseVersion = computed(() => summary.value?.latest_release ? `V${summary.value.latest_release.version}` : '未发布')
const releaseName = computed(() => summary.value?.latest_release?.name || '先校验并发布企业模型')

onMounted(async () => {
  try {
    domains.value = await fetchOntologyDomains()
    domainId.value = domains.value[0]?.id || null
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
})

watch(domainId, loadCapabilities)

async function loadCapabilities() {
  if (!domainId.value) {
    summary.value = null
    context.value = null
    queryCapabilities.value = []
    return
  }
  loading.value = true
  try {
    const [nextSummary, nextContext, nextQueries] = await Promise.all([
      fetchOntologySummary(domainId.value),
      fetchOntologyAgentContext(domainId.value),
      fetchOntologyQueryCapabilities(domainId.value),
    ])
    summary.value = nextSummary
    context.value = nextContext
    queryCapabilities.value = nextQueries
  } catch (error) {
    summary.value = null
    context.value = null
    queryCapabilities.value = []
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

function openModelRelease() {
  router.push({ path: '/enterprise-model', query: { section: 'ontology' } })
}

function showQueryContract(capability: OntologyQueryCapability) {
  const arguments_: Record<string, unknown> = { capability_key: capability.key }
  if (capability.supported_metrics[0]) arguments_.metrics = [capability.supported_metrics[0]]
  if (capability.supported_dimensions[0]) arguments_.dimensions = [capability.supported_dimensions[0]]
  selectedContract.value = {
    kind: '只读查询能力',
    name: capability.name,
    key: capability.key,
    description: capability.description || '',
    tool: 'ontology_query_capability',
    example: { arguments: arguments_ },
    raw: capability as unknown as Record<string, unknown>,
  }
  contractVisible.value = true
}

function showActionContract(action: Record<string, unknown>) {
  const actionKey = String(action.action_key || '')
  selectedContract.value = {
    kind: '受控动作能力',
    name: String(action.name || actionKey),
    key: actionKey,
    description: String(action.description || ''),
    tool: 'ontology_execute_action',
    example: {
      arguments: {
        action_key: actionKey,
        target_object_id: 123,
        parameters: {},
        decision_context: { source: 'vertical_agent' },
      },
    },
    raw: action,
  }
  contractVisible.value = true
}

function showToolContract(tool: OntologyAgentToolDefinition) {
  selectedContract.value = {
    kind: 'Agent 标准工具',
    name: toolLabel(tool.name),
    key: tool.name,
    description: tool.description,
    tool: tool.name,
    example: { arguments: {} },
    raw: tool as unknown as Record<string, unknown>,
  }
  contractVisible.value = true
}

function toolLabel(name: string) {
  return ({
    ontology_query_objects: '对象实例查询',
    ontology_query_capability: '业务指标查询',
    ontology_execute_action: '受控业务动作',
  } as Record<string, string>)[name] || name
}

function errorMessage(error: unknown) {
  const candidate = error as { response?: { data?: { detail?: string | { message?: string } } }; message?: string }
  const detail = candidate?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return candidate?.message || '能力列表加载失败'
}
</script>

<style scoped>
.capability-page {
  height: 100%;
  min-height: 0;
  overflow: auto;
}

.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
}

.header-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.domain-select {
  width: 280px;
}

.publish-chain {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 48px minmax(0, 1fr) 48px minmax(0, 1fr);
  align-items: center;
  margin-bottom: 16px;
  padding: 15px 18px;
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  box-shadow: var(--wq-shadow-sm);
}

.publish-chain > div {
  display: grid;
  gap: 3px;
}

.publish-chain span {
  color: var(--wq-primary-strong);
  font-size: 12px;
  font-weight: 700;
}

.publish-chain strong {
  color: var(--wq-text);
  font-size: 14px;
}

.publish-chain i {
  color: var(--wq-subtle);
  font-style: normal;
  text-align: center;
}

.capability-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 16px;
  overflow: hidden;
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  box-shadow: var(--wq-shadow-sm);
}

.capability-summary > div {
  min-width: 0;
  padding: 15px 18px;
  display: grid;
  gap: 4px;
  border-right: 1px solid var(--wq-border);
}

.capability-summary > div:last-child {
  border-right: 0;
}

.capability-summary span,
.capability-summary small {
  overflow: hidden;
  color: var(--wq-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.capability-summary strong {
  color: var(--wq-text);
  font-size: 22px;
  line-height: 1.25;
}

.publish-alert {
  margin-bottom: 16px;
}

.version-boundary {
  margin-top: 16px;
}

.capability-surface {
  min-height: 380px;
  padding: 0 16px 16px;
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  box-shadow: var(--wq-shadow-sm);
}

.tab-heading {
  min-height: 66px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.tab-heading h3 {
  color: var(--wq-text);
  font-size: 15px;
}

.tab-heading p {
  margin-top: 4px;
  color: var(--wq-muted);
  font-size: 12px;
}

.primary-cell {
  display: grid;
  gap: 4px;
}

.primary-cell code,
.capability-table code {
  width: fit-content;
  color: #31506f;
  font-size: 12px;
}

.scope-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.scope-cell span {
  padding: 3px 7px;
  color: var(--wq-muted);
  font-size: 12px;
  background: var(--wq-surface-soft);
  border: 1px solid var(--wq-border);
  border-radius: 6px;
}

.scope-cell b {
  color: var(--wq-text);
}

.cell-note {
  display: block;
  margin-top: 5px;
  color: var(--wq-muted);
  font-size: 12px;
}

.tool-list {
  display: grid;
  gap: 10px;
}

.tool-list article {
  min-height: 84px;
  padding: 14px;
  display: grid;
  grid-template-columns: minmax(220px, 0.75fr) minmax(0, 1.8fr) auto;
  align-items: center;
  gap: 18px;
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
}

.tool-list article > div {
  min-width: 0;
  display: grid;
  gap: 5px;
}

.tool-list code {
  overflow: hidden;
  color: #31506f;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-list p {
  color: var(--wq-muted);
  font-size: 13px;
  line-height: 1.6;
}

.contract-detail {
  display: grid;
  gap: 18px;
}

.contract-identity {
  padding: 14px;
  display: grid;
  gap: 5px;
  background: var(--wq-surface-soft);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
}

.contract-identity span {
  color: var(--wq-primary-strong);
  font-size: 12px;
  font-weight: 700;
}

.contract-identity strong {
  color: var(--wq-text);
  font-size: 17px;
}

.contract-identity code,
.endpoint {
  width: fit-content;
  max-width: 100%;
  overflow-wrap: anywhere;
  color: #31506f;
  font-size: 12px;
}

.contract-description {
  color: var(--wq-muted);
  line-height: 1.7;
}

.contract-detail section {
  display: grid;
  gap: 8px;
}

.contract-detail h4 {
  color: var(--wq-text);
  font-size: 14px;
}

.contract-detail pre {
  max-height: 300px;
  overflow: auto;
  padding: 12px;
  color: #d0d5dd;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  background: #182230;
  border-radius: var(--wq-radius);
}

@media (max-width: 980px) {
  .capability-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .capability-summary > div:nth-child(2) {
    border-right: 0;
  }

  .capability-summary > div:nth-child(-n + 2) {
    border-bottom: 1px solid var(--wq-border);
  }

  .tool-list article {
    grid-template-columns: minmax(180px, 0.8fr) minmax(0, 1.5fr);
  }

  .tool-list article .el-button {
    grid-column: 1 / -1;
    justify-self: start;
  }
}

@media (max-width: 760px) {
  .page-header,
  .header-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .domain-select {
    width: min(100%, 360px);
  }

  .publish-chain,
  .capability-summary,
  .tool-list article {
    grid-template-columns: 1fr;
  }

  .publish-chain i {
    display: none;
  }

  .publish-chain > div {
    padding: 8px 0;
    border-bottom: 1px solid var(--wq-border);
  }

  .publish-chain > div:last-child {
    border-bottom: 0;
  }

  .capability-summary > div {
    border-right: 0;
    border-bottom: 1px solid var(--wq-border);
  }
}
</style>
