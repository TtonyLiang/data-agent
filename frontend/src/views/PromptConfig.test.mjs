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
    source.includes('nl2sql_fallback.system') &&
    source.includes('phase3_python_generate.system') &&
    source.includes('phase3_python_generate.user') &&
    source.includes('phase3_report_generator.system') &&
    source.includes('phase3_report_generator.user'),
  'PromptConfig should cover all default prompt keys exposed by the agent catalog',
)

assert.ok(
  source.includes('fetchPromptCatalog') && source.includes('promptCatalog') && source.includes('defaultForm(promptKey'),
  'PromptConfig should load default prompt catalog and prefill new templates from it',
)

assert.ok(
  source.includes('fetchAgents') && source.includes('fetchModelConfigs') && source.includes('fetchAllSemanticDomains'),
  'PromptConfig should allow scoping templates by agent, model config, and semantic domain',
)

assert.ok(
  source.includes('openDetail(row)') && source.includes('openEdit(row)') && source.includes('handleDelete(row)'),
  'PromptConfig should provide detail, edit, and delete actions',
)

assert.ok(
  source.includes('embedded-toolbar') && source.includes('还没有 Prompt 模板') && source.includes('新增模板'),
  'PromptConfig should remain usable when embedded in SystemParameterConfig',
)
