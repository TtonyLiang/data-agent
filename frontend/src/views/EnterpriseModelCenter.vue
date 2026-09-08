<template>
  <div class="enterprise-model-center" v-loading="domainLoading" :aria-busy="domainLoading">
    <header class="model-center-header">
      <div class="model-center-bar">
        <div class="model-center-title">
          <strong>企业模型</strong>
          <span>先确定业务领域，再维护模型、数据口径和运行版本</span>
        </div>

        <section class="domain-context" aria-label="当前业务领域">
          <div class="domain-field">
            <span class="domain-field-label">业务领域</span>
            <el-select
              v-model="domainId"
              class="domain-select"
              filterable
              placeholder="请先选择业务领域"
              aria-label="选择业务领域"
              :disabled="domains.length === 0"
            >
              <el-option
                v-for="domain in domains"
                :key="domain.id"
                :label="`${domain.name} · ${domain.domain_key}`"
                :value="domain.id"
              />
            </el-select>
          </div>
          <div v-if="currentDomain" class="domain-meta">
            <el-tag :type="currentDomain.status === 'active' ? 'success' : 'info'" effect="plain">
              {{ currentDomain.status === 'active' ? '已启用' : '已停用' }}
            </el-tag>
            <span>{{ currentDatasourceName }}</span>
          </div>
          <div v-if="canManage" class="domain-actions">
            <el-button @click="openCreateDomain">新建领域</el-button>
            <el-dropdown @command="handleDomainCommand">
              <el-button type="primary" plain>领域管理</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit" :disabled="!currentDomain">编辑</el-dropdown-item>
                  <el-dropdown-item command="copy" :disabled="!currentDomain">复制语义配置</el-dropdown-item>
                  <el-dropdown-item command="import" divided>导入语义包</el-dropdown-item>
                  <el-dropdown-item command="export" :disabled="!currentDomain">导出语义包</el-dropdown-item>
                  <el-dropdown-item command="delete" :disabled="!currentDomain" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <input
              ref="domainImportInput"
              class="file-input"
              type="file"
              accept="application/json,.json"
              tabindex="-1"
              aria-hidden="true"
              @change="handleDomainImport"
            />
          </div>
        </section>
      </div>

      <nav class="model-sections" :class="{ single: !canManage }" aria-label="企业模型建模顺序">
        <button
          type="button"
          :disabled="!domainId"
          :class="{ active: activeSection === 'ontology' }"
          :aria-current="activeSection === 'ontology' ? 'step' : undefined"
          @click="selectSection('ontology')"
        >
          <span><b>业务本体</b><small>对象、关系、状态与动作</small></span>
        </button>
        <button
          v-if="canManage"
          type="button"
          :disabled="!domainId"
          :class="{ active: activeSection === 'semantic' }"
          :aria-current="activeSection === 'semantic' ? 'step' : undefined"
          @click="selectSection('semantic')"
        >
          <span><b>语义与数据</b><small>指标、规则、映射与查询口径</small></span>
        </button>
        <button
          v-if="canManage"
          type="button"
          :disabled="!domainId"
          :class="{ active: activeSection === 'release' }"
          :aria-current="activeSection === 'release' ? 'step' : undefined"
          @click="selectSection('release')"
        >
          <span><b>版本发布</b><small>绑定、校验、激活与回滚</small></span>
        </button>
      </nav>
    </header>

    <section class="model-center-workspace" aria-label="企业模型工作区">
      <el-empty
        v-if="!domainId"
        :description="canManage ? '请先新建或选择一个业务领域' : '暂无可访问业务领域，请联系管理员分配验证客户端权限'"
      />
      <OntologyWorkbench
        v-else-if="activeSection === 'ontology'"
        :domain-id="domainId"
        :current-domain="currentDomain"
      />
      <KnowledgeConfig
        v-else-if="activeSection === 'semantic'"
        :domain-id="domainId"
        :current-domain="currentDomain"
        @domain-updated="loadDomains(domainId)"
      />
      <ModelReleaseCenter
        v-else
        :domain-id="domainId"
        :current-domain="currentDomain"
      />
    </section>

    <el-dialog
      v-model="showDomainDialog"
      :title="domainDialogMode === 'edit' ? '编辑业务领域' : '新增业务领域'"
      width="620px"
      @opened="focusDomainName"
    >
      <el-form :model="domainForm" label-width="110px" label-position="left">
        <el-form-item label="领域名称" required>
          <el-input ref="domainNameInput" v-model="domainForm.name" placeholder="如 贷款风控、订单分析" />
        </el-form-item>
        <el-form-item label="领域标识" required>
          <el-input
            v-model="domainForm.domain_key"
            placeholder="如 loan_risk"
            :disabled="domainDialogMode === 'edit'"
          />
        </el-form-item>
        <el-form-item label="默认数据源">
          <el-select v-model="domainForm.datasource_id" clearable filterable placeholder="可选">
            <el-option
              v-for="datasource in datasources"
              :key="datasource.id"
              :label="`${datasource.name} · ${datasource.database_name}`"
              :value="datasource.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="domainForm.status">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="业务范围">
          <el-input
            v-model="domainForm.description"
            type="textarea"
            :rows="4"
            placeholder="说明领域覆盖的业务范围、数据口径和使用边界"
          />
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        title="业务领域是企业模型资产的边界，不属于某一个 Agent。"
      />
      <template #footer>
        <el-button @click="showDomainDialog = false">取消</el-button>
        <el-button type="primary" :loading="domainSaving" @click="saveDomain">保存并开始建模</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  copySemanticDomain,
  deleteSemanticDomain,
  exportSemanticDomain,
  fetchAllDatasources,
  fetchOntologyDomains,
  importSemanticDomain,
  upsertSemanticDomain,
  type DatasourceItem,
  type SemanticDomain,
  type SemanticDomainRequest,
} from '../api'
import { isAdmin } from '../stores/auth'

const OntologyWorkbench = defineAsyncComponent(() => import('./OntologyWorkbench.vue'))
const KnowledgeConfig = defineAsyncComponent(() => import('./KnowledgeConfig.vue'))
const ModelReleaseCenter = defineAsyncComponent(() => import('./ModelReleaseCenter.vue'))

type ModelSection = 'ontology' | 'semantic' | 'release'

const route = useRoute()
const router = useRouter()
const domains = ref<SemanticDomain[]>([])
const domainId = ref<number | null>(null)
const datasources = ref<DatasourceItem[]>([])
const domainLoading = ref(false)
const domainSaving = ref(false)
const showDomainDialog = ref(false)
const domainDialogMode = ref<'create' | 'edit'>('create')
const domainImportInput = ref<HTMLInputElement>()
const domainNameInput = ref<{ focus: () => void }>()
const domainForm = ref<SemanticDomainRequest>(emptyDomain())
const canManage = computed(() => isAdmin())
const currentDomain = computed<SemanticDomain | null>(() => (
  domains.value.find((domain) => domain.id === domainId.value) || null
))
const currentDatasourceName = computed(() => {
  const datasourceId = currentDomain.value?.datasource_id
  if (!datasourceId) return '未绑定默认数据源'
  const datasource = datasources.value.find((item) => item.id === datasourceId)
  return datasource ? `${datasource.name} · ${datasource.database_name}` : `数据源 #${datasourceId}`
})

const activeSection = computed<ModelSection>(() => {
  if (!canManage.value) return 'ontology'
  if (route.query.section === 'semantic' || route.query.section === 'release') {
    return route.query.section
  }
  return 'ontology'
})

onMounted(async () => {
  await Promise.all([
    loadDomains(),
    canManage.value ? loadDatasources() : Promise.resolve(),
  ])
})

function emptyDomain(): SemanticDomainRequest {
  return {
    id: null,
    agent_id: null,
    datasource_id: null,
    domain_key: '',
    name: '',
    description: '',
    status: 'active',
  }
}

function focusDomainName() {
  requestAnimationFrame(() => domainNameInput.value?.focus())
}

async function loadDomains(preferredDomainId?: number | null) {
  domainLoading.value = true
  try {
    const nextDomains = await fetchOntologyDomains()
    domains.value = nextDomains
    const preferred = preferredDomainId ?? domainId.value
    domainId.value = preferred && nextDomains.some((item) => item.id === preferred)
      ? preferred
      : nextDomains[0]?.id || null
  } catch (error) {
    domains.value = []
    domainId.value = null
    ElMessage.error(errorMessage(error, '业务领域加载失败'))
  } finally {
    domainLoading.value = false
  }
}

async function loadDatasources() {
  try {
    datasources.value = await fetchAllDatasources()
  } catch {
    datasources.value = []
  }
}

function selectSection(section: ModelSection) {
  if (!domainId.value) {
    ElMessage.warning('请先创建或选择业务领域')
    return
  }
  if (section === activeSection.value) return
  router.replace({ path: '/enterprise-model', query: { ...route.query, section } })
}

function openCreateDomain() {
  domainDialogMode.value = 'create'
  domainForm.value = emptyDomain()
  showDomainDialog.value = true
}

function openEditDomain() {
  if (!currentDomain.value) return
  domainDialogMode.value = 'edit'
  domainForm.value = {
    id: currentDomain.value.id,
    agent_id: currentDomain.value.agent_id || null,
    datasource_id: currentDomain.value.datasource_id || null,
    domain_key: currentDomain.value.domain_key,
    name: currentDomain.value.name,
    description: currentDomain.value.description || '',
    status: currentDomain.value.status || 'active',
  }
  showDomainDialog.value = true
}

async function saveDomain() {
  const payload: SemanticDomainRequest = {
    ...domainForm.value,
    agent_id: domainForm.value.agent_id ? Number(domainForm.value.agent_id) : null,
    datasource_id: domainForm.value.datasource_id ? Number(domainForm.value.datasource_id) : null,
    domain_key: cleanText(domainForm.value.domain_key),
    name: cleanText(domainForm.value.name),
    description: cleanText(domainForm.value.description),
    status: domainForm.value.status || 'active',
  }
  if (!payload.name) return ElMessage.warning('请输入业务领域名称')
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(payload.domain_key)) {
    return ElMessage.warning('领域标识只能使用英文、数字和下划线，且不能以数字开头')
  }
  domainSaving.value = true
  try {
    const result = await upsertSemanticDomain(payload)
    const selectedId = Number(result.id || payload.id || 0) || null
    showDomainDialog.value = false
    await loadDomains(selectedId)
    await router.replace({ path: '/enterprise-model', query: { section: 'ontology' } })
    ElMessage.success(result.message || '业务领域已保存')
  } catch (error) {
    ElMessage.error(errorMessage(error, '业务领域保存失败'))
  } finally {
    domainSaving.value = false
  }
}

async function deleteCurrentDomain() {
  if (!currentDomain.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除业务领域“${currentDomain.value.name}”？仅未产生版本、实例、运行或审计记录的领域可以删除；已有历史的领域请改为停用。`,
      '删除业务领域',
      { type: 'warning' },
    )
    await deleteSemanticDomain(currentDomain.value.id)
    ElMessage.success('业务领域已删除')
    await loadDomains()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error, '业务领域删除失败'))
  }
}

async function copyCurrentDomain() {
  if (!currentDomain.value) return
  try {
    const { value } = await ElMessageBox.prompt(
      '请输入新业务领域标识；此操作复制语义资产，不复制业务本体。',
      '复制业务领域',
      {
        inputValue: `${currentDomain.value.domain_key}_copy`,
        inputPattern: /^[A-Za-z_][A-Za-z0-9_]*$/,
        inputErrorMessage: '只能使用英文、数字和下划线，且不能以数字开头',
      },
    )
    const result = await copySemanticDomain(currentDomain.value.id, {
      domain_key: value,
      name: `${currentDomain.value.name} 副本`,
    })
    await loadDomains(Number(result.id || 0) || null)
    ElMessage.success(result.message || '业务领域已复制')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error, '业务领域复制失败'))
  }
}

async function exportCurrentDomain() {
  if (!currentDomain.value) return
  try {
    const bundle = await exportSemanticDomain(currentDomain.value.id)
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${currentDomain.value.domain_key}.semantic.json`
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success('领域语义包已导出')
  } catch (error) {
    ElMessage.error(errorMessage(error, '领域语义包导出失败'))
  }
}

function handleDomainCommand(command: string) {
  if (command === 'edit') openEditDomain()
  else if (command === 'copy') copyCurrentDomain()
  else if (command === 'import') domainImportInput.value?.click()
  else if (command === 'export') exportCurrentDomain()
  else if (command === 'delete') deleteCurrentDomain()
}

async function handleDomainImport(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    const result = await importSemanticDomain(JSON.parse(await file.text()))
    await loadDomains(Number(result.id || 0) || null)
    ElMessage.success(result.message || '业务领域已导入')
  } catch (error) {
    ElMessage.error(errorMessage(error, '业务领域导入失败'))
  }
}

function cleanText(value: unknown) {
  return String(value || '').trim()
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
</script>

<style scoped>
.enterprise-model-center { width: 100%; height: 100%; min-height: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--wq-bg); }
.model-center-header { flex: 0 0 auto; background: var(--wq-surface); border-bottom: 1px solid var(--wq-border); }
.model-center-bar { width: 100%; max-width: var(--wq-page-max-width); min-height: 72px; margin: 0 auto; padding: 10px var(--wq-page-gutter); display: grid; grid-template-columns: minmax(190px, .55fr) minmax(0, 2.45fr); align-items: center; gap: 24px; border-bottom: 1px solid var(--wq-border); }
.model-center-title { min-width: 0; display: grid; gap: 3px; }
.model-center-title strong { color: var(--wq-text); font-size: 18px; line-height: 1.3; }
.model-center-title span, .domain-meta > span, .domain-field-label { color: var(--wq-muted); font-size: 12px; }
.domain-context { min-width: 0; display: flex; align-items: center; justify-content: flex-end; gap: 12px; }
.domain-field { min-width: 0; display: flex; align-items: center; gap: 9px; }
.domain-field-label { flex: 0 0 auto; font-weight: 650; }
.domain-select { width: 280px; flex: 0 1 280px; }
.domain-meta, .domain-actions { display: flex; align-items: center; gap: 7px; white-space: nowrap; }
.domain-meta > span { max-width: 210px; overflow: hidden; text-overflow: ellipsis; }
.domain-actions { flex: 0 0 auto; }
.model-sections { width: 100%; max-width: var(--wq-page-max-width); min-width: 0; min-height: 52px; margin: 0 auto; padding: 0 var(--wq-page-gutter); display: flex; align-items: stretch; gap: 30px; }
.model-sections.single { max-width: 420px; }
.model-sections button { position: relative; min-width: 150px; min-height: 52px; padding: 8px 2px 9px; display: flex; align-items: center; color: var(--wq-muted); text-align: left; background: transparent; border: 0; border-bottom: 3px solid transparent; border-radius: 0; cursor: pointer; }
.model-sections button:hover:not(:disabled) { color: var(--wq-text); }
.model-sections button:focus-visible { outline: 2px solid var(--wq-primary); outline-offset: -4px; }
.model-sections button.active { color: var(--wq-primary-strong); border-bottom-color: var(--wq-primary); }
.model-sections button:disabled { cursor: not-allowed; opacity: .55; }
.model-sections button > span:last-child { min-width: 0; display: grid; gap: 1px; }
.model-sections b, .model-sections small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-sections b { font-size: 14px; }
.model-sections small { color: var(--wq-subtle); font-size: 12px; }
.model-sections button.active small { color: var(--wq-primary-strong); }
.model-center-workspace { min-height: 0; flex: 1; overflow: hidden; }
.model-center-workspace > .el-empty { height: 100%; }
.file-input { display: none; }
@media (max-width: 1120px) {
  .model-center-bar { grid-template-columns: 170px minmax(0, 1fr); gap: 16px; }
  .domain-context { flex-wrap: wrap; }
  .domain-meta > span { display: none; }
}
@media (max-width: 760px) {
  .model-center-bar { min-height: 0; padding: 12px 16px; grid-template-columns: 1fr; gap: 10px; }
  .domain-context { display: grid; grid-template-columns: minmax(0, 1fr) auto; justify-content: stretch; gap: 10px; }
  .domain-field { grid-column: 1 / -1; display: grid; grid-template-columns: 72px minmax(0, 1fr); }
  .domain-select { width: 100%; }
  .domain-meta { min-width: 0; overflow: hidden; }
  .domain-meta > span { display: block; max-width: 100%; }
  .domain-actions { justify-self: end; }
  .model-sections { padding: 0 16px; flex-wrap: wrap; gap: 0 20px; }
  .model-sections button { flex: 1 1 calc(50% - 10px); min-width: 140px; }
  .model-sections button > span:last-child { width: 100%; }
  .model-sections b, .model-sections small { white-space: normal; }
}
@media (max-width: 460px) {
  .domain-context { grid-template-columns: 1fr; }
  .domain-meta, .domain-actions { width: 100%; justify-self: stretch; }
  .domain-actions :deep(.el-button), .domain-actions :deep(.el-dropdown) { flex: 1 1 0; }
  .domain-actions :deep(.el-dropdown .el-button) { width: 100%; }
  .model-sections { display: grid; grid-template-columns: 1fr; gap: 0; }
  .model-sections button { min-width: 0; width: 100%; }
}
</style>
