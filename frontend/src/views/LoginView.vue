<template>
  <div class="auth-page">
    <section class="auth-panel">
      <div class="auth-brand">
        <div class="brand-mark">WQ</div>
        <h1>WenQu 智能问数</h1>
        <p>登录后进入你的问数工作台。</p>
      </div>
      <el-form class="auth-form" :model="form" @submit.prevent="handleLogin">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            autocomplete="current-password"
            placeholder="请输入密码"
            show-password
            type="password"
          />
        </el-form-item>
        <el-button type="primary" :loading="loading" native-type="submit">登录</el-button>
        <div class="auth-links">
          <span>还没有账号？</span>
          <router-link to="/register">注册普通用户</router-link>
        </div>
      </el-form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function handleLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await login(form.username, form.password)
    router.replace(String(route.query.redirect || '/'))
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '登录失败')
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
