import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./ChatView.vue', import.meta.url), 'utf8')

assert.ok(!source.includes('v-html'), 'ChatView should not render chat content with v-html')

assert.match(
  source,
  /onUnmounted\(\(\) => \{\s*cancelActiveStream\(\)/s,
  'ChatView should abort the active stream when the component unmounts',
)

assert.ok(
  source.includes('answerSummaryLines(msg)'),
  'ChatView should render final answers through structured summary lines',
)

assert.ok(
  source.includes('cleanAnswerContent'),
  'ChatView should strip legacy SQL/markdown table text from final answers',
)
