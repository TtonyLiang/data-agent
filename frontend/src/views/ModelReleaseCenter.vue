<template>
  <div class="model-release-center" v-loading="loading" :aria-busy="loading">
    <header class="release-header">
      <div>
        <h2>
          校验发布与企业模型版本
          <span v-if="currentDomain">· {{ currentDomain.name }}</span>
        </h2>
        <p>先检查当前草稿，再固化语义快照并绑定本体版本，最后激活供运行时和外部能力使用。</p>
      </div>
      <el-button text :disabled="!domainId" @click="loadAll">刷新</el-button>
    </header>

    <el-empty v-if="!loading && !domainId" description="请先选择业务领域" />

    <template v-else-if="domainId">
      <section class="release-flow" aria-label="企业模型发布流程">
        <div :class="{ ready: semanticValidationState === 'success' || semanticValidationState === 'warning' }">
          <span>1</span>
          <p><strong>检查当前草稿</strong><small>语义完整性和查询运行时</small></p>
        </div>
        <i aria-hidden="true">›</i>
        <div :class="{ ready: semanticSnapshots.length > 0 }">
          <span>2</span>
          <p><strong>固化模型版本</strong><small>语义快照绑定本体发布</small></p>
        </div>
        <i aria-hidden="true">›</i>
        <div :class="{ ready: Boolean(activeRelease) }">
          <span>3</span>
          <p><strong>激活并准备调用</strong><small>同步验证检索索引</small></p>
        </div>
      </section>

      <section class="release-section version-section">
        <div class="section-heading">
          <div>
            <h3>固化并管理企业模型版本</h3>
            <p>语义快照保存指标、规则和数据映射，统一版本再将它与已发布的本体定义绑定。</p>
          </div>
          <div class="section-actions">
            <el-button :disabled="!canEditModelRole" @click="handleCreateSnapshot">创建语义快照</el-button>
            <el-button :disabled="semanticSnapshots.length === 0" @click="openSnapshots">管理快照</el-button>
            <el-button
              type="primary"
              :disabled="!canCreateUnifiedRelease"
              @click="openCreate"
            >创建统一版本</el-button>
          </div>
        </div>

        <section class="release-summary" aria-label="企业模型版本概况">
          <div>
            <span>当前激活版本</span>
            <strong>{{ activeRelease ? `V${activeRelease.version}` : '未激活' }}</strong>
            <small>{{ activeRelease?.name || '外部能力调用前必须激活' }}</small>
          </div>
          <div>
            <span>统一版本</span>
            <strong>{{ releases.length }}</strong>
            <small>包含草稿、已校验、激活和历史版本</small>
          </div>
          <div>
            <span>语义快照</span>
            <strong>{{ semanticSnapshots.length }}</strong>
            <small>{{ latestSnapshotText }}</small>
          </div>
          <div>
            <span>本体发布</span>
            <strong>{{ ontologyReleases.length }}</strong>
            <small>对象、关系、状态和动作定义</small>
          </div>
        </section>

        <div v-if="!canCreateUnifiedRelease && canEditModelRole" class="release-prerequisite">
          <strong>创建统一版本前：</strong>
          <span v-if="semanticSnapshots.length === 0">请先创建语义快照。</span>
          <span v-if="ontologyReleases.length === 0">请先在“业务模型”中发布本体版本。</span>
        </div>

        <div class="release-table-panel">
          <el-table v-if="releases.length" :data="releases" :scrollbar-tabindex="-1">
            <el-table-column label="版本" min-width="220">
              <template #default="{ row }">
                <div class="primary-cell">
                  <strong>V{{ row.version }} · {{ row.name }}</strong>
                  <code :title="row.model_hash || ''">{{ shortHash(row.model_hash) }}</code>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="104">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" effect="plain">
                  {{ statusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="版本组成" min-width="260">
              <template #default="{ row }">
                <div class="component-links">
                  <span>{{ semanticSnapshotLabel(row.semantic_snapshot_id) }}</span>
                  <span>{{ ontologyReleaseLabel(row.ontology_release_id) }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="校验结果" min-width="180">
              <template #default="{ row }">{{ releaseValidationText(row) }}</template>
            </el-table-column>
            <el-table-column label="说明" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.description || '-' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="286" fixed="right">
              <template #default="{ row }">
                <div class="table-actions">
                  <el-button
                    link
                    type="primary"
                    @click="handleDiffRelease(row)"
                  >查看差异</el-button>
                  <el-button
                    v-if="row.status === 'draft' && canEditModelRole"
                    link
                    type="primary"
                    @click="validateRelease(row)"
                  >校验版本</el-button>
                  <el-button
                    v-if="row.status === 'validated' && canPublishModelRole"
                    link
                    type="success"
                    @click="activateRelease(row)"
                  >激活</el-button>
                  <el-button
                    v-if="row.status === 'active' && canPublishModelRole"
                    link
                    type="warning"
                    @click="deactivateRelease(row)"
                  >停用</el-button>
                  <el-button
                    v-if="row.status === 'retired' && canPublishModelRole"
                    link
                    type="primary"
                    @click="rollbackRelease(row)"
                  >回滚并激活</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无统一企业模型版本，请先创建语义快照并发布本体版本" />
        </div>

        <el-alert
          class="release-note"
          type="info"
          :closable="false"
          title="已激活版本使用固定快照；后续修改当前草稿，不会自动改变运行中的版本。"
        />
      </section>

      <section class="release-section preflight-section">
        <div class="section-heading">
          <div>
            <h3>发布前检查</h3>
            <p>检查对象、指标、规则和映射是否完整，并确认当前草稿可以装载为查询运行时。</p>
          </div>
        </div>

        <div class="operation-list">
          <article class="operation-row">
            <div class="operation-main">
              <div class="operation-title">
                <strong>业务语义校验</strong>
                <el-tag :type="operationTagType(semanticValidationState)" effect="plain" size="small">
                  {{ operationStatusLabel(semanticValidationState) }}
                </el-tag>
              </div>
              <p>检查业务对象、关系、指标、规则和数据映射之间的引用是否完整。</p>
              <div v-if="semanticValidationResult" class="validation-feedback" :class="semanticValidationState">
                <strong>{{ validationSummary }}</strong>
                <ul v-if="validationIssues.length">
                  <li v-for="item in validationIssues" :key="item">{{ item }}</li>
                </ul>
              </div>
            </div>
            <el-button
              type="primary"
              plain
              :loading="semanticValidationState === 'running'"
              :disabled="!canEditModelRole"
              @click="handleValidateDomain"
            >开始校验</el-button>
          </article>

          <article class="operation-row">
            <div class="operation-main">
              <div class="operation-title">
                <strong>查询运行时检查</strong>
                <el-tag :type="operationTagType(runtimeState)" effect="plain" size="small">
                  {{ operationStatusLabel(runtimeState) }}
                </el-tag>
              </div>
              <p>按当前草稿装载查询资产，用于发布前技术验证；此操作不会创建或激活版本。</p>
              <div v-if="runtimeMessage" class="operation-feedback" :class="runtimeState">
                {{ runtimeMessage }}
              </div>
            </div>
            <el-button
              :loading="runtimeState === 'running'"
              :disabled="!canManageTechnical"
              @click="handleBuildRuntime"
            >构建并检查</el-button>
          </article>
        </div>
      </section>

      <section class="release-section post-release-section">
        <div class="post-release-copy">
          <div class="operation-title">
            <strong>更新验证检索索引</strong>
            <el-tag :type="operationTagType(vectorState)" effect="plain" size="small">
              {{ operationStatusLabel(vectorState) }}
            </el-tag>
          </div>
          <p v-if="activeRelease">
            当前将按已激活的 V{{ activeRelease.version }} 生成语义检索索引，供内置 Agent 验证和能力调用时召回业务语义。
          </p>
          <p v-else>先校验并激活一个统一企业模型版本，再更新供验证使用的检索索引。</p>
          <div v-if="vectorMessage" class="operation-feedback" :class="vectorState">
            {{ vectorMessage }}
          </div>
        </div>
        <el-button
          type="primary"
          :loading="vectorState === 'running'"
          :disabled="!activeRelease || !canManageTechnical"
          @click="handleSyncVector"
        >更新检索索引</el-button>
      </section>
    </template>

    <el-dialog v-model="showCreate" title="创建统一企业模型版本" width="580px" append-to-body>
      <el-form :model="form" label-width="112px" label-position="left">
        <el-form-item label="语义快照" required>
          <el-select v-model="form.semantic_snapshot_id" placeholder="选择已固化的语义快照">
            <el-option
              v-for="item in semanticSnapshots"
              :key="item.id"
              :label="`#${item.id} · ${item.name}`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="本体版本" required>
          <el-select v-model="form.ontology_release_id" placeholder="选择已发布的本体版本">
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
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="记录本次发布包含的业务变化" />
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        title="创建后先执行版本校验，校验通过才可以激活。"
      />
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canCreateUnifiedRelease" @click="createRelease">创建</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="showSnapshotDrawer" title="语义资产快照" size="620px" append-to-body>
      <div class="snapshot-drawer-toolbar">
        <p>快照用于固化当前指标、规则、映射和查询模板，可用于创建统一版本或恢复当前草稿。</p>
        <el-button type="primary" plain :disabled="!canEditModelRole" @click="handleCreateSnapshot">创建快照</el-button>
      </div>
      <el-empty v-if="semanticSnapshots.length === 0" description="暂无语义快照" />
      <div v-else class="snapshot-list">
        <article v-for="item in semanticSnapshots" :key="item.id" class="snapshot-card">
          <div class="snapshot-card-heading">
            <div>
              <strong>#{{ item.id }} · {{ item.name }}</strong>
              <p>{{ item.description || '无说明' }}</p>
            </div>
            <small>{{ formatDateTime(item.created_at) }}</small>
          </div>
          <div class="snapshot-meta">{{ formatSnapshotCounts(item.asset_counts) }}</div>
          <div class="snapshot-actions">
            <el-button size="small" @click="handleDiffSnapshot(item)">查看差异</el-button>
            <el-button v-if="canPublishModelRole" size="small" type="warning" plain @click="handleRollbackSnapshot(item)">
              恢复为当前草稿
            </el-button>
          </div>
        </article>
      </div>
    </el-drawer>

    <el-dialog v-model="showSnapshotDiffDialog" title="语义快照与当前草稿差异" width="780px" append-to-body>
      <div v-if="snapshotDiff" class="snapshot-diff">
        <div class="snapshot-diff-summary">
          <div><span>当前新增</span><strong>{{ snapshotDiffSummary.added }}</strong></div>
          <div><span>当前删除</span><strong>{{ snapshotDiffSummary.removed }}</strong></div>
          <div><span>内容变更</span><strong>{{ snapshotDiffSummary.changed }}</strong></div>
          <div><span>领域配置</span><strong>{{ snapshotDiffSummary.domain_changed ? '有变化' : '无变化' }}</strong></div>
        </div>

        <section v-if="snapshotDomainChanges.length" class="snapshot-diff-section">
          <h4>领域配置差异</h4>
          <div v-for="item in snapshotDomainChanges" :key="String(item.field)" class="snapshot-change-row">
            <strong>{{ diffFieldLabel(String(item.field)) }}</strong>
            <p>当前：{{ formatDiffValue(item.current) }}</p>
            <p>快照：{{ formatDiffValue(item.snapshot) }}</p>
          </div>
        </section>

        <section v-for="section in snapshotAssetDiffSections" :key="section.type" class="snapshot-diff-section">
          <h4>{{ assetTypeName(section.type) }}</h4>
          <p>新增 {{ section.added.length }} 项，删除 {{ section.removed.length }} 项，变更 {{ section.changed.length }} 项</p>
          <div v-if="section.added.length" class="snapshot-key-list"><strong>当前新增：</strong>{{ section.added.join('、') }}</div>
          <div v-if="section.removed.length" class="snapshot-key-list"><strong>快照中存在：</strong>{{ section.removed.join('、') }}</div>
          <div v-if="section.changed.length" class="snapshot-key-list"><strong>内容变更：</strong>{{ snapshotChangedKeys(section.changed) }}</div>
        </section>

        <el-empty
          v-if="!snapshotDomainChanges.length && snapshotAssetDiffSections.length === 0"
          description="当前草稿与该快照没有差异"
        />
      </div>
      <template #footer>
        <el-button @click="showSnapshotDiffDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showReleaseDiffDialog" title="企业模型版本差异与影响" width="820px" append-to-body>
      <div v-if="releaseDiff" class="snapshot-diff">
        <div class="snapshot-diff-summary">
          <div><span>对比版本</span><strong>{{ releaseDiffCurrentLabel }}</strong></div>
          <div><span>基线版本</span><strong>{{ releaseDiffBaselineLabel }}</strong></div>
          <div><span>新增 / 删除</span><strong>{{ releaseDiffSummary.added }} / {{ releaseDiffSummary.removed }}</strong></div>
          <div><span>内容变更</span><strong>{{ releaseDiffSummary.changed }}</strong></div>
        </div>
        <section class="snapshot-diff-section">
          <h4>影响范围</h4>
          <p>受影响对象 {{ releaseImpact.affected_objects.length }} 个，指标 {{ releaseImpact.affected_metrics.length }} 个，查询能力 {{ releaseImpact.affected_capabilities.length }} 个{{ releaseImpact.datasource_changed ? '；默认数据源已变化' : '' }}。</p>
          <div v-if="releaseImpact.affected_objects.length" class="snapshot-key-list"><strong>对象：</strong>{{ releaseImpact.affected_objects.join('、') }}</div>
          <div v-if="releaseImpact.affected_metrics.length" class="snapshot-key-list"><strong>指标：</strong>{{ releaseImpact.affected_metrics.join('、') }}</div>
          <div v-if="releaseImpact.affected_capabilities.length" class="snapshot-key-list"><strong>查询能力：</strong>{{ releaseImpact.affected_capabilities.join('、') }}</div>
        </section>
        <section v-for="section in releaseOntologyDiffSections" :key="section.type" class="snapshot-diff-section">
          <h4>{{ section.title }}</h4>
          <p>新增 {{ section.added.length }} 项，删除 {{ section.removed.length }} 项，变更 {{ section.changed.length }} 项</p>
          <div v-if="section.added.length" class="snapshot-key-list"><strong>当前新增：</strong>{{ section.added.join('、') }}</div>
          <div v-if="section.removed.length" class="snapshot-key-list"><strong>基线中存在：</strong>{{ section.removed.join('、') }}</div>
          <div v-if="section.changed.length" class="snapshot-key-list"><strong>内容变更：</strong>{{ snapshotChangedKeys(section.changed) }}</div>
        </section>
        <el-empty v-if="!releaseDiffHasChanges" :description="releaseDiff?.baseline ? '与基线版本没有差异' : '没有可对比的上一激活版本'" />
      </div>
      <template #footer>
        <el-button @click="showReleaseDiffDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, toRefs, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  activateEnterpriseModelRelease,
  buildSemanticRuntime,
  createEnterpriseModelRelease,
  createSemanticSnapshot,
  deactivateEnterpriseModelRelease,
  diffEnterpriseModelRelease,
  diffSemanticSnapshot,
  fetchEnterpriseModelReleases,
  fetchOntologyReleases,
  fetchSemanticSnapshots,
  rollbackEnterpriseModelRelease,
  rollbackSemanticSnapshot,
  syncSemanticVector,
  validateEnterpriseModelRelease,
  validateSemanticDomain,
  type EnterpriseModelRelease,
  type OntologyRelease,
  type SemanticDomain,
  type SemanticDomainSnapshot,
} from '../api'
import { canEditModel, canPublishModel, isTechnicalUser } from '../stores/auth'
import { formatDateTime } from '../utils/datetime'

type OperationState = 'idle' | 'running' | 'success' | 'warning' | 'error'

interface SemanticValidationResult {
  valid?: boolean
  errors?: unknown[]
  warnings?: unknown[]
}

interface SnapshotDiff {
  summary?: { added?: number; removed?: number; changed?: number; domain_changed?: boolean }
  domain?: Array<Record<string, unknown>>
  assets?: Record<string, {
    added?: unknown[]
    removed?: unknown[]
    changed?: Array<Record<string, unknown>>
  }>
}

interface ReleaseDiffSummary {
  id?: number
  version?: number
  name?: string
  status?: string
}

interface KeyedDiff {
  added?: string[]
  removed?: string[]
  changed?: Array<Record<string, unknown>>
}

interface ReleaseDiff {
  current?: ReleaseDiffSummary
  baseline?: ReleaseDiffSummary | null
  summary?: { added?: number; removed?: number; changed?: number }
  ontology?: {
    object_types?: KeyedDiff
    link_types?: KeyedDiff
    action_types?: KeyedDiff
  }
  impact?: {
    affected_objects?: string[]
    affected_metrics?: string[]
    affected_capabilities?: string[]
    datasource_changed?: boolean
  }
}

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
const showSnapshotDrawer = ref(false)
const showSnapshotDiffDialog = ref(false)
const snapshotDiff = ref<SnapshotDiff | null>(null)
const showReleaseDiffDialog = ref(false)
const releaseDiff = ref<ReleaseDiff | null>(null)
const semanticValidationState = ref<OperationState>('idle')
const semanticValidationResult = ref<SemanticValidationResult | null>(null)
const runtimeState = ref<OperationState>('idle')
const runtimeMessage = ref('')
const vectorState = ref<OperationState>('idle')
const vectorMessage = ref('')

const form = reactive({
  semantic_snapshot_id: null as number | null,
  ontology_release_id: null as number | null,
  name: '',
  description: '',
})

const activeRelease = computed(() => releases.value.find((item) => item.status === 'active'))
const canEditModelRole = computed(() => canEditModel())
const canPublishModelRole = computed(() => canPublishModel())
const canManageTechnical = computed(() => isTechnicalUser())
const canCreateUnifiedRelease = computed(() => Boolean(
  domainId.value
  && canEditModelRole.value
  && semanticSnapshots.value.length
  && ontologyReleases.value.length,
))

const latestSnapshotText = computed(() => {
  const snapshot = semanticSnapshots.value[0]
  return snapshot ? `最近：#${snapshot.id} ${snapshot.name}` : '尚未固化当前语义配置'
})
const validationErrors = computed(() => normalizeIssues(semanticValidationResult.value?.errors))
const validationWarnings = computed(() => normalizeIssues(semanticValidationResult.value?.warnings))
const validationIssues = computed(() => [...validationErrors.value, ...validationWarnings.value])
const validationSummary = computed(() => {
  if (validationErrors.value.length) return `发现 ${validationErrors.value.length} 个阻断问题`
  if (validationWarnings.value.length) return `校验通过，另有 ${validationWarnings.value.length} 条提醒`
  return '校验通过，未发现阻断问题'
})
const snapshotDiffSummary = computed(() => ({
  added: Number(snapshotDiff.value?.summary?.added || 0),
  removed: Number(snapshotDiff.value?.summary?.removed || 0),
  changed: Number(snapshotDiff.value?.summary?.changed || 0),
  domain_changed: Boolean(snapshotDiff.value?.summary?.domain_changed),
}))
const snapshotDomainChanges = computed(() => Array.isArray(snapshotDiff.value?.domain) ? snapshotDiff.value.domain : [])
const releaseDiffSummary = computed(() => ({
  added: Number(releaseDiff.value?.summary?.added || 0),
  removed: Number(releaseDiff.value?.summary?.removed || 0),
  changed: Number(releaseDiff.value?.summary?.changed || 0),
}))
const releaseDiffCurrentLabel = computed(() => {
  const current = releaseDiff.value?.current
  return current ? `V${current.version} · ${current.name}` : '-'
})
const releaseDiffBaselineLabel = computed(() => {
  const baseline = releaseDiff.value?.baseline
  return baseline ? `V${baseline.version} · ${baseline.name}` : '无基线版本'
})
const releaseImpact = computed(() => ({
  affected_objects: Array.isArray(releaseDiff.value?.impact?.affected_objects) ? releaseDiff.value.impact.affected_objects : [],
  affected_metrics: Array.isArray(releaseDiff.value?.impact?.affected_metrics) ? releaseDiff.value.impact.affected_metrics : [],
  affected_capabilities: Array.isArray(releaseDiff.value?.impact?.affected_capabilities) ? releaseDiff.value.impact.affected_capabilities : [],
  datasource_changed: Boolean(releaseDiff.value?.impact?.datasource_changed),
}))
const releaseOntologyDiffSections = computed(() => {
  const ontology = releaseDiff.value?.ontology || {}
  return [
    { type: 'object_types', title: '对象类型', ...(ontology.object_types || { added: [], removed: [], changed: [] }) },
    { type: 'link_types', title: '关系类型', ...(ontology.link_types || { added: [], removed: [], changed: [] }) },
    { type: 'action_types', title: '动作类型', ...(ontology.action_types || { added: [], removed: [], changed: [] }) },
  ].map((section) => ({
    ...section,
    added: Array.isArray(section.added) ? section.added : [],
    removed: Array.isArray(section.removed) ? section.removed : [],
    changed: Array.isArray(section.changed) ? section.changed : [],
  })).filter((section) => section.added.length || section.removed.length || section.changed.length)
})
const releaseDiffHasChanges = computed(() => Boolean(
  releaseDiffSummary.value.added
  || releaseDiffSummary.value.removed
  || releaseDiffSummary.value.changed
  || releaseOntologyDiffSections.value.length
  || releaseImpact.value.affected_objects.length
  || releaseImpact.value.affected_metrics.length
  || releaseImpact.value.affected_capabilities.length,
))
const snapshotAssetDiffSections = computed(() => {
  const assets = snapshotDiff.value?.assets || {}
  return ['concept', 'relation', 'metric', 'rule', 'mapping', 'template']
    .map((type) => ({
      type,
      added: normalizeKeys(assets[type]?.added),
      removed: normalizeKeys(assets[type]?.removed),
      changed: Array.isArray(assets[type]?.changed) ? assets[type].changed : [],
    }))
    .filter((section) => section.added.length || section.removed.length || section.changed.length)
})

watch(domainId, () => {
  resetOperationStates()
  void loadAll()
}, { immediate: true })

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

async function handleValidateDomain() {
  if (!domainId.value) return
  semanticValidationState.value = 'running'
  semanticValidationResult.value = null
  try {
    const result = await validateSemanticDomain(domainId.value) as SemanticValidationResult
    semanticValidationResult.value = result
    if (normalizeIssues(result.errors).length) {
      semanticValidationState.value = 'error'
      ElMessage.error('业务语义校验未通过')
    } else if (normalizeIssues(result.warnings).length) {
      semanticValidationState.value = 'warning'
      ElMessage.warning('业务语义校验通过，但存在提醒')
    } else {
      semanticValidationState.value = 'success'
      ElMessage.success('业务语义校验通过')
    }
  } catch (error) {
    semanticValidationState.value = 'error'
    semanticValidationResult.value = { errors: [errorMessage(error)] }
    ElMessage.error(errorMessage(error))
  }
}

async function handleBuildRuntime() {
  if (!currentDomain.value) return
  runtimeState.value = 'running'
  runtimeMessage.value = ''
  try {
    await buildSemanticRuntime({
      agent_id: currentDomain.value.agent_id || undefined,
      datasource_id: currentDomain.value.datasource_id || undefined,
      domain_id: currentDomain.value.id,
      domain_key: currentDomain.value.domain_key,
    })
    runtimeState.value = 'success'
    runtimeMessage.value = '当前语义草稿已成功装载为查询运行时。'
    ElMessage.success('查询运行时检查通过')
  } catch (error) {
    runtimeState.value = 'error'
    runtimeMessage.value = errorMessage(error, '查询运行时构建失败')
    ElMessage.error(runtimeMessage.value)
  }
}

async function handleSyncVector() {
  if (!domainId.value || !activeRelease.value) return
  vectorState.value = 'running'
  vectorMessage.value = ''
  try {
    const result = await syncSemanticVector(domainId.value) as Record<string, unknown>
    vectorState.value = result.skipped ? 'warning' : 'success'
    vectorMessage.value = String(result.message || '验证检索索引已更新')
    if (result.skipped) ElMessage.warning(vectorMessage.value)
    else ElMessage.success(vectorMessage.value)
  } catch (error) {
    vectorState.value = 'error'
    vectorMessage.value = errorMessage(error, '验证检索索引更新失败')
    ElMessage.error(vectorMessage.value)
  }
}

async function handleCreateSnapshot() {
  if (!currentDomain.value) return
  try {
    const { value } = await ElMessageBox.prompt(
      '请输入本次语义配置的说明，便于创建统一版本或以后恢复。',
      '创建语义资产快照',
      { inputValue: '完成业务口径和数据映射检查' },
    )
    const result = await createSemanticSnapshot(currentDomain.value.id, {
      name: `${currentDomain.value.name} 语义快照`,
      description: value,
    }) as Record<string, unknown>
    ElMessage.success(String(result.message || '语义快照已创建'))
    await loadAll()
    showSnapshotDrawer.value = true
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error, '创建语义快照失败'))
  }
}

async function openSnapshots() {
  if (!domainId.value) return
  try {
    semanticSnapshots.value = await fetchSemanticSnapshots(domainId.value)
    showSnapshotDrawer.value = true
  } catch (error) {
    ElMessage.error(errorMessage(error, '语义快照加载失败'))
  }
}

async function handleDiffRelease(item: EnterpriseModelRelease) {
  if (!domainId.value) return
  try {
    releaseDiff.value = await diffEnterpriseModelRelease(domainId.value, item.id) as ReleaseDiff
    showReleaseDiffDialog.value = true
  } catch (error) {
    ElMessage.error(errorMessage(error, '版本差异加载失败'))
  }
}

async function handleDiffSnapshot(item: SemanticDomainSnapshot) {
  if (!domainId.value) return
  try {
    snapshotDiff.value = await diffSemanticSnapshot(domainId.value, item.id) as SnapshotDiff
    showSnapshotDiffDialog.value = true
  } catch (error) {
    ElMessage.error(errorMessage(error, '快照差异加载失败'))
  }
}

async function handleRollbackSnapshot(item: SemanticDomainSnapshot) {
  if (!currentDomain.value || !canPublishModelRole.value) return
  try {
    await ElMessageBox.confirm(
      `确定把「${currentDomain.value.name}」的当前语义草稿恢复到快照「${item.name}」？当前草稿会被覆盖，已创建和已激活的企业模型版本不会改变。`,
      '恢复语义草稿',
      { type: 'warning' },
    )
    const result = await rollbackSemanticSnapshot(currentDomain.value.id, item.id) as Record<string, unknown>
    resetOperationStates()
    ElMessage.success(String(result.message || '当前语义草稿已恢复'))
    await loadAll()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error, '语义草稿恢复失败'))
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
    ElMessage.warning('请选择语义快照和本体版本')
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
      checks: { component_integrity: true }, errors: [], warnings: [],
    })
    if (validated.status === 'validated') {
      ElMessage.success('统一企业模型版本校验通过')
    } else {
      const errors = normalizeIssues(validated.validation?.errors)
      ElMessage.error(errors.length ? errors.join('；') : '统一企业模型版本校验未通过')
    }
    await loadAll()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function activateRelease(release: EnterpriseModelRelease) {
  await confirmAndRun(`激活 V${release.version} 后，运行时和外部能力将固定使用该版本。`, async () => {
    await activateEnterpriseModelRelease(release.domain_id, release.id)
    vectorState.value = 'idle'
    vectorMessage.value = ''
  })
}

async function deactivateRelease(release: EnterpriseModelRelease) {
  await confirmAndRun('停用后，外部能力调用将因没有激活版本而被阻断。', async () => {
    await deactivateEnterpriseModelRelease(release.domain_id, release.id)
    vectorState.value = 'idle'
    vectorMessage.value = ''
  })
}

async function rollbackRelease(release: EnterpriseModelRelease) {
  await confirmAndRun(`回滚后将重新激活 V${release.version}，运行时会重新固定到该版本。`, async () => {
    await rollbackEnterpriseModelRelease(release.domain_id, release.id)
    vectorState.value = 'idle'
    vectorMessage.value = ''
  })
}

async function confirmAndRun(message: string, action: () => Promise<void>) {
  try {
    await ElMessageBox.confirm(message, '确认版本操作', { type: 'warning' })
    await action()
    ElMessage.success('企业模型版本状态已更新')
    await loadAll()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error))
  }
}

function resetOperationStates() {
  semanticValidationState.value = 'idle'
  semanticValidationResult.value = null
  runtimeState.value = 'idle'
  runtimeMessage.value = ''
  vectorState.value = 'idle'
  vectorMessage.value = ''
  snapshotDiff.value = null
  releaseDiff.value = null
}

function statusLabel(status: EnterpriseModelRelease['status']) {
  return ({ draft: '草稿', validated: '已校验', active: '已激活', retired: '已停用' })[status]
}

function statusType(status: EnterpriseModelRelease['status']) {
  return ({ draft: 'info', validated: 'primary', active: 'success', retired: 'warning' } as const)[status]
}

function operationStatusLabel(status: OperationState) {
  return ({ idle: '待执行', running: '执行中', success: '已通过', warning: '有提醒', error: '未通过' })[status]
}

function operationTagType(status: OperationState) {
  return ({ idle: 'info', running: 'primary', success: 'success', warning: 'warning', error: 'danger' } as const)[status]
}

function semanticSnapshotLabel(snapshotId: number) {
  const item = semanticSnapshots.value.find((snapshot) => snapshot.id === snapshotId)
  return item ? `语义快照 #${item.id} · ${item.name}` : `语义快照 #${snapshotId}`
}

function ontologyReleaseLabel(releaseId: number) {
  const item = ontologyReleases.value.find((release) => release.id === releaseId)
  return item ? `本体 V${item.version} · ${item.name}` : `本体 #${releaseId}`
}

function releaseValidationText(release: EnterpriseModelRelease) {
  const validation = release.validation || {}
  const errors = normalizeIssues(validation.errors)
  const warnings = normalizeIssues(validation.warnings)
  if (errors.length) return `${errors.length} 个阻断问题`
  if (release.status === 'draft') return '等待版本校验'
  if (warnings.length) return `通过，${warnings.length} 条提醒`
  return '校验通过'
}

function formatSnapshotCounts(value: unknown) {
  if (!value || typeof value !== 'object') return '无资产统计'
  const record = value as Record<string, unknown>
  return [
    `对象 ${record.concept ?? 0}`, `关系 ${record.relation ?? 0}`, `指标 ${record.metric ?? 0}`,
    `规则 ${record.rule ?? 0}`, `映射 ${record.mapping ?? 0}`, `模板 ${record.template ?? 0}`,
  ].join('，')
}

function assetTypeName(type: string) {
  return ({ concept: '业务对象语义', relation: '关系查询路径', metric: '指标', rule: '规则', mapping: '数据映射', template: '查询模板' } as Record<string, string>)[type] || type
}

function diffFieldLabel(field: string) {
  return ({ name: '领域名称', description: '业务范围', status: '领域状态', datasource_id: '默认数据源', domain_key: '领域标识' } as Record<string, string>)[field] || field
}

function formatDiffValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function snapshotChangedKeys(items: Array<Record<string, unknown>>) {
  return items.map((item) => String(item.key || '')).filter(Boolean).join('、')
}

function normalizeIssues(value: unknown) {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : []
}

function normalizeKeys(value: unknown) {
  if (!Array.isArray(value)) return []
  return value.map((item) => typeof item === 'string' ? item : String((item as Record<string, unknown>)?.key || item)).filter(Boolean)
}

function shortHash(value: string) {
  return value ? `${value.slice(0, 12)}…` : '-'
}

function errorMessage(error: unknown, fallback = '企业模型版本操作失败') {
  const candidate = error as { response?: { data?: { detail?: string | { message?: string } } }; message?: string }
  const detail = candidate?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return candidate?.message || fallback
}
</script>

<style scoped>
.model-release-center {
  width: 100%;
  min-width: 0;
  max-width: var(--wq-page-max-width);
  height: 100%;
  margin: 0 auto;
  padding: 12px var(--wq-page-gutter) 20px;
  display: flex;
  flex-direction: column;
  overflow: auto;
  color: var(--wq-text);
  background: var(--wq-bg);
}

.release-header,
.section-heading,
.operation-row,
.post-release-section,
.snapshot-card-heading,
.snapshot-drawer-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 18px;
}

.release-header { align-items: center; justify-content: flex-end; padding-bottom: 10px; border-bottom: 1px solid var(--wq-border); }
.release-header h2,
.release-header p { display: none; }
.release-header p,
.section-heading p,
.operation-main > p,
.post-release-copy > p,
.snapshot-drawer-toolbar p { margin: 4px 0 0; color: var(--wq-muted); font-size: 12px; line-height: 1.5; }

.release-flow {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  margin: 10px 0;
  padding: 8px 13px;
  border: 1px solid var(--wq-border);
  border-radius: 7px;
  background: var(--wq-surface);
}
.release-flow > div { display: flex; align-items: center; gap: 8px; min-width: 0; }
.release-flow > div > span {
  display: inline-flex;
  flex: 0 0 25px;
  width: 25px;
  height: 25px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--wq-border-strong);
  border-radius: 50%;
  color: var(--wq-muted);
  font-size: 12px;
  font-weight: 700;
}
.release-flow > div.ready > span { border-color: var(--wq-primary); color: var(--wq-primary-strong); background: var(--wq-primary-soft); }
.release-flow p { display: grid; gap: 2px; margin: 0; min-width: 0; }
.release-flow strong { font-size: 12px; }
.release-flow small { overflow: hidden; color: var(--wq-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.release-flow i { color: var(--wq-subtle); font-size: 18px; font-style: normal; }

.release-section { margin-top: 10px; border: 1px solid var(--wq-border); border-radius: 7px; background: var(--wq-surface); }
.section-heading { align-items: center; padding: 11px 14px; border-bottom: 1px solid var(--wq-border); }
.section-heading h3 { margin: 0; color: var(--wq-text); font-size: 15px; }
.section-heading p { margin-top: 4px; }
.section-actions,
.table-actions,
.snapshot-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.section-actions :deep(.el-button),
.table-actions :deep(.el-button),
.snapshot-actions :deep(.el-button) { margin-left: 0; white-space: nowrap; }

.operation-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.operation-row { align-items: flex-start; min-width: 0; padding: 11px 14px; }
.operation-row + .operation-row { border-left: 1px solid var(--wq-border); }
.operation-main, .post-release-copy { min-width: 0; }
.operation-title { display: flex; align-items: center; gap: 9px; }
.operation-title strong { color: var(--wq-text); font-size: 13px; }
.validation-feedback,
.operation-feedback {
  margin-top: 8px;
  padding: 7px 10px;
  border-left: 3px solid var(--wq-primary);
  border-radius: 4px;
  color: #344054;
  background: #f5f9ff;
  font-size: 12px;
  line-height: 1.55;
}
.validation-feedback.warning, .operation-feedback.warning { border-left-color: var(--wq-warning); color: #854a0e; background: #fffaeb; }
.validation-feedback.error, .operation-feedback.error { border-left-color: var(--wq-danger); color: #b42318; background: #fef3f2; }
.validation-feedback ul { margin: 6px 0 0; padding-left: 18px; }

.release-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 0; border-bottom: 1px solid var(--wq-border); }
.release-summary > div { min-width: 0; padding: 10px 12px; display: grid; gap: 3px; border-right: 1px solid var(--wq-border); }
.release-summary > div:last-child { border-right: 0; }
.release-summary span,
.release-summary small { overflow: hidden; color: var(--wq-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.release-summary strong { font-size: 18px; }
.release-prerequisite { display: flex; gap: 6px; padding: 10px 16px; border-bottom: 1px solid #fedf89; color: #854a0e; background: #fffaeb; font-size: 12px; line-height: 1.5; }
.release-table-panel { overflow: hidden; }
.primary-cell, .component-links { display: grid; gap: 4px; }
.primary-cell code, .component-links { color: var(--wq-muted); font-size: 12px; }
.release-note { margin: 12px 16px 16px; }
.post-release-section { align-items: center; padding: 12px 14px; }

@media (min-width: 761px) and (max-height: 820px) {
  .release-note { margin-block: 8px 10px; }
  .release-table-panel :deep(.el-table__body td.el-table__cell) { padding: 8px 0; }
  .preflight-section .section-heading { padding-block: 9px; }
  .operation-row { padding-block: 9px; }
}

.snapshot-drawer-toolbar { align-items: flex-start; margin-bottom: 16px; padding-bottom: 14px; border-bottom: 1px solid var(--wq-border); }
.snapshot-drawer-toolbar p { max-width: 430px; margin: 0; }
.snapshot-list { display: grid; gap: 10px; }
.snapshot-card { display: grid; gap: 10px; padding: 14px; border: 1px solid var(--wq-border); border-radius: 7px; background: var(--wq-surface); }
.snapshot-card-heading { align-items: flex-start; }
.snapshot-card-heading strong { color: var(--wq-text); font-size: 14px; }
.snapshot-card-heading p { margin: 5px 0 0; color: var(--wq-muted); font-size: 12px; line-height: 1.55; }
.snapshot-card-heading small, .snapshot-meta { color: var(--wq-subtle); font-size: 12px; }
.snapshot-card-heading small { flex: 0 0 auto; }
.snapshot-meta { padding: 8px 10px; border-radius: 5px; background: #f7f9fc; line-height: 1.5; }

.snapshot-diff { display: grid; gap: 14px; }
.snapshot-diff-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--wq-border); border-radius: 7px; overflow: hidden; }
.snapshot-diff-summary > div { min-width: 0; padding: 12px; border-right: 1px solid var(--wq-border); background: #f8fbff; }
.snapshot-diff-summary > div:last-child { border-right: 0; }
.snapshot-diff-summary span, .snapshot-diff-summary strong { display: block; }
.snapshot-diff-summary span { color: var(--wq-subtle); font-size: 12px; }
.snapshot-diff-summary strong { margin-top: 4px; color: var(--wq-text); font-size: 18px; }
.snapshot-diff-section { padding: 12px 14px; border: 1px solid var(--wq-border); border-radius: 7px; background: var(--wq-surface); }
.snapshot-diff-section h4 { margin: 0 0 8px; color: var(--wq-text); font-size: 14px; }
.snapshot-diff-section p, .snapshot-key-list { margin: 6px 0 0; color: #475467; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.snapshot-change-row { padding: 9px 0; border-top: 1px solid var(--wq-border); }
.snapshot-change-row:first-of-type { border-top: 0; }
.snapshot-change-row > strong { font-size: 12px; }

@media (max-width: 1100px) {
  .section-heading { align-items: flex-start; flex-direction: column; }
  .section-actions { justify-content: flex-start; }
  .operation-list { grid-template-columns: 1fr; }
  .operation-row + .operation-row { border-top: 1px solid var(--wq-border); border-left: 0; }
}

@media (max-width: 760px) {
  .model-release-center { padding-inline: 14px; }
  .release-header,
  .operation-row,
  .post-release-section,
  .snapshot-drawer-toolbar,
  .snapshot-card-heading { align-items: flex-start; flex-direction: column; }
  .release-flow { grid-template-columns: 1fr; gap: 10px; }
  .release-flow > i { display: none; }
  .release-summary, .snapshot-diff-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .release-summary > div:nth-child(2), .snapshot-diff-summary > div:nth-child(2) { border-right: 0; }
  .release-summary > div:nth-child(-n + 2), .snapshot-diff-summary > div:nth-child(-n + 2) { border-bottom: 1px solid var(--wq-border); }
  .release-prerequisite { flex-direction: column; }
}
</style>
