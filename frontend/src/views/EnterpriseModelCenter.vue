<template>
  <div class="enterprise-model-center">
    <header class="model-center-bar">
      <div class="model-center-title">
        <strong>企业模型</strong>
        <span>用同一套业务语言连接本体结构与数据口径</span>
      </div>

      <nav class="model-sections" :class="{ single: !canManage }" aria-label="企业模型功能">
        <button
          type="button"
          :class="{ active: activeSection === 'ontology' }"
          :aria-current="activeSection === 'ontology' ? 'page' : undefined"
          @click="selectSection('ontology')"
        >
          <span class="section-index">1</span>
          <span>
            <b>业务本体</b>
            <small>对象、关系、状态与动作</small>
          </span>
        </button>
        <span v-if="canManage" class="section-connector" aria-hidden="true">+</span>
        <button
          v-if="canManage"
          type="button"
          :class="{ active: activeSection === 'semantic' }"
          :aria-current="activeSection === 'semantic' ? 'page' : undefined"
          @click="selectSection('semantic')"
        >
          <span class="section-index">2</span>
          <span>
            <b>语义与数据</b>
            <small>指标、规则、映射与查询口径</small>
          </span>
        </button>
      </nav>

      <div class="model-center-outcome">
        <span>企业空间</span>
        <strong>{{ workspaceName }}</strong>
        <small>{{ workspaceDomainCount }} 个业务领域 · 企业资产统一归属</small>
      </div>
    </header>

    <main class="model-center-workspace">
      <OntologyWorkbench v-if="activeSection === 'ontology'" />
      <KnowledgeConfig v-else />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  fetchEnterpriseWorkspaces,
  fetchOntologyDomains,
  fetchWorkspaceDomains,
  type EnterpriseWorkspace,
} from '../api'
import { isAdmin } from '../stores/auth'

const OntologyWorkbench = defineAsyncComponent(() => import('./OntologyWorkbench.vue'))
const KnowledgeConfig = defineAsyncComponent(() => import('./KnowledgeConfig.vue'))

const route = useRoute()
const router = useRouter()
const workspaces = ref<EnterpriseWorkspace[]>([])
const workspaceDomainCount = ref(0)
const canManage = computed(() => isAdmin())
const workspaceName = computed(() => workspaces.value[0]?.name || '默认企业空间')

const activeSection = computed<'ontology' | 'semantic'>(() => (
  canManage.value && route.query.section === 'semantic' ? 'semantic' : 'ontology'
))

onMounted(async () => {
  const visibleDomains = await fetchOntologyDomains().catch(() => [])
  workspaceDomainCount.value = visibleDomains.length
  if (!canManage.value) return
  try {
    workspaces.value = await fetchEnterpriseWorkspaces()
    if (workspaces.value[0]) {
      workspaceDomainCount.value = (await fetchWorkspaceDomains(workspaces.value[0].id)).length
    }
  } catch {
    workspaces.value = []
  }
})

function selectSection(section: 'ontology' | 'semantic') {
  if (section === activeSection.value) return
  router.replace({
    path: '/enterprise-model',
    query: { ...route.query, section },
  })
}
</script>

<style scoped>
.enterprise-model-center {
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--wq-bg);
}

.model-center-bar {
  min-height: 76px;
  padding: 10px var(--wq-page-gutter);
  display: grid;
  grid-template-columns: minmax(200px, 0.8fr) minmax(470px, 1.5fr) minmax(220px, 0.8fr);
  align-items: center;
  gap: 20px;
  background: var(--wq-surface);
  border-bottom: 1px solid var(--wq-border);
}

.model-center-title,
.model-center-outcome {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.model-center-title strong {
  color: var(--wq-text);
  font-size: 18px;
  line-height: 1.3;
}

.model-center-title span,
.model-center-outcome span,
.model-center-outcome small {
  color: var(--wq-muted);
  font-size: 12px;
}

.model-sections {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 20px minmax(0, 1fr);
  align-items: center;
  gap: 6px;
}

.model-sections.single {
  grid-template-columns: minmax(0, 1fr);
}

.model-sections button {
  min-width: 0;
  min-height: 52px;
  padding: 7px 12px;
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--wq-muted);
  text-align: left;
  background: var(--wq-surface-soft);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  cursor: pointer;
  transition: color 140ms ease, border-color 140ms ease, background-color 140ms ease, transform 100ms ease;
}

.model-sections button:hover {
  color: var(--wq-text);
  border-color: #93b4fb;
}

.model-sections button:active {
  transform: scale(0.99);
}

.model-sections button.active {
  color: var(--wq-primary-strong);
  background: var(--wq-primary-soft);
  border-color: #93b4fb;
  box-shadow: inset 3px 0 0 var(--wq-primary);
}

.model-sections button > span:last-child {
  min-width: 0;
  display: grid;
  gap: 1px;
}

.model-sections b,
.model-sections small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-sections b {
  font-size: 14px;
}

.model-sections small {
  color: var(--wq-subtle);
  font-size: 12px;
}

.section-index {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  display: grid;
  place-items: center;
  color: var(--wq-primary-strong);
  font-size: 12px;
  font-weight: 700;
  background: #ffffff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
}

.section-connector {
  color: var(--wq-subtle);
  font-size: 16px;
  text-align: center;
}

.model-center-outcome {
  padding-left: 18px;
  border-left: 1px solid var(--wq-border);
}

.model-center-outcome strong {
  color: var(--wq-text);
  font-size: 13px;
  line-height: 1.45;
}

.model-center-outcome small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-center-workspace {
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

@media (max-width: 1120px) {
  .model-center-bar {
    grid-template-columns: 180px minmax(430px, 1fr);
  }

  .model-center-outcome {
    display: none;
  }
}

@media (max-width: 760px) {
  .model-center-bar {
    min-height: 0;
    padding: 10px 16px;
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .model-center-title span {
    display: none;
  }

  .model-sections {
    grid-template-columns: minmax(0, 1fr) 12px minmax(0, 1fr);
  }

  .model-sections button {
    padding: 7px 8px;
  }

  .model-sections small {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .model-sections button {
    transition: none;
  }
}
</style>
