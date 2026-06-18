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
  trace_id?: string
  require_sql_confirmation?: boolean
  enable_low_confidence_clarification?: boolean
}

export interface ChatResponse {
  session_id: string
  intent: string
  sql: string
  compiled_sql?: string
  logic_form?: Record<string, unknown>
  answer: string
  sql_result: Record<string, unknown>[]
  plan?: Record<string, unknown>
  semantic_check?: Record<string, unknown>
  python_result?: Record<string, unknown>
  report_payload?: Record<string, unknown>
  trace_id?: string
  execution_trace?: Record<string, unknown>
  human_confirmation?: Record<string, unknown>
  clarification?: Record<string, unknown>
}

export interface DatasourceItem {
  id: number
  agent_id?: number | null
  name: string
  db_type: string
  host: string
  port: number
  username: string
  database_name: string
  status: string
}

export interface DatasourceColumnMeta {
  id: number
  table_id: number
  column_name: string
  data_type: string
  column_comment?: string | null
  is_primary_key: boolean | number
  is_foreign_key: boolean | number
  foreign_key_ref?: string | null
}

export interface DatasourceTableMeta {
  id: number
  datasource_id: number
  table_name: string
  table_comment?: string | null
  columns: DatasourceColumnMeta[]
}

export interface DatasourceTableSummary {
  id: number
  datasource_id: number
  table_name: string
  table_comment?: string | null
  column_count: number
}

export interface DatasourceRemoteTable {
  table_name: string
  table_comment?: string | null
  collected: boolean
  table_id?: number | null
  column_count: number
}

export interface DatasourceSchemaStats {
  table_count: number
  column_count: number
  noise_level: 'normal' | 'high'
  recommendation: string
}

export interface AgentItem {
  id: number
  name: string
  description: string
  chat_model_config_id?: number | null
  embedding_model_config_id?: number | null
  semantic_domain_id?: number | null
  chat_model_config_name?: string | null
  embedding_model_config_name?: string | null
  semantic_domain_name?: string | null
  semantic_domain_key?: string | null
  llm_provider: string
  llm_model: string
  created_at: string
}

export interface AgentCreateRequest {
  name: string
  description: string
  chat_model_config_id?: number | null
  embedding_model_config_id?: number | null
  semantic_domain_id?: number | null
  datasource_ids?: number[]
  llm_provider?: string
  llm_model?: string
}

export interface ModelConfigItem {
  id: number
  name: string
  model_type: 'chat' | 'embedding'
  provider: string
  base_url: string
  model_name: string
  api_key_enabled: boolean | number
  api_key_configured?: boolean | number
  api_key_expires_at?: string | null
  api_key_expired?: boolean | number
  api_key_expires_soon?: boolean | number
  embedding_dimension?: number | null
  status: string
  created_at?: string
}

export type ModelConfigRequest = Omit<ModelConfigItem, 'id' | 'created_at'> & {
  api_key?: string | null
}

export interface PromptTemplateItem {
  id: number
  prompt_key: string
  name: string
  description?: string | null
  agent_id?: number | null
  model_config_id?: number | null
  semantic_domain_id?: number | null
  template_text: string
  status: string
  created_at?: string
  updated_at?: string
}

export type PromptTemplateRequest = Omit<PromptTemplateItem, 'id' | 'created_at' | 'updated_at'> & {
  id?: number | null
}

export async function fetchAgents(): Promise<AgentItem[]> {
  const { data } = await api.get<{ agents: AgentItem[] }>('/agent/list')
  return data.agents || []
}

export async function createAgent(agent: AgentCreateRequest) {
  const { data } = await api.post('/agent/create', agent)
  return data
}

export async function updateAgent(agentId: number, agent: AgentCreateRequest) {
  const { data } = await api.put(`/agent/${agentId}`, agent)
  return data
}

export async function deleteAgent(agentId: number) {
  const { data } = await api.delete(`/agent/${agentId}`)
  return data
}

export async function fetchModelConfigs(modelType?: 'chat' | 'embedding'): Promise<ModelConfigItem[]> {
  const { data } = await api.get<{ configs: ModelConfigItem[] }>('/model-config/list', {
    params: modelType ? { model_type: modelType } : undefined,
  })
  return data.configs || []
}

export async function createModelConfig(config: ModelConfigRequest) {
  const { data } = await api.post('/model-config/create', config)
  return data
}

export async function updateModelConfig(configId: number, config: ModelConfigRequest) {
  const { data } = await api.put(`/model-config/${configId}`, config)
  return data
}

export async function testModelConfig(configId: number) {
  const { data } = await api.post<{
    ok: boolean
    message: string
    status_code?: number
    latency_ms?: number
    detail?: string
  }>(`/model-config/${configId}/test`)
  return data
}

export async function deleteModelConfig(configId: number) {
  const { data } = await api.delete(`/model-config/${configId}`)
  return data
}

export async function fetchPromptTemplates(promptKey?: string): Promise<PromptTemplateItem[]> {
  const { data } = await api.get<{ templates: PromptTemplateItem[] }>('/prompt/list', {
    params: promptKey ? { prompt_key: promptKey } : undefined,
  })
  return data.templates || []
}

export async function upsertPromptTemplate(template: PromptTemplateRequest) {
  const { data } = await api.post('/prompt/templates', template)
  return data
}

export async function deletePromptTemplate(templateId: number) {
  const { data } = await api.delete(`/prompt/templates/${templateId}`)
  return data
}

export async function resolvePromptTemplate(payload: Record<string, unknown>) {
  const { data } = await api.post('/prompt/resolve', payload)
  return data
}

export async function sendMessage(req: ChatRequest): Promise<ChatResponse> {
  const { data } = await api.post<ChatResponse>('/chat', req)
  return data
}

export async function confirmSqlExecution(req: ChatRequest & { sql: string }): Promise<ChatResponse> {
  const { data } = await api.post<ChatResponse>('/chat/confirm-sql', req)
  return data
}

export interface StreamEvent {
  event:
    | 'node_start'
    | 'node_progress'
    | 'reasoning'
    | 'token'
    | 'node_complete'
    | 'answer_start'
    | 'answer_delta'
    | 'answer_complete'
    | 'result'
    | 'error'
    | 'done'
  data: Record<string, unknown>
}

export interface ReasoningTraceStep {
  node: string
  label: string
  status: 'running' | 'done' | 'pending'
  reasoning: string
  streamText?: string
  events?: string[]
  output: Record<string, unknown> | null
  summary: string
}

export interface FeedbackRequest {
  agent_id?: number
  session_id?: string | null
  trace_id?: string | null
  rating?: 'positive' | 'negative' | 'neutral'
  comment?: string | null
  payload?: Record<string, unknown>
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
    if (!resp.ok) {
      onEvent({ event: 'error', data: { message: `请求失败: ${resp.status}` } })
      return
    }
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
      onEvent({ event: 'error', data: { message: '服务未返回流式内容' } })
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
  }).catch((error) => {
    if (error instanceof DOMException && error.name === 'AbortError') return
    onEvent({ event: 'error', data: { message: '网络连接失败' } })
  })
  return controller
}

export async function fetchDatasources(agentId: number) {
  const { data } = await api.get<{ datasources: DatasourceItem[] }>(`/datasource/list/${agentId}`)
  return data.datasources
}

export async function fetchAllDatasources() {
  const { data } = await api.get<{ datasources: DatasourceItem[] }>('/datasource/list')
  return data.datasources
}

export async function fetchAgentDatasourceIds(agentId: number): Promise<number[]> {
  const { data } = await api.get<{ datasource_ids: number[] }>(`/datasource/agent/${agentId}/ids`)
  return data.datasource_ids || []
}

export async function createDatasource(ds: Record<string, unknown>) {
  const { data } = await api.post('/datasource/create', ds)
  return data
}

export async function updateDatasource(dsId: number, ds: Record<string, unknown>) {
  const { data } = await api.put(`/datasource/${dsId}`, ds)
  return data
}

export async function deleteDatasource(dsId: number) {
  const { data } = await api.delete(`/datasource/${dsId}`)
  return data
}

export async function testConnection(dsId: number) {
  const { data } = await api.post(`/datasource/${dsId}/test`)
  return data
}

export async function collectSchema(dsId: number, tableNames?: string[]) {
  const { data } = await api.post(
    `/datasource/${dsId}/collect-schema`,
    tableNames ? { table_names: tableNames } : undefined,
  )
  return data
}

export async function uncollectSchema(dsId: number, tableNames: string[]) {
  const { data } = await api.post(`/datasource/${dsId}/uncollect-schema`, {
    table_names: tableNames,
  })
  return data
}

export async function fetchDatasourceSchema(dsId: number): Promise<DatasourceTableMeta[]> {
  const { data } = await api.get<{ tables: DatasourceTableMeta[] }>(`/datasource/${dsId}/schema`)
  return data.tables || []
}

export async function fetchDatasourceRemoteTables(dsId: number): Promise<DatasourceRemoteTable[]> {
  const { data } = await api.get<{ tables: DatasourceRemoteTable[] }>(`/datasource/${dsId}/remote-tables`)
  return data.tables || []
}

export async function fetchDatasourceTableSummaries(dsId: number): Promise<DatasourceTableSummary[]> {
  const { data } = await api.get<{ tables: DatasourceTableSummary[] }>(`/datasource/${dsId}/schema/tables`)
  return data.tables || []
}

export async function fetchDatasourceTableDetail(dsId: number, tableId: number): Promise<DatasourceTableMeta> {
  const { data } = await api.get<{ table: DatasourceTableMeta }>(`/datasource/${dsId}/schema/tables/${tableId}`)
  return data.table
}

export async function fetchDatasourceSchemaStats(dsId: number): Promise<DatasourceSchemaStats> {
  const { data } = await api.get<{ stats: DatasourceSchemaStats }>(`/datasource/${dsId}/schema/stats`)
  return data.stats
}

export interface SemanticDomain {
  id: number
  agent_id: number
  datasource_id?: number | null
  domain_key: string
  name: string
  description?: string
  status: string
}

export type SemanticDomainRequest = Omit<SemanticDomain, 'id'> & {
  id?: number | null
}

export async function fetchSemanticDomains(agentId: number): Promise<SemanticDomain[]> {
  const { data } = await api.get<{ domains: SemanticDomain[] }>('/semantic/domains', {
    params: { agent_id: agentId },
  })
  return data.domains || []
}

export async function fetchAllSemanticDomains(): Promise<SemanticDomain[]> {
  const { data } = await api.get<{ domains: SemanticDomain[] }>('/semantic/domains/all')
  return data.domains || []
}

export async function upsertSemanticDomain(domain: SemanticDomainRequest) {
  const { data } = await api.post('/semantic/domains', domain)
  return data
}

export async function deleteSemanticDomain(domainId: number) {
  const { data } = await api.delete(`/semantic/domains/${domainId}`)
  return data
}

export async function copySemanticDomain(domainId: number, payload: Record<string, unknown>) {
  const { data } = await api.post(`/semantic/domains/${domainId}/copy`, payload)
  return data
}

export async function exportSemanticDomain(domainId: number) {
  const { data } = await api.get(`/semantic/domains/${domainId}/export`)
  return data
}

export async function importSemanticDomain(payload: Record<string, unknown>) {
  const { data } = await api.post('/semantic/domains/import', payload)
  return data
}

export async function validateSemanticDomain(domainId: number) {
  const { data } = await api.post(`/semantic/domains/${domainId}/validate`)
  return data
}

export async function createSemanticSnapshot(domainId: number, payload: Record<string, unknown>) {
  const { data } = await api.post(`/semantic/domains/${domainId}/snapshot`, payload)
  return data
}

export async function fetchSemanticSnapshots(domainId: number) {
  const { data } = await api.get(`/semantic/domains/${domainId}/snapshots`)
  return data.snapshots || []
}

export async function fetchSemanticSnapshot(domainId: number, snapshotId: number) {
  const { data } = await api.get(`/semantic/domains/${domainId}/snapshots/${snapshotId}`)
  return data.snapshot
}

export async function diffSemanticSnapshot(domainId: number, snapshotId: number) {
  const { data } = await api.get(`/semantic/domains/${domainId}/snapshots/${snapshotId}/diff`)
  return data
}

export async function rollbackSemanticSnapshot(domainId: number, snapshotId: number) {
  const { data } = await api.post(`/semantic/domains/${domainId}/snapshots/${snapshotId}/rollback`)
  return data
}

export async function fetchSemanticAssets(domainId: number, assetType?: string) {
  const { data } = await api.get(`/semantic/assets/${domainId}`, {
    params: assetType ? { type: assetType } : undefined,
  })
  return data.assets || {}
}

export async function upsertSemanticAsset(
  domainId: number,
  assetType: string,
  asset: Record<string, unknown>,
) {
  const { data } = await api.post(`/semantic/assets/${domainId}`, {
    asset_type: assetType,
    data: asset,
  })
  return data
}

export async function deleteSemanticAsset(
  domainId: number,
  assetType: string,
  assetId: number,
) {
  const { data } = await api.delete(`/semantic/assets/${domainId}/${assetType}/${assetId}`)
  return data
}

export async function buildSemanticRuntime(payload: Record<string, unknown>) {
  const { data } = await api.post('/semantic/runtime/build', payload)
  return data.runtime
}

export async function validateLogicForm(payload: Record<string, unknown>) {
  const { data } = await api.post('/semantic/logic-form/validate', payload)
  return data
}

export async function syncSemanticVector(domainId: number) {
  const { data } = await api.post(`/semantic/sync-vector/${domainId}`)
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
  compiled_sql?: string
  reasoning_trace?: ReasoningTraceStep[]
  logic_form?: Record<string, unknown>
  sql_result?: Record<string, unknown>[]
  plan_payload?: Record<string, unknown>
  semantic_check?: Record<string, unknown>
  python_result?: Record<string, unknown>
  report_payload?: Record<string, unknown>
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

export async function submitFeedback(feedback: FeedbackRequest) {
  const { data } = await api.post('/feedback', feedback)
  return data
}
