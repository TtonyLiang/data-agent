import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

export interface ChatRequest {
  question: string
  agent_id?: number
  datasource_id?: number | null
  session_id?: string
}

export interface ChatResponse {
  session_id: string
  intent: string
  sql: string
  answer: string
  sql_result: Record<string, unknown>[]
}

export interface DatasourceItem {
  id: number
  agent_id: number
  name: string
  db_type: string
  host: string
  port: number
  database_name: string
  status: string
}

export interface AgentItem {
  id: number
  name: string
  description: string
  llm_provider: string
  llm_model: string
  created_at: string
}

export interface AgentCreateRequest {
  name: string
  description: string
  llm_provider: string
  llm_model: string
}

export async function fetchAgents(): Promise<AgentItem[]> {
  const { data } = await api.get<{ agents: AgentItem[] }>('/agent/list')
  return data.agents || []
}

export async function createAgent(agent: AgentCreateRequest) {
  const { data } = await api.post('/agent/create', agent)
  return data
}

export async function sendMessage(req: ChatRequest): Promise<ChatResponse> {
  const { data } = await api.post<ChatResponse>('/chat', req)
  return data
}

export interface StreamEvent {
  event: 'node_start' | 'reasoning' | 'token' | 'node_complete' | 'result' | 'done'
  data: Record<string, unknown>
}

export function sendMessageStream(
  req: ChatRequest,
  onEvent: (evt: StreamEvent) => void,
): AbortController {
  const controller = new AbortController()
  fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal: controller.signal,
  }).then(async (resp) => {
    let receivedDone = false
    let currentEvent = 'message'
    let dataLines: string[] = []
    const dispatchEvent = () => {
      if (dataLines.length === 0) return
      const raw = dataLines.join('\n')
      const eventName = currentEvent as StreamEvent['event']
      currentEvent = 'message'
      dataLines = []
      try {
        const data = JSON.parse(raw)
        if (eventName === 'done') receivedDone = true
        onEvent({ event: eventName, data })
      } catch { /* skip malformed */ }
    }

    if (!resp.body) {
      onEvent({ event: 'done', data: {} })
      return
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (line === '') {
          dispatchEvent()
          continue
        }
        if (line.startsWith(':')) continue
        const separator = line.indexOf(':')
        const field = separator >= 0 ? line.slice(0, separator) : line
        const value = separator >= 0 ? line.slice(separator + 1).trimStart() : ''
        if (field === 'event') {
          currentEvent = value
        } else if (field === 'data') {
          dataLines.push(value)
        }
      }
    }
    if (buffer) {
      const separator = buffer.indexOf(':')
      const field = separator >= 0 ? buffer.slice(0, separator) : buffer
      const value = separator >= 0 ? buffer.slice(separator + 1).trimStart() : ''
      if (field === 'event') currentEvent = value
      else if (field === 'data') dataLines.push(value)
    }
    dispatchEvent()
    if (!receivedDone) onEvent({ event: 'done', data: {} })
  }).catch(() => {
    onEvent({ event: 'done', data: {} })
  })
  return controller
}

export async function fetchDatasources(agentId: number) {
  const { data } = await api.get<{ datasources: DatasourceItem[] }>(`/datasource/list/${agentId}`)
  return data.datasources
}

export async function createDatasource(ds: Record<string, unknown>) {
  const { data } = await api.post('/datasource/create', ds)
  return data
}

export async function testConnection(dsId: number) {
  const { data } = await api.post(`/datasource/${dsId}/test`)
  return data
}

export async function collectSchema(dsId: number) {
  const { data } = await api.post(`/datasource/${dsId}/collect-schema`)
  return data
}

export async function fetchSemanticModels(agentId: number) {
  const { data } = await api.get(`/knowledge/semantic-model/${agentId}`)
  return data.models
}

export async function createSemanticModel(sm: Record<string, unknown>) {
  const { data } = await api.post('/knowledge/semantic-model', sm)
  return data
}

export async function fetchBusinessKnowledge(agentId: number) {
  const { data } = await api.get(`/knowledge/business-knowledge/${agentId}`)
  return data.knowledge
}

export async function createBusinessKnowledge(bk: Record<string, unknown>) {
  const { data } = await api.post('/knowledge/business-knowledge', bk)
  return data
}

// 会话历史
export interface SessionItem {
  session_id: string
  created_at: string
  turn_count: number
  last_question: string
}

export interface HistoryItem {
  role: 'user' | 'assistant'
  content: string
  sql_text?: string
  sql_result?: Record<string, unknown>[]
  created_at: string
}

export async function fetchSessions(agentId: number): Promise<SessionItem[]> {
  const { data } = await api.get<{ sessions: SessionItem[] }>(`/chat/sessions/${agentId}`)
  return data.sessions || []
}

export async function fetchHistory(agentId: number, sessionId: string): Promise<HistoryItem[]> {
  const { data } = await api.get<{ history: HistoryItem[] }>(`/chat/history/${agentId}/${sessionId}`)
  return data.history || []
}

export async function deleteSession(agentId: number, sessionId: string) {
  const { data } = await api.delete(`/chat/sessions/${agentId}/${sessionId}`)
  return data
}
