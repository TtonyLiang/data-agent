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
  source.includes('msg.report_payload ? reportDisplayTitle(msg.report_payload) : panelResultTitle(msg)'),
  'ChatView should switch final answer cards to inline report rendering when a report payload exists',
)

assert.ok(
  source.includes('reportBodyBlocks(msg.report_payload)'),
  'ChatView should render report body blocks directly inside the final answer card',
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
  source.includes('表格只渲染当前页') && source.includes('导出会保留完整结果和全部字段'),
  'ChatView should make lazy page rendering and full-result export semantics explicit',
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
  source.includes('正在理解问题并补全业务口径') && source.includes('panelStepSummary(step)'),
  'ChatView should keep the semantic enhancement lead stable while rendering progress separately',
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

assert.ok(
  source.includes('reportDisplayTitle') && source.includes('humanizeReportTitle'),
  'ChatView should render human-readable report titles instead of raw metric/dimension keys',
)

assert.ok(
  source.includes("msg.sql_result && msg.sql_result.length > 0 && !msg.report_payload"),
  'ChatView should hide duplicate inline result preview when a deep analysis report already exists',
)

assert.ok(
  source.includes('inlineMarkdownParts') && source.includes('stripInlineMarkdown'),
  'ChatView should render inline markdown safely without showing raw ** markers',
)

assert.ok(
  source.includes('const InlineMarkdown = defineComponent') &&
    source.includes('<InlineMarkdown :text="item" />') &&
    !source.includes('reportAnalysisSummary(expandedReport)" :key="item">{{ item }}'),
  'ChatView should render structured report list items through inline markdown parsing',
)

assert.ok(
  source.includes('<InlineMarkdown :text="String(cell ?? \'\')" />') &&
    source.includes('<InlineMarkdown :text="formatReportValue(row[column])" />'),
  'ChatView should render report table cells through inline markdown parsing',
)

assert.ok(
  source.includes('chartFromEchartsOption') && source.includes('report-md-chart-card'),
  'ChatView should convert ECharts report code blocks into visible chart cards',
)

assert.ok(
  source.includes('looksLikeRawEchartsJson') &&
    source.includes('collectRawEchartsJson') &&
    source.includes('hasEquivalentChartBlock'),
  'ChatView should consume raw ECharts JSON in report markdown instead of rendering it as text',
)

assert.ok(
  source.includes('normalizeChartKind') && source.includes('buildReportEchartsOption') && source.includes('prettifySeries'),
  'ChatView should honor backend-declared chart kinds and render report charts through ECharts',
)

assert.ok(
  source.includes("import * as echarts from 'echarts/core'") &&
    source.includes('echarts.use([') &&
    source.includes('<ReportEChart :chart='),
  'ChatView should use tree-shaken ECharts instead of hand-written report SVG charts',
)

assert.ok(
  !source.includes('由报告中的 ECharts 配置自动渲染'),
  'ChatView should not show internal ECharts auto-render helper text',
)

assert.ok(
  source.includes('Math.max(toFiniteNumber(isPlainObject(base.grid) ? base.grid.top : undefined) || 0, 46)') &&
    source.includes('nameGap: Math.max(toFiniteNumber(base.nameGap) || 0, 18)'),
  'ChatView should reserve enough top spacing for complex ECharts axis names',
)

assert.ok(
  source.includes('分析过程摘要') && source.includes('reportAnalysisSummary') && !source.includes('附录：Python 分析结果'),
  'ChatView should show a business-facing analysis summary instead of raw Python JSON appendix',
)

assert.ok(
  source.includes("continue: '续跑'") &&
    source.includes("refine: '细化'") &&
    source.includes("retry: '重试'") &&
    source.includes("analyze: '结果分析'"),
  'ChatView should label persistent task turn modes in the answer badge area',
)

assert.ok(
  source.includes('复用 {{ msg.reused_artifacts.length }} 项上下文') &&
    source.includes('上下文已刷新'),
  'ChatView should show compact reuse and context invalidation badges',
)

assert.ok(
  source.includes("handleSend('retry')") && source.includes('turn_mode: turnMode'),
  'ChatView should request retry mode when the user reruns the latest question',
)

assert.ok(
  source.includes('task_id: item.task_id') &&
    source.includes('turn_id: item.turn_id') &&
    source.includes('turn_mode: item.turn_mode') &&
    source.includes('task_status: item.task_status') &&
    source.includes('reused_artifacts: item.reused_artifacts') &&
    source.includes('invalidated_artifacts: item.invalidated_artifacts') &&
    source.includes('context_invalidated: item.context_invalidated'),
  'ChatView should preserve all task metadata when rebuilding messages from history',
)
