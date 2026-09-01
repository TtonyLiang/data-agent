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
    source.includes('overflow-wrap: anywhere') &&
    source.includes('@media (max-width: 760px)') &&
    source.includes('grid-template-columns: repeat(2, minmax(0, 1fr))'),
  'workbench should use a height-safe dense desktop layout with a narrow-screen fallback',
)

assert.ok(
  !source.includes('<el-card') &&
    source.includes('class="metric-strip"') &&
    source.includes('class="table-section"') &&
    source.includes('class="version-record"'),
  'operational workspace should avoid nested cards and use flat sections and record rows',
)
