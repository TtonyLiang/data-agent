import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./PromptConfig.vue', import.meta.url), 'utf8')

assert.ok(
  source.includes('提示词配置') && source.includes('fetchPromptTemplates'),
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
  source.includes('embedded-toolbar') && source.includes('还没有提示词模板') && source.includes('新增模板'),
  'PromptConfig should remain usable when embedded in SystemParameterConfig',
)

assert.ok(
  source.includes('业务领域和模型维护企业模型提示词') &&
    source.includes('验证智能体范围仅用于兼容覆盖') &&
    source.includes('业务领域：') &&
    source.includes('label="业务领域"') &&
    source.includes('验证智能体覆盖') &&
    !source.includes('label="语义层"') &&
    !source.includes('语义层：'),
  'visible Prompt terminology should align semantic assets with business domains and treat Agent scope as compatibility only',
)

assert.ok(
  source.includes('agentScopedInteractionOutputPromptKeys') &&
    source.includes('businessSemanticPromptKeys') &&
    source.includes(':disabled="!selectedPromptAllowsAgentScope"') &&
    source.includes('业务语义关键节点不可按智能体覆盖') &&
    source.includes('只允许按业务领域、模型或全局配置') &&
    source.includes('历史智能体覆盖：运行时忽略'),
  'business-semantic prompts should disable Agent overrides and explain how legacy rows are handled',
)
