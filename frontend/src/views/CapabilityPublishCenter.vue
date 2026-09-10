<template>
  <div class="page-shell capability-page" v-loading="loading" :aria-busy="loading">
    <header class="page-header">
      <div>
        <h2>能力发布中心</h2>
        <p>当前对外发布只读 Query Capability；对象查询和 Action 工具仅用于本项目内部验证。</p>
      </div>
      <div class="header-actions">
        <el-select v-model="domainId" class="domain-select" placeholder="选择业务领域" aria-label="选择业务领域">
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
        <el-button v-if="canManage" @click="openModelRelease">模型发布</el-button>
        <el-button v-if="canManage" type="primary" @click="openCreateClient">
          <el-icon><Plus /></el-icon>
          新建调用方
        </el-button>
      </div>
    </header>

    <el-alert
      class="consumer-note"
      type="info"
      :closable="false"
      title="外部 Agent 当前通过独立凭据调用 Query Capability；对象查询和 Action 尚未作为外部能力发布。"
    />

    <el-empty
      v-if="!loading && domains.length === 0"
      :description="canManage ? '暂无业务领域，请先在企业模型中创建并发布' : '暂无可访问业务领域，请联系技术人员配置业务领域或验证客户端权限'"
    />

    <template v-else-if="currentDomain">
      <details class="publish-chain-disclosure">
        <summary>能力发布链路</summary>
      <section class="publish-chain" aria-label="能力发布链路">
        <div>
          <span>企业模型</span>
          <strong>对象、指标、规则与动作</strong>
        </div>
        <i aria-hidden="true">→</i>
        <div>
          <span>能力合同</span>
          <strong>外部 Query / 内部验证工具</strong>
        </div>
        <i aria-hidden="true">→</i>
        <div>
          <span>能力消费者</span>
          <strong>外部 Agent 与业务应用</strong>
        </div>
      </section>
      </details>

      <section class="capability-summary">
        <div>
          <span>当前模型版本</span>
          <strong>{{ releaseVersion }}</strong>
          <small>{{ releaseName }}</small>
        </div>
        <div>
          <span>外部 Query 能力</span>
          <strong>{{ queryCapabilities.length }}</strong>
          <small>确定性编译与受控执行</small>
        </div>
        <div>
          <span>内部动作合同</span>
          <strong>{{ actions.length }}</strong>
          <small>按当前角色过滤</small>
        </div>
        <div>
          <span>内部验证工具</span>
          <strong>{{ tools.length }}</strong>
          <small>对象查询 / 业务查询 / 动作</small>
        </div>
      </section>

      <el-alert
        v-if="!activeModelRelease"
        class="publish-alert"
        type="warning"
        :closable="false"
        title="当前领域尚未激活统一企业模型版本；可以检查能力合同，但外部能力调用会被阻断。"
      />

      <section class="capability-surface">
        <el-tabs v-model="activeTab">
          <el-tab-pane :label="`外部 Query ${queryCapabilities.length}`" name="queries">
            <div class="tab-heading">
              <div>
                <h3>外部只读 Query 能力</h3>
                <p>通过独立调用凭据开放，由本体对象与明确绑定的语义指标生成。</p>
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
                  <el-button link type="primary" :aria-label="`查看 Query 能力合同：${row.name}`" @click="showQueryContract(row)">查看合同</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无查询能力：请先为本体对象绑定语义指标和维度" />
          </el-tab-pane>

          <el-tab-pane :label="`内部动作验证 ${actions.length}`" name="actions">
            <div class="tab-heading">
              <div>
                <h3>内部受控动作验证</h3>
                <p>当前仅供本项目内部验证；执行时仍会校验角色、对象版本、前置条件与审批单号。</p>
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
                  <el-button link type="primary" :aria-label="`查看内部动作合同：${row.name}`" @click="showActionContract(row)">查看合同</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="当前角色没有可用于内部验证的生效动作" />
          </el-tab-pane>

          <el-tab-pane :label="`内部工具 ${tools.length}`" name="tools">
            <div class="tab-heading">
              <div>
                <h3>内部 Agent 验证工具</h3>
                <p>用于验证对象查询、业务查询和动作效果，不代表这些工具均已对外发布。</p>
              </div>
            </div>
            <div class="tool-list">
              <article v-for="tool in tools" :key="tool.name">
                <div>
                  <strong>{{ toolLabel(tool.name) }}</strong>
                  <code>{{ tool.name }}</code>
                </div>
                <p>{{ tool.description }}</p>
                <el-button text type="primary" :aria-label="`查看内部工具参数：${toolLabel(tool.name)}`" @click="showToolContract(tool)">查看参数</el-button>
              </article>
            </div>
          </el-tab-pane>

          <el-tab-pane v-if="canManage" :label="`调用方 ${clients.length}`" name="clients">
            <div class="tab-heading">
              <div>
                <h3>第三方调用方</h3>
                <p>调用方使用独立凭据消费已授权能力，不需要在本项目创建智能体。</p>
              </div>
              <el-button type="primary" @click="openCreateClient">
                <el-icon><Plus /></el-icon>
                新建调用方
              </el-button>
            </div>
            <el-table
              v-if="clients.length"
              v-loading="clientsLoading"
              :data="clients"
              border
              class="capability-table"
            >
              <el-table-column label="调用方" min-width="210">
                <template #default="{ row }">
                  <div class="primary-cell">
                    <strong>{{ row.name }}</strong>
                    <span class="cell-note">{{ row.description || '未填写说明' }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="Client Key" min-width="240">
                <template #default="{ row }"><code>{{ row.client_key }}</code></template>
              </el-table-column>
              <el-table-column label="授权" width="100" align="center">
                <template #default="{ row }">{{ activeGrantCount(row.id) }} 项</template>
              </el-table-column>
              <el-table-column label="状态" width="100" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
                    {{ row.status === 'active' ? '已启用' : '已停用' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="最近使用" width="170">
                <template #default="{ row }">{{ formatDateTime(row.last_used_at, '尚未调用') }}</template>
              </el-table-column>
              <el-table-column label="操作" width="210" fixed="right" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" :aria-label="`管理调用方授权：${row.name}`" @click="openGrantDrawer(row)">授权管理</el-button>
                  <el-button
                    link
                    :type="row.status === 'active' ? 'warning' : 'success'"
                    :aria-label="`${row.status === 'active' ? '停用' : '启用'}调用方：${row.name}`"
                    @click="toggleClientStatus(row)"
                  >
                    {{ row.status === 'active' ? '停用' : '启用' }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else-if="!clientsLoading" description="暂无第三方调用方" />
          </el-tab-pane>

          <el-tab-pane v-if="canManage" :label="`调用审计 ${audits.length}`" name="audits">
            <div class="tab-heading">
              <div>
                <h3>能力调用审计</h3>
                <p>记录调用身份、能力、状态、耗时和结果摘要，不保存查询结果全文。</p>
              </div>
              <el-button :loading="auditsLoading" @click="loadAudits">刷新审计</el-button>
            </div>
            <el-table
              v-if="audits.length"
              v-loading="auditsLoading"
              :data="audits"
              border
              class="capability-table"
            >
              <el-table-column label="时间" width="170">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="调用方" min-width="150">
                <template #default="{ row }">{{ clientName(row.client_id) }}</template>
              </el-table-column>
              <el-table-column label="能力" min-width="230">
                <template #default="{ row }"><code>{{ row.capability_key }}</code></template>
              </el-table-column>
              <el-table-column label="状态" width="150">
                <template #default="{ row }">
                  <el-tag :type="auditStatusType(row.status)" effect="plain">
                    {{ auditStatusLabel(row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="模型版本" width="180">
                <template #default="{ row }">
                  <div class="primary-cell">
                    <code>模型 #{{ row.model_release_id || '-' }}</code>
                    <span class="cell-note">
                      语义 #{{ row.semantic_snapshot_id || '-' }} · 本体 #{{ row.ontology_release_id || '-' }}
                    </span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="结果" width="150">
                <template #default="{ row }">{{ row.row_count }} 行 · {{ row.latency_ms }} ms</template>
              </el-table-column>
              <el-table-column label="Trace" min-width="170">
                <template #default="{ row }"><code>{{ row.trace_id }}</code></template>
              </el-table-column>
              <el-table-column label="错误" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">{{ row.error_message || '-' }}</template>
              </el-table-column>
            </el-table>
            <el-empty v-else-if="!auditsLoading" description="当前领域暂无调用记录" />
          </el-tab-pane>
        </el-tabs>
      </section>

      <el-alert
        class="version-boundary"
        type="info"
        :closable="false"
        title="第一版已提供独立调用身份、领域能力授权和调用审计；独立能力版本、灰度与配额治理仍属于后续建设。"
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
          <code class="endpoint">{{ selectedContract.endpoint }}</code>
          <span class="endpoint-note">{{ selectedContract.endpointNote }}</span>
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

    <el-drawer
      v-model="grantDrawerVisible"
      :title="selectedClient ? `${selectedClient.name} · 能力授权` : '能力授权'"
      size="720px"
      append-to-body
    >
      <div v-if="selectedClient" class="grant-management">
        <div class="grant-toolbar">
          <div>
            <span>Client Key</span>
            <code>{{ selectedClient.client_key }}</code>
          </div>
          <el-button type="primary" :disabled="!domainId" @click="openGrantDialog">
            新增授权
          </el-button>
        </div>
        <el-table v-if="selectedGrants.length" :data="selectedGrants" border size="small">
          <el-table-column label="业务领域" min-width="150">
            <template #default="{ row }">{{ domainName(row.domain_id) }}</template>
          </el-table-column>
          <el-table-column label="能力" min-width="220">
            <template #default="{ row }"><code>{{ row.capability_key }}</code></template>
          </el-table-column>
          <el-table-column label="数据边界" min-width="180">
            <template #default="{ row }">
              <div class="primary-cell">
                <strong>{{ row.execution_agent_id ? '旧权限兼容适配' : '业务领域权限' }}</strong>
                <span class="cell-note">{{ row.execution_agent_id ? `内部适配 #${row.execution_agent_id}，待迁移` : '领域表和字段权限直接生效' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="授权合同" min-width="170">
            <template #default="{ row }">
              <div class="primary-cell">
                <strong>{{ row.model_release_id ? `模型 #${row.model_release_id}` : '历史授权' }}</strong>
                <span class="cell-note">{{ row.contract_hash ? `合同 ${row.contract_hash.slice(0, 8)}…` : '首次调用时兼容绑定' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
                {{ row.status === 'active' ? '生效' : '已撤销' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" align="center">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'active'"
                link
                type="danger"
                :aria-label="`撤销能力授权：${row.capability_key}`"
                @click="revokeGrant(row)"
              >
                撤销
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无能力授权" />
      </div>
    </el-drawer>

    <el-dialog v-model="createClientVisible" title="新建第三方调用方" width="520px" @opened="focusControl(clientNameInput)">
      <el-form :model="clientForm" label-width="90px">
        <el-form-item label="名称" required>
          <el-input ref="clientNameInput" v-model="clientForm.name" maxlength="256" placeholder="例如：审批助手" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="clientForm.description" type="textarea" :rows="3" maxlength="20000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createClientVisible = false">取消</el-button>
        <el-button type="primary" :loading="clientSaving" @click="saveClient">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="credentialVisible" title="调用凭据" width="620px" :close-on-click-modal="false" @opened="focusControl(copyCredentialButton)">
      <el-alert
        type="warning"
        :closable="false"
        title="Client Secret 只展示本次。关闭前请交付给调用方并妥善保存。"
      />
      <dl v-if="createdCredential" class="credential-detail">
        <dt>Client Key</dt><dd><code>{{ createdCredential.client_key }}</code></dd>
        <dt>Client Secret</dt><dd><code>{{ createdCredential.client_secret }}</code></dd>
      </dl>
      <template #footer>
        <el-button ref="copyCredentialButton" @click="copyCredential">复制凭据</el-button>
        <el-button type="primary" @click="credentialVisible = false">我已保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="grantDialogVisible" title="新增能力授权" width="560px" @opened="focusControl(grantCapabilitySelect)">
      <el-form :model="grantForm" label-width="110px">
        <el-alert
          class="grant-boundary-note"
          type="info"
          :closable="false"
          title="这里只授权调用方可以使用哪些业务能力。数据源、表和字段权限由平台按业务领域自动适配，无需选择或创建内部验证 Agent。"
        />
        <el-form-item label="业务领域" required>
          <el-select v-model="grantForm.domain_id" disabled class="form-control">
            <el-option
              v-for="domain in domains"
              :key="domain.id"
              :label="domain.name"
              :value="domain.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="Query 能力" required>
          <el-select ref="grantCapabilitySelect" v-model="grantForm.capability_key" class="form-control" placeholder="选择能力">
            <el-option
              v-for="capability in queryCapabilities"
              :key="capability.key"
              :label="`${capability.name} · ${capability.key}`"
              :value="capability.key"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="grantDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="grantSaving" @click="saveGrant">保存授权</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  createCapabilityClient,
  fetchCapabilityClients,
  fetchCapabilityGrants,
  fetchCapabilityInvocationAudits,
  fetchOntologyAgentContext,
  fetchOntologyDomains,
  fetchOntologyQueryCapabilities,
  updateCapabilityClientStatus,
  updateCapabilityGrant,
  type CapabilityClient,
  type CapabilityClientCredential,
  type CapabilityGrant,
  type CapabilityInvocationAudit,
  type OntologyAgentContext,
  type OntologyAgentToolDefinition,
  type OntologyQueryCapability,
  type SemanticDomain,
} from '../api'
import { isTechnicalUser } from '../stores/auth'
import { formatDateTime } from '../utils/datetime'

interface ContractView {
  kind: string
  name: string
  key: string
  description: string
  tool: string
  endpoint: string
  endpointNote: string
  example: Record<string, unknown>
  raw: Record<string, unknown>
}
type FocusableControl = { focus: () => void }

const router = useRouter()
const domains = ref<SemanticDomain[]>([])
const domainId = ref<number | null>(null)
const context = ref<OntologyAgentContext | null>(null)
const queryCapabilities = ref<OntologyQueryCapability[]>([])
const activeTab = ref('queries')
const loading = ref(true)
const contractVisible = ref(false)
const selectedContract = ref<ContractView | null>(null)
const clients = ref<CapabilityClient[]>([])
const grantsByClient = ref<Record<number, CapabilityGrant[]>>({})
const audits = ref<CapabilityInvocationAudit[]>([])
const clientsLoading = ref(false)
const auditsLoading = ref(false)
const clientSaving = ref(false)
const grantSaving = ref(false)
const createClientVisible = ref(false)
const credentialVisible = ref(false)
const grantDrawerVisible = ref(false)
const grantDialogVisible = ref(false)
const createdCredential = ref<CapabilityClientCredential | null>(null)
const selectedClient = ref<CapabilityClient | null>(null)
const clientNameInput = ref<FocusableControl>()
const copyCredentialButton = ref<FocusableControl>()
const grantCapabilitySelect = ref<FocusableControl>()
const clientForm = reactive({ name: '', description: '' })
const grantForm = reactive({
  domain_id: null as number | null,
  capability_key: '',
})

const currentDomain = computed(() => domains.value.find((item) => item.id === domainId.value) || null)
const actions = computed(() => context.value?.actions || [])
const tools = computed(() => context.value?.tools || [])
const canManage = computed(() => isTechnicalUser())
const activeModelRelease = computed(() => context.value?.model_release || null)
const selectedGrants = computed(() => (
  selectedClient.value ? grantsByClient.value[selectedClient.value.id] || [] : []
))
const releaseVersion = computed(() => activeModelRelease.value ? `V${activeModelRelease.value.version}` : '未激活')
const releaseName = computed(() => activeModelRelease.value?.name || '先创建、校验并激活统一企业模型版本')

function focusControl(control: FocusableControl | undefined) {
  requestAnimationFrame(() => control?.focus())
}

onMounted(async () => {
  try {
    domains.value = await fetchOntologyDomains()
    domainId.value = domains.value[0]?.id || null
    if (canManage.value) {
      await loadClients()
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    if (!domainId.value) loading.value = false
  }
})

watch(domainId, loadCapabilities)

async function loadCapabilities() {
  if (!domainId.value) {
    context.value = null
    queryCapabilities.value = []
    return
  }
  loading.value = true
  try {
    const [nextContext, nextQueries] = await Promise.all([
      fetchOntologyAgentContext(domainId.value),
      fetchOntologyQueryCapabilities(domainId.value),
    ])
    context.value = nextContext
    queryCapabilities.value = nextQueries
    if (canManage.value) await loadAudits()
  } catch (error) {
    context.value = null
    queryCapabilities.value = []
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

function openModelRelease() {
  router.push({ path: '/enterprise-model', query: { section: 'release' } })
}

async function loadClients() {
  clientsLoading.value = true
  try {
    clients.value = await fetchCapabilityClients()
    const entries = await Promise.all(
      clients.value.map(async client => [client.id, await fetchCapabilityGrants(client.id)] as const),
    )
    grantsByClient.value = Object.fromEntries(entries)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    clientsLoading.value = false
  }
}

async function loadAudits() {
  if (!domainId.value || !canManage.value) return
  auditsLoading.value = true
  try {
    audits.value = await fetchCapabilityInvocationAudits({
      domain_id: domainId.value,
      limit: 100,
    })
  } catch (error) {
    audits.value = []
    ElMessage.error(errorMessage(error))
  } finally {
    auditsLoading.value = false
  }
}

function openCreateClient() {
  clientForm.name = ''
  clientForm.description = ''
  createClientVisible.value = true
}

async function saveClient() {
  if (!clientForm.name.trim()) {
    ElMessage.warning('请输入调用方名称')
    return
  }
  clientSaving.value = true
  try {
    createdCredential.value = await createCapabilityClient({
      name: clientForm.name.trim(),
      description: clientForm.description.trim(),
    })
    createClientVisible.value = false
    credentialVisible.value = true
    activeTab.value = 'clients'
    await loadClients()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    clientSaving.value = false
  }
}

async function copyCredential() {
  if (!createdCredential.value) return
  const text = [
    `X-Capability-Key: ${createdCredential.value.client_key}`,
    `X-Capability-Secret: ${createdCredential.value.client_secret}`,
  ].join('\n')
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('调用凭据已复制')
  } catch {
    ElMessage.error('复制失败，请手动保存凭据')
  }
}

async function toggleClientStatus(client: CapabilityClient) {
  const nextStatus = client.status === 'active' ? 'disabled' : 'active'
  try {
    await ElMessageBox.confirm(
      nextStatus === 'disabled'
        ? `停用“${client.name}”后，其能力调用将立即被拒绝。`
        : `确认重新启用“${client.name}”？`,
      nextStatus === 'disabled' ? '停用调用方' : '启用调用方',
      { type: nextStatus === 'disabled' ? 'warning' : 'info' },
    )
    await updateCapabilityClientStatus(client.id, nextStatus)
    ElMessage.success('调用方状态已更新')
    await loadClients()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error))
  }
}

function openGrantDrawer(client: CapabilityClient) {
  selectedClient.value = client
  grantDrawerVisible.value = true
}

function openGrantDialog() {
  if (!domainId.value) return
  if (!queryCapabilities.value.length) {
    ElMessage.warning('当前领域暂无可授权的 Query Capability')
    return
  }
  grantForm.domain_id = domainId.value
  grantForm.capability_key = queryCapabilities.value[0]?.key || ''
  grantDialogVisible.value = true
}

async function saveGrant() {
  if (
    !selectedClient.value
    || !grantForm.domain_id
    || !grantForm.capability_key
  ) {
    ElMessage.warning('请选择需要授权的业务能力')
    return
  }
  grantSaving.value = true
  try {
    await updateCapabilityGrant(selectedClient.value.id, {
      domain_id: grantForm.domain_id,
      capability_key: grantForm.capability_key,
      status: 'active',
    })
    grantDialogVisible.value = false
    ElMessage.success('能力授权已保存')
    await loadClients()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    grantSaving.value = false
  }
}

async function revokeGrant(grant: CapabilityGrant) {
  try {
    await ElMessageBox.confirm(
      `撤销 ${grant.capability_key} 后，该调用方将不能再调用此能力。`,
      '撤销能力授权',
      { type: 'warning' },
    )
    await updateCapabilityGrant(grant.client_id, {
      domain_id: grant.domain_id,
      capability_key: grant.capability_key,
      status: 'revoked',
    })
    ElMessage.success('能力授权已撤销')
    await loadClients()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error))
  }
}

function activeGrantCount(clientId: number) {
  return (grantsByClient.value[clientId] || []).filter(item => item.status === 'active').length
}

function clientName(clientId: number) {
  return clients.value.find(item => item.id === clientId)?.name || `调用方 ${clientId}`
}

function domainName(id: number) {
  return domains.value.find(item => item.id === id)?.name || `领域 ${id}`
}

function auditStatusLabel(status: string) {
  return ({
    succeeded: '成功',
    validation_blocked: '校验拦截',
    security_blocked: '安全拦截',
    permission_blocked: '权限拦截',
    database_error: '数据库错误',
    failed: '失败',
  } as Record<string, string>)[status] || status
}

function auditStatusType(status: string) {
  if (status === 'succeeded') return 'success'
  if (status.endsWith('blocked')) return 'warning'
  return 'danger'
}

function showQueryContract(capability: OntologyQueryCapability) {
  const example: Record<string, unknown> = {
    domain_id: domainId.value,
    logic_form: {
      domain_key: currentDomain.value?.domain_key,
      metrics: capability.supported_metrics.slice(0, 1),
      dimensions: capability.supported_dimensions.slice(0, 1),
    },
  }
  if (activeModelRelease.value?.id) {
    example.model_release_id = activeModelRelease.value.id
  }
  selectedContract.value = {
    kind: '只读查询能力',
    name: capability.name,
    key: capability.key,
    description: capability.description || '',
    tool: 'ontology_query_capability',
    endpoint: `POST /api/v1/capabilities/${capability.key}:invoke`,
    endpointNote: '请求头需携带 X-Capability-Key 与 X-Capability-Secret。',
    example,
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
    endpoint: `POST /api/ontology/domains/${domainId.value}/agent-tools/ontology_execute_action`,
    endpointNote: '仅供本项目内调试；外部 Action 能力尚未发布。',
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
    endpoint: `POST /api/ontology/domains/${domainId.value}/agent-tools/${tool.name}`,
    endpointNote: '项目内调试入口；外部 Agent 当前通过已授权的 Query Capability API 调用。',
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

.consumer-note {
  margin-bottom: 14px;
}

.grant-boundary-note {
  margin-bottom: 18px;
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

.publish-chain-disclosure { margin-bottom: 10px; border: 1px solid var(--wq-border); border-radius: 7px; background: var(--wq-surface); }
.publish-chain-disclosure > summary { padding: 7px 11px; color: var(--wq-muted); font-size: 12px; font-weight: 650; cursor: pointer; }
.publish-chain-disclosure[open] > summary { border-bottom: 1px solid var(--wq-border); color: var(--wq-primary-strong); }
.publish-chain-disclosure .publish-chain { margin: 0; border: 0; border-radius: 0; box-shadow: none; }

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
  padding: 10px 13px;
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
  font-size: 19px;
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

.endpoint-note {
  color: var(--wq-muted);
  font-size: 12px;
  line-height: 1.5;
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

.grant-management {
  display: grid;
  gap: 16px;
}

.grant-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--wq-border);
}

.grant-toolbar > div {
  min-width: 0;
  display: grid;
  gap: 5px;
}

.grant-toolbar span,
.form-help {
  color: var(--wq-muted);
  font-size: 12px;
}

.grant-toolbar code,
.credential-detail code {
  overflow-wrap: anywhere;
  color: #31506f;
  font-size: 12px;
}

.credential-detail {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 14px 16px;
  margin-top: 18px;
}

.credential-detail dt {
  color: var(--wq-muted);
  font-size: 13px;
}

.credential-detail dd {
  min-width: 0;
  margin: 0;
}

.form-control {
  width: 100%;
}

.form-help {
  display: block;
  width: 100%;
  margin-top: 5px;
  line-height: 1.5;
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
  .header-actions,
  .grant-toolbar {
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
