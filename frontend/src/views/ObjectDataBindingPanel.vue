<template>
  <div class="object-binding-panel" v-loading="loading" :aria-busy="loading">
    <header class="binding-header">
      <div class="binding-title">
        <h2>对象数据绑定</h2>
        <p>
          {{ domainName }}。对象定义来自业务模型，这里只配置业务库的只读数据来源。
        </p>
      </div>
      <el-button :icon="Refresh" :disabled="!domainId || loading" @click="loadObjects">
        刷新
      </el-button>
    </header>

    <section class="binding-guide" role="note" aria-label="数据绑定说明">
      <strong>配置边界</strong>
      <span>不在这里新建对象或修改属性。查询列通过 <code>AS 属性标识</code> 绑定已有属性，预览不会写入业务库或孪生实例。</span>
    </section>

    <section v-if="domainId" class="binding-summary" aria-label="对象数据绑定概览">
      <div><span>业务对象</span><strong>{{ objectTypes.length }}</strong></div>
      <div><span>已配置查询</span><strong>{{ configuredCount }}</strong></div>
      <div><span>已启用同步</span><strong>{{ enabledCount }}</strong></div>
      <div><span>同步异常</span><strong :class="{ danger: failedCount > 0 }">{{ failedCount }}</strong></div>
    </section>

    <el-alert
      v-if="loadError"
      class="load-error"
      type="error"
      :closable="false"
      :title="loadError"
      show-icon
    >
      <template #default>
        <el-button link type="primary" @click="loadObjects">重新加载</el-button>
      </template>
    </el-alert>

    <el-empty v-if="!loading && !domainId" description="请先选择业务领域" />
    <el-empty
      v-else-if="!loading && !loadError && objectTypes.length === 0"
      description="当前领域还没有业务对象，请先在业务模型中创建对象"
    />

    <section v-else-if="objectTypes.length" class="binding-table-section" aria-label="对象数据绑定列表">
      <el-table class="binding-table desktop-table" :data="objectTypes" row-key="id" height="100%">
        <el-table-column label="业务对象" min-width="200">
          <template #default="{ row }">
            <div class="primary-cell">
              <strong>{{ row.name }}</strong>
              <code>{{ row.object_key }}</code>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="对象属性" min-width="280">
          <template #default="{ row }">
            <div class="property-tags" :aria-label="propertyAriaLabel(row)">
              <el-tag
                v-for="property in row.properties"
                :key="property.property_key"
                size="small"
                effect="plain"
                :type="property.property_key === row.primary_property ? 'warning' : 'info'"
              >
                {{ property.name || property.property_key }}
              </el-tag>
              <span v-if="row.properties.length === 0" class="muted">未定义属性</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="主属性" min-width="150">
          <template #default="{ row }">
            <div class="property-identity">
              <strong>{{ primaryPropertyName(row) }}</strong>
              <code>{{ row.primary_property }}</code>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="数据读取" width="132">
          <template #default="{ row }">
            <div class="stacked-cell">
              <el-tag size="small" effect="plain" :type="row.sync_enabled ? 'success' : 'info'">
                {{ row.sync_enabled ? '已启用' : '未启用' }}
              </el-tag>
              <small>上限 {{ row.sync_limit || 200 }} 条</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="来源查询" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="hasSourceQuery(row) ? 'primary' : 'info'">
              {{ hasSourceQuery(row) ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="最近同步" min-width="175">
          <template #default="{ row }">
            <div class="stacked-cell">
              <el-tooltip
                :disabled="!row.last_sync_error"
                :content="row.last_sync_error || ''"
                placement="top"
              >
                <el-tag
                  class="sync-status-tag"
                  size="small"
                  effect="plain"
                  :type="syncStatusType(row)"
                  :tabindex="row.last_sync_error ? 0 : -1"
                >
                  {{ syncStatusLabel(row) }}
                </el-tag>
              </el-tooltip>
              <small v-if="row.last_synced_at">{{ formatDateTime(row.last_synced_at) }}</small>
              <small v-else>尚无同步记录</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="112" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <el-button type="primary" link :icon="Setting" @click="openEditor(row)">
              配置
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-list" aria-label="对象数据绑定列表">
        <article v-for="row in objectTypes" :key="row.id" class="binding-card">
          <header>
            <div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.object_key }}</code></div>
            <el-tag size="small" effect="plain" :type="row.sync_enabled ? 'success' : 'info'">
              {{ row.sync_enabled ? '同步已启用' : '同步未启用' }}
            </el-tag>
          </header>
          <dl>
            <div><dt>主属性</dt><dd>{{ primaryPropertyName(row) }}（{{ row.primary_property }}）</dd></div>
            <div><dt>对象属性</dt><dd>{{ row.properties.length }} 项</dd></div>
            <div><dt>来源查询</dt><dd>{{ hasSourceQuery(row) ? '已配置' : '未配置' }}</dd></div>
            <div><dt>最近同步</dt><dd>{{ syncStatusLabel(row) }}</dd></div>
          </dl>
          <el-button type="primary" plain :icon="Setting" @click="openEditor(row)">配置数据绑定</el-button>
        </article>
      </div>
    </section>

    <el-dialog
      v-model="editorOpen"
      class="binding-editor-dialog"
      :title="editingObject ? `配置数据绑定：${editingObject.name}` : '配置数据绑定'"
      width="900px"
      destroy-on-close
      @opened="focusEditor"
    >
      <template v-if="editingObject">
        <section class="object-definition" aria-label="对象定义">
          <div>
            <span>业务对象</span>
            <strong>{{ editingObject.name }}</strong>
            <code>{{ editingObject.object_key }}</code>
          </div>
          <div>
            <span>主属性</span>
            <strong>{{ primaryPropertyName(editingObject) }}</strong>
            <code>{{ editingObject.primary_property }}</code>
          </div>
          <div>
            <span>属性数量</span>
            <strong>{{ editingObject.properties.length }}</strong>
            <small>属性定义保持不变</small>
          </div>
        </section>

        <section class="property-definition" aria-labelledby="binding-properties-title">
          <header>
            <strong id="binding-properties-title">已有对象属性</strong>
            <span>查询返回列必须使用这些属性标识作为别名。</span>
          </header>
          <div class="property-definition-list">
            <div v-for="property in editingObject.properties" :key="property.property_key">
              <span>{{ property.name }}</span>
              <code>{{ property.property_key }}</code>
              <el-tag v-if="property.property_key === editingObject.primary_property" size="small" type="warning" effect="plain">主属性</el-tag>
              <small>{{ typeLabel(property.data_type) }}</small>
            </div>
          </div>
        </section>

        <el-form class="binding-form" label-position="top" :model="bindingForm">
          <div class="form-grid">
            <el-form-item label="业务表同步">
              <el-switch
                v-model="bindingForm.sync_enabled"
                active-text="启用"
                inactive-text="不启用"
              />
              <span class="form-help">关闭时保留查询配置，但孪生运行不会读取该对象。</span>
            </el-form-item>
            <el-form-item label="单次读取上限">
              <el-input-number
                v-model="bindingForm.sync_limit"
                :min="1"
                :max="1000"
                controls-position="right"
              />
              <span class="form-help">控制单次预览和同步的最大记录数，范围 1-1000。</span>
            </el-form-item>
          </div>

          <div class="binding-mode-switch" role="tablist" aria-label="对象数据绑定方式">
            <button type="button" role="tab" :aria-selected="bindingMode === 'guided'" :class="{ active: bindingMode === 'guided' }" @click="bindingMode = 'guided'">
              选择表和字段
            </button>
            <button type="button" role="tab" :aria-selected="bindingMode === 'sql'" :class="{ active: bindingMode === 'sql' }" @click="bindingMode = 'sql'">
              高级 SQL
            </button>
          </div>

          <template v-if="bindingMode === 'guided'">
            <el-alert v-if="schemaTables.length === 0" type="warning" :closable="false" title="当前数据源没有已采集 Schema，请先采集表结构，或切换到高级 SQL。" />
            <div class="guided-binding-heading">
              <div><strong>选择业务表并绑定字段</strong><span>平台根据属性标识和字段名自动推荐，仍可逐项调整。</span></div>
              <el-button size="small" :disabled="!selectedTableName" @click="autoMapFields">重新自动匹配</el-button>
            </div>
            <el-form-item label="来源业务表">
              <el-select v-model="selectedTableName" filterable placeholder="选择已采集表" @change="handleSourceTableChange">
                <el-option v-for="table in schemaTables" :key="table.table_name" :label="tableLabel(table)" :value="table.table_name" />
              </el-select>
            </el-form-item>
            <div class="field-mapping-list" aria-label="对象属性字段映射">
              <div v-for="property in editingObject.properties" :key="property.property_key" class="field-mapping-row">
                <div><strong>{{ property.name }}</strong><code>{{ property.property_key }}</code></div>
                <span aria-hidden="true">对应</span>
                <el-select v-model="propertyMappings[property.property_key]" clearable filterable placeholder="选择数据库字段" :aria-label="`为${property.name || property.property_key}选择数据库字段`">
                  <el-option v-for="column in sourceTableColumns" :key="column.column_name" :label="columnLabel(column)" :value="column.column_name" />
                </el-select>
                <el-tag v-if="property.property_key === editingObject.primary_property" type="warning" effect="plain" size="small">主属性</el-tag>
                <span v-else></span>
              </div>
            </div>
            <details class="generated-query-preview">
              <summary>查看自动生成的只读查询</summary>
              <pre>{{ effectiveSourceQuery || '请先选择业务表和字段' }}</pre>
            </details>
          </template>

          <el-form-item v-else label="只读同步 SELECT">
            <el-input
              ref="queryInput"
              v-model="bindingForm.source_query"
              class="query-input"
              type="textarea"
              :rows="9"
              spellcheck="false"
              placeholder="SELECT application_id AS application_id, status AS approval_status FROM loan_application ORDER BY application_id"
              @keydown.ctrl.enter.prevent="previewMapping"
              @keydown.meta.enter.prevent="previewMapping"
            />
            <span class="form-help">
              只支持只读查询，并且必须包含稳定的 ORDER BY。按 Ctrl/Command + Enter 可执行映射预览。
            </span>
          </el-form-item>

          <div class="preview-action-bar" role="note">
            <span>预览会检查数据权限、返回列、主属性完整性和样例数据，不会保存配置。</span>
            <el-button
              type="primary"
              plain
              :icon="View"
              :loading="previewLoading"
              :disabled="!canPreview"
              @click="previewMapping"
            >
              预览映射
            </el-button>
          </div>
        </el-form>
      </template>

      <template #footer>
        <div class="editor-footer">
          <span>保存只更新当前对象的数据绑定，业务定义、属性和状态保持不变。</span>
          <div>
            <el-button @click="editorOpen = false">取消</el-button>
            <el-button type="primary" :loading="saving" @click="saveBinding">保存绑定</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="previewOpen"
      class="mapping-preview-dialog"
      title="对象映射预览"
      width="960px"
      append-to-body
    >
      <template v-if="previewResult">
        <el-alert
          :type="previewResult.valid ? 'success' : 'error'"
          :closable="false"
          show-icon
          :title="previewResult.valid ? '映射检查通过' : '映射检查未通过'"
          :description="previewResult.valid ? '可以保存数据绑定并进入模型校验。' : '请先处理错误，再重新预览。'"
        />

        <section class="preview-summary" aria-label="映射预览概览">
          <div><span>识别源表</span><strong :title="previewResult.query.tables.join('、')">{{ previewResult.query.tables.join('、') || '未识别' }}</strong></div>
          <div><span>可用记录</span><strong>{{ previewResult.statistics.available ? previewResult.statistics.total_rows ?? '未知' : '未知' }}</strong></div>
          <div><span>属性覆盖</span><strong>{{ previewResult.mapping.mapped.length }} / {{ editingObject?.properties.length || 0 }}</strong></div>
          <div><span>主属性重复</span><strong>{{ previewResult.statistics.duplicate_primary_rows ?? '未知' }}</strong></div>
        </section>

        <section class="preview-section">
          <h3>字段检查</h3>
          <div v-if="previewResult.mapping.missing.length" class="issue-list error-list">
            <span v-for="item in previewResult.mapping.missing" :key="item.property_key">
              缺少 {{ item.name }}（{{ item.property_key }}）
            </span>
          </div>
          <p v-else class="success-text">查询结果已覆盖全部对象属性。</p>
          <p v-if="previewResult.mapping.unmapped_columns.length" class="warning-text">
            未绑定查询列：{{ previewResult.mapping.unmapped_columns.join('、') }}
          </p>
        </section>

        <section v-if="previewResult.errors.length" class="preview-section">
          <h3>错误</h3>
          <div class="issue-list error-list">
            <span v-for="(item, index) in previewResult.errors" :key="index">{{ previewIssueText(item) }}</span>
          </div>
        </section>

        <section v-if="previewResult.warnings.length" class="preview-section">
          <h3>提醒</h3>
          <div class="issue-list warning-list">
            <span v-for="(item, index) in previewResult.warnings" :key="index">{{ previewIssueText(item) }}</span>
          </div>
        </section>

        <section class="preview-section">
          <h3>样例数据（{{ previewResult.statistics.sample_rows }} 行）</h3>
          <el-table v-if="previewResult.sample_rows.length" :data="previewResult.sample_rows" border size="small" max-height="300">
            <el-table-column
              v-for="property in editingObject?.properties || []"
              :key="property.property_key"
              :label="property.name || property.property_key"
              :prop="property.property_key"
              min-width="140"
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ previewValue(row[property.property_key]) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="没有返回样例数据" :image-size="64" />
        </section>
      </template>
      <el-empty v-else description="尚未执行映射预览" />
      <template #footer><el-button @click="previewOpen = false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, toRefs, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Setting, View } from '@element-plus/icons-vue'
import {
  fetchDatasourceSchema,
  fetchOntologyObjectTypes,
  previewOntologyObjectMapping,
  saveOntologyObjectType,
  type DatasourceColumnMeta,
  type DatasourceTableMeta,
  type OntologyMappingPreviewResult,
  type OntologyObjectType,
  type OntologyPropertyType,
  type SemanticDomain,
} from '../api'
import { formatDateTime } from '../utils/datetime'

const props = defineProps<{
  domainId: number | null
  currentDomain?: SemanticDomain | null
}>()
const emit = defineEmits<{
  (event: 'updated'): void
}>()

const { domainId } = toRefs(props)
const objectTypes = ref<OntologyObjectType[]>([])
const schemaTables = ref<DatasourceTableMeta[]>([])
const loading = ref(false)
const saving = ref(false)
const previewLoading = ref(false)
const loadError = ref('')
const editorOpen = ref(false)
const previewOpen = ref(false)
const editingObject = ref<OntologyObjectType | null>(null)
const previewResult = ref<OntologyMappingPreviewResult | null>(null)
const queryInput = ref<{ focus: () => void }>()
const bindingForm = reactive({
  sync_enabled: false,
  sync_limit: 200,
  source_query: '',
})
const bindingMode = ref<'guided' | 'sql'>('guided')
const selectedTableName = ref('')
const propertyMappings = reactive<Record<string, string>>({})

const domainName = computed(() => props.currentDomain?.name || '当前业务领域')
const configuredCount = computed(() => objectTypes.value.filter(hasSourceQuery).length)
const enabledCount = computed(() => objectTypes.value.filter((item) => item.sync_enabled).length)
const failedCount = computed(() => objectTypes.value.filter((item) => item.last_sync_status === 'failed').length)
const sourceTableColumns = computed(() => (
  schemaTables.value.find(item => item.table_name === selectedTableName.value)?.columns || []
))
const effectiveSourceQuery = computed(() => (
  bindingMode.value === 'guided' ? buildGuidedSourceQuery() : cleanText(bindingForm.source_query)
))
const canPreview = computed(() => Boolean(
  domainId.value
  && editingObject.value
  && effectiveSourceQuery.value
  && editingObject.value.primary_property
  && editingObject.value.properties.length,
))

watch(() => [domainId.value, props.currentDomain?.datasource_id] as const, () => {
  objectTypes.value = []
  loadError.value = ''
  editorOpen.value = false
  previewOpen.value = false
  editingObject.value = null
  previewResult.value = null
  void Promise.all([loadObjects(), loadSchema()])
}, { immediate: true })

defineExpose({ refresh: loadObjects })

async function loadObjects() {
  if (!domainId.value) {
    objectTypes.value = []
    loadError.value = ''
    loading.value = false
    return
  }
  const requestedDomainId = domainId.value
  loading.value = true
  loadError.value = ''
  try {
    const nextObjects = await fetchOntologyObjectTypes(requestedDomainId)
    if (domainId.value !== requestedDomainId) return
    objectTypes.value = nextObjects
  } catch (error) {
    if (domainId.value !== requestedDomainId) return
    objectTypes.value = []
    loadError.value = `对象数据绑定加载失败：${errorMessage(error)}`
  } finally {
    if (domainId.value === requestedDomainId) loading.value = false
  }
}

async function loadSchema() {
  const datasourceId = props.currentDomain?.datasource_id
  if (!datasourceId) {
    schemaTables.value = []
    return
  }
  try {
    schemaTables.value = await fetchDatasourceSchema(Number(datasourceId))
  } catch {
    schemaTables.value = []
  }
}

function openEditor(row: OntologyObjectType) {
  editingObject.value = cloneObject(row)
  bindingForm.sync_enabled = Boolean(row.sync_enabled)
  bindingForm.sync_limit = normalizeLimit(row.sync_limit)
  bindingForm.source_query = row.source_query || ''
  hydrateGuidedBinding(row.source_query || '')
  previewResult.value = null
  editorOpen.value = true
}

function focusEditor() {
  requestAnimationFrame(() => queryInput.value?.focus())
}

async function saveBinding() {
  if (!domainId.value || !editingObject.value) return
  const sourceQuery = effectiveSourceQuery.value
  if (bindingForm.sync_enabled && !sourceQuery) {
    ElMessage.warning('启用业务表同步时必须配置只读 SELECT')
    queryInput.value?.focus()
    return
  }

  const requestedDomainId = domainId.value
  const objectDefinition = cloneObject(editingObject.value)
  const payload: Record<string, unknown> = {
    ...objectDefinition,
    domain_id: requestedDomainId,
    sync_enabled: Boolean(bindingForm.sync_enabled),
    sync_limit: normalizeLimit(bindingForm.sync_limit),
    source_query: sourceQuery,
    properties: cloneValue(objectDefinition.properties || []),
  }
  removeRuntimeFields(payload)

  saving.value = true
  try {
    await saveOntologyObjectType(requestedDomainId, payload)
    if (domainId.value !== requestedDomainId) return
    ElMessage.success('对象数据绑定已保存')
    editorOpen.value = false
    await loadObjects()
    emit('updated')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

async function previewMapping() {
  if (!domainId.value || !editingObject.value || !canPreview.value || previewLoading.value) return
  const requestedDomainId = domainId.value
  const objectDefinition = cloneObject(editingObject.value)
  const payload: Record<string, unknown> = {
    ...objectDefinition,
    domain_id: requestedDomainId,
    sync_enabled: Boolean(bindingForm.sync_enabled),
    sync_limit: normalizeLimit(bindingForm.sync_limit),
    source_query: effectiveSourceQuery.value,
    properties: cloneValue(objectDefinition.properties || []),
  }
  removeRuntimeFields(payload)

  previewLoading.value = true
  previewResult.value = null
  try {
    const result = await previewOntologyObjectMapping(requestedDomainId, payload)
    if (domainId.value !== requestedDomainId) return
    previewResult.value = result
    previewOpen.value = true
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    previewLoading.value = false
  }
}

function handleSourceTableChange() {
  for (const key of Object.keys(propertyMappings)) delete propertyMappings[key]
  autoMapFields()
}

function autoMapFields() {
  if (!editingObject.value || !selectedTableName.value) return
  const columns = sourceTableColumns.value
  const used = new Set<string>()
  for (const property of editingObject.value.properties) {
    const existing = propertyMappings[property.property_key]
    if (existing && columns.some(column => column.column_name === existing)) {
      used.add(existing)
      continue
    }
    const propertyTokens = normalizedTokens(`${property.property_key} ${property.name}`)
    const exact = columns.find(column => normalizeName(column.column_name) === normalizeName(property.property_key))
    const semantic = columns.find(column => {
      const columnTokens = normalizedTokens(`${column.column_name} ${column.column_comment || ''}`)
      return columnTokens.some(token => propertyTokens.includes(token))
    })
    const match = exact || semantic
    if (match && !used.has(match.column_name)) {
      propertyMappings[property.property_key] = match.column_name
      used.add(match.column_name)
    }
  }
}

function hydrateGuidedBinding(sourceQuery: string) {
  for (const key of Object.keys(propertyMappings)) delete propertyMappings[key]
  selectedTableName.value = ''
  const query = cleanText(sourceQuery)
  if (!query) {
    bindingMode.value = schemaTables.value.length ? 'guided' : 'sql'
    return
  }
  const tableMatch = query.match(/\bFROM\s+`?([A-Za-z_][A-Za-z0-9_]*)`?/i)
  const selectMatch = query.match(/^\s*SELECT\s+([\s\S]+?)\s+FROM\s+/i)
  const tableName = tableMatch?.[1] || ''
  if (!tableName || !selectMatch || !schemaTables.value.some(item => item.table_name === tableName)) {
    bindingMode.value = 'sql'
    return
  }
  selectedTableName.value = tableName
  const selectParts = selectMatch[1].split(',').map(part => part.trim()).filter(Boolean)
  const parsedMappings: Array<{ propertyKey: string; columnName: string }> = []
  for (const part of selectParts) {
    const match = part.match(/^(?:`?[A-Za-z_][A-Za-z0-9_]*`?\.)?`?([A-Za-z_][A-Za-z0-9_]*)`?\s+AS\s+`?([A-Za-z_][A-Za-z0-9_]*)`?$/i)
    if (!match) {
      bindingMode.value = 'sql'
      selectedTableName.value = ''
      return
    }
    parsedMappings.push({ propertyKey: match[2], columnName: match[1] })
  }
  for (const item of parsedMappings) propertyMappings[item.propertyKey] = item.columnName
  const recognized = editingObject.value?.properties.some(item => propertyMappings[item.property_key])
  bindingMode.value = recognized ? 'guided' : 'sql'
}

function buildGuidedSourceQuery() {
  if (!editingObject.value || !selectedTableName.value) return ''
  const selectedMappings = editingObject.value.properties
    .map(property => ({ property, column: cleanText(propertyMappings[property.property_key]) }))
    .filter(item => item.column)
  if (!selectedMappings.length) return ''
  const selectList = selectedMappings
    .map(item => `${quoteIdentifier(item.column)} AS ${quoteIdentifier(item.property.property_key)}`)
    .join(',\n  ')
  const primaryColumn = cleanText(propertyMappings[editingObject.value.primary_property])
  const orderBy = primaryColumn ? `\nORDER BY ${quoteIdentifier(primaryColumn)}` : ''
  return `SELECT\n  ${selectList}\nFROM ${quoteIdentifier(selectedTableName.value)}${orderBy}`
}

function tableLabel(table: DatasourceTableMeta) {
  return table.table_comment ? `${table.table_comment} (${table.table_name})` : table.table_name
}

function columnLabel(column: DatasourceColumnMeta) {
  return column.column_comment
    ? `${column.column_comment} (${column.column_name})`
    : `${column.column_name} · ${column.data_type}`
}

function quoteIdentifier(value: string) {
  return `\`${value.replace(/`/g, '``')}\``
}

function normalizeName(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '')
}

function normalizedTokens(value: string) {
  return value
    .toLowerCase()
    .split(/[^a-z0-9\u4e00-\u9fff]+/)
    .map(item => item.trim())
    .filter(item => item.length > 1)
}

function cloneObject(value: OntologyObjectType): OntologyObjectType {
  return cloneValue(value)
}

function cloneValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function removeRuntimeFields(payload: Record<string, unknown>) {
  for (const key of ['last_sync_status', 'last_sync_count', 'last_sync_total', 'last_sync_error', 'last_synced_at']) {
    delete payload[key]
  }
}

function cleanText(value: unknown) {
  return String(value ?? '').trim()
}

function normalizeLimit(value: unknown) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 200
  return Math.min(Math.max(Math.trunc(parsed), 1), 1000)
}

function hasSourceQuery(row: OntologyObjectType) {
  return Boolean(cleanText(row.source_query))
}

function primaryPropertyName(row: OntologyObjectType) {
  return row.properties.find((item) => item.property_key === row.primary_property)?.name || row.primary_property || '未设置'
}

function propertyAriaLabel(row: OntologyObjectType) {
  if (!row.properties.length) return `${row.name}未定义属性`
  return `${row.name}包含属性：${row.properties.map((item) => item.name || item.property_key).join('、')}`
}

function syncStatusLabel(row: OntologyObjectType) {
  if (!row.sync_enabled) return '未启用'
  if (!row.last_sync_status) return '等待首次同步'
  return ({ succeeded: '同步成功', partial: '部分成功', failed: '同步失败' } as Record<string, string>)[row.last_sync_status] || row.last_sync_status
}

function syncStatusType(row: OntologyObjectType): 'success' | 'warning' | 'danger' | 'info' {
  if (!row.sync_enabled || !row.last_sync_status) return 'info'
  if (row.last_sync_status === 'succeeded') return 'success'
  if (row.last_sync_status === 'partial') return 'warning'
  return 'danger'
}

function typeLabel(type: OntologyPropertyType) {
  return ({
    string: '短文本', text: '长文本', integer: '整数', number: '数字', boolean: '布尔值',
    date: '日期', datetime: '时间', json: 'JSON',
  } as Record<OntologyPropertyType, string>)[type] || type
}

function previewIssueText(item: Record<string, unknown>) {
  return cleanText(item.message) || cleanText(item.code) || '检查未通过'
}

function previewValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function errorMessage(error: unknown) {
  const candidate = error as {
    message?: string
    response?: { data?: { detail?: string | { message?: string } | Array<{ msg?: string }> } }
  }
  const detail = candidate?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => cleanText(item?.msg)).filter(Boolean)
    if (messages.length) return messages.slice(0, 3).join('；')
  }
  if (detail && typeof detail === 'object' && 'message' in detail) return cleanText(detail.message)
  return cleanText(candidate?.message) || '操作失败'
}
</script>

<style scoped>
.object-binding-panel {
  width: 100%;
  max-width: none;
  height: 100%;
  min-width: 0;
  min-height: 0;
  margin: 0 auto;
  padding: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--wq-text);
}

.binding-header {
  flex: 0 0 auto;
  min-height: 52px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--wq-border);
}

.binding-title { min-width: 0; }
.binding-title h2 { margin: 0; color: var(--wq-text); font-size: 20px; line-height: 1.25; }
.binding-title p { margin: 4px 0 0; color: var(--wq-muted); font-size: 12px; line-height: 1.45; }

.binding-guide {
  flex: 0 0 auto;
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 6px;
  padding: 6px 10px;
  border: 1px solid #b2ddff;
  border-left: 3px solid var(--wq-primary);
  border-radius: 6px;
  background: #f5f9ff;
  color: var(--wq-muted);
  font-size: 11px;
  line-height: 1.5;
}
.binding-guide strong { flex: 0 0 auto; color: var(--wq-text); }
.binding-guide code { color: var(--wq-primary-strong); }

.binding-summary {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 6px 0;
  border: 1px solid var(--wq-border);
  border-radius: 7px;
  overflow: hidden;
  background: var(--wq-surface);
}
.binding-summary > div { min-width: 0; padding: 6px 10px; }
.binding-summary > div + div { border-left: 1px solid var(--wq-border); }
.binding-summary span { display: block; color: var(--wq-muted); font-size: 11px; }
.binding-summary strong { display: block; margin-top: 1px; color: var(--wq-text); font-size: 16px; font-weight: 680; }
.binding-summary strong.danger { color: var(--wq-danger); }

.load-error { flex: 0 0 auto; margin: 0 0 10px; }
.binding-table-section { flex: 1; min-width: 0; min-height: 0; overflow: hidden; border: 1px solid var(--wq-border); border-radius: 7px; background: var(--wq-surface); }
.binding-table { width: 100%; height: 100%; }
.binding-table :deep(.el-table__header-wrapper th.el-table__cell) { color: #475467; background: #f5f7fa; font-size: 12px; font-weight: 680; }
.binding-table :deep(.el-table__body td.el-table__cell) { padding: 9px 0; }
.binding-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: #f5f9ff !important; }

@media (min-width: 921px) and (max-height: 820px) {
  .binding-table :deep(.el-table__body td.el-table__cell) { padding: 7px 0; }
  .property-tags { gap: 3px; }
  .property-tags :deep(.el-tag) { height: 22px; }
}

.primary-cell, .property-identity, .stacked-cell { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; min-width: 0; }
.primary-cell strong, .property-identity strong { overflow: hidden; max-width: 100%; color: var(--wq-text); font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
code { color: #344054; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; overflow-wrap: anywhere; }
.stacked-cell small, .object-definition small { color: var(--wq-muted); font-size: 11px; line-height: 1.35; }
.sync-status-tag { max-width: 100%; }
.muted { color: var(--wq-muted); font-size: 12px; }

.property-tags { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; padding: 2px 0; }
.property-tags :deep(.el-tag) { max-width: 150px; }
.property-tags :deep(.el-tag__content) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.mobile-list { display: none; }

:deep(.binding-editor-dialog), :deep(.mapping-preview-dialog) { max-width: calc(100vw - 32px); }
:deep(.binding-editor-dialog .el-dialog__body), :deep(.mapping-preview-dialog .el-dialog__body) { max-height: calc(100vh - 190px); overflow-y: auto; padding-top: 16px; }

.object-definition {
  display: grid;
  grid-template-columns: 1.4fr 1.2fr .8fr;
  border: 1px solid var(--wq-border);
  border-radius: 7px;
  background: #f8fafc;
}
.object-definition > div { min-width: 0; display: grid; align-content: start; gap: 3px; padding: 11px 13px; }
.object-definition > div + div { border-left: 1px solid var(--wq-border); }
.object-definition span { color: var(--wq-muted); font-size: 11px; }
.object-definition strong { overflow: hidden; color: var(--wq-text); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }

.property-definition { margin-top: 16px; }
.property-definition > header { display: flex; align-items: baseline; gap: 9px; margin-bottom: 8px; }
.property-definition > header strong { color: var(--wq-text); font-size: 13px; }
.property-definition > header span { color: var(--wq-muted); font-size: 11px; }
.property-definition-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.property-definition-list > div { min-width: 0; display: grid; grid-template-columns: minmax(90px, 1fr) minmax(110px, 1.2fr) auto 54px; align-items: center; gap: 7px; min-height: 34px; padding: 5px 9px; border: 1px solid var(--wq-border); border-radius: 5px; background: var(--wq-surface); }
.property-definition-list span { overflow: hidden; color: var(--wq-text); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.property-definition-list small { color: var(--wq-muted); font-size: 11px; text-align: right; }

.binding-form { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--wq-border); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.form-help { display: block; margin-top: 5px; color: var(--wq-muted); font-size: 11px; line-height: 1.5; }
.query-input :deep(textarea) { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 1.6; }

.binding-mode-switch { display: inline-flex; gap: 4px; margin-bottom: 14px; padding: 3px; border: 1px solid var(--wq-border); border-radius: 7px; background: #f3f6fa; }
.binding-mode-switch button { min-height: 32px; padding: 0 13px; color: var(--wq-muted); background: transparent; border: 0; border-radius: 5px; cursor: pointer; }
.binding-mode-switch button:hover { color: var(--wq-text); }
.binding-mode-switch button:focus-visible { outline: 2px solid var(--wq-primary); outline-offset: 1px; }
.binding-mode-switch button.active { color: var(--wq-primary-strong); background: #fff; box-shadow: 0 1px 2px rgba(16, 24, 40, .08); }

.guided-binding-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin: 15px 0 12px; }
.guided-binding-heading > div { display: grid; gap: 3px; }
.guided-binding-heading strong { color: var(--wq-text); font-size: 13px; }
.guided-binding-heading span { color: var(--wq-muted); font-size: 11px; }
.field-mapping-list { display: grid; gap: 6px; margin-bottom: 12px; }
.field-mapping-row { display: grid; grid-template-columns: minmax(150px, .9fr) 44px minmax(220px, 1.2fr) 58px; align-items: center; gap: 8px; min-height: 46px; padding: 7px 9px; border: 1px solid var(--wq-border); border-radius: 6px; background: #f8fafc; }
.field-mapping-row > div { min-width: 0; display: grid; gap: 2px; }
.field-mapping-row strong { overflow: hidden; color: var(--wq-text); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.field-mapping-row > span { color: var(--wq-subtle); font-size: 11px; text-align: center; }
.field-mapping-row :deep(.el-select) { width: 100%; }
.generated-query-preview { margin: 10px 0 14px; padding: 0 11px; border: 1px solid var(--wq-border); border-radius: 6px; background: #f8fafc; }
.generated-query-preview summary { padding: 9px 0; color: var(--wq-muted); font-size: 11px; cursor: pointer; }
.generated-query-preview pre { max-height: 220px; margin: 0 0 10px; overflow: auto; padding: 10px; border-radius: 5px; background: #111827; color: #d1d5db; font: 11px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; }

.preview-action-bar { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-top: -2px; padding: 10px 12px; border: 1px solid #b2ddff; border-radius: 6px; background: #f5f9ff; }
.preview-action-bar span { color: var(--wq-muted); font-size: 12px; line-height: 1.5; }
.preview-action-bar .el-button { flex: 0 0 auto; margin-left: 0; white-space: nowrap; }

.editor-footer { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.editor-footer > span { color: var(--wq-muted); font-size: 11px; text-align: left; line-height: 1.45; }
.editor-footer > div { flex: 0 0 auto; display: flex; gap: 8px; }

.preview-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 14px; }
.preview-summary > div { min-width: 0; padding: 10px 12px; border: 1px solid var(--wq-border); border-radius: 6px; background: #f8fafc; }
.preview-summary span { display: block; color: var(--wq-muted); font-size: 11px; }
.preview-summary strong { display: block; margin-top: 3px; overflow: hidden; color: var(--wq-text); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.preview-section { margin-top: 17px; }
.preview-section h3 { margin: 0 0 8px; color: var(--wq-text); font-size: 13px; }
.preview-section p { margin: 0; font-size: 12px; line-height: 1.5; }
.issue-list { display: grid; gap: 5px; padding: 8px 10px; border-radius: 5px; font-size: 12px; line-height: 1.5; }
.error-list { color: #b42318; background: #fef3f2; }
.warning-list { color: #b54708; background: #fffaeb; }
.success-text { color: #067647; }
.warning-text { margin-top: 7px !important; color: #b54708; }

@media (max-width: 920px) {
  .object-binding-panel { overflow-y: auto; }
  .desktop-table { display: none; }
  .binding-table-section { flex: 0 0 auto; overflow: visible; border: 0; background: transparent; }
  .mobile-list { display: grid; gap: 10px; padding-bottom: 8px; }
  .binding-card { padding: 13px; border: 1px solid var(--wq-border); border-radius: 7px; background: var(--wq-surface); }
  .binding-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .binding-card dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px 14px; margin: 13px 0; }
  .binding-card dl > div { min-width: 0; }
  .binding-card dt { color: var(--wq-muted); font-size: 11px; }
  .binding-card dd { margin: 3px 0 0; color: var(--wq-text); font-size: 12px; overflow-wrap: anywhere; }
  .binding-card > .el-button { width: 100%; margin-left: 0; }
  .property-definition-list { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .object-binding-panel { padding: 0; }
  .binding-header { align-items: flex-start; flex-direction: column; gap: 10px; padding: 15px 0 12px; }
  .binding-guide { align-items: flex-start; flex-direction: column; gap: 3px; }
  .binding-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .binding-summary > div:nth-child(3) { border-left: 0; border-top: 1px solid var(--wq-border); }
  .binding-summary > div:nth-child(4) { border-top: 1px solid var(--wq-border); }
  .object-definition, .form-grid, .preview-summary { grid-template-columns: 1fr; }
  .object-definition > div + div { border-top: 1px solid var(--wq-border); border-left: 0; }
  .property-definition > header { align-items: flex-start; flex-direction: column; gap: 2px; }
  .property-definition-list > div { grid-template-columns: minmax(90px, 1fr) minmax(110px, 1.2fr) auto; }
  .property-definition-list small { display: none; }
  .preview-action-bar, .editor-footer { align-items: stretch; flex-direction: column; }
  .preview-action-bar .el-button { width: 100%; }
  .editor-footer > div { justify-content: flex-end; }
  .binding-card dl { grid-template-columns: 1fr; }
  .guided-binding-heading { align-items: stretch; flex-direction: column; }
  .field-mapping-row { grid-template-columns: 1fr; }
  .field-mapping-row > span { text-align: left; }
}

@media (prefers-reduced-motion: reduce) {
  .binding-mode-switch button { transition: none; }
}
</style>
