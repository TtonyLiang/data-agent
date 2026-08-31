import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./ModelConfig.vue', import.meta.url), 'utf8')

assert.ok(
  source.includes("const MASKED_API_KEY = '********'"),
  'ModelConfig should use a masked API key sentinel for edit echo',
)

assert.ok(
  source.includes("'api_key_configured' in config ? Boolean(config.api_key_configured) : Boolean(config.api_key_enabled)"),
  'ModelConfig should use the explicit configured flag when the backend provides it',
)

assert.ok(
  source.includes('已配置 Key；直接保存会保留原 Key，输入新 Key 会覆盖。'),
  'ModelConfig should explain that saving without changing the key preserves it',
)

assert.ok(
  source.includes('function modelConfigPayload()'),
  'ModelConfig should normalize the edit payload before submit',
)

assert.ok(
  source.includes('payload.api_key = null'),
  'ModelConfig should not submit the masked sentinel as a real API key',
)

assert.ok(
  source.includes("return 'Key 缺失'"),
  'ModelConfig should warn when API key is enabled but the stored key is missing',
)

assert.ok(
  source.includes('testModelConfig') && source.includes('handleTest'),
  'ModelConfig should expose a model connection test action',
)

assert.ok(
  source.includes('api_key_expires_at') && source.includes('即将过期'),
  'ModelConfig should expose API key expiration reminders',
)

assert.ok(
  source.includes('format="YYYY-MM-DD HH:mm:ss"') && source.includes('formatDateTime(detailConfig.api_key_expires_at)'),
  'ModelConfig should display API key expiration timestamps only to seconds',
)
