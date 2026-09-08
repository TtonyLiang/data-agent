<template>
  <div class="model-release-center" v-loading="loading">
    <header class="release-header">
      <div>
        <h2>
          企业模型版本
          <span v-if="currentDomain">· {{ currentDomain.name }}</span>
        </h2>
        <p>将语义资产快照与 Ontology 发布绑定为一个可激活、可回滚的运行版本。</p>
      </div>
      <div class="release-actions">
        <el-button :disabled="!domainId" @click="loadAll">刷新</el-button>
        <el-button type="primary" :disabled="!domainId" @click="openCreate">
          创建统一版本
        </el-button>
      </div>
    </header>

    <el-empty v-if="!loading && !domainId" description="请先选择业务领域" />

    <template v-else-if="domainId">
      <section class="release-summary">
        <div>
          <span>当前激活版本</span>
          <strong>{{ activeRelease ? `V${activeRelease.version}` : '未激活' }}</strong>
          <small>{{ activeRelease?.name || '外部能力调用前必须激活' }}</small>
        </div>
        <div>
          <span>统一版本</span>
          <strong>{{ releases.length }}</strong>
          <small>草稿、已校验、激活及历史版本</small>
        </div>
        <div>
          <span>语义快照</span>
          <strong>{{ semanticSnapshots.length }}</strong>
          <small>指标、规则、映射和模板</small>
        </div>
        <div>
          <span>Ontology 发布</span>
          <strong>{{ ontologyReleases.length }}</strong>
          <small>对象、关系和动作定义</small>
        </div>
      </section>

      <section class="release-table-panel">
        <el-table v-if="releases.length" :data="releases" border>
          <el-table-column label="版本" min-width="210">
            <template #default="{ row }">
              <div class="primary-cell">
                <strong>V{{ row.version }} · {{ row.name }}</strong>
                <code>{{ shortHash(row.model_hash) }}</code>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" effect="plain">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="版本组成" min-width="230">
            <template #default="{ row }">
              <div class="component-links">
                <span>语义快照 #{{ row.semantic_snapshot_id }}</span>
                <span>Ontology #{{ row.ontology_release_id }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ row.description || '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="250" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'draft'"
                link
                type="primary"
                @click="validateRelease(row)"
              >校验</el-button>
              <el-button
                v-if="row.status === 'validated'"
                link
                type="success"
                @click="activateRelease(row)"
              >激活</el-button>
              <el-button
                v-if="row.status === 'active'"
                link
                type="warning"
                @click="deactivateRelease(row)"
              >停用</el-button>
              <el-button
                v-if="row.status === 'retired'"
                link
                type="primary"
                @click="rollbackRelease(row)"
              >回滚并激活</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无统一企业模型版本" />
      </section>

      <el-alert
        class="release-note"
        type="info"
        :closable="false"
        title="运行时优先使用激活版本；修改实时草稿不会改变已激活版本。"
      />
    </template>

    <el-dialog v-model="showCreate" title="创建统一企业模型版本" width="560">
      <el-form :model="form" label-width="110px">
        <el-form-item label="语义快照">
          <el-select v-model="form.semantic_snapshot_id" placeholder="选择语义快照">
            <el-option
              v-for="item in semanticSnapshots"
              :key="item.id"
              :label="`#${item.id} · ${item.name}`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="Ontology 版本">
          <el-select v-model="form.ontology_release_id" placeholder="选择 Ontology 版本">
            <el-option
              v-for="item in ontologyReleases"
              :key="item.id"
              :label="`V${item.version} · ${item.name}`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="版本名称">
          <el-input v-model="form.name" placeholder="例如：贷款业务模型 V1" />
        </el-form-item>
        <el-form-item label="版本说明">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createRelease">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, toRefs, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  activateEnterpriseModelRelease,
  createEnterpriseModelRelease,
  deactivateEnterpriseModelRelease,
  fetchEnterpriseModelReleases,
  fetchOntologyReleases,
  fetchSemanticSnapshots,
  rollbackEnterpriseModelRelease,
  validateEnterpriseModelRelease,
  type EnterpriseModelRelease,
  type OntologyRelease,
  type SemanticDomain,
  type SemanticDomainSnapshot,
} from '../api'

const props = defineProps<{
  domainId: number | null
  currentDomain: SemanticDomain | null
}>()
const { domainId, currentDomain } = toRefs(props)
const releases = ref<EnterpriseModelRelease[]>([])
const semanticSnapshots = ref<SemanticDomainSnapshot[]>([])
const ontologyReleases = ref<OntologyRelease[]>([])
const loading = ref(false)
const saving = ref(false)
const showCreate = ref(false)
const form = reactive({
  semantic_snapshot_id: null as number | null,
  ontology_release_id: null as number | null,
  name: '',
  description: '',
})

const activeRelease = computed(() => releases.value.find((item) => item.status === 'active'))

watch(domainId, loadAll, { immediate: true })

async function loadAll() {
  if (!domainId.value) {
    loading.value = false
    releases.value = []
    semanticSnapshots.value = []
    ontologyReleases.value = []
    return
  }
  const requestedDomainId = domainId.value
  loading.value = true
  try {
    const [nextReleases, nextSnapshots, nextOntologyReleases] = await Promise.all([
      fetchEnterpriseModelReleases(requestedDomainId),
      fetchSemanticSnapshots(requestedDomainId),
      fetchOntologyReleases(requestedDomainId),
    ])
    if (domainId.value !== requestedDomainId) return
    releases.value = nextReleases
    semanticSnapshots.value = nextSnapshots
    ontologyReleases.value = nextOntologyReleases
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    if (domainId.value === requestedDomainId) loading.value = false
  }
}

function openCreate() {
  form.semantic_snapshot_id = semanticSnapshots.value[0]?.id || null
  form.ontology_release_id = ontologyReleases.value[0]?.id || null
  form.name = ''
  form.description = ''
  showCreate.value = true
}

async function createRelease() {
  if (!domainId.value || !form.semantic_snapshot_id || !form.ontology_release_id) {
    ElMessage.warning('请选择语义快照和 Ontology 版本')
    return
  }
  saving.value = true
  try {
    await createEnterpriseModelRelease(domainId.value, {
      semantic_snapshot_id: form.semantic_snapshot_id,
      ontology_release_id: form.ontology_release_id,
      name: form.name || undefined,
      description: form.description,
    })
    showCreate.value = false
    ElMessage.success('统一企业模型草稿已创建')
    await loadAll()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

async function validateRelease(release: EnterpriseModelRelease) {
  try {
    const validated = await validateEnterpriseModelRelease(release.domain_id, release.id, {
      checks: { component_integrity: true },
      errors: [],
      warnings: [],
    })
    if (validated.status === 'validated') {
      ElMessage.success('版本校验通过')
    } else {
      const errors = validated.validation?.errors
      ElMessage.error(
        Array.isArray(errors) && errors.length
          ? errors.map(String).join('；')
          : '版本校验未通过',
      )
    }
    await loadAll()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function activateRelease(release: EnterpriseModelRelease) {
  await confirmAndRun(`激活 V${release.version} 后，运行时将固定使用该版本。`, async () => {
    await activateEnterpriseModelRelease(release.domain_id, release.id)
  })
}

async function deactivateRelease(release: EnterpriseModelRelease) {
  await confirmAndRun('停用后，外部能力调用将因没有激活版本而被阻断。', async () => {
    await deactivateEnterpriseModelRelease(release.domain_id, release.id)
  })
}

async function rollbackRelease(release: EnterpriseModelRelease) {
  await confirmAndRun(`回滚后将重新激活 V${release.version}。`, async () => {
    await rollbackEnterpriseModelRelease(release.domain_id, release.id)
  })
}

async function confirmAndRun(message: string, action: () => Promise<void>) {
  try {
    await ElMessageBox.confirm(message, '确认版本操作', { type: 'warning' })
    await action()
    ElMessage.success('版本状态已更新')
    await loadAll()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error))
  }
}

function statusLabel(status: EnterpriseModelRelease['status']) {
  return ({ draft: '草稿', validated: '已校验', active: '已激活', retired: '已停用' })[status]
}

function statusType(status: EnterpriseModelRelease['status']) {
  return ({ draft: 'info', validated: 'primary', active: 'success', retired: 'warning' } as const)[status]
}

function shortHash(value: string) {
  return value ? `${value.slice(0, 12)}…` : '-'
}

function errorMessage(error: unknown) {
  const candidate = error as { response?: { data?: { detail?: string | { message?: string } } }; message?: string }
  const detail = candidate?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return candidate?.message || '企业模型版本操作失败'
}
</script>

<style scoped>
.model-release-center {
  height: 100%;
  padding: 18px var(--wq-page-gutter) 28px;
  overflow: auto;
  background: var(--wq-bg);
}

.release-header,
.release-actions {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}

.release-header h2 {
  font-size: 18px;
}

.release-header p {
  margin-top: 4px;
  color: var(--wq-muted);
  font-size: 13px;
}

.release-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 16px 0;
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
}

.release-summary > div {
  min-width: 0;
  padding: 14px 16px;
  display: grid;
  gap: 4px;
  border-right: 1px solid var(--wq-border);
}

.release-summary > div:last-child {
  border-right: 0;
}

.release-summary span,
.release-summary small {
  color: var(--wq-muted);
  font-size: 12px;
}

.release-summary strong {
  font-size: 20px;
}

.release-table-panel {
  overflow: hidden;
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
}

.primary-cell,
.component-links {
  display: grid;
  gap: 4px;
}

.primary-cell code,
.component-links {
  color: var(--wq-muted);
  font-size: 12px;
}

.release-note {
  margin-top: 14px;
}

@media (max-width: 900px) {
  .release-header,
  .release-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .release-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
