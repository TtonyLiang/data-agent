<template>
  <div class="page">
    <div class="page-header">
      <h2>智能体管理</h2>
      <el-button type="primary" @click="showCreate = true">
        <el-icon><Plus /></el-icon> 创建智能体
      </el-button>
    </div>

    <el-table :data="agents" border stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="description" label="描述" />
      <el-table-column prop="llm_model" label="LLM模型" width="160" />
      <el-table-column prop="created_at" label="创建时间" width="180" />
    </el-table>

    <el-dialog v-model="showCreate" title="创建智能体" width="500">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="请输入智能体名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="LLM提供商">
          <el-select v-model="form.llm_provider">
            <el-option label="Ollama" value="ollama" />
            <el-option label="DeepSeek" value="deepseek" />
            <el-option label="MiMo" value="mimo" />
            <el-option label="MiniMax" value="minimax" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型">
          <el-input v-model="form.llm_model" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { createAgent, fetchAgents, type AgentCreateRequest, type AgentItem } from '../api'

const agents = ref<AgentItem[]>([])
const showCreate = ref(false)
const form = ref<AgentCreateRequest>({
  name: '',
  description: '',
  llm_provider: 'ollama',
  llm_model: 'qwen3:14b',
})

onMounted(async () => {
  await loadAgents()
})

async function loadAgents() {
  try {
    agents.value = await fetchAgents()
  } catch {
    // 首次可能无数据
  }
}

async function handleCreate() {
  if (!form.value.name) {
    ElMessage.warning('请输入名称')
    return
  }
  try {
    await createAgent(form.value)
    ElMessage.success('创建成功')
    showCreate.value = false
    form.value = { name: '', description: '', llm_provider: 'ollama', llm_model: 'qwen3:14b' }
    await loadAgents()
  } catch (err: unknown) {
    ElMessage.error('创建失败')
  }
}
</script>

<style scoped>
.page { background: #fff; padding: 24px; border-radius: 8px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h2 { font-size: 18px; }
</style>
