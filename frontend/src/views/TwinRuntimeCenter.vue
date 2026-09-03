<template>
  <div class="page-shell twin-runtime-page" v-loading="loading">
    <header class="page-header">
      <div>
        <h2>孪生运行</h2>
        <p>把业务数据库中的记录同步成可识别、可关联、可追踪的企业对象。</p>
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
        <el-button :disabled="!domainId" @click="loadRuntime">
          <el-icon><Refresh /></el-icon>
          刷新状态
        </el-button>
      </div>
    </header>

    <el-empty v-if="!loading && domains.length === 0" description="暂无可用业务领域" />

    <template v-else-if="currentDomain">
      <section class="runtime-flow" aria-label="孪生数据处理流程">
        <div :class="{ ready: Boolean(currentDomain.datasource_id) }">
          <span>1</span>
          <strong>连接数据</strong>
          <small>{{ currentDomain.datasource_id ? `数据源 #${currentDomain.datasource_id}` : '未绑定数据源' }}</small>
        </div>
        <i aria-hidden="true">→</i>
        <div :class="{ ready: mappingCount > 0 }">
          <span>2</span>
          <strong>统一数据含义</strong>
          <small>{{ mappingCount }} 项字段映射</small>
        </div>
        <i aria-hidden="true">→</i>
        <div :class="{ ready: syncEnabledCount > 0 }">
          <span>3</span>
          <strong>同步业务对象</strong>
          <small>{{ syncEnabledCount }} 类对象已配置</small>
        </div>
        <i aria-hidden="true">→</i>
        <div :class="{ ready: sourceObjectCount > 0 }">
          <span>4</span>
          <strong>形成当前孪生</strong>
          <small>{{ sourceObjectCount }} 个对象实例</small>
        </div>
      </section>

      <section class="runtime-summary">
        <div>
          <span>同步对象类型</span>
          <strong>{{ syncEnabledCount }} / {{ objectTypes.length }}</strong>
          <small>已配置 / 全部</small>
        </div>
        <div>
          <span>业务对象实例</span>
          <strong>{{ sourceObjectCount }}</strong>
          <small>源数据统计</small>
        </div>
        <div>
          <span>最近同步</span>
          <strong class="summary-time">{{ lastSyncedAt ? formatDateTime(lastSyncedAt) : '尚未同步' }}</strong>
          <small>{{ lastSyncStatusText }}</small>
        </div>
        <div>
          <span>当前模型版本</span>
          <strong>{{ summary?.latest_release ? `V${summary.latest_release.version}` : '未发布' }}</strong>
          <small>{{ summary?.latest_release?.name || '发布后供 Agent 使用' }}</small>
        </div>
      </section>

      <section class="runtime-content">
        <div class="runtime-table-panel">
          <div class="panel-heading">
            <div>
              <h3>对象同步任务</h3>
              <p>每次手动读取一个对象类型的一页数据，并更新同步状态。</p>
            </div>
            <el-button text type="primary" @click="openModelConfig">配置业务对象</el-button>
          </div>

          <el-table v-if="objectTypes.length" :data="objectTypes" class="runtime-table" border>
            <el-table-column label="业务对象" min-width="200">
              <template #default="{ row }">
                <div class="primary-cell">
                  <strong>{{ row.name }}</strong>
                  <code>{{ row.object_key }}</code>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="数据同步" min-width="150">
              <template #default="{ row }">
                <el-tag v-if="row.sync_enabled" type="success" effect="plain">已配置</el-tag>
                <el-tag v-else type="info" effect="plain">未配置</el-tag>
                <span class="cell-note">{{ row.source_query ? '只读查询已配置' : '未配置来源查询' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="运行状态" min-width="170">
              <template #default="{ row }">
                <el-tag :type="syncStatusType(row.last_sync_status)" effect="plain">
                  {{ syncStatusLabel(row) }}
                </el-tag>
                <span class="cell-note">
                  {{ row.last_synced_at ? formatDateTime(row.last_synced_at) : '暂无运行记录' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="源记录" width="110" align="right">
              <template #default="{ row }">{{ row.last_sync_total || row.last_sync_count || 0 }}</template>
            </el-table-column>
            <el-table-column label="操作" width="128" fixed="right" align="center">
              <template #default="{ row }">
                <el-tooltip
                  :disabled="row.sync_enabled"
                  content="请先在企业模型中配置只读同步查询"
                  placement="top"
                >
                  <span>
                    <el-button
                      type="primary"
                      plain
                      size="small"
                      :disabled="!row.sync_enabled"
                      :loading="syncingTypeId === row.id"
                      @click="syncObjectType(row)"
                    >
                      同步一页
                    </el-button>
                  </span>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-else description="当前领域还没有业务对象">
            <el-button type="primary" @click="openModelConfig">开始本体建模</el-button>
          </el-empty>
        </div>

        <aside class="runtime-boundary">
          <h3>当前运行边界</h3>
          <ul>
            <li class="available">
              <b>已可用</b>
              <span>业务库只读分页同步</span>
            </li>
            <li class="available">
              <b>已可用</b>
              <span>源数据与本地动作结果合并</span>
            </li>
            <li class="available">
              <b>已可用</b>
              <span>同步数量、时间和错误记录</span>
            </li>
            <li>
              <b>下一步</b>
              <span>后台定时与增量调度</span>
            </li>
            <li>
              <b>下一步</b>
              <span>对象身份合并与状态历史</span>
            </li>
          </ul>
          <el-alert
            type="info"
            :closable="false"
            title="当前页面是手动运行入口，不表示已经接入 CDC 或自动调度。"
          />
        </aside>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  fetchOntologyDomains,
  fetchOntologyObjectTypes,
  fetchOntologySummary,
  fetchSemanticAssets,
  syncOntologyObjects,
  type OntologyObjectType,
  type OntologySummary,
  type SemanticDomain,
} from '../api'
import { formatDateTime } from '../utils/datetime'

const router = useRouter()
const domains = ref<SemanticDomain[]>([])
const domainId = ref<number | null>(null)
const summary = ref<OntologySummary | null>(null)
const objectTypes = ref<OntologyObjectType[]>([])
const mappingCount = ref(0)
const loading = ref(false)
const syncingTypeId = ref<number | null>(null)

const currentDomain = computed(() => domains.value.find((item) => item.id === domainId.value) || null)
const syncEnabledCount = computed(() => objectTypes.value.filter((item) => item.sync_enabled).length)
const sourceObjectCount = computed(() => Number(summary.value?.counts.source_objects || summary.value?.counts.objects || 0))
const lastSyncedAt = computed(() => objectTypes.value
  .map((item) => item.last_synced_at)
  .filter((value): value is string => Boolean(value))
  .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0] || '')
const lastSyncStatusText = computed(() => {
  const synced = objectTypes.value.filter((item) => item.last_sync_status)
  if (!synced.length) return '等待首次运行'
  if (synced.some((item) => item.last_sync_status === 'failed')) return '存在同步失败'
  if (synced.some((item) => item.last_sync_status === 'partial')) return '存在部分成功'
  return '最近任务运行成功'
})

onMounted(async () => {
  try {
    domains.value = await fetchOntologyDomains()
    domainId.value = domains.value[0]?.id || null
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
})

watch(domainId, loadRuntime)

async function loadRuntime() {
  if (!domainId.value) {
    summary.value = null
    objectTypes.value = []
    mappingCount.value = 0
    return
  }
  loading.value = true
  try {
    const [nextSummary, nextTypes, assets] = await Promise.all([
      fetchOntologySummary(domainId.value),
      fetchOntologyObjectTypes(domainId.value),
      fetchSemanticAssets(domainId.value),
    ])
    summary.value = nextSummary
    objectTypes.value = nextTypes
    mappingCount.value = Array.isArray(assets.mapping) ? assets.mapping.length : 0
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

async function syncObjectType(objectType: OntologyObjectType) {
  if (!domainId.value || !objectType.sync_enabled) return
  syncingTypeId.value = objectType.id
  try {
    const result = await syncOntologyObjects(domainId.value, {
      object_type_id: objectType.id,
      page: 1,
      page_size: Math.min(Math.max(Number(objectType.sync_limit || 200), 1), 1000),
      sync_links: true,
    })
    const typeResult = result.types.find((item) => item.object_type_id === objectType.id) || result.types[0]
    if (typeResult?.errors?.length) {
      ElMessage.warning(`同步完成，但有 ${typeResult.errors.length} 个问题：${typeResult.errors[0]}`)
    } else {
      const changed = Number(typeResult?.created || 0) + Number(typeResult?.updated || 0)
      ElMessage.success(`已读取 ${typeResult?.read || result.objects.length} 条，更新 ${changed} 条`)
    }
    await loadRuntime()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    syncingTypeId.value = null
  }
}

function openModelConfig() {
  router.push({ path: '/enterprise-model', query: { section: 'ontology' } })
}

function syncStatusLabel(row: OntologyObjectType) {
  if (!row.sync_enabled) return '未配置'
  return ({
    succeeded: '同步成功',
    partial: '部分成功',
    failed: '同步失败',
  } as Record<string, string>)[String(row.last_sync_status || '')] || '等待同步'
}

function syncStatusType(status: OntologyObjectType['last_sync_status']) {
  if (status === 'succeeded') return 'success'
  if (status === 'partial') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}

function errorMessage(error: unknown) {
  const candidate = error as { response?: { data?: { detail?: string | { message?: string } } }; message?: string }
  const detail = candidate?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return candidate?.message || '孪生运行状态加载失败'
}
</script>

<style scoped>
.twin-runtime-page {
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

.runtime-flow {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr);
  align-items: center;
  padding: 16px 18px;
  margin-bottom: 16px;
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  box-shadow: var(--wq-shadow-sm);
}

.runtime-flow > div {
  min-width: 0;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  column-gap: 9px;
  align-items: center;
}

.runtime-flow > div > span {
  width: 28px;
  height: 28px;
  grid-row: 1 / 3;
  display: grid;
  place-items: center;
  color: var(--wq-muted);
  font-size: 12px;
  font-weight: 700;
  background: var(--wq-surface-raised);
  border: 1px solid var(--wq-border);
  border-radius: 7px;
}

.runtime-flow > div.ready > span {
  color: var(--wq-success);
  background: #ecfdf3;
  border-color: #abefc6;
}

.runtime-flow strong,
.runtime-flow small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-flow strong {
  color: var(--wq-text);
  font-size: 14px;
}

.runtime-flow small {
  color: var(--wq-muted);
  font-size: 12px;
}

.runtime-flow i {
  color: var(--wq-subtle);
  font-style: normal;
  text-align: center;
}

.runtime-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 16px;
  overflow: hidden;
  border: 1px solid var(--wq-border);
}

.runtime-summary > div {
  min-width: 0;
  padding: 15px 18px;
  display: grid;
  gap: 4px;
  border-right: 1px solid var(--wq-border);
}

.runtime-summary > div:last-child {
  border-right: 0;
}

.runtime-summary span,
.runtime-summary small {
  color: var(--wq-muted);
  font-size: 12px;
}

.runtime-summary strong {
  color: var(--wq-text);
  font-size: 22px;
  line-height: 1.25;
}

.runtime-summary .summary-time {
  font-size: 15px;
  line-height: 1.6;
}

.runtime-content {
  min-height: 360px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 290px;
  gap: 16px;
  align-items: start;
}

.runtime-table-panel,
.runtime-boundary {
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  box-shadow: var(--wq-shadow-sm);
}

.runtime-table-panel {
  overflow: hidden;
}

.panel-heading {
  min-height: 72px;
  padding: 13px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--wq-border);
}

.panel-heading h3,
.runtime-boundary h3 {
  color: var(--wq-text);
  font-size: 15px;
}

.panel-heading p {
  margin-top: 4px;
  color: var(--wq-muted);
  font-size: 12px;
}

.primary-cell,
.runtime-table :deep(.cell) {
  display: grid;
  gap: 4px;
}

.primary-cell code {
  width: fit-content;
  color: #31506f;
  font-size: 12px;
}

.cell-note {
  color: var(--wq-muted);
  font-size: 12px;
}

.runtime-boundary {
  padding: 17px;
}

.runtime-boundary ul {
  list-style: none;
  margin: 13px 0 16px;
  border-top: 1px solid var(--wq-border);
}

.runtime-boundary li {
  padding: 11px 0;
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 8px;
  border-bottom: 1px solid var(--wq-border);
}

.runtime-boundary li b {
  color: var(--wq-warning);
  font-size: 12px;
}

.runtime-boundary li.available b {
  color: var(--wq-success);
}

.runtime-boundary li span {
  color: #344054;
  font-size: 13px;
}

@media (max-width: 980px) {
  .runtime-flow {
    grid-template-columns: 1fr 18px 1fr;
    row-gap: 14px;
  }

  .runtime-flow > i:nth-of-type(2) {
    display: none;
  }

  .runtime-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .runtime-summary > div:nth-child(2) {
    border-right: 0;
  }

  .runtime-summary > div:nth-child(-n + 2) {
    border-bottom: 1px solid var(--wq-border);
  }

  .runtime-content {
    grid-template-columns: 1fr;
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

  .runtime-flow {
    grid-template-columns: 1fr;
  }

  .runtime-flow > i {
    display: none;
  }

  .runtime-summary {
    grid-template-columns: 1fr;
  }

  .runtime-summary > div {
    border-right: 0;
    border-bottom: 1px solid var(--wq-border);
  }
}
</style>
