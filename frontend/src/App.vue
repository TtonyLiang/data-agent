<template>
  <el-config-provider :locale="zhCn">
    <router-view v-if="isAuthPage" />
    <el-container class="app-container" direction="vertical">
      <template v-if="!isAuthPage">
      <el-header class="app-header">
        <div class="brand">
          <div class="brand-mark">WQ</div>
          <div>
            <h1>问渠 WenQu</h1>
            <span>AI报告交付与风险决策平台</span>
          </div>
        </div>
        <el-menu
          class="top-nav"
          :default-active="route.path"
          router
          mode="horizontal"
          :ellipsis="true"
        >
          <el-menu-item index="/" :disabled="isNavigationDisabled('/')">
            <el-icon><ChatDotRound /></el-icon>
            <span>对话</span>
          </el-menu-item>
          <el-menu-item v-if="isAdminUser" index="/agent" :disabled="isNavigationDisabled('/agent')">
            <el-icon><User /></el-icon>
            <span>智能体管理</span>
          </el-menu-item>
          <el-menu-item v-if="isAdminUser" index="/model-config" :disabled="isNavigationDisabled('/model-config')">
            <el-icon><Setting /></el-icon>
            <span>模型配置</span>
          </el-menu-item>
          <el-menu-item v-if="isAdminUser" index="/datasource" :disabled="isNavigationDisabled('/datasource')">
            <el-icon><Coin /></el-icon>
            <span>数据源</span>
          </el-menu-item>
          <el-menu-item v-if="isAdminUser" index="/knowledge" :disabled="isNavigationDisabled('/knowledge')">
            <el-icon><Document /></el-icon>
            <span>查询语义</span>
          </el-menu-item>
          <el-menu-item v-if="isAuthenticatedUser" index="/risk-delivery" :disabled="isNavigationDisabled('/risk-delivery')">
            <el-icon><WarningFilled /></el-icon>
            <span>风险交付</span>
          </el-menu-item>
          <el-menu-item v-if="isAuthenticatedUser" index="/ontology" :disabled="isNavigationDisabled('/ontology')">
            <el-icon><Share /></el-icon>
            <span>本体建模</span>
          </el-menu-item>
          <el-menu-item v-if="isAdminUser" index="/system-parameter" :disabled="isNavigationDisabled('/system-parameter')">
            <el-icon><Setting /></el-icon>
            <span>系统参数</span>
          </el-menu-item>
        </el-menu>
        <div class="header-tools">
          <el-tag class="env-tag" :type="envTagType" effect="light" round>{{ envLabel }}</el-tag>
          <el-button :icon="Bell" circle aria-label="通知" title="通知" />
          <div class="user-pill">
            <span class="avatar">{{ userInitial }}</span>
            <span>{{ displayName }}</span>
          </div>
          <el-button text @click="handleLogout">退出</el-button>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
      </template>
    </el-container>
  </el-config-provider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { chatRunState } from './stores/chatRun'
import { Bell, Setting } from '@element-plus/icons-vue'
import { authState, isAdmin, isLoggedIn, logout } from './stores/auth'

const route = useRoute()
const router = useRouter()
const appMode = import.meta.env.MODE
const envLabel = appMode === 'production' ? '生产环境' : appMode === 'development' ? '开发环境' : `${appMode} 环境`
const envTagType = appMode === 'production' ? 'success' : 'warning'
const isAdminUser = computed(() => isAdmin())
const isAuthenticatedUser = computed(() => isLoggedIn())
const isAuthPage = computed(() => route.path === '/login' || route.path === '/register')
const displayName = computed(() => authState.currentUser?.display_name || authState.currentUser?.username || '')
const userInitial = computed(() => (displayName.value || 'U').slice(0, 1).toUpperCase())

function isNavigationDisabled(path: string) {
  return chatRunState.busy && route.path !== path
}

async function handleLogout() {
  await logout()
  router.replace('/login')
}
</script>

<style>
:root {
  color-scheme: light;
  --wq-bg: #f4f6f9;
  --wq-surface: #ffffff;
  --wq-surface-soft: #f7f9fc;
  --wq-surface-raised: #eef2f7;
  --wq-border: #dfe4ec;
  --wq-border-strong: #c8d1de;
  --wq-text: #182230;
  --wq-muted: #475467;
  --wq-subtle: #667085;
  --wq-primary: #2563eb;
  --wq-primary-hover: #1d4ed8;
  --wq-primary-strong: #1d4ed8;
  --wq-primary-soft: #eff6ff;
  --wq-success: #067647;
  --wq-warning: #b54708;
  --wq-danger: #b42318;
  --wq-code: #101828;
  --wq-radius: 8px;
  --wq-control-radius: 7px;
  --wq-shadow: 0 8px 24px rgba(24, 34, 48, 0.08);
  --wq-header-height: 64px;

  --el-color-primary: var(--wq-primary-strong);
  --el-color-success: var(--wq-success);
  --el-color-warning: var(--wq-warning);
  --el-color-danger: var(--wq-danger);
  --el-bg-color: var(--wq-surface);
  --el-bg-color-page: var(--wq-bg);
  --el-bg-color-overlay: var(--wq-surface);
  --el-fill-color-blank: var(--wq-surface);
  --el-fill-color-light: #f4f6f9;
  --el-fill-color-lighter: #f8fafc;
  --el-fill-color-extra-light: #fbfcfe;
  --el-fill-color-dark: #e8edf3;
  --el-fill-color-darker: #dfe5ec;
  --el-fill-color: #eef2f6;
  --el-text-color-primary: var(--wq-text);
  --el-text-color-regular: #344054;
  --el-text-color-secondary: var(--wq-muted);
  --el-text-color-placeholder: var(--wq-subtle);
  --el-border-color: var(--wq-border);
  --el-border-color-light: #e5e9f0;
  --el-border-color-lighter: #edf0f4;
  --el-border-color-extra-light: #f2f4f7;
  --el-mask-color: rgba(16, 24, 40, 0.42);
  --el-box-shadow-light: var(--wq-shadow);
  --el-border-radius-base: var(--wq-control-radius);
  --el-border-radius-small: 6px;
  --el-font-size-base: 14px;
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html, body, #app {
  height: 100%;
  width: 100%;
  overflow: hidden;
  color: var(--wq-text);
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 14px;
  line-height: 1.5;
  background: var(--wq-bg);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

.app-container {
  height: 100dvh;
  width: 100vw;
  overflow: hidden;
  background: var(--wq-bg);
  display: flex;
  flex-direction: column;
}

.app-header {
  height: var(--wq-header-height);
  padding: 0 20px;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--wq-border);
  display: grid;
  grid-template-columns: minmax(190px, 220px) minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  backdrop-filter: blur(14px) saturate(120%);
  -webkit-backdrop-filter: blur(14px) saturate(120%);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: #ffffff;
  font-size: 12px;
  font-weight: 750;
  background: var(--wq-primary);
  letter-spacing: 0;
}

.brand h1 {
  font-size: 16px;
  font-weight: 680;
  line-height: 1.2;
  letter-spacing: 0;
  color: var(--wq-text);
}

.brand span {
  display: block;
  margin-top: 1px;
  color: var(--wq-muted);
  font-size: 12px;
  line-height: 1.2;
}

.top-nav {
  width: 100%;
  height: var(--wq-header-height);
  border-bottom: 0;
  background: transparent;
  min-width: 0;
  --el-menu-active-color: var(--wq-primary-strong);
  --el-menu-text-color: var(--wq-muted);
  --el-menu-hover-text-color: var(--wq-text);
  --el-menu-hover-bg-color: var(--wq-surface-soft);
}

.top-nav.el-menu--horizontal > .el-menu-item {
  flex: 0 0 auto;
  height: 36px;
  margin: 14px 2px;
  padding: 0 12px;
  border-bottom: 0;
  border-radius: var(--wq-control-radius);
  color: var(--wq-muted);
  font-size: 14px;
  font-weight: 520;
  letter-spacing: 0;
  white-space: nowrap;
}

.top-nav.el-menu--horizontal > .el-menu-item.is-active {
  color: var(--wq-primary-strong);
  font-weight: 650;
  background: var(--wq-primary-soft);
}

.top-nav.el-menu--horizontal > .el-menu-item.is-active .el-icon {
  color: var(--wq-primary);
}

.top-nav.el-menu--horizontal > .el-menu-item:not(.is-disabled):not(.is-active):hover {
  color: var(--wq-text);
  background: var(--wq-surface-raised);
}

.top-nav.el-menu--horizontal > .el-menu-item.is-disabled {
  color: var(--wq-subtle);
}

.header-tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.env-tag {
  border-radius: 6px;
  font-size: 12px;
  font-weight: 620;
}

.env-tag.el-tag--success {
  --el-tag-bg-color: #ecfdf3;
  --el-tag-border-color: #abefc6;
  --el-tag-text-color: #067647;
}

.env-tag.el-tag--warning {
  --el-tag-bg-color: #fff7ed;
  --el-tag-border-color: #fed7aa;
  --el-tag-text-color: #9a3412;
}

.user-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 3px 6px 3px 3px;
  color: #344054;
  font-size: 14px;
  font-weight: 520;
  white-space: nowrap;
}

.user-pill > span:last-child {
  max-width: 128px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.avatar {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  color: var(--wq-primary-strong);
  font-size: 12px;
  font-weight: 700;
  background: var(--wq-primary-soft);
  border: 1px solid #bfdbfe;
}

.app-main {
  background: var(--wq-bg);
  padding: 0;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.el-button {
  border-radius: var(--wq-control-radius);
  font-weight: 600;
}

.header-tools .el-button {
  --el-button-text-color: var(--wq-muted);
  --el-button-hover-text-color: var(--wq-text);
  --el-button-hover-bg-color: var(--wq-surface-soft);
  --el-button-active-bg-color: var(--wq-surface-raised);
}

.el-button--primary {
  --el-button-bg-color: var(--wq-primary-strong);
  --el-button-border-color: var(--wq-primary-strong);
  --el-button-hover-bg-color: var(--wq-primary-hover);
  --el-button-hover-border-color: var(--wq-primary-hover);
  --el-button-active-bg-color: #1e40af;
  --el-button-active-border-color: #1e40af;
}

.el-input__wrapper,
.el-textarea__inner,
.el-select__wrapper {
  border-radius: var(--wq-control-radius);
  box-shadow: 0 0 0 1px var(--wq-border) inset;
  background: var(--wq-surface);
}

.el-table {
  --el-table-header-bg-color: #f7f9fc;
  --el-table-header-text-color: #344054;
  --el-table-border-color: var(--wq-border);
  --el-table-row-hover-bg-color: #f2f6ff;
  --el-table-tr-bg-color: var(--wq-surface);
  --el-table-bg-color: var(--wq-surface);
  color: #344054;
}

@media (max-width: 1560px) {
  .app-header {
    grid-template-columns: 204px minmax(0, 1fr) auto;
    padding-inline: 16px;
  }

  .header-tools .env-tag {
    display: none;
  }

  .top-nav.el-menu--horizontal > .el-menu-item {
    margin-inline: 0;
    padding-inline: 9px;
  }
}

@media (max-width: 1240px) {
  .user-pill > span:last-child {
    max-width: 92px;
  }

  .top-nav.el-menu--horizontal > .el-menu-item {
    padding-inline: 8px;
  }
}

@media (max-width: 1080px) {
  :root {
    --wq-header-height: 102px;
  }

  .app-header {
    grid-template-columns: minmax(0, 1fr) auto;
    height: auto;
    min-height: var(--wq-header-height);
    padding: 8px 14px;
    gap: 8px 12px;
  }

  .top-nav {
    order: 3;
    grid-column: 1 / -1;
    height: 42px;
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: none;
  }

  .top-nav::-webkit-scrollbar {
    display: none;
  }

  .top-nav.el-menu--horizontal > .el-menu-item {
    height: 32px;
    margin: 5px 2px;
    padding: 0 10px;
    font-size: 14px;
  }
}

@media (max-width: 520px) {
  .app-header {
    padding: 8px 12px;
  }

  .brand h1 {
    font-size: 15px;
  }

  .brand span,
  .user-pill span:not(.avatar) {
    display: none;
  }

  .top-nav.el-menu--horizontal > .el-menu-item {
    padding: 0 10px;
  }
}
</style>
