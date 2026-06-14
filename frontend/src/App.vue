<template>
  <el-config-provider :locale="zhCn">
    <el-container class="app-container">
      <el-aside width="200px" class="app-aside">
        <div class="logo">
          <h2>WenQu 智能问数</h2>
        </div>
        <el-menu
          :default-active="route.path"
          router
          background-color="#304156"
          text-color="#bfcbd9"
          active-text-color="#409eff"
        >
          <el-menu-item index="/" :disabled="isNavigationDisabled('/')">
            <el-icon><ChatDotRound /></el-icon>
            <span>对话</span>
          </el-menu-item>
          <el-menu-item index="/agent" :disabled="isNavigationDisabled('/agent')">
            <el-icon><User /></el-icon>
            <span>智能体管理</span>
          </el-menu-item>
          <el-menu-item index="/datasource" :disabled="isNavigationDisabled('/datasource')">
            <el-icon><Coin /></el-icon>
            <span>数据源</span>
          </el-menu-item>
          <el-menu-item index="/knowledge" :disabled="isNavigationDisabled('/knowledge')">
            <el-icon><Document /></el-icon>
            <span>知识库</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
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

const route = useRoute()

function isNavigationDisabled(path: string) {
  return chatRunState.busy && route.path !== path
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { height: 100%; width: 100%; overflow: hidden; }
.app-container { height: 100vh; width: 100vw; overflow: hidden; }
.app-aside {
  background-color: #304156;
  overflow: hidden;
  flex: 0 0 200px;
}
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
.logo h2 { font-size: 16px; }
.app-main {
  background: #f5f7fa;
  padding: 20px;
  min-width: 0;
  overflow: hidden;
}
</style>
