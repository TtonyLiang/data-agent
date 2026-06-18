import assert from 'node:assert/strict'
import { existsSync, readFileSync, writeFileSync, unlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const sourcePath = new URL('./index.ts', import.meta.url)
assert.ok(existsSync(sourcePath), 'api index.ts should exist')

let source = readFileSync(sourcePath, 'utf8')
source = source.replace("import axios from 'axios'", "const axios = globalThis.__axios")
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
    strict: true,
  },
}).outputText

const tempPath = join(tmpdir(), `api-index.${process.pid}.${Date.now()}.mjs`)
writeFileSync(tempPath, compiled)

const axiosCalls = []

globalThis.__axios = {
  create() {
    return {
      get(url) {
        axiosCalls.push(['get', url])
        return Promise.resolve({ data: {} })
      },
      post(url, body) {
        axiosCalls.push(['post', url, body])
        return Promise.resolve({ data: {} })
      },
      put(url, body) {
        axiosCalls.push(['put', url, body])
        return Promise.resolve({ data: {} })
      },
      delete(url) {
        axiosCalls.push(['delete', url])
        return Promise.resolve({ data: {} })
      },
    }
  },
}

const api = await import(pathToFileURL(tempPath).href)
unlinkSync(tempPath)

{
  await api.updateAgent(3, {
    name: '编辑后智能体',
    description: '',
    chat_model_config_id: 1,
    embedding_model_config_id: 2,
    semantic_domain_id: 6,
    datasource_ids: [5],
  })
  await api.deleteAgent(3)
  await api.fetchModelConfigs('chat')
  await api.createModelConfig({ name: 'chat', model_type: 'chat', provider: 'ollama', base_url: '/v1', model_name: 'qwen3', api_key_enabled: false, status: 'active' })
  await api.testModelConfig(9)
  await api.fetchPromptTemplates('nl2lf_generate.system')
  await api.upsertPromptTemplate({
    prompt_key: 'nl2lf_generate.system',
    name: '贷款 LogicForm 模板',
    description: '',
    agent_id: 1,
    model_config_id: 9,
    semantic_domain_id: 8,
    template_text: '请生成 LogicForm',
    status: 'active',
  })
  await api.deletePromptTemplate(6)
  await api.confirmSqlExecution({
    question: '确认执行 SQL',
    agent_id: 1,
    datasource_id: 5,
    session_id: 'session-confirm',
    trace_id: 'trace-confirm',
    sql: 'SELECT 1',
  })
  await api.updateDatasource(5, { name: '编辑后数据源' })
  await api.deleteDatasource(5)
  await api.fetchDatasourceSchema(5)
  await api.collectSchema(5, ['orders'])
  await api.uncollectSchema(5, ['orders'])
  await api.fetchDatasourceRemoteTables(5)
  await api.fetchDatasourceTableSummaries(5)
  await api.fetchDatasourceTableDetail(5, 7)
  await api.submitFeedback({
    agent_id: 1,
    session_id: 'session-1',
    trace_id: 'trace-1',
    rating: 'negative',
    comment: '口径不对',
    payload: { question: '前五呢' },
  })
  await api.fetchAllSemanticDomains()
  await api.upsertSemanticDomain({
    id: 8,
    agent_id: 1,
    datasource_id: 5,
    domain_key: 'loan_risk',
    name: '贷款风控',
    description: '',
    status: 'active',
  })
  await api.deleteSemanticDomain(8)
  await api.fetchSemanticSnapshot(8, 3)
  await api.diffSemanticSnapshot(8, 3)
  await api.rollbackSemanticSnapshot(8, 3)
  await api.deleteSemanticAsset(8, 'metric', 11)

  assert.deepEqual(axiosCalls.slice(0, 25), [
    ['put', '/agent/3', {
      name: '编辑后智能体',
      description: '',
      chat_model_config_id: 1,
      embedding_model_config_id: 2,
      semantic_domain_id: 6,
      datasource_ids: [5],
    }],
    ['delete', '/agent/3'],
    ['get', '/model-config/list'],
    ['post', '/model-config/create', { name: 'chat', model_type: 'chat', provider: 'ollama', base_url: '/v1', model_name: 'qwen3', api_key_enabled: false, status: 'active' }],
    ['post', '/model-config/9/test', undefined],
    ['get', '/prompt/list'],
    ['post', '/prompt/templates', {
      prompt_key: 'nl2lf_generate.system',
      name: '贷款 LogicForm 模板',
      description: '',
      agent_id: 1,
      model_config_id: 9,
      semantic_domain_id: 8,
      template_text: '请生成 LogicForm',
      status: 'active',
    }],
    ['delete', '/prompt/templates/6'],
    ['post', '/chat/confirm-sql', {
      question: '确认执行 SQL',
      agent_id: 1,
      datasource_id: 5,
      session_id: 'session-confirm',
      trace_id: 'trace-confirm',
      sql: 'SELECT 1',
    }],
    ['put', '/datasource/5', { name: '编辑后数据源' }],
    ['delete', '/datasource/5'],
    ['get', '/datasource/5/schema'],
    ['post', '/datasource/5/collect-schema', { table_names: ['orders'] }],
    ['post', '/datasource/5/uncollect-schema', { table_names: ['orders'] }],
    ['get', '/datasource/5/remote-tables'],
    ['get', '/datasource/5/schema/tables'],
    ['get', '/datasource/5/schema/tables/7'],
    ['post', '/feedback', {
      agent_id: 1,
      session_id: 'session-1',
      trace_id: 'trace-1',
      rating: 'negative',
      comment: '口径不对',
      payload: { question: '前五呢' },
    }],
    ['get', '/semantic/domains/all'],
    ['post', '/semantic/domains', {
      id: 8,
      agent_id: 1,
      datasource_id: 5,
      domain_key: 'loan_risk',
      name: '贷款风控',
      description: '',
      status: 'active',
    }],
    ['delete', '/semantic/domains/8'],
    ['get', '/semantic/domains/8/snapshots/3'],
    ['get', '/semantic/domains/8/snapshots/3/diff'],
    ['post', '/semantic/domains/8/snapshots/3/rollback', undefined],
    ['delete', '/semantic/assets/8/metric/11'],
  ])
}

assert.ok(
  source.includes('enable_low_confidence_clarification?: boolean'),
  'ChatRequest should expose the low-confidence clarification switch',
)

{
  const events = []
  globalThis.fetch = async () => ({
    ok: false,
    status: 500,
    body: {
      getReader() {
        throw new Error('body should not be read for failed response')
      },
    },
  })

  api.sendMessageStream({ question: 'x' }, event => events.push(event))
  await new Promise(resolve => setTimeout(resolve, 0))

  assert.deepEqual(events, [
    { event: 'error', data: { message: '请求失败: 500' } },
  ])
}

{
  const events = []
  globalThis.fetch = async () => {
    throw new Error('network down')
  }

  api.sendMessageStream({ question: 'x' }, event => events.push(event))
  await new Promise(resolve => setTimeout(resolve, 0))

  assert.deepEqual(events, [
    { event: 'error', data: { message: '网络连接失败' } },
  ])
}
