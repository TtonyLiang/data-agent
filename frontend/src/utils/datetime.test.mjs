import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { formatDateTime, isDateTimeField, isDateTimeValue } from './datetime.ts'

assert.equal(formatDateTime('2026-08-31T10:24:03.185396'), '2026-08-31 10:24:03')
assert.equal(formatDateTime('2026-08-31 10:24:03'), '2026-08-31 10:24:03')
assert.equal(formatDateTime(null), '-')
assert.equal(formatDateTime('not-a-date'), 'not-a-date')
assert.equal(isDateTimeField('updated_at'), true)
assert.equal(isDateTimeField('apply_date'), false)
assert.equal(isDateTimeValue('2026-08-31T02:24:03.185396+00:00'), true)
assert.equal(isDateTimeValue('2026-08-31'), false)

for (const [path, expected] of [
  ['../views/AgentList.vue', 'formatDateTime(row.created_at)'],
  ['../views/UserManagement.vue', 'formatDateTime(row.last_login_at)'],
  ['../views/ModelConfig.vue', 'formatDateTime(detailConfig.api_key_expires_at)'],
  ['../views/KnowledgeConfig.vue', 'formatDateTime(item.created_at)'],
  ['../views/OntologyWorkbench.vue', 'formatDateTime(row.created_at)'],
  ['../views/ChatView.vue', 'formatDateTime(report.generated_at)'],
]) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  assert.ok(source.includes(expected), `${path} should use the shared date-time formatter`)
}
