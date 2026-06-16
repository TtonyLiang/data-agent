export type ChatRole = 'user' | 'assistant'
export type AssistantStatus = 'running' | 'complete' | 'error'
export type StepStatus = 'running' | 'done' | 'pending'

export interface ChatReasoningStep {
  node: string
  label: string
  status: StepStatus
  reasoning: string
  showReasoning: boolean
  output: Record<string, unknown> | null
  summary: string
}

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  status?: AssistantStatus
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
    assistant.steps.push({
      node,
      label: String(data.label || node),
      status: 'running',
      reasoning: '',
      showReasoning: true,
      output: null,
      summary: '',
    })
  } else if (input.event === 'reasoning') {
    const step = findStep(assistant, String(data.node || ''))
    if (step) step.reasoning += String(data.delta || '')
  } else if (input.event === 'node_complete') {
    const step = findStep(assistant, String(data.node || ''))
    if (step) {
      step.status = 'done'
      step.output = (data.output as Record<string, unknown>) || {}
      step.summary = summarizeStep(step)
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
    const trace = data.reasoning_trace as ChatReasoningStep[] | undefined
    if (Array.isArray(trace) && trace.length) {
      assistant.steps = trace.map(step => ({
        node: String(step.node || ''),
        label: String(step.label || step.node || ''),
        status: step.status === 'running' || step.status === 'pending' ? step.status : 'done',
        reasoning: String(step.reasoning || ''),
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
    assistant.error = {
      message,
      detail: typeof data.detail === 'string' ? data.detail : undefined,
      node: typeof data.node === 'string' ? data.node : undefined,
      label: typeof data.label === 'string' ? data.label : undefined,
      type: typeof data.error_type === 'string' ? data.error_type : undefined,
    }
  } else if (input.event === 'done') {
    if (assistant.status !== 'error') assistant.status = 'complete'
    assistant.steps = assistant.steps.map(step => ({
      ...step,
      status: step.status === 'running' ? 'done' : step.status,
      showReasoning: false,
    }))
  }

  messages[assistantIndex] = assistant
  return { ...state, messages }
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

function cloneMessage(message: ChatMessage): ChatMessage {
  return {
    ...message,
    steps: message.steps.map(step => ({ ...step })),
    error: message.error ? { ...message.error } : message.error,
    logic_form: message.logic_form ? { ...message.logic_form } : message.logic_form,
    sql_result: message.sql_result ? [...message.sql_result] : message.sql_result,
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
  if (step.node === 'semantic_runtime_recall') {
    const domain = String(output.domain || '')
    return domain ? `${domain} · 召回 ${String(output.count || 0)} 条语义资产` : `召回 ${String(output.count || 0)} 条语义资产`
  }
  if (step.node === 'nl2lf_generate') {
    const logicForm = output.logic_form as Record<string, unknown> | undefined
    const metrics = Array.isArray(logicForm?.metrics) ? logicForm.metrics : []
    return metrics.length ? `指标: ${metrics.join(', ')}` : '已生成 LogicForm'
  }
  if (step.node === 'lf_validate') {
    const valid = output.valid === true
    const errors = (output.errors as string[]) || []
    return valid ? '校验通过' : `校验失败: ${errors[0] || ''}`
  }
  if (step.node === 'lf_to_sql_compile') {
    return output.compiled_sql ? '已编译 SQL' : ''
  }
  if (step.node === 'sql_execute') {
    const error = output.error as string | undefined
    return error ? `错误: ${error.slice(0, 40)}` : `${String(output.row_count || 0)} 条结果`
  }
  return ''
}
