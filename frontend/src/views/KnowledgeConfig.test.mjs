import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./KnowledgeConfig.vue', import.meta.url), 'utf8')

for (const [key, label] of [
  ['application_count', '申请笔数'],
  ['application_product_type', '申请产品类型'],
  ['application_region', '申请地区'],
  ['application_risk_grade', '申请风险等级'],
]) {
  assert.ok(
    source.includes(`${key}: '${label}'`),
    `KnowledgeConfig should label ${key} as ${label}`,
  )
}

assert.ok(
  source.includes("loan_application_indicator: '贷款申请指标表'"),
  'KnowledgeConfig should label loan_application_indicator in Chinese',
)

for (const [key, label] of [
  ['application_product_type', '申请产品类型'],
  ['application_region', '申请地区'],
  ['application_risk_grade', '申请风险等级'],
]) {
  assert.ok(
    source.includes(`${key}: '${label}'`),
    `KnowledgeConfig should label mapping column ${key} as ${label}`,
  )
}
