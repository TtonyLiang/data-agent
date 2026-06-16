<template>
  <div class="chat-layout">
    <div class="session-sidebar">
      <div class="sidebar-header">
        <el-button class="new-chat-button" type="primary" :disabled="loading" @click="newSession">
          <el-icon><Plus /></el-icon>
          <span>新对话</span>
        </el-button>
        <el-button :icon="Refresh" :disabled="loading" @click="loadSessions" />
      </div>
      <div class="session-search">
        <el-input v-model="sessionSearch" :prefix-icon="Search" placeholder="搜索历史会话" clearable />
      </div>
      <div class="session-list">
        <div class="session-group">今天</div>
        <div
          v-for="s in filteredSessions"
          :key="s.session_id"
          :class="['session-item', { active: s.session_id === sessionId, disabled: loading }]"
          @click="loadSession(s.session_id)"
        >
          <div class="session-title">{{ s.last_question || '新对话' }}</div>
          <div class="session-meta">
            <span>{{ formatTime(s.created_at) }}</span>
            <span>{{ s.turn_count }}轮</span>
          </div>
          <el-icon class="session-delete" @click.stop="handleDeleteSession(s.session_id)"><Delete /></el-icon>
        </div>
        <div v-if="filteredSessions.length === 0" class="empty-sessions">暂无历史会话</div>
      </div>
      <div class="session-footer">
        <span>历史记录按当前智能体自动保存</span>
      </div>
    </div>

    <div class="chat-container">
      <div class="workspace-toolbar">
        <div class="workspace-title">
          <h2>智能问数对话</h2>
          <p>{{ selectedDatasourceName }} · {{ selectedAgentName }}</p>
        </div>
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
              v-if="agents.length === 0"
              label="默认智能体"
              :value="agentId"
            />
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
        <div v-if="messages.length === 0" class="empty-hint">
          <div class="empty-icon">
            <el-icon :size="28"><ChatDotRound /></el-icon>
          </div>
          <h3>输入自然语言，开始查询数据</h3>
          <p>支持贷款风控指标、Vintage、逾期、核销和催收回收分析。</p>
          <div class="empty-examples">
            <el-button v-for="query in quickQueries.slice(0, 3)" :key="query" @click="useQuickQuery(query)">
              {{ query }}
            </el-button>
          </div>
        </div>

        <template v-for="(msg, idx) in messages" :key="idx">
          <div :class="['message', msg.role]">
            <div class="message-avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
            <div class="message-content">
              <div v-if="msg.role === 'assistant'" class="meta">
                <el-tag v-if="isAssistantStreaming(msg)" size="small">生成中</el-tag>
                <el-tag v-if="msg.intent" size="small" type="info">{{ msg.intent }}</el-tag>
                <el-tag v-if="msg.sql" size="small" type="success">SQL</el-tag>
              </div>

              <div v-if="msg.role === 'assistant' && msg.steps.length > 0" class="chain-panel">
                <div class="chain-header">
                  <el-icon v-if="isAssistantStreaming(msg)" class="is-loading"><Loading /></el-icon>
                  <el-icon v-else><CircleCheck /></el-icon>
                  <span>{{ isAssistantStreaming(msg) ? '分析中...' : '分析过程' }}</span>
                </div>

                <div v-for="step in msg.steps" :key="step.node" class="chain-step">
                  <div class="step-header">
                    <span :class="['step-status', step.status]">
                      <el-icon v-if="step.status === 'running'" class="is-loading"><Loading /></el-icon>
                      <el-icon v-else-if="step.status === 'done'"><CircleCheck /></el-icon>
                      <el-icon v-else><Clock /></el-icon>
                    </span>
                    <span class="step-label">{{ step.label }}</span>
                    <span v-if="step.summary" class="step-summary">{{ step.summary }}</span>
                  </div>

                  <div v-if="step.reasoning" class="step-reasoning">
                    <div class="reasoning-toggle" @click="toggleReasoning(msg.id, step.node)">
                      <el-icon><View v-if="!step.showReasoning" /><Hide v-else /></el-icon>
                      <span>思考过程 ({{ step.reasoning.length }}字)</span>
                    </div>
                    <div v-if="step.showReasoning" class="reasoning-content">
                      {{ step.reasoning }}
                    </div>
                  </div>

                  <div v-if="step.output" class="step-output">
                    <div v-if="step.node === 'nl2lf_generate' && getOutputObject(step.output, 'logic_form')" class="output-enhanced">
                      <pre><code>{{ formatJson(getOutputObject(step.output, 'logic_form')) }}</code></pre>
                    </div>
                    <div v-else-if="step.node === 'lf_to_sql_compile' && getOutputString(step.output, 'compiled_sql')" class="output-sql">
                      <pre><code>{{ getOutputString(step.output, 'compiled_sql') }}</code></pre>
                    </div>
                    <div v-else-if="step.node === 'sql_execute' && hasOutputKey(step.output, 'row_count')" class="output-result">
                      <span v-if="getOutputString(step.output, 'error')" class="error">错误: {{ getOutputString(step.output, 'error') }}</span>
                      <span v-else>返回 {{ getOutputValue(step.output, 'row_count') }} 条结果</span>
                    </div>
                    <div v-else-if="getOutputStrings(step.output, 'errors').length" class="output-result">
                      <span class="error">{{ getOutputStrings(step.output, 'errors').join('；') }}</span>
                    </div>
                    <div v-else-if="getOutputStrings(step.output, 'items').length" class="output-evidence">
                      语义资产: {{ getOutputStrings(step.output, 'items').join(', ') }}
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="msg.role === 'assistant' && msg.status === 'error'" class="run-error-card">
                <div class="run-error-header">
                  <el-icon><WarningFilled /></el-icon>
                  <div>
                    <span class="run-error-kicker">运行失败</span>
                    <h3>{{ msg.error?.label || '后端处理' }}</h3>
                  </div>
                  <el-tag v-if="msg.error?.type" type="danger" size="small" effect="plain">{{ msg.error.type }}</el-tag>
                </div>
                <div class="run-error-message">{{ msg.error?.message || msg.content }}</div>
                <div v-if="msg.error?.detail && msg.error.detail !== msg.error.message" class="run-error-detail">
                  {{ msg.error.detail }}
                </div>
                <div class="run-error-tip">完整堆栈已写入 logs/backend.log</div>
              </div>

              <div v-else-if="msg.role === 'assistant'" class="answer-card">
                <div class="answer-card-header">
                  <div>
                    <span class="answer-kicker">Final Answer</span>
                    <h3>分析结论</h3>
                  </div>
                  <div class="answer-badges">
                    <el-tag v-if="msg.intent" size="small" type="info">{{ msg.intent }}</el-tag>
                    <el-tag v-if="msg.sql" size="small" type="success">SQL 已生成</el-tag>
                    <el-tag v-if="msg.sql_result?.length" size="small" effect="plain">{{ msg.sql_result.length }} 行</el-tag>
                  </div>
                </div>
                <div class="answer-body">
                  <div class="answer-summary">
                    <div class="summary-mark">
                      <el-icon><CircleCheck /></el-icon>
                    </div>
                    <div class="answer-copy">
                      <p
                        v-for="(line, lineIndex) in answerSummaryLines(msg)"
                        :key="`${msg.id}-summary-${lineIndex}`"
                      >
                        {{ line }}
                      </p>
                    </div>
                  </div>
                  <div v-if="resultHighlights(msg).length" class="answer-kpi-grid">
                    <div
                      v-for="item in resultHighlights(msg)"
                      :key="item.key"
                      class="answer-kpi"
                    >
                      <span>{{ item.label }}</span>
                      <strong>{{ item.value }}</strong>
                      <code>{{ item.key }}</code>
                    </div>
                  </div>
                </div>
                <div v-if="msg.sql || msg.sql_result?.length" class="answer-assets">
                  <button v-if="msg.sql" class="asset-chip" type="button" @click="activeResultTab = 'sql'">
                    <span>SQL 详情</span>
                    <strong>{{ compactSql(msg.sql) }}</strong>
                  </button>
                  <button v-if="msg.sql_result?.length" class="asset-chip" type="button" @click="activeResultTab = 'result'">
                    <span>结果表</span>
                    <strong>{{ msg.sql_result.length }} 行数据，点击查看</strong>
                  </button>
                </div>
              </div>
              <div v-else class="text">{{ msg.content }}</div>
              <div v-if="msg.role === 'assistant' && msg.sql_result && msg.sql_result.length > 0" class="result-table compact-result">
                <div class="inline-result-header">
                  <span>结果预览</span>
                  <el-button size="small" text @click="activeResultTab = 'result'">查看完整结果</el-button>
                </div>
                <el-table :data="msg.sql_result.slice(0, 5)" border size="small" max-height="240">
                  <el-table-column
                    v-for="col in Object.keys(msg.sql_result[0])"
                    :key="col"
                    :prop="col"
                    min-width="120"
                  >
                    <template #header>
                      <div class="column-heading">
                        <span>{{ columnTitle(col) }}</span>
                        <small>{{ col }}</small>
                      </div>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </div>
          </div>
        </template>
      </div>

      <div class="chat-input">
        <div class="query-composer">
          <el-input
            v-model="inputText"
            type="textarea"
            placeholder="输入你的问题，支持自然语言查询数据..."
            :autosize="{ minRows: 2, maxRows: 4 }"
            :disabled="loading"
            @keydown.enter.exact.prevent="handleSend"
          />
          <div class="composer-footer">
            <div class="quick-query-list">
              <el-button v-for="query in quickQueries" :key="query" size="small" @click="useQuickQuery(query)">
                {{ query }}
              </el-button>
            </div>
            <el-button :icon="Promotion" @click="handleSend" :loading="loading" type="primary">
              发送
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <div class="insight-panel">
      <el-tabs v-model="activeResultTab" stretch>
        <el-tab-pane label="分析链路" name="chain">
          <div class="panel-actions">
            <el-button size="small" :icon="Refresh" :disabled="loading || !latestUserQuestion" @click="rerunLatestQuestion">重新运行</el-button>
            <span class="run-state" :class="{ running: loading }">
              {{ loading ? '生成中' : latestAssistant ? '已完成' : '待查询' }}
            </span>
          </div>
          <div v-if="latestSteps.length" class="panel-timeline">
            <div v-for="step in latestSteps" :key="step.node" class="panel-step">
              <span :class="['timeline-dot', step.status]" />
              <div>
                <strong>{{ step.label }}</strong>
                <p>{{ step.summary || statusText(step.status) }}</p>
              </div>
            </div>
          </div>
          <div v-else class="panel-empty">发起查询后，这里会展示理解问题、召回语义运行时、生成 LogicForm、编译 SQL 和执行查询的过程。</div>
        </el-tab-pane>

        <el-tab-pane label="SQL" name="sql">
          <div class="panel-actions">
            <el-button size="small" :icon="DocumentCopy" :disabled="!latestSql" @click="copyLatestSql">复制 SQL</el-button>
            <span class="result-count">生成的 SQL</span>
          </div>
          <div v-if="latestSql" class="panel-sql">
            <pre><code>{{ latestSql }}</code></pre>
          </div>
          <div v-else class="panel-empty">暂无 SQL，完成一次问数后会自动展示。</div>
        </el-tab-pane>

        <el-tab-pane label="结果" name="result">
          <div class="panel-actions">
            <el-button size="small" :icon="Download" :disabled="latestRows.length === 0" @click="downloadResults">导出</el-button>
            <span class="result-count">查询结果（{{ latestRows.length }} 行）</span>
          </div>
          <el-table v-if="latestRows.length" :data="latestRows" border size="small" height="360">
            <el-table-column
              v-for="col in Object.keys(latestRows[0])"
              :key="col"
              :prop="col"
              min-width="120"
            >
              <template #header>
                <div class="column-heading">
                  <span>{{ columnTitle(col) }}</span>
                  <small>{{ col }}</small>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="panel-empty">暂无结果数据。</div>
        </el-tab-pane>
      </el-tabs>
      </div>
    </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, nextTick, onUnmounted, watch } from 'vue'
import { Promotion, Loading, ChatDotRound, Plus, Delete, CircleCheck, Clock, View, Hide, Search, Refresh, Download, DocumentCopy, WarningFilled } from '@element-plus/icons-vue'
import {
  sendMessageStream, fetchAgents, fetchDatasources, fetchSessions, fetchHistory, deleteSession,
  fetchSemanticAssets, fetchSemanticDomains,
  type AgentItem, type DatasourceItem, type SessionItem, type HistoryItem,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { setChatBusy } from '../stores/chatRun'
import {
  createChatStreamState,
  reduceChatStreamEvent,
  startChatRun,
  toggleAssistantReasoning,
  type ChatMessage,
  type ChatStreamState,
} from '../stores/chatStream'

const streamState = ref<ChatStreamState>(createChatStreamState())
const messages = computed(() => streamState.value.messages)
const inputText = ref('')
const sessionSearch = ref('')
const activeResultTab = ref('chain')
const loading = ref(false)
const agentId = ref<number>(Number(localStorage.getItem('wenqu_agent_id')) || 1)
const agents = ref<AgentItem[]>([])
const datasourceId = ref<number | null>(null)
const datasources = ref<DatasourceItem[]>([])
const sessions = ref<SessionItem[]>([])
const sessionId = ref<string>('')
const messagesRef = ref<HTMLElement>()
const semanticLabels = ref<Record<string, string>>({})
let abortController: AbortController | null = null
let activeRunId = 0

const quickQueries = [
  '本月现金贷 M1+逾期率怎么算',
  '按 Vintage 看放款后 MOB3 的风险表现',
  '各催收团队的催收回收率排名',
  '高 PD 客户的余额和逾期情况',
]

const filteredSessions = computed(() => {
  const keyword = sessionSearch.value.trim().toLowerCase()
  if (!keyword) return sessions.value
  return sessions.value.filter((session) => (session.last_question || '新对话').toLowerCase().includes(keyword))
})

const selectedAgentName = computed(() => {
  return agents.value.find(agent => agent.id === agentId.value)?.name || '未选择智能体'
})

const selectedDatasourceName = computed(() => {
  const datasource = datasources.value.find(item => item.id === datasourceId.value)
  return datasource ? `${datasource.name} (${datasource.database_name})` : '未选择数据源'
})

const latestAssistant = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const message = messages.value[i]
    if (message.role === 'assistant') return message
  }
  return null
})

const latestUserQuestion = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const message = messages.value[i]
    if (message.role === 'user') return message.content
  }
  return ''
})

const latestSteps = computed(() => latestAssistant.value?.steps || [])

const latestSql = computed(() => {
  if (latestAssistant.value?.sql) return latestAssistant.value.sql
  for (const step of latestSteps.value) {
    if (step.node === 'lf_to_sql_compile' && step.output) {
      const sql = getOutputString(step.output, 'compiled_sql')
      if (sql) return sql
    }
  }
  return ''
})

const latestRows = computed(() => latestAssistant.value?.sql_result || [])

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
    ElMessage.error('智能体配置加载失败，请确认后端服务已启动')
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
  } catch {
    ElMessage.error('数据源加载失败，请确认后端服务已启动')
    datasources.value = []
    datasourceId.value = null
  }
  await loadSemanticLabels()
  await loadSessions()
}

async function loadSemanticLabels() {
  try {
    const domains = await fetchSemanticDomains(agentId.value)
    const domain = domains[0]
    if (!domain?.id) {
      semanticLabels.value = defaultSemanticLabels()
      return
    }
    const assets = await fetchSemanticAssets(domain.id)
    semanticLabels.value = buildSemanticLabels(assets)
  } catch {
    semanticLabels.value = defaultSemanticLabels()
  }
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
  streamState.value = createChatStreamState()
}

function newSession() {
  cancelActiveStream()
  resetConversation()
}

function useQuickQuery(query: string) {
  inputText.value = query
}

async function copyLatestSql() {
  if (!latestSql.value) return
  try {
    await navigator.clipboard.writeText(latestSql.value)
    ElMessage.success('SQL 已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择 SQL')
  }
}

function downloadResults() {
  if (latestRows.value.length === 0) return
  const columns = Object.keys(latestRows.value[0])
  const escapeCsv = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`
  const csv = [
    columns.map(escapeCsv).join(','),
    ...latestRows.value.map(row => columns.map(column => escapeCsv(row[column])).join(',')),
  ].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'wenqu-query-result.csv'
  link.click()
  URL.revokeObjectURL(url)
}

function rerunLatestQuestion() {
  if (!latestUserQuestion.value || loading.value) return
  inputText.value = latestUserQuestion.value
  handleSend()
}

function statusText(status: string) {
  if (status === 'done') return '已完成'
  if (status === 'running') return '处理中'
  return '等待执行'
}

async function loadSession(sid: string) {
  if (loading.value) {
    ElMessage.warning('当前对话正在生成，请等待完成后再切换会话')
    return
  }
  cancelActiveStream()
  const loadRunId = activeRunId
  sessionId.value = sid
  streamState.value = createChatStreamState()
  try {
    const history = await fetchHistory(agentId.value, sid)
    if (loadRunId !== activeRunId || sessionId.value !== sid) return
    streamState.value = {
      ...streamState.value,
      messages: history.map((item, index) => historyToMessage(item, sid, index)),
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

function historyToMessage(item: HistoryItem, sid: string, index: number): ChatMessage {
  if (item.role === 'assistant') {
    return {
      id: `history-${sid}-${index}`,
      role: 'assistant',
      content: item.content,
      status: 'complete',
      sql: item.compiled_sql || item.sql_text,
      logic_form: item.logic_form,
      sql_result: item.sql_result,
      steps: (item.reasoning_trace || []).map(step => ({
        node: step.node,
        label: step.label,
        status: step.status === 'running' || step.status === 'pending' ? step.status : 'done',
        reasoning: step.reasoning || '',
        showReasoning: false,
        output: step.output || null,
        summary: step.summary || '',
      })),
    }
  }
  return {
    id: `history-${sid}-${index}`,
    role: 'user',
    content: item.content,
    steps: [],
  }
}

function toggleReasoning(messageId: string, node: string) {
  streamState.value = toggleAssistantReasoning(streamState.value, messageId, node)
}

function isAssistantStreaming(message: ChatMessage) {
  return message.role === 'assistant' && !!message.status && message.status !== 'complete'
}

function getOutputValue(output: Record<string, unknown>, key: string) {
  return output[key]
}

function getOutputString(output: Record<string, unknown>, key: string) {
  const value = output[key]
  return typeof value === 'string' ? value : ''
}

function getOutputObject(output: Record<string, unknown>, key: string) {
  const value = output[key]
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function formatJson(value: Record<string, unknown> | null) {
  return value ? JSON.stringify(value, null, 2) : ''
}

function getOutputStrings(output: Record<string, unknown>, key: string) {
  const value = output[key]
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function hasOutputKey(output: Record<string, unknown>, key: string) {
  return Object.prototype.hasOwnProperty.call(output, key)
}

function compactSql(sql: string) {
  return sql.replace(/\s+/g, ' ').trim().slice(0, 80)
}

function answerSummaryLines(message: ChatMessage) {
  const clean = cleanAnswerContent(message.content || '')
  if (clean) {
    return clean
      .split(/\n+/)
      .map(line => line.trim())
      .filter(Boolean)
      .slice(0, 3)
  }
  if (isAssistantStreaming(message)) return ['正在整理结论...']
  return [buildResultNarrative(message)]
}

function cleanAnswerContent(content: string) {
  const text = content.trim()
  if (!text) return ''
  if (/^SQL\s*[:：]/i.test(text)) return ''
  const lines = text.split(/\r?\n/)
  return lines
    .filter((line) => {
      const trimmed = line.trim()
      if (!trimmed) return true
      if (/^SQL\s*[:：]/i.test(trimmed)) return false
      if (/^共\s*\d+\s*条结果\s*[:：]?/.test(trimmed)) return false
      if (/^\|.*\|$/.test(trimmed)) return false
      if (/^\.\.\.\s*共\s*\d+\s*条/.test(trimmed)) return false
      return true
    })
    .join('\n')
    .trim()
}

function buildResultNarrative(message: ChatMessage) {
  const rows = message.sql_result || []
  if (rows.length === 0) return '查询完成，未返回匹配数据。'
  const highlights = resultHighlights(message)
  if (rows.length === 1 && highlights.length >= 2) {
    const dimension = highlights.find(item => !item.numeric)
    const metric = highlights.find(item => item.numeric)
    if (dimension && metric) return `${dimension.value}的 ${metric.label}为 ${metric.value}。`
  }
  return `查询完成，共 ${rows.length} 条结果。关键字段已整理在下方，完整明细可以在右侧“结果”中查看。`
}

function resultHighlights(message: ChatMessage) {
  const row = message.sql_result?.[0]
  if (!row) return []
  return Object.keys(row).slice(0, 4).map((key) => {
    const value = row[key]
    return {
      key,
      label: columnTitle(key),
      value: formatDisplayValue(key, value),
      numeric: isNumericValue(value),
    }
  })
}

function formatDisplayValue(key: string, value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (isNumericValue(value)) {
    const numeric = Number(value)
    if (shouldFormatPercent(key, numeric)) return `${(numeric * 100).toFixed(2)}%`
    return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(numeric)
  }
  return String(value)
}

function isNumericValue(value: unknown) {
  if (typeof value === 'number') return Number.isFinite(value)
  if (typeof value !== 'string' || value.trim() === '') return false
  return Number.isFinite(Number(value))
}

function shouldFormatPercent(key: string, value: number) {
  if (Math.abs(value) > 1) return false
  return /rate|ratio|percent|pct|probability|pd|dti/i.test(key)
}

function columnTitle(key: string) {
  return semanticLabels.value[key] || defaultSemanticLabels()[key] || key
}

function buildSemanticLabels(assets: Record<string, Record<string, unknown>[]>) {
  const labels = defaultSemanticLabels()
  for (const metric of assets.metric || []) {
    const key = String(metric.metric_key || '')
    const name = String(metric.name || '')
    if (key && name) labels[key] = name
  }
  for (const mapping of assets.mapping || []) {
    const key = String(mapping.asset_key || '')
    if (key && !labels[key]) labels[key] = humanizeField(key)
  }
  return labels
}

function defaultSemanticLabels() {
  return {
    approval_rate: '审批通过率',
    disbursement_amount: '放款金额',
    outstanding_balance: '贷款余额',
    m1_plus_rate: 'M1+逾期率',
    mob: '账龄',
    dpd: '逾期天数',
    vintage: '放款批次',
    pd: '预测违约概率',
    dti: '负债收入比',
    writeoff_amount: '核销金额',
    collection_recovery_rate: '催收回收率',
    product_type: '产品类型',
    region: '地区',
    channel: '渠道',
    risk_grade: '风险等级',
    overdue_bucket: '逾期阶段',
    assigned_team: '催收团队',
    collection_strategy: '催收策略',
    overdue_bucket_at_entry: '入催逾期阶段',
    customer_segment: '客户分层',
  } as Record<string, string>
}

function humanizeField(key: string) {
  return key
    .split('_')
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function handleSend() {
  const q = inputText.value.trim()
  if (!q || loading.value) return
  const runId = activeRunId + 1
  activeRunId = runId

  streamState.value = startChatRun(streamState.value, { runId, question: q })
  inputText.value = ''
  setLoading(true)
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
      streamState.value = reduceChatStreamEvent(streamState.value, {
        runId,
        event: evt.event,
        data: evt.data,
      })
      const nextSessionId = evt.data.session_id
      if (typeof nextSessionId === 'string' && nextSessionId) sessionId.value = nextSessionId

      if (evt.event === 'done' || evt.event === 'error') {
        setLoading(false)
        abortController = null
        loadSessions()
      }
      scrollToBottom()
    },
  )
}

onUnmounted(() => {
  cancelActiveStream()
})
</script>

<style scoped>
.chat-layout {
  display: grid;
  grid-template-columns: 280px minmax(460px, 1fr) 430px;
  height: calc(100vh - 68px);
  width: 100%;
  max-width: 100%;
  min-width: 0;
  min-height: 0;
  background: var(--wq-surface);
  overflow: hidden;
}

.session-sidebar {
  min-width: 0;
  min-height: 0;
  background: #fbfcff;
  border-right: 1px solid var(--wq-border);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 20px 18px 10px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.new-chat-button {
  flex: 1;
  justify-content: center;
  height: 36px;
}

.session-search {
  padding: 0 18px 16px;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 18px 14px;
}

.session-group {
  margin: 2px 0 8px;
  color: var(--wq-subtle);
  font-size: 12px;
  font-weight: 680;
}

.session-item {
  padding: 12px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 6px;
  position: relative;
  background: transparent;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.session-item:hover {
  background: #f2f5fb;
}

.session-item.active {
  background: var(--wq-primary-soft);
  border-color: #c8d6ff;
  box-shadow: inset 3px 0 0 var(--wq-primary);
}

.session-item.disabled { cursor: not-allowed; opacity: 0.65; }
.session-item.disabled:hover { background: transparent; }

.session-title {
  font-size: 14px;
  line-height: 1.35;
  color: #344054;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 24px;
}

.session-item.active .session-title {
  color: var(--wq-primary);
  font-weight: 650;
}

.session-meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: var(--wq-subtle);
  margin-top: 8px;
}

.session-delete {
  position: absolute;
  right: 10px;
  top: 13px;
  color: var(--wq-subtle);
  display: none;
}

.session-item:hover .session-delete { display: block; }
.session-delete:hover { color: var(--wq-danger); }

.empty-sessions {
  text-align: center;
  color: var(--wq-subtle);
  padding: 48px 0;
  font-size: 13px;
}

.session-footer {
  padding: 12px 18px 18px;
  border-top: 1px solid var(--wq-border);
}

.session-footer span {
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1.5;
}

.chat-container {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--wq-surface);
}

.workspace-toolbar {
  min-height: 70px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--wq-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex: 0 0 auto;
  min-width: 0;
}

.workspace-title {
  min-width: 0;
}

.workspace-title h2 {
  font-size: 17px;
  line-height: 1.25;
  color: var(--wq-text);
  font-weight: 760;
  letter-spacing: 0;
}

.workspace-title p {
  margin-top: 5px;
  color: var(--wq-subtle);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-controls {
  display: flex;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.chat-messages {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 26px 20px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfcff 100%);
}

.empty-hint {
  width: min(620px, 100%);
  margin: 12vh auto 0;
  text-align: center;
  color: var(--wq-muted);
}

.empty-icon {
  width: 58px;
  height: 58px;
  margin: 0 auto 18px;
  display: grid;
  place-items: center;
  border-radius: 18px;
  color: var(--wq-primary);
  background: var(--wq-primary-soft);
  border: 1px solid #d9e3ff;
}

.empty-hint h3 {
  color: var(--wq-text);
  font-size: 18px;
  line-height: 1.35;
  font-weight: 720;
}

.empty-hint p {
  margin-top: 8px;
  line-height: 1.55;
  font-size: 14px;
}

.empty-examples {
  margin-top: 18px;
  display: flex;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
}

.message {
  margin-bottom: 24px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
}

.message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  color: #fff;
  font-size: 13px;
  font-weight: 760;
  background: #5b7cf6;
}

.message.assistant .message-avatar {
  color: var(--wq-primary);
  background: var(--wq-primary-soft);
  border: 1px solid #d9e3ff;
}

.message.user .message-content {
  background: #f3f6ff;
  color: #24324b;
  border: 1px solid #dce6ff;
  border-radius: 10px;
  max-width: min(560px, calc(100% - 56px));
}

.message.assistant .message-content {
  background: transparent;
  border-radius: 0;
}

.message-content {
  max-width: min(760px, calc(100% - 56px));
  min-width: 0;
  padding: 10px 0;
  overflow: hidden;
}

.message.user .message-content {
  padding: 10px 14px;
}

.message-content .meta {
  margin-bottom: 10px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.message-content .text {
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: #344054;
  font-size: 14px;
}

.answer-card {
  max-width: 100%;
  background: #fff;
  border: 1px solid #dce6f5;
  border-radius: 8px;
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
  overflow: hidden;
}

.run-error-card {
  max-width: 100%;
  background: #fff7f7;
  border: 1px solid #fecaca;
  border-radius: 8px;
  box-shadow: 0 12px 28px rgba(185, 28, 28, 0.08);
  overflow: hidden;
}

.run-error-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px 18px 12px;
  border-bottom: 1px solid #fecaca;
  background: #fff1f2;
  color: #b42318;
}

.run-error-header .el-icon {
  margin-top: 2px;
  font-size: 20px;
}

.run-error-header h3 {
  margin: 0;
  color: #7a271a;
  font-size: 16px;
  line-height: 1.35;
  font-weight: 760;
}

.run-error-header .el-tag {
  margin-left: auto;
  flex: 0 0 auto;
}

.run-error-kicker {
  display: block;
  margin-bottom: 3px;
  color: #d92d20;
  font-size: 11px;
  font-weight: 760;
}

.run-error-message {
  padding: 16px 18px 8px;
  color: #7a271a;
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.run-error-detail {
  margin: 0 18px 12px;
  padding: 10px 12px;
  border: 1px solid #fed7aa;
  border-radius: 6px;
  background: #fffaf5;
  color: #9a3412;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.run-error-tip {
  padding: 0 18px 16px;
  color: #b54708;
  font-size: 12px;
}

.answer-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 16px 18px 12px;
  border-bottom: 1px solid var(--wq-border);
  background: #f8fbff;
}

.answer-kicker {
  display: block;
  margin-bottom: 4px;
  color: var(--wq-primary);
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 0;
}

.answer-card h3 {
  margin: 0;
  color: var(--wq-text);
  font-size: 17px;
  line-height: 1.3;
  font-weight: 760;
}

.answer-badges {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.answer-body {
  padding: 18px;
  color: #263448;
  font-size: 15px;
}

.answer-summary {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 12px;
  align-items: flex-start;
}

.summary-mark {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: #079455;
  background: #ecfdf3;
  border: 1px solid #abefc6;
}

.answer-copy {
  min-width: 0;
}

.answer-copy p {
  margin: 0;
  color: #263448;
  font-size: 14px;
  line-height: 1.75;
  overflow-wrap: anywhere;
}

.answer-copy p + p {
  margin-top: 8px;
}

.answer-kpi-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}

.answer-kpi {
  min-width: 0;
  padding: 12px;
  border: 1px solid #dbe4f0;
  border-radius: 8px;
  background: #fbfcff;
}

.answer-kpi span,
.answer-kpi code {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.answer-kpi span {
  color: #667085;
  font-size: 12px;
  line-height: 1.35;
}

.answer-kpi strong {
  display: block;
  margin-top: 6px;
  color: #1d2939;
  font-size: 20px;
  line-height: 1.25;
  font-weight: 780;
  overflow-wrap: anywhere;
}

.answer-kpi code {
  margin-top: 5px;
  color: #98a2b3;
  font-size: 11px;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.answer-assets {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 0 18px 18px;
}

.asset-chip {
  min-width: 0;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fbfcff;
  padding: 10px 12px;
  text-align: left;
  cursor: pointer;
}

.asset-chip:hover {
  border-color: #b9c8ff;
  background: var(--wq-primary-soft);
}

.asset-chip span {
  display: block;
  margin-bottom: 5px;
  color: var(--wq-subtle);
  font-size: 12px;
}

.asset-chip strong {
  display: block;
  color: #344054;
  font-size: 13px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message.user .message-content .text {
  color: #24324b;
  line-height: 1.55;
}

.sql-block {
  max-width: 100%;
  margin-top: 12px;
  background: #101828;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
}

.sql-block pre { margin: 0; min-width: 0; }
.sql-block code { color: #e6edf7; font-size: 13px; font-family: "SFMono-Regular", Consolas, monospace; }
.result-table { margin-top: 12px; }

.compact-result {
  padding: 12px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fff;
}

.inline-result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  color: #344054;
  font-size: 13px;
  font-weight: 680;
}

.column-heading {
  display: flex;
  flex-direction: column;
  gap: 1px;
  line-height: 1.35;
}

.column-heading span {
  color: #1d2939;
  font-size: 13px;
  font-weight: 660;
}

.column-heading small {
  color: #98a2b3;
  font-size: 11px;
  font-weight: 400;
  letter-spacing: 0;
}

.chat-input {
  flex: 0 0 auto;
  padding: 16px 20px 18px;
  border-top: 1px solid var(--wq-border);
  background: #fff;
}

.query-composer {
  border: 1px solid #b9c8ff;
  border-radius: 8px;
  padding: 10px;
  background: #fff;
  box-shadow: 0 10px 30px rgba(63, 111, 243, 0.08);
}

.query-composer :deep(.el-textarea__inner) {
  box-shadow: none;
  border-radius: 0;
  min-height: 48px !important;
  padding: 4px 6px;
  resize: none;
}

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 8px;
}

.quick-query-list {
  min-width: 0;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  overflow: hidden;
  padding-bottom: 1px;
}

.quick-query-list .el-button {
  flex: 0 0 auto;
}

.chain-panel {
  max-width: 100%;
  min-width: 0;
  background: #fbfcff;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 16px;
  overflow: hidden;
}

.chain-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 680;
  color: var(--wq-text);
  margin-bottom: 12px;
}

.chain-step { margin-bottom: 12px; min-width: 0; }

.step-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  min-width: 0;
}

.step-status { display: flex; align-items: center; }
.step-status.running { color: var(--wq-primary); }
.step-status.done { color: var(--wq-success); }
.step-status.pending { color: var(--wq-subtle); }
.step-label { font-weight: 650; color: #344054; min-width: 80px; }

.step-summary {
  color: var(--wq-subtle);
  font-size: 12px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-reasoning { margin: 6px 0 6px 28px; }

.reasoning-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--wq-subtle);
  cursor: pointer;
  user-select: none;
}

.reasoning-toggle:hover { color: var(--wq-primary); }

.reasoning-content {
  margin-top: 6px;
  padding: 10px 12px;
  background: #f3f6fb;
  border-radius: 6px;
  font-size: 12px;
  color: var(--wq-muted);
  line-height: 1.65;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.step-output {
  max-width: calc(100% - 28px);
  min-width: 0;
  margin: 4px 0 0 28px;
  font-size: 12px;
  color: var(--wq-muted);
}

.output-sql {
  max-width: 100%;
  background: #101828;
  border-radius: 6px;
  padding: 8px;
  margin-top: 6px;
  overflow-x: auto;
}

.output-sql pre { margin: 0; min-width: 0; }
.output-sql code { color: #e6edf7; font-size: 12px; font-family: "SFMono-Regular", Consolas, monospace; }
.output-result .error { color: var(--wq-danger); }

.insight-panel {
  min-width: 0;
  border-left: 1px solid var(--wq-border);
  background: #fbfcff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.insight-panel :deep(.el-tabs) {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.insight-panel :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 22px;
  background: #fff;
}

.insight-panel :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 20px;
}

.panel-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 16px;
}

.run-state,
.result-count {
  color: var(--wq-muted);
  font-size: 13px;
  white-space: nowrap;
}

.run-state::before {
  content: "";
  width: 7px;
  height: 7px;
  display: inline-block;
  margin-right: 7px;
  border-radius: 50%;
  background: var(--wq-success);
  vertical-align: 1px;
}

.run-state.running::before {
  background: var(--wq-primary);
}

.panel-timeline {
  border-left: 1px solid var(--wq-border-strong);
  margin-left: 8px;
  padding-left: 18px;
}

.panel-step {
  position: relative;
  display: flex;
  gap: 10px;
  padding-bottom: 22px;
}

.timeline-dot {
  position: absolute;
  left: -25px;
  top: 3px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid var(--wq-subtle);
}

.timeline-dot.done { border-color: var(--wq-success); background: #eaf8f1; }
.timeline-dot.running { border-color: var(--wq-primary); background: var(--wq-primary-soft); }

.panel-step strong {
  display: block;
  color: #344054;
  font-size: 14px;
  line-height: 1.35;
}

.panel-step p {
  margin-top: 5px;
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.panel-empty {
  min-height: 180px;
  display: grid;
  place-items: center;
  padding: 24px;
  color: var(--wq-subtle);
  line-height: 1.6;
  text-align: center;
  border: 1px dashed var(--wq-border-strong);
  border-radius: 8px;
  background: #fff;
}

.panel-sql {
  background: #101828;
  border-radius: 8px;
  padding: 14px;
  overflow-x: auto;
}

.panel-sql pre {
  margin: 0;
}

.panel-sql code {
  color: #e6edf7;
  font-size: 13px;
  line-height: 1.75;
  font-family: "SFMono-Regular", Consolas, monospace;
}

@media (max-width: 1260px) {
  .chat-layout {
    grid-template-columns: 260px minmax(440px, 1fr);
  }

  .insight-panel {
    display: none;
  }
}

@media (max-width: 860px) {
  .chat-layout {
    grid-template-columns: 1fr;
    height: calc(100vh - 114px);
  }

  .session-sidebar {
    display: none;
  }

  .workspace-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .chat-controls {
    width: 100%;
    justify-content: flex-start;
  }

  .chat-controls .el-select {
    width: 100% !important;
  }

  .composer-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .composer-footer > .el-button {
    width: 100%;
  }
}
</style>
