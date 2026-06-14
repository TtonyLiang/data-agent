<template>
  <div class="page">
    <div class="page-header">
      <h2>数据源管理</h2>
      <div class="header-actions">
        <el-select v-model="agentId" placeholder="选择智能体" style="width: 180px">
          <el-option
            v-for="agent in agents"
            :key="agent.id"
            :label="agent.name"
            :value="agent.id"
          />
        </el-select>
        <el-button type="primary" @click="showCreate = true">
          <el-icon><Plus /></el-icon> 添加数据源
        </el-button>
      </div>
    </div>

    <el-table :data="datasources" border stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="host" label="主机" />
      <el-table-column prop="port" label="端口" width="80" />
      <el-table-column prop="database_name" label="数据库" />
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'danger'" size="small">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260">
        <template #default="{ row }">
          <el-button size="small" @click="handleTest(row.id)">测试连接</el-button>
          <el-button size="small" type="success" @click="handleCollect(row.id)">采集Schema</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showCreate" title="添加数据源" width="500">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="主机">
          <el-input v-model="form.host" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="form.port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="数据库名">
          <el-input v-model="form.database_name" />
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
import { ref, onMounted, watch } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { fetchAgents, fetchDatasources, createDatasource, testConnection, collectSchema, type AgentItem, type DatasourceItem } from '../api'

const agentId = ref<number>(Number(localStorage.getItem('wenqu_agent_id')) || 1)
const agents = ref<AgentItem[]>([])
const datasources = ref<DatasourceItem[]>([])
const showCreate = ref(false)
const form = ref({
  agent_id: agentId.value,
  name: '',
  db_type: 'mysql',
  host: '127.0.0.1',
  port: 3306,
  username: 'root',
  password: '',
  database_name: '',
})

onMounted(async () => {
  await loadAgents()
  await loadDatasources()
})

watch(agentId, async (id) => {
  localStorage.setItem('wenqu_agent_id', String(id))
  form.value.agent_id = id
  await loadDatasources()
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

async function loadDatasources() {
  try {
    datasources.value = await fetchDatasources(agentId.value)
  } catch {
    // 首次可能无数据
  }
}

async function handleCreate() {
  if (!form.value.name || !form.value.host || !form.value.database_name) {
    ElMessage.warning('请填写完整信息')
    return
  }
  try {
    form.value.agent_id = agentId.value
    await createDatasource(form.value)
    ElMessage.success('创建成功')
    showCreate.value = false
    await loadDatasources()
  } catch {
    ElMessage.error('创建失败')
  }
}

async function handleTest(id: number) {
  try {
    const res = await testConnection(id)
    if (res.success) {
      ElMessage.success('连接成功')
    } else {
      ElMessage.error('连接失败')
    }
  } catch {
    ElMessage.error('测试失败')
  }
}

async function handleCollect(id: number) {
  try {
    const res = await collectSchema(id)
    ElMessage.success(`采集完成，共 ${res.tables?.length || 0} 张表`)
  } catch {
    ElMessage.error('采集失败')
  }
}
</script>

<style scoped>
.page { background: #fff; padding: 24px; border-radius: 8px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h2 { font-size: 18px; }
.header-actions { display: flex; gap: 12px; align-items: center; }
</style>
