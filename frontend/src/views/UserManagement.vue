<template>
  <div :class="['management-page', { embedded }]">
    <header class="page-header">
      <div>
        <h2>用户管理</h2>
        <p>管理系统用户、角色状态和可访问智能体。</p>
      </div>
      <el-button type="primary" @click="openCreate">新增用户</el-button>
    </header>

    <el-table :data="users" border class="admin-table" v-loading="loading">
      <el-table-column prop="id" label="ID" width="80" sortable />
      <el-table-column prop="username" label="用户名" min-width="140" />
      <el-table-column prop="display_name" label="展示名" min-width="160" />
      <el-table-column label="角色" width="100">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'danger' : 'info'">
            {{ row.role === 'admin' ? '管理员' : '普通用户' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'warning'">
            {{ row.status === 'active' ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_login_at" label="最近登录" min-width="180" />
      <el-table-column label="操作" width="420" fixed="right">
        <template #default="{ row }">
          <div class="action-row">
            <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button text type="primary" @click="openAgentPermission(row)">智能体权限</el-button>
            <el-button text type="warning" @click="openResetPassword(row)">重置密码</el-button>
            <el-button
              text
              :type="row.status === 'active' ? 'danger' : 'success'"
              @click="toggleStatus(row)"
            >
              {{ row.status === 'active' ? '禁用' : '启用' }}
            </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showUserDialog" :title="editingUser ? '编辑用户' : '新增用户'" width="520px" align-center>
      <el-form label-width="90px" :model="userForm">
        <el-form-item label="用户名">
          <el-input v-model="userForm.username" :disabled="Boolean(editingUser)" />
        </el-form-item>
        <el-form-item v-if="!editingUser" label="密码">
          <el-input v-model="userForm.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="展示名">
          <el-input v-model="userForm.display_name" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.role">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="userForm.status">
            <el-option label="启用" value="active" />
            <el-option label="禁用" value="disabled" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showUserDialog = false">取消</el-button>
        <el-button type="primary" @click="saveUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showAgentDialog" title="智能体访问权限" width="560px" align-center>
      <p class="dialog-tip">普通用户只能看到并使用这里勾选的智能体。</p>
      <el-checkbox-group v-model="selectedAgentIds" class="agent-checks">
        <el-checkbox v-for="agent in agents" :key="agent.id" :label="agent.id">
          {{ agent.name }}
        </el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="showAgentDialog = false">取消</el-button>
        <el-button type="primary" @click="saveAgentPermission">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showPasswordDialog" title="重置密码" width="460px" align-center>
      <el-input v-model="newPassword" type="password" show-password placeholder="请输入新密码" />
      <template #footer>
        <el-button @click="showPasswordDialog = false">取消</el-button>
        <el-button type="primary" @click="savePassword">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createUser,
  disableUser,
  enableUser,
  fetchAgents,
  fetchUserAgentIds,
  fetchUsers,
  resetUserPassword,
  updateUser,
  updateUserAgentIds,
  type AgentItem,
  type CurrentUser,
} from '../api'

defineProps<{ embedded?: boolean }>()

const users = ref<CurrentUser[]>([])
const agents = ref<AgentItem[]>([])
const loading = ref(false)
const showUserDialog = ref(false)
const showAgentDialog = ref(false)
const showPasswordDialog = ref(false)
const editingUser = ref<CurrentUser | null>(null)
const permissionUser = ref<CurrentUser | null>(null)
const passwordUser = ref<CurrentUser | null>(null)
const selectedAgentIds = ref<number[]>([])
const newPassword = ref('')
const userForm = reactive({
  username: '',
  password: '',
  display_name: '',
  role: 'user' as 'admin' | 'user',
  status: 'active' as 'active' | 'disabled',
})

onMounted(loadData)

async function loadData() {
  loading.value = true
  try {
    users.value = await fetchUsers()
    agents.value = await fetchAgents()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingUser.value = null
  Object.assign(userForm, { username: '', password: '', display_name: '', role: 'user', status: 'active' })
  showUserDialog.value = true
}

function openEdit(user: CurrentUser) {
  editingUser.value = user
  Object.assign(userForm, {
    username: user.username,
    password: '',
    display_name: user.display_name || '',
    role: user.role,
    status: user.status,
  })
  showUserDialog.value = true
}

async function saveUser() {
  try {
    if (editingUser.value) {
      await updateUser(editingUser.value.id, {
        display_name: userForm.display_name,
        role: userForm.role,
        status: userForm.status,
        must_change_password: Boolean(editingUser.value.must_change_password),
      })
    } else {
      await createUser({
        username: userForm.username,
        password: userForm.password,
        display_name: userForm.display_name,
        role: userForm.role,
        status: userForm.status,
      })
    }
    ElMessage.success('用户已保存')
    showUserDialog.value = false
    await loadData()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '保存失败')
  }
}

async function openAgentPermission(user: CurrentUser) {
  permissionUser.value = user
  selectedAgentIds.value = await fetchUserAgentIds(user.id)
  showAgentDialog.value = true
}

async function saveAgentPermission() {
  if (!permissionUser.value) return
  await updateUserAgentIds(permissionUser.value.id, selectedAgentIds.value)
  ElMessage.success('智能体权限已保存')
  showAgentDialog.value = false
}

function openResetPassword(user: CurrentUser) {
  passwordUser.value = user
  newPassword.value = ''
  showPasswordDialog.value = true
}

async function savePassword() {
  if (!passwordUser.value || !newPassword.value) return
  await resetUserPassword(passwordUser.value.id, newPassword.value)
  ElMessage.success('密码已重置')
  showPasswordDialog.value = false
}

async function toggleStatus(user: CurrentUser) {
  await ElMessageBox.confirm(
    `确定${user.status === 'active' ? '禁用' : '启用'}用户「${user.username}」？`,
    '确认操作',
    { type: 'warning' },
  )
  if (user.status === 'active') await disableUser(user.id)
  else await enableUser(user.id)
  await loadData()
}
</script>

<style scoped>
.management-page {
  height: 100%;
  padding: 22px;
  overflow: auto;
}

.management-page.embedded {
  padding: 0;
  overflow: visible;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0;
  color: var(--wq-text);
}

.page-header p,
.dialog-tip {
  margin: 6px 0 0;
  color: var(--wq-muted);
}

.admin-table {
  background: #fff;
}

.admin-table :deep(.el-table__cell) {
  vertical-align: middle;
}

.action-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.action-row :deep(.el-button) {
  margin-left: 0;
  padding: 0;
  min-height: 0;
  line-height: 1.3;
}

.agent-checks {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}
</style>
