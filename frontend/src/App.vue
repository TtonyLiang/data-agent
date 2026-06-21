<template>
  <el-config-provider :locale="zhCn">
    <el-container class="app-container">
      <el-header class="app-header">
        <div class="brand">
          <div class="brand-mark">WQ</div>
          <div>
            <h1>WenQu 智能问数</h1>
            <span>AI Data Analyst</span>
          </div>
        </div>
        <el-menu
          class="top-nav"
          :default-active="route.path"
          router
          mode="horizontal"
          :ellipsis="false"
        >
          <el-menu-item index="/" :disabled="isNavigationDisabled('/')">
            <el-icon><ChatDotRound /></el-icon>
            <span>对话</span>
          </el-menu-item>
          <el-menu-item index="/agent" :disabled="isNavigationDisabled('/agent')">
            <el-icon><User /></el-icon>
            <span>智能体管理</span>
          </el-menu-item>
          <el-menu-item index="/model-config" :disabled="isNavigationDisabled('/model-config')">
            <el-icon><Setting /></el-icon>
            <span>模型配置</span>
          </el-menu-item>
          <el-menu-item index="/prompt-config" :disabled="isNavigationDisabled('/prompt-config')">
            <el-icon><Document /></el-icon>
            <span>Prompt 配置</span>
          </el-menu-item>
          <el-menu-item index="/system-parameter" :disabled="isNavigationDisabled('/system-parameter')">
            <el-icon><Setting /></el-icon>
            <span>系统参数</span>
          </el-menu-item>
          <el-menu-item index="/datasource" :disabled="isNavigationDisabled('/datasource')">
            <el-icon><Coin /></el-icon>
            <span>数据源</span>
          </el-menu-item>
          <el-menu-item index="/knowledge" :disabled="isNavigationDisabled('/knowledge')">
            <el-icon><Document /></el-icon>
            <span>语义层配置</span>
          </el-menu-item>
        </el-menu>
        <div class="header-tools">
          <el-tag class="env-tag" :type="envTagType" effect="light" round>{{ envLabel }}</el-tag>
          <el-button :icon="Bell" circle />
          <div class="user-pill">
            <span class="avatar">Z</span>
            <span>zhangsan</span>
          </div>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-config-provider>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { chatRunState } from './stores/chatRun'
import { Bell, Setting } from '@element-plus/icons-vue'

const route = useRoute()
const appMode = import.meta.env.MODE
const envLabel = appMode === 'production' ? '生产环境' : appMode === 'development' ? '开发环境' : `${appMode} 环境`
const envTagType = appMode === 'production' ? 'success' : 'warning'

function isNavigationDisabled(path: string) {
  return chatRunState.busy && route.path !== path
}
</script>

<style>
:root {
  --wq-bg: #f7f9fc;
  --wq-surface: #ffffff;
  --wq-surface-soft: #f3f6fb;
  --wq-border: #e5eaf3;
  --wq-border-strong: #d7deeb;
  --wq-text: #172033;
  --wq-muted: #667085;
  --wq-subtle: #98a2b3;
  --wq-primary: #3f6ff3;
  --wq-primary-soft: #eef3ff;
  --wq-success: #21b26b;
  --wq-warning: #d98622;
  --wq-danger: #e5484d;
  --wq-radius: 8px;
  --wq-shadow: 0 12px 34px rgba(15, 23, 42, 0.06);
}

* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app {
  height: 100%;
  width: 100%;
  overflow: hidden;
  color: var(--wq-text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--wq-bg);
}

.app-container {
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: var(--wq-bg);
}

.app-header {
  height: 68px;
  padding: 0 24px 0 28px;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--wq-border);
  display: grid;
  grid-template-columns: 260px minmax(360px, 1fr) auto;
  align-items: center;
  gap: 18px;
  flex-shrink: 0;
  backdrop-filter: blur(12px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  background: linear-gradient(135deg, #3157e8 0%, #35b7a4 100%);
  letter-spacing: 0;
}

.brand h1 {
  font-size: 18px;
  font-weight: 760;
  line-height: 1.1;
  letter-spacing: 0;
  color: var(--wq-text);
}

.brand span {
  display: block;
  margin-top: 3px;
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1;
}

.top-nav {
  height: 68px;
  border-bottom: 0;
  background: transparent;
  min-width: 0;
}

.top-nav.el-menu--horizontal > .el-menu-item {
  height: 68px;
  padding: 0 18px;
  border-bottom-width: 2px;
  color: var(--wq-muted);
  font-size: 14px;
  letter-spacing: 0;
}

.top-nav.el-menu--horizontal > .el-menu-item.is-active {
  color: var(--wq-primary);
  font-weight: 650;
  border-bottom-color: var(--wq-primary);
  background: transparent;
}

.top-nav.el-menu--horizontal > .el-menu-item:not(.is-disabled):hover {
  color: var(--wq-primary);
  background: var(--wq-primary-soft);
}

.header-tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  min-width: 0;
}

.env-tag {
  border-radius: 999px;
  font-weight: 620;
}

.user-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: #344054;
  font-size: 14px;
  white-space: nowrap;
}

.avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #fff;
  font-weight: 700;
  background: var(--wq-primary);
}

.app-main {
  background: var(--wq-bg);
  padding: 0;
  min-width: 0;
  overflow: hidden;
}

.el-button {
  border-radius: 6px;
  font-weight: 560;
}

.el-button--primary {
  --el-button-bg-color: var(--wq-primary);
  --el-button-border-color: var(--wq-primary);
  --el-button-hover-bg-color: #315ee7;
  --el-button-hover-border-color: #315ee7;
}

.el-input__wrapper,
.el-textarea__inner,
.el-select__wrapper {
  border-radius: 6px;
  box-shadow: 0 0 0 1px var(--wq-border) inset;
}

.el-table {
  --el-table-header-bg-color: #f8fafc;
  --el-table-header-text-color: #344054;
  --el-table-border-color: var(--wq-border);
  --el-table-row-hover-bg-color: #f4f7ff;
  color: #344054;
}

@media (max-width: 1080px) {
  .app-header {
    grid-template-columns: auto 1fr;
    height: auto;
    min-height: 68px;
    padding: 10px 16px;
    gap: 8px 14px;
  }

  .top-nav {
    order: 3;
    grid-column: 1 / -1;
    height: 46px;
    overflow-x: auto;
  }

  .top-nav.el-menu--horizontal > .el-menu-item {
    height: 46px;
    padding: 0 10px;
    font-size: 13px;
  }

  .header-tools .env-tag {
    display: none;
  }
}

@media (max-width: 520px) {
  .app-header {
    padding: 10px 14px;
  }

  .brand h1 {
    font-size: 17px;
  }

  .brand span,
  .user-pill span:not(.avatar) {
    display: none;
  }

  .top-nav.el-menu--horizontal > .el-menu-item {
    padding: 0 8px;
  }
}
</style>
