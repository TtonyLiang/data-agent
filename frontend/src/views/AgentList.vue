<template>
  <div class="page-shell">
    <div class="page-header">
      <div>
        <h2>智能体管理</h2>
        <p>配置问数助手说明、模型绑定、语义领域和可访问数据源。</p>
      </div>
      <div class="header-actions">
        <el-tag effect="plain">共 {{ agents.length }} 个智能体</el-tag>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon> 创建智能体
        </el-button>
      </div>
    </div>

    <div class="table-surface">
      <el-table :data="agents" border stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
        <el-table-column prop="chat_model_config_name" label="大语言模型" min-width="160" />
        <el-table-column prop="embedding_model_config_name" label="向量模型" min-width="160" />
        <el-table-column label="语义领域" min-width="180">
          <template #default="{ row }">
            <span v-if="row.semantic_domain_name">
              {{ row.semantic_domain_name }}
              <code class="inline-code">{{ row.semantic_domain_key }}</code>
            </span>
            <span v-else class="muted">未绑定</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="190">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
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

    <el-dialog v-model="showDialog" :title="editingAgentId ? '编辑智能体' : '创建智能体'" width="620">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="请输入智能体名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="大语言模型">
          <el-select v-model="form.chat_model_config_id" clearable placeholder="选择大语言模型配置">
            <el-option
              v-for="config in chatModelConfigs"
              :key="config.id"
              :label="`${config.name} · ${config.model_name}`"
              :value="config.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="向量模型">
          <el-select v-model="form.embedding_model_config_id" clearable placeholder="选择向量模型配置">
            <el-option
              v-for="config in embeddingModelConfigs"
              :key="config.id"
              :label="`${config.name} · ${config.model_name}`"
              :value="config.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="数据源">
          <el-select v-model="form.datasource_ids" multiple clearable collapse-tags placeholder="选择智能体可访问的数据源">
            <el-option
              v-for="ds in datasources"
              :key="ds.id"
              :label="`${ds.name} · ${ds.database_name}`"
              :value="ds.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="语义领域">
          <el-select v-model="form.semantic_domain_id" clearable placeholder="选择智能体默认语义领域">
            <el-option
              v-if="semanticDomains.length === 0"
              disabled
              label="暂无语义领域，请先在语义层配置中维护"
              :value="0"
            />
            <el-option
              v-for="domain in semanticDomains"
              :key="domain.id"
              :label="`${domain.name} · ${domain.domain_key}`"
              :value="domain.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="默认问题">
          <el-input
            v-model="defaultQuestionsText"
            type="textarea"
            :rows="4"
            placeholder="每行一个默认问题，会显示在对话输入框上方"
          />
          <div class="form-help">建议配置 3-6 个高频问题，普通用户进入该智能体后会优先看到这些问题。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="showDetailDrawer"
      title="智能体详情"
      size="640px"
      append-to-body
      class="agent-detail-drawer"
    >
      <div v-if="detailAgent" class="agent-detail">
        <div class="detail-identity">
          <span>智能体配置</span>
          <strong>{{ detailAgent.name }}</strong>
          <code>{{ `agent_${detailAgent.id}` }}</code>
        </div>

        <section class="detail-section">
          <h4>基础信息</h4>
          <dl class="detail-grid">
            <dt>ID</dt>
            <dd>{{ detailAgent.id }}</dd>
            <dt>名称</dt>
            <dd>{{ detailAgent.name }}</dd>
            <dt>描述</dt>
            <dd>{{ detailAgent.description || '未填写' }}</dd>
            <dt>创建时间</dt>
            <dd>{{ formatDateTime(detailAgent.created_at) }}</dd>
          </dl>
        </section>

        <section class="detail-section">
          <h4>模型与语义层</h4>
          <dl class="detail-grid">
            <dt>大语言模型</dt>
            <dd>{{ detailAgent.chat_model_config_name || modelConfigLabel(detailAgent.chat_model_config_id, 'chat') || '未绑定' }}</dd>
            <dt>向量模型</dt>
            <dd>{{ detailAgent.embedding_model_config_name || modelConfigLabel(detailAgent.embedding_model_config_id, 'embedding') || '未绑定' }}</dd>
            <dt>语义领域</dt>
            <dd>
              <span v-if="detailAgent.semantic_domain_name">
                {{ detailAgent.semantic_domain_name }}
                <code class="inline-code">{{ detailAgent.semantic_domain_key }}</code>
              </span>
              <span v-else class="muted">未绑定</span>
            </dd>
          </dl>
        </section>

        <section class="detail-section">
          <h4>可访问数据源</h4>
          <div v-if="detailDatasourceNames.length" class="detail-chip-list">
            <el-tag v-for="name in detailDatasourceNames" :key="name" effect="plain">{{ name }}</el-tag>
          </div>
          <el-empty v-else description="当前未绑定数据源" :image-size="72" />
        </section>

        <section class="detail-section">
          <h4>默认问题</h4>
          <div v-if="detailDefaultQuestions.length" class="question-list">
            <el-tag v-for="question in detailDefaultQuestions" :key="question" effect="plain">{{ question }}</el-tag>
          </div>
          <el-empty v-else description="当前未配置默认问题" :image-size="72" />
        </section>

        <section class="detail-section">
          <h4>说明与运行上下文</h4>
          <dl class="detail-grid">
            <dt>说明字段</dt>
            <dd>{{ detailAgent.description || '可在编辑时补充业务边界、提示词风格或使用说明。' }}</dd>
            <dt>运行模型</dt>
            <dd>{{ detailAgent.llm_provider || '-' }} / {{ detailAgent.llm_model || '-' }}</dd>
          </dl>
        </section>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <el-button @click="showDetailDrawer = false">关闭</el-button>
          <el-button v-if="detailAgent" type="primary" @click="openEdit(detailAgent)">编辑</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatDateTime } from '../utils/datetime'
import {
  createAgent,
  deleteAgent,
  fetchAgentDatasourceIds,
  fetchAgents,
  fetchAllDatasources,
  fetchAllSemanticDomains,
  fetchModelConfigs,
  updateAgent,
  type AgentCreateRequest,
  type AgentItem,
  type DatasourceItem,
  type ModelConfigItem,
  type SemanticDomain,
} from '../api'

const agents = ref<AgentItem[]>([])
const chatModelConfigs = ref<ModelConfigItem[]>([])
const embeddingModelConfigs = ref<ModelConfigItem[]>([])
const datasources = ref<DatasourceItem[]>([])
const semanticDomains = ref<SemanticDomain[]>([])
const showDialog = ref(false)
const showDetailDrawer = ref(false)
const editingAgentId = ref<number | null>(null)
const detailAgent = ref<AgentItem | null>(null)
const detailDatasourceIds = ref<number[]>([])
const form = ref<AgentCreateRequest>({
  name: '',
  description: '',
  chat_model_config_id: null,
  embedding_model_config_id: null,
  semantic_domain_id: null,
  default_questions: [],
  datasource_ids: [],
})
const defaultQuestionsText = ref('')
const detailDatasourceNames = computed(() => detailDatasourceIds.value
  .map((id) => datasources.value.find((item) => item.id === id))
  .filter((item): item is DatasourceItem => !!item)
  .map((item) => `${item.name} · ${item.database_name}`))
const detailDefaultQuestions = computed(() => normalizeDefaultQuestions(detailAgent.value?.default_questions))

onMounted(async () => {
  await loadDependencies()
  await loadAgents()
})

function resetForm() {
  form.value = {
    name: '',
    description: '',
    chat_model_config_id: chatModelConfigs.value[0]?.id || null,
    embedding_model_config_id: embeddingModelConfigs.value[0]?.id || null,
    semantic_domain_id: semanticDomains.value[0]?.id || null,
    default_questions: [],
    datasource_ids: [],
  }
  defaultQuestionsText.value = ''
}

function openCreate() {
  editingAgentId.value = null
  resetForm()
  showDialog.value = true
}

async function openDetail(agent: AgentItem) {
  detailAgent.value = agent
  showDetailDrawer.value = true
  detailDatasourceIds.value = await fetchAgentDatasourceIds(agent.id).catch(() => [])
}

async function openEdit(agent: AgentItem) {
  showDetailDrawer.value = false
  editingAgentId.value = agent.id
  const datasourceIds = await fetchAgentDatasourceIds(agent.id).catch(() => [])
  form.value = {
    name: agent.name,
    description: agent.description || '',
    chat_model_config_id: agent.chat_model_config_id || null,
    embedding_model_config_id: agent.embedding_model_config_id || null,
    semantic_domain_id: agent.semantic_domain_id || null,
    default_questions: normalizeDefaultQuestions(agent.default_questions),
    datasource_ids: datasourceIds,
  }
  defaultQuestionsText.value = normalizeDefaultQuestions(agent.default_questions).join('\n')
  showDialog.value = true
}

function normalizeDefaultQuestions(value: unknown) {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  return value
    .map((item) => String(item || '').trim())
    .filter((item) => {
      if (!item || seen.has(item)) return false
      seen.add(item)
      return true
    })
}

function parseDefaultQuestionsText() {
  const seen = new Set<string>()
  return defaultQuestionsText.value
    .split('\n')
    .map((item) => item.trim())
    .filter((item) => {
      if (!item || seen.has(item)) return false
      seen.add(item)
      return true
    })
}

function modelConfigLabel(configId: number | null | undefined, modelType: 'chat' | 'embedding') {
  if (!configId) return ''
  const configs = modelType === 'chat' ? chatModelConfigs.value : embeddingModelConfigs.value
  const match = configs.find((item) => item.id === configId)
  return match ? `${match.name} · ${match.model_name}` : ''
}

async function loadDependencies() {
  try {
    const [chatConfigs, embeddingConfigs, allDatasources, allSemanticDomains] = await Promise.all([
      fetchModelConfigs('chat'),
      fetchModelConfigs('embedding'),
      fetchAllDatasources(),
      fetchAllSemanticDomains(),
    ])
    chatModelConfigs.value = chatConfigs
    embeddingModelConfigs.value = embeddingConfigs
    datasources.value = allDatasources
    semanticDomains.value = allSemanticDomains
  } catch {
    ElMessage.error('模型配置或数据源加载失败，请确认后端服务已启动')
  }
}

async function loadAgents() {
  try {
    agents.value = await fetchAgents()
  } catch {
    ElMessage.error('智能体配置加载失败，请确认后端服务已启动')
    agents.value = []
  }
}

async function handleSubmit() {
  if (!form.value.name) {
    ElMessage.warning('请输入名称')
    return
  }
  try {
    const payload = {
      ...form.value,
      default_questions: parseDefaultQuestionsText(),
    }
    const currentEditingId = editingAgentId.value
    if (currentEditingId) {
      await updateAgent(currentEditingId, payload)
      ElMessage.success('更新成功')
    } else {
      await createAgent(payload)
      ElMessage.success('创建成功')
    }
    showDialog.value = false
    editingAgentId.value = null
    resetForm()
    await loadAgents()
    if (detailAgent.value && currentEditingId !== null) {
      const updated = agents.value.find((item) => item.id === detailAgent.value?.id)
      if (updated) detailAgent.value = updated
    }
  } catch (err: unknown) {
    ElMessage.error(editingAgentId.value ? '更新失败' : '创建失败')
  }
}

async function handleDelete(agent: AgentItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除智能体「${agent.name}」？知识、会话和语义配置会一并删除，数据源连接会保留。`,
      '删除智能体',
      { type: 'warning' },
    )
    await deleteAgent(agent.id)
    ElMessage.success('删除成功')
    await loadAgents()
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

.inline-code {
  margin-left: 6px;
  padding: 2px 6px;
  border-radius: 5px;
  background: #eef3f8;
  color: #31506f;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.muted {
  color: var(--wq-muted);
}

:global(.agent-detail-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--wq-border);
  color: var(--wq-text);
  font-weight: 760;
}

.agent-detail {
  padding: 2px 2px 20px;
  color: #344054;
}

.detail-identity {
  display: grid;
  gap: 6px;
  margin-bottom: 18px;
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
  color: #667085;
  background: #fff;
  border: 1px solid var(--wq-border);
  border-radius: 5px;
  padding: 3px 7px;
  font-size: 12px;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.detail-section {
  margin-top: 18px;
}

.detail-section h4 {
  margin: 0 0 10px;
  color: var(--wq-text);
  font-size: 14px;
  font-weight: 760;
}

.detail-grid {
  margin: 0;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  overflow: hidden;
}

.detail-grid dt,
.detail-grid dd {
  margin: 0;
  padding: 11px 12px;
  border-bottom: 1px solid var(--wq-border);
  font-size: 13px;
  line-height: 1.65;
}

.detail-grid dt {
  float: left;
  clear: left;
  width: 128px;
  min-height: 46px;
  color: var(--wq-muted);
  background: #f8fafc;
  font-weight: 700;
}

.detail-grid dd {
  min-height: 46px;
  margin-left: 128px;
  color: var(--wq-text);
  word-break: break-word;
}

.detail-grid dd:last-child,
.detail-grid dt:has(+ dd:last-child) {
  border-bottom: 0;
}

.detail-chip-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.question-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: flex-start;
}

.question-list :deep(.el-tag) {
  height: auto;
  max-width: 100%;
  padding: 6px 10px;
  white-space: normal;
  line-height: 1.45;
}

.form-help {
  margin-top: 7px;
  color: var(--wq-muted);
  font-size: 12px;
  line-height: 1.5;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 760px) {
  .page-shell { padding: 18px; }
  .page-header { align-items: flex-start; flex-direction: column; }
  .header-actions { justify-content: flex-start; }
}
</style>
