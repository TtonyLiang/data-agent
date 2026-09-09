<template>
  <div class="page-shell">
    <div class="page-header">
      <div>
        <h2>数据源管理</h2>
        <p>维护公司可复用的数据连接；验证智能体只在配置数据访问权限时作为过渡适配。</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon> 添加数据源
        </el-button>
      </div>
    </div>

    <div class="table-surface">
      <el-table
        ref="datasourceTableRef"
        :data="datasources"
        row-key="id"
        border
        stripe
        @expand-change="handleExpandChange"
      >
        <el-table-column type="expand" width="48">
          <template #default="{ row }">
            <div class="schema-workbench">
              <div class="schema-workbench__head">
                <div>
                  <strong>库表清单</strong>
                  <span>{{ row.database_name }} · 先读取表清单，再选择需要逆向的表</span>
                </div>
                <div class="schema-actions">
                  <el-button size="small" :loading="tableCatalogLoading[row.id]" @click="loadTableCatalog(row.id, true)">
                    读取表清单
                  </el-button>
                  <el-button
                    size="small"
                    type="primary"
                    :loading="schemaCollecting[row.id]"
                    :disabled="!selectedTablesByDatasource[row.id]?.length"
                    @click="handleCollect(row.id)"
                  >
                    采集选中表
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    plain
                    :loading="schemaUncollecting[row.id]"
                    :disabled="!selectedCollectedTableNames(row.id).length"
                    @click="handleUncollect(row.id)"
                  >
                    取消采集选中表
                  </el-button>
                </div>
              </div>

              <div class="schema-summary">
                <div>
                  <span>远端表</span>
                  <strong>{{ tableCatalogStats(row.id).total }}</strong>
                </div>
                <div>
                  <span>已采集</span>
                  <strong>{{ tableCatalogStats(row.id).collected }}</strong>
                </div>
                <div>
                  <span>本次选择</span>
                  <strong>{{ selectedTablesByDatasource[row.id]?.length || 0 }}</strong>
                </div>
                <div>
                  <span>已采集字段</span>
                  <strong>{{ schemaStatsByDatasource[row.id]?.column_count || 0 }}</strong>
                </div>
              </div>

              <el-alert
                v-if="schemaStatsByDatasource[row.id]?.noise_level === 'high'"
                type="warning"
                show-icon
                :closable="false"
                class="schema-noise-alert"
                :title="schemaStatsByDatasource[row.id]?.recommendation"
              />

              <div class="schema-filters">
                <el-input
                  v-model="tableSearchByDatasource[row.id]"
                  clearable
                  placeholder="搜索表名或中文注释"
                />
                <el-select v-model="tableStatusFilterByDatasource[row.id]" placeholder="采集状态">
                  <el-option label="全部表" value="all" />
                  <el-option label="已采集" value="collected" />
                  <el-option label="未采集" value="uncollected" />
                </el-select>
              </div>

              <el-skeleton v-if="tableCatalogLoading[row.id] && !tableCatalogByDatasource[row.id]" :rows="5" animated />

              <el-empty
                v-else-if="!tableCatalogByDatasource[row.id]?.length"
                description="还没有读取到表清单"
                :image-size="72"
              >
                <el-button type="primary" size="small" :loading="tableCatalogLoading[row.id]" @click="loadTableCatalog(row.id, true)">
                  读取表清单
                </el-button>
              </el-empty>

              <el-table
                v-else
                :data="filteredTableCatalog(row.id)"
                row-key="table_name"
                border
                size="small"
                class="schema-catalog-table"
                @selection-change="handleTableSelection(row.id, $event)"
              >
                <el-table-column type="selection" width="44" />
                <el-table-column label="表" min-width="260">
                  <template #default="{ row: table }">
                    <div class="table-name-cell">
                      <strong>{{ table.table_comment || table.table_name }}</strong>
                      <code>{{ table.table_name }}</code>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="112">
                  <template #default="{ row: table }">
                    <el-tag v-if="table.collected" type="success" size="small" round>已采集</el-tag>
                    <el-tag v-else type="info" size="small" round>未采集</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="字段数" width="96">
                  <template #default="{ row: table }">
                    {{ table.collected ? table.column_count : '-' }}
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="260" fixed="right">
                  <template #default="{ row: table }">
                    <div class="table-row-actions">
                      <el-button
                        v-if="table.collected"
                        link
                        type="primary"
                        size="small"
                        :disabled="!table.table_id"
                        @click="openTableDetail(row.id, table)"
                      >
                        字段详情
                      </el-button>
                      <el-button
                        link
                        type="primary"
                        size="small"
                        :loading="schemaCollecting[row.id]"
                        @click="handleCollect(row.id, [table.table_name])"
                      >
                        {{ table.collected ? '重新采集' : '采集' }}
                      </el-button>
                      <el-button
                        v-if="table.collected"
                        link
                        type="danger"
                        size="small"
                        :loading="schemaUncollecting[row.id]"
                        @click="handleUncollect(row.id, [table.table_name])"
                      >
                        取消采集
                      </el-button>
                    </div>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="数据源" min-width="210">
          <template #default="{ row }">
            <div class="table-name-cell"><strong>{{ row.name }}</strong><code>#{{ row.id }} · {{ row.database_name }}</code></div>
          </template>
        </el-table-column>
        <el-table-column prop="db_type" label="类型" width="100" />
        <el-table-column label="连接地址" min-width="210" show-overflow-tooltip>
          <template #default="{ row }"><code>{{ row.host }}:{{ row.port }}</code></template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'danger'" size="small" round>
              {{ row.status === 'active' ? '已启用' : row.status === 'disabled' ? '已停用' : row.status || '未设置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <div class="datasource-row-actions">
              <el-button size="small" link type="primary" @click="openSchemaPanel(row)">表结构</el-button>
              <el-button size="small" link @click="openPermissionDrawer(row)">访问权限</el-button>
              <el-dropdown trigger="click">
                <el-button size="small" text :icon="MoreFilled" :aria-label="`更多数据源操作：${row.name}`" title="更多操作" />
                <template #dropdown><el-dropdown-menu>
                  <el-dropdown-item :icon="View" @click="openDatasourceDetail(row)">详情</el-dropdown-item>
                  <el-dropdown-item :icon="Edit" @click="openEdit(row)">编辑</el-dropdown-item>
                  <el-dropdown-item :icon="Connection" @click="handleTest(row.id)">测试连接</el-dropdown-item>
                  <el-dropdown-item divided :icon="Delete" class="datasource-delete" @click="handleDelete(row)">删除</el-dropdown-item>
                </el-dropdown-menu></template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer
      v-model="showDatasourceDetail"
      title="数据源详情"
      size="560px"
      append-to-body
    >
      <dl v-if="selectedDatasourceDetail" class="datasource-detail-grid">
        <dt>名称</dt><dd>{{ selectedDatasourceDetail.name }}</dd>
        <dt>类型</dt><dd>{{ selectedDatasourceDetail.db_type }}</dd>
        <dt>主机</dt><dd>{{ selectedDatasourceDetail.host }}</dd>
        <dt>端口</dt><dd>{{ selectedDatasourceDetail.port }}</dd>
        <dt>数据库</dt><dd>{{ selectedDatasourceDetail.database_name }}</dd>
        <dt>用户名</dt><dd>{{ selectedDatasourceDetail.username || '-' }}</dd>
        <dt>状态</dt><dd>{{ selectedDatasourceDetail.status || 'active' }}</dd>
        <dt>已采集表</dt><dd>{{ schemaStatsByDatasource[selectedDatasourceDetail.id]?.table_count || 0 }}</dd>
        <dt>已采集字段</dt><dd>{{ schemaStatsByDatasource[selectedDatasourceDetail.id]?.column_count || 0 }}</dd>
      </dl>
    </el-drawer>

    <el-drawer
      v-model="showPermissionDrawer"
      title="数据访问权限"
      size="860px"
      append-to-body
      class="permission-drawer"
    >
      <el-skeleton v-if="permissionLoading" :rows="8" animated />
      <div v-else-if="permissionDatasource" class="permission-editor">
        <div class="permission-context">
          <div>
            <span>数据源</span>
            <strong>{{ permissionDatasource.name }} / {{ permissionDatasource.database_name }}</strong>
          </div>
          <div class="permission-adapter-field">
            <span>权限归属业务领域</span>
            <el-select
              v-model="permissionDomainId"
              clearable
              placeholder="选择绑定当前数据源的业务领域"
              :disabled="permissionEligibleDomains.length === 0"
              aria-label="选择权限归属业务领域"
              @change="loadDomainPermissions"
            >
              <el-option
                v-for="domain in permissionEligibleDomains"
                :key="domain.id"
                :label="domain.name"
                :value="domain.id"
              />
            </el-select>
            <small>这是企业模型和外部能力的正式数据权限边界；不再按某个 Agent 分别维护。</small>
          </div>
          <el-tag type="success" effect="plain">领域白名单强制生效</el-tag>
        </div>

        <el-alert
          v-if="permissionEligibleDomains.length === 0"
          title="当前没有绑定该数据源的业务领域。请先在“企业模型中心”给业务领域绑定默认数据源。"
          type="warning"
          :closable="false"
          show-icon
          class="permission-alert"
        />
        <el-alert
          v-else
          title="只有下方明确允许的表可被该业务领域访问；未勾选和后续新接入的表默认不可访问。旧领域若尚未配置领域规则，运行时才会显式兼容 Agent 白名单。"
          type="warning"
          :closable="false"
          show-icon
          class="permission-alert"
        />

        <el-collapse class="permission-compatibility">
          <el-collapse-item name="legacy-agent">
            <template #title>
              <span>旧领域兼容入口（仅迁移）</span>
            </template>
            <div class="permission-compatibility__body">
              <span>验证权限适配（过渡）</span>
              <el-select
                v-model="permissionAgentId"
                clearable
                placeholder="选择已绑定当前数据源的验证智能体"
                :disabled="permissionEligibleAgents.length === 0"
                @change="loadDatasourcePermissions"
              >
                <el-option
                  v-for="agent in permissionEligibleAgents"
                  :key="agent.id"
                  :label="agent.name"
                  :value="agent.id"
                />
              </el-select>
              <el-button
                size="small"
                :disabled="!permissionAgentId"
                @click="saveDatasourcePermissions"
              >
                保存旧权限
              </el-button>
              <small>仅用于尚未迁移领域规则的历史数据；新配置请使用上方业务领域权限。</small>
            </div>
          </el-collapse-item>
        </el-collapse>

        <el-empty
          v-if="permissionEligibleDomains.length > 0 && !permissionDomainId"
          description="请选择业务领域，再配置表和字段权限"
          :image-size="72"
        />
        <el-empty
          v-else-if="permissionDomainId && permissionTables.length === 0"
          description="请先采集表结构，再配置访问权限"
          :image-size="72"
        />
        <el-table
          v-else
          :data="permissionTables"
          row-key="table_name"
          border
          size="small"
          class="permission-table"
        >
          <el-table-column type="expand" width="44">
            <template #default="{ row: table }">
              <div class="column-permission-panel">
                <div v-if="table.columns.length" class="column-permission-list">
                  <div
                    v-for="column in table.columns"
                    :key="`${table.table_name}.${column.column_name}`"
                    class="column-permission-row"
                  >
                    <div class="column-identity">
                      <strong>{{ column.column_comment || column.column_name }}</strong>
                      <code>{{ column.column_name }}</code>
                      <span>{{ column.data_type || '-' }}</span>
                    </div>
                    <el-switch
                      v-model="column.allowed"
                      :disabled="!table.allowed"
                      active-text="可见"
                      inactive-text="不可见"
                    />
                    <el-select
                      v-model="column.masking_policy"
                      :disabled="!table.allowed || !column.allowed"
                      aria-label="脱敏策略"
                      style="width: 142px"
                    >
                      <el-option label="不脱敏" value="none" />
                      <el-option label="完全隐藏" value="redact" />
                      <el-option label="部分隐藏" value="partial" />
                      <el-option label="哈希处理" value="hash" />
                    </el-select>
                  </div>
                </div>
                <el-empty v-else description="该表暂无已采集字段" :image-size="52" />
              </div>
            </template>
          </el-table-column>
          <el-table-column label="表" min-width="320">
            <template #default="{ row: table }">
              <div class="table-name-cell">
                <strong>{{ table.table_comment || table.table_name }}</strong>
                <code>{{ table.table_name }}</code>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="字段数" width="96">
            <template #default="{ row: table }">{{ table.columns.length }}</template>
          </el-table-column>
          <el-table-column label="表访问" width="210">
            <template #default="{ row: table }">
              <el-switch
                v-model="table.allowed"
                active-text="允许"
                inactive-text="拒绝"
              />
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="showPermissionDrawer = false">取消</el-button>
        <el-button
          type="primary"
          :loading="permissionSaving"
          :disabled="permissionLoading || !permissionDatasource || !permissionDomainId"
          @click="saveDomainDatasourcePermissions"
        >
          保存权限
        </el-button>
      </template>
    </el-drawer>

    <el-drawer
      v-model="showTableDetail"
      title="表字段详情"
      size="720px"
      append-to-body
      class="table-detail-drawer"
    >
      <el-skeleton v-if="tableDetailLoading" :rows="5" animated />
      <div v-else-if="selectedTableDetail" class="table-detail">
        <div class="detail-identity">
          <span>{{ selectedDatasourceName }}</span>
          <strong>{{ selectedTableDetail.table_comment || selectedTableDetail.table_name }}</strong>
          <code>{{ selectedTableDetail.table_name }}</code>
        </div>

        <el-input
          v-model="columnSearch"
          clearable
          placeholder="搜索字段名或字段中文名"
          class="column-search"
        />

        <el-table :data="filteredSelectedColumns" border stripe size="small" class="column-table">
          <el-table-column label="字段中文名" min-width="160">
            <template #default="{ row: column }">
              {{ column.column_comment || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="字段名" min-width="180">
            <template #default="{ row: column }">
              <code>{{ column.column_name }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="data_type" label="类型" width="120" />
          <el-table-column label="键" width="118">
            <template #default="{ row: column }">
              <div class="key-tags">
                <el-tag v-if="isEnabled(column.is_primary_key)" size="small" type="warning">主键</el-tag>
                <el-tag v-if="isEnabled(column.is_foreign_key)" size="small" type="info">外键</el-tag>
                <span v-if="!isEnabled(column.is_primary_key) && !isEnabled(column.is_foreign_key)">-</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="外键引用" min-width="180" show-overflow-tooltip>
            <template #default="{ row: column }">
              <code v-if="column.foreign_key_ref">{{ column.foreign_key_ref }}</code>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <el-empty v-else description="请选择一张已采集的表" />
    </el-drawer>

    <el-dialog v-model="showDialog" :title="editingDatasourceId ? '编辑数据源' : '添加数据源'" width="560">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="主机">
          <el-input v-model="form.host" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="form.port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="editingDatasourceId ? '不修改请留空' : ''"
          />
        </el-form-item>
        <el-form-item label="数据库名">
          <el-input v-model="form.database_name" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { Plus, MoreFilled, View, Edit, Connection, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchAllSemanticDomains,
  fetchAgents,
  fetchAgentDatasourceIds,
  fetchAllDatasources,
  createDatasource,
  updateDatasource,
  deleteDatasource,
  testConnection,
  collectSchema,
  uncollectSchema,
  fetchDatasourceSchema,
  fetchDatasourceRemoteTables,
  fetchDatasourceSchemaStats,
  fetchDatasourceTableDetail,
  fetchDomainDatasourcePermissions,
  updateDomainDatasourcePermissions,
  fetchDatasourcePermissions,
  updateDatasourcePermissions,
  type DatasourceMaskingPolicy,
  type DatasourcePermissionConfig,
  type DatasourcePermissionReplace,
  type DomainDatasourcePermissionConfig,
  type AgentItem,
  type SemanticDomain,
  type DatasourceItem,
  type DatasourceRemoteTable,
  type DatasourceSchemaStats,
  type DatasourceTableMeta,
} from '../api'

interface PermissionColumnDraft {
  column_name: string
  column_comment?: string | null
  data_type?: string
  allowed: boolean
  masking_policy: DatasourceMaskingPolicy
}

interface PermissionTableDraft {
  table_name: string
  table_comment?: string | null
  allowed: boolean
  columns: PermissionColumnDraft[]
}

const permissionDomainId = ref<number | null>(null)
const semanticDomains = ref<SemanticDomain[]>([])
const permissionAgentId = ref<number | null>(null)
const agents = ref<AgentItem[]>([])
const agentDatasourceIds = ref<Record<number, number[]>>({})
const datasources = ref<DatasourceItem[]>([])
const datasourceTableRef = ref()
const tableCatalogByDatasource = ref<Record<number, DatasourceRemoteTable[]>>({})
const schemaStatsByDatasource = ref<Record<number, DatasourceSchemaStats>>({})
const selectedTablesByDatasource = ref<Record<number, DatasourceRemoteTable[]>>({})
const tableSearchByDatasource = ref<Record<number, string>>({})
const tableStatusFilterByDatasource = ref<Record<number, string>>({})
const tableCatalogLoading = ref<Record<number, boolean>>({})
const schemaCollecting = ref<Record<number, boolean>>({})
const schemaUncollecting = ref<Record<number, boolean>>({})
const showTableDetail = ref(false)
const showDatasourceDetail = ref(false)
const selectedDatasourceId = ref<number | null>(null)
const selectedDatasourceDetail = ref<DatasourceItem | null>(null)
const selectedTableDetail = ref<DatasourceTableMeta | null>(null)
const columnSearch = ref('')
const tableDetailLoading = ref(false)
const showPermissionDrawer = ref(false)
const permissionDatasource = ref<DatasourceItem | null>(null)
const permissionTables = ref<PermissionTableDraft[]>([])
const permissionLoading = ref(false)
const permissionSaving = ref(false)
const showDialog = ref(false)
const editingDatasourceId = ref<number | null>(null)
const form = ref({
  agent_id: null as number | null,
  name: '',
  db_type: 'mysql',
  host: '127.0.0.1',
  port: 3306,
  username: 'root',
  password: '',
  database_name: '',
  status: 'active',
})

const selectedDatasourceName = computed(() => {
  const datasource = datasources.value.find(item => item.id === selectedDatasourceId.value)
  return datasource ? `${datasource.name} / ${datasource.database_name}` : '数据源'
})

const permissionEligibleDomains = computed(() => {
  const datasourceId = permissionDatasource.value?.id
  if (!datasourceId) return []
  return semanticDomains.value.filter(domain => (
    Number(domain.datasource_id || 0) === datasourceId
    && domain.status !== 'disabled'
  ))
})

const permissionEligibleAgents = computed(() => {
  const datasourceId = permissionDatasource.value?.id
  if (!datasourceId) return []
  return agents.value.filter(agent => (
    agentDatasourceIds.value[agent.id] || []
  ).includes(datasourceId))
})

const filteredSelectedColumns = computed(() => {
  const columns = selectedTableDetail.value?.columns || []
  const keyword = columnSearch.value.trim().toLowerCase()
  if (!keyword) return columns
  return columns.filter(column => (
    column.column_name.toLowerCase().includes(keyword)
    || String(column.column_comment || '').toLowerCase().includes(keyword)
  ))
})

onMounted(async () => {
  await loadSemanticDomains()
  await loadAgents()
  await loadDatasources()
})

function defaultForm() {
  return {
    agent_id: null,
    name: '',
    db_type: 'mysql',
    host: '127.0.0.1',
    port: 3306,
    username: 'root',
    password: '',
    database_name: '',
    status: 'active',
  }
}

function openCreate() {
  editingDatasourceId.value = null
  form.value = defaultForm()
  showDialog.value = true
}

function openEdit(ds: DatasourceItem) {
  editingDatasourceId.value = ds.id
  form.value = {
    agent_id: null,
    name: ds.name,
    db_type: ds.db_type || 'mysql',
    host: ds.host,
    port: ds.port,
    username: ds.username || 'root',
    password: '',
    database_name: ds.database_name,
    status: ds.status || 'active',
  }
  showDialog.value = true
}

async function openDatasourceDetail(ds: DatasourceItem) {
  selectedDatasourceDetail.value = ds
  showDatasourceDetail.value = true
  if (!schemaStatsByDatasource.value[ds.id]) {
    try {
      const stats = await fetchDatasourceSchemaStats(ds.id)
      schemaStatsByDatasource.value = { ...schemaStatsByDatasource.value, [ds.id]: stats }
    } catch { /* keep drawer available */ }
  }
}

function buildPermissionDraft(
  schema: DatasourceTableMeta[],
  permissions: DatasourcePermissionReplace,
): PermissionTableDraft[] {
  const tableRules = new Map(
    permissions.table_permissions.map(rule => [rule.table_name.toLowerCase(), rule]),
  )
  const columnRules = new Map(
    permissions.column_permissions.map(rule => [
      `${rule.table_name.toLowerCase()}.${rule.column_name.toLowerCase()}`,
      rule,
    ]),
  )
  const tables = new Map<string, PermissionTableDraft>()
  for (const table of schema) {
    const tableKey = table.table_name.toLowerCase()
    const tableRule = tableRules.get(tableKey)
    tables.set(tableKey, {
      table_name: table.table_name,
      table_comment: table.table_comment,
      allowed: Boolean(tableRule?.allowed),
      columns: table.columns.map((column) => {
        const rule = columnRules.get(`${tableKey}.${column.column_name.toLowerCase()}`)
        return {
          column_name: column.column_name,
          column_comment: column.column_comment,
          data_type: column.data_type,
          allowed: rule?.allowed ?? true,
          masking_policy: rule?.masking_policy ?? 'none',
        }
      }),
    })
  }

  for (const rule of permissions.table_permissions) {
    const tableKey = rule.table_name.toLowerCase()
    if (!tables.has(tableKey)) {
      tables.set(tableKey, {
        table_name: rule.table_name,
        allowed: rule.allowed,
        columns: [],
      })
    }
  }
  for (const rule of permissions.column_permissions) {
    const tableKey = rule.table_name.toLowerCase()
    if (!tables.has(tableKey)) {
      tables.set(tableKey, {
        table_name: rule.table_name,
        allowed: Boolean(tableRules.get(tableKey)?.allowed),
        columns: [],
      })
    }
    const table = tables.get(tableKey)!
    if (!table.columns.some(column => column.column_name.toLowerCase() === rule.column_name.toLowerCase())) {
      table.columns.push({
        column_name: rule.column_name,
        allowed: rule.allowed,
        masking_policy: rule.masking_policy,
      })
    }
  }

  return [...tables.values()]
    .map(table => ({
      ...table,
      columns: [...table.columns].sort((left, right) => left.column_name.localeCompare(right.column_name)),
    }))
    .sort((left, right) => left.table_name.localeCompare(right.table_name))
}

async function openPermissionDrawer(ds: DatasourceItem) {
  permissionDatasource.value = ds
  permissionTables.value = []
  permissionDomainId.value = permissionEligibleDomains.value[0]?.id || null
  permissionAgentId.value = null
  showPermissionDrawer.value = true
  if (permissionDomainId.value) void loadDomainPermissions()
}

async function loadDatasourcePermissions() {
  if (!permissionDatasource.value || !permissionAgentId.value) return
  permissionLoading.value = true
  try {
    const [schema, permissions] = await Promise.all([
      fetchDatasourceSchema(permissionDatasource.value.id),
      fetchDatasourcePermissions(permissionDatasource.value.id, permissionAgentId.value),
    ])
    permissionTables.value = buildPermissionDraft(schema, permissions)
  } catch (error) {
    ElMessage.error(errorMessage(error, '旧权限加载失败'))
  } finally {
    permissionLoading.value = false
  }
}

async function loadDomainPermissions() {
  if (!permissionDatasource.value || !permissionDomainId.value) {
    permissionTables.value = []
    return
  }
  permissionLoading.value = true
  try {
    const [schema, permissions] = await Promise.all([
      fetchDatasourceSchema(permissionDatasource.value.id),
      fetchDomainDatasourcePermissions(permissionDatasource.value.id, permissionDomainId.value),
    ])
    permissionTables.value = buildPermissionDraft(schema, permissions)
  } catch (error) {
    permissionTables.value = []
    ElMessage.error(errorMessage(error, '访问权限加载失败'))
  } finally {
    permissionLoading.value = false
  }
}

async function saveDomainDatasourcePermissions() {
  if (!permissionDatasource.value || !permissionDomainId.value) return
  if (permissionTables.value.length === 0) {
    ElMessage.warning('请先采集表结构，再配置表白名单')
    return
  }

  const tablePermissions = permissionTables.value.map(table => ({
    table_name: table.table_name,
    allowed: table.allowed,
  }))
  const columnPermissions = permissionTables.value.flatMap(table => (
    table.columns
      .filter(column => !column.allowed || column.masking_policy !== 'none')
      .map(column => ({
        table_name: table.table_name,
        column_name: column.column_name,
        allowed: column.allowed,
        masking_policy: column.allowed ? column.masking_policy : 'none' as DatasourceMaskingPolicy,
      }))
  ))

  permissionSaving.value = true
  try {
    await updateDomainDatasourcePermissions(permissionDatasource.value.id, permissionDomainId.value, {
      table_permissions: tablePermissions,
      column_permissions: columnPermissions,
    })
    ElMessage.success('访问权限已保存')
    showPermissionDrawer.value = false
  } catch {
    ElMessage.error('访问权限保存失败')
  } finally {
    permissionSaving.value = false
  }
}

async function saveDatasourcePermissions() {
  if (!permissionDatasource.value || !permissionAgentId.value) return
  if (permissionTables.value.length === 0) {
    ElMessage.warning('请先采集表结构，再配置表白名单')
    return
  }
  const tablePermissions = permissionTables.value.map(table => ({
    table_name: table.table_name,
    allowed: table.allowed,
  }))
  const columnPermissions = permissionTables.value.flatMap(table => (
    table.columns
      .filter(column => !column.allowed || column.masking_policy !== 'none')
      .map(column => ({
        table_name: table.table_name,
        column_name: column.column_name,
        allowed: column.allowed,
        masking_policy: column.allowed ? column.masking_policy : 'none' as DatasourceMaskingPolicy,
      }))
  ))
  permissionSaving.value = true
  try {
    await updateDatasourcePermissions(permissionDatasource.value.id, permissionAgentId.value, {
      table_permissions: tablePermissions,
      column_permissions: columnPermissions,
    })
    ElMessage.success('旧领域兼容权限已保存')
  } catch (error) {
    ElMessage.error(errorMessage(error, '旧权限保存失败'))
  } finally {
    permissionSaving.value = false
  }
}

async function loadSemanticDomains() {
  try {
    semanticDomains.value = await fetchAllSemanticDomains()
  } catch {
    ElMessage.error('业务领域加载失败，请确认后端服务已启动')
    semanticDomains.value = []
  }
}

async function loadAgents() {
  try {
    agents.value = await fetchAgents()
    const bindings = await Promise.all(agents.value.map(async agent => (
      [agent.id, await fetchAgentDatasourceIds(agent.id).catch(() => [])] as const
    )))
    agentDatasourceIds.value = Object.fromEntries(bindings)
  } catch {
    agents.value = []
    agentDatasourceIds.value = {}
  }
}

function errorMessage(error: unknown, fallback: string) {
  const candidate = error as {
    response?: { data?: { detail?: string | { message?: string } } }
    message?: string
  }
  const detail = candidate?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return candidate?.message || fallback
}

async function loadDatasources() {
  try {
    datasources.value = await fetchAllDatasources()
  } catch {
    ElMessage.error('数据源加载失败，请确认后端服务已启动')
    datasources.value = []
  }
}

function isEnabled(value: boolean | number | undefined | null) {
  return value === true || value === 1
}

function tableCatalogStats(datasourceId: number) {
  const tables = tableCatalogByDatasource.value[datasourceId] || []
  return {
    total: tables.length,
    collected: tables.filter(table => table.collected).length,
  }
}

function filteredTableCatalog(datasourceId: number) {
  const keyword = (tableSearchByDatasource.value[datasourceId] || '').trim().toLowerCase()
  const status = tableStatusFilterByDatasource.value[datasourceId] || 'all'
  return (tableCatalogByDatasource.value[datasourceId] || []).filter((table) => {
    const matchesKeyword = !keyword
      || table.table_name.toLowerCase().includes(keyword)
      || String(table.table_comment || '').toLowerCase().includes(keyword)
    const matchesStatus = status === 'all'
      || (status === 'collected' && table.collected)
      || (status === 'uncollected' && !table.collected)
    return matchesKeyword && matchesStatus
  })
}

function selectedCollectedTableNames(datasourceId: number) {
  return (selectedTablesByDatasource.value[datasourceId] || [])
    .filter(table => table.collected)
    .map(table => table.table_name)
}

async function loadTableCatalog(datasourceId: number, force = false) {
  if (!force && tableCatalogByDatasource.value[datasourceId]) return
  tableCatalogLoading.value = { ...tableCatalogLoading.value, [datasourceId]: true }
  try {
    const [tables, stats] = await Promise.all([
      fetchDatasourceRemoteTables(datasourceId),
      fetchDatasourceSchemaStats(datasourceId),
    ])
    tableCatalogByDatasource.value = { ...tableCatalogByDatasource.value, [datasourceId]: tables }
    schemaStatsByDatasource.value = { ...schemaStatsByDatasource.value, [datasourceId]: stats }
    if (!tableStatusFilterByDatasource.value[datasourceId]) {
      tableStatusFilterByDatasource.value = { ...tableStatusFilterByDatasource.value, [datasourceId]: 'all' }
    }
  } catch {
    ElMessage.error('表清单读取失败，请确认连接配置和数据库权限')
    tableCatalogByDatasource.value = { ...tableCatalogByDatasource.value, [datasourceId]: [] }
  } finally {
    tableCatalogLoading.value = { ...tableCatalogLoading.value, [datasourceId]: false }
  }
}

function handleExpandChange(row: DatasourceItem, expandedRows: DatasourceItem[]) {
  if (expandedRows.some(item => item.id === row.id)) {
    void loadTableCatalog(row.id)
  }
}

function openSchemaPanel(row: DatasourceItem) {
  datasourceTableRef.value?.toggleRowExpansion(row, true)
  void loadTableCatalog(row.id)
}

function handleTableSelection(datasourceId: number, rows: DatasourceRemoteTable[]) {
  selectedTablesByDatasource.value = {
    ...selectedTablesByDatasource.value,
    [datasourceId]: rows,
  }
}

async function openTableDetail(datasourceId: number, table: DatasourceRemoteTable) {
  if (!table.table_id) {
    ElMessage.warning('请先采集该表，再查看字段详情')
    return
  }
  selectedDatasourceId.value = datasourceId
  selectedTableDetail.value = null
  columnSearch.value = ''
  showTableDetail.value = true
  tableDetailLoading.value = true
  try {
    selectedTableDetail.value = await fetchDatasourceTableDetail(datasourceId, table.table_id)
  } catch {
    ElMessage.error('表字段加载失败')
    showTableDetail.value = false
  } finally {
    tableDetailLoading.value = false
  }
}

async function handleSubmit() {
  if (!form.value.name || !form.value.host || !form.value.database_name) {
    ElMessage.warning('请填写完整信息')
    return
  }
  try {
    if (editingDatasourceId.value) {
      await updateDatasource(editingDatasourceId.value, form.value)
      ElMessage.success('更新成功')
    } else {
      await createDatasource(form.value)
      ElMessage.success('创建成功')
    }
    showDialog.value = false
    editingDatasourceId.value = null
    form.value = defaultForm()
    await loadDatasources()
  } catch {
    ElMessage.error(editingDatasourceId.value ? '更新失败' : '创建失败')
  }
}

async function handleTest(id: number) {
  try {
    const res = await testConnection(id)
    if (res.success) {
      ElMessage.success('连接成功')
    } else {
      ElMessage.error('连接失败')
    }
  } catch {
    ElMessage.error('测试失败')
  }
}

async function handleCollect(id: number, explicitTableNames?: string[]) {
  const tableNames = explicitTableNames
    || (selectedTablesByDatasource.value[id] || []).map(table => table.table_name)
  if (!tableNames.length) {
    ElMessage.warning('请先选择要逆向采集的表')
    return
  }
  schemaCollecting.value = { ...schemaCollecting.value, [id]: true }
  try {
    const res = await collectSchema(id, tableNames)
    selectedTablesByDatasource.value = { ...selectedTablesByDatasource.value, [id]: [] }
    await loadTableCatalog(id, true)
    ElMessage.success(`采集完成，共 ${res.tables?.length || 0} 张表`)
  } catch {
    ElMessage.error('采集失败')
  } finally {
    schemaCollecting.value = { ...schemaCollecting.value, [id]: false }
  }
}

async function handleUncollect(id: number, explicitTableNames?: string[]) {
  const tableNames = explicitTableNames || selectedCollectedTableNames(id)
  if (!tableNames.length) {
    ElMessage.warning('请选择已采集的表')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定取消采集 ${tableNames.length} 张表？这只会移除元数据，不会删除真实数据库表。取消后大模型不会再从这些表结构里召回上下文。`,
      '取消采集表结构',
      { type: 'warning' },
    )
  } catch {
    return
  }
  schemaUncollecting.value = { ...schemaUncollecting.value, [id]: true }
  try {
    const res = await uncollectSchema(id, tableNames)
    selectedTablesByDatasource.value = { ...selectedTablesByDatasource.value, [id]: [] }
    if (selectedTableDetail.value && tableNames.includes(selectedTableDetail.value.table_name)) {
      showTableDetail.value = false
      selectedTableDetail.value = null
    }
    await loadTableCatalog(id, true)
    ElMessage.success(`已取消采集 ${res.tables?.length || 0} 张表`)
  } catch {
    ElMessage.error('取消采集失败')
  } finally {
    schemaUncollecting.value = { ...schemaUncollecting.value, [id]: false }
  }
}

async function handleDelete(ds: DatasourceItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除数据源「${ds.name}」？平台会删除连接、权限配置和已采集 Schema，但不会删除业务领域或企业模型；仍被领域使用时会阻止删除。`,
      '删除数据源',
      { type: 'warning' },
    )
    await deleteDatasource(ds.id)
    ElMessage.success('删除成功')
    const nextCatalog = { ...tableCatalogByDatasource.value }
    delete nextCatalog[ds.id]
    tableCatalogByDatasource.value = nextCatalog
    const nextSelected = { ...selectedTablesByDatasource.value }
    delete nextSelected[ds.id]
    selectedTablesByDatasource.value = nextSelected
    await loadDatasources()
  } catch {
    // cancelled or failed
  }
}
</script>

<style scoped>
.page-shell {
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding: 18px var(--wq-page-gutter) 24px !important;
  background: var(--wq-bg);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  margin-bottom: 12px;
}

.page-header h2 {
  font-size: 20px;
  line-height: 1.25;
  color: var(--wq-text);
}

.page-header p {
  margin-top: 4px;
  color: var(--wq-muted);
  font-size: 12px;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.table-surface {
  background: #fff;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: var(--wq-shadow);
}

.schema-workbench {
  padding: 16px 18px 20px;
  background: #f8fafc;
}

.schema-workbench__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.schema-workbench__head strong {
  display: block;
  color: var(--wq-text);
  font-size: 14px;
}

.schema-workbench__head span {
  display: block;
  margin-top: 4px;
  color: var(--wq-muted);
  font-size: 12px;
}

.schema-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.schema-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.schema-summary div {
  min-width: 0;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
}

.schema-summary span {
  display: block;
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1.25;
}

.schema-summary strong {
  display: block;
  margin-top: 4px;
  color: var(--wq-text);
  font-size: 18px;
  line-height: 1.25;
}

.schema-catalog-table {
  background: #fff;
}

.schema-noise-alert {
  margin-bottom: 12px;
}

.schema-filters {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 160px;
  gap: 10px;
  margin-bottom: 12px;
}

.table-name-cell {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.table-name-cell strong {
  color: var(--wq-text);
  font-size: 13px;
  line-height: 1.35;
}

.table-name-cell code {
  width: fit-content;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.table-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  white-space: nowrap;
}

.datasource-row-actions { display: flex; align-items: center; gap: 12px; white-space: nowrap; }
.datasource-row-actions :deep(.el-button) { margin-left: 0; }
.datasource-row-actions :deep(.el-dropdown .el-button) { width: 30px; padding: 0; }
:global(.datasource-delete) { color: var(--wq-danger); }

:global(.table-detail-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--wq-border);
  color: var(--wq-text);
  font-weight: 760;
}

.table-detail {
  padding: 2px 2px 20px;
}

.detail-identity {
  display: grid;
  gap: 6px;
  margin-bottom: 16px;
  padding: 14px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #f8fafc;
}

.detail-identity span {
  color: var(--wq-subtle);
  font-size: 12px;
}

.detail-identity strong {
  color: var(--wq-text);
  font-size: 18px;
  line-height: 1.35;
}

.detail-identity code {
  width: fit-content;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

code {
  padding: 2px 6px;
  border-radius: 5px;
  background: #eef3f8;
  color: #31506f;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.column-table {
  border: 0;
}

.column-search {
  margin-bottom: 12px;
}

.datasource-detail-grid {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 12px;
  margin: 0;
}

.datasource-detail-grid dt {
  color: var(--wq-subtle);
  font-size: 13px;
}

.datasource-detail-grid dd {
  margin: 0;
  color: var(--wq-text);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.permission-editor {
  padding: 2px 2px 20px;
}

.permission-compatibility {
  margin: 12px 0 16px;
}

.permission-compatibility__body {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 4px 12px 12px;
  color: var(--wq-muted);
  font-size: 12px;
}

.permission-compatibility__body small {
  flex-basis: 100%;
}

.permission-context {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #f8fafc;
}

.permission-context div {
  min-width: 0;
}

.permission-context span,
.permission-context strong {
  display: block;
}

.permission-context span {
  color: var(--wq-subtle);
  font-size: 12px;
}

.permission-context strong {
  margin-top: 4px;
  overflow: hidden;
  color: var(--wq-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.permission-adapter-field {
  display: grid;
  gap: 5px;
}

.permission-adapter-field small {
  color: var(--wq-muted);
  font-size: 12px;
  line-height: 1.4;
}

.permission-alert {
  margin-bottom: 12px;
}

.permission-table {
  background: #fff;
}

.column-permission-panel {
  padding: 8px 14px 12px 48px;
  background: #f8fafc;
}

.column-permission-list {
  border-top: 1px solid #dbe3ef;
}

.column-permission-row {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) 150px 142px;
  align-items: center;
  gap: 16px;
  min-height: 54px;
  border-bottom: 1px solid #dbe3ef;
}

.column-identity {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.column-identity strong {
  min-width: 0;
  overflow: hidden;
  color: var(--wq-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.column-identity span {
  flex: none;
  color: var(--wq-subtle);
  font-size: 12px;
}

.key-tags {
  display: flex;
  gap: 6px;
  align-items: center;
  min-height: 22px;
}

@media (max-width: 760px) {
  .page-shell { padding: 18px; }
  .page-header { align-items: flex-start; flex-direction: column; }
  .header-actions { justify-content: flex-start; }
  .schema-summary,
  .schema-filters { grid-template-columns: 1fr; }
  .permission-context,
  .column-permission-row { grid-template-columns: 1fr; }
  .column-permission-panel { padding-left: 14px; }
  .column-permission-row { gap: 8px; padding: 10px 0; }
}
</style>
