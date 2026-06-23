import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { chatRunState } from '../stores/chatRun'
import { adminOnlyPaths, initAuth, isAdmin, isLoggedIn } from '../stores/auth'

const routes = [
  { path: '/', name: 'Chat', component: () => import('../views/ChatView.vue') },
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
  { path: '/register', name: 'Register', component: () => import('../views/RegisterView.vue'), meta: { public: true } },
  { path: '/agent', name: 'Agent', component: () => import('../views/AgentList.vue') },
  { path: '/model-config', name: 'ModelConfig', component: () => import('../views/ModelConfig.vue') },
  { path: '/prompt-config', redirect: { path: '/system-parameter', query: { tab: 'prompt' } } },
  { path: '/system-parameter', name: 'SystemParameter', component: () => import('../views/SystemParameterConfig.vue') },
  { path: '/datasource', name: 'Datasource', component: () => import('../views/DatasourceConfig.vue') },
  { path: '/knowledge', name: 'SemanticRuntime', component: () => import('../views/KnowledgeConfig.vue') },
  { path: '/users', redirect: { path: '/system-parameter', query: { tab: 'users' } } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, from) => {
  if (!to.meta.public) await initAuth()
  if (!to.meta.public && !isLoggedIn()) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.public && isLoggedIn()) return { path: '/' }
  if (adminOnlyPaths.has(to.path) && !isAdmin()) {
    ElMessage.warning('无权访问该页面')
    return { path: '/' }
  }
  if (chatRunState.busy && to.path !== from.path) {
    ElMessage.warning('当前对话正在生成，请等待完成后再切换页面')
    return false
  }
  return true
})

export default router
