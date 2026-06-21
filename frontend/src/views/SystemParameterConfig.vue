<template>
  <section class="system-page">
    <div class="page-head">
      <div>
        <h2>系统参数</h2>
        <p>统一维护运行参数和 Prompt 模板。这里的配置优先于后端默认值。</p>
      </div>
      <div class="head-actions">
        <el-button v-if="activeTab === 'runtime'" :icon="Refresh" @click="loadParameters">刷新</el-button>
        <el-button v-if="activeTab === 'runtime'" type="primary" :icon="Check" :loading="saving" @click="saveParameters">
          保存
        </el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane label="运行参数" name="runtime">
        <div class="content">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="数据定位召回策略"
            description="候选表先按分数排序，再按最高分的相对阈值筛选。阈值越高，召回越严格，大模型上下文噪音越少。"
          />

          <el-form v-loading="loading" class="param-form" label-position="top">
            <div class="param-grid">
              <div v-for="item in schemaRecallParams" :key="item.key" class="param-row">
                <div class="param-meta">
                  <h3>{{ item.name }}</h3>
                  <p>{{ item.description }}</p>
                  <el-tag size="small" effect="plain">{{ item.key }}</el-tag>
                </div>
                <div class="param-control">
                  <el-input-number
                    v-if="item.value_type === 'int'"
                    v-model="form[item.key]"
                    :min="1"
                    :max="50"
                    :step="1"
                    controls-position="right"
                  />
                  <el-input-number
                    v-else-if="item.value_type === 'float'"
                    v-model="form[item.key]"
                    :min="0"
                    :max="1"
                    :step="0.01"
                    :precision="2"
                    controls-position="right"
                  />
                  <el-input v-else v-model="form[item.key]" />
                </div>
              </div>
            </div>
          </el-form>

          <div class="example-panel">
            <h3>筛选示例</h3>
            <p>
              如果最高分是 2162，必须召回阈值 0.35，则强相关线是 756.7；可召回阈值 0.15，则补充线是 324.3。
              分数低于补充线的表会被剔除，不再机械进入 TopN。
            </p>
          </div>
        </div>
      </el-tab-pane>
      <el-tab-pane label="Prompt 模板" name="prompt">
        <PromptConfig embedded />
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Check, Refresh } from '@element-plus/icons-vue'
import PromptConfig from './PromptConfig.vue'
import {
  fetchSystemParameters,
  updateSystemParameters,
  type SystemParameterItem,
} from '../api'

const loading = ref(false)
const saving = ref(false)
const route = useRoute()
const router = useRouter()
const activeTab = ref(route.query.tab === 'prompt' ? 'prompt' : 'runtime')
const parameters = ref<SystemParameterItem[]>([])
const form = reactive<Record<string, number | string | boolean | Record<string, unknown> | unknown[]>>({})

const schemaRecallParams = computed(() =>
  parameters.value.filter((item) => item.category === 'schema_recall'),
)

watch(
  () => route.query.tab,
  (tab) => {
    activeTab.value = tab === 'prompt' ? 'prompt' : 'runtime'
  },
)

watch(activeTab, (tab) => {
  const query = tab === 'prompt' ? { tab: 'prompt' } : {}
  router.replace({ path: '/system-parameter', query })
})

async function loadParameters() {
  loading.value = true
  try {
    parameters.value = await fetchSystemParameters('schema_recall')
    for (const item of parameters.value) {
      form[item.key] = item.value
    }
  } finally {
    loading.value = false
  }
}

async function saveParameters() {
  const required = Number(form['schema_recall.required_score_ratio'])
  const optional = Number(form['schema_recall.optional_score_ratio'])
  if (optional > required) {
    ElMessage.warning('可召回相对分阈值不能大于必须召回相对分阈值')
    return
  }
  saving.value = true
  try {
    const payload = schemaRecallParams.value.map((item) => ({
      key: item.key,
      value: form[item.key],
    }))
    const result = await updateSystemParameters(payload)
    parameters.value = result.parameters.filter((item) => item.category === 'schema_recall')
    ElMessage.success(result.message || '保存成功')
  } finally {
    saving.value = false
  }
}

onMounted(loadParameters)
</script>

<style scoped>
.system-page {
  height: 100%;
  overflow: auto;
  padding: 24px;
}

.page-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.page-head h2 {
  font-size: 22px;
  line-height: 1.2;
  margin: 0 0 6px;
}

.page-head p,
.param-meta p,
.example-panel p {
  color: var(--wq-muted);
  font-size: 14px;
  line-height: 1.6;
}

.head-actions {
  display: flex;
  gap: 8px;
}

.content {
  display: grid;
  gap: 16px;
}

.param-form,
.example-panel {
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  padding: 18px;
}

.param-grid {
  display: grid;
  gap: 14px;
}

.param-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 20px;
  align-items: center;
  padding: 14px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fbfcff;
}

.param-meta h3,
.example-panel h3 {
  margin: 0 0 6px;
  font-size: 15px;
}

.param-meta p {
  margin: 0 0 8px;
}

.param-control {
  display: flex;
  justify-content: flex-end;
}

.param-control :deep(.el-input-number) {
  width: 180px;
}

@media (max-width: 720px) {
  .page-head,
  .param-row {
    grid-template-columns: 1fr;
    display: grid;
  }

  .head-actions,
  .param-control {
    justify-content: flex-start;
  }
}
</style>
