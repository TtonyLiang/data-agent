<template>
  <div class="page-shell">
    <div class="page-header">
      <div>
        <span class="page-kicker">Agent Console</span>
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
        <el-table-column prop="created_at" label="创建时间" width="190" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
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
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
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
const editingAgentId = ref<number | null>(null)
const form = ref<AgentCreateRequest>({
  name: '',
  description: '',
  chat_model_config_id: null,
  embedding_model_config_id: null,
  semantic_domain_id: null,
  datasource_ids: [],
})

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
    datasource_ids: [],
  }
}

function openCreate() {
  editingAgentId.value = null
  resetForm()
  showDialog.value = true
}

async function openEdit(agent: AgentItem) {
  editingAgentId.value = agent.id
  const datasourceIds = await fetchAgentDatasourceIds(agent.id).catch(() => [])
  form.value = {
    name: agent.name,
    description: agent.description || '',
    chat_model_config_id: agent.chat_model_config_id || null,
    embedding_model_config_id: agent.embedding_model_config_id || null,
    semantic_domain_id: agent.semantic_domain_id || null,
    datasource_ids: datasourceIds,
  }
  showDialog.value = true
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
    if (editingAgentId.value) {
      await updateAgent(editingAgentId.value, form.value)
      ElMessage.success('更新成功')
    } else {
      await createAgent(form.value)
      ElMessage.success('创建成功')
    }
    showDialog.value = false
    editingAgentId.value = null
    resetForm()
    await loadAgents()
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

@media (max-width: 760px) {
  .page-shell { padding: 18px; }
  .page-header { align-items: flex-start; flex-direction: column; }
  .header-actions { justify-content: flex-start; }
}
</style>
