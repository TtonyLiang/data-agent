<template>
  <div class="page-shell">
    <div class="page-header">
      <div>
        <span class="page-kicker">Model Registry</span>
        <h2>大模型配置</h2>
        <p>分别维护大语言模型和向量模型，供智能体按需绑定。</p>
      </div>
      <div class="header-actions">
        <el-segmented v-model="activeType" :options="typeOptions" />
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon> 新增配置
        </el-button>
      </div>
    </div>

    <div class="table-surface">
      <el-table :data="filteredConfigs" border stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="row.model_type === 'chat' ? 'primary' : 'success'" round>
              {{ row.model_type === 'chat' ? '大语言模型' : '向量模型' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="provider" label="提供商" width="140" />
        <el-table-column prop="model_name" label="模型" min-width="180" />
        <el-table-column prop="base_url" label="Base URL" min-width="240" show-overflow-tooltip />
        <el-table-column label="API Key" width="110">
          <template #default="{ row }">
            <el-tag :type="row.api_key_enabled ? 'success' : 'info'" size="small" round>
              {{ row.api_key_enabled ? '启用' : '未启用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="embedding_dimension" label="维度" width="100" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="showDialog" :title="editingId ? '编辑模型配置' : '新增模型配置'" width="620">
      <el-form :model="form" label-width="120px">
        <el-form-item label="配置名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="模型类型">
          <el-segmented v-model="form.model_type" :options="typeOptions" />
        </el-form-item>
        <el-form-item label="提供商">
          <el-input v-model="form.provider" placeholder="ollama / deepseek / openai-compatible" />
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="http://127.0.0.1:11434/v1" />
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="form.model_name" />
        </el-form-item>
        <el-form-item v-if="form.model_type === 'embedding'" label="向量维度">
          <el-input-number v-model="form.embedding_dimension" :min="1" :max="8192" />
        </el-form-item>
        <el-form-item label="启用 Key">
          <el-switch v-model="form.api_key_enabled" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password :placeholder="editingId ? '不修改请重新填写或留空' : ''" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status">
            <el-option label="active" value="active" />
            <el-option label="disabled" value="disabled" />
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
import { computed, onMounted, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createModelConfig,
  deleteModelConfig,
  fetchModelConfigs,
  updateModelConfig,
  type ModelConfigItem,
  type ModelConfigRequest,
} from '../api'

const typeOptions = [
  { label: '大语言模型', value: 'chat' },
  { label: '向量模型', value: 'embedding' },
]
const activeType = ref<'chat' | 'embedding'>('chat')
const configs = ref<ModelConfigItem[]>([])
const showDialog = ref(false)
const editingId = ref<number | null>(null)
const form = ref<ModelConfigRequest>(defaultForm('chat'))

const filteredConfigs = computed(() => configs.value.filter(item => item.model_type === activeType.value))

onMounted(loadConfigs)

function defaultForm(modelType: 'chat' | 'embedding'): ModelConfigRequest {
  return {
    name: modelType === 'chat' ? '默认大语言模型' : '默认向量模型',
    model_type: modelType,
    provider: modelType === 'chat' ? 'ollama' : 'openai-compatible',
    base_url: modelType === 'chat' ? 'http://127.0.0.1:11434/v1' : 'https://api.deepseek.com/v1',
    model_name: modelType === 'chat' ? 'qwen3:14b' : 'embedding-3',
    api_key: '',
    api_key_enabled: false,
    embedding_dimension: modelType === 'embedding' ? 1024 : null,
    status: 'active',
  }
}

async function loadConfigs() {
  try {
    configs.value = await fetchModelConfigs()
  } catch {
    ElMessage.error('模型配置加载失败')
    configs.value = []
  }
}

function openCreate() {
  editingId.value = null
  form.value = defaultForm(activeType.value)
  showDialog.value = true
}

function openEdit(config: ModelConfigItem) {
  editingId.value = config.id
  form.value = {
    name: config.name,
    model_type: config.model_type,
    provider: config.provider,
    base_url: config.base_url,
    model_name: config.model_name,
    api_key: '',
    api_key_enabled: Boolean(config.api_key_enabled),
    embedding_dimension: config.embedding_dimension || null,
    status: config.status || 'active',
  }
  showDialog.value = true
}

async function handleSubmit() {
  if (!form.value.name || !form.value.base_url || !form.value.model_name) {
    ElMessage.warning('请填写完整模型配置')
    return
  }
  try {
    if (editingId.value) {
      await updateModelConfig(editingId.value, form.value)
      ElMessage.success('更新成功')
    } else {
      await createModelConfig(form.value)
      ElMessage.success('创建成功')
    }
    activeType.value = form.value.model_type
    showDialog.value = false
    editingId.value = null
    await loadConfigs()
  } catch {
    ElMessage.error(editingId.value ? '更新失败' : '创建失败')
  }
}

async function handleDelete(config: ModelConfigItem) {
  try {
    await ElMessageBox.confirm(`确定删除模型配置「${config.name}」？已绑定的智能体会解除该模型绑定。`, '删除模型配置', { type: 'warning' })
    await deleteModelConfig(config.id)
    ElMessage.success('删除成功')
    await loadConfigs()
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

@media (max-width: 760px) {
  .page-shell { padding: 18px; }
  .page-header { align-items: flex-start; flex-direction: column; }
  .header-actions { justify-content: flex-start; }
}
</style>
