<template>
  <div class="page">
    <div class="page-header">
      <h2>知识库</h2>
      <el-select v-model="agentId" placeholder="选择智能体" style="width: 180px">
        <el-option
          v-for="agent in agents"
          :key="agent.id"
          :label="agent.name"
          :value="agent.id"
        />
      </el-select>
    </div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="语义模型" name="semantic">
        <div class="tab-header">
          <h3>语义模型管理</h3>
          <el-button type="primary" size="small" @click="showSemantic = true">添加语义模型</el-button>
        </div>
        <el-table :data="semanticModels" border stripe size="small">
          <el-table-column prop="table_name" label="表名" />
          <el-table-column prop="column_name" label="字段名" />
          <el-table-column prop="business_name" label="业务名称" />
          <el-table-column prop="synonyms" label="同义词" />
          <el-table-column prop="description" label="描述" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="业务知识" name="business">
        <div class="tab-header">
          <h3>业务知识管理</h3>
          <el-button type="primary" size="small" @click="showBusiness = true">添加业务知识</el-button>
        </div>
        <el-table :data="businessKnowledge" border stripe size="small">
          <el-table-column prop="title" label="标题" />
          <el-table-column prop="content" label="内容" show-overflow-tooltip />
          <el-table-column prop="knowledge_type" label="类型" width="120" />
          <el-table-column prop="synonyms" label="同义词" />
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 语义模型弹窗 -->
    <el-dialog v-model="showSemantic" title="添加语义模型" width="500">
      <el-form :model="semanticForm" label-width="100px">
        <el-form-item label="表名">
          <el-input v-model="semanticForm.table_name" placeholder="物理表名" />
        </el-form-item>
        <el-form-item label="字段名">
          <el-input v-model="semanticForm.column_name" placeholder="物理字段名" />
        </el-form-item>
        <el-form-item label="业务名称">
          <el-input v-model="semanticForm.business_name" placeholder="业务人员常用名称" />
        </el-form-item>
        <el-form-item label="同义词">
          <el-input v-model="semanticForm.synonyms" placeholder="逗号分隔，如: 订单金额,成交价,销售额" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="semanticForm.description" type="textarea" :rows="2" placeholder="特殊取值逻辑或业务含义" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSemantic = false">取消</el-button>
        <el-button type="primary" @click="handleCreateSemantic">确定</el-button>
      </template>
    </el-dialog>

    <!-- 业务知识弹窗 -->
    <el-dialog v-model="showBusiness" title="添加业务知识" width="500">
      <el-form :model="businessForm" label-width="100px">
        <el-form-item label="标题">
          <el-input v-model="businessForm.title" placeholder="如: GMV、复购率" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="businessForm.content" type="textarea" :rows="4" placeholder="定义计算公式、过滤条件或业务规则" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="businessForm.knowledge_type">
            <el-option label="定义" value="definition" />
            <el-option label="公式" value="formula" />
            <el-option label="规则" value="rule" />
          </el-select>
        </el-form-item>
        <el-form-item label="同义词">
          <el-input v-model="businessForm.synonyms" placeholder="逗号分隔" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showBusiness = false">取消</el-button>
        <el-button type="primary" @click="handleCreateBusiness">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchAgents, fetchSemanticModels, createSemanticModel,
  fetchBusinessKnowledge, createBusinessKnowledge,
  type AgentItem,
} from '../api'

const agentId = ref<number>(Number(localStorage.getItem('wenqu_agent_id')) || 1)
const agents = ref<AgentItem[]>([])
const activeTab = ref('semantic')
const semanticModels = ref<Record<string, unknown>[]>([])
const businessKnowledge = ref<Record<string, unknown>[]>([])
const showSemantic = ref(false)
const showBusiness = ref(false)

const semanticForm = ref({
  agent_id: agentId.value,
  table_name: '',
  column_name: '',
  business_name: '',
  synonyms: '',
  description: '',
  data_type: null as string | null,
})

const businessForm = ref({
  agent_id: agentId.value,
  title: '',
  content: '',
  knowledge_type: 'definition',
  synonyms: '',
  is_recall: true,
})

onMounted(async () => {
  await loadAgents()
  await Promise.all([loadSemantic(), loadBusiness()])
})

watch(agentId, async (id) => {
  localStorage.setItem('wenqu_agent_id', String(id))
  semanticForm.value.agent_id = id
  businessForm.value.agent_id = id
  await Promise.all([loadSemantic(), loadBusiness()])
})

async function loadAgents() {
  try {
    agents.value = await fetchAgents()
    if (agents.value.length > 0 && !agents.value.some(agent => agent.id === agentId.value)) {
      agentId.value = agents.value[0].id
    }
  } catch {
    agents.value = []
  }
}

async function loadSemantic() {
  try { semanticModels.value = await fetchSemanticModels(agentId.value) } catch { /* empty */ }
}

async function loadBusiness() {
  try { businessKnowledge.value = await fetchBusinessKnowledge(agentId.value) } catch { /* empty */ }
}

async function handleCreateSemantic() {
  if (!semanticForm.value.table_name || !semanticForm.value.column_name || !semanticForm.value.business_name) {
    ElMessage.warning('请填写完整')
    return
  }
  try {
    semanticForm.value.agent_id = agentId.value
    await createSemanticModel(semanticForm.value)
    ElMessage.success('创建成功')
    showSemantic.value = false
    semanticForm.value = { agent_id: agentId.value, table_name: '', column_name: '', business_name: '', synonyms: '', description: '', data_type: null }
    await loadSemantic()
  } catch { ElMessage.error('创建失败') }
}

async function handleCreateBusiness() {
  if (!businessForm.value.title || !businessForm.value.content) {
    ElMessage.warning('请填写完整')
    return
  }
  try {
    businessForm.value.agent_id = agentId.value
    await createBusinessKnowledge(businessForm.value)
    ElMessage.success('创建成功')
    showBusiness.value = false
    businessForm.value = { agent_id: agentId.value, title: '', content: '', knowledge_type: 'definition', synonyms: '', is_recall: true }
    await loadBusiness()
  } catch { ElMessage.error('创建失败') }
}
</script>

<style scoped>
.page { background: #fff; padding: 24px; border-radius: 8px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { font-size: 18px; }
.tab-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.tab-header h3 { font-size: 15px; }
</style>
