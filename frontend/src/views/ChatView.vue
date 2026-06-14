<template>
  <div class="chat-layout">
    <!-- 会话侧边栏 -->
    <div class="session-sidebar">
      <div class="sidebar-header">
        <h4>历史会话</h4>
        <el-button size="small" type="primary" :disabled="loading" @click="newSession">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
      </div>
      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.session_id"
          :class="['session-item', { active: s.session_id === sessionId, disabled: loading }]"
          @click="loadSession(s.session_id)"
        >
          <div class="session-title">{{ s.last_question || '新对话' }}</div>
          <div class="session-meta">{{ s.turn_count }}轮 · {{ formatTime(s.created_at) }}</div>
          <el-icon class="session-delete" @click.stop="handleDeleteSession(s.session_id)"><Delete /></el-icon>
        </div>
        <div v-if="sessions.length === 0" class="empty-sessions">暂无历史会话</div>
      </div>
    </div>

    <!-- 对话主区域 -->
    <div class="chat-container">
      <div class="chat-header">
        <h3>智能问数对话</h3>
        <div class="chat-controls">
          <el-select
            v-model="datasourceId"
            placeholder="选择数据源"
            style="width: 200px"
            size="small"
            :disabled="loading"
          >
            <el-option
              v-for="ds in datasources"
              :key="ds.id"
              :label="`${ds.name} (${ds.database_name})`"
              :value="ds.id"
            />
          </el-select>
          <el-select
            v-model="agentId"
            placeholder="选择智能体"
            style="width: 180px"
            size="small"
            :disabled="loading"
          >
            <el-option
              v-for="agent in agents"
              :key="agent.id"
              :label="agent.name"
              :value="agent.id"
            />
          </el-select>
        </div>
      </div>

      <div class="chat-messages" ref="messagesRef">
        <div v-if="messages.length === 0 && !chain.steps.length" class="empty-hint">
          <el-icon :size="48" color="#c0c4cc"><ChatDotRound /></el-icon>
          <p>输入自然语言问题开始查询</p>
          <p class="examples">例如: "上个月的总销售额是多少？" "各地区订单量排名前10"</p>
        </div>

        <!-- 历史消息 -->
        <template v-for="(msg, idx) in messages" :key="idx">
          <div :class="['message', msg.role]">
            <div class="message-content">
              <div v-if="msg.role === 'assistant'" class="meta">
                <el-tag v-if="msg.intent" size="small" type="info">{{ msg.intent }}</el-tag>
                <el-tag v-if="msg.sql" size="small" type="success">SQL</el-tag>
              </div>
              <div class="text" v-html="msg.content"></div>
              <div v-if="msg.sql" class="sql-block">
                <pre><code>{{ msg.sql }}</code></pre>
              </div>
              <div v-if="msg.sql_result && msg.sql_result.length > 0" class="result-table">
                <el-table :data="msg.sql_result" border size="small" max-height="300">
                  <el-table-column
                    v-for="col in Object.keys(msg.sql_result[0])"
                    :key="col"
                    :prop="col"
                    :label="col"
                    min-width="120"
                  />
                </el-table>
              </div>
            </div>
          </div>
        </template>

        <!-- 正在执行: 链式思考面板 -->
        <div v-if="chain.steps.length > 0" class="chain-panel">
          <div class="chain-header">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>分析中...</span>
          </div>

          <div v-for="(step, idx) in chain.steps" :key="idx" class="chain-step">
            <div class="step-header">
              <span :class="['step-status', step.status]">
                <el-icon v-if="step.status === 'running'" class="is-loading"><Loading /></el-icon>
                <el-icon v-else-if="step.status === 'done'"><CircleCheck /></el-icon>
                <el-icon v-else><Clock /></el-icon>
              </span>
              <span class="step-label">{{ step.label }}</span>
              <span v-if="step.summary" class="step-summary">{{ step.summary }}</span>
            </div>

            <!-- 思考过程 (可折叠) -->
            <div v-if="step.reasoning" class="step-reasoning">
              <div class="reasoning-toggle" @click="step.showReasoning = !step.showReasoning">
                <el-icon><View v-if="!step.showReasoning" /><Hide v-else /></el-icon>
                <span>思考过程 ({{ step.reasoning.length }}字)</span>
              </div>
              <div v-if="step.showReasoning" class="reasoning-content">
                {{ step.reasoning }}
              </div>
            </div>

            <!-- 节点输出 -->
            <div v-if="step.output" class="step-output">
              <div v-if="step.node === 'sql_generate' && step.output.sql" class="output-sql">
                <pre><code>{{ step.output.sql }}</code></pre>
              </div>
              <div v-else-if="step.node === 'sql_execute' && step.output.row_count !== undefined" class="output-result">
                <span v-if="step.output.error" class="error">错误: {{ step.output.error }}</span>
                <span v-else>返回 {{ step.output.row_count }} 条结果</span>
              </div>
              <div v-else-if="step.output.tables" class="output-tables">
                表: {{ step.output.tables.join(', ') }}
              </div>
              <div v-else-if="step.output.enhanced_query" class="output-enhanced">
                改写: {{ step.output.enhanced_query }}
              </div>
              <div v-else-if="step.output.items" class="output-evidence">
                知识: {{ step.output.items.join(', ') }}
              </div>
            </div>
          </div>
        </div>

        <!-- 流式输出的最终结果 -->
        <div v-if="streamResult" class="message assistant">
          <div class="message-content">
            <div class="meta">
              <el-tag v-if="streamResult.intent" size="small" type="info">{{ streamResult.intent }}</el-tag>
              <el-tag v-if="streamResult.sql" size="small" type="success">SQL</el-tag>
            </div>
            <div class="text" v-html="streamResult.answer"></div>
            <div v-if="streamResult.sql" class="sql-block">
              <pre><code>{{ streamResult.sql }}</code></pre>
            </div>
            <div v-if="streamResult.sql_result && streamResult.sql_result.length > 0" class="result-table">
              <el-table :data="streamResult.sql_result" border size="small" max-height="300">
                <el-table-column
                  v-for="col in Object.keys(streamResult.sql_result[0])"
                  :key="col"
                  :prop="col"
                  :label="col"
                  min-width="120"
                />
              </el-table>
            </div>
          </div>
        </div>
      </div>

      <div class="chat-input">
        <el-input
          v-model="inputText"
          placeholder="输入你的问题..."
          :disabled="loading"
          @keydown.enter="handleSend"
          size="large"
        >
          <template #append>
            <el-button :icon="Promotion" @click="handleSend" :loading="loading" type="primary">
              发送
            </el-button>
          </template>
        </el-input>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, nextTick, onUnmounted, watch } from 'vue'
import { Promotion, Loading, ChatDotRound, Plus, Delete, CircleCheck, Clock, View, Hide } from '@element-plus/icons-vue'
import {
  sendMessageStream, fetchAgents, fetchDatasources, fetchSessions, fetchHistory, deleteSession,
  type AgentItem, type ChatResponse, type DatasourceItem, type SessionItem, type HistoryItem,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { setChatBusy } from '../stores/chatRun'

interface Message {
  role: 'user' | 'assistant'
  content: string
  intent?: string
  sql?: string
  sql_result?: Record<string, unknown>[]
}

interface ChainStep {
  node: string
  label: string
  status: 'running' | 'done' | 'pending'
  reasoning: string
  showReasoning: boolean
  output: Record<string, any> | null
  summary: string
}

const messages = ref<Message[]>([])
const inputText = ref('')
const loading = ref(false)
const agentId = ref<number>(Number(localStorage.getItem('wenqu_agent_id')) || 1)
const agents = ref<AgentItem[]>([])
const datasourceId = ref<number | null>(null)
const datasources = ref<DatasourceItem[]>([])
const sessions = ref<SessionItem[]>([])
const sessionId = ref<string>('')
const messagesRef = ref<HTMLElement>()
const streamResult = ref<ChatResponse | null>(null)
let abortController: AbortController | null = null
let activeRunId = 0

const chain = reactive<{ steps: ChainStep[] }>({ steps: [] })

onMounted(async () => {
  await loadAgents()
  await refreshAgentScopedData()
})

watch(agentId, async (id) => {
  if (loading.value) return
  cancelActiveStream()
  localStorage.setItem('wenqu_agent_id', String(id))
  resetConversation()
  await refreshAgentScopedData()
})

async function loadAgents() {
  try {
    agents.value = await fetchAgents()
    if (agents.value.length > 0 && !agents.value.some(agent => agent.id === agentId.value)) {
      agentId.value = agents.value[0].id
    }
  } catch {
    agents.value = []
  }
}

async function refreshAgentScopedData() {
  try {
    datasources.value = await fetchDatasources(agentId.value)
    if (datasources.value.length > 0) {
      datasourceId.value = datasources.value[0].id
    } else {
      datasourceId.value = null
    }
  } catch { /* empty */ }
  await loadSessions()
}

function formatTime(t: string) {
  if (!t) return ''
  const d = new Date(t)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function loadSessions() {
  try { sessions.value = await fetchSessions(agentId.value) } catch { sessions.value = [] }
}

function cancelActiveStream() {
  activeRunId += 1
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  setLoading(false)
}

function setLoading(value: boolean) {
  loading.value = value
  setChatBusy(value)
}

function resetConversation() {
  sessionId.value = ''
  messages.value = []
  chain.steps = []
  streamResult.value = null
}

function newSession() {
  cancelActiveStream()
  resetConversation()
}

async function loadSession(sid: string) {
  if (loading.value) {
    ElMessage.warning('当前对话正在生成，请等待完成后再切换会话')
    return
  }
  cancelActiveStream()
  const loadRunId = activeRunId
  sessionId.value = sid
  messages.value = []
  chain.steps = []
  streamResult.value = null
  try {
    const history = await fetchHistory(agentId.value, sid)
    if (loadRunId !== activeRunId || sessionId.value !== sid) return
    for (const h of history) {
      messages.value.push({
        role: h.role,
        content: h.content,
        sql: h.sql_text,
        sql_result: h.sql_result,
      })
    }
    scrollToBottom()
  } catch { /* empty */ }
}

async function handleDeleteSession(sid: string) {
  if (loading.value) {
    ElMessage.warning('当前对话正在生成，请等待完成后再删除会话')
    return
  }
  try {
    await ElMessageBox.confirm('确定删除该会话？', '提示', { type: 'warning' })
    await deleteSession(agentId.value, sid)
    if (sessionId.value === sid) newSession()
    await loadSessions()
  } catch { /* cancelled */ }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

function getStep(node: string): ChainStep | undefined {
  return chain.steps.find(s => s.node === node)
}

function handleSend() {
  const q = inputText.value.trim()
  if (!q || loading.value) return
  const runId = activeRunId + 1
  activeRunId = runId

  // 添加用户消息
  messages.value.push({ role: 'user', content: q })
  inputText.value = ''
  setLoading(true)
  chain.steps = []
  streamResult.value = null
  scrollToBottom()

  abortController = sendMessageStream(
    {
      question: q,
      agent_id: agentId.value,
      datasource_id: datasourceId.value,
      session_id: sessionId.value || undefined,
    },
    (evt) => {
      if (runId !== activeRunId) return
      const d = evt.data

      if (evt.event === 'node_start') {
        chain.steps.push({
          node: d.node as string,
          label: d.label as string,
          status: 'running',
          reasoning: '',
          showReasoning: false,
          output: null,
          summary: '',
        })
        scrollToBottom()
      }

      else if (evt.event === 'reasoning') {
        const step = getStep(d.node as string)
        if (step) {
          step.reasoning += d.delta as string
          scrollToBottom()
        }
      }

      else if (evt.event === 'token') {
        const step = getStep(d.node as string)
        if (step) {
          // token 是 LLM 输出的内容 token
          scrollToBottom()
        }
      }

      else if (evt.event === 'node_complete') {
        const step = getStep(d.node as string)
        if (step) {
          step.status = 'done'
          step.output = (d.output || {}) as Record<string, any>
          // 生成摘要
          if (step.node === 'intent_recognition') {
            step.summary = `→ ${step.output?.intent || ''}`
          } else if (step.node === 'evidence_recall') {
            step.summary = `召回 ${step.output?.count || 0} 条知识`
          } else if (step.node === 'schema_recall') {
            const tables = (step.output?.tables as string[]) || []
            step.summary = tables.join(', ')
          } else if (step.node === 'sql_execute') {
            const err = step.output?.error as string
            step.summary = err ? `错误: ${err.slice(0, 40)}` : `${step.output?.row_count || 0} 条结果`
          }
          scrollToBottom()
        }
      }

      else if (evt.event === 'result') {
        streamResult.value = d as unknown as ChatResponse
        sessionId.value = (d.session_id as string) || sessionId.value
        scrollToBottom()
      }

      else if (evt.event === 'done') {
        if (runId !== activeRunId) return
        setLoading(false)
        abortController = null
        // 将流式结果也加入 messages 历史
        if (streamResult.value) {
          messages.value.push({
            role: 'assistant',
            content: (streamResult.value.answer as string) || '无回答',
            intent: streamResult.value.intent as string,
            sql: streamResult.value.sql as string,
            sql_result: streamResult.value.sql_result as Record<string, unknown>[],
          })
          streamResult.value = null
        }
        chain.steps = []
        loadSessions()
        scrollToBottom()
      }
    },
  )
}

onUnmounted(() => {
  setChatBusy(false)
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: calc(100vh - 80px);
  width: 100%;
  max-width: 100%;
  min-width: 0;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
}

/* 侧边栏 */
.session-sidebar {
  width: 240px;
  flex: 0 0 240px;
  min-width: 240px;
  background: #f5f7fa;
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
}
.sidebar-header {
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sidebar-header h4 { font-size: 14px; color: #303133; }
.session-list { flex: 1; overflow-y: auto; padding: 8px; }
.session-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
  position: relative;
}
.session-item:hover { background: #ecf5ff; }
.session-item.active { background: #d9ecff; border: 1px solid #409eff; }
.session-item.disabled { cursor: not-allowed; opacity: 0.65; }
.session-item.disabled:hover { background: transparent; }
.session-title {
  font-size: 13px; color: #303133;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-right: 20px;
}
.session-meta { font-size: 11px; color: #909399; margin-top: 4px; }
.session-delete { position: absolute; right: 8px; top: 12px; color: #c0c4cc; display: none; }
.session-item:hover .session-delete { display: block; }
.session-delete:hover { color: #f56c6c; }
.empty-sessions { text-align: center; color: #c0c4cc; padding: 40px 0; font-size: 13px; }

/* 对话区 */
.chat-container {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.chat-header {
  padding: 16px 20px; border-bottom: 1px solid #ebeef5;
  display: flex; align-items: center; justify-content: space-between;
  flex: 0 0 auto;
  min-width: 0;
}
.chat-header h3 { font-size: 16px; color: #303133; }
.chat-controls { display: flex; gap: 10px; min-width: 0; }
.chat-messages {
  flex: 1 1 auto;
  min-width: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 20px;
}
.empty-hint { text-align: center; color: #909399; margin-top: 120px; }
.empty-hint .examples { font-size: 13px; color: #c0c4cc; margin-top: 8px; }

.message { margin-bottom: 16px; display: flex; min-width: 0; }
.message.user { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }
.message.user .message-content {
  background: #409eff; color: #fff;
  border-radius: 12px 12px 0 12px;
}
.message.assistant .message-content {
  background: #f4f4f5;
  border-radius: 12px 12px 12px 0;
}
.message-content {
  max-width: min(860px, calc(100% - 80px));
  min-width: 0;
  padding: 12px 16px;
  overflow: hidden;
}
.message-content .meta { margin-bottom: 8px; display: flex; gap: 6px; }
.message-content .text {
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.sql-block {
  max-width: 100%;
  margin-top: 8px;
  background: #1e1e1e;
  border-radius: 6px;
  padding: 10px;
  overflow-x: auto;
}
.sql-block pre { margin: 0; min-width: 0; }
.sql-block code { color: #d4d4d4; font-size: 13px; font-family: 'Fira Code', monospace; }
.result-table { margin-top: 10px; }
.chat-input { flex: 0 0 auto; padding: 16px 20px; border-top: 1px solid #ebeef5; }

/* 链式思考面板 */
.chain-panel {
  max-width: 100%;
  min-width: 0;
  background: #fafbfc;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
  overflow: hidden;
}
.chain-header {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 600; color: #409eff; margin-bottom: 12px;
}
.chain-step { margin-bottom: 12px; min-width: 0; }
.step-header {
  display: flex; align-items: center; gap: 8px; font-size: 13px;
  min-width: 0;
}
.step-status { display: flex; align-items: center; }
.step-status.running { color: #409eff; }
.step-status.done { color: #67c23a; }
.step-status.pending { color: #c0c4cc; }
.step-label { font-weight: 500; color: #303133; min-width: 80px; }
.step-summary {
  color: #909399;
  font-size: 12px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 思考过程 */
.step-reasoning { margin: 6px 0 6px 28px; }
.reasoning-toggle {
  display: flex; align-items: center; gap: 4px;
  font-size: 12px; color: #909399; cursor: pointer; user-select: none;
}
.reasoning-toggle:hover { color: #409eff; }
.reasoning-content {
  margin-top: 4px; padding: 8px 12px; background: #f0f2f5;
  border-radius: 4px; font-size: 12px; color: #606266;
  line-height: 1.6; max-height: 200px; overflow-y: auto;
  white-space: pre-wrap;
}

/* 节点输出 */
.step-output {
  max-width: calc(100% - 28px);
  min-width: 0;
  margin: 4px 0 0 28px;
  font-size: 12px;
  color: #606266;
}
.output-sql {
  max-width: 100%;
  background: #1e1e1e;
  border-radius: 4px;
  padding: 8px;
  margin-top: 4px;
  overflow-x: auto;
}
.output-sql pre { margin: 0; min-width: 0; }
.output-sql code { color: #d4d4d4; font-size: 12px; font-family: 'Fira Code', monospace; }
.output-result .error { color: #f56c6c; }
</style>
