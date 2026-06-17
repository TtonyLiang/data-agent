import assert from 'node:assert/strict'
import { existsSync, readFileSync, writeFileSync, unlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const sourcePath = new URL('./chatStream.ts', import.meta.url)
assert.ok(existsSync(sourcePath), 'chatStream.ts should exist')

const source = readFileSync(sourcePath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
    strict: true,
  },
}).outputText

const tempPath = join(tmpdir(), `chatStream.${process.pid}.${Date.now()}.mjs`)
writeFileSync(tempPath, compiled)
const reducer = await import(pathToFileURL(tempPath).href)
unlinkSync(tempPath)

const {
  createChatStreamState,
  startChatRun,
  reduceChatStreamEvent,
  toggleAssistantChain,
  toggleAssistantErrorDetail,
  toggleAssistantReasoning,
} = reducer

function assistantMessage(state) {
  const message = state.messages.find((item) => item.role === 'assistant')
  assert.ok(message, 'assistant message should exist')
  return message
}

{
  let state = createChatStreamState()
  state = startChatRun(state, { runId: 1, question: '本月销售额是多少？' })
  state = reduceChatStreamEvent(state, {
    runId: 1,
    event: 'node_start',
    data: { node: 'intent_recognition', label: '意图识别' },
  })
  state = reduceChatStreamEvent(state, {
    runId: 1,
    event: 'reasoning',
    data: { node: 'intent_recognition', delta: '先理解问题。' },
  })
  state = reduceChatStreamEvent(state, {
    runId: 1,
    event: 'reasoning',
    data: { node: 'intent_recognition', delta: '再识别指标。' },
  })

  assert.equal(assistantMessage(state).steps[0].reasoning, '先理解问题。再识别指标。')
}

{
  let state = createChatStreamState()
  state = startChatRun(state, { runId: 2, question: '列出订单' })
  state = reduceChatStreamEvent(state, { runId: 2, event: 'answer_start', data: {} })
  state = reduceChatStreamEvent(state, { runId: 2, event: 'answer_delta', data: { delta: '共有 ' } })
  state = reduceChatStreamEvent(state, { runId: 2, event: 'answer_delta', data: { delta: '10 条订单。' } })

  assert.equal(assistantMessage(state).content, '共有 10 条订单。')
}

{
  let state = createChatStreamState()
  state = startChatRun(state, { runId: 8, question: '生成 LogicForm' })
  state = reduceChatStreamEvent(state, {
    runId: 8,
    event: 'node_start',
    data: { node: 'nl2lf_generate', label: 'LogicForm 生成' },
  })
  state = reduceChatStreamEvent(state, {
    runId: 8,
    event: 'token',
    data: { node: 'nl2lf_generate', delta: '{"metrics":' },
  })
  state = reduceChatStreamEvent(state, {
    runId: 8,
    event: 'token',
    data: { node: 'nl2lf_generate', delta: '["application_count"]}' },
  })

  const step = assistantMessage(state).steps[0]
  assert.equal(step.streamText, '{"metrics":["application_count"]}')
  assert.match(step.summary, /application_count/)
}

{
  let state = createChatStreamState()
  state = startChatRun(state, { runId: 7, question: '申请笔数最多的前三种贷款是多少' })
  state = reduceChatStreamEvent(state, {
    runId: 7,
    event: 'node_start',
    data: { node: 'semantic_runtime_recall', label: '知识召回' },
  })
  state = reduceChatStreamEvent(state, {
    runId: 7,
    event: 'node_progress',
    data: {
      node: 'semantic_runtime_recall',
      message: '正在检索知识库、匹配语义资产...',
    },
  })

  const message = assistantMessage(state)
  assert.equal(message.steps[0].status, 'running')
  assert.equal(message.steps[0].summary, '正在检索知识库、匹配语义资产...')
}

{
  let state = createChatStreamState()
  state = startChatRun(state, { runId: 3, question: '生成 SQL' })
  state = reduceChatStreamEvent(state, {
    runId: 3,
    event: 'node_start',
    data: { node: 'lf_to_sql_compile', label: 'SQL 编译' },
  })
  state = reduceChatStreamEvent(state, {
    runId: 3,
    event: 'reasoning',
    data: { node: 'lf_to_sql_compile', delta: '编译受控查询。' },
  })
  state = reduceChatStreamEvent(state, {
    runId: 3,
    event: 'answer_delta',
    data: { delta: '查询完成。' },
  })
  state = reduceChatStreamEvent(state, {
    runId: 3,
    event: 'result',
    data: {
      intent: 'sales_query',
      sql: 'select * from sales',
      answer: '查询完成。',
      sql_result: [{ amount: 42 }],
    },
  })
  state = reduceChatStreamEvent(state, { runId: 3, event: 'done', data: {} })

  const message = assistantMessage(state)
  assert.equal(message.status, 'complete')
  assert.equal(message.chainCollapsed, true)
  assert.equal(message.steps[0].showReasoning, false)
  assert.equal(message.sql, 'select * from sales')
  assert.deepEqual(message.sql_result, [{ amount: 42 }])

  state = toggleAssistantReasoning(state, message.id, 'lf_to_sql_compile')
  assert.equal(assistantMessage(state).steps[0].showReasoning, true)

  state = toggleAssistantChain(state, message.id)
  assert.equal(assistantMessage(state).chainCollapsed, false)
}

{
  let state = createChatStreamState()
  state = startChatRun(state, { runId: 5, question: '新问题' })
  state = reduceChatStreamEvent(state, {
    runId: 4,
    event: 'answer_delta',
    data: { delta: '旧回答不应出现' },
  })
  state = reduceChatStreamEvent(state, {
    runId: 5,
    event: 'answer_delta',
    data: { delta: '新回答' },
  })

  assert.equal(assistantMessage(state).content, '新回答')
}

{
  let state = createChatStreamState()
  state = startChatRun(state, { runId: 6, question: '会失败的问题' })
  state = reduceChatStreamEvent(state, {
    runId: 6,
    event: 'error',
    data: {
      message: 'SQL 编译节点失败：服务暂不可用（RuntimeError）',
      detail: '服务暂不可用',
      node: 'lf_to_sql_compile',
      label: 'SQL 编译',
      error_type: 'RuntimeError',
    },
  })
  state = reduceChatStreamEvent(state, { runId: 6, event: 'done', data: {} })

  const message = assistantMessage(state)
  assert.equal(message.status, 'error')
  assert.equal(message.chainCollapsed, true)
  assert.equal(message.content, 'SQL 编译节点失败：服务暂不可用（RuntimeError）')
  assert.deepEqual(message.error, {
    message: 'SQL 编译节点失败：服务暂不可用（RuntimeError）',
    detail: '服务暂不可用',
    node: 'lf_to_sql_compile',
    label: 'SQL 编译',
    type: 'RuntimeError',
  })

  state = toggleAssistantErrorDetail(state, message.id)
  assert.equal(assistantMessage(state).showErrorDetail, true)
}
