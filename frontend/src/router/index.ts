import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { chatRunState } from '../stores/chatRun'

const routes = [
  { path: '/', name: 'Chat', component: () => import('../views/ChatView.vue') },
  { path: '/agent', name: 'Agent', component: () => import('../views/AgentList.vue') },
  { path: '/model-config', name: 'ModelConfig', component: () => import('../views/ModelConfig.vue') },
  { path: '/prompt-config', name: 'PromptConfig', component: () => import('../views/PromptConfig.vue') },
  { path: '/system-parameter', name: 'SystemParameter', component: () => import('../views/SystemParameterConfig.vue') },
  { path: '/datasource', name: 'Datasource', component: () => import('../views/DatasourceConfig.vue') },
  { path: '/knowledge', name: 'SemanticRuntime', component: () => import('../views/KnowledgeConfig.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from) => {
  if (chatRunState.busy && to.path !== from.path) {
    ElMessage.warning('当前对话正在生成，请等待完成后再切换页面')
    return false
  }
  return true
})

export default router
