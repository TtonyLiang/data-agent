<template>
  <div class="enterprise-model-center" v-loading="domainLoading" :aria-busy="domainLoading">
    <header class="model-center-header">
      <div class="model-center-bar">
        <div class="model-center-title">
          <strong>企业模型</strong>
          <span>围绕业务对象完成建模、数据绑定和版本发布</span>
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
                  <el-dropdown-item v-if="canConfigureData" command="copy" :disabled="!currentDomain">复制企业模型</el-dropdown-item>
                  <el-dropdown-item command="import" divided>导入企业模型包</el-dropdown-item>
                  <el-dropdown-item command="export" :disabled="!currentDomain">导出企业模型包</el-dropdown-item>
                  <el-dropdown-item v-if="canConfigureData" command="delete" :disabled="!currentDomain" divided>删除</el-dropdown-item>
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

      <nav class="model-sections" :class="{ single: !canConfigureData }" aria-label="企业模型建模顺序">
        <button
          type="button"
          :disabled="!domainId"
          :class="{ active: activeSection === 'ontology' }"
          :aria-current="activeSection === 'ontology' ? 'step' : undefined"
          @click="selectSection('ontology')"
        >
          <span><b>业务模型</b><small>对象、关系、指标、规则与动作</small></span>
        </button>
        <button
          v-if="canManage"
          type="button"
          :disabled="!domainId"
          :class="{ active: activeSection === 'semantic' }"
          :aria-current="activeSection === 'semantic' ? 'step' : undefined"
          @click="selectSection('semantic')"
        >
          <span><b>数据绑定</b><small>对象来源、字段、JOIN 与计算</small></span>
        </button>
        <button
          v-if="canManage"
          type="button"
          :disabled="!domainId"
          :class="{ active: activeSection === 'release' }"
          :aria-current="activeSection === 'release' ? 'step' : undefined"
          @click="selectSection('release')"
        >
          <span><b>校验发布</b><small>预览、校验、激活与回滚</small></span>
        </button>
      </nav>
    </header>

    <section class="model-center-workspace" aria-label="企业模型工作区">
      <el-empty
        v-if="!domainId"
        :description="canManage ? '请先新建或选择一个业务领域' : '暂无可访问业务领域，请联系技术人员配置业务领域或验证客户端权限'"
      />
      <div v-else-if="activeSection === 'ontology'" class="business-model-workspace">
        <div class="business-model-switch" role="tablist" aria-label="业务模型工作区">
          <div class="business-model-switch-heading">
            <span>当前工作区</span>
            <strong>业务模型</strong>
            <small>选择要维护的模型内容</small>
          </div>
          <div class="business-model-switch-options">
            <button
              type="button"
              role="tab"
              :aria-selected="businessView === 'ontology'"
              :class="{ active: businessView === 'ontology' }"
              @click="businessView = 'ontology'"
            >
              <span class="business-model-tab-index" aria-hidden="true">01</span>
              <span class="business-model-tab-copy">
                <b>业务对象与动作</b>
                <small>定义对象、关系、状态与动作</small>
              </span>
              <span class="business-model-tab-indicator" aria-hidden="true"></span>
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="businessView === 'metrics'"
              :class="{ active: businessView === 'metrics' }"
              @click="businessView = 'metrics'"
            >
              <span class="business-model-tab-index" aria-hidden="true">02</span>
              <span class="business-model-tab-copy">
                <b>指标与业务规则</b>
                <small>维护指标口径、阈值与业务判断</small>
              </span>
              <span class="business-model-tab-indicator" aria-hidden="true"></span>
            </button>
          </div>
        </div>
        <div class="business-model-content">
          <OntologyWorkbench
            v-if="businessView === 'ontology'"
            :domain-id="domainId"
            :current-domain="currentDomain"
          />
          <KnowledgeConfig
            v-else
            mode="business"
            :domain-id="domainId"
            :current-domain="currentDomain"
            @domain-updated="loadDomains(domainId)"
          />
        </div>
      </div>
      <KnowledgeConfig
        v-else-if="activeSection === 'semantic'"
        mode="binding"
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
        <el-form-item v-if="canConfigureData" label="默认数据源">
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
  exportOntologyBundle,
  exportSemanticDomain,
  fetchAllDatasources,
  fetchOntologyDomains,
  importSemanticDomain,
  importOntologyBundle,
  upsertSemanticDomain,
  type DatasourceItem,
  type SemanticDomain,
  type SemanticDomainRequest,
} from '../api'
import { canEditModel, isTechnicalUser } from '../stores/auth'

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
const businessView = ref<'ontology' | 'metrics'>('ontology')
const canManage = computed(() => canEditModel())
const canConfigureData = computed(() => isTechnicalUser())
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
  // Business users can inspect the data-binding and release sections in
  // read-only mode. The child views keep technical controls disabled; only
  // legacy users without model access stay on the business model section.
  if (!canManage.value) return 'ontology'
  if (route.query.section === 'semantic' || route.query.section === 'release') {
    return route.query.section
  }
  return 'ontology'
})

onMounted(async () => {
  await Promise.all([
    loadDomains(),
    canConfigureData.value ? loadDatasources() : Promise.resolve(),
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
    datasource_id: canConfigureData.value
      ? (domainForm.value.datasource_id ? Number(domainForm.value.datasource_id) : null)
      : (currentDomain.value?.datasource_id || null),
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
    businessView.value = 'ontology'
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
  let copiedDomainId: number | null = null
  try {
    const { value } = await ElMessageBox.prompt(
      '请输入新业务领域标识；对象、关系、动作、指标、规则和数据映射会作为一套企业模型复制。运行实例、发布版本和审计记录不会复制。',
      '复制企业模型',
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
    copiedDomainId = Number(result.id || 0) || null
    if (!copiedDomainId) throw new Error('复制后未返回新业务领域 ID')
    const ontologyBundle = await exportOntologyBundle(currentDomain.value.id, false)
    await importOntologyBundle(copiedDomainId, ontologyBundle, true)
    await loadDomains(copiedDomainId)
    ElMessage.success('企业模型已复制；请校验后创建新的发布版本')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (copiedDomainId) {
      try { await deleteSemanticDomain(copiedDomainId) } catch { /* 保留原始错误提示 */ }
    }
    ElMessage.error(errorMessage(error, '业务领域复制失败'))
  }
}

async function exportCurrentDomain() {
  if (!currentDomain.value) return
  try {
    const [semantic, ontology] = await Promise.all([
      exportSemanticDomain(currentDomain.value.id),
      exportOntologyBundle(currentDomain.value.id, false),
    ])
    const bundle = {
      format: 'wenqu-enterprise-model',
      version: 1,
      exported_at: new Date().toISOString(),
      semantic,
      ontology,
    }
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${currentDomain.value.domain_key}.enterprise-model.json`
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success('企业模型包已导出')
  } catch (error) {
    ElMessage.error(errorMessage(error, '企业模型包导出失败'))
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
  let importedDomainId: number | null = null
  try {
    const bundle = JSON.parse(await file.text())
    const enterpriseBundle = bundle?.format === 'wenqu-enterprise-model'
    const semanticBundle = enterpriseBundle ? bundle.semantic : bundle
    if (!semanticBundle || typeof semanticBundle !== 'object') throw new Error('企业模型包缺少语义与数据资产')
    const result = await importSemanticDomain(semanticBundle)
    importedDomainId = Number(result.id || 0) || null
    if (!importedDomainId) throw new Error('导入后未返回业务领域 ID')
    if (enterpriseBundle) {
      if (!bundle.ontology || typeof bundle.ontology !== 'object') throw new Error('企业模型包缺少业务本体资产')
      await importOntologyBundle(importedDomainId, bundle.ontology, true)
    }
    await loadDomains(importedDomainId)
    ElMessage.success(enterpriseBundle ? '企业模型已导入，请校验后发布' : '旧版语义包已导入；业务对象与动作仍需补充')
  } catch (error) {
    if (importedDomainId) {
      try { await deleteSemanticDomain(importedDomainId) } catch { /* 保留原始错误提示 */ }
    }
    ElMessage.error(errorMessage(error, '企业模型导入失败'))
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
.model-center-bar { width: 100%; max-width: var(--wq-page-max-width); min-height: 54px; margin: 0 auto; padding: 5px var(--wq-page-gutter); display: grid; grid-template-columns: minmax(170px, .48fr) minmax(0, 2.52fr); align-items: center; gap: 16px; border-bottom: 1px solid var(--wq-border); }
.model-center-title { min-width: 0; display: grid; gap: 3px; }
.model-center-title strong { color: var(--wq-text); font-size: 16px; line-height: 1.3; }
.model-center-title span, .domain-meta > span, .domain-field-label { color: var(--wq-muted); font-size: 10px; }
.domain-context { min-width: 0; display: flex; align-items: center; justify-content: flex-end; gap: 12px; }
.domain-field { min-width: 0; display: flex; align-items: center; gap: 9px; }
.domain-field-label { flex: 0 0 auto; font-weight: 650; }
.domain-select { width: 280px; flex: 0 1 280px; }
.domain-meta, .domain-actions { display: flex; align-items: center; gap: 7px; white-space: nowrap; }
.domain-meta > span { max-width: 210px; overflow: hidden; text-overflow: ellipsis; }
.domain-actions { flex: 0 0 auto; }
.model-sections { width: 100%; max-width: var(--wq-page-max-width); min-width: 0; min-height: 38px; margin: 0 auto; padding: 0 var(--wq-page-gutter); display: flex; align-items: stretch; gap: 24px; }
.model-sections.single { max-width: 420px; }
.model-sections button { position: relative; min-width: 145px; min-height: 38px; padding: 3px 2px 4px; display: flex; align-items: center; color: var(--wq-muted); text-align: left; background: transparent; border: 0; border-bottom: 2px solid transparent; border-radius: 0; cursor: pointer; }
.model-sections button:hover:not(:disabled) { color: var(--wq-text); }
.model-sections button:focus-visible { outline: 2px solid var(--wq-primary); outline-offset: -4px; }
.model-sections button.active { color: var(--wq-primary-strong); border-bottom-color: var(--wq-primary); }
.model-sections button:disabled { cursor: not-allowed; opacity: .55; }
.model-sections button > span:last-child { min-width: 0; display: grid; gap: 1px; }
.model-sections b, .model-sections small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-sections b { font-size: 12px; line-height: 1.15; }.model-sections small { color: var(--wq-subtle); font-size: 10px; line-height: 1.15; }
.model-sections button.active small { color: var(--wq-primary-strong); }
.model-center-workspace { min-height: 0; flex: 1; overflow: hidden; }
.model-center-workspace > .page-shell,
.model-center-workspace > .model-release-center { min-height: 0; }
.model-center-workspace > .el-empty { height: 100%; }
.business-model-workspace { height: 100%; min-height: 0; display: flex; flex-direction: column; }
.business-model-switch { flex: 0 0 auto; width: 100%; max-width: var(--wq-page-max-width); margin: 0 auto; padding: 7px var(--wq-page-gutter) 6px; display: grid; grid-template-columns: minmax(0, 1fr); align-items: center; gap: 0; background: var(--wq-bg); border-bottom: 1px solid var(--wq-border); }
.business-model-switch-heading { display: none; }
.business-model-switch-heading > span { color: var(--wq-primary-strong); font-size: 11px; font-weight: 700; line-height: 1.3; }
.business-model-switch-heading strong { color: var(--wq-text); font-size: 15px; line-height: 1.35; }
.business-model-switch-heading small { color: var(--wq-muted); font-size: 11px; line-height: 1.4; }
.business-model-switch-options { display: flex; flex-wrap: wrap; justify-content: flex-start; gap: 8px; width: 100%; }
.business-model-switch button { position: relative; min-width: 0; min-height: 34px; padding: 6px 12px; display: grid; grid-template-columns: 22px minmax(0, 1fr); align-items: center; gap: 8px; color: var(--wq-text); text-align: left; background: var(--wq-surface); border: 1px solid var(--wq-border-strong); border-radius: 7px; cursor: pointer; transition: border-color 160ms ease, background-color 160ms ease, box-shadow 160ms ease, transform 100ms ease; }
.business-model-switch button:hover { border-color: #93b4fb; background: #fbfdff; }
.business-model-switch button:active { transform: scale(.99); }
.business-model-switch button:focus-visible { outline: 2px solid var(--wq-primary); outline-offset: 2px; }
.business-model-switch button.active { color: var(--wq-primary-strong); background: #eaf2ff; border-color: var(--wq-primary); box-shadow: inset 3px 0 0 var(--wq-primary), 0 2px 6px rgba(37, 99, 235, .08); }
.business-model-tab-index { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; color: var(--wq-muted); background: #f2f4f7; border: 1px solid #d0d5dd; border-radius: 5px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10px; font-weight: 700; }
.business-model-switch button.active .business-model-tab-index { color: #fff; background: var(--wq-primary); border-color: var(--wq-primary); }
.business-model-tab-copy { display: grid; gap: 3px; min-width: 0; }
.business-model-tab-copy b, .business-model-tab-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.business-model-tab-copy b { font-size: 12px; line-height: 1.2; }.business-model-tab-copy small { display: none; color: var(--wq-muted); font-size: 10px; line-height: 1.2; }
.business-model-switch button.active .business-model-tab-copy small { color: #175cd3; }
.business-model-tab-indicator { display: none; width: 8px; height: 8px; justify-self: end; border-radius: 50%; background: #cbd5e1; }
.business-model-switch button.active .business-model-tab-indicator { background: var(--wq-primary); box-shadow: 0 0 0 4px rgba(37, 99, 235, .14); }
.business-model-content { flex: 1; min-height: 0; overflow: hidden; }
.file-input { display: none; }
@media (max-width: 1120px) {
  .model-center-bar { grid-template-columns: 170px minmax(0, 1fr); gap: 16px; }
  .domain-context { flex-wrap: wrap; }
  .domain-meta > span { display: none; }
}
@media (min-width: 1121px) and (max-height: 820px) {
  .model-center-title span { display: none; }
  .model-center-bar { min-height: 56px; padding-block: 5px; }
  .model-sections { min-height: 40px; }
  .model-sections button { min-height: 40px; padding-block: 3px; }
  .business-model-switch { padding-block: 7px; }
  .business-model-switch button { min-height: 48px; padding-block: 6px; }
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
  .model-sections button { flex: 1 1 calc(50% - 10px); min-width: 140px; min-height: 50px; padding: 7px 2px 8px; }
  .model-sections button > span:last-child { width: 100%; }
  .model-sections b, .model-sections small { white-space: normal; }
  .model-sections small { line-height: 1.35; }
  .business-model-switch { grid-template-columns: 1fr; gap: 10px; padding: 12px 16px; }
  .business-model-switch-options { max-width: none; justify-content: stretch; }
}
@media (max-width: 460px) {
  .domain-context { grid-template-columns: 1fr; }
  .domain-meta, .domain-actions { width: 100%; justify-self: stretch; }
  .domain-actions :deep(.el-button), .domain-actions :deep(.el-dropdown) { flex: 1 1 0; }
  .domain-actions :deep(.el-dropdown .el-button) { width: 100%; }
  .model-sections { display: grid; grid-template-columns: 1fr; gap: 0; }
  .model-sections button { min-width: 0; width: 100%; }
  .business-model-switch-options { grid-template-columns: 1fr; }
}
</style>
