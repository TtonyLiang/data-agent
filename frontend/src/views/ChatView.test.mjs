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
  source.includes('shouldShowAnswerCard(msg)'),
  'ChatView should hide the final answer card while an assistant message is still streaming',
)

assert.ok(
  !source.includes('正在整理结论...'),
  'ChatView should not show a final-answer placeholder during the analysis process',
)

assert.ok(
  source.includes('cleanAnswerContent'),
  'ChatView should strip legacy SQL/markdown table text from final answers',
)

assert.ok(
  source.includes('el-pagination'),
  'ChatView should provide pagination for result browsing',
)

assert.ok(
  source.includes('toggleErrorDetail'),
  'ChatView should allow expanding technical error detail',
)

assert.ok(
  source.includes('class="analysis-flow"'),
  'ChatView should render the query process as a single narrative analysis flow',
)

assert.ok(
  source.includes("step.node === 'semantic_enhance'") && source.includes('语义增强'),
  'ChatView should render semantic enhancement as a first-class analysis step',
)

assert.ok(
  source.includes('analysisStepIndex(step, stepIndex)'),
  'ChatView should derive visible analysis step numbers from the rendered narrative order',
)

assert.ok(
  !source.includes("if (step.node === 'semantic_runtime_recall') return '3'"),
  'ChatView should not hardcode semantic runtime as step 3 because persisted traces may omit newer nodes',
)

assert.ok(
  source.includes('展开分析过程') && !source.includes('展开技术细节'),
  'ChatView should collapse completed reasoning as analysis process, not as a separate technical-detail panel',
)

assert.ok(
  source.includes('reportStreamText(step)') && source.includes('pythonCodeText(step)'),
  'ChatView should stream Phase 3 script, analysis JSON, and report content inline',
)
