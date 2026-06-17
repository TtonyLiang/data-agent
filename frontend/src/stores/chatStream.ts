export type ChatRole = 'user' | 'assistant'
export type AssistantStatus = 'running' | 'complete' | 'error'
export type StepStatus = 'running' | 'done' | 'pending'

export interface ChatReasoningStep {
  node: string
  label: string
  status: StepStatus
  reasoning: string
  streamText?: string
  events?: string[]
  showReasoning: boolean
  showPythonCode?: boolean
  output: Record<string, unknown> | null
  summary: string
}

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  status?: AssistantStatus
  chainCollapsed?: boolean
  showErrorDetail?: boolean
  error?: {
    message: string
    detail?: string
    node?: string
    label?: string
    type?: string
  }
  intent?: string
  sql?: string
  logic_form?: Record<string, unknown>
  sql_result?: Record<string, unknown>[]
  plan?: Record<string, unknown>
  semantic_check?: Record<string, unknown>
  python_result?: Record<string, unknown>
  report_payload?: Record<string, unknown>
  steps: ChatReasoningStep[]
}

export interface ChatStreamState {
  activeRunId: number
  sessionId?: string
  messages: ChatMessage[]
}

export interface ChatStreamInputEvent {
  runId: number
  event: string
  data: Record<string, unknown>
}

export function createChatStreamState(): ChatStreamState {
  return {
    activeRunId: 0,
    messages: [],
  }
}

export function startChatRun(
  state: ChatStreamState,
  payload: { runId: number; question: string },
): ChatStreamState {
  return {
    activeRunId: payload.runId,
    messages: [
      ...state.messages,
      {
        id: `user-${payload.runId}`,
        role: 'user',
        content: payload.question,
        steps: [],
      },
      {
        id: `assistant-${payload.runId}`,
        role: 'assistant',
        content: '',
        status: 'running',
        chainCollapsed: true,
        showErrorDetail: false,
        steps: [],
      },
    ],
  }
}

export function createAssistantMessage(content = ''): ChatMessage {
  return {
    id: `assistant-${Date.now()}`,
    role: 'assistant',
    content,
    status: 'complete',
    steps: [],
  }
}

export function clearActiveRun(state: ChatStreamState): ChatStreamState {
  return {
    ...state,
    activeRunId: state.activeRunId + 1,
  }
}

export function reduceChatStreamEvent(
  state: ChatStreamState,
  input: ChatStreamInputEvent,
): ChatStreamState {
  if (input.runId !== state.activeRunId) return state
  const assistantIndex = state.messages.findIndex(
    message => message.id === `assistant-${input.runId}`,
  )
  if (assistantIndex < 0) return state

  const messages = [...state.messages]
  const assistant = cloneMessage(messages[assistantIndex])
  const data = input.data

  if (input.event === 'node_start') {
    const node = String(data.node || '')
    assistant.chainCollapsed = true
    const label = String(data.label || node)
    assistant.steps.push({
      node,
      label,
      status: 'running',
      reasoning: '',
      streamText: '',
      events: [`开始${label}。`],
      showReasoning: true,
      showPythonCode: false,
      output: null,
      summary: '',
    })
  } else if (input.event === 'node_progress') {
    const step = findStep(assistant, String(data.node || ''))
    if (step && step.status === 'running') {
      const message = String(data.message || step.summary || '处理中...')
      step.summary = message
      replaceProgressEvent(step, message)
    }
  } else if (input.event === 'reasoning') {
    const step = findStep(assistant, String(data.node || ''))
    if (step) step.reasoning += String(data.delta || '')
  } else if (input.event === 'token') {
    const step = findStep(assistant, String(data.node || ''))
    if (step) {
      step.streamText = `${step.streamText || ''}${String(data.delta || '')}`
      if (!step.summary || step.status === 'running') {
        step.summary = summarizeStreamingToken(step)
      }
    }
  } else if (input.event === 'node_complete') {
    const step = findStep(assistant, String(data.node || ''))
    if (step) {
      step.status = 'done'
      step.output = (data.output as Record<string, unknown>) || {}
      step.summary = summarizeStep(step)
      if (step.summary) appendStepEvent(step, `完成：${step.summary}`)
    }
  } else if (input.event === 'answer_start') {
    assistant.content = ''
  } else if (input.event === 'answer_delta') {
    assistant.content += String(data.delta || '')
  } else if (input.event === 'answer_complete') {
    assistant.content = String(data.answer || assistant.content)
  } else if (input.event === 'result') {
    if (typeof data.session_id === 'string') {
      state = { ...state, sessionId: data.session_id }
    }
    assistant.intent = String(data.intent || '')
    assistant.sql = String(data.sql || '')
    assistant.logic_form = (data.logic_form as Record<string, unknown>) || undefined
    assistant.sql_result = (data.sql_result as Record<string, unknown>[]) || []
    assistant.plan = (data.plan as Record<string, unknown>) || undefined
    assistant.semantic_check = (data.semantic_check as Record<string, unknown>) || undefined
    assistant.python_result = (data.python_result as Record<string, unknown>) || undefined
    assistant.report_payload = (data.report_payload as Record<string, unknown>) || undefined
    const trace = data.reasoning_trace as ChatReasoningStep[] | undefined
    if (Array.isArray(trace) && trace.length) {
      assistant.steps = trace.map(step => ({
        node: String(step.node || ''),
        label: String(step.label || step.node || ''),
        status: step.status === 'running' || step.status === 'pending' ? step.status : 'done',
        reasoning: String(step.reasoning || ''),
        streamText: streamTextFromTrace(step),
        events: eventsFromTrace(step),
        showReasoning: false,
        output: step.output || null,
        summary: String(step.summary || ''),
      }))
    }
    if (!assistant.content) assistant.content = String(data.answer || '')
  } else if (input.event === 'error') {
    const message = String(data.message || '请求失败，请稍后重试。')
    assistant.status = 'error'
    assistant.content = message
    assistant.chainCollapsed = true
    assistant.showErrorDetail = false
    assistant.error = {
      message,
      detail: typeof data.detail === 'string' ? data.detail : undefined,
      node: typeof data.node === 'string' ? data.node : undefined,
      label: typeof data.label === 'string' ? data.label : undefined,
      type: typeof data.error_type === 'string' ? data.error_type : undefined,
    }
  } else if (input.event === 'done') {
    if (assistant.status !== 'error') assistant.status = 'complete'
    assistant.chainCollapsed = true
    assistant.steps = assistant.steps.map(step => ({
      ...step,
      status: step.status === 'running' ? 'done' : step.status,
      showReasoning: false,
      showPythonCode: step.showPythonCode ?? false,
    }))
  }

  messages[assistantIndex] = assistant
  return { ...state, messages }
}

function summarizeStreamingToken(step: ChatReasoningStep): string {
  const text = String(step.streamText || '').replace(/\s+/g, ' ').trim()
  if (!text) return step.summary || '正在生成...'
  return text.length > 80 ? `${text.slice(0, 80)}...` : text
}

function appendStepEvent(step: ChatReasoningStep, message: string) {
  const text = message.trim()
  if (!text) return
  const events = step.events || []
  if (events[events.length - 1] !== text) {
    step.events = [...events, text]
  }
}

function replaceProgressEvent(step: ChatReasoningStep, message: string) {
  const text = message.trim()
  if (!text) return
  const events = step.events || []
  const durableEvents = events.filter(event => {
    const normalized = String(event || '').trim()
    return normalized && !normalized.startsWith('正在') && !normalized.endsWith('...')
  })
  step.events = [...durableEvents, text]
}

function streamTextFromTrace(step: ChatReasoningStep) {
  const rawStep = step as unknown as Record<string, unknown>
  return String(step.streamText || rawStep.stream_text || '')
}

function eventsFromTrace(step: ChatReasoningStep) {
  const rawStep = step as unknown as Record<string, unknown>
  if (Array.isArray(rawStep.events)) return rawStep.events.map(String).filter(Boolean)
  return step.summary ? [String(step.summary)] : []
}

export function toggleAssistantReasoning(
  state: ChatStreamState,
  messageId: string,
  node: string,
): ChatStreamState {
  return {
    ...state,
    messages: state.messages.map((message) => {
      if (message.id !== messageId || message.role !== 'assistant') return message
      return {
        ...message,
        steps: message.steps.map(step => (
          step.node === node ? { ...step, showReasoning: !step.showReasoning } : step
        )),
      }
    }),
  }
}

export function toggleAssistantPythonCode(
  state: ChatStreamState,
  messageId: string,
  node: string,
): ChatStreamState {
  return {
    ...state,
    messages: state.messages.map((message) => {
      if (message.id !== messageId || message.role !== 'assistant') return message
      return {
        ...message,
        steps: message.steps.map(step => (
          step.node === node ? { ...step, showPythonCode: !step.showPythonCode } : step
        )),
      }
    }),
  }
}

export function toggleAssistantChain(
  state: ChatStreamState,
  messageId: string,
): ChatStreamState {
  return {
    ...state,
    messages: state.messages.map((message) => {
      if (message.id !== messageId || message.role !== 'assistant') return message
      return {
        ...message,
        chainCollapsed: !message.chainCollapsed,
      }
    }),
  }
}

export function toggleAssistantErrorDetail(
  state: ChatStreamState,
  messageId: string,
): ChatStreamState {
  return {
    ...state,
    messages: state.messages.map((message) => {
      if (message.id !== messageId || message.role !== 'assistant') return message
      return {
        ...message,
        showErrorDetail: !message.showErrorDetail,
      }
    }),
  }
}

function cloneMessage(message: ChatMessage): ChatMessage {
  return {
    ...message,
    steps: message.steps.map(step => ({ ...step })),
    error: message.error ? { ...message.error } : message.error,
    logic_form: message.logic_form ? { ...message.logic_form } : message.logic_form,
    sql_result: message.sql_result ? [...message.sql_result] : message.sql_result,
    plan: message.plan ? { ...message.plan } : message.plan,
    semantic_check: message.semantic_check ? { ...message.semantic_check } : message.semantic_check,
    python_result: message.python_result ? { ...message.python_result } : message.python_result,
    report_payload: message.report_payload ? { ...message.report_payload } : message.report_payload,
  }
}

function findStep(message: ChatMessage, node: string): ChatReasoningStep | undefined {
  return message.steps.find(step => step.node === node)
}

function summarizeStep(step: ChatReasoningStep): string {
  const output = step.output || {}
  if (step.node === 'intent_recognition') {
    return `→ ${String(output.intent || '')}`
  }
  if (step.node === 'semantic_enhance') {
    const original = String(output.original_question || '')
    const enhanced = String(output.enhanced_question || '')
    if (enhanced && enhanced !== original) return `已改写问题：${enhanced}`
    return enhanced || '问题已整理'
  }
  if (step.node === 'semantic_runtime_recall') {
    const domain = String(output.domain || '')
    return domain ? `${domain} · 召回 ${String(output.count || 0)} 条语义资产` : `召回 ${String(output.count || 0)} 条语义资产`
  }
  if (step.node === 'schema_recall') {
    const tables = Array.isArray(output.matched_tables) ? output.matched_tables.length : 0
    const columns = Array.isArray(output.matched_columns) ? output.matched_columns.length : 0
    return output.fallback_used ? `已采集表结构兜底 · ${tables} 张表 ${columns} 个字段` : `定位 ${tables} 张候选表 · ${columns} 个字段`
  }
  if (step.node === 'nl2lf_generate') {
    const logicForm = output.logic_form as Record<string, unknown> | undefined
    const metrics = Array.isArray(logicForm?.metrics) ? logicForm.metrics : []
    const dimensions = Array.isArray(logicForm?.dimensions) ? logicForm.dimensions : []
    const limit = logicForm?.limit
    const parts = []
    if (metrics.length) parts.push(`指标: ${metrics.join(', ')}`)
    if (dimensions.length) parts.push(`维度: ${dimensions.join(', ')}`)
    if (typeof limit === 'number' && limit > 0) parts.push(`限数: ${limit}`)
    return parts.length ? parts.join(' · ') : '已生成 LogicForm'
  }
  if (step.node === 'lf_validate') {
    const valid = output.valid === true
    const errors = (output.errors as string[]) || []
    const warnings = (output.warnings as string[]) || []
    if (valid) {
      return warnings.length ? `校验通过 · ${warnings[0]}` : '校验通过'
    }
    return `校验失败: ${errors[0] || ''}`
  }
  if (step.node === 'lf_to_sql_compile') {
    const error = output.error as string | undefined
    const strategy = output.strategy as string | undefined
    if (output.compiled_sql) return strategy ? `已编译 SQL · ${strategy}` : '已编译 SQL'
    return error ? `编译失败: ${error.slice(0, 40)}` : ''
  }
  if (step.node === 'nl2sql_fallback') {
    const error = output.error as string | undefined
    if (output.compiled_sql) return '已生成兜底 SQL'
    return error ? `兜底失败: ${error.slice(0, 40)}` : ''
  }
  if (step.node === 'semantic_check') {
    return output.valid === true ? '一致性通过' : '一致性未通过'
  }
  if (step.node === 'sql_execute') {
    const error = output.error as string | undefined
    const columns = Array.isArray(output.columns) ? output.columns.length : 0
    const sampleRows = Array.isArray(output.sample_rows) ? output.sample_rows.length : 0
    if (error) return `错误: ${error.slice(0, 40)}`
    return `${String(output.row_count || 0)} 条结果 · ${columns} 列 · ${sampleRows} 条样例`
  }
  if (step.node === 'planner') {
    const plan = output.plan as Record<string, unknown> | undefined
    const steps = Array.isArray(plan?.analysis_steps) ? plan.analysis_steps : []
    const modeLabel = String(output.mode_label || plan?.mode_label || '本地分析计划')
    const rowCount = output.row_count ?? plan?.row_count
    const columnCount = output.column_count ?? plan?.column_count
    return `${modeLabel} · ${steps.length} 个步骤 · ${String(rowCount ?? 0)} 行 ${String(columnCount ?? 0)} 列`
  }
  if (step.node === 'python_generate') {
    const tasks = Array.isArray(output.generated_tasks) ? output.generated_tasks : []
    const hasCode = typeof output.python_code === 'string' && output.python_code.trim().length > 0
    return `统计脚本${hasCode ? '（点击查看）' : ''} · ${tasks.length} 个任务`
  }
  if (step.node === 'python_analyze') {
    const result = output.python_result as Record<string, unknown> | undefined
    const computed = Array.isArray(output.computed_items) ? output.computed_items : []
    return result?.status === 'success' ? `基础统计完成 · ${computed.join('、')}` : String(result?.status || '')
  }
  if (step.node === 'report_generator') {
    return `${String(output.mode_label || '结构化报告')} · ${String(output.title || '已生成报告')}`
  }
  return ''
}
