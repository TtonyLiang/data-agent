<template>
  <div class="risk-delivery-page">
    <header class="page-toolbar">
      <div class="title-group">
        <h2>风险与报告交付</h2>
        <p v-if="currentDomain">{{ currentDomain.name }} · {{ currentDomain.domain_key || `domain-${currentDomain.id}` }}</p>
        <p v-else>连接风险事项、证据、人工复核、报告版本与决策审计</p>
      </div>
      <div class="toolbar-actions">
        <el-select
          v-model="domainId"
          class="domain-select"
          placeholder="选择领域"
          :loading="domainLoading"
          :disabled="domainLoading || domains.length === 0"
        >
          <el-option
            v-for="domain in domains"
            :key="domain.id"
            :label="domain.name"
            :value="domain.id"
          />
        </el-select>
        <el-button
          :icon="Refresh"
          :loading="workspaceLoading"
          :disabled="!domainId"
          aria-label="刷新工作台"
          @click="refreshWorkspace"
        >
          刷新
        </el-button>
      </div>
    </header>

    <div v-if="pageError" class="page-error-row">
      <el-alert
        class="page-error"
        type="error"
        :title="pageError"
        show-icon
        :closable="false"
      />
      <el-button class="page-retry-button" :icon="Refresh" @click="retryPageLoad">重试</el-button>
    </div>

    <el-empty
      v-if="!domainLoading && domains.length === 0"
      description="暂无可用领域，请先完成领域和本体配置"
    >
      <el-button type="primary" :icon="Refresh" @click="loadDomains">重新加载</el-button>
    </el-empty>

    <template v-else-if="domainId">
      <section class="metric-strip" aria-label="风险交付指标">
        <div v-for="metric in metrics" :key="metric.label" :class="['metric-item', `tone-${metric.tone}`, metric.value > 0 ? 'has-value' : 'is-empty']">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <el-icon><component :is="metric.icon" /></el-icon>
        </div>
      </section>

      <el-tabs v-model="activeTab" class="workspace-tabs" @tab-change="handleTabChange">
        <el-tab-pane label="风险事项" name="risks">
          <section class="table-section" v-loading="riskLoading">
            <div class="section-toolbar risk-toolbar">
              <div class="section-heading">
                <div class="section-heading-copy">
                  <strong>风险事项</strong>
                  <span>按严重度和状态优先处理，点击行查看详情</span>
                </div>
                <em>{{ filteredRiskIssues.length }} / {{ riskIssues.length }} 项</em>
              </div>
              <div class="section-actions filter-group">
                <el-select v-model="riskStatusFilter" class="filter-select" aria-label="风险状态筛选">
                  <el-option label="全部状态" value="all" />
                  <el-option v-for="item in riskStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-select v-model="riskSeverityFilter" class="filter-select" aria-label="风险严重度筛选">
                  <el-option label="全部严重度" value="all" />
                  <el-option v-for="item in severityOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-button type="primary" :icon="Plus" @click="openRiskDialog">新建风险事项</el-button>
              </div>
            </div>

            <el-alert
              v-if="riskError"
              class="section-error"
              type="error"
              :title="riskError"
              show-icon
              :closable="false"
            />

            <el-table
              class="workbench-table risk-issues-table"
              :data="filteredRiskIssues"
              row-key="id"
              :row-class-name="riskRowClassName"
              height="100%"
              empty-text="暂无风险事项"
              @row-click="openRiskDetail"
            >
              <template #empty>
                <div class="table-empty">
                  <el-empty :image-size="58" description="暂无风险事项">
                    <el-button type="primary" :icon="Plus" @click="openRiskDialog">新建风险事项</el-button>
                  </el-empty>
                </div>
              </template>
              <el-table-column label="风险事项" min-width="260">
                <template #default="{ row }">
                  <div :class="['primary-cell', 'risk-title-cell', severityClass(textField(row, 'severity'))]">
                    <strong>{{ textFieldOr(row, '未命名风险', 'title', 'name') }}</strong>
                    <div class="primary-meta">
                      <code>{{ textFieldOr(row, `ISSUE-${issueId(row)}`, 'issue_key', 'risk_key') }}</code>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="严重度" width="102">
                <template #default="{ row }">
                  <el-tag :class="['severity-tag', severityClass(textField(row, 'severity'))]" :type="severityType(textField(row, 'severity'))" effect="plain">
                    {{ severityLabel(textField(row, 'severity')) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="112">
                <template #default="{ row }">
                  <el-tag :class="['status-tag', riskStatusClass(textField(row, 'status'))]" :type="riskStatusType(textField(row, 'status'))" effect="plain">
                    {{ riskStatusLabel(textField(row, 'status')) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="关联对象" min-width="180">
                <template #default="{ row }">
                  <div class="object-cell">
                    <strong>{{ issueObjectLabel(row) }}</strong>
                    <span v-if="textField(row, 'subject_type')">{{ textField(row, 'subject_type') }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="风险依据" min-width="300">
                <template #default="{ row }">
                  <div class="risk-basis-cell">
                    <div v-for="item in riskBasisItems(row)" :key="item.label" class="risk-basis-item">
                      <span>{{ item.label }}</span>
                      <strong :class="{ 'is-rule-key': item.label === '规则' }">{{ item.value }}</strong>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="证据 / 复核" width="116" align="center">
                <template #default="{ row }">
                  <div class="count-pair" aria-label="证据和复核数量">
                    <span><b>证</b>{{ numberField(row, 'evidence_count') }}</span>
                    <span><b>复</b>{{ numberField(row, 'review_count') }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="更新时间" width="170">
                <template #default="{ row }"><time class="table-time">{{ formatTime(field(row, 'updated_at', 'created_at')) }}</time></template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="报告版本" name="reports">
          <section class="table-section" v-loading="reportLoading">
            <div class="section-toolbar">
              <div class="section-heading">
                <div class="section-heading-copy">
                  <strong>报告交付</strong>
                  <span>以不可变版本记录风险结论和交付状态</span>
                </div>
                <em>{{ reports.length }} 份</em>
              </div>
              <el-button type="primary" :icon="Plus" @click="openReportDialog">新建报告并创建 V1</el-button>
            </div>

            <el-alert
              v-if="reportError"
              class="section-error"
              type="error"
              :title="reportError"
              show-icon
              :closable="false"
            />

            <el-table class="workbench-table report-table" :data="reports" row-key="id" height="100%" empty-text="暂无报告" :row-class-name="reportRowClassName" @row-click="openReportVersions">
              <template #empty>
                <div class="table-empty">
                  <el-empty :image-size="58" description="暂无报告">
                    <el-button type="primary" :icon="Plus" @click="openReportDialog">新建报告并创建 V1</el-button>
                  </el-empty>
                </div>
              </template>
              <el-table-column label="报告" min-width="270">
                <template #default="{ row }">
                  <div class="primary-cell report-title-cell">
                    <strong>{{ textFieldOr(row, '未命名报告', 'title', 'name') }}</strong>
                    <div class="primary-meta"><code>{{ textFieldOr(row, `REPORT-${reportId(row)}`, 'report_key', 'report_no') }}</code></div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="报告类型" min-width="150">
                <template #default="{ row }">{{ reportTypeLabel(textField(row, 'report_type', 'type')) }}</template>
              </el-table-column>
              <el-table-column label="报告期间" min-width="190">
                <template #default="{ row }"><span class="period-value">{{ reportPeriodLabel(row) }}</span></template>
              </el-table-column>
              <el-table-column label="定稿时间" width="170">
                <template #default="{ row }"><time class="table-time">{{ formatTime(field(row, 'finalized_at')) }}</time></template>
              </el-table-column>
              <el-table-column label="当前版本" width="112" align="center">
                <template #default="{ row }"><span class="version-token">V{{ numberField(row, 'current_version', 'latest_version', 'version_count') || 1 }}</span></template>
              </el-table-column>
              <el-table-column label="状态" width="110">
                <template #default="{ row }">
                  <el-tag :class="['status-tag', `report-${textField(row, 'status')}`]" :type="reportStatusType(textField(row, 'status'))" effect="plain">
                    {{ reportStatusLabel(textField(row, 'status')) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="更新时间" width="170">
                <template #default="{ row }"><time class="table-time">{{ formatTime(field(row, 'updated_at', 'created_at')) }}</time></template>
              </el-table-column>
              <el-table-column label="操作" width="146" fixed="right" align="center" header-align="center">
                <template #default="{ row }">
                  <div class="table-actions">
                    <el-tooltip content="查看版本" placement="top">
                      <el-button class="table-action-btn is-view" text :icon="View" aria-label="查看报告版本" @click.stop="openReportVersions(row)" />
                    </el-tooltip>
                    <el-tooltip content="创建新版本" placement="top">
                      <el-button
                        class="table-action-btn is-version"
                        text
                        type="primary"
                        :icon="DocumentAdd"
                        aria-label="创建报告新版本"
                        :disabled="isFinalReport(row)"
                        @click.stop="openVersionDialog(row)"
                      />
                    </el-tooltip>
                    <el-tooltip v-if="canFinalize" content="定稿" placement="top">
                      <el-button
                        class="table-action-btn is-finalize"
                        text
                        type="success"
                        :icon="CircleCheck"
                        aria-label="定稿报告"
                        :disabled="isFinalReport(row)"
                        @click.stop="handleFinalizeReport(row)"
                      />
                    </el-tooltip>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="决策审计" name="audit">
          <section class="table-section audit-section" v-loading="auditLoading">
            <div class="section-toolbar">
              <div class="section-heading">
                <div class="section-heading-copy">
                  <strong>决策审计事件</strong>
                  <span>记录关键业务动作，哈希字段用于技术追溯</span>
                </div>
                <em>{{ auditEvents.length }} 条</em>
              </div>
              <el-button
                :icon="CircleCheck"
                :loading="auditVerifying"
                @click="handleVerifyAuditChain"
              >
                校验审计链
              </el-button>
            </div>

            <el-alert
              v-if="auditError"
              class="section-error"
              type="error"
              :title="auditError"
              show-icon
              :closable="false"
            />
            <el-alert
              v-if="auditVerifyResult"
              class="audit-result"
              :type="auditVerificationValid ? 'success' : 'error'"
              :title="auditVerificationMessage"
              show-icon
              closable
              @close="auditVerifyResult = null"
            />

            <el-table class="workbench-table audit-table" :data="auditEvents" row-key="id" height="100%" empty-text="暂无审计事件">
              <template #empty>
                <div class="table-empty">
                  <el-empty :image-size="58" description="暂无审计事件">
                    <span class="empty-note">完成风险创建、证据添加或人工复核后，这里会保留可追溯记录</span>
                  </el-empty>
                </div>
              </template>
              <el-table-column label="事件类型" min-width="180">
                <template #default="{ row }">
                  <div :class="['primary-cell', 'audit-event-cell', auditEventClass(textField(row, 'event_type', 'type'))]">
                    <strong>{{ auditEventLabel(textField(row, 'event_type', 'type')) }}</strong>
                    <div class="primary-meta"><code>事件 #{{ numberField(row, 'sequence_no', 'id') }}</code></div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="实体" min-width="220">
                <template #default="{ row }">
                  <div class="secondary-cell audit-entity-cell">
                    <span>{{ textFieldOr(row, '-', 'entity_type', 'aggregate_type') }}</span>
                    <code>{{ textFieldOr(row, '-', 'entity_key', 'entity_id', 'aggregate_id') }}</code>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="Release" width="110">
                <template #default="{ row }"><span class="release-token">{{ releaseLabel(row) }}</span></template>
              </el-table-column>
              <el-table-column label="执行人" min-width="150">
                <template #default="{ row }">{{ textFieldOr(row, '-', 'actor_name', 'username', 'actor') }}</template>
              </el-table-column>
              <el-table-column label="时间" width="180">
                <template #default="{ row }"><time class="table-time">{{ formatTime(field(row, 'created_at', 'occurred_at')) }}</time></template>
              </el-table-column>
              <el-table-column label="事件哈希" min-width="260">
                <template #default="{ row }">
                  <el-tooltip :content="String(field(row, 'event_hash', 'hash') || '-')" placement="top-start">
                    <code class="hash-value">{{ shortHash(field(row, 'event_hash', 'hash'), 24) }}</code>
                  </el-tooltip>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-drawer
      v-model="riskDetailDrawer"
      class="risk-detail-panel"
      :title="`风险事项 · ${selectedIssueTitle}`"
      size="780px"
      append-to-body
      destroy-on-close
    >
      <div class="risk-detail-drawer" v-loading="issueDetailLoadingIds.includes(issueId(selectedIssue))">
        <el-alert
          v-if="selectedIssue && issueDetailErrors[issueId(selectedIssue)]"
          type="error"
          :title="issueDetailErrors[issueId(selectedIssue)]"
          show-icon
          :closable="false"
        />
        <template v-else-if="selectedIssue">
          <section class="risk-detail-overview">
            <div class="risk-detail-heading">
              <div :class="['risk-title-cell', severityClass(textField(selectedIssue, 'severity'))]">
                <strong>{{ selectedIssueTitle }}</strong>
                <code>{{ textFieldOr(selectedIssue, `ISSUE-${issueId(selectedIssue)}`, 'issue_key', 'risk_key') }}</code>
              </div>
              <div class="risk-detail-tags">
                <el-tag :class="['severity-tag', severityClass(textField(selectedIssue, 'severity'))]" :type="severityType(textField(selectedIssue, 'severity'))" effect="plain">
                  {{ severityLabel(textField(selectedIssue, 'severity')) }}
                </el-tag>
                <el-tag :class="['status-tag', riskStatusClass(textField(selectedIssue, 'status'))]" :type="riskStatusType(textField(selectedIssue, 'status'))" effect="plain">
                  {{ riskStatusLabel(textField(selectedIssue, 'status')) }}
                </el-tag>
              </div>
            </div>
            <p v-if="textField(selectedIssue, 'description')" class="risk-detail-description">{{ textField(selectedIssue, 'description') }}</p>
            <dl class="risk-detail-facts">
              <div><dt>关联对象</dt><dd>{{ issueObjectLabel(selectedIssue) }}</dd></div>
              <div><dt>风险分类</dt><dd>{{ riskCategoryLabel(textField(selectedIssue, 'category')) }}</dd></div>
              <div><dt>命中规则</dt><dd>{{ riskRuleLabel(textField(selectedIssue, 'rule_key', 'rule_code')) }}</dd></div>
              <div><dt>检测值</dt><dd>{{ riskDetectedValueSummary(field(selectedIssue, 'detected_value')) }}</dd></div>
              <div><dt>更新时间</dt><dd><time>{{ formatTime(field(selectedIssue, 'updated_at', 'created_at')) }}</time></dd></div>
              <div><dt>当前版本</dt><dd>V{{ numberField(selectedIssue, 'version') || 1 }}</dd></div>
            </dl>
          </section>

          <section class="drawer-detail-section">
            <div class="detail-heading">
              <div>
                <strong>证据链</strong>
                <span>{{ evidenceItems(issueId(selectedIssue)).length }} 条</span>
              </div>
              <el-button class="detail-action is-evidence" size="small" plain :icon="Link" @click="openEvidenceDialog(selectedIssue)">添加证据</el-button>
            </div>
            <div v-if="evidenceItems(issueId(selectedIssue)).length" class="detail-list">
              <article v-for="item in evidenceItems(issueId(selectedIssue))" :key="recordKey(item)" class="detail-record evidence-record">
                <div class="record-line">
                  <strong>{{ textFieldOr(item, '证据', 'title', 'evidence_type') }}</strong>
                  <el-tag size="small" effect="plain">{{ evidenceTypeLabel(textField(item, 'evidence_type', 'type')) }}</el-tag>
                </div>
                <p v-if="textField(item, 'description')">{{ textField(item, 'description') }}</p>
                <div v-if="evidenceSummaryItems(item).length" class="evidence-summary">
                  <div v-for="entry in evidenceSummaryItems(item)" :key="entry.label" class="evidence-summary-item">
                    <span>{{ entry.label }}</span>
                    <strong>{{ entry.value }}</strong>
                  </div>
                </div>
                <div class="record-meta">
                  <span>来源 {{ evidenceSourceLabel(item) }}</span>
                  <span v-if="textField(item, 'trace_id')">追溯 {{ shortHash(field(item, 'trace_id'), 12) }}</span>
                  <span>{{ formatTime(field(item, 'created_at')) }}</span>
                  <code v-if="field(item, 'checksum', 'evidence_hash', 'hash')">{{ shortHash(field(item, 'checksum', 'evidence_hash', 'hash')) }}</code>
                </div>
              </article>
            </div>
            <el-empty v-else :image-size="46" description="尚未添加证据" />
          </section>

          <section class="drawer-detail-section review-section">
            <div class="detail-heading">
              <div>
                <strong>人工复核</strong>
                <span>{{ reviewItems(issueId(selectedIssue)).length }} 条</span>
              </div>
              <el-button v-if="canReviewIssue(selectedIssue)" class="detail-action is-review" size="small" type="primary" plain :icon="Finished" @click="openReviewDialog(selectedIssue)">提交复核</el-button>
            </div>
            <div v-if="reviewItems(issueId(selectedIssue)).length" class="detail-list">
              <article v-for="item in reviewItems(issueId(selectedIssue))" :key="recordKey(item)" :class="['detail-record', 'review-record', riskStatusClass(textField(item, 'after_status', 'status'))]">
                <div class="record-line">
                  <strong>{{ reviewDecisionLabel(textField(item, 'review_action', 'action', 'decision')) }}</strong>
                  <el-tag :class="['status-tag', riskStatusClass(textField(item, 'after_status', 'status'))]" size="small" :type="riskStatusType(textField(item, 'after_status', 'status'))" effect="plain">
                    {{ riskStatusLabel(textField(item, 'after_status', 'status')) }}
                  </el-tag>
                </div>
                <p>{{ textFieldOr(item, '暂无复核意见', 'comment') }}</p>
                <div class="record-meta">
                  <span>{{ textFieldOr(item, '未知复核人', 'reviewer_name', 'reviewer') }}</span>
                  <span>{{ formatTime(field(item, 'created_at')) }}</span>
                  <span>{{ releaseLabel(item) }}</span>
                </div>
              </article>
            </div>
            <el-empty v-else :image-size="46" description="尚无人工复核记录" />
          </section>
        </template>
        <el-empty v-else description="未选择风险事项" />
      </div>
    </el-drawer>

    <el-dialog
      v-model="riskDialog"
      title="新建风险事项"
      width="760px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form :model="riskForm" label-position="top">
        <div class="form-grid two">
          <el-form-item label="风险标题" required>
            <el-input v-model="riskForm.title" placeholder="如 借款人近 30 天逾期次数异常" />
          </el-form-item>
          <el-form-item label="风险标识" required>
            <el-input v-model="riskForm.issue_key" placeholder="如 high_dti_manual_review" />
          </el-form-item>
        </div>
        <div class="form-grid two">
          <el-form-item label="风险分类" required>
            <el-input v-model="riskForm.category" placeholder="如 credit_risk、collection_risk" />
          </el-form-item>
          <el-form-item label="严重度" required>
            <el-select v-model="riskForm.severity">
              <el-option v-for="item in severityOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-grid two">
          <el-form-item label="关联本体对象">
            <el-select v-model="riskForm.subject_object_id" clearable filterable placeholder="选择贷款账户、客户快照或其他对象">
              <el-option v-for="item in objects" :key="item.id" :label="objectOptionLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="命中规则">
            <el-input v-model="riskForm.rule_key" placeholder="如 overdue_frequency_rule" />
          </el-form-item>
        </div>
        <div class="form-grid two">
          <el-form-item label="指派人">
            <el-input v-model="riskForm.assignee" placeholder="可填写内部复核人或团队" />
          </el-form-item>
          <el-form-item label="初始状态"><el-input model-value="待处理" disabled /></el-form-item>
        </div>
        <el-form-item label="风险说明" required>
          <el-input v-model="riskForm.description" type="textarea" :rows="4" placeholder="说明发现的问题、影响范围和需要复核的判断" />
        </el-form-item>
        <div class="form-grid two">
          <el-form-item label="检测值（JSON）" required>
            <el-input v-model="riskForm.detected_value_json" type="textarea" :rows="4" spellcheck="false" placeholder='如 {"dti":0.62}' />
          </el-form-item>
          <el-form-item label="期望值（JSON）">
            <el-input v-model="riskForm.expected_value_json" type="textarea" :rows="4" spellcheck="false" placeholder='如 {"dti_lt":0.6}' />
          </el-form-item>
        </div>
        <el-form-item label="来源上下文（JSON）">
          <el-input v-model="riskForm.source_context_json" type="textarea" :rows="4" spellcheck="false" placeholder='如 {"snapshot_date":"2026-08-31","trace_id":"..."}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="riskDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingRisk" @click="handleCreateRisk">创建风险事项</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="evidenceDialog"
      :title="`添加证据 · ${selectedIssueTitle}`"
      width="700px"
      :close-on-click-modal="false"
    >
      <el-form :model="evidenceForm" label-position="top">
        <div class="form-grid two">
          <el-form-item label="证据标题" required>
            <el-input v-model="evidenceForm.title" placeholder="如 近 30 天还款流水" />
          </el-form-item>
          <el-form-item label="证据类型" required>
            <el-select v-model="evidenceForm.evidence_type">
              <el-option label="本体对象快照" value="ontology_object" />
              <el-option label="指标结果" value="metric" />
              <el-option label="数据查询" value="query" />
              <el-option label="业务文件" value="document" />
              <el-option label="人工说明" value="manual" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-grid two">
          <el-form-item label="来源引用">
            <el-input v-model="evidenceForm.source_ref" placeholder="查询 trace、文件编号或外部记录 ID" />
          </el-form-item>
          <el-form-item label="查询 Trace ID">
            <el-input v-model="evidenceForm.trace_id" placeholder="可关联问数或规则执行 trace" />
          </el-form-item>
        </div>
        <el-form-item label="证据说明">
          <el-input v-model="evidenceForm.description" type="textarea" :rows="3" placeholder="说明证据与风险判断之间的关系" />
        </el-form-item>
        <el-form-item label="结构化证据内容（JSON）" required>
          <el-input v-model="evidenceForm.content_json" type="textarea" :rows="6" spellcheck="false" placeholder='如 {"metric_key":"customer_dti","value":0.62,"as_of":"2026-08-31"}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="evidenceDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingEvidence" @click="handleAddEvidence">保存证据</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="reviewDialog"
      :title="`提交人工复核 · ${selectedIssueTitle}`"
      width="700px"
      :close-on-click-modal="false"
    >
      <el-form :model="reviewForm" label-position="top">
        <el-alert
          class="dialog-context"
          type="info"
          :closable="false"
          :title="`当前状态：${riskStatusLabel(textField(selectedIssue, 'status'))} · 版本：v${numberField(selectedIssue, 'version')}`"
        />
        <el-form-item label="复核动作" required>
          <el-select v-model="reviewForm.action">
            <el-option v-for="item in reviewActionOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="复核意见" required>
          <el-input v-model="reviewForm.comment" type="textarea" :rows="5" placeholder="写明判断依据、补件要求或后续处置说明" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingReview" @click="handleSubmitReview">提交复核</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="reportDialog"
      title="新建报告并创建 V1"
      width="780px"
      :close-on-click-modal="false"
    >
      <el-form :model="reportForm" label-position="top">
        <div class="form-grid two">
          <el-form-item label="报告名称" required>
            <el-input v-model="reportForm.name" placeholder="如 2026 年 8 月贷款风险复核报告" />
          </el-form-item>
          <el-form-item label="报告标识" required>
            <el-input v-model="reportForm.report_key" placeholder="如 loan_risk_2026_q3" />
          </el-form-item>
        </div>
        <div class="form-grid two">
          <el-form-item label="报告类型" required>
            <el-select v-model="reportForm.report_type">
              <el-option label="贷款风险复核报告" value="loan_risk_review" />
              <el-option label="财务分析报告" value="financial_analysis" />
              <el-option label="税务风险报告" value="tax_risk" />
              <el-option label="专项说明" value="special_memo" />
            </el-select>
          </el-form-item>
          <el-form-item label="纳入风险事项" required>
            <el-select v-model="reportForm.issue_ids" multiple filterable collapse-tags placeholder="选择报告覆盖的风险事项">
              <el-option v-for="item in riskIssues" :key="item.id" :label="riskIssueOptionLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-grid two">
          <el-form-item label="期间开始" required>
            <el-date-picker v-model="reportForm.period_start" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="期间结束" required>
            <el-date-picker v-model="reportForm.period_end" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
        </div>
        <el-form-item label="V1 快照（JSON）" required>
          <el-input v-model="reportForm.snapshot_json" type="textarea" :rows="6" spellcheck="false" placeholder='如 {"stage":"system_detected","change_summary":"初始版本","review_status":"pending"}' />
          <p class="form-help">技术追溯信息，普通阅读者无需填写或查看；用于记录版本快照。</p>
        </el-form-item>
        <el-form-item label="V1 报告正文（Markdown）" required>
          <el-input v-model="reportForm.markdown" type="textarea" :rows="8" spellcheck="false" placeholder="# 风险复核报告\n\n## 系统识别\n\n- ..." />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reportDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingReport" @click="handleCreateReport">创建报告与 V1</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="versionDialog"
      :title="`创建新版本 · ${selectedReportTitle}`"
      width="760px"
      :close-on-click-modal="false"
    >
      <el-form :model="versionForm" label-position="top" v-loading="versionsLoading">
        <el-alert
          class="dialog-context"
          type="info"
          :closable="false"
          :title="`将在 V${numberField(selectedReport, 'current_version') || 1} 基础上创建不可变新版本`"
        />
        <el-form-item label="纳入风险事项" required>
          <el-select v-model="versionForm.issue_ids" multiple filterable collapse-tags placeholder="选择本版本覆盖的风险事项">
            <el-option v-for="item in riskIssues" :key="item.id" :label="riskIssueOptionLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="版本快照（JSON）" required>
          <el-input v-model="versionForm.snapshot_json" type="textarea" :rows="6" spellcheck="false" placeholder='如 {"stage":"human_reviewed","change_summary":"写入人工复核结果"}' />
          <p class="form-help">技术追溯信息，普通阅读者无需填写或查看；用于记录本次版本变化。</p>
        </el-form-item>
        <el-form-item label="报告正文（Markdown）" required>
          <el-input v-model="versionForm.markdown" type="textarea" :rows="8" spellcheck="false" placeholder="# 风险复核报告\n\n## 人工复核结果\n\n- ..." />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="versionDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingVersion" @click="handleCreateVersion">创建新版本</el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="versionDrawer"
      class="version-drawer-panel"
      :title="`报告版本 · ${selectedReportTitle}`"
      size="620px"
      append-to-body
    >
      <div class="version-drawer" v-loading="versionsLoading">
        <el-alert
          v-if="versionsError"
          type="error"
          :title="versionsError"
          show-icon
          :closable="false"
        />
        <template v-else-if="reportVersionViews.length">
          <article
            v-for="{ version, issues, markdownBlocks, issueOverviewLabel, fallbackSummary } in reportVersionViews"
            :key="recordKey(version)"
            class="version-record"
          >
            <div class="version-heading">
              <div>
                <strong>V{{ numberField(version, 'version', 'version_no') || 1 }}</strong>
                <el-tag v-if="isCurrentReportVersion(version)" type="primary" size="small" effect="plain">当前版本</el-tag>
                <el-tag v-else type="info" size="small" effect="plain">不可变版本</el-tag>
              </div>
              <span>{{ formatTime(field(version, 'created_at')) }}</span>
            </div>
            <section class="report-reading-panel" aria-label="业务阅读版">
              <div class="report-reading-kicker">业务阅读版</div>
              <div class="report-overview-grid">
                <div>
                  <span>报告状态</span>
                  <strong>{{ reportStatusLabel(textField(selectedReport, 'status') || textField(version, 'status')) }}</strong>
                </div>
                <div>
                  <span>报告期间</span>
                  <strong>{{ reportPeriodLabel(selectedReport || version) }}</strong>
                </div>
                <div>
                  <span>风险事项</span>
                  <strong>{{ issues.length }} 项</strong>
                </div>
                <div>
                  <span>{{ isCurrentReportVersion(version) ? '当前版本' : '版本号' }}</span>
                  <strong>V{{ numberField(version, 'version', 'version_no') || 1 }}</strong>
                </div>
              </div>

              <section class="version-section report-overview-section">
                <div class="version-section-heading">
                  <h4>风险概览</h4>
                  <span>{{ issueOverviewLabel }}</span>
                </div>
                <div v-if="issues.length" class="report-issue-list">
                  <article v-for="issue in issues" :key="recordKey(issue)" class="report-issue-summary">
                    <div class="report-issue-heading">
                      <strong>{{ reportIssueTitle(issue) }}</strong>
                      <div class="report-issue-tags">
                        <el-tag
                          :type="reportIssueSnapshotTagType(issue)"
                          size="small"
                          effect="plain"
                          class="snapshot-source-tag"
                        >
                          {{ reportIssueSnapshotLabel(issue) }}
                        </el-tag>
                        <el-tag
                          :class="['severity-tag', severityClass(reportIssueSeverity(issue) || 'low')]"
                          :type="severityType(reportIssueSeverity(issue))"
                          size="small"
                          effect="plain"
                        >
                          {{ reportIssueSeverityLabel(issue) }}
                        </el-tag>
                        <el-tag
                          :class="['status-tag', riskStatusClass(reportIssueStatus(issue) || 'open')]"
                          :type="riskStatusType(reportIssueStatus(issue))"
                          size="small"
                          effect="plain"
                        >
                          {{ reportIssueStatusLabel(issue) }}
                        </el-tag>
                      </div>
                    </div>
                    <p v-if="reportIssueSnapshotNote(issue)" class="report-issue-snapshot-note">
                      {{ reportIssueSnapshotNote(issue) }}
                    </p>
                    <div class="report-issue-facts">
                      <div><span>关联对象</span><strong>{{ reportIssueObjectLabel(issue) }}</strong></div>
                      <div><span>检测值</span><strong>{{ reportIssueDetectedValue(issue) }}</strong></div>
                      <div><span>证据</span><strong>{{ reportIssueEvidenceSummary(issue) }}</strong></div>
                      <div><span>复核结论</span><strong>{{ reportIssueReviewSummary(issue) }}</strong></div>
                    </div>
                  </article>
                </div>
                <p v-else class="version-empty-copy">{{ fallbackSummary }}</p>
              </section>

              <section class="version-section report-body-section">
                <div class="version-section-heading">
                  <h4>报告正文</h4>
                  <span>面向业务阅读，技术字段已收纳到下方追溯区</span>
                </div>
                <div v-if="markdownBlocks.length" class="report-markdown-body">
                  <div
                    v-for="(block, index) in markdownBlocks"
                    :key="`version-report-${recordKey(version)}-${index}`"
                    :class="['report-md-block', `report-md-${block.type}`]"
                  >
                    <h2 v-if="block.type === 'heading'">{{ stripInlineMarkdown(block.text) }}</h2>
                    <h3 v-else-if="block.type === 'subheading'">{{ stripInlineMarkdown(block.text) }}</h3>
                    <p v-else-if="block.type === 'paragraph'">
                      <template
                        v-for="(part, partIndex) in inlineMarkdownParts(block.text)"
                        :key="`version-paragraph-${index}-${partIndex}`"
                      >
                        <strong v-if="part.type === 'bold'">{{ part.text }}</strong>
                        <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                        <span v-else>{{ part.text }}</span>
                      </template>
                    </p>
                    <ol v-else-if="block.type === 'list' && block.ordered">
                      <li v-for="(item, itemIndex) in block.items" :key="`version-list-${index}-${itemIndex}`">
                        <template
                          v-for="(part, partIndex) in inlineMarkdownParts(item)"
                          :key="`version-list-part-${index}-${itemIndex}-${partIndex}`"
                        >
                          <strong v-if="part.type === 'bold'">{{ part.text }}</strong>
                          <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                          <span v-else>{{ part.text }}</span>
                        </template>
                      </li>
                    </ol>
                    <ul v-else-if="block.type === 'list'">
                      <li v-for="(item, itemIndex) in block.items" :key="`version-list-${index}-${itemIndex}`">
                        <template
                          v-for="(part, partIndex) in inlineMarkdownParts(item)"
                          :key="`version-list-part-${index}-${itemIndex}-${partIndex}`"
                        >
                          <strong v-if="part.type === 'bold'">{{ part.text }}</strong>
                          <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                          <span v-else>{{ part.text }}</span>
                        </template>
                      </li>
                    </ul>
                    <div v-else-if="block.type === 'table'" class="report-data-table-wrap">
                      <table class="report-data-table">
                        <thead>
                          <tr>
                            <th v-for="column in block.columns" :key="column">{{ stripInlineMarkdown(column) }}</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-for="(row, rowIndex) in block.rows" :key="`version-table-row-${index}-${rowIndex}`">
                            <td v-for="(cell, cellIndex) in row" :key="`version-table-cell-${index}-${rowIndex}-${cellIndex}`">
                              <template
                                v-for="(part, partIndex) in inlineMarkdownParts(cell)"
                                :key="`version-table-part-${index}-${rowIndex}-${cellIndex}-${partIndex}`"
                              >
                                <strong v-if="part.type === 'bold'">{{ part.text }}</strong>
                                <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                                <span v-else>{{ part.text }}</span>
                              </template>
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                    <pre v-else-if="block.type === 'code'"><code>{{ block.text }}</code></pre>
                  </div>
                </div>
                <p v-else class="version-empty-copy">{{ fallbackSummary }}</p>
              </section>
            </section>

            <el-collapse class="technical-trace-collapse" @change="handleTechnicalTraceChange(version, $event)">
              <el-collapse-item name="technical" title="技术追溯（原始 JSON、哈希与版本字段）">
                <template v-if="isTechnicalTraceExpanded(version)">
                  <dl class="version-meta">
                    <div><dt>Ontology release</dt><dd>{{ releaseLabel(version) }}</dd></div>
                    <div><dt>创建人</dt><dd>{{ textFieldOr(version, '-', 'creator_name', 'created_by_name', 'created_by') }}</dd></div>
                    <div><dt>快照哈希</dt><dd><code>{{ shortHash(field(version, 'snapshot_hash', 'content_hash'), 24) }}</code></dd></div>
                  </dl>
                  <section class="version-section technical-section">
                    <h4>版本摘要</h4>
                    <p>{{ snapshotSummary(version) }}</p>
                  </section>
                  <section class="version-section technical-section">
                    <h4>原始 snapshot JSON</h4>
                    <pre>{{ formatSnapshot(field(version, 'snapshot_json', 'snapshot')) }}</pre>
                  </section>
                  <section class="version-section technical-section">
                    <h4>原始 Markdown</h4>
                    <pre>{{ textFieldOr(version, '暂无报告正文', 'markdown', 'content_markdown') }}</pre>
                  </section>
                  <section class="version-section technical-section">
                    <h4>技术字段</h4>
                    <pre>{{ formatTechnicalFields(version) }}</pre>
                  </section>
                </template>
              </el-collapse-item>
            </el-collapse>
          </article>
        </template>
        <el-empty v-else description="暂无报告版本" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addRiskEvidence,
  createRiskIssue,
  createRiskReport,
  createRiskReportVersion,
  fetchDecisionAuditEvents,
  fetchOntologyDomains,
  fetchOntologyObjects,
  fetchRiskIssueDetail,
  fetchRiskIssues,
  fetchRiskReportVersions,
  fetchRiskReports,
  fetchRiskSummary,
  finalizeRiskReport,
  submitRiskReview,
  verifyDecisionAuditChain,
  type DecisionAuditEvent,
  type OntologyObject,
  type RiskIssue,
  type RiskIssueDetail,
  type RiskReport,
  type RiskReportVersion,
  type RiskSummary,
} from '../api'
import {
  CircleCheck,
  DocumentAdd,
  Finished,
  Link,
  Plus,
  Refresh,
  View,
} from '@element-plus/icons-vue'
import { authState, isAdmin } from '../stores/auth'
import { formatDateTime, isDateTimeValue } from '../utils/datetime'

type DomainOption = { id: number; name: string; domain_key?: string }
type UnknownRecord = Record<string, unknown>
type DisplayEntry = { label: string; value: string }

const domains = ref<DomainOption[]>([])
const domainId = ref<number | null>(null)
const summary = ref<RiskSummary | null>(null)
const riskIssues = ref<RiskIssue[]>([])
const reports = ref<RiskReport[]>([])
const auditEvents = ref<DecisionAuditEvent[]>([])
const objects = ref<OntologyObject[]>([])
const riskDetails = ref<Record<number, RiskIssueDetail>>({})
const reportVersions = ref<RiskReportVersion[]>([])

const activeTab = ref('risks')
const riskStatusFilter = ref('all')
const riskSeverityFilter = ref('all')
const domainLoading = ref(false)
const workspaceLoading = ref(false)
const riskLoading = ref(false)
const reportLoading = ref(false)
const auditLoading = ref(false)
const pageError = ref('')
const riskError = ref('')
const reportError = ref('')
const auditError = ref('')
const issueDetailLoadingIds = ref<number[]>([])
const issueDetailErrors = reactive<Record<number, string>>({})

const riskDialog = ref(false)
const riskDetailDrawer = ref(false)
const evidenceDialog = ref(false)
const reviewDialog = ref(false)
const reportDialog = ref(false)
const versionDialog = ref(false)
const versionDrawer = ref(false)
const savingRisk = ref(false)
const savingEvidence = ref(false)
const savingReview = ref(false)
const savingReport = ref(false)
const savingVersion = ref(false)
const versionsLoading = ref(false)
const versionsError = ref('')
const expandedTechnicalVersionKeys = ref<string[]>([])
const auditVerifying = ref(false)
const auditVerifyResult = ref<UnknownRecord | null>(null)
const selectedIssue = ref<RiskIssue | null>(null)
const selectedReport = ref<RiskReport | null>(null)

const severityOptions = [
  { value: 'critical', label: '重大' },
  { value: 'high', label: '高' },
  { value: 'medium', label: '中' },
  { value: 'low', label: '低' },
]

const riskStatusOptions = [
  { value: 'open', label: '待处理' },
  { value: 'in_review', label: '待复核' },
  { value: 'needs_info', label: '待补资料' },
  { value: 'confirmed', label: '已确认' },
  { value: 'dismissed', label: '已驳回' },
  { value: 'resolved', label: '已解决' },
]

const riskForm = reactive(emptyRiskForm())
const evidenceForm = reactive(emptyEvidenceForm())
const reviewForm = reactive(emptyReviewForm())
const reportForm = reactive(emptyReportForm())
const versionForm = reactive(emptyVersionForm())

const currentDomain = computed(() => domains.value.find((item) => item.id === domainId.value))
const selectedIssueTitle = computed(() => selectedIssue.value ? textFieldOr(selectedIssue.value, '风险事项', 'title', 'name') : '风险事项')
const selectedReportTitle = computed(() => selectedReport.value ? textFieldOr(selectedReport.value, '报告', 'title', 'name') : '报告')
const reviewActionOptions = computed(() => availableReviewActions(textField(selectedIssue.value, 'status')))
const canFinalize = computed(() => isAdmin())
const reportVersionViews = computed(() => reportVersions.value.map((version) => {
  const issues = reportVersionIssues(version)
  return {
    version,
    issues,
    markdownBlocks: reportVersionMarkdownBlocks(version),
    issueOverviewLabel: reportIssueOverviewLabel(issues),
    fallbackSummary: reportVersionFallbackSummary(version, issues),
  }
}))

const filteredRiskIssues = computed(() => riskIssues.value.filter((item) => {
  const statusMatches = riskStatusFilter.value === 'all' || textField(item, 'status') === riskStatusFilter.value
  const severityMatches = riskSeverityFilter.value === 'all' || textField(item, 'severity') === riskSeverityFilter.value
  return statusMatches && severityMatches
}))

const metrics = computed(() => [
  { label: '待处理风险', value: summaryMetric(['pending_risks', 'pending_issues', 'open_issues'], issueStatusCount('open')), icon: 'Warning', tone: 'danger' },
  { label: '高风险', value: summaryMetric(['high_risks', 'high_risk_issues'], issueSeverityCount('high') + issueSeverityCount('critical')), icon: 'WarningFilled', tone: 'warning' },
  { label: '待复核', value: summaryMetric(['pending_review', 'pending_reviews', 'in_review_issues'], issueStatusCount('in_review') + issueStatusCount('needs_info')), icon: 'Finished', tone: 'primary' },
  { label: '报告数', value: summaryMetric(['report_count'], reportTotal()), icon: 'Document', tone: 'success' },
  { label: '审计事件', value: summaryMetric(['audit_events', 'audit_event_count'], auditEvents.value.length), icon: 'Clock', tone: 'neutral' },
])

const auditVerificationValid = computed(() => Boolean(field(auditVerifyResult.value, 'valid', 'is_valid')))
const auditVerificationMessage = computed(() => {
  const count = numberField(auditVerifyResult.value, 'checked', 'checked_events', 'event_count', 'verified_count')
  if (auditVerificationValid.value) return `审计链校验通过，共检查 ${count} 条事件`
  return textFieldOr(auditVerifyResult.value, '审计链校验未通过，请检查异常事件', 'reason', 'message')
})

function emptyRiskForm() {
  return {
    issue_key: '',
    title: '',
    category: 'credit_risk',
    severity: 'high',
    subject_object_id: null as number | null,
    rule_key: '',
    assignee: '',
    description: '',
    detected_value_json: '{\n  \n}',
    expected_value_json: '{\n  \n}',
    source_context_json: '{\n  \n}',
  }
}

function emptyEvidenceForm() {
  return {
    title: '',
    evidence_type: 'query',
    description: '',
    source_ref: '',
    trace_id: '',
    content_json: '{\n  \n}',
  }
}

function emptyReviewForm() {
  return { action: 'confirm', comment: '' }
}

function emptyReportForm() {
  return {
    report_key: '',
    name: '',
    report_type: 'loan_risk_review',
    period_start: '',
    period_end: '',
    issue_ids: [] as number[],
    snapshot_json: '{\n  "stage": "system_detected",\n  "change_summary": "初始版本",\n  "review_status": "pending"\n}',
    markdown: '# 风险复核报告\n\n## 系统识别\n\n',
  }
}

function emptyVersionForm() {
  return {
    issue_ids: [] as number[],
    snapshot_json: '{\n  "stage": "human_reviewed",\n  "change_summary": "写入人工复核结果"\n}',
    markdown: '# 风险复核报告\n\n## 人工复核结果\n\n',
  }
}

function replaceForm(target: UnknownRecord, value: UnknownRecord) {
  Object.keys(target).forEach((key) => delete target[key])
  Object.assign(target, value)
}

function asRecord(value: unknown): UnknownRecord {
  return value && typeof value === 'object' ? value as UnknownRecord : {}
}

function field(value: unknown, ...keys: string[]): unknown {
  const record = asRecord(value)
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null && record[key] !== '') return record[key]
  }
  return undefined
}

function textField(value: unknown, ...keys: string[]): string {
  const valueFound = field(value, ...keys)
  return valueFound === undefined ? '' : String(valueFound)
}

function textFieldOr(value: unknown, fallback: string, ...keys: string[]): string {
  return textField(value, ...keys) || fallback
}

function numberField(value: unknown, ...keys: string[]): number {
  const raw = field(value, ...keys)
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : 0
}

function normalizeList<T>(value: unknown, ...keys: string[]): T[] {
  if (Array.isArray(value)) return value as T[]
  const record = asRecord(value)
  for (const key of keys) if (Array.isArray(record[key])) return record[key] as T[]
  return []
}

function errorMessage(error: unknown, fallback: string) {
  const record = asRecord(error)
  const response = asRecord(record.response)
  const data = asRecord(response.data)
  const detail = data.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') return textFieldOr(detail, fallback, 'message', 'detail')
  return textFieldOr(error, fallback, 'message')
}

function summaryMetric(keys: string[], fallback: number) {
  const counts = field(summary.value, 'counts')
  const raw = field(counts, ...keys) ?? field(summary.value, ...keys)
  if (raw === undefined || raw === null || raw === '') return fallback
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : fallback
}

function issueStatusCount(status: string) {
  return numberField(field(field(summary.value, 'issues'), 'by_status'), status)
}

function issueSeverityCount(severity: string) {
  return numberField(field(field(summary.value, 'issues'), 'by_severity'), severity)
}

function reportTotal() {
  const countsValue = field(field(summary.value, 'counts'), 'reports')
  if (countsValue !== undefined) return Number(countsValue) || 0
  return numberField(field(summary.value, 'reports'), 'total')
}

function issueId(value: unknown) { return numberField(value, 'id') }
function reportId(value: unknown) { return numberField(value, 'id') }
function recordKey(value: unknown) { return String(field(value, 'id', 'event_hash', 'hash', 'created_at') || JSON.stringify(value)) }
function formatTime(value: unknown) { return formatDateTime(value, '-') }

function shortHash(value: unknown, visible = 16) {
  const text = String(value || '-')
  if (text.length <= visible + 8) return text
  return `${text.slice(0, visible)}…${text.slice(-8)}`
}

function severityLabel(value: string) {
  return severityOptions.find((item) => item.value === value)?.label || value || '-'
}

function severityType(value: string) {
  if (value === 'critical') return 'danger'
  if (value === 'high') return 'warning'
  if (value === 'medium') return 'primary'
  return 'info'
}

function severityClass(value: string) {
  return `severity-${value || 'low'}`
}

function riskStatusLabel(value: string) {
  return riskStatusOptions.find((item) => item.value === value)?.label || value || '-'
}

function riskStatusType(value: string) {
  if (value === 'resolved') return 'success'
  if (value === 'dismissed') return 'info'
  if (value === 'in_review' || value === 'needs_info') return 'warning'
  if (value === 'confirmed') return 'primary'
  return 'danger'
}

function riskStatusClass(value: string) {
  return `status-${value || 'open'}`
}

function reportStatusLabel(value: string) {
  return ({ draft: '草稿', reviewing: '复核中', finalized: '已定稿', final: '已定稿' } as Record<string, string>)[value] || value || '-'
}

function reportStatusType(value: string) {
  if (value === 'finalized' || value === 'final') return 'success'
  if (value === 'reviewing') return 'warning'
  return 'info'
}

function reportTypeLabel(value: string) {
  return ({ loan_risk_review: '贷款风险复核报告', risk_review: '风险复核报告', financial_analysis: '财务分析报告', tax_risk: '税务风险报告', special_memo: '专项说明' } as Record<string, string>)[value] || value || '-'
}

function evidenceTypeLabel(value: string) {
  return ({ ontology_object: '本体对象快照', metric: '指标结果', query: '数据查询', document: '业务文件', manual: '人工说明' } as Record<string, string>)[value] || value || '-'
}

function reviewDecisionLabel(value: string) {
  return ({ start_review: '开始复核', confirm: '确认风险', dismiss: '驳回风险', request_info: '请求补充资料', resolve: '解决并关闭', reopen: '重新打开' } as Record<string, string>)[value] || value || '复核记录'
}

function availableReviewActions(status: string) {
  const actions = [
    { value: 'start_review', label: '开始复核', statuses: ['open', 'needs_info'] },
    { value: 'confirm', label: '确认风险', statuses: ['open', 'in_review', 'needs_info'] },
    { value: 'dismiss', label: '驳回风险', statuses: ['open', 'in_review', 'needs_info'] },
    { value: 'request_info', label: '请求补充资料', statuses: ['open', 'in_review'] },
    { value: 'resolve', label: '解决并关闭', statuses: ['confirmed'] },
    { value: 'reopen', label: '重新打开', statuses: ['needs_info', 'confirmed', 'dismissed', 'resolved'] },
  ]
  return actions.filter((item) => item.statuses.includes(status)).map(({ value, label }) => ({ value, label }))
}

function canReviewIssue(row: RiskIssue) {
  if (isAdmin()) return true
  const user = authState.currentUser
  if (!user || numberField(row, 'created_by') === user.id) return false
  const assignee = textField(row, 'assignee').trim()
  return Boolean(assignee && [user.username, user.display_name || ''].includes(assignee))
}

function auditEventLabel(value: string) {
  return ({ 'issue.created': '风险事项创建', 'evidence.created': '证据添加', 'issue.reviewed': '人工复核', 'report.created': '报告创建', 'report.version.created': '报告版本创建', 'report.finalized': '报告定稿', 'ontology.action.succeeded': '业务动作成功', 'ontology.action.failed': '业务动作失败' } as Record<string, string>)[value] || value || '-'
}

function auditEventClass(value: string) {
  if (value === 'issue.created') return 'event-created'
  if (value === 'evidence.created') return 'event-evidence'
  if (value === 'issue.reviewed') return 'event-reviewed'
  if (value.startsWith('report.')) return 'event-report'
  return 'event-action'
}

function riskRowClassName({ row }: { row: RiskIssue }) {
  return severityClass(textField(row, 'severity'))
}

function reportRowClassName({ row }: { row: RiskReport }) {
  return isFinalReport(row) ? 'is-finalized' : 'is-editable'
}

function objectOptionLabel(item: OntologyObject) {
  return `${item.display_name} · ${item.object_type_name}`
}

function objectLabelById(rawId: unknown) {
  const id = Number(rawId)
  const item = objects.value.find((object) => object.id === id)
  return item ? objectOptionLabel(item) : id ? `对象 #${id}` : '-'
}

function issueObjectLabel(row: RiskIssue) {
  return textField(row, 'object_name', 'subject_name') || objectLabelById(field(row, 'object_id', 'subject_object_id'))
}

function riskBasisItems(row: RiskIssue): DisplayEntry[] {
  return [
    { label: '分类', value: riskCategoryLabel(textField(row, 'category')) },
    { label: '规则', value: riskRuleLabel(textField(row, 'rule_key', 'rule_code')) },
    { label: '检测值', value: riskDetectedValueSummary(field(row, 'detected_value')) },
  ]
}

function riskIssueOptionLabel(row: RiskIssue) {
  return `${severityLabel(textField(row, 'severity'))} · ${textFieldOr(row, `ISSUE-${issueId(row)}`, 'title')}`
}

function riskCategoryLabel(value: string) {
  return ({
    credit_risk: '信用风险',
    collection_risk: '催收风险',
    tax_risk: '税务风险',
    financial_risk: '财务风险',
    compliance_risk: '合规风险',
  } as Record<string, string>)[value] || readableKey(value)
}

function riskRuleLabel(value: string) {
  return ({
    demo_m1_collection_technical: 'M1+ 逾期催收检查',
    demo_high_dti_technical: '高 DTI 补充资料检查',
  } as Record<string, string>)[value] || readableKey(value)
}

function riskDetectedValueSummary(value: unknown) {
  const entries = displayEntries(value, 2)
  return entries.length ? entries.map((entry) => `${entry.label} ${entry.value}`).join('；') : '-'
}

function readableKey(value: string) {
  if (!value) return '-'
  return value.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()
}

function evidenceSummaryItems(item: unknown): DisplayEntry[] {
  const content = asRecord(field(item, 'content'))
  const type = textField(item, 'evidence_type', 'type')
  if (!Object.keys(content).length) return []

  if (type === 'query') {
    const rows = field(content, 'result_preview', 'rows')
    const firstRow = Array.isArray(rows) ? rows[0] : field(content, 'row')
    return [
      ...displayEntries({ 查询问题: field(content, 'question'), 查询结果: rowCountLabel(content) }, 2),
      ...displayEntries(firstRow, 3),
    ]
  }

  if (type === 'ontology_object') {
    return [
      ...displayEntries({ 对象类型: field(content, 'object_type_name', 'object_type_key'), 业务对象: field(content, 'display_name', 'primary_value') }, 2),
      ...displayEntries(field(content, 'properties'), 3),
    ]
  }

  if (type === 'metric') {
    const metrics = field(content, 'metrics')
    const firstMetric = Array.isArray(metrics) ? metrics[0] : content
    const threshold = asRecord(field(content, 'threshold'))
    return [
      ...displayEntries(firstMetric, 2, ['metric_key', 'value', 'unit']),
      ...displayEntries({ 阈值: thresholdLabel(threshold), 命中结果: field(content, 'matched') }, 2),
    ]
  }

  return displayEntries(content, 4)
}

function evidenceSourceLabel(item: unknown) {
  const sourceRef = textField(item, 'source_ref')
  if (sourceRef && !sourceRef.includes('://')) return sourceRef
  const type = textField(item, 'evidence_type', 'type')
  return ({
    ontology_object: '已同步业务对象快照',
    metric: '规则或指标运行结果',
    query: '受控数据查询结果',
    document: '业务文件',
    manual: '人工补充说明',
  } as Record<string, string>)[type] || '业务证据'
}

function displayEntries(value: unknown, limit: number, preferredKeys: string[] = []): DisplayEntry[] {
  const record = asRecord(value)
  const preferred = preferredKeys
    .filter((key) => record[key] !== undefined && record[key] !== null && record[key] !== '')
    .map((key) => [key, record[key]] as const)
  const rest = Object.entries(record).filter(([key]) => !preferredKeys.includes(key))
  return [...preferred, ...rest]
    .filter(([, entryValue]) => entryValue !== undefined && entryValue !== null && entryValue !== '' && typeof entryValue !== 'object')
    .slice(0, limit)
    .map(([key, entryValue]) => ({ label: displayKeyLabel(key), value: formatBusinessValue(key, entryValue) }))
}

function displayKeyLabel(key: string) {
  return ({
    current_overdue_days: '当前逾期天数',
    remaining_principal: '剩余本金',
    is_written_off: '是否已核销',
    overdue_bucket: '逾期阶段',
    loan_no: '贷款编号',
    current_status: '当前状态',
    approval_rate: '审批通过率',
    application_count: '申请笔数',
    application_region: '申请区域',
    disbursement_amount: '放款金额',
    outstanding_balance: '贷款余额',
    m1_plus_rate: 'M1+逾期率',
    mob: '贷款账龄',
    dpd: '逾期天数',
    vintage: '放款批次',
    pd: '违约概率',
    dti: '负债收入比',
    writeoff_amount: '核销金额',
    collection_recovery_rate: '催收回收率',
    region: '区域',
    evidence_count: '证据数量',
    review_count: '复核次数',
    risk_grade: '风险等级',
    model_pd: '模型违约概率',
    max_dpd_12m: '近 12 月最大逾期天数',
    stat_month: '统计月份',
    customer_id: '客户编号',
    snapshot_id: '快照编号',
    created_at: '创建时间',
    updated_at: '更新时间',
    question: '查询问题',
    row_count: '结果记录',
    查询问题: '查询问题',
    查询结果: '查询结果',
    object_type_name: '对象类型',
    object_type_key: '对象类型',
    display_name: '业务对象',
    primary_value: '业务对象',
    metric_key: '指标',
    value: '检测值',
    matched: '命中结果',
    unit: '单位',
    阈值: '阈值条件',
    命中结果: '命中结果',
  } as Record<string, string>)[key] || ({
    approvalRate: '审批通过率',
    applicationCount: '申请笔数',
    applicationRegion: '申请区域',
    disbursementAmount: '放款金额',
    outstandingBalance: '贷款余额',
    m1PlusRate: 'M1+逾期率',
    mob: '贷款账龄',
    dpd: '逾期天数',
    vintage: '放款批次',
    pd: '违约概率',
    dti: '负债收入比',
    writeoffAmount: '核销金额',
    collectionRecoveryRate: '催收回收率',
    evidenceCount: '证据数量',
    reviewCount: '复核次数',
  } as Record<string, string>)[key] || readableKey(key)
}

function formatBusinessValue(key: string, value: unknown) {
  const normalizedKey = key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string' && isDateTimeValue(value)) return formatDateTime(value)
  if (typeof value === 'number') {
    if (['dti', 'model_pd', 'approval_rate', 'm1_plus_rate', 'pd', 'collection_recovery_rate'].includes(normalizedKey)) return `${formatNumber(value * 100)}%`
    if (['remaining_principal', 'balance', 'amount'].some((token) => normalizedKey.includes(token))) return `¥${formatNumber(value)}`
    if (['dpd', 'mob'].includes(normalizedKey)) return `${formatNumber(value)} ${normalizedKey === 'mob' ? '个月' : '天'}`
    if (normalizedKey.includes('days')) return `${formatNumber(value)} 天`
    return formatNumber(value)
  }
  return String(value)
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
}

function rowCountLabel(content: UnknownRecord) {
  const count = Number(field(content, 'row_count'))
  return Number.isFinite(count) ? `${count} 条` : '-'
}

function thresholdLabel(threshold: UnknownRecord) {
  const metric = textField(threshold, 'metric')
  const operator = textField(threshold, 'operator')
  const value = field(threshold, 'value')
  if (!operator || value === undefined) return '-'
  return `${metric ? `${displayKeyLabel(metric)} ` : ''}${operator} ${formatBusinessValue(metric, value)}`
}

function reportPeriodLabel(row: unknown) {
  const start = textField(row, 'period_start', 'start_date')
  const end = textField(row, 'period_end', 'end_date')
  return start || end ? `${start || '-'} 至 ${end || '-'}` : textFieldOr(row, '-', 'period_label')
}

function releaseLabel(value: unknown) {
  const version = field(value, 'release_version', 'ontology_release_version')
  if (version !== undefined) return `V${version}`
  const id = field(value, 'release_id', 'ontology_release_id')
  return id !== undefined ? `#${id}` : '-'
}

function isFinalReport(row: RiskReport) {
  return ['final', 'finalized'].includes(textField(row, 'status'))
}

function isCurrentReportVersion(version: unknown) {
  const versionNumber = numberField(version, 'version', 'version_no')
  const currentVersion = numberField(selectedReport.value, 'current_version')
  return versionNumber > 0 && currentVersion > 0 && versionNumber === currentVersion
}

function formatSnapshot(value: unknown) {
  if (value === undefined || value === null || value === '') return '暂无快照摘要'
  if (typeof value === 'string') return value
  try { return JSON.stringify(value, null, 2) } catch { return String(value) }
}

function snapshotSummaryValue(version: unknown) {
  const snapshot = reportVersionSnapshot(version)
  const contextValue = field(snapshot, 'context')
  const context = asRecord(contextValue)
  return textField(snapshot, 'change_summary', 'changeSummary', 'summary', 'stage')
    || (typeof contextValue === 'string' ? contextValue : '')
    || textField(context, 'change_summary', 'changeSummary', 'summary', 'stage')
}

function snapshotSummary(version: unknown) {
  return snapshotSummaryValue(version) || '当前版本已绑定风险事项、证据与 Ontology release 快照'
}

type VersionMarkdownBlock =
  | { type: 'heading' | 'subheading' | 'paragraph' | 'code'; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'table'; columns: string[]; rows: string[][] }

function reportVersionSnapshot(version: unknown) {
  return asRecord(field(version, 'snapshot_json', 'snapshot'))
}

function reportVersionMarkdown(version: unknown) {
  return textField(version, 'markdown', 'content_markdown', 'body')
}

function reportVersionIssueIds(version: unknown) {
  const snapshot = reportVersionSnapshot(version)
  const versionRaw = field(version, 'issue_ids', 'issueIds')
  const snapshotRaw = field(snapshot, 'issue_ids', 'issueIds')
  const versionIds = normalizeList<unknown>(versionRaw, 'items')
    .map((value) => Number(typeof value === 'object' && value !== null ? field(value, 'id', 'issue_id') : value))
    .filter((value) => Number.isFinite(value) && value > 0)
  if (versionIds.length) return versionIds
  return normalizeList<unknown>(snapshotRaw, 'items')
    .map((value) => Number(typeof value === 'object' && value !== null ? field(value, 'id', 'issue_id') : value))
    .filter((value) => Number.isFinite(value) && value > 0)
}

const REPORT_ISSUE_SNAPSHOT_STATE = '__report_snapshot_state'
const REPORT_ISSUE_REFERENCE_KEYS = new Set(['id', 'issue_id', 'issueId'])
type ReportIssueSnapshotState = 'snapshot' | 'live_supplement' | 'missing'

function withReportIssueSnapshotState(issue: UnknownRecord, state: ReportIssueSnapshotState): UnknownRecord {
  return { ...issue, [REPORT_ISSUE_SNAPSHOT_STATE]: state }
}

function hasSnapshotIssueDetails(issue: UnknownRecord) {
  return Object.keys(issue).some((key) => !REPORT_ISSUE_REFERENCE_KEYS.has(key))
}

function reportVersionIssues(version: unknown): UnknownRecord[] {
  const snapshot = reportVersionSnapshot(version)
  const rawIssues = field(snapshot, 'issues', 'risk_issues', 'riskIssues')
  const rawIssueList = normalizeList<unknown>(rawIssues, 'items')
  const liveById = new Map(riskIssues.value.map((issue) => [issueId(issue), asRecord(issue)]))
  const issueIds = new Set(reportVersionIssueIds(version))
  const result: UnknownRecord[] = []
  const seenIds = new Set<number>()
  const seenKeys = new Set<string>()

  const pushIssue = (issue: UnknownRecord) => {
    const id = numberField(issue, 'id', 'issue_id', 'issueId')
    const key = recordKey(issue)
    if ((id && seenIds.has(id)) || (!id && seenKeys.has(key))) return
    if (id) seenIds.add(id)
    else seenKeys.add(key)
    result.push(issue)
  }

  rawIssueList.forEach((rawIssue) => {
    const rawRecord = asRecord(rawIssue)
    const nestedIssue = asRecord(field(rawRecord, 'issue'))
    const snapshotIssue: UnknownRecord = { ...nestedIssue, ...rawRecord }
    delete snapshotIssue.issue
    const scalarId = Number(rawIssue)
    const id = numberField(snapshotIssue, 'id', 'issue_id', 'issueId') || (Number.isFinite(scalarId) && scalarId > 0 ? scalarId : 0)
    if (id && !numberField(snapshotIssue, 'id', 'issue_id', 'issueId')) snapshotIssue.issue_id = id
    if (id) issueIds.add(id)
    if (!Object.keys(snapshotIssue).length) return
    if (hasSnapshotIssueDetails(snapshotIssue)) {
      pushIssue(withReportIssueSnapshotState(snapshotIssue, 'snapshot'))
      return
    }
    const liveIssue = id ? liveById.get(id) : undefined
    pushIssue(liveIssue
      ? withReportIssueSnapshotState({ ...liveIssue, ...snapshotIssue }, 'live_supplement')
      : withReportIssueSnapshotState(snapshotIssue, 'missing'))
  })

  issueIds.forEach((id) => {
    if (seenIds.has(id)) return
    const snapshotIssue = { issue_id: id }
    const liveIssue = liveById.get(id)
    pushIssue(liveIssue
      ? withReportIssueSnapshotState({ ...liveIssue, ...snapshotIssue }, 'live_supplement')
      : withReportIssueSnapshotState(snapshotIssue, 'missing'))
  })
  return result
}

function reportIssueSnapshotState(issue: unknown): ReportIssueSnapshotState {
  const state = textField(issue, REPORT_ISSUE_SNAPSHOT_STATE)
  if (state === 'live_supplement' || state === 'missing') return state
  return 'snapshot'
}

function reportIssueSnapshotLabel(issue: unknown) {
  const state = reportIssueSnapshotState(issue)
  if (state === 'live_supplement') return '未固化信息'
  if (state === 'missing') return '快照缺失'
  return '当前快照'
}

function reportIssueSnapshotTagType(issue: unknown) {
  const state = reportIssueSnapshotState(issue)
  if (state === 'live_supplement') return 'warning'
  if (state === 'missing') return 'danger'
  return 'info'
}

function reportIssueSnapshotNote(issue: unknown) {
  const state = reportIssueSnapshotState(issue)
  if (state === 'live_supplement') return '该事项在此版本中仅固化了 ID，以下详情来自当前风险数据，不属于不可变报告快照。'
  if (state === 'missing') return '该事项在此版本中仅固化了 ID，当前也无法获取对应详情。'
  return ''
}

function reportIssueTitle(issue: unknown) {
  const id = numberField(issue, 'id', 'issue_id', 'issueId')
  return textFieldOr(issue, id ? `风险事项 #${id}` : '未命名风险事项', 'title', 'name', 'issue_title', 'issueTitle')
}

function reportIssueSeverity(issue: unknown) {
  return textField(issue, 'severity', 'risk_severity', 'riskSeverity')
}

function reportIssueSeverityLabel(issue: unknown) {
  const value = reportIssueSeverity(issue)
  return value ? severityLabel(value) : '未标注'
}

function reportIssueStatus(issue: unknown) {
  return textField(issue, 'status', 'risk_status', 'riskStatus')
}

function reportIssueStatusLabel(issue: unknown) {
  const value = reportIssueStatus(issue)
  return value ? riskStatusLabel(value) : '未标注'
}

function reportIssueObjectLabel(issue: unknown) {
  return textField(issue, 'object_name', 'subject_name', 'objectName', 'subjectName')
    || objectLabelById(field(issue, 'object_id', 'subject_object_id', 'objectId', 'subjectObjectId'))
    || textFieldOr(issue, '-', 'subject_type', 'object_type', 'subjectType', 'objectType')
}

function reportIssueDetectedValue(issue: unknown) {
  return riskDetectedValueSummary(field(issue, 'detected_value', 'detectedValue', 'value'))
}

function reportIssueEvidenceSummary(issue: unknown) {
  const explicit = textField(issue, 'evidence_summary', 'evidenceSummary')
  if (explicit) return explicit
  const evidence = normalizeList<UnknownRecord>(field(issue, 'evidence', 'evidences'), 'items')
  const countValue = field(issue, 'evidence_count', 'evidenceCount')
  const count = countValue === undefined ? evidence.length : Number(countValue)
  const firstTitle = evidence.length ? textFieldOr(evidence[0], '', 'title', 'name') : ''
  if (count > 0) return `${count} 条${firstTitle ? ` · ${firstTitle}` : ''}`
  return '暂无证据记录'
}

function reportIssueReviewSummary(issue: unknown) {
  const explicit = textField(issue, 'review_summary', 'reviewSummary', 'last_review_comment', 'lastReviewComment')
  if (explicit) return explicit
  const reviews = normalizeList<UnknownRecord>(field(issue, 'reviews', 'review_records', 'reviewRecords'), 'items')
  const latest = reviews[reviews.length - 1]
  if (latest) {
    const action = reviewDecisionLabel(textField(latest, 'review_action', 'action', 'decision'))
    const comment = textField(latest, 'comment', 'review_comment', 'reviewComment')
    return comment ? `${action}：${comment}` : action
  }
  const status = textField(issue, 'status', 'risk_status', 'riskStatus')
  return status ? `当前状态：${riskStatusLabel(status)}` : '暂无复核记录'
}

function reportIssueOverviewLabel(issues: UnknownRecord[]) {
  if (!issues.length) return '暂无纳入的风险事项'
  const highSeverityCount = issues.filter((issue) => ['high', 'critical'].includes(textField(issue, 'severity', 'risk_severity', 'riskSeverity'))).length
  return `共 ${issues.length} 项${highSeverityCount ? ` · 高/重大 ${highSeverityCount} 项` : ''}`
}

function reportVersionFallbackSummary(version: unknown, issues = reportVersionIssues(version)) {
  const snapshot = reportVersionSnapshot(version)
  const context = asRecord(field(snapshot, 'context'))
  const changeSummary = snapshotSummaryValue(version)
    || textField(snapshot, 'executive_summary', 'executiveSummary')
    || textField(context, 'executive_summary', 'executiveSummary')
  const issueNames = issues
    .slice(0, 3)
    .map((issue) => reportIssueTitle(issue))
    .join('、')
  const issueSummary = issues.length
    ? `本版本纳入 ${issues.length} 个风险事项${issueNames ? `：${issueNames}${issues.length > 3 ? '等' : ''}` : ''}。`
    : '当前版本已记录风险事项和版本快照。'
  return [changeSummary, issueSummary].filter(Boolean).join(' ')
}

function reportVersionMarkdownBlocks(version: unknown): VersionMarkdownBlock[] {
  const markdown = reportVersionMarkdown(version)
  if (!markdown) return []

  const blocks: VersionMarkdownBlock[] = []
  const lines = markdown.split(/\r?\n/)
  let paragraph: string[] = []
  let listItems: string[] = []
  let listOrdered: boolean | null = null
  let codeLines: string[] = []
  let inCode = false

  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push({ type: 'paragraph', text: paragraph.join(' ').trim() })
    paragraph = []
  }
  const flushList = () => {
    if (!listItems.length) return
    blocks.push({ type: 'list', ordered: Boolean(listOrdered), items: [...listItems] })
    listItems = []
    listOrdered = null
  }
  const flushCode = () => {
    if (!codeLines.length) return
    blocks.push({ type: 'code', text: codeLines.join('\n') })
    codeLines = []
  }

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex].trimEnd()
    const trimmed = line.trim()
    if (trimmed.startsWith('```')) {
      if (inCode) {
        inCode = false
        flushCode()
      } else {
        flushParagraph()
        flushList()
        inCode = true
        codeLines = []
      }
      continue
    }
    if (inCode) {
      codeLines.push(line)
      continue
    }
    if (!trimmed) {
      flushParagraph()
      flushList()
      continue
    }
    if (isVersionMarkdownTableLine(trimmed)) {
      const tableLines = collectVersionMarkdownTableLines(lines, lineIndex)
      const table = parseVersionMarkdownTable(tableLines)
      if (table) {
        flushParagraph()
        flushList()
        blocks.push(table)
        lineIndex += tableLines.length - 1
        continue
      }
    }
    if (trimmed.startsWith('### ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'subheading', text: trimmed.replace(/^###\s+/, '') })
    } else if (trimmed.startsWith('## ') || trimmed.startsWith('# ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'heading', text: trimmed.replace(/^#{1,2}\s+/, '') })
    } else if (/^[-*]\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed)) {
      flushParagraph()
      const ordered = /^\d+\.\s+/.test(trimmed)
      if (listItems.length && listOrdered !== ordered) flushList()
      listOrdered = ordered
      listItems.push(trimmed.replace(/^[-*]\s+/, '').replace(/^\d+\.\s+/, ''))
    } else {
      flushList()
      paragraph.push(trimmed)
    }
  }
  flushParagraph()
  flushList()
  if (inCode) flushCode()
  return blocks.length ? blocks : [{ type: 'paragraph', text: markdown }]
}

type InlineReportPart = { type: 'text' | 'bold' | 'code'; text: string }

function inlineMarkdownParts(text: string): InlineReportPart[] {
  const parts: InlineReportPart[] = []
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let cursor = 0
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > cursor) parts.push({ type: 'text', text: text.slice(cursor, index) })
    const raw = match[0]
    parts.push(raw.startsWith('**')
      ? { type: 'bold', text: raw.slice(2, -2) }
      : { type: 'code', text: raw.slice(1, -1) })
    cursor = index + raw.length
  }
  if (cursor < text.length) parts.push({ type: 'text', text: text.slice(cursor) })
  return parts.length ? parts : [{ type: 'text', text }]
}

function stripInlineMarkdown(text: string) {
  return inlineMarkdownParts(text).map((part) => part.text).join('')
}

function isVersionMarkdownTableLine(line: string) {
  return line.startsWith('|') && line.endsWith('|')
}

function collectVersionMarkdownTableLines(lines: string[], start: number) {
  const tableLines: string[] = []
  for (let index = start; index < lines.length; index += 1) {
    const line = lines[index].trim()
    if (!isVersionMarkdownTableLine(line)) break
    tableLines.push(line)
  }
  return tableLines
}

function parseVersionMarkdownTable(lines: string[]): Extract<VersionMarkdownBlock, { type: 'table' }> | null {
  if (lines.length < 2) return null
  const columns = splitVersionMarkdownTableRow(lines[0])
  const bodyLines = lines.slice(1).filter((line) => !/^\|\s*[-:|\s]+\s*\|$/.test(line))
  const rows = bodyLines.map(splitVersionMarkdownTableRow).filter((row) => row.length)
  if (!columns.length || !rows.length) return null
  return { type: 'table', columns, rows }
}

function splitVersionMarkdownTableRow(line: string) {
  return line.replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

function formatTechnicalFields(version: unknown) {
  const technicalFields = Object.fromEntries(
    Object.entries(asRecord(version)).filter(([key]) => !['snapshot_json', 'snapshot', 'markdown', 'content_markdown', 'body'].includes(key)),
  )
  return Object.keys(technicalFields).length ? formatSnapshot(technicalFields) : '暂无技术字段'
}

function isTechnicalTraceExpanded(version: unknown) {
  return expandedTechnicalVersionKeys.value.includes(recordKey(version))
}

function handleTechnicalTraceChange(version: unknown, activeNames: unknown) {
  const names = Array.isArray(activeNames) ? activeNames : [activeNames]
  const key = recordKey(version)
  const keys = new Set(expandedTechnicalVersionKeys.value)
  if (names.some((name) => String(name) === 'technical')) keys.add(key)
  else keys.delete(key)
  expandedTechnicalVersionKeys.value = [...keys]
}

function evidenceItems(id: number) {
  const detail = riskDetails.value[id]
  return normalizeList<UnknownRecord>(field(detail, 'evidence', 'evidences'), 'items')
}

function reviewItems(id: number) {
  const detail = riskDetails.value[id]
  return normalizeList<UnknownRecord>(field(detail, 'reviews', 'review_records'), 'items')
}

async function loadDomains() {
  domainLoading.value = true
  pageError.value = ''
  try {
    domains.value = normalizeList<DomainOption>(await fetchOntologyDomains(), 'domains')
    if (domains.value.length && !domains.value.some((item) => item.id === domainId.value)) domainId.value = domains.value[0].id
  } catch (error) {
    pageError.value = errorMessage(error, '领域加载失败，请确认服务已启动')
  } finally {
    domainLoading.value = false
  }
}

async function loadSummary(id: number) {
  try {
    const result = await fetchRiskSummary(id)
    if (domainId.value === id) summary.value = result
  } catch (error) {
    pageError.value = errorMessage(error, '风险交付指标加载失败')
  }
}

async function loadRisks(id: number) {
  riskLoading.value = true
  riskError.value = ''
  try {
    const result = await fetchRiskIssues(id)
    if (domainId.value === id) {
      riskIssues.value = normalizeList<RiskIssue>(result, 'issues', 'risk_issues')
      const currentIssueId = issueId(selectedIssue.value)
      const refreshedIssue = riskIssues.value.find((item) => issueId(item) === currentIssueId)
      if (refreshedIssue) selectedIssue.value = refreshedIssue
    }
  } catch (error) {
    riskError.value = errorMessage(error, '风险事项加载失败')
  } finally {
    riskLoading.value = false
  }
}

async function loadReports(id: number) {
  reportLoading.value = true
  reportError.value = ''
  try {
    const result = await fetchRiskReports(id)
    if (domainId.value === id) reports.value = normalizeList<RiskReport>(result, 'reports')
  } catch (error) {
    reportError.value = errorMessage(error, '报告加载失败')
  } finally {
    reportLoading.value = false
  }
}

async function loadAudit(id: number) {
  auditLoading.value = true
  auditError.value = ''
  try {
    const result = await fetchDecisionAuditEvents(id)
    if (domainId.value === id) auditEvents.value = normalizeList<DecisionAuditEvent>(result, 'events', 'audit_events')
  } catch (error) {
    auditError.value = errorMessage(error, '决策审计事件加载失败')
  } finally {
    auditLoading.value = false
  }
}

async function loadObjects(id: number) {
  try {
    const result = await fetchOntologyObjects(id)
    if (domainId.value === id) objects.value = normalizeList<OntologyObject>(result, 'objects')
  } catch (error) {
    pageError.value = errorMessage(error, '本体对象加载失败，创建记录时暂时无法关联对象')
  }
}

async function refreshWorkspace() {
  if (!domainId.value) return
  const id = domainId.value
  workspaceLoading.value = true
  pageError.value = ''
  auditVerifyResult.value = null
  try {
    await Promise.all([loadSummary(id), loadRisks(id), loadReports(id), loadAudit(id), loadObjects(id)])
  } finally {
    if (domainId.value === id) workspaceLoading.value = false
  }
}

async function retryPageLoad() {
  if (domainId.value) return refreshWorkspace()
  return loadDomains()
}

async function loadIssueDetail(row: RiskIssue, force = false) {
  if (!domainId.value) return
  const id = issueId(row)
  if (!id || (riskDetails.value[id] && !force)) return
  issueDetailLoadingIds.value = [...new Set([...issueDetailLoadingIds.value, id])]
  delete issueDetailErrors[id]
  try {
    const result = await fetchRiskIssueDetail(domainId.value, id)
    riskDetails.value = { ...riskDetails.value, [id]: result }
  } catch (error) {
    issueDetailErrors[id] = errorMessage(error, '风险详情加载失败')
  } finally {
    issueDetailLoadingIds.value = issueDetailLoadingIds.value.filter((item) => item !== id)
  }
}

function handleTabChange(name: string | number) {
  if (!domainId.value) return
  if (name === 'reports' && reports.value.length === 0 && !reportLoading.value) void loadReports(domainId.value)
  if (name === 'audit' && auditEvents.value.length === 0 && !auditLoading.value) void loadAudit(domainId.value)
}

function openRiskDialog() {
  replaceForm(riskForm, emptyRiskForm())
  riskDialog.value = true
}

function openRiskDetail(row: RiskIssue) {
  selectedIssue.value = row
  riskDetailDrawer.value = true
  void loadIssueDetail(row)
}

function openEvidenceDialog(row: RiskIssue) {
  selectedIssue.value = row
  replaceForm(evidenceForm, emptyEvidenceForm())
  evidenceDialog.value = true
  void loadIssueDetail(row)
}

function openReviewDialog(row: RiskIssue) {
  if (!canReviewIssue(row)) {
    ElMessage.warning('只有指派复核人可以提交复核，且不能自审')
    return
  }
  selectedIssue.value = row
  replaceForm(reviewForm, emptyReviewForm())
  reviewForm.action = availableReviewActions(textField(row, 'status'))[0]?.value || ''
  reviewDialog.value = true
  void loadIssueDetail(row)
}

function openReportDialog() {
  replaceForm(reportForm, emptyReportForm())
  reportDialog.value = true
}

async function openVersionDialog(row: RiskReport) {
  selectedReport.value = row
  replaceForm(versionForm, emptyVersionForm())
  versionDialog.value = true
  versionsLoading.value = true
  try {
    const versions = normalizeList<RiskReportVersion>(await fetchRiskReportVersions(domainId.value!, reportId(row)), 'versions')
    const latest = versions[0]
    if (!latest) return
    versionForm.issue_ids = normalizeList<number>(field(latest, 'issue_ids'))
    versionForm.snapshot_json = JSON.stringify(asRecord(field(latest, 'snapshot_json', 'snapshot')), null, 2)
    versionForm.markdown = textField(latest, 'markdown', 'content_markdown')
  } catch (error) {
    ElMessage.warning(errorMessage(error, '上一版本加载失败，请手动填写新版本内容'))
  } finally {
    versionsLoading.value = false
  }
}

async function handleCreateRisk() {
  if (!domainId.value || !riskForm.issue_key.trim() || !riskForm.title.trim() || !riskForm.category.trim() || !riskForm.description.trim()) {
    return ElMessage.warning('请完整填写风险标识、标题、分类和说明')
  }
  if (!isValidBusinessKey(riskForm.issue_key)) return ElMessage.warning('风险标识只能以英文字母开头，并使用英文、数字、点、下划线或短横线')
  if (riskForm.rule_key && !isValidBusinessKey(riskForm.rule_key)) return ElMessage.warning('规则标识格式不正确')
  savingRisk.value = true
  try {
    const detectedValue = parseJsonObject(riskForm.detected_value_json, '检测值')
    const expectedValue = parseJsonObject(riskForm.expected_value_json, '期望值')
    const sourceContext = parseJsonObject(riskForm.source_context_json, '来源上下文')
    await createRiskIssue(domainId.value, {
      domain_id: domainId.value,
      subject_object_id: riskForm.subject_object_id,
      issue_key: riskForm.issue_key.trim(),
      category: riskForm.category.trim(),
      title: riskForm.title.trim(),
      severity: riskForm.severity,
      rule_key: riskForm.rule_key.trim() || null,
      description: riskForm.description.trim(),
      detected_value: detectedValue,
      expected_value: expectedValue,
      source_context: sourceContext,
      assignee: riskForm.assignee.trim() || null,
    })
    ElMessage.success('风险事项已创建')
    riskDialog.value = false
    await Promise.all([loadRisks(domainId.value), loadSummary(domainId.value), loadAudit(domainId.value)])
  } catch (error) {
    ElMessage.error(errorMessage(error, '风险事项创建失败'))
  } finally {
    savingRisk.value = false
  }
}

function isValidBusinessKey(value: string) {
  return /^[A-Za-z][A-Za-z0-9_.-]*$/.test(value.trim())
}

function parseJsonObject(text: string, label: string) {
  const normalized = text.trim()
  if (!normalized) return {}
  try {
    const parsed = JSON.parse(normalized)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
    return parsed as UnknownRecord
  } catch {
    throw new Error(`${label}必须是有效的 JSON 对象`)
  }
}

async function handleAddEvidence() {
  if (!domainId.value || !selectedIssue.value) return
  if (!evidenceForm.title.trim() || !evidenceForm.content_json.trim()) return ElMessage.warning('请填写证据标题和结构化内容')
  savingEvidence.value = true
  try {
    const content = parseJsonObject(evidenceForm.content_json, '证据内容')
    await addRiskEvidence(domainId.value, issueId(selectedIssue.value), {
      evidence_type: evidenceForm.evidence_type,
      title: evidenceForm.title.trim(),
      description: evidenceForm.description.trim(),
      source_ref: evidenceForm.source_ref.trim() || null,
      content,
      trace_id: evidenceForm.trace_id.trim() || null,
    })
    ElMessage.success('证据已添加')
    evidenceDialog.value = false
    await Promise.all([loadIssueDetail(selectedIssue.value, true), loadRisks(domainId.value), loadSummary(domainId.value), loadAudit(domainId.value)])
  } catch (error) {
    ElMessage.error(errorMessage(error, '证据添加失败'))
  } finally {
    savingEvidence.value = false
  }
}

async function handleSubmitReview() {
  if (!domainId.value || !selectedIssue.value) return
  if (!reviewForm.action || !reviewForm.comment.trim()) return ElMessage.warning('请选择复核动作并填写复核意见')
  savingReview.value = true
  try {
    await submitRiskReview(domainId.value, issueId(selectedIssue.value), {
      action: reviewForm.action,
      comment: reviewForm.comment.trim(),
      expected_version: numberField(selectedIssue.value, 'version') || null,
    })
    ElMessage.success('人工复核已提交')
    reviewDialog.value = false
    await Promise.all([loadIssueDetail(selectedIssue.value, true), loadRisks(domainId.value), loadSummary(domainId.value), loadAudit(domainId.value)])
  } catch (error) {
    ElMessage.error(errorMessage(error, '人工复核提交失败'))
  } finally {
    savingReview.value = false
  }
}

async function handleCreateReport() {
  if (!domainId.value || !reportForm.report_key.trim() || !reportForm.name.trim() || !reportForm.period_start || !reportForm.period_end || reportForm.issue_ids.length === 0 || !reportForm.snapshot_json.trim() || !reportForm.markdown.trim()) {
    return ElMessage.warning('请完整填写报告标识、名称、期间、风险事项、V1 快照和正文')
  }
  if (!isValidBusinessKey(reportForm.report_key)) return ElMessage.warning('报告标识只能以英文字母开头，并使用英文、数字、点、下划线或短横线')
  if (reportForm.period_start > reportForm.period_end) return ElMessage.warning('报告期间开始日期不能晚于结束日期')
  savingReport.value = true
  try {
    const snapshot = parseJsonObject(reportForm.snapshot_json, 'V1 快照')
    await createRiskReport(domainId.value, {
      domain_id: domainId.value,
      report_key: reportForm.report_key.trim(),
      name: reportForm.name.trim(),
      report_type: reportForm.report_type,
      period_start: reportForm.period_start,
      period_end: reportForm.period_end,
      status: 'draft',
      issue_ids: [...reportForm.issue_ids],
      snapshot,
      markdown: reportForm.markdown,
    })
    ElMessage.success('报告与 V1 已创建')
    reportDialog.value = false
    activeTab.value = 'reports'
    await Promise.all([loadReports(domainId.value), loadSummary(domainId.value), loadAudit(domainId.value)])
  } catch (error) {
    ElMessage.error(errorMessage(error, '报告创建失败'))
  } finally {
    savingReport.value = false
  }
}

async function handleCreateVersion() {
  if (!domainId.value || !selectedReport.value) return
  if (versionForm.issue_ids.length === 0 || !versionForm.snapshot_json.trim() || !versionForm.markdown.trim()) return ElMessage.warning('请选择风险事项并填写版本快照和报告正文')
  savingVersion.value = true
  try {
    const snapshot = parseJsonObject(versionForm.snapshot_json, '版本快照')
    await createRiskReportVersion(domainId.value, reportId(selectedReport.value), {
      issue_ids: [...versionForm.issue_ids],
      snapshot,
      markdown: versionForm.markdown,
      expected_current_version: numberField(selectedReport.value, 'current_version') || null,
    })
    ElMessage.success('报告新版本已创建')
    versionDialog.value = false
    await Promise.all([loadReports(domainId.value), loadSummary(domainId.value), loadAudit(domainId.value)])
    if (versionDrawer.value) await loadReportVersions(selectedReport.value)
  } catch (error) {
    ElMessage.error(errorMessage(error, '报告版本创建失败'))
  } finally {
    savingVersion.value = false
  }
}

async function handleFinalizeReport(row: RiskReport) {
  if (!domainId.value) return
  try {
    await ElMessageBox.confirm(
      `定稿后报告“${textFieldOr(row, '未命名报告', 'title', 'name')}”将锁定当前版本，是否继续？`,
      '报告定稿',
      { type: 'warning', confirmButtonText: '定稿' },
    )
    await finalizeRiskReport(
      domainId.value,
      reportId(row),
      numberField(row, 'current_version') || null,
    )
    ElMessage.success('报告已定稿')
    await Promise.all([loadReports(domainId.value), loadSummary(domainId.value), loadAudit(domainId.value)])
    if (versionDrawer.value && reportId(selectedReport.value) === reportId(row)) await loadReportVersions(row)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error, '报告定稿失败'))
  }
}

async function loadReportVersions(row: RiskReport) {
  if (!domainId.value) return
  versionsLoading.value = true
  versionsError.value = ''
  try {
    const result = await fetchRiskReportVersions(domainId.value, reportId(row))
    reportVersions.value = normalizeList<RiskReportVersion>(result, 'versions')
  } catch (error) {
    versionsError.value = errorMessage(error, '报告版本加载失败')
  } finally {
    versionsLoading.value = false
  }
}

async function openReportVersions(row: RiskReport) {
  selectedReport.value = row
  reportVersions.value = []
  expandedTechnicalVersionKeys.value = []
  versionDrawer.value = true
  await loadReportVersions(row)
}

async function handleVerifyAuditChain() {
  if (!domainId.value) return
  auditVerifying.value = true
  auditVerifyResult.value = null
  try {
    auditVerifyResult.value = asRecord(await verifyDecisionAuditChain(domainId.value))
    if (auditVerificationValid.value) ElMessage.success('审计链校验通过')
    else ElMessage.error('审计链校验未通过')
  } catch (error) {
    auditError.value = errorMessage(error, '审计链校验失败')
  } finally {
    auditVerifying.value = false
  }
}

watch(domainId, (id) => {
  summary.value = null
  riskIssues.value = []
  reports.value = []
  auditEvents.value = []
  objects.value = []
  riskDetails.value = {}
  reportVersions.value = []
  riskDetailDrawer.value = false
  selectedIssue.value = null
  selectedReport.value = null
  if (id) void refreshWorkspace()
})

onMounted(loadDomains)
</script>

<style scoped>
.risk-delivery-page {
  --risk-ink: #182230;
  --risk-body: #344054;
  --risk-muted: #667085;
  --risk-line: #e4e7ec;
  --risk-soft: #f7f9fc;
  --risk-accent: #175cd3;
  --risk-shadow: 0 8px 22px rgba(16, 24, 40, 0.08);
  width: 100%;
  max-width: var(--wq-page-max-width);
  height: 100%;
  min-height: 0;
  min-width: 0;
  margin: 0 auto;
  padding-inline: var(--wq-page-gutter);
  padding-bottom: var(--wq-page-bottom-gap);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--wq-text);
}

.page-toolbar {
  min-height: 66px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--wq-border);
}

.title-group { min-width: 0; }
.title-group h2 { color: var(--wq-text); font-size: 23px; line-height: 1.25; letter-spacing: 0; }
.title-group p { margin-top: 8px; color: var(--wq-muted); font-size: 14px; }
.toolbar-actions, .section-toolbar, .section-actions, .detail-heading, .record-line, .version-heading { display: flex; align-items: center; }
.toolbar-actions { justify-content: flex-end; gap: 8px; }
.domain-select { width: 230px; }
.page-error-row { display: flex; align-items: stretch; gap: 10px; margin-top: 12px; }
.page-error { flex: 1; margin-top: 0; }
.page-retry-button { flex: 0 0 auto; min-width: 72px; }

.metric-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 1px;
  margin: 14px 0 8px;
  background: var(--wq-border);
  border: 1px solid var(--wq-border);
  border-radius: 7px;
  overflow: hidden;
}

.metric-item { position: relative; min-height: 76px; padding: 13px 16px; background: var(--wq-surface); border-top: 3px solid transparent; transition: background-color 160ms ease; }
.metric-item span { display: block; color: var(--wq-muted); font-size: 12px; }
.metric-item strong { display: block; margin-top: 3px; color: var(--risk-ink); font-size: 25px; font-weight: 720; line-height: 1.1; }
.metric-item .el-icon { position: absolute; right: 14px; top: 22px; color: #98a2b3; font-size: 24px; }
.metric-item.has-value { background: #fcfdff; }
.metric-item.is-empty strong, .metric-item.is-empty .el-icon { color: #98a2b3; }
.metric-item.tone-danger { border-top-color: #f04438; }
.metric-item.tone-danger strong, .metric-item.tone-danger .el-icon { color: #b42318; }
.metric-item.tone-warning { border-top-color: #f79009; }
.metric-item.tone-warning strong, .metric-item.tone-warning .el-icon { color: #b54708; }
.metric-item.tone-primary { border-top-color: #528bff; }
.metric-item.tone-primary strong, .metric-item.tone-primary .el-icon { color: #175cd3; }
.metric-item.tone-success { border-top-color: #32d583; }
.metric-item.tone-success strong, .metric-item.tone-success .el-icon { color: #067647; }
.metric-item.tone-neutral { border-top-color: #98a2b3; }

.workspace-tabs { min-width: 0; min-height: 0; flex: 1; }
.workspace-tabs :deep(.el-tabs__header) { margin: 0; }
.workspace-tabs :deep(.el-tabs__content) { min-width: 0; height: calc(100% - 40px); }
.workspace-tabs :deep(.el-tab-pane) { min-width: 0; height: 100%; }
.workspace-tabs :deep(.el-tabs__item) { height: 42px; color: #475467; font-weight: 600; }
.workspace-tabs :deep(.el-tabs__item.is-active) { color: var(--risk-accent); }
.workspace-tabs :deep(.el-tabs__active-bar) { height: 2px; }

.table-section {
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  overflow: hidden;
  background: var(--wq-surface);
}

.table-section:not(:has(.section-error)):not(:has(.audit-result)) { grid-template-rows: auto minmax(0, 1fr); }
.audit-section:has(.audit-result):not(:has(.section-error)) { grid-template-rows: auto auto minmax(0, 1fr); }
.audit-section:has(.audit-result):has(.section-error) { grid-template-rows: auto auto auto minmax(0, 1fr); }
.section-toolbar { min-height: 66px; justify-content: space-between; gap: 18px; padding: 0 2px; border-bottom: 1px solid var(--wq-border); }
.section-heading { display: flex; align-items: center; gap: 10px; min-width: 0; }
.section-heading-copy { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.section-heading strong { color: var(--risk-ink); font-size: 15px; }
.section-heading span { color: var(--wq-muted); font-size: 11px; line-height: 1.45; }
.section-heading em { display: inline-flex; align-items: center; min-height: 22px; padding: 0 8px; color: #475467; background: var(--risk-soft); border: 1px solid #d0d5dd; border-radius: 5px; font-size: 11px; font-style: normal; white-space: nowrap; }
.section-actions { justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.filter-group { padding: 5px; background: var(--risk-soft); border: 1px solid var(--risk-line); border-radius: 7px; }
.filter-select { width: 138px; }
.section-error, .audit-result { margin: 10px 0; }
.workbench-table { width: 100%; min-height: 0; height: 100%; }
.workbench-table :deep(.el-table__header-wrapper th.el-table__cell) { height: 42px; color: #475467; background: #f8fafc; border-bottom-color: #dfe4ec; font-size: 12px; font-weight: 700; }
.workbench-table :deep(.el-table__body-wrapper td.el-table__cell) { min-height: 72px; border-bottom-color: #eaecf0; }
.workbench-table :deep(.el-table__body tr > td.el-table__cell) { transition: background-color 160ms ease, box-shadow 160ms ease; }
.workbench-table :deep(.el-table__body tr:last-child > td.el-table__cell) { border-bottom: 0; }
.workbench-table :deep(.el-table__body tr.severity-critical > td.el-table__cell) { background: #fffafa; }
.workbench-table :deep(.el-table__body tr.severity-high > td.el-table__cell) { background: #fffdf5; }
.risk-issues-table :deep(.el-table__body tr) { cursor: pointer; }
.risk-issues-table :deep(.el-table__body tr:hover > td.el-table__cell), .report-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: #eff8ff; box-shadow: inset 0 1px 0 #b2ddff, inset 0 -1px 0 #b2ddff; }
.risk-issues-table :deep(.el-table__body tr:active > td.el-table__cell), .report-table :deep(.el-table__body tr:active > td.el-table__cell) { background: #e0f2fe; }
.report-table :deep(.el-table__body tr) { cursor: pointer; }
.report-table :deep(.el-table__body tr.is-finalized) { background: #fbfefc; }
.report-table :deep(.el-table__body tr.is-editable) { background: #fcfdff; }
.audit-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: #f8fafc; }

.primary-cell, .secondary-cell { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.primary-cell strong { color: var(--risk-ink); font-weight: 680; line-height: 1.45; }
.secondary-cell span { color: #475467; }
.primary-meta { display: flex; align-items: center; min-width: 0; }
code { color: #667085; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }

.risk-title-cell { position: relative; padding-left: 12px; }
.risk-title-cell::before { position: absolute; top: 2px; bottom: 2px; left: 0; width: 3px; border-radius: 2px; content: ''; background: #98a2b3; }
.risk-title-cell.severity-critical::before { background: #d92d20; }
.risk-title-cell.severity-high::before { background: #f79009; }
.risk-title-cell.severity-medium::before { background: #528bff; }

.severity-tag, .status-tag { min-width: 54px; justify-content: center; border-radius: 5px; font-weight: 650; }
.severity-tag.severity-critical { --el-tag-bg-color: #fef3f2; --el-tag-border-color: #fecdca; --el-tag-text-color: #b42318; }
.severity-tag.severity-high { --el-tag-bg-color: #fffaeb; --el-tag-border-color: #fedf89; --el-tag-text-color: #b54708; }
.severity-tag.severity-medium { --el-tag-bg-color: #eff8ff; --el-tag-border-color: #b2ddff; --el-tag-text-color: #175cd3; }
.severity-tag.severity-low { --el-tag-bg-color: #f2f4f7; --el-tag-border-color: #d0d5dd; --el-tag-text-color: #475467; }
.status-tag.status-confirmed, .status-tag.status-resolved, .status-tag.report-finalized, .status-tag.report-final { --el-tag-bg-color: #ecfdf3; --el-tag-border-color: #abefc6; --el-tag-text-color: #067647; }
.status-tag.status-in_review, .status-tag.status-needs_info, .status-tag.report-reviewing { --el-tag-bg-color: #fffaeb; --el-tag-border-color: #fedf89; --el-tag-text-color: #b54708; }
.status-tag.status-open { --el-tag-bg-color: #fef3f2; --el-tag-border-color: #fecdca; --el-tag-text-color: #b42318; }
.status-tag.status-dismissed, .status-tag.report-draft { --el-tag-bg-color: #f2f4f7; --el-tag-border-color: #d0d5dd; --el-tag-text-color: #475467; }

.object-cell { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.object-cell strong { color: #344054; font-weight: 560; overflow-wrap: anywhere; }
.object-cell span { color: #98a2b3; font-size: 11px; }

.risk-basis-cell { display: grid; gap: 3px; min-width: 0; }
.risk-basis-item { display: grid; grid-template-columns: 36px minmax(0, 1fr); align-items: start; gap: 6px; min-width: 0; }
.risk-basis-item > span { color: #98a2b3; font-size: 11px; line-height: 1.55; }
.risk-basis-item > strong { color: #344054; font-size: 12px; font-weight: 600; line-height: 1.55; overflow-wrap: anywhere; }
.risk-basis-item > strong.is-rule-key { color: #667085; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; font-weight: 560; }

.count-pair { display: inline-flex; align-items: center; justify-content: center; gap: 4px; }
.count-pair span { display: inline-flex; align-items: center; gap: 3px; color: #475467; font-size: 12px; }
.count-pair span + span { padding-left: 5px; border-left: 1px solid var(--wq-border); }
.count-pair b { display: grid; width: 18px; height: 18px; place-items: center; border-radius: 4px; color: #175cd3; background: #eff8ff; font-size: 10px; font-weight: 700; }
.count-pair span + span b { color: #9e6000; background: #fffaeb; }
.table-time { color: #667085; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; white-space: nowrap; }
.period-value { color: #475467; font-size: 13px; }
.version-token, .release-token { display: inline-flex; align-items: center; justify-content: center; min-width: 36px; padding: 2px 7px; color: #175cd3; background: #eff8ff; border: 1px solid #b2ddff; border-radius: 5px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; font-weight: 700; }
.release-token { color: #475467; background: #f9fafb; border-color: #d0d5dd; }

.table-actions { display: flex; align-items: center; justify-content: center; gap: 4px; flex-wrap: nowrap; }
.table-actions :deep(.el-tooltip__trigger) { display: inline-flex; }
.table-action-btn { flex: 0 0 30px; width: 30px; height: 30px; min-height: 30px; padding: 0; margin: 0 !important; border-radius: 6px; color: #475467; background: #f9fafb; }
.table-action-btn:hover { color: #175cd3; background: #eff8ff; }
.table-action-btn.is-evidence { color: #027a48; background: #ecfdf3; }
.table-action-btn.is-evidence:hover { color: #05603a; background: #d1fadf; }
.table-action-btn.is-review, .table-action-btn.is-version { color: #175cd3; background: #eff8ff; }
.table-action-btn.is-review:hover, .table-action-btn.is-version:hover { color: #004eeb; background: #d1e9ff; }
.table-action-btn.is-finalize { color: #067647; background: #ecfdf3; }
.table-action-btn.is-finalize:hover { color: #05603a; background: #d1fadf; }
.table-action-btn.is-view { color: #475467; background: #f2f4f7; }
.table-empty { display: flex; min-height: 240px; align-items: center; justify-content: center; }
.table-empty :deep(.el-empty) { padding: 28px 0; }
.empty-note { display: block; max-width: 360px; color: #98a2b3; font-size: 12px; line-height: 1.6; }

.risk-detail-drawer { min-height: 260px; padding-bottom: 20px; }
.risk-detail-overview { padding: 2px 0 22px; border-bottom: 1px solid var(--wq-border); }
.risk-detail-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.risk-detail-heading .risk-title-cell { flex: 1; min-width: 0; }
.risk-detail-heading .risk-title-cell strong { display: block; color: #182230; font-size: 17px; line-height: 1.45; }
.risk-detail-heading .risk-title-cell code { display: block; margin-top: 4px; }
.risk-detail-tags { display: flex; flex: 0 0 auto; gap: 6px; }
.risk-detail-description { margin: 14px 0 0; padding: 11px 12px; color: #475467; background: #f8fafc; border-left: 3px solid #b2ddff; font-size: 13px; line-height: 1.7; }
.risk-detail-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; margin-top: 18px; border-top: 1px solid #eaecf0; border-left: 1px solid #eaecf0; }
.risk-detail-facts > div { min-width: 0; padding: 10px 12px; border-right: 1px solid #eaecf0; border-bottom: 1px solid #eaecf0; }
.risk-detail-facts dt { color: #98a2b3; font-size: 11px; }
.risk-detail-facts dd { margin: 3px 0 0; color: #344054; font-size: 12px; font-weight: 600; line-height: 1.55; overflow-wrap: anywhere; }
.risk-detail-facts time { color: #667085; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; font-weight: 560; }
.drawer-detail-section { padding: 20px 0; border-bottom: 1px solid var(--wq-border); }
.drawer-detail-section:last-child { border-bottom: 0; }
.detail-heading { min-height: 34px; justify-content: space-between; gap: 12px; }
.detail-heading > div { display: flex; align-items: baseline; gap: 7px; }
.detail-heading strong { color: #182230; font-size: 14px; }
.detail-heading span { color: #667085; font-size: 12px; }
.detail-heading > div > strong { letter-spacing: 0; }
.detail-action { font-weight: 600; }
.detail-action.is-evidence { --el-button-text-color: #027a48; --el-button-bg-color: #ecfdf3; --el-button-border-color: #abefc6; --el-button-hover-text-color: #05603a; --el-button-hover-bg-color: #d1fadf; }
.detail-action.is-review { --el-button-text-color: #175cd3; --el-button-bg-color: #eff8ff; --el-button-border-color: #b2ddff; --el-button-hover-text-color: #004eeb; --el-button-hover-bg-color: #d1e9ff; }
.detail-list { min-width: 0; margin-top: 8px; border-top: 1px solid #dfe4ec; }
.detail-record { min-width: 0; padding: 14px 12px; border-bottom: 1px solid #dfe4ec; background: #fcfdff; }
.detail-record:first-child { border-top: 1px solid #dfe4ec; }
.evidence-record { border-left: 3px solid #12b76a; }
.review-record { border-left: 3px solid #f79009; }
.record-line { justify-content: space-between; gap: 10px; }
.record-line strong { color: #344054; font-size: 13px; }
.detail-record p { margin: 5px 0; color: #667085; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.record-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; color: #667085; font-size: 11px; }
.evidence-summary { display: flex; flex-wrap: wrap; gap: 8px 0; margin: 9px 0; padding: 9px 0; border-top: 1px solid #eaecf0; border-bottom: 1px solid #eaecf0; background: transparent; }
.evidence-summary-item { min-width: 140px; max-width: 50%; padding: 0 12px; border-left: 2px solid #d0d5dd; background: transparent; }
.evidence-summary-item:first-child { padding-left: 0; border-left: 0; }
.evidence-summary-item span { display: block; color: #98a2b3; font-size: 10px; line-height: 1.4; }
.evidence-summary-item strong { display: block; margin-top: 2px; color: #344054; font-size: 12px; font-weight: 600; line-height: 1.5; overflow-wrap: anywhere; }
.review-section .detail-list { position: relative; padding-left: 17px; }
.review-section .detail-list::before { position: absolute; top: 0; bottom: 0; left: 4px; width: 1px; content: ''; background: #d0d5dd; }
.review-record { position: relative; }
.review-record::before { position: absolute; top: 19px; left: -17px; width: 9px; height: 9px; border: 2px solid #f7f9fc; border-radius: 50%; content: ''; background: #98a2b3; box-shadow: 0 0 0 1px #98a2b3; }
.review-record.status-confirmed::before, .review-record.status-resolved::before { background: #12b76a; box-shadow: 0 0 0 1px #12b76a; }
.review-record.status-needs_info::before, .review-record.status-in_review::before { background: #f79009; box-shadow: 0 0 0 1px #f79009; }
.review-record.status-open::before { background: #f04438; box-shadow: 0 0 0 1px #f04438; }

.audit-event-cell { position: relative; padding-left: 11px; }
.audit-event-cell::before { position: absolute; top: 3px; bottom: 3px; left: 0; width: 3px; border-radius: 2px; content: ''; background: #98a2b3; }
.audit-event-cell.event-created::before { background: #528bff; }
.audit-event-cell.event-evidence::before { background: #12b76a; }
.audit-event-cell.event-reviewed::before { background: #f79009; }
.audit-event-cell.event-report::before { background: #7f56d9; }
.audit-entity-cell code { color: #98a2b3; }

.hash-value { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: help; }

.form-grid { display: grid; gap: 14px; }
.form-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.form-grid :deep(.el-select), .form-grid :deep(.el-date-editor), .form-grid :deep(.el-input-number) { width: 100%; }

.version-drawer { min-height: 220px; }
.version-record { padding: 0 0 22px; margin-bottom: 22px; border-bottom: 1px solid var(--wq-border); }
.version-record:last-child { margin-bottom: 0; border-bottom: 0; }
.version-heading { justify-content: space-between; gap: 14px; }
.version-heading > div { display: flex; align-items: center; gap: 8px; }
.version-heading > div strong { font-size: 18px; }
.version-heading > span { color: var(--wq-muted); font-size: 12px; }
.report-reading-panel { margin-top: 14px; padding: 14px; background: #fcfdff; border: 1px solid #dfe4ec; border-radius: 8px; }
.report-reading-kicker { color: var(--risk-accent); font-size: 11px; font-weight: 750; letter-spacing: .04em; }
.report-overview-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-top: 10px; background: var(--wq-border); border: 1px solid var(--wq-border); border-radius: 6px; overflow: hidden; }
.report-overview-grid > div { min-width: 0; padding: 10px 11px; background: #fff; }
.report-overview-grid span, .report-issue-facts span { display: block; color: #98a2b3; font-size: 11px; line-height: 1.45; }
.report-overview-grid strong { display: block; margin-top: 3px; color: var(--risk-ink); font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; }
.report-overview-section { padding-top: 14px; }
.version-section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.version-section-heading h4 { margin: 0; color: #344054; font-size: 14px; }
.version-section-heading span { color: #98a2b3; font-size: 11px; line-height: 1.5; text-align: right; }
.report-issue-list { display: grid; gap: 9px; margin-top: 9px; }
.report-issue-summary { min-width: 0; padding: 11px 12px; background: #fff; border: 1px solid #eaecf0; border-left: 3px solid #f79009; border-radius: 6px; }
.report-issue-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.report-issue-heading > strong { min-width: 0; color: #182230; font-size: 13px; line-height: 1.55; overflow-wrap: anywhere; }
.report-issue-tags { display: flex; flex: 0 0 auto; justify-content: flex-end; gap: 5px; flex-wrap: wrap; }
.snapshot-source-tag { font-weight: 650; }
.report-issue-snapshot-note { margin: 8px 0 0; padding: 7px 9px; color: #b54708; background: #fffaeb; border-left: 3px solid #fdb022; font-size: 11px; line-height: 1.55; }
.report-issue-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 14px; margin-top: 9px; padding-top: 9px; border-top: 1px solid #f0f2f5; }
.report-issue-facts > div { min-width: 0; }
.report-issue-facts strong { display: block; margin-top: 2px; color: #475467; font-size: 12px; font-weight: 600; line-height: 1.55; overflow-wrap: anywhere; }
.version-empty-copy { margin: 9px 0 0; color: #667085; font-size: 13px; line-height: 1.75; }
.report-body-section { padding: 16px 0 0; }
.report-markdown-body { margin-top: 10px; }
.report-md-block + .report-md-block { margin-top: 11px; }
.report-md-heading h2 { margin: 0; padding-top: 4px; color: var(--risk-accent); font-size: 17px; line-height: 1.5; }
.report-md-subheading h3 { margin: 0; color: #344054; font-size: 14px; line-height: 1.5; }
.report-md-paragraph p { margin: 0; color: #344054; font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.report-md-paragraph code, .report-md-list code, .report-md-table code { padding: 1px 4px; color: #175cd3; background: #eff8ff; border-radius: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.report-md-list { color: #344054; font-size: 13px; line-height: 1.8; }
.report-md-list ul, .report-md-list ol { margin: 0; padding-left: 21px; }
.report-md-list ul { list-style: disc; }
.report-md-list ol { list-style: decimal; }
.report-md-list li + li { margin-top: 3px; }
.report-md-code pre { margin: 0; padding: 10px 12px; overflow: auto; color: #344054; background: #f8fafc; border: 1px solid #eaecf0; border-left: 3px solid #84adff; border-radius: 5px; white-space: pre-wrap; overflow-wrap: anywhere; }
.report-md-code code { color: #475467; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; line-height: 1.65; }
.report-data-table-wrap { max-width: 100%; overflow-x: auto; border: 1px solid #eaecf0; border-radius: 5px; }
.report-data-table { width: 100%; min-width: 420px; border-collapse: collapse; color: #344054; font-size: 12px; }
.report-data-table th { color: #475467; background: #f8fafc; font-weight: 700; text-align: left; }
.report-data-table th, .report-data-table td { padding: 8px 10px; border-bottom: 1px solid #eaecf0; vertical-align: top; line-height: 1.55; }
.report-data-table tr:last-child td { border-bottom: 0; }
.technical-trace-collapse { margin-top: 13px; border-top: 1px solid #eaecf0; border-bottom: 1px solid #eaecf0; }
.technical-trace-collapse :deep(.el-collapse-item__header) { height: 42px; color: #667085; font-size: 12px; font-weight: 650; }
.technical-trace-collapse :deep(.el-collapse-item__wrap) { border-bottom: 0; }
.technical-trace-collapse :deep(.el-collapse-item__content) { padding-bottom: 12px; }
.technical-section { padding-top: 11px; }
.version-meta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin: 14px 0; background: var(--wq-border); border: 1px solid var(--wq-border); border-radius: 6px; overflow: hidden; }
.version-meta > div { min-width: 0; padding: 9px 10px; background: #f8fafc; }
.version-meta dt { color: var(--wq-muted); font-size: 11px; }
.version-meta dd { margin: 4px 0 0; color: #344054; font-size: 13px; overflow-wrap: anywhere; }
.version-section { padding-top: 12px; }
.version-section h4 { margin: 0 0 6px; color: #344054; font-size: 13px; }
.version-section p, .version-section pre { margin: 0; color: #475467; font-size: 13px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.version-section pre { padding: 10px; background: #f8fafc; border-left: 3px solid #84adff; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.form-help { margin: 5px 0 0; color: #98a2b3; font-size: 11px; line-height: 1.5; }

@media (max-width: 1100px) {
  .page-toolbar { align-items: flex-start; }
  .metric-strip { grid-template-columns: repeat(3, 1fr); }
  .risk-toolbar { align-items: flex-start; }
  .section-actions { max-width: 68%; }
  .form-grid.three { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 760px) {
  .risk-delivery-page { height: auto; min-height: 100%; padding-inline: 16px; padding-bottom: 16px; overflow: auto; }
  .page-error-row { flex-direction: column; }
  .page-toolbar { flex-direction: column; align-items: stretch; }
  .toolbar-actions { justify-content: flex-start; }
  .domain-select { width: min(100%, 320px); }
  .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .workspace-tabs { min-height: 680px; }
  .section-toolbar { align-items: flex-start; flex-direction: column; padding: 10px 0; }
  .section-heading { width: 100%; justify-content: space-between; }
  .section-actions { width: 100%; max-width: none; justify-content: flex-start; }
  .filter-group { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filter-select { width: auto; min-width: 0; }
  .section-actions > .el-button { width: 100%; }
  .table-section { overflow: auto; }
  .workbench-table { min-width: 920px; }
  .report-table { min-width: 980px; }
  .audit-table { min-width: 940px; }
  .evidence-summary { grid-template-columns: 1fr; }
  .evidence-summary-item { max-width: 100%; padding-left: 0; border-left: 0; }
  .risk-detail-facts { grid-template-columns: 1fr; }
  .risk-detail-heading { flex-direction: column; }
  .form-grid.two, .form-grid.three { grid-template-columns: 1fr; }
  .report-overview-grid, .report-issue-facts { grid-template-columns: 1fr; }
  .report-issue-heading, .version-section-heading { flex-direction: column; align-items: flex-start; }
  .version-section-heading span { text-align: left; }
  .version-meta { grid-template-columns: 1fr; }
  :deep(.risk-detail-panel), :deep(.version-drawer-panel) { width: 100% !important; }
}
</style>
