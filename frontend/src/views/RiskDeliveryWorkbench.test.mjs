import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./RiskDeliveryWorkbench.vue', import.meta.url), 'utf8')

assert.ok(
  source.includes('<h2>风险与报告交付</h2>') &&
    source.includes('v-model="domainId"') &&
    source.includes('fetchOntologyDomains') &&
    source.includes('fetchOntologyObjects'),
  'workbench should expose the risk delivery title and domain-scoped ontology context',
)

for (const metric of ['待处理风险', '高风险', '待复核', '报告数', '审计事件']) {
  assert.ok(source.includes(metric), `workbench should include the ${metric} metric`)
}

for (const tab of ['风险事项', '报告版本', '决策审计']) {
  assert.ok(source.includes(`label="${tab}"`), `workbench should include the ${tab} tab`)
}

assert.ok(
  source.includes('v-model="riskStatusFilter"') &&
    source.includes('v-model="riskSeverityFilter"') &&
    source.includes('filteredRiskIssues') &&
    source.includes('@row-click="openRiskDetail"') &&
    source.includes('v-model="riskDetailDrawer"') &&
    !source.includes('@expand-change="handleRiskExpand"') &&
    !source.includes('<el-table-column type="expand"'),
  'risk table should support status/severity filters and open issue details from a row click',
)

assert.ok(
  source.includes('class="page-error-row"') &&
    source.includes('class="page-retry-button"') &&
    source.includes('@click="retryPageLoad"') &&
    source.includes('class="table-empty"') &&
    source.includes('报告交付') &&
    source.includes('决策审计事件') &&
    source.includes('@row-click="openReportVersions"') &&
    source.includes(':row-class-name="reportRowClassName"'),
  'workbench should expose retryable errors, actionable empty states, and report detail navigation',
)

assert.ok(
    source.includes('证据链') &&
    source.includes('人工复核') &&
    source.includes('class="risk-detail-drawer"') &&
    source.includes('class="risk-detail-overview"') &&
    source.includes('class="drawer-detail-section"') &&
    source.includes('evidenceSummaryItems(item)') &&
    source.includes('evidenceSourceLabel(item)') &&
    !source.includes('<pre class="detail-json">{{ formatSnapshot(field(item, \'content\')) }}</pre>') &&
    source.includes('openEvidenceDialog') &&
    source.includes('openReviewDialog') &&
    source.includes('fetchRiskIssueDetail(domainId.value, id)') &&
    source.includes('addRiskEvidence(domainId.value, issueId(selectedIssue.value)') &&
    source.includes('submitRiskReview(domainId.value, issueId(selectedIssue.value)') &&
    source.includes('function openRiskDetail(row: RiskIssue)') &&
    source.includes('riskDetailDrawer.value = true'),
  'risk detail drawer should load evidence and reviews and expose both write workflows',
)

assert.ok(
  source.includes('label="风险依据"') &&
    source.includes("{ label: '分类'") &&
    source.includes("{ label: '规则'") &&
    source.includes("{ label: '检测值'") &&
    source.includes('riskCategoryLabel') &&
    source.includes('riskRuleLabel') &&
    source.includes('riskDetectedValueSummary'),
  'risk basis should present category, rule, and detected values as readable business summaries',
)

assert.ok(
  source.includes(':row-class-name="riskRowClassName"') &&
    source.includes("'risk-title-cell'") &&
    source.includes("'severity-tag'") &&
    source.includes("'status-tag'") &&
    source.includes('class="count-pair"') &&
    source.includes('class="table-time"') &&
    source.includes('formatDateTime, isDateTimeValue') &&
    source.includes("if (typeof value === 'string' && isDateTimeValue(value)) return formatDateTime(value)"),
  'risk rows should distinguish primary risk signals from compact count and second-level time fields',
)

assert.ok(
  source.includes("start_review: '开始复核'") &&
    source.includes("{ value: 'start_review', label: '开始复核'") &&
    source.includes('canReviewIssue(row)') &&
    source.includes('风险事项创建人不能') === false &&
    source.includes("numberField(row, 'created_by') === user.id") &&
    source.includes('const canFinalize = computed(() => isAdmin())') &&
    source.includes('v-if="canFinalize"'),
  'review controls should expose a reachable in-review state, assigned-reviewer gating, and admin-only finalization',
)

assert.ok(
  source.includes('新建风险事项') &&
    source.includes('domain_id: domainId.value') &&
    source.includes('subject_object_id: riskForm.subject_object_id') &&
    source.includes('issue_key: riskForm.issue_key.trim()') &&
    source.includes('category: riskForm.category.trim()') &&
    source.includes('rule_key: riskForm.rule_key.trim() || null') &&
    source.includes('detected_value: detectedValue') &&
    source.includes('expected_value: expectedValue') &&
    source.includes('source_context: sourceContext') &&
    source.includes('assignee: riskForm.assignee.trim() || null'),
  'risk creation dialog should submit complete snake_case business fields',
)

assert.ok(
  source.includes('evidence_type: evidenceForm.evidence_type') &&
    source.includes('description: evidenceForm.description.trim()') &&
    source.includes('source_ref: evidenceForm.source_ref.trim() || null') &&
    source.includes('content,') &&
    source.includes('trace_id: evidenceForm.trace_id.trim() || null') &&
    source.includes('action: reviewForm.action') &&
    source.includes('comment: reviewForm.comment.trim()') &&
    source.includes("expected_version: numberField(selectedIssue.value, 'version') || null"),
  'evidence and review dialogs should use the backend evidence and optimistic-review contracts',
)

assert.ok(
  source.includes('新建报告并创建 V1') &&
    source.includes('createRiskReport(domainId.value') &&
    source.includes('report_key: reportForm.report_key.trim()') &&
    source.includes('name: reportForm.name.trim()') &&
    source.includes('report_type: reportForm.report_type') &&
    source.includes('period_start: reportForm.period_start') &&
    source.includes('period_end: reportForm.period_end') &&
    source.includes('issue_ids: [...reportForm.issue_ids]') &&
    source.includes('snapshot,') &&
    source.includes('markdown: reportForm.markdown'),
  'report creation should create V1 with period and snapshot fields using snake_case payloads',
)

assert.ok(
    source.includes('createRiskReportVersion(domainId.value, reportId(selectedReport.value)') &&
    source.includes('issue_ids: [...versionForm.issue_ids]') &&
    source.includes('markdown: versionForm.markdown') &&
    source.includes("expected_current_version: numberField(selectedReport.value, 'current_version') || null") &&
    source.includes('await finalizeRiskReport(') &&
    source.includes("numberField(row, 'current_version') || null") &&
    source.includes('fetchRiskReportVersions(domainId.value, reportId(row))') &&
    source.includes('快照摘要') &&
    source.includes('Ontology release') &&
    source.includes('快照哈希'),
  'report workflow should create versions, finalize reports, and display snapshot provenance',
)

assert.ok(
  source.includes('class="report-reading-panel"') &&
    source.includes('aria-label="业务阅读版"') &&
    source.includes('业务阅读版') &&
    source.includes('报告状态') &&
    source.includes('报告期间') &&
    source.includes('风险事项') &&
    source.includes('当前版本') &&
    source.includes('风险概览') &&
    source.includes('reportVersionIssues(version)') &&
    source.includes('reportIssueTitle(issue)') &&
    source.includes('reportIssueSeverity(issue)') &&
    source.includes('reportIssueStatus(issue)') &&
    source.includes('reportIssueObjectLabel(issue)') &&
    source.includes('reportIssueDetectedValue(issue)') &&
    source.includes('reportIssueEvidenceSummary(issue)') &&
    source.includes('reportIssueReviewSummary(issue)') &&
    source.includes('function reportVersionFallbackSummary(version') &&
    source.includes('暂无纳入的风险事项'),
  'report versions should default to a readable business summary with graceful issue fallbacks',
)

assert.ok(
  source.includes('class="technical-trace-collapse"') &&
    source.includes('技术追溯（原始 JSON、哈希与版本字段）') &&
    source.includes('Ontology release') &&
    source.includes('创建人') &&
    source.includes('快照哈希') &&
    source.includes('原始 snapshot JSON') &&
    source.includes('原始 Markdown') &&
    source.includes('技术字段') &&
    source.includes('function formatTechnicalFields(version'),
  'technical provenance should be available in a secondary collapsed section',
)

const reportVersionIssuesSource = source.slice(
  source.indexOf('function reportVersionIssues'),
  source.indexOf('function reportIssueTitle'),
)

assert.ok(
  source.includes("const REPORT_ISSUE_SNAPSHOT_STATE = '__report_snapshot_state'") &&
    reportVersionIssuesSource.includes('if (hasSnapshotIssueDetails(snapshotIssue))') &&
    reportVersionIssuesSource.includes("withReportIssueSnapshotState(snapshotIssue, 'snapshot')") &&
    reportVersionIssuesSource.includes("withReportIssueSnapshotState({ ...liveIssue, ...snapshotIssue }, 'live_supplement')") &&
    !reportVersionIssuesSource.includes('{ ...(liveById.get') &&
    source.includes("if (state === 'live_supplement') return '未固化信息'") &&
    source.includes("if (state === 'missing') return '快照缺失'") &&
    source.includes("return '当前快照'") &&
    source.includes('不属于不可变报告快照'),
  'immutable report issues should keep snapshot fields authoritative and label live-only supplements',
)

const snapshotSummarySource = source.slice(
  source.indexOf('function snapshotSummaryValue'),
  source.indexOf('type VersionMarkdownBlock'),
)

assert.ok(
  snapshotSummarySource.includes("const contextValue = field(snapshot, 'context')") &&
    snapshotSummarySource.includes("textField(snapshot, 'change_summary', 'changeSummary', 'summary', 'stage')") &&
    snapshotSummarySource.includes("textField(context, 'change_summary', 'changeSummary', 'summary', 'stage')") &&
    source.includes('snapshotSummaryValue(version)'),
  'snapshot summaries should read root fields first and then the backend context payload',
)

assert.ok(
  source.includes('v-if="isCurrentReportVersion(version)"') &&
    source.includes('<el-tag v-else type="info" size="small" effect="plain">不可变版本</el-tag>') &&
    source.includes("{{ isCurrentReportVersion(version) ? '当前版本' : '版本号' }}") &&
    source.includes("const currentVersion = numberField(selectedReport.value, 'current_version')") &&
    source.includes('versionNumber === currentVersion'),
  'only the selected report current version should receive the current-version label',
)

assert.ok(
  source.includes('reportVersionMarkdownBlocks(version)') &&
    source.includes('inlineMarkdownParts(block.text)') &&
    source.includes("block.type === 'heading'") &&
    source.includes("block.type === 'subheading'") &&
    source.includes("block.type === 'paragraph'") &&
    source.includes("block.type === 'list'") &&
    source.includes('<ol v-else-if="block.type === \'list\' && block.ordered">') &&
    source.includes('<ul v-else-if="block.type === \'list\'">') &&
    source.includes("| { type: 'list'; ordered: boolean; items: string[] }") &&
    source.includes("blocks.push({ type: 'list', ordered: Boolean(listOrdered), items: [...listItems] })") &&
    source.includes("block.type === 'table'") &&
    source.includes("block.type === 'code'") &&
    source.includes('function parseVersionMarkdownTable(lines') &&
    source.includes('function isVersionMarkdownTableLine(line') &&
    !source.includes('v-html'),
  'report markdown should use safe block rendering for headings, text, lists, tables, and code',
)

assert.ok(
  source.includes('v-for="{ version, issues, markdownBlocks, issueOverviewLabel, fallbackSummary } in reportVersionViews"') &&
    source.includes('const reportVersionViews = computed(() => reportVersions.value.map((version) => {') &&
    source.includes('@change="handleTechnicalTraceChange(version, $event)"') &&
    source.includes('<template v-if="isTechnicalTraceExpanded(version)">') &&
    source.includes('const expandedTechnicalVersionKeys = ref<string[]>([])') &&
    !source.includes('reportVersionIssues(version).length') &&
    !source.includes('v-if="reportVersionMarkdownBlocks(version).length"'),
  'version cards should precompute business projections and mount technical trace content only while expanded',
)

assert.ok(
  source.includes('class="form-help"') &&
    source.includes('技术追溯信息，普通阅读者无需填写或查看') &&
    source.includes('V1 快照（JSON）') &&
    source.includes('版本快照（JSON）'),
  'technical JSON inputs should explain that they are for traceability rather than ordinary reading',
)

for (const auditColumn of ['事件类型', '实体', 'Release', '执行人', '时间', '事件哈希']) {
  assert.ok(source.includes(`label="${auditColumn}"`), `audit table should include the ${auditColumn} column`)
}

assert.ok(
  source.includes('校验审计链') &&
    source.includes('fetchDecisionAuditEvents(id)') &&
    source.includes('verifyDecisionAuditChain(domainId.value)') &&
    source.includes("numberField(row, 'sequence_no', 'id')") &&
    source.includes("textFieldOr(row, '-', 'actor_name', 'username', 'actor')") &&
    source.includes('auditVerificationValid') &&
    source.includes('auditVerificationMessage'),
  'audit workspace should load events and show audit-chain verification results',
)

assert.ok(
  source.includes('riskLoading') &&
    source.includes('reportLoading') &&
    source.includes('auditLoading') &&
    source.includes('savingRisk') &&
    source.includes('savingEvidence') &&
    source.includes('savingReview') &&
    source.includes('savingReport') &&
    source.includes('savingVersion') &&
    source.includes('pageError') &&
    source.includes('riskError') &&
    source.includes('reportError') &&
    source.includes('auditError'),
  'every major read and write path should expose explicit loading and error state',
)

assert.ok(
  source.includes('.risk-delivery-page {') &&
    source.includes('max-width: var(--wq-page-max-width)') &&
    source.includes('height: 100%;') &&
    source.includes('min-height: 0;') &&
    source.includes('.metric-strip {') &&
    source.includes('grid-template-columns: repeat(5, minmax(120px, 1fr))') &&
    source.includes('.workspace-tabs :deep(.el-tabs__content)') &&
    source.includes('.table-section {') &&
    source.includes('minmax(0, 1fr)') &&
    source.includes('.risk-detail-drawer {') &&
    source.includes('.risk-detail-facts {') &&
    source.includes('.evidence-summary {') &&
    source.includes('.review-section .detail-list::before') &&
    source.includes('.table-action-btn.is-evidence') &&
    source.includes('.table-action-btn.is-review') &&
    source.includes('.table-action-btn.is-finalize') &&
    source.includes('--risk-accent: #175cd3') &&
    source.includes('.section-heading-copy') &&
    source.includes('.filter-group') &&
    source.includes('.metric-item.has-value') &&
    source.includes('.workbench-table :deep(.el-table__header-wrapper th.el-table__cell)') &&
    source.includes('.table-empty') &&
    source.includes('.evidence-record') &&
    source.includes('.review-record {') &&
    source.includes('.report-table :deep(.el-table__body tr) { cursor: pointer; }') &&
    source.includes('min-width: 920px;') &&
    source.includes('overflow-wrap: anywhere') &&
    source.includes('@media (max-width: 760px)') &&
    source.includes('grid-template-columns: repeat(2, minmax(0, 1fr))'),
  'workbench should use a hierarchy-first dense layout with actionable states and a narrow-screen fallback',
)

assert.ok(
  !source.includes('<el-card') &&
    source.includes('class="metric-strip"') &&
    source.includes('class="table-section"') &&
    source.includes('class="version-record"'),
  'operational workspace should avoid nested cards and use flat sections and record rows',
)
