import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

export const AUTH_TOKEN_STORAGE_KEY = 'wenqu_access_token'

export function getAccessToken(): string {
  if (typeof window === 'undefined') return ''
  return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || ''
}

export function setAccessToken(token: string) {
  if (typeof window !== 'undefined') window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token)
}

export function clearAccessToken() {
  if (typeof window !== 'undefined') window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
}

export function buildAuthHeaders(): Record<string, string> {
  const token = getAccessToken().trim()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export type ChatTurnMode = 'new_task' | 'continue' | 'refine' | 'retry' | 'analyze' | 'respond'

export interface ChatTaskMetadata {
  task_id?: string
  turn_id?: string
  turn_mode?: ChatTurnMode
  task_status?: string
  checkpoint_revision?: number
  reused_artifacts?: string[]
  invalidated_artifacts?: string[]
  context_invalidated?: boolean
}

api.interceptors.request.use((config) => {
  const headers = buildAuthHeaders()
  if (headers.Authorization) {
    config.headers = config.headers || {}
    config.headers.Authorization = headers.Authorization
  }
  return config
})

export interface ChatRequest {
  question: string
  agent_id?: number
  datasource_id?: number | null
  session_id?: string
  trace_id?: string
  turn_mode?: ChatTurnMode
  require_sql_confirmation?: boolean
  enable_low_confidence_clarification?: boolean
}

export interface ChatResponse extends ChatTaskMetadata {
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
  default_questions?: string[]
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
  default_questions?: string[]
  datasource_ids?: number[]
  llm_provider?: string
  llm_model?: string
}

export interface CurrentUser {
  id: number
  username: string
  display_name?: string | null
  role: 'admin' | 'user'
  status: 'active' | 'disabled'
  must_change_password?: boolean
  created_at?: string | null
  updated_at?: string | null
  last_login_at?: string | null
}

export interface UserCreateRequest {
  username: string
  password: string
  display_name?: string | null
  role?: 'admin' | 'user'
  status?: 'active' | 'disabled'
}

export interface UserUpdateRequest {
  display_name?: string | null
  role: 'admin' | 'user'
  status: 'active' | 'disabled'
  must_change_password?: boolean
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

export interface PromptCatalogItem {
  prompt_key: string
  filename: string
  name: string
  description: string
  node: string
  template_text: string
}

export interface SystemParameterItem {
  key: string
  name: string
  value: number | string | boolean | Record<string, unknown> | unknown[]
  value_type: 'int' | 'float' | 'bool' | 'string' | 'json'
  category: string
  description?: string
  created_at?: string | null
  updated_at?: string | null
}

export interface SystemParameterUpdate {
  key: string
  value: number | string | boolean | Record<string, unknown> | unknown[]
}

export type PromptTemplateRequest = Omit<PromptTemplateItem, 'id' | 'created_at' | 'updated_at'> & {
  id?: number | null
}

export async function registerUser(payload: { username: string; password: string; display_name?: string }) {
  const { data } = await api.post('/auth/register', payload)
  return data
}

export async function loginUser(payload: { username: string; password: string }) {
  const { data } = await api.post<{ access_token: string; token_type: string; user: CurrentUser }>('/auth/login', payload)
  setAccessToken(data.access_token)
  return data
}

export async function logoutUser() {
  try {
    await api.post('/auth/logout')
  } finally {
    clearAccessToken()
  }
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const { data } = await api.get<CurrentUser>('/auth/me')
  return data
}

export async function fetchUsers(): Promise<CurrentUser[]> {
  const { data } = await api.get<{ users: CurrentUser[] }>('/users')
  return data.users || []
}

export async function createUser(payload: UserCreateRequest) {
  const { data } = await api.post('/users', payload)
  return data
}

export async function updateUser(userId: number, payload: UserUpdateRequest) {
  const { data } = await api.put(`/users/${userId}`, payload)
  return data
}

export async function disableUser(userId: number) {
  const { data } = await api.post(`/users/${userId}/disable`)
  return data
}

export async function enableUser(userId: number) {
  const { data } = await api.post(`/users/${userId}/enable`)
  return data
}

export async function resetUserPassword(userId: number, password: string) {
  const { data } = await api.post(`/users/${userId}/reset-password`, {
    password,
    must_change_password: true,
  })
  return data
}

export async function fetchUserAgentIds(userId: number): Promise<number[]> {
  const { data } = await api.get<{ agent_ids: number[] }>(`/users/${userId}/agents`)
  return data.agent_ids || []
}

export async function updateUserAgentIds(userId: number, agentIds: number[]) {
  const { data } = await api.put(`/users/${userId}/agents`, { agent_ids: agentIds })
  return data
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

export async function fetchPromptCatalog(): Promise<PromptCatalogItem[]> {
  const { data } = await api.get<{ prompts: PromptCatalogItem[] }>('/prompt/catalog')
  return data.prompts || []
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

export async function fetchSystemParameters(category?: string): Promise<SystemParameterItem[]> {
  const { data } = await api.get<{ parameters: SystemParameterItem[] }>('/system/parameters', {
    params: category ? { category } : undefined,
  })
  return data.parameters || []
}

export async function updateSystemParameters(updates: SystemParameterUpdate[]) {
  const { data } = await api.put<{ parameters: SystemParameterItem[]; message: string }>(
    '/system/parameters',
    updates,
  )
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
    headers: { 'Content-Type': 'application/json', ...buildAuthHeaders() },
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

export type OntologyPropertyType =
  | 'string'
  | 'text'
  | 'integer'
  | 'number'
  | 'boolean'
  | 'date'
  | 'datetime'
  | 'json'

export interface OntologyProperty {
  id?: number
  property_key: string
  name: string
  data_type: OntologyPropertyType
  required: boolean
  unique: boolean
  description?: string
  default_value?: unknown
  sort_order: number
}

export interface OntologyObjectType {
  id: number
  domain_id: number
  object_key: string
  name: string
  description?: string
  primary_property: string
  display_property?: string | null
  sync_enabled: boolean
  source_query?: string | null
  sync_limit: number
  last_sync_status?: 'succeeded' | 'partial' | 'failed' | null
  last_sync_count?: number
  last_sync_total?: number
  last_sync_error?: string | null
  last_synced_at?: string | null
  status: 'draft' | 'active' | 'deprecated'
  properties: OntologyProperty[]
}

export interface OntologyLinkType {
  id: number
  domain_id: number
  link_key: string
  name: string
  source_object_key: string
  target_object_key: string
  source_property?: string | null
  target_property?: string | null
  cardinality: 'one_to_one' | 'one_to_many' | 'many_to_one' | 'many_to_many'
  description?: string
  status: 'draft' | 'active' | 'deprecated'
}

export interface OntologyActionParameter {
  parameter_key: string
  name: string
  data_type: OntologyPropertyType
  required: boolean
  options: unknown[]
  description?: string
}

export interface OntologyPrecondition {
  property: string
  operator: 'eq' | 'ne' | 'in' | 'not_in' | 'gt' | 'gte' | 'lt' | 'lte' | 'exists'
  value: unknown
  message?: string
}

export interface OntologyEffect {
  property: string
  value: unknown
}

export interface OntologyActionType {
  id: number
  domain_id: number
  action_key: string
  name: string
  target_object_key: string
  description?: string
  parameters: OntologyActionParameter[]
  preconditions: OntologyPrecondition[]
  effects: OntologyEffect[]
  allowed_roles: Array<'admin' | 'user'>
  requires_approval: boolean
  status: 'draft' | 'active' | 'deprecated'
}

export interface OntologyObject {
  id: number
  domain_id: number
  object_type_id: number
  object_type_key: string
  object_type_name: string
  primary_value: string
  display_name: string
  properties: Record<string, unknown>
  version: number
  status: 'active' | 'archived'
  source_kind?: 'manual' | 'bundle' | 'database' | string
  source_datasource_id?: number | null
  source_properties?: Record<string, unknown>
  overlay_properties?: Record<string, unknown>
  last_synced_at?: string | null
  created_at?: string
  updated_at?: string
}

export interface OntologyLink {
  id: number
  link_type_id: number
  link_key: string
  link_type_name: string
  source_object_id: number
  source_name: string
  source_primary_value: string
  target_object_id: number
  target_name: string
  target_primary_value: string
  properties: Record<string, unknown>
}

export interface OntologyActionRun {
  id: number
  action_type_id: number
  action_key: string
  action_name: string
  target_object_id?: number
  target_name?: string
  user_id?: number
  user_name?: string
  username?: string
  status: 'running' | 'succeeded' | 'failed'
  parameters: Record<string, unknown>
  decision_context: Record<string, unknown>
  before_state: Record<string, unknown>
  after_state: Record<string, unknown>
  error_message?: string
  created_at?: string
  completed_at?: string
}

export interface OntologySummary {
  domain: SemanticDomain
  counts: {
    object_types: number
    link_types: number
    action_types: number
    objects: number
    source_objects?: number
    links: number
    action_runs: number
  }
  latest_release?: {
    id: number
    version: number
    name: string
    description?: string
    created_at?: string
  } | null
}

export interface OntologyAgentToolDefinition {
  name: 'ontology_query_objects' | 'ontology_execute_action' | string
  description: string
  parameters: Record<string, unknown>
}

export interface OntologyAgentContext {
  domain: SemanticDomain | Record<string, unknown>
  release?: Record<string, unknown> | null
  role: 'admin' | 'user' | string
  object_types: Array<Record<string, unknown>>
  link_types: Array<Record<string, unknown>>
  actions: Array<Record<string, unknown>>
  capabilities: { query_objects: boolean; execute_actions: boolean }
  tools: OntologyAgentToolDefinition[]
}

export async function fetchOntologyDomains(): Promise<SemanticDomain[]> {
  const { data } = await api.get<{ domains: SemanticDomain[] }>('/ontology/domains')
  return data.domains || []
}

export async function fetchOntologySummary(domainId: number): Promise<OntologySummary> {
  const { data } = await api.get(`/ontology/domains/${domainId}/summary`)
  return data
}

export async function fetchOntologyObjectTypes(domainId: number): Promise<OntologyObjectType[]> {
  const { data } = await api.get(`/ontology/domains/${domainId}/object-types`)
  return data.object_types || []
}

export async function saveOntologyObjectType(domainId: number, payload: Record<string, unknown>) {
  const { data } = await api.post(`/ontology/domains/${domainId}/object-types`, payload)
  return data
}

export async function deleteOntologyObjectType(domainId: number, objectTypeId: number) {
  const { data } = await api.delete(`/ontology/domains/${domainId}/object-types/${objectTypeId}`)
  return data
}

export async function fetchOntologyLinkTypes(domainId: number): Promise<OntologyLinkType[]> {
  const { data } = await api.get(`/ontology/domains/${domainId}/link-types`)
  return data.link_types || []
}

export async function saveOntologyLinkType(domainId: number, payload: Record<string, unknown>) {
  const { data } = await api.post(`/ontology/domains/${domainId}/link-types`, payload)
  return data
}

export async function deleteOntologyLinkType(domainId: number, linkTypeId: number) {
  const { data } = await api.delete(`/ontology/domains/${domainId}/link-types/${linkTypeId}`)
  return data
}

export async function fetchOntologyActionTypes(domainId: number): Promise<OntologyActionType[]> {
  const { data } = await api.get(`/ontology/domains/${domainId}/action-types`)
  return data.action_types || []
}

export async function fetchOntologyAgentContext(domainId: number): Promise<OntologyAgentContext> {
  const { data } = await api.get<OntologyAgentContext>(`/ontology/domains/${domainId}/agent-context`)
  return data
}

export async function queryOntologyObjects(
  domainId: number,
  params?: { object_type_key?: string; search?: string; limit?: number; offset?: number },
) {
  const { data } = await api.get(`/ontology/domains/${domainId}/query`, { params })
  return data
}

export async function executeOntologyTool(
  domainId: number,
  toolName: string,
  arguments_: Record<string, unknown>,
) {
  const { data } = await api.post(`/ontology/domains/${domainId}/agent-tools/${toolName}`, {
    arguments: arguments_,
  })
  return data
}

export async function saveOntologyActionType(domainId: number, payload: Record<string, unknown>) {
  const { data } = await api.post(`/ontology/domains/${domainId}/action-types`, payload)
  return data
}

export async function deleteOntologyActionType(domainId: number, actionTypeId: number) {
  const { data } = await api.delete(`/ontology/domains/${domainId}/action-types/${actionTypeId}`)
  return data
}

export async function validateOntology(domainId: number) {
  const { data } = await api.post(`/ontology/domains/${domainId}/validate`)
  return data
}

export async function publishOntology(domainId: number, payload: Record<string, unknown>) {
  const { data } = await api.post(`/ontology/domains/${domainId}/publish`, payload)
  return data
}

export async function fetchOntologyReleases(domainId: number) {
  const { data } = await api.get(`/ontology/domains/${domainId}/releases`)
  return data.releases || []
}

export async function exportOntologyBundle(domainId: number, includeInstances = true) {
  const { data } = await api.get(`/ontology/domains/${domainId}/export`, {
    params: { include_instances: includeInstances },
  })
  return data
}

export async function importOntologyBundle(
  domainId: number,
  bundle: Record<string, unknown>,
  replace = false,
) {
  const { data } = await api.post(`/ontology/domains/${domainId}/import`, { bundle, replace })
  return data
}

export interface OntologySyncTypeResult {
  object_type_id: number
  object_key: string
  name: string
  page: number
  page_size: number
  total: number
  read: number
  created: number
  updated: number
  unchanged: number
  skipped: number
  errors: string[]
  objects: OntologyObject[]
}

export interface OntologySyncResult {
  domain_id: number
  datasource_id: number
  page: number
  types: OntologySyncTypeResult[]
  objects: OntologyObject[]
  total: number
  links_synced: number
  has_errors: boolean
}

export interface OntologySyncRequest {
  object_type_id: number
  page: number
  page_size: number
  sync_links: boolean
}

export async function syncOntologyObjects(
  domainId: number,
  payload: OntologySyncRequest,
): Promise<OntologySyncResult> {
  const { data } = await api.post(`/ontology/domains/${domainId}/sync`, payload)
  return data
}

export async function fetchOntologyObjects(
  domainId: number,
  objectTypeId?: number,
  limit = 1000,
  offset = 0,
): Promise<OntologyObject[]> {
  const { data } = await api.get(`/ontology/domains/${domainId}/objects`, {
    params: {
      ...(objectTypeId ? { object_type_id: objectTypeId } : {}),
      limit,
      offset,
    },
  })
  return data.objects || []
}

export async function saveOntologyObject(domainId: number, payload: Record<string, unknown>) {
  const { data } = await api.post(`/ontology/domains/${domainId}/objects`, payload)
  return data
}

export async function deleteOntologyObject(domainId: number, objectId: number) {
  const { data } = await api.delete(`/ontology/domains/${domainId}/objects/${objectId}`)
  return data
}

export async function fetchOntologyLinks(domainId: number): Promise<OntologyLink[]> {
  const { data } = await api.get(`/ontology/domains/${domainId}/links`)
  return data.links || []
}

export async function saveOntologyLink(domainId: number, payload: Record<string, unknown>) {
  const { data } = await api.post(`/ontology/domains/${domainId}/links`, payload)
  return data
}

export async function deleteOntologyLink(domainId: number, linkId: number) {
  const { data } = await api.delete(`/ontology/domains/${domainId}/links/${linkId}`)
  return data
}

export async function executeOntologyAction(
  domainId: number,
  actionTypeId: number,
  payload: Record<string, unknown>,
) {
  const { data } = await api.post(
    `/ontology/domains/${domainId}/actions/${actionTypeId}/execute`,
    payload,
  )
  return data
}

export async function fetchOntologyActionRuns(domainId: number): Promise<OntologyActionRun[]> {
  const { data } = await api.get(`/ontology/domains/${domainId}/action-runs`)
  return data.runs || []
}

// 会话历史
export interface SessionItem {
  session_id: string
  created_at: string
  turn_count: number
  last_question: string
}

export interface HistoryItem extends ChatTaskMetadata {
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
