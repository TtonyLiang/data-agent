<template>
  <main class="auth-page">
    <div class="auth-shell">
      <aside class="brand-panel" aria-label="WenQu 智能问数">
        <div class="brand-lockup">
          <div class="brand-mark" aria-hidden="true">
            <el-icon :size="20"><DataAnalysis /></el-icon>
          </div>
          <div class="brand-text">
            <strong>WenQu</strong>
            <span>智能问数</span>
          </div>
        </div>

        <div class="brand-copy">
          <h2>数据查询，回到问题本身。</h2>
          <p>用自然语言连接业务数据，查看可追溯的查询结果。</p>
        </div>

        <div class="access-note">
          <el-icon aria-hidden="true"><Lock /></el-icon>
          <span>访问范围由工作区权限控制</span>
        </div>
      </aside>

      <section class="auth-panel" aria-labelledby="login-title">
        <div class="mobile-brand">
          <div class="brand-mark" aria-hidden="true">
            <el-icon :size="19"><DataAnalysis /></el-icon>
          </div>
          <div class="brand-text">
            <strong>WenQu</strong>
            <span>智能问数</span>
          </div>
        </div>

        <header class="form-heading">
          <h1 id="login-title">登录</h1>
          <p>使用工作区账号继续</p>
        </header>

        <el-form class="auth-form" :model="form" label-position="top" @submit.prevent="handleLogin">
          <el-form-item label="用户名">
            <el-input v-model="form.username" autocomplete="username" placeholder="请输入用户名">
              <template #prefix>
                <el-icon aria-hidden="true"><User /></el-icon>
              </template>
            </el-input>
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              autocomplete="current-password"
              placeholder="请输入密码"
              show-password
              type="password"
            >
              <template #prefix>
                <el-icon aria-hidden="true"><Lock /></el-icon>
              </template>
            </el-input>
          </el-form-item>
          <el-button class="auth-submit" type="primary" :loading="loading" native-type="submit">
            登录
            <el-icon v-if="!loading" aria-hidden="true"><ArrowRight /></el-icon>
          </el-button>
          <div class="auth-links">
            <span>还没有账号？</span>
            <router-link to="/register">注册普通用户</router-link>
          </div>
        </el-form>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, DataAnalysis, Lock, User } from '@element-plus/icons-vue'
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
  --auth-accent: #1d4ed8;
  --auth-accent-hover: #1e40af;
  --auth-ink: #172033;
  --auth-muted: #536174;
  --auth-subtle: #687586;
  --auth-border: #d8e0e9;
  box-sizing: border-box;
  display: grid;
  min-height: 100dvh;
  place-items: center;
  padding: 24px;
  color: var(--auth-ink);
  background: #edf1f5;
}

.auth-shell {
  display: grid;
  grid-template-columns: minmax(250px, 0.78fr) minmax(430px, 1.22fr);
  width: min(900px, 100%);
  min-height: min(610px, calc(100dvh - 48px));
  overflow: hidden;
  border: 1px solid var(--auth-border);
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 24px 64px rgba(33, 46, 66, 0.12);
}

.brand-panel {
  display: flex;
  flex-direction: column;
  padding: 42px;
  border-right: 1px solid var(--auth-border);
  background: #f5f7fa;
}

.brand-lockup,
.mobile-brand {
  display: inline-flex;
  align-items: center;
  gap: 11px;
}

.brand-mark {
  display: grid;
  flex: 0 0 auto;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 8px;
  color: #ffffff;
  background: var(--auth-accent);
}

.brand-text {
  display: grid;
  gap: 1px;
}

.brand-text strong {
  color: var(--auth-ink);
  font-size: 16px;
  font-weight: 720;
  line-height: 1.25;
}

.brand-text span {
  color: var(--auth-muted);
  font-size: 12px;
  line-height: 1.3;
}

.brand-copy {
  margin: auto 0;
}

.brand-copy h2 {
  max-width: 9ch;
  margin: 0;
  color: var(--auth-ink);
  font-size: 28px;
  font-weight: 680;
  line-height: 1.35;
  letter-spacing: 0;
}

.brand-copy p {
  max-width: 24ch;
  margin: 18px 0 0;
  color: var(--auth-muted);
  font-size: 14px;
  line-height: 1.75;
}

.access-note {
  display: flex;
  gap: 9px;
  align-items: center;
  padding-top: 20px;
  border-top: 1px solid var(--auth-border);
  color: var(--auth-muted);
  font-size: 12px;
  line-height: 1.5;
}

.access-note .el-icon {
  flex: 0 0 auto;
  color: var(--auth-accent);
}

.auth-panel {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  justify-content: center;
  width: min(100%, 520px);
  padding: clamp(48px, 7vw, 72px);
  margin: 0 auto;
  background: #ffffff;
}

.mobile-brand {
  display: none;
}

.form-heading {
  margin-bottom: 30px;
}

.form-heading h1 {
  margin: 0;
  color: var(--auth-ink);
  font-size: 30px;
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: 0;
}

.form-heading p {
  margin: 9px 0 0;
  color: var(--auth-muted);
  font-size: 14px;
  line-height: 1.6;
}

.auth-form {
  display: grid;
  gap: 6px;
}

:deep(.el-form-item) {
  margin-bottom: 10px;
}

:deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 8px;
  color: #344054 !important;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.4;
}

:deep(.el-input__wrapper) {
  min-height: 46px;
  padding: 1px 13px;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 0 0 1px #c8d1dc inset !important;
  transition: box-shadow 0.18s ease, background-color 0.18s ease;
}

:deep(.el-input__wrapper:hover) {
  background: #fbfcfe;
  box-shadow: 0 0 0 1px #8b9aae inset !important;
}

:deep(.el-input__wrapper.is-focus) {
  background: #ffffff;
  box-shadow: 0 0 0 1px var(--auth-accent) inset, 0 0 0 3px rgba(29, 78, 216, 0.13) !important;
}

:deep(.el-input__inner) {
  color: var(--auth-ink);
  font-size: 14px;
  caret-color: var(--auth-accent);
}

:deep(.el-input__inner::placeholder) {
  color: var(--auth-subtle);
  opacity: 1;
}

:deep(.el-input__inner:-webkit-autofill) {
  -webkit-text-fill-color: var(--auth-ink);
}

:deep(.el-input__prefix-inner),
:deep(.el-input__suffix-inner) {
  color: #536174;
}

.auth-submit {
  --el-button-bg-color: var(--auth-accent);
  --el-button-border-color: var(--auth-accent);
  --el-button-text-color: #ffffff;
  --el-button-hover-bg-color: var(--auth-accent-hover);
  --el-button-hover-border-color: var(--auth-accent-hover);
  --el-button-hover-text-color: #ffffff;
  --el-button-active-bg-color: #1e3a8a;
  --el-button-active-border-color: #1e3a8a;
  --el-button-active-text-color: #ffffff;
  width: 100%;
  min-height: 46px;
  margin-top: 6px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
  transition: transform 0.16s ease;
}

.auth-submit:active {
  transform: translateY(1px);
}

.auth-submit .el-icon {
  margin-left: 4px;
}

.auth-links {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 14px;
  color: var(--auth-muted);
  font-size: 13px;
  line-height: 1.5;
}

.auth-links a {
  border-radius: 4px;
  color: var(--auth-accent);
  font-weight: 650;
  text-decoration: none;
}

.auth-links a:hover {
  color: var(--auth-accent-hover);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.auth-links a:focus-visible {
  outline: 2px solid var(--auth-accent);
  outline-offset: 3px;
}

@media (max-width: 760px) {
  .auth-shell {
    display: block;
    width: min(480px, 100%);
    min-height: 0;
  }

  .brand-panel {
    display: none;
  }

  .auth-panel {
    min-height: min(620px, calc(100dvh - 48px));
    padding: 40px;
  }

  .mobile-brand {
    display: inline-flex;
    margin-bottom: 44px;
  }
}

@media (max-width: 480px) {
  .auth-page {
    padding: 0;
    background: #ffffff;
  }

  .auth-shell {
    min-height: 100dvh;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }

  .auth-panel {
    min-height: 100dvh;
    padding: 28px 22px 32px;
  }

  .mobile-brand {
    margin-bottom: 42px;
  }

  .form-heading {
    margin-bottom: 26px;
  }

  .form-heading h1 {
    font-size: 27px;
  }
}

@media (prefers-reduced-motion: reduce) {
  :deep(.el-input__wrapper),
  .auth-submit {
    transition: none;
  }
}
</style>
