<template>
  <div class="auth-page">
    <section class="auth-panel">
      <div class="auth-brand">
        <div class="brand-mark">WQ</div>
        <h1>注册账号</h1>
        <p>注册后需要管理员分配智能体权限。</p>
      </div>
      <el-form class="auth-form" :model="form" @submit.prevent="handleRegister">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" placeholder="至少 3 位" />
        </el-form-item>
        <el-form-item label="展示名">
          <el-input v-model="form.display_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            autocomplete="new-password"
            placeholder="至少 8 位"
            show-password
            type="password"
          />
        </el-form-item>
        <el-button type="primary" :loading="loading" native-type="submit">注册</el-button>
        <div class="auth-links">
          <span>已有账号？</span>
          <router-link to="/login">返回登录</router-link>
        </div>
      </el-form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { register } from '../stores/auth'

const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', display_name: '', password: '' })

async function handleRegister() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await register(form.username, form.password, form.display_name)
    ElMessage.success('注册成功，请登录')
    router.replace('/login')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: #f7f9fc;
}

.auth-panel {
  width: min(420px, 100%);
  padding: 30px;
  border: 1px solid #e5eaf3;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 16px 42px rgba(15, 23, 42, 0.08);
}

.auth-brand {
  margin-bottom: 24px;
}

.brand-mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  margin-bottom: 14px;
  border-radius: 8px;
  background: #172033;
  color: #fff;
  font-weight: 800;
}

h1 {
  margin: 0;
  color: #172033;
  font-size: 24px;
}

p {
  margin: 8px 0 0;
  color: #667085;
}

.auth-form {
  display: grid;
  gap: 4px;
}

.auth-links {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  color: #667085;
  font-size: 13px;
}
</style>
