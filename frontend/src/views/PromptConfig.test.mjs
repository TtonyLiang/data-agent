import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./PromptConfig.vue', import.meta.url), 'utf8')

assert.ok(
  source.includes('Prompt 配置') && source.includes('fetchPromptTemplates'),
  'PromptConfig should expose a prompt template management page',
)

assert.ok(
  source.includes('semantic_enhance.system') &&
    source.includes('nl2lf_generate.system') &&
    source.includes('nl2sql_fallback.system'),
  'PromptConfig should cover the prompt keys currently used by model-backed nodes',
)

assert.ok(
  source.includes('fetchAgents') && source.includes('fetchModelConfigs') && source.includes('fetchAllSemanticDomains'),
  'PromptConfig should allow scoping templates by agent, model config, and semantic domain',
)

assert.ok(
  source.includes('openDetail(row)') && source.includes('openEdit(row)') && source.includes('handleDelete(row)'),
  'PromptConfig should provide detail, edit, and delete actions',
)
