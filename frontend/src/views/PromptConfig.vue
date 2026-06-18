<template>
  <div class="page-shell">
    <div class="page-header">
      <div>
        <span class="page-kicker">Prompt Center</span>
        <h2>Prompt 配置</h2>
        <p>按节点、智能体、模型和语义层维护提示词模板，优先匹配更具体的作用域。</p>
      </div>
      <div class="header-actions">
        <el-select v-model="activePromptKey" clearable placeholder="全部节点" class="key-filter" @change="loadTemplates">
          <el-option v-for="item in promptKeyOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon> 新增模板
        </el-button>
      </div>
    </div>

    <div class="table-surface">
      <el-table :data="templates" border stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="节点" min-width="170">
          <template #default="{ row }">{{ promptKeyLabel(row.prompt_key) }}</template>
        </el-table-column>
        <el-table-column label="作用域" min-width="260">
          <template #default="{ row }">
            <div class="scope-tags">
              <el-tag v-if="row.agent_id" size="small" effect="plain">智能体：{{ agentName(row.agent_id) }}</el-tag>
              <el-tag v-if="row.model_config_id" size="small" effect="plain">模型：{{ modelName(row.model_config_id) }}</el-tag>
              <el-tag v-if="row.semantic_domain_id" size="small" effect="plain">语义层：{{ domainName(row.semantic_domain_id) }}</el-tag>
              <el-tag v-if="!row.agent_id && !row.model_config_id && !row.semantic_domain_id" size="small" type="info" effect="plain">全局默认</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" round>{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDetail(row)">详情</el-button>
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="showDetail" title="Prompt 模板详情" size="680px" append-to-body>
      <div v-if="detailTemplate" class="detail-panel">
        <dl class="detail-grid">
          <dt>名称</dt><dd>{{ detailTemplate.name }}</dd>
          <dt>节点</dt><dd>{{ promptKeyLabel(detailTemplate.prompt_key) }}</dd>
          <dt>智能体</dt><dd>{{ detailTemplate.agent_id ? agentName(detailTemplate.agent_id) : '全局' }}</dd>
          <dt>模型</dt><dd>{{ detailTemplate.model_config_id ? modelName(detailTemplate.model_config_id) : '不限定' }}</dd>
          <dt>语义层</dt><dd>{{ detailTemplate.semantic_domain_id ? domainName(detailTemplate.semantic_domain_id) : '不限定' }}</dd>
          <dt>状态</dt><dd>{{ detailTemplate.status }}</dd>
          <dt>说明</dt><dd>{{ detailTemplate.description || '-' }}</dd>
        </dl>
        <h4>模板内容</h4>
        <pre class="template-preview">{{ detailTemplate.template_text }}</pre>
      </div>
    </el-drawer>

    <el-dialog v-model="showDialog" :title="editingId ? '编辑 Prompt 模板' : '新增 Prompt 模板'" width="760">
      <el-form :model="form" label-width="110px">
        <el-form-item label="模板名称">
          <el-input v-model="form.name" placeholder="例如：信贷指标 LogicForm 生成模板" />
        </el-form-item>
        <el-form-item label="节点">
          <el-select v-model="form.prompt_key" placeholder="选择生效节点">
            <el-option v-for="item in promptKeyOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" placeholder="模板用途、适用范围或变更说明" />
        </el-form-item>
        <el-form-item label="智能体">
          <el-select v-model="form.agent_id" clearable placeholder="不限定智能体">
            <el-option v-for="agent in agents" :key="agent.id" :label="agent.name" :value="agent.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型">
          <el-select v-model="form.model_config_id" clearable placeholder="不限定模型">
            <el-option
              v-for="model in modelConfigs"
              :key="model.id"
              :label="`${model.name} · ${model.model_name}`"
              :value="model.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="语义层">
          <el-select v-model="form.semantic_domain_id" clearable placeholder="不限定语义层">
            <el-option
              v-for="domain in semanticDomains"
              :key="domain.id"
              :label="`${domain.name} · ${domain.domain_key}`"
              :value="domain.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status">
            <el-option label="active" value="active" />
            <el-option label="disabled" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="模板内容">
          <el-input
            v-model="form.template_text"
            type="textarea"
            :rows="12"
            placeholder="支持 {runtime_context}、{question_context}、{schema_context} 等变量，具体变量由对应节点注入。"
          />
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
import { computed, onMounted, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deletePromptTemplate,
  fetchAgents,
  fetchAllSemanticDomains,
  fetchModelConfigs,
  fetchPromptTemplates,
  upsertPromptTemplate,
  type AgentItem,
  type ModelConfigItem,
  type PromptTemplateItem,
  type PromptTemplateRequest,
  type SemanticDomain,
} from '../api'

const promptKeyOptions = [
  { label: '语义增强', value: 'semantic_enhance.system' },
  { label: 'LogicForm 生成', value: 'nl2lf_generate.system' },
  { label: 'NL2SQL 兜底', value: 'nl2sql_fallback.system' },
]

const activePromptKey = ref('')
const templates = ref<PromptTemplateItem[]>([])
const agents = ref<AgentItem[]>([])
const modelConfigs = ref<ModelConfigItem[]>([])
const semanticDomains = ref<SemanticDomain[]>([])
const showDialog = ref(false)
const showDetail = ref(false)
const editingId = ref<number | null>(null)
const detailTemplate = ref<PromptTemplateItem | null>(null)
const form = ref<PromptTemplateRequest>(defaultForm())

const agentMap = computed(() => new Map(agents.value.map(item => [item.id, item.name])))
const modelMap = computed(() => new Map(modelConfigs.value.map(item => [item.id, item.name])))
const domainMap = computed(() => new Map(semanticDomains.value.map(item => [item.id, item.name])))

onMounted(async () => {
  await Promise.all([loadTemplates(), loadScopeOptions()])
})

function defaultForm(): PromptTemplateRequest {
  return {
    prompt_key: 'nl2lf_generate.system',
    name: 'LogicForm 生成模板',
    description: '',
    agent_id: null,
    model_config_id: null,
    semantic_domain_id: null,
    template_text: '',
    status: 'active',
  }
}

async function loadTemplates() {
  try {
    templates.value = await fetchPromptTemplates(activePromptKey.value || undefined)
  } catch {
    ElMessage.error('Prompt 模板加载失败')
    templates.value = []
  }
}

async function loadScopeOptions() {
  try {
    const [agentRows, modelRows, domainRows] = await Promise.all([
      fetchAgents(),
      fetchModelConfigs(),
      fetchAllSemanticDomains(),
    ])
    agents.value = agentRows
    modelConfigs.value = modelRows
    semanticDomains.value = domainRows
  } catch {
    ElMessage.warning('作用域选项加载失败，可先保存全局模板')
  }
}

function promptKeyLabel(key: string) {
  return promptKeyOptions.find(item => item.value === key)?.label || key
}

function agentName(id: number) {
  return agentMap.value.get(id) || `#${id}`
}

function modelName(id: number) {
  return modelMap.value.get(id) || `#${id}`
}

function domainName(id: number) {
  return domainMap.value.get(id) || `#${id}`
}

function openCreate() {
  editingId.value = null
  form.value = defaultForm()
  if (activePromptKey.value) form.value.prompt_key = activePromptKey.value
  showDialog.value = true
}

function openDetail(template: PromptTemplateItem) {
  detailTemplate.value = template
  showDetail.value = true
}

function openEdit(template: PromptTemplateItem) {
  editingId.value = template.id
  form.value = {
    id: template.id,
    prompt_key: template.prompt_key,
    name: template.name,
    description: template.description || '',
    agent_id: template.agent_id || null,
    model_config_id: template.model_config_id || null,
    semantic_domain_id: template.semantic_domain_id || null,
    template_text: template.template_text,
    status: template.status || 'active',
  }
  showDialog.value = true
}

async function handleSubmit() {
  if (!form.value.name || !form.value.prompt_key || !form.value.template_text.trim()) {
    ElMessage.warning('请填写模板名称、节点和模板内容')
    return
  }
  try {
    await upsertPromptTemplate({
      ...form.value,
      id: editingId.value,
      agent_id: form.value.agent_id || null,
      model_config_id: form.value.model_config_id || null,
      semantic_domain_id: form.value.semantic_domain_id || null,
    })
    ElMessage.success(editingId.value ? '更新成功' : '创建成功')
    showDialog.value = false
    editingId.value = null
    await loadTemplates()
  } catch {
    ElMessage.error(editingId.value ? '更新失败' : '创建失败')
  }
}

async function handleDelete(template: PromptTemplateItem) {
  try {
    await ElMessageBox.confirm(`确定删除 Prompt 模板「${template.name}」？`, '删除 Prompt 模板', { type: 'warning' })
    await deletePromptTemplate(template.id)
    ElMessage.success('删除成功')
    await loadTemplates()
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

.page-kicker {
  display: block;
  margin-bottom: 7px;
  color: var(--wq-primary);
  font-size: 12px;
  font-weight: 720;
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
  align-items: center;
  gap: 12px;
}

.key-filter {
  width: 190px;
}

.table-surface {
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  padding: 14px;
  box-shadow: var(--wq-shadow);
}

.scope-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.detail-panel h4 {
  margin: 18px 0 8px;
  color: var(--wq-text);
}

.detail-grid {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 12px 16px;
  font-size: 14px;
}

.detail-grid dt {
  color: var(--wq-muted);
}

.detail-grid dd {
  color: var(--wq-text);
  word-break: break-word;
}

.template-preview {
  min-height: 260px;
  max-height: 520px;
  overflow: auto;
  padding: 14px;
  border: 1px solid var(--wq-border);
  border-radius: 6px;
  background: #0f172a;
  color: #d9e4ff;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
}
</style>
