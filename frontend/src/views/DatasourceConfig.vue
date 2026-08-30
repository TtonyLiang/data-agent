<template>
  <div class="page-shell">
    <div class="page-header">
      <div>
        <h2>数据源管理</h2>
        <p>维护可复用的数据连接，智能体访问权限在智能体管理中绑定。</p>
      </div>
      <div class="header-actions">
        <el-select v-model="agentId" clearable placeholder="初始关联智能体" style="width: 180px">
          <el-option
            v-if="agents.length === 0"
            label="默认智能体"
            :value="agentId"
          />
          <el-option
            v-for="agent in agents"
            :key="agent.id"
            :label="agent.name"
            :value="agent.id"
          />
        </el-select>
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
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column prop="db_type" label="类型" width="100" />
        <el-table-column prop="host" label="主机" min-width="180" />
        <el-table-column prop="port" label="端口" width="90" />
        <el-table-column prop="database_name" label="数据库" min-width="160" />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'danger'" size="small" round>
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="390" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDatasourceDetail(row)">详情</el-button>
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" @click="handleTest(row.id)">测试连接</el-button>
            <el-button size="small" type="primary" plain @click="openSchemaPanel(row)">表结构</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
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
import { computed, ref, onMounted, watch } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchAgents,
  fetchAllDatasources,
  createDatasource,
  updateDatasource,
  deleteDatasource,
  testConnection,
  collectSchema,
  uncollectSchema,
  fetchDatasourceRemoteTables,
  fetchDatasourceSchemaStats,
  fetchDatasourceTableDetail,
  type AgentItem,
  type DatasourceItem,
  type DatasourceRemoteTable,
  type DatasourceSchemaStats,
  type DatasourceTableMeta,
} from '../api'

const agentId = ref<number | null>(Number(localStorage.getItem('wenqu_agent_id')) || 1)
const agents = ref<AgentItem[]>([])
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
const showDialog = ref(false)
const editingDatasourceId = ref<number | null>(null)
const form = ref({
  agent_id: agentId.value as number | null,
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
  await loadAgents()
  await loadDatasources()
})

function defaultForm() {
  return {
    agent_id: agentId.value,
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
    agent_id: ds.agent_id ?? null,
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

watch(agentId, async (id) => {
  if (id) localStorage.setItem('wenqu_agent_id', String(id))
  form.value.agent_id = id
  await loadDatasources()
})

async function loadAgents() {
  try {
    agents.value = await fetchAgents()
    if (agents.value.length > 0 && !agents.value.some(agent => agent.id === agentId.value)) {
      agentId.value = agents.value[0].id
    }
  } catch {
    ElMessage.error('智能体配置加载失败，请确认后端服务已启动')
    agents.value = []
  }
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
    form.value.agent_id = agentId.value || null
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
      `确定删除数据源「${ds.name}」？已采集的 Schema 元数据也会一并删除。`,
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
  height: calc(100vh - 68px);
  overflow: auto;
  padding: 28px;
  background: var(--wq-bg);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  margin-bottom: 18px;
}

.page-header h2 {
  font-size: 22px;
  line-height: 1.25;
  color: var(--wq-text);
}

.page-header p {
  margin-top: 8px;
  color: var(--wq-muted);
  font-size: 14px;
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
}
</style>
