<template>
  <div class="chat-layout">
    <div class="session-sidebar">
      <div class="sidebar-header">
        <el-button class="new-chat-button" type="primary" :disabled="loading" @click="newSession">
          <el-icon><Plus /></el-icon>
          <span>新对话</span>
        </el-button>
        <el-button :icon="Refresh" :disabled="loading" @click="loadSessions" />
      </div>
      <div class="session-search">
        <el-input v-model="sessionSearch" :prefix-icon="Search" placeholder="搜索历史会话" clearable />
      </div>
      <div class="session-list">
        <div class="session-group">今天</div>
        <div
          v-for="s in filteredSessions"
          :key="s.session_id"
          :class="['session-item', { active: s.session_id === sessionId, disabled: loading }]"
          @click="loadSession(s.session_id)"
        >
          <div class="session-title">{{ s.last_question || '新对话' }}</div>
          <div class="session-meta">
            <span>{{ formatTime(s.created_at) }}</span>
            <span>{{ s.turn_count }}轮</span>
          </div>
          <el-icon class="session-delete" @click.stop="handleDeleteSession(s.session_id)"><Delete /></el-icon>
        </div>
        <div v-if="filteredSessions.length === 0" class="empty-sessions">暂无历史会话</div>
      </div>
      <div class="session-footer">
        <span>历史记录按当前智能体自动保存</span>
      </div>
    </div>

    <div class="chat-container">
      <div class="workspace-toolbar">
        <div class="workspace-title">
          <h2>智能问数对话</h2>
          <p>{{ selectedDatasourceName }} · {{ selectedAgentName }}</p>
        </div>
        <div class="chat-controls">
          <el-select
            v-model="datasourceId"
            placeholder="选择数据源"
            style="width: 200px"
            size="small"
            :disabled="loading"
          >
            <el-option
              v-for="ds in datasources"
              :key="ds.id"
              :label="`${ds.name} (${ds.database_name})`"
              :value="ds.id"
            />
          </el-select>
          <el-select
            v-model="agentId"
            placeholder="选择智能体"
            style="width: 180px"
            size="small"
            :disabled="loading"
          >
            <el-option
              v-if="agents.length === 0"
              label="默认智能体"
              :value="agentId"
            />
            <el-option
              v-for="agent in agents"
              :key="agent.id"
              :label="agent.name"
              :value="agent.id"
            />
          </el-select>
        </div>
      </div>

      <div class="chat-messages" ref="messagesRef" @scroll="handleMessagesScroll">
        <div v-if="messages.length === 0" class="empty-hint">
          <div class="empty-icon">
            <el-icon :size="28"><ChatDotRound /></el-icon>
          </div>
          <h3>输入自然语言，开始查询数据</h3>
          <p>支持贷款风控指标、Vintage、逾期、核销和催收回收分析。</p>
          <div class="empty-examples">
            <el-button v-for="query in quickQueries.slice(0, 3)" :key="query" @click="useQuickQuery(query)">
              {{ query }}
            </el-button>
          </div>
        </div>

        <template v-for="(msg, idx) in messages" :key="idx">
          <div :class="['message', msg.role]">
            <div class="message-avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
            <div class="message-content">
              <div v-if="msg.role === 'assistant'" class="meta">
                <el-tag v-if="isAssistantStreaming(msg)" size="small">生成中</el-tag>
                <el-tag v-if="msg.intent" size="small" type="info">{{ msg.intent }}</el-tag>
                <el-tag v-if="msg.sql" size="small" type="success">SQL</el-tag>
              </div>

              <div v-if="msg.role === 'assistant' && msg.steps.length > 0" class="chain-panel">
                <div class="chain-header">
                  <div class="chain-title">
                    <el-icon v-if="isAssistantStreaming(msg)" class="is-loading"><Loading /></el-icon>
                    <el-icon v-else><CircleCheck /></el-icon>
                    <span>{{ isAssistantStreaming(msg) ? '分析中...' : '分析过程' }}</span>
                  </div>
                  <button class="chain-collapse" type="button" @click="toggleChain(msg.id)">
                    <el-icon><ArrowRight v-if="msg.chainCollapsed" /><ArrowDown v-else /></el-icon>
                    <span>{{ msg.chainCollapsed ? '展开' : '收起' }}</span>
                  </button>
                </div>

                <div v-if="msg.chainCollapsed" class="chain-collapsed-summary">
                  <el-tag
                    v-for="step in msg.steps"
                    :key="`${msg.id}-${step.node}`"
                    :type="step.status === 'done' ? 'success' : step.status === 'running' ? 'primary' : 'info'"
                    size="small"
                    effect="plain"
                  >
                    {{ displayStepLabel(step) }}
                  </el-tag>
                </div>

                <div v-else>
                  <div v-for="step in msg.steps" :key="step.node" class="chain-step">
                    <div class="step-header">
                      <span :class="['step-status', step.status]">
                        <el-icon v-if="step.status === 'running'" class="is-loading"><Loading /></el-icon>
                        <el-icon v-else-if="step.status === 'done'"><CircleCheck /></el-icon>
                        <el-icon v-else><Clock /></el-icon>
                      </span>
                      <span class="step-label">{{ displayStepLabel(step) }}</span>
                      <button
                        v-if="canShowPythonCode(step)"
                        type="button"
                        class="step-summary step-summary-button"
                        @click="togglePythonCode(msg.id, step.node)"
                      >
                        <span>统计脚本</span>
                        <span>{{ pythonSummarySuffix(step) }}</span>
                      </button>
                      <span v-else-if="step.summary" class="step-summary">{{ step.summary }}</span>
                    </div>

                    <div v-if="step.reasoning" class="step-reasoning">
                      <div class="reasoning-toggle" @click="toggleReasoning(msg.id, step.node)">
                        <el-icon><View v-if="!step.showReasoning" /><Hide v-else /></el-icon>
                        <span>思考过程 ({{ step.reasoning.length }}字)</span>
                      </div>
                      <div v-if="step.showReasoning" class="reasoning-content">
                        {{ step.reasoning }}
                      </div>
                    </div>

                    <div v-if="step.output" class="step-output">
                      <div v-if="stepDetails(step).length" class="output-detail-grid">
                        <div v-for="detail in stepDetails(step)" :key="detail.label" class="output-detail-item">
                          <span>{{ detail.label }}</span>
                          <strong>{{ detail.value }}</strong>
                        </div>
                      </div>
                      <div v-if="stepListDetails(step).length" class="output-list-grid">
                        <div v-for="detail in stepListDetails(step)" :key="detail.label" class="output-list-block">
                          <span>{{ detail.label }}</span>
                          <ul>
                            <li v-for="item in detail.items" :key="item">{{ item }}</li>
                          </ul>
                        </div>
                      </div>
                      <div v-if="step.node === 'nl2lf_generate' && getOutputObject(step.output, 'logic_form')" class="output-enhanced">
                        <pre><code>{{ formatJson(getOutputObject(step.output, 'logic_form')) }}</code></pre>
                      </div>
                      <div v-else-if="step.streamText" class="output-stream-text">
                        <pre><code>{{ step.streamText }}</code></pre>
                      </div>
                      <div v-else-if="(step.node === 'lf_to_sql_compile' || step.node === 'nl2sql_fallback') && getOutputString(step.output, 'compiled_sql')" class="output-sql">
                        <pre><code>{{ getOutputString(step.output, 'compiled_sql') }}</code></pre>
                      </div>
                      <div v-else-if="canShowPythonCode(step)" class="output-code-section">
                        <button type="button" class="output-code-toggle" @click="togglePythonCode(msg.id, step.node)">
                          <el-icon><View v-if="!step.showPythonCode" /><Hide v-else /></el-icon>
                          <span>{{ step.showPythonCode ? '收起统计脚本' : '查看统计脚本' }}</span>
                        </button>
                        <div v-if="step.showPythonCode" class="output-sql output-python-code">
                          <pre><code>{{ getOutputString(step.output, 'python_code') }}</code></pre>
                        </div>
                      </div>
                      <div v-else-if="(step.node === 'lf_to_sql_compile' || step.node === 'nl2sql_fallback') && getOutputString(step.output, 'error')" class="output-result">
                        <span class="error">{{ step.node === 'nl2sql_fallback' ? '兜底失败' : '编译失败' }}: {{ getOutputString(step.output, 'error') }}</span>
                      </div>
                      <div v-else-if="step.node === 'sql_execute' && hasOutputKey(step.output, 'row_count')" class="output-result">
                        <span v-if="getOutputString(step.output, 'error')" class="error">错误: {{ getOutputString(step.output, 'error') }}</span>
                        <span v-else>返回 {{ getOutputValue(step.output, 'row_count') }} 条结果</span>
                      </div>
                      <div v-else-if="getOutputStrings(step.output, 'errors').length" class="output-result">
                        <span class="error">{{ getOutputStrings(step.output, 'errors').join('；') }}</span>
                      </div>
                      <div v-else-if="getOutputStrings(step.output, 'items').length" class="output-evidence">
                        语义资产: {{ getOutputStrings(step.output, 'items').join(', ') }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="msg.role === 'assistant' && msg.status === 'error'" class="run-error-card">
                <div class="run-error-header">
                  <el-icon><WarningFilled /></el-icon>
                  <div>
                    <span class="run-error-kicker">运行失败</span>
                    <h3>{{ errorStageText(msg) }}</h3>
                  </div>
                  <el-tag v-if="msg.error?.type" type="danger" size="small" effect="plain">{{ msg.error.type }}</el-tag>
                </div>
                <div class="run-error-body">
                  <div class="run-error-summary">
                    <el-icon><InfoFilled /></el-icon>
                    <p>{{ friendlyErrorSummary(msg) }}</p>
                  </div>
                  <div v-if="showRawErrorMessage(msg)" class="run-error-message">{{ msg.error?.message || msg.content }}</div>
                  <div class="run-error-suggestion">{{ friendlyErrorSuggestion(msg) }}</div>
                </div>
                <div v-if="msg.error?.detail || msg.error?.node" class="run-error-detail-panel">
                  <button class="detail-toggle" type="button" @click="toggleErrorDetail(msg.id)">
                    <el-icon><ArrowRight v-if="!msg.showErrorDetail" /><ArrowDown v-else /></el-icon>
                    <span>{{ msg.showErrorDetail ? '收起技术明细' : '查看技术明细' }}</span>
                  </button>
                  <div v-if="msg.showErrorDetail" class="run-error-detail">
                    <div><strong>出错阶段：</strong>{{ errorStageText(msg) }}</div>
                    <div v-if="msg.error?.node"><strong>节点标识：</strong>{{ msg.error.node }}</div>
                    <div v-if="msg.error?.detail"><strong>技术明细：</strong>{{ msg.error.detail }}</div>
                  </div>
                </div>
                <div class="run-error-actions">
                  <el-button size="small" type="primary" :icon="Refresh" :disabled="loading || !latestUserQuestion" @click="rerunLatestQuestion">
                    重新运行
                  </el-button>
                  <el-button size="small" :disabled="!latestSql" @click="activeResultTab = 'sql'">查看 SQL</el-button>
                </div>
                <div class="run-error-tip">完整堆栈已写入 logs/backend.log</div>
              </div>

              <div v-else-if="shouldShowAnswerCard(msg)" class="answer-card">
                <div class="answer-card-header">
                  <div>
                    <span class="answer-kicker">Final Answer</span>
                    <h3>分析结论</h3>
                    <p class="answer-subtitle">{{ panelResultTitle(msg) }}</p>
                  </div>
                  <div class="answer-badges">
                    <el-tag v-if="msg.intent" size="small" type="info">{{ msg.intent }}</el-tag>
                    <el-tag v-if="msg.sql" size="small" type="success">SQL 已生成</el-tag>
                    <el-tag v-if="msg.sql_result?.length" size="small" effect="plain">{{ msg.sql_result.length }} 行</el-tag>
                  </div>
                </div>
                <div class="answer-body">
                  <div class="answer-summary">
                    <div class="summary-mark">
                      <el-icon><CircleCheck /></el-icon>
                    </div>
                    <div class="answer-copy">
                      <p
                        v-for="(line, lineIndex) in answerSummaryLines(msg)"
                        :key="`${msg.id}-summary-${lineIndex}`"
                      >
                        {{ line }}
                      </p>
                    </div>
                  </div>
                  <div v-if="resultHighlights(msg).length" class="answer-kpi-grid">
                    <div
                      v-for="item in resultHighlights(msg)"
                      :key="item.key"
                      class="answer-kpi"
                    >
                      <span>{{ item.label }}</span>
                      <strong>{{ item.value }}</strong>
                      <code>{{ item.key }}</code>
                    </div>
                  </div>
                </div>
                <div v-if="msg.sql || msg.sql_result?.length || msg.report_payload" class="answer-assets">
                  <button v-if="msg.sql" class="asset-chip" type="button" @click="activeResultTab = 'sql'">
                    <span>SQL 详情</span>
                    <strong>{{ compactSql(msg.sql) }}</strong>
                  </button>
                  <button v-if="msg.sql_result?.length" class="asset-chip" type="button" @click="activeResultTab = 'result'">
                    <span>结果表</span>
                    <strong>{{ msg.sql_result.length }} 行数据，点击查看</strong>
                  </button>
                  <button v-if="msg.report_payload" class="asset-chip" type="button" @click="openReport(msg)">
                    <span>分析报告</span>
                    <strong>{{ reportTitle(msg.report_payload) }}</strong>
                  </button>
                </div>
              </div>
              <div v-else class="text">{{ msg.content }}</div>
              <div v-if="msg.role === 'assistant' && msg.sql_result && msg.sql_result.length > 0" class="result-table compact-result">
                <div class="inline-result-header">
                  <span>结果预览</span>
                  <el-button size="small" text @click="activeResultTab = 'result'">查看完整结果</el-button>
                </div>
                <el-table :data="msg.sql_result.slice(0, 5)" border size="small" max-height="240">
                  <el-table-column
                    v-for="col in Object.keys(msg.sql_result[0])"
                    :key="col"
                    :prop="col"
                    min-width="120"
                    show-overflow-tooltip
                  >
                    <template #header>
                      <div class="column-heading">
                        <span>{{ columnTitle(col) }}</span>
                        <small>{{ col }}</small>
                      </div>
                    </template>
                    <template #default="{ row }">
                      <button
                        v-if="isLongCellValue(row[col])"
                        class="result-cell-button"
                        type="button"
                        @click="previewCellValue(col, row[col])"
                      >
                        {{ renderCellText(col, row[col]) }}
                      </button>
                      <span v-else>{{ renderCellText(col, row[col]) }}</span>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </div>
          </div>
        </template>
      </div>

      <div class="chat-input">
      <button
        v-if="hasUnreadStream"
        type="button"
        class="jump-latest-button"
        @click="jumpToLatest"
      >
        回到底部
      </button>

      <div class="query-composer">
          <el-input
            v-model="inputText"
            type="textarea"
            placeholder="输入你的问题，支持自然语言查询数据..."
            :autosize="{ minRows: 2, maxRows: 4 }"
            :disabled="loading"
            @keydown.enter.exact.prevent="handleSend"
          />
          <div class="composer-footer">
            <div class="quick-query-list">
              <el-button v-for="query in quickQueries" :key="query" size="small" @click="useQuickQuery(query)">
                {{ query }}
              </el-button>
            </div>
            <el-button :icon="Promotion" @click="handleSend" :loading="loading" type="primary">
              发送
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <div class="insight-panel">
      <el-tabs v-model="activeResultTab" stretch>
        <el-tab-pane label="分析链路" name="chain">
          <div class="panel-actions">
            <el-button size="small" :icon="Refresh" :disabled="loading || !latestUserQuestion" @click="rerunLatestQuestion">重新运行</el-button>
            <span class="run-state" :class="{ running: loading }">
              {{ loading ? '生成中' : latestAssistant ? '已完成' : '待查询' }}
            </span>
          </div>
          <div v-if="latestSteps.length" class="panel-timeline">
            <div v-for="step in latestSteps" :key="step.node" class="panel-step">
              <span :class="['timeline-dot', step.status]" />
              <div>
                <strong>{{ displayStepLabel(step) }}</strong>
                <p>{{ step.summary || statusText(step.status) }}</p>
              </div>
            </div>
          </div>
          <div v-else class="panel-empty">发起查询后，这里会展示理解问题、知识召回、生成 LogicForm、编译 SQL 和执行查询的过程。</div>
        </el-tab-pane>

        <el-tab-pane label="SQL" name="sql">
          <div class="panel-actions">
            <el-button size="small" :icon="DocumentCopy" :disabled="!latestSql" @click="copyLatestSql">复制 SQL</el-button>
            <span class="result-count">生成的 SQL</span>
          </div>
          <div v-if="latestSql" class="panel-sql">
            <pre><code>{{ latestSql }}</code></pre>
          </div>
          <div v-else class="panel-empty">暂无 SQL，完成一次问数后会自动展示。</div>
        </el-tab-pane>

        <el-tab-pane label="结果" name="result">
          <div class="panel-actions">
            <el-button size="small" :icon="Download" :disabled="latestRows.length === 0" @click="downloadResults">导出</el-button>
            <span class="result-count">查询结果（{{ latestRows.length }} 行）</span>
          </div>
          <div v-if="latestRows.length" class="panel-result">
            <div class="result-meta-card">
              <div>
                <strong>{{ latestResultSummary }}</strong>
                <p>当前显示 {{ latestRowRangeText }}，可通过分页查看完整明细。</p>
              </div>
              <el-tag effect="plain">{{ latestColumns.length }} 列</el-tag>
            </div>
            <div class="result-column-tools">
              <el-select
                v-model="visibleResultColumns"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="选择展示列"
              >
                <el-option
                  v-for="col in latestColumns"
                  :key="col"
                  :label="columnTitle(col)"
                  :value="col"
                />
              </el-select>
              <el-button size="small" @click="resetVisibleColumns">重置列</el-button>
            </div>
            <el-table :data="pagedLatestRows" border size="small" height="420" class="result-grid">
              <el-table-column
                v-for="col in displayedLatestColumns"
                :key="col"
                :prop="col"
                min-width="140"
                show-overflow-tooltip
              >
                <template #header>
                  <div class="column-heading">
                    <span>{{ columnTitle(col) }}</span>
                    <small>{{ col }}</small>
                  </div>
                </template>
                <template #default="{ row }">
                  <button
                    v-if="isLongCellValue(row[col])"
                    class="result-cell-button"
                    type="button"
                    @click="previewCellValue(col, row[col])"
                  >
                    {{ renderCellText(col, row[col]) }}
                  </button>
                  <span v-else>{{ renderCellText(col, row[col]) }}</span>
                </template>
              </el-table-column>
            </el-table>
            <div class="result-pagination">
              <span class="result-page-hint">显示范围：{{ latestRowRangeText }}</span>
              <el-pagination
                v-model:current-page="resultPage"
                v-model:page-size="resultPageSize"
                background
                layout="total, sizes, prev, pager, next"
                :page-sizes="resultPageSizeOptions"
                :total="latestRows.length"
              />
            </div>
          </div>
          <div v-else-if="latestAssistantComplete" class="empty-result-card">
            <strong>本次 SQL 返回 0 行</strong>
            <p>可能是时间范围、过滤条件、字段口径或数据源选择过窄。可以查看 SQL 后调整问法，或重新运行最近的问题。</p>
            <div>
              <el-button size="small" :disabled="!latestSql" @click="activeResultTab = 'sql'">查看 SQL</el-button>
              <el-button size="small" type="primary" :disabled="loading || !latestUserQuestion" @click="rerunLatestQuestion">重新提问</el-button>
            </div>
          </div>
          <div v-else class="panel-empty">暂无结果数据。</div>
        </el-tab-pane>

        <el-tab-pane label="报告" name="report">
          <div class="panel-actions">
            <el-button size="small" :icon="FullScreen" :disabled="!latestReport" @click="openLatestReport">展开查看</el-button>
            <span class="result-count">{{ latestReport ? '结构化分析报告' : '暂无报告' }}</span>
          </div>
          <div v-if="latestReport" class="report-preview">
            <div class="report-preview-header">
              <span>分析报告</span>
              <h3>{{ reportTitle(latestReport) }}</h3>
              <p>{{ reportSummary(latestReport) }}</p>
            </div>
            <div class="report-highlight-list">
              <div
                v-for="item in reportHighlights(latestReport).slice(0, 4)"
                :key="`${item.field}-${item.label}`"
                class="report-highlight"
              >
                <span>{{ item.label }}</span>
                <strong>{{ formatReportValue(item.value) }}</strong>
              </div>
            </div>
            <div class="report-section-preview">
              <div v-for="section in reportSections(latestReport).slice(0, 2)" :key="section.title" class="report-mini-section">
                <strong>{{ section.title }}</strong>
                <p>{{ section.items.slice(0, 2).join('；') }}</p>
              </div>
            </div>
          </div>
          <div v-else class="panel-empty">完成一次深度分析后，这里会展示报告预览。</div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="showCellDetail" title="字段详情" width="640px" append-to-body>
      <div class="cell-detail">
        <div class="cell-detail-heading">
          <strong>{{ cellDetailTitle }}</strong>
        </div>
        <pre>{{ cellDetailValue }}</pre>
      </div>
    </el-dialog>

    <el-dialog
      v-model="showReportDialog"
      class="report-dialog"
      width="min(1120px, 92vw)"
      append-to-body
      destroy-on-close
    >
      <template #header>
        <div class="report-dialog-title">
          <span>深度分析报告</span>
          <h2>{{ expandedReport ? reportTitle(expandedReport) : '' }}</h2>
        </div>
      </template>
      <div v-if="expandedReport" class="report-document">
        <header class="report-paper-head">
          <span>{{ reportStatusText(expandedReport) }}</span>
          <h1>{{ reportTitle(expandedReport) }}</h1>
          <p>{{ reportSummary(expandedReport) }}</p>
          <div class="report-meta-line">
            <span>生成时间：{{ reportGeneratedAt(expandedReport) }}</span>
            <span>结果行数：{{ reportRowCount(expandedReport) }}</span>
          </div>
        </header>

        <section class="report-doc-section">
          <h2>执行摘要</h2>
          <div class="report-kpi-table">
            <div
              v-for="item in reportExecutivePoints(expandedReport)"
              :key="item.label"
              class="report-kpi-cell"
            >
              <span>{{ item.label }}</span>
              <strong>{{ formatReportValue(item.value) }}</strong>
            </div>
          </div>
          <ul>
            <li v-for="item in reportExecutiveBullets(expandedReport)" :key="item">{{ item }}</li>
          </ul>
        </section>

        <section class="report-doc-section">
          <h2>分析背景与用户诉求</h2>
          <p v-for="item in reportBackground(expandedReport)" :key="item">{{ item }}</p>
        </section>

        <section class="report-doc-section">
          <h2>数据分析过程</h2>
          <article
            v-for="(step, index) in reportProcessSteps(expandedReport)"
            :key="`${step.title}-${index}`"
            class="report-step-block"
          >
            <h3>{{ step.title }}</h3>
            <p>{{ step.text }}</p>
            <pre v-if="step.result && /select|from|where|group by|order by/i.test(step.result)"><code>{{ step.result }}</code></pre>
            <p v-else-if="step.result" class="report-step-result">{{ step.result }}</p>
          </article>
        </section>

        <section v-if="reportCharts(expandedReport).length" class="report-doc-section">
          <h2>结果解读</h2>
          <div
            v-for="chart in reportCharts(expandedReport)"
            :key="chart.title"
            class="report-chart-card"
          >
            <div class="report-chart-head">
              <h3>{{ chart.title }}</h3>
              <p>{{ chart.subtitle }}</p>
            </div>
            <div class="report-bar-chart">
              <div
                v-for="item in chart.data"
                :key="String(item.label)"
                class="report-bar-row"
              >
                <span>{{ item.label }}</span>
                <div class="report-bar-track">
                  <i :style="{ width: `${barPercent(item.value, chart.data)}%` }"></i>
                </div>
                <strong>{{ formatReportValue(item.value) }}</strong>
              </div>
            </div>
          </div>
          <ul>
            <li v-for="item in reportInterpretation(expandedReport)" :key="item">{{ item }}</li>
          </ul>
        </section>

        <section v-else class="report-doc-section">
          <h2>结果解读</h2>
          <ul>
            <li v-for="item in reportInterpretation(expandedReport)" :key="item">{{ item }}</li>
          </ul>
        </section>

        <section v-if="reportTables(expandedReport).length" class="report-doc-section">
          <h2>结果明细</h2>
          <div
            v-for="table in reportTables(expandedReport)"
            :key="table.title"
            class="report-data-table-wrap"
          >
            <h3>{{ table.title }}</h3>
            <table class="report-data-table">
              <thead>
                <tr>
                  <th v-for="column in table.columns" :key="column">{{ columnTitle(column) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, rowIndex) in table.rows" :key="rowIndex">
                  <td v-for="column in table.columns" :key="column">{{ formatReportValue(row[column]) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="report-doc-section">
          <h2>建议与后续行动</h2>
          <ul>
            <li v-for="item in reportSuggestions(expandedReport)" :key="item">{{ item }}</li>
          </ul>
        </section>

        <section v-if="reportPythonResult(expandedReport)" class="report-doc-section report-appendix">
          <h2>附录：Python 分析结果</h2>
          <pre><code>{{ formatJson(reportPythonResult(expandedReport)) }}</code></pre>
        </section>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, nextTick, onUnmounted, watch } from 'vue'
import { Promotion, Loading, ChatDotRound, Plus, Delete, CircleCheck, Clock, View, Hide, Search, Refresh, Download, DocumentCopy, WarningFilled, ArrowDown, ArrowRight, InfoFilled, FullScreen } from '@element-plus/icons-vue'
import {
  sendMessageStream, fetchAgents, fetchDatasources, fetchSessions, fetchHistory, deleteSession,
  fetchSemanticAssets, fetchSemanticDomains,
  type AgentItem, type DatasourceItem, type SessionItem, type HistoryItem,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { setChatBusy } from '../stores/chatRun'
import {
  createChatStreamState,
  reduceChatStreamEvent,
  startChatRun,
  toggleAssistantChain,
  toggleAssistantErrorDetail,
  toggleAssistantPythonCode,
  toggleAssistantReasoning,
  type ChatMessage,
  type ChatReasoningStep,
  type ChatStreamState,
} from '../stores/chatStream'

const streamState = ref<ChatStreamState>(createChatStreamState())
const messages = computed(() => streamState.value.messages)
const inputText = ref('')
const sessionSearch = ref('')
const activeResultTab = ref('chain')
const loading = ref(false)
const agentId = ref<number>(Number(localStorage.getItem('wenqu_agent_id')) || 1)
const agents = ref<AgentItem[]>([])
const datasourceId = ref<number | null>(null)
const datasources = ref<DatasourceItem[]>([])
const sessions = ref<SessionItem[]>([])
const sessionId = ref<string>('')
const messagesRef = ref<HTMLElement>()
const semanticLabels = ref<Record<string, string>>({})
const resultPage = ref(1)
const resultPageSize = ref(10)
const visibleResultColumns = ref<string[]>([])
const showCellDetail = ref(false)
const cellDetailTitle = ref('')
const cellDetailValue = ref('')
const showReportDialog = ref(false)
const expandedReport = ref<Record<string, unknown> | null>(null)
const shouldAutoScroll = ref(true)
const hasUnreadStream = ref(false)
let abortController: AbortController | null = null
let activeRunId = 0
const resultPageSizeOptions = [10, 20, 50, 100]

const quickQueries = [
  '本月现金贷 M1+逾期率怎么算',
  '按 Vintage 看放款后 MOB3 的风险表现',
  '各催收团队的催收回收率排名',
  '高 PD 客户的余额和逾期情况',
]

const filteredSessions = computed(() => {
  const keyword = sessionSearch.value.trim().toLowerCase()
  if (!keyword) return sessions.value
  return sessions.value.filter((session) => (session.last_question || '新对话').toLowerCase().includes(keyword))
})

const selectedAgentName = computed(() => {
  return agents.value.find(agent => agent.id === agentId.value)?.name || '未选择智能体'
})

const selectedDatasourceName = computed(() => {
  const datasource = datasources.value.find(item => item.id === datasourceId.value)
  return datasource ? `${datasource.name} (${datasource.database_name})` : '未选择数据源'
})

const latestAssistant = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const message = messages.value[i]
    if (message.role === 'assistant') return message
  }
  return null
})

const latestAssistantComplete = computed(() => latestAssistant.value?.status === 'complete')

const latestUserQuestion = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const message = messages.value[i]
    if (message.role === 'user') return message.content
  }
  return ''
})

const latestSteps = computed(() => latestAssistant.value?.steps || [])

const latestSql = computed(() => {
  if (latestAssistant.value?.sql) return latestAssistant.value.sql
  for (const step of latestSteps.value) {
    if (step.node === 'lf_to_sql_compile' && step.output) {
      const sql = getOutputString(step.output, 'compiled_sql')
      if (sql) return sql
    }
  }
  return ''
})

const latestRows = computed(() => latestAssistant.value?.sql_result || [])
const latestReport = computed(() => {
  if (!latestAssistantComplete.value) return null
  return latestAssistant.value?.report_payload || null
})
const latestColumns = computed(() => {
  const firstRow = latestRows.value[0]
  return firstRow ? Object.keys(firstRow) : []
})
const displayedLatestColumns = computed(() => {
  const visible = visibleResultColumns.value.filter(column => latestColumns.value.includes(column))
  return visible.length ? visible : latestColumns.value.slice(0, 12)
})
const pagedLatestRows = computed(() => {
  const start = (resultPage.value - 1) * resultPageSize.value
  return latestRows.value.slice(start, start + resultPageSize.value)
})
const latestRowRangeText = computed(() => {
  const total = latestRows.value.length
  if (total === 0) return '暂无结果'
  const start = (resultPage.value - 1) * resultPageSize.value + 1
  const end = Math.min(start + resultPageSize.value - 1, total)
  return `${start}-${end} / ${total}`
})
const latestResultSummary = computed(() => {
  if (!latestAssistant.value) return '等待查询'
  if (latestAssistant.value.status === 'error') return '本次运行失败，可切换到分析链路查看出错阶段。'
  if (latestRows.value.length === 0) return '本次查询没有返回匹配数据，请尝试调整筛选条件或时间范围。'
  return `共 ${latestRows.value.length} 行，${latestColumns.value.length} 列。支持翻页查看完整结果。`
})

onMounted(async () => {
  await loadAgents()
  await refreshAgentScopedData()
})

watch(agentId, async (id) => {
  if (loading.value) return
  cancelActiveStream()
  localStorage.setItem('wenqu_agent_id', String(id))
  resetConversation()
  await refreshAgentScopedData()
})

watch(latestAssistant, () => {
  resultPage.value = 1
})

watch(resultPageSize, () => {
  resultPage.value = 1
})

watch(latestRows, (rows) => {
  const maxPage = Math.max(1, Math.ceil(rows.length / resultPageSize.value))
  if (resultPage.value > maxPage) resultPage.value = maxPage
  resetVisibleColumns()
})

async function loadAgents() {
  try {
    agents.value = await fetchAgents()
    if (agents.value.length > 0 && !agents.value.some(agent => agent.id === agentId.value)) {
      agentId.value = agents.value[0].id
    }
  } catch {
    ElMessage.error('智能体配置加载失败，请确认后端服务已启动')
    agents.value = []
  }
}

async function refreshAgentScopedData() {
  try {
    datasources.value = await fetchDatasources(agentId.value)
    if (datasources.value.length > 0) {
      datasourceId.value = datasources.value[0].id
    } else {
      datasourceId.value = null
    }
  } catch {
    ElMessage.error('数据源加载失败，请确认后端服务已启动')
    datasources.value = []
    datasourceId.value = null
  }
  await loadSemanticLabels()
  await loadSessions()
}

async function loadSemanticLabels() {
  try {
    const domains = await fetchSemanticDomains(agentId.value)
    const domain = domains[0]
    if (!domain?.id) {
      semanticLabels.value = defaultSemanticLabels()
      return
    }
    const assets = await fetchSemanticAssets(domain.id)
    semanticLabels.value = buildSemanticLabels(assets)
  } catch {
    semanticLabels.value = defaultSemanticLabels()
  }
}

function formatTime(t: string) {
  if (!t) return ''
  const d = new Date(t)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function loadSessions() {
  try { sessions.value = await fetchSessions(agentId.value) } catch { sessions.value = [] }
}

function cancelActiveStream() {
  activeRunId += 1
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  setLoading(false)
}

function setLoading(value: boolean) {
  loading.value = value
  setChatBusy(value)
}

function resetConversation() {
  sessionId.value = ''
  streamState.value = createChatStreamState()
}

function newSession() {
  cancelActiveStream()
  resetConversation()
}

function useQuickQuery(query: string) {
  inputText.value = query
}

async function copyLatestSql() {
  if (!latestSql.value) return
  try {
    await navigator.clipboard.writeText(latestSql.value)
    ElMessage.success('SQL 已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择 SQL')
  }
}

function downloadResults() {
  if (latestRows.value.length === 0) return
  const columns = Object.keys(latestRows.value[0])
  const escapeCsv = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`
  const csv = [
    columns.map(escapeCsv).join(','),
    ...latestRows.value.map(row => columns.map(column => escapeCsv(row[column])).join(',')),
  ].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'wenqu-query-result.csv'
  link.click()
  URL.revokeObjectURL(url)
}

function rerunLatestQuestion() {
  if (!latestUserQuestion.value || loading.value) return
  inputText.value = latestUserQuestion.value
  handleSend()
}

function resetVisibleColumns() {
  visibleResultColumns.value = latestColumns.value.slice(0, 12)
}

function statusText(status: string) {
  if (status === 'done') return '已完成'
  if (status === 'running') return '处理中'
  return '等待执行'
}

function displayStepLabel(step: ChatReasoningStep) {
  if (step.node === 'semantic_runtime_recall') return '知识召回'
  if (step.node === 'schema_recall') return '数据定位'
  return step.label === '语义运行时' ? '知识召回' : step.label
}

async function loadSession(sid: string) {
  if (loading.value) {
    ElMessage.warning('当前对话正在生成，请等待完成后再切换会话')
    return
  }
  cancelActiveStream()
  const loadRunId = activeRunId
  sessionId.value = sid
  streamState.value = createChatStreamState()
  try {
    const history = await fetchHistory(agentId.value, sid)
    if (loadRunId !== activeRunId || sessionId.value !== sid) return
    streamState.value = {
      ...streamState.value,
      messages: history.map((item, index) => historyToMessage(item, sid, index)),
    }
    scrollToBottom()
  } catch { /* empty */ }
}

async function handleDeleteSession(sid: string) {
  if (loading.value) {
    ElMessage.warning('当前对话正在生成，请等待完成后再删除会话')
    return
  }
  try {
    await ElMessageBox.confirm('确定删除该会话？', '提示', { type: 'warning' })
    await deleteSession(agentId.value, sid)
    if (sessionId.value === sid) newSession()
    await loadSessions()
  } catch { /* cancelled */ }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

function maybeScrollToBottom() {
  if (shouldAutoScroll.value) {
    scrollToBottom()
  } else {
    hasUnreadStream.value = true
  }
}

function isNearMessageBottom() {
  const el = messagesRef.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 96
}

function handleMessagesScroll() {
  shouldAutoScroll.value = isNearMessageBottom()
  if (shouldAutoScroll.value) hasUnreadStream.value = false
}

function jumpToLatest() {
  shouldAutoScroll.value = true
  hasUnreadStream.value = false
  scrollToBottom()
}

function historyToMessage(item: HistoryItem, sid: string, index: number): ChatMessage {
  if (item.role === 'assistant') {
    return {
      id: `history-${sid}-${index}`,
      role: 'assistant',
      content: item.content,
      status: 'complete',
      chainCollapsed: true,
      showErrorDetail: false,
      sql: item.compiled_sql || item.sql_text,
      logic_form: item.logic_form,
      sql_result: item.sql_result,
      plan: item.plan_payload,
      semantic_check: item.semantic_check,
      python_result: item.python_result,
      report_payload: item.report_payload,
      steps: (item.reasoning_trace || []).map(step => ({
        node: step.node,
        label: step.label,
        status: step.status === 'running' || step.status === 'pending' ? step.status : 'done',
        reasoning: step.reasoning || '',
        showReasoning: false,
        output: step.output || null,
        summary: step.summary || '',
      })),
    }
  }
  return {
    id: `history-${sid}-${index}`,
    role: 'user',
    content: item.content,
    steps: [],
  }
}

function toggleReasoning(messageId: string, node: string) {
  streamState.value = toggleAssistantReasoning(streamState.value, messageId, node)
}

function togglePythonCode(messageId: string, node: string) {
  streamState.value = toggleAssistantPythonCode(streamState.value, messageId, node)
}

function canShowPythonCode(step: ChatReasoningStep) {
  return step.node === 'python_generate' && !!getOutputString(step.output || {}, 'python_code')
}

function pythonSummarySuffix(step: ChatReasoningStep) {
  const tasks = getOutputArray(step.output || {}, 'generated_tasks').length
  return ` · ${tasks} 个任务 · 点击${step.showPythonCode ? '收起' : '查看'}`
}

function toggleChain(messageId: string) {
  streamState.value = toggleAssistantChain(streamState.value, messageId)
}

function toggleErrorDetail(messageId: string) {
  streamState.value = toggleAssistantErrorDetail(streamState.value, messageId)
}

function isAssistantStreaming(message: ChatMessage) {
  return message.role === 'assistant' && !!message.status && message.status !== 'complete'
}

function shouldShowAnswerCard(message: ChatMessage) {
  return message.role === 'assistant' && !isAssistantStreaming(message)
}

function getOutputValue(output: Record<string, unknown>, key: string) {
  return output[key]
}

function getOutputString(output: Record<string, unknown>, key: string) {
  const value = output[key]
  return typeof value === 'string' ? value : ''
}

function getOutputObject(output: Record<string, unknown>, key: string) {
  const value = output[key]
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function formatJson(value: Record<string, unknown> | null) {
  return value ? JSON.stringify(value, null, 2) : ''
}

function getOutputStrings(output: Record<string, unknown>, key: string) {
  const value = output[key]
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function getOutputArray(output: Record<string, unknown> | null, key: string) {
  if (!output) return []
  const value = output[key]
  return Array.isArray(value) ? value : []
}

function hasOutputKey(output: Record<string, unknown>, key: string) {
  return Object.prototype.hasOwnProperty.call(output, key)
}

function stepDetails(step: ChatReasoningStep) {
  const output = step.output || {}
  const details: Array<{ label: string; value: string }> = []
  if (step.node === 'semantic_runtime_recall') {
    const counts = getOutputObject(output, 'runtime_counts')
    if (counts) {
      details.push({ label: '指标数', value: String(counts.metrics ?? 0) })
      details.push({ label: '字段/维度', value: String(counts.dimensions ?? 0) })
      details.push({ label: '规则', value: String(counts.rules ?? 0) })
      details.push({ label: '模板', value: String(counts.templates ?? 0) })
    }
    details.push({ label: '召回资产', value: `${String(output.count ?? 0)} 条` })
  } else if (step.node === 'schema_recall') {
    const scope = getOutputObject(output, 'schema_scope')
    details.push({ label: '候选表', value: `${getOutputArray(output, 'matched_tables').length} 张` })
    details.push({ label: '候选字段', value: `${getOutputArray(output, 'matched_columns').length} 个` })
    details.push({ label: '关联提示', value: `${getOutputArray(output, 'likely_joins').length} 条` })
    if (scope) details.push({ label: '定位模式', value: scope.fallback_used ? '已采集表兜底' : '语义引导' })
  } else if (step.node === 'nl2lf_generate') {
    details.push({ label: '指标', value: arraySummary(getOutputArray(output, 'metrics')) || '未识别' })
    details.push({ label: '维度', value: arraySummary(getOutputArray(output, 'dimensions')) || '无' })
    details.push({ label: '过滤', value: `${getOutputArray(output, 'filters').length} 个` })
    if (output.limit !== null && output.limit !== undefined) {
      details.push({ label: 'Limit', value: String(output.limit) })
    }
  } else if (step.node === 'lf_validate') {
    details.push({ label: '结果', value: output.valid === true ? '通过' : '未通过' })
    details.push({ label: '使用资产', value: `${getOutputArray(output, 'used_assets').length} 个` })
  } else if (step.node === 'lf_to_sql_compile' || step.node === 'nl2sql_fallback') {
    details.push({ label: '策略', value: String(output.strategy || (step.node === 'nl2sql_fallback' ? 'nl2sql_fallback' : 'logic_form')) })
    details.push({ label: '使用资产', value: `${getOutputArray(output, 'used_assets').length} 个` })
    if (output.reason) details.push({ label: '原因', value: String(output.reason) })
  } else if (step.node === 'sql_execute') {
    details.push({ label: '返回行数', value: `${String(output.row_count ?? 0)} 行` })
    details.push({ label: '字段数', value: `${getOutputArray(output, 'columns').length} 列` })
  } else if (step.node === 'semantic_check') {
    details.push({ label: '一致性', value: output.valid === true ? '通过' : '未通过' })
    const checked = getOutputObject(output, 'checked_items')
    if (checked) {
      details.push({ label: '检查指标', value: arraySummary(getOutputArray(checked, 'metrics')) || '无' })
      details.push({ label: '检查维度', value: arraySummary(getOutputArray(checked, 'dimensions')) || '无' })
    }
  } else if (step.node === 'planner') {
    details.push({ label: '分析模式', value: String(output.mode_label || '本地基础画像') })
    details.push({ label: '结果规模', value: `${String(output.row_count ?? 0)} 行 / ${String(output.column_count ?? 0)} 列` })
    details.push({ label: '数值字段', value: `${getOutputArray(output, 'numeric_columns').length} 个` })
    details.push({ label: '维度字段', value: `${getOutputArray(output, 'dimension_columns').length} 个` })
  } else if (step.node === 'python_generate') {
    details.push({ label: '执行范围', value: String(output.analysis_scope || 'SQL 结果集基础统计') })
    details.push({ label: '脚本长度', value: `${String(output.code_length ?? 0)} 字符` })
    details.push({ label: '生成任务', value: `${getOutputArray(output, 'generated_tasks').length} 个` })
  } else if (step.node === 'python_analyze') {
    details.push({ label: '状态', value: String(output.status || 'unknown') })
    details.push({ label: '计算项', value: `${getOutputArray(output, 'computed_items').length} 个` })
    details.push({ label: '数值统计', value: `${getOutputArray(output, 'metrics').length} 个字段` })
    details.push({ label: '维度识别', value: `${getOutputArray(output, 'dimensions').length} 个字段` })
  } else if (step.node === 'report_generator') {
    details.push({ label: '报告模式', value: String(output.mode_label || '结构化报告') })
    details.push({ label: '结果行数', value: `${String(output.row_count ?? 0)} 行` })
    details.push({ label: '报告段落', value: `${getOutputArray(output, 'sections').length} 段` })
  }
  return details
}

function stepListDetails(step: ChatReasoningStep) {
  const output = step.output || {}
  const blocks: Array<{ label: string; items: string[] }> = []
  if (step.node === 'semantic_runtime_recall') {
    const assets = getOutputArray(output, 'matched_assets')
      .map(item => formatMatchedAsset(item))
      .filter(Boolean)
      .slice(0, 6)
    if (assets.length) blocks.push({ label: '命中的语义资产', items: assets })
    const metrics = getOutputArray(output, 'available_metrics')
      .map(item => formatAvailableMetric(item))
      .filter(Boolean)
      .slice(0, 6)
    if (metrics.length) blocks.push({ label: '当前可用指标', items: metrics })
  }
  if (step.node === 'schema_recall') {
    const tables = getOutputArray(output, 'matched_tables')
      .map(item => formatMatchedTable(item))
      .filter(Boolean)
      .slice(0, 6)
    const columns = getOutputArray(output, 'matched_columns')
      .map(item => formatMatchedColumn(item))
      .filter(Boolean)
      .slice(0, 10)
    const joins = getOutputArray(output, 'likely_joins')
      .map(item => formatJoinHint(item))
      .filter(Boolean)
      .slice(0, 6)
    if (tables.length) blocks.push({ label: '候选表', items: tables })
    if (columns.length) blocks.push({ label: '候选字段', items: columns })
    if (joins.length) blocks.push({ label: '关联提示', items: joins })
  }
  if (step.node === 'lf_validate' || step.node === 'semantic_check') {
    const errors = getOutputArray(output, 'errors').map(String)
    const warnings = getOutputArray(output, 'warnings').map(String)
    if (errors.length) blocks.push({ label: '错误', items: errors })
    if (warnings.length) blocks.push({ label: '提醒', items: warnings })
  }
  if (step.node === 'lf_to_sql_compile' || step.node === 'nl2sql_fallback') {
    const assets = getOutputArray(output, 'used_assets').map(String)
    const warnings = getOutputArray(output, 'warnings').map(String)
    if (assets.length) blocks.push({ label: '使用资产', items: assets.slice(0, 8) })
    if (warnings.length) blocks.push({ label: '提醒', items: warnings })
  }
  if (step.node === 'sql_execute') {
    const columns = getOutputArray(output, 'columns').map(String)
    if (columns.length) blocks.push({ label: '返回字段', items: columns.slice(0, 12) })
  }
  if (step.node === 'planner') {
    const numeric = getOutputArray(output, 'numeric_columns').map(String)
    const dimensions = getOutputArray(output, 'dimension_columns').map(String)
    const limitations = getOutputArray(output, 'limitations').map(String)
    if (numeric.length) blocks.push({ label: '计划分析的数值字段', items: numeric.slice(0, 8) })
    if (dimensions.length) blocks.push({ label: '计划分析的维度字段', items: dimensions.slice(0, 8) })
    if (limitations.length) blocks.push({ label: '当前阶段边界', items: limitations })
  }
  if (step.node === 'python_generate') {
    const tasks = getOutputArray(output, 'generated_tasks').map(String)
    if (tasks.length) blocks.push({ label: '脚本会执行', items: tasks })
  }
  if (step.node === 'python_analyze') {
    const computed = getOutputArray(output, 'computed_items').map(String)
    const dimensions = getOutputArray(output, 'dimensions').map(String)
    if (computed.length) blocks.push({ label: '已计算内容', items: computed })
    if (dimensions.length) blocks.push({ label: '识别到的维度字段', items: dimensions.slice(0, 8) })
  }
  if (step.node === 'report_generator') {
    const limitations = getOutputArray(output, 'limitations').map(String)
    if (limitations.length) blocks.push({ label: '报告边界', items: limitations })
  }
  return blocks
}

function arraySummary(items: unknown[]) {
  return items.map(String).filter(Boolean).slice(0, 4).join(', ')
}

function formatMatchedAsset(item: unknown) {
  if (!item || typeof item !== 'object') return ''
  const record = item as Record<string, unknown>
  const key = String(record.key || '')
  const type = String(record.type || '')
  const score = record.score === undefined ? '' : ` · score ${record.score}`
  const content = String(record.content || '').slice(0, 48)
  return [key || type, content].filter(Boolean).join('：') + score
}

function formatAvailableMetric(item: unknown) {
  if (!item || typeof item !== 'object') return ''
  const record = item as Record<string, unknown>
  const key = String(record.key || '')
  const name = String(record.name || '')
  const dimensions = Array.isArray(record.dimensions) ? record.dimensions.map(String).slice(0, 4).join(', ') : ''
  return `${name || key}${key ? ` (${key})` : ''}${dimensions ? ` · 可按 ${dimensions}` : ''}`
}

function formatMatchedTable(item: unknown) {
  if (!item || typeof item !== 'object') return ''
  const record = item as Record<string, unknown>
  const name = String(record.table_name || record.table || '')
  const comment = String(record.table_comment || record.comment || '')
  const reason = String(record.reason || '')
  return `${comment || name}${name ? ` (${name})` : ''}${reason ? ` · ${reason}` : ''}`
}

function formatMatchedColumn(item: unknown) {
  if (!item || typeof item !== 'object') return ''
  const record = item as Record<string, unknown>
  const table = String(record.table_name || record.table || '')
  const column = String(record.column_name || record.column || '')
  const comment = String(record.column_comment || record.comment || '')
  return `${comment || column}${table && column ? ` (${table}.${column})` : ''}`
}

function formatJoinHint(item: unknown) {
  if (!item || typeof item !== 'object') return ''
  const record = item as Record<string, unknown>
  return [record.left, record.right].filter(Boolean).join(' = ')
}

function compactSql(sql: string) {
  return sql.replace(/\s+/g, ' ').trim().slice(0, 80)
}

function panelResultTitle(message: ChatMessage) {
  const rows = message.sql_result?.length || 0
  if (rows === 0) return '结果表'
  return `结果表 · ${rows} 行`
}

function answerSummaryLines(message: ChatMessage) {
  const clean = cleanAnswerContent(message.content || '')
  if (clean) {
    return clean
      .split(/\n+/)
      .map(line => line.trim())
      .filter(Boolean)
      .slice(0, 3)
  }
  return [buildResultNarrative(message)]
}

function cleanAnswerContent(content: string) {
  const text = content.trim()
  if (!text) return ''
  if (/^SQL\s*[:：]/i.test(text)) return ''
  const lines = text.split(/\r?\n/)
  return lines
    .filter((line) => {
      const trimmed = line.trim()
      if (!trimmed) return true
      if (/^SQL\s*[:：]/i.test(trimmed)) return false
      if (/^共\s*\d+\s*条结果\s*[:：]?/.test(trimmed)) return false
      if (/^\|.*\|$/.test(trimmed)) return false
      if (/^\.\.\.\s*共\s*\d+\s*条/.test(trimmed)) return false
      return true
    })
    .join('\n')
    .trim()
}

function buildResultNarrative(message: ChatMessage) {
  const rows = message.sql_result || []
  if (rows.length === 0) return '查询完成，未返回匹配数据。'
  const highlights = resultHighlights(message)
  if (rows.length === 1 && highlights.length >= 2) {
    const dimension = highlights.find(item => !item.numeric)
    const metric = highlights.find(item => item.numeric)
    if (dimension && metric) return `${dimension.value}的 ${metric.label}为 ${metric.value}。`
  }
  return `查询完成，共 ${rows.length} 条结果。关键字段已整理在下方，完整明细可以在右侧“结果”中查看。`
}

function resultHighlights(message: ChatMessage) {
  const row = message.sql_result?.[0]
  if (!row) return []
  return Object.keys(row).slice(0, 4).map((key) => {
    const value = row[key]
    return {
      key,
      label: columnTitle(key),
      value: formatDisplayValue(key, value),
      numeric: isNumericValue(value),
    }
  })
}

function formatDisplayValue(key: string, value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (isNumericValue(value)) {
    const numeric = Number(value)
    if (shouldFormatPercent(key, numeric)) return `${(numeric * 100).toFixed(2)}%`
    return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(numeric)
  }
  return String(value)
}

function formatCellValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function isLongCellValue(value: unknown) {
  return formatCellValue(value).length > 48
}

function previewCellValue(column: string, value: unknown) {
  cellDetailTitle.value = columnTitle(column)
  cellDetailValue.value = formatCellValue(value)
  showCellDetail.value = true
}

function openLatestReport() {
  if (!latestReport.value) return
  expandedReport.value = latestReport.value
  showReportDialog.value = true
}

function openReport(message: ChatMessage) {
  if (!message.report_payload) return
  activeResultTab.value = 'report'
  expandedReport.value = message.report_payload
  showReportDialog.value = true
}

function reportTitle(report: Record<string, unknown>) {
  return String(report.title || '查询结果分析')
}

function reportSummary(report: Record<string, unknown>) {
  const text = String(report.summary || '')
  if (text) return text
  const bullets = reportExecutiveBullets(report)
  if (bullets.length) return bullets[0]
  return '暂无摘要。'
}

function reportRowCount(report: Record<string, unknown>) {
  const value = report.row_count
  return typeof value === 'number' ? value : Number(value || 0)
}

function reportStatusText(report: Record<string, unknown>) {
  if (report.status === 'empty') return '空结果'
  if (report.status === 'success') return '分析完成'
  return '报告'
}

function reportGeneratedAt(report: Record<string, unknown>) {
  const raw = String(report.generated_at || '')
  if (!raw) return '-'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString('zh-CN', { hour12: false })
}

function reportHighlights(report: Record<string, unknown>) {
  const highlights = report.highlights
  if (!Array.isArray(highlights)) return []
  return highlights
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map(item => ({
      label: String(item.label || item.field || '指标'),
      value: item.value,
      field: String(item.field || ''),
    }))
}

function reportSections(report: Record<string, unknown>) {
  const sections = report.sections
  if (!Array.isArray(sections)) return []
  return sections
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map(item => ({
      title: String(item.title || '报告段落'),
      items: Array.isArray(item.items) ? item.items.map(value => String(value)).filter(Boolean) : [],
    }))
    .filter(section => section.items.length > 0)
}

function reportExecutiveBullets(report: Record<string, unknown>) {
  const executive = report.executive_summary
  if (executive && typeof executive === 'object' && !Array.isArray(executive)) {
    const bullets = (executive as Record<string, unknown>).bullets
    if (Array.isArray(bullets)) return bullets.map(item => String(item)).filter(Boolean)
  }
  return reportSections(report).find(section => section.title === '执行摘要')?.items || []
}

function reportExecutivePoints(report: Record<string, unknown>) {
  const executive = report.executive_summary
  if (executive && typeof executive === 'object' && !Array.isArray(executive)) {
    const points = (executive as Record<string, unknown>).key_points
    if (Array.isArray(points)) {
      return points
        .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
        .map(item => ({
          label: String(item.label || '指标'),
          value: item.value,
        }))
    }
  }
  return reportHighlights(report).map(item => ({ label: item.label, value: item.value }))
}

function reportBackground(report: Record<string, unknown>) {
  const background = report.background
  if (background && typeof background === 'object' && !Array.isArray(background)) {
    const paragraphs = (background as Record<string, unknown>).paragraphs
    if (Array.isArray(paragraphs)) return paragraphs.map(item => String(item)).filter(Boolean)
  }
  return reportSections(report).find(section => section.title === '分析背景与用户诉求')?.items || []
}

function reportProcessSteps(report: Record<string, unknown>) {
  const process = report.analysis_process
  if (process && typeof process === 'object' && !Array.isArray(process)) {
    const steps = (process as Record<string, unknown>).steps
    if (Array.isArray(steps)) {
      return steps
        .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
        .map(item => ({
          title: String(item.title || '分析步骤'),
          text: String(item.text || ''),
          result: String(item.result || ''),
        }))
    }
  }
  return reportSections(report)
    .find(section => section.title === '数据分析过程' || section.title === '分析步骤')
    ?.items.map((item, index) => ({ title: `步骤${index + 1}`, text: item, result: '' })) || []
}

function reportInterpretation(report: Record<string, unknown>) {
  const interpretation = report.interpretation
  if (interpretation && typeof interpretation === 'object' && !Array.isArray(interpretation)) {
    const bullets = (interpretation as Record<string, unknown>).bullets
    if (Array.isArray(bullets)) return bullets.map(item => String(item)).filter(Boolean)
  }
  return reportSections(report).find(section => section.title === '结果解读')?.items || []
}

function reportSuggestions(report: Record<string, unknown>) {
  const suggestions = report.suggestions
  if (suggestions && typeof suggestions === 'object' && !Array.isArray(suggestions)) {
    const items = (suggestions as Record<string, unknown>).items
    if (Array.isArray(items)) return items.map(item => String(item)).filter(Boolean)
  }
  return reportSections(report).find(section => section.title === '建议与后续行动')?.items || []
}

function reportCharts(report: Record<string, unknown>) {
  const charts = report.charts
  if (!Array.isArray(charts)) return []
  return charts
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map(item => ({
      title: String(item.title || '图表'),
      subtitle: String(item.subtitle || ''),
      data: Array.isArray(item.data)
        ? item.data
            .filter((row): row is Record<string, unknown> => !!row && typeof row === 'object')
            .map(row => ({ label: String(row.label ?? '-'), value: row.value }))
        : [],
    }))
    .filter(item => item.data.length > 0)
}

function reportTables(report: Record<string, unknown>) {
  const tables = report.tables
  if (!Array.isArray(tables)) return []
  return tables
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map(item => {
      const columns = Array.isArray(item.columns) ? item.columns.map(column => String(column)) : []
      const rows = Array.isArray(item.rows)
        ? item.rows.filter((row): row is Record<string, unknown> => !!row && typeof row === 'object')
        : []
      return {
        title: String(item.title || '结果明细'),
        columns,
        rows,
      }
    })
    .filter(item => item.columns.length > 0 && item.rows.length > 0)
}

function barPercent(value: unknown, rows: { value: unknown }[]) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 0
  const max = Math.max(...rows.map(row => Number(row.value)).filter(Number.isFinite), 0)
  if (!max) return 0
  return Math.max(4, Math.min(100, (numeric / max) * 100))
}

function reportPythonResult(report: Record<string, unknown>) {
  const value = report.python_result
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function formatReportValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (isNumericValue(value)) return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(Number(value))
  return String(value)
}

function renderCellText(column: string, value: unknown) {
  if (isNumericValue(value)) return formatDisplayValue(column, value)
  const text = formatCellValue(value)
  return text.length > 64 ? `${text.slice(0, 64)}...` : text
}

function isNumericValue(value: unknown) {
  if (typeof value === 'number') return Number.isFinite(value)
  if (typeof value !== 'string' || value.trim() === '') return false
  return Number.isFinite(Number(value))
}

function shouldFormatPercent(key: string, value: number) {
  if (Math.abs(value) > 1) return false
  return /rate|ratio|percent|pct|probability|pd|dti/i.test(key)
}

function columnTitle(key: string) {
  return semanticLabels.value[key] || defaultSemanticLabels()[key] || key
}

function errorStageText(message: ChatMessage) {
  const node = message.error?.node || ''
  if (node === 'semantic_runtime_recall') return '知识召回'
  if (node === 'schema_recall') return '数据定位'
  if (node === 'nl2lf_generate') return 'LogicForm 生成'
  if (node === 'lf_validate' || /语义校验|校验失败/.test(message.error?.message || '')) return '语义校验'
  if (node === 'lf_to_sql_compile') return 'SQL 编译'
  if (node === 'sql_execute') return 'SQL 执行'
  return message.error?.label || '后端处理'
}

function friendlyErrorSummary(message: ChatMessage) {
  const raw = `${message.error?.message || ''} ${message.error?.detail || ''}`.trim()
  if (!raw) return '本次请求未能完成，请稍后重试。'
  if (/不支持维度/.test(raw)) return '当前指标不支持按这个维度展开。'
  if (/时间字段|time_field|时间口径/.test(raw)) return '当前查询缺少可用的时间字段或时间口径。'
  if (/SQL为空/.test(raw)) return '没有生成可执行 SQL，请先检查语义配置和 LogicForm。'
  if (/sql/i.test(raw) && /执行|失败|error|异常/.test(raw)) return 'SQL 执行失败，查询未成功返回结果。'
  if (/未返回匹配数据|没有返回匹配数据|0 条结果/.test(raw)) return '查询成功执行，但没有匹配到结果数据。'
  return message.error?.message || raw
}

function friendlyErrorSuggestion(message: ChatMessage) {
  const raw = `${message.error?.message || ''} ${message.error?.detail || ''}`.trim()
  if (/不支持维度/.test(raw)) return '建议更换一个支持的维度，或到语义层里为该指标补充可切维度配置。'
  if (/时间字段|time_field|时间口径/.test(raw)) return '建议检查指标默认时间字段、映射层时间字段，以及问题里引用的时间口径是否一致。'
  if (/SQL为空/.test(raw)) return '建议先查看分析链路里的 LogicForm 与校验结果，确认指标、维度和规则是否能成功编译。'
  if (/sql/i.test(raw) && /执行|失败|error|异常/.test(raw)) return '建议优先检查生成 SQL、表字段映射和数据源表结构是否一致。'
  return '可以先查看下方技术明细和右侧分析链路，定位具体出错节点。'
}

function showRawErrorMessage(message: ChatMessage) {
  return !/不支持维度|时间字段|SQL为空|未返回匹配数据|没有返回匹配数据/.test(
    `${message.error?.message || ''} ${message.error?.detail || ''}`,
  )
}

function buildSemanticLabels(assets: Record<string, Record<string, unknown>[]>) {
  const labels = defaultSemanticLabels()
  for (const metric of assets.metric || []) {
    const key = String(metric.metric_key || '')
    const name = String(metric.name || '')
    if (key && name) labels[key] = name
  }
  for (const mapping of assets.mapping || []) {
    const key = String(mapping.asset_key || '')
    if (key && !labels[key]) labels[key] = humanizeField(key)
  }
  return labels
}

function defaultSemanticLabels() {
  return {
    approval_rate: '审批通过率',
    application_count: '申请笔数',
    disbursement_amount: '放款金额',
    outstanding_balance: '贷款余额',
    m1_plus_rate: 'M1+逾期率',
    mob: '账龄',
    dpd: '逾期天数',
    vintage: '放款批次',
    pd: '预测违约概率',
    dti: '负债收入比',
    writeoff_amount: '核销金额',
    collection_recovery_rate: '催收回收率',
    product_type: '产品类型',
    application_product_type: '申请产品类型',
    application_region: '申请地区',
    application_risk_grade: '申请风险等级',
    region: '地区',
    channel: '渠道',
    risk_grade: '风险等级',
    overdue_bucket: '逾期阶段',
    assigned_team: '催收团队',
    collection_strategy: '催收策略',
    overdue_bucket_at_entry: '入催逾期阶段',
    customer_segment: '客户分层',
  } as Record<string, string>
}

function humanizeField(key: string) {
  return key
    .split('_')
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function handleSend() {
  const q = inputText.value.trim()
  if (!q || loading.value) return
  const runId = activeRunId + 1
  activeRunId = runId

  streamState.value = startChatRun(streamState.value, { runId, question: q })
  inputText.value = ''
  setLoading(true)
  shouldAutoScroll.value = true
  hasUnreadStream.value = false
  scrollToBottom()

  abortController = sendMessageStream(
    {
      question: q,
      agent_id: agentId.value,
      datasource_id: datasourceId.value,
      session_id: sessionId.value || undefined,
    },
    (evt) => {
      if (runId !== activeRunId) return
      streamState.value = reduceChatStreamEvent(streamState.value, {
        runId,
        event: evt.event,
        data: evt.data,
      })
      const nextSessionId = evt.data.session_id
      if (typeof nextSessionId === 'string' && nextSessionId) sessionId.value = nextSessionId

      if (evt.event === 'done' || evt.event === 'error') {
        setLoading(false)
        abortController = null
        loadSessions()
      }
      maybeScrollToBottom()
    },
  )
}

onUnmounted(() => {
  cancelActiveStream()
})
</script>

<style scoped>
.chat-layout {
  display: grid;
  grid-template-columns: 280px minmax(460px, 1fr) 430px;
  height: calc(100vh - 68px);
  width: 100%;
  max-width: 100%;
  min-width: 0;
  min-height: 0;
  background: var(--wq-surface);
  overflow: hidden;
}

.session-sidebar {
  min-width: 0;
  min-height: 0;
  background: #fbfcff;
  border-right: 1px solid var(--wq-border);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 20px 18px 10px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.new-chat-button {
  flex: 1;
  justify-content: center;
  height: 36px;
}

.session-search {
  padding: 0 18px 16px;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 18px 14px;
}

.session-group {
  margin: 2px 0 8px;
  color: var(--wq-subtle);
  font-size: 12px;
  font-weight: 680;
}

.session-item {
  padding: 12px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 6px;
  position: relative;
  background: transparent;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.session-item:hover {
  background: #f2f5fb;
}

.session-item.active {
  background: var(--wq-primary-soft);
  border-color: #c8d6ff;
  box-shadow: inset 3px 0 0 var(--wq-primary);
}

.session-item.disabled { cursor: not-allowed; opacity: 0.65; }
.session-item.disabled:hover { background: transparent; }

.session-title {
  font-size: 14px;
  line-height: 1.35;
  color: #344054;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 24px;
}

.session-item.active .session-title {
  color: var(--wq-primary);
  font-weight: 650;
}

.session-meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: var(--wq-subtle);
  margin-top: 8px;
}

.session-delete {
  position: absolute;
  right: 10px;
  top: 13px;
  color: var(--wq-subtle);
  display: none;
}

.session-item:hover .session-delete { display: block; }
.session-delete:hover { color: var(--wq-danger); }

.empty-sessions {
  text-align: center;
  color: var(--wq-subtle);
  padding: 48px 0;
  font-size: 13px;
}

.session-footer {
  padding: 12px 18px 18px;
  border-top: 1px solid var(--wq-border);
}

.session-footer span {
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1.5;
}

.chat-container {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--wq-surface);
  position: relative;
}

.workspace-toolbar {
  min-height: 70px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--wq-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex: 0 0 auto;
  min-width: 0;
}

.workspace-title {
  min-width: 0;
}

.workspace-title h2 {
  font-size: 17px;
  line-height: 1.25;
  color: var(--wq-text);
  font-weight: 760;
  letter-spacing: 0;
}

.workspace-title p {
  margin-top: 5px;
  color: var(--wq-subtle);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-controls {
  display: flex;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.chat-messages {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 26px 20px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfcff 100%);
}

.jump-latest-button {
  position: absolute;
  right: 24px;
  bottom: 104px;
  z-index: 5;
  padding: 7px 12px;
  border: 1px solid #c7d7fe;
  border-radius: 999px;
  background: #fff;
  color: var(--wq-primary);
  font-size: 12px;
  font-weight: 680;
  box-shadow: 0 10px 24px rgba(63, 111, 243, 0.16);
  cursor: pointer;
}

.jump-latest-button:hover {
  background: #f5f8ff;
}

.empty-hint {
  width: min(620px, 100%);
  margin: 12vh auto 0;
  text-align: center;
  color: var(--wq-muted);
}

.empty-icon {
  width: 58px;
  height: 58px;
  margin: 0 auto 18px;
  display: grid;
  place-items: center;
  border-radius: 18px;
  color: var(--wq-primary);
  background: var(--wq-primary-soft);
  border: 1px solid #d9e3ff;
}

.empty-hint h3 {
  color: var(--wq-text);
  font-size: 18px;
  line-height: 1.35;
  font-weight: 720;
}

.empty-hint p {
  margin-top: 8px;
  line-height: 1.55;
  font-size: 14px;
}

.empty-examples {
  margin-top: 18px;
  display: flex;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
}

.message {
  margin-bottom: 24px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
}

.message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  color: #fff;
  font-size: 13px;
  font-weight: 760;
  background: #5b7cf6;
}

.message.assistant .message-avatar {
  color: var(--wq-primary);
  background: var(--wq-primary-soft);
  border: 1px solid #d9e3ff;
}

.message.user .message-content {
  background: #f3f6ff;
  color: #24324b;
  border: 1px solid #dce6ff;
  border-radius: 10px;
  max-width: min(560px, calc(100% - 56px));
}

.message.assistant .message-content {
  background: transparent;
  border-radius: 0;
}

.message-content {
  max-width: min(760px, calc(100% - 56px));
  min-width: 0;
  padding: 10px 0;
  overflow: hidden;
}

.message.user .message-content {
  padding: 10px 14px;
}

.message-content .meta {
  margin-bottom: 10px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.message-content .text {
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: #344054;
  font-size: 14px;
}

.answer-card {
  max-width: 100%;
  background: #fff;
  border: 1px solid #dce6f5;
  border-radius: 8px;
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
  overflow: hidden;
}

.run-error-card {
  max-width: 100%;
  background: #fff7f7;
  border: 1px solid #fecaca;
  border-radius: 8px;
  box-shadow: 0 12px 28px rgba(185, 28, 28, 0.08);
  overflow: hidden;
}

.run-error-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px 18px 12px;
  border-bottom: 1px solid #fecaca;
  background: #fff1f2;
  color: #b42318;
}

.run-error-header .el-icon {
  margin-top: 2px;
  font-size: 20px;
}

.run-error-header h3 {
  margin: 0;
  color: #7a271a;
  font-size: 16px;
  line-height: 1.35;
  font-weight: 760;
}

.run-error-header .el-tag {
  margin-left: auto;
  flex: 0 0 auto;
}

.run-error-kicker {
  display: block;
  margin-bottom: 3px;
  color: #d92d20;
  font-size: 11px;
  font-weight: 760;
}

.run-error-message {
  padding: 0;
  color: #7a271a;
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.run-error-body {
  padding: 16px 18px 10px;
}

.run-error-summary {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid #fecdd3;
  border-radius: 6px;
  background: #fff;
  color: #912018;
}

.run-error-summary p {
  margin: 0;
  line-height: 1.6;
}

.run-error-suggestion {
  margin-top: 10px;
  color: #b54708;
  font-size: 12px;
  line-height: 1.6;
}

.run-error-detail-panel {
  padding: 0 18px 12px;
}

.run-error-detail {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid #fed7aa;
  border-radius: 6px;
  background: #fffaf5;
  color: #9a3412;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.run-error-tip {
  padding: 0 18px 16px;
  color: #b54708;
  font-size: 12px;
}

.run-error-actions {
  display: flex;
  gap: 8px;
  padding: 0 18px 12px;
  flex-wrap: wrap;
}

.detail-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 0;
  padding: 0;
  background: transparent;
  color: #b42318;
  font-size: 12px;
  cursor: pointer;
}

.answer-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 16px 18px 12px;
  border-bottom: 1px solid var(--wq-border);
  background: #f8fbff;
}

.answer-kicker {
  display: block;
  margin-bottom: 4px;
  color: var(--wq-primary);
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 0;
}

.answer-card h3 {
  margin: 0;
  color: var(--wq-text);
  font-size: 17px;
  line-height: 1.3;
  font-weight: 760;
}

.answer-subtitle {
  margin-top: 6px;
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1.5;
}

.answer-badges {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.answer-body {
  padding: 18px;
  color: #263448;
  font-size: 15px;
}

.answer-summary {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 12px;
  align-items: flex-start;
}

.summary-mark {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: #079455;
  background: #ecfdf3;
  border: 1px solid #abefc6;
}

.answer-copy {
  min-width: 0;
}

.answer-copy p {
  margin: 0;
  color: #263448;
  font-size: 14px;
  line-height: 1.75;
  overflow-wrap: anywhere;
}

.answer-copy p + p {
  margin-top: 8px;
}

.answer-kpi-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}

.answer-kpi {
  min-width: 0;
  padding: 12px;
  border: 1px solid #dbe4f0;
  border-radius: 8px;
  background: #fbfcff;
}

.answer-kpi span,
.answer-kpi code {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.answer-kpi span {
  color: #667085;
  font-size: 12px;
  line-height: 1.35;
}

.answer-kpi strong {
  display: block;
  margin-top: 6px;
  color: #1d2939;
  font-size: 20px;
  line-height: 1.25;
  font-weight: 780;
  overflow-wrap: anywhere;
}

.answer-kpi code {
  margin-top: 5px;
  color: #98a2b3;
  font-size: 11px;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.answer-assets {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 0 18px 18px;
}

.asset-chip {
  min-width: 0;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fbfcff;
  padding: 10px 12px;
  text-align: left;
  cursor: pointer;
}

.asset-chip:hover {
  border-color: #b9c8ff;
  background: var(--wq-primary-soft);
}

.asset-chip span {
  display: block;
  margin-bottom: 5px;
  color: var(--wq-subtle);
  font-size: 12px;
}

.asset-chip strong {
  display: block;
  color: #344054;
  font-size: 13px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message.user .message-content .text {
  color: #24324b;
  line-height: 1.55;
}

.sql-block {
  max-width: 100%;
  margin-top: 12px;
  background: #101828;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
}

.sql-block pre { margin: 0; min-width: 0; }
.sql-block code { color: #e6edf7; font-size: 13px; font-family: "SFMono-Regular", Consolas, monospace; }
.result-table { margin-top: 12px; }

.compact-result {
  padding: 12px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fff;
}

.inline-result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  color: #344054;
  font-size: 13px;
  font-weight: 680;
}

.result-cell-button {
  width: 100%;
  border: 0;
  padding: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  font: inherit;
}

.result-cell-button:hover {
  color: var(--wq-primary);
}

.column-heading {
  display: flex;
  flex-direction: column;
  gap: 1px;
  line-height: 1.35;
}

.column-heading span {
  color: #1d2939;
  font-size: 13px;
  font-weight: 660;
}

.column-heading small {
  color: #98a2b3;
  font-size: 11px;
  font-weight: 400;
  letter-spacing: 0;
}

.chat-input {
  flex: 0 0 auto;
  padding: 16px 20px 18px;
  border-top: 1px solid var(--wq-border);
  background: #fff;
}

.query-composer {
  border: 1px solid #b9c8ff;
  border-radius: 8px;
  padding: 10px;
  background: #fff;
  box-shadow: 0 10px 30px rgba(63, 111, 243, 0.08);
}

.query-composer :deep(.el-textarea__inner) {
  box-shadow: none;
  border-radius: 0;
  min-height: 48px !important;
  padding: 4px 6px;
  resize: none;
}

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 8px;
}

.quick-query-list {
  min-width: 0;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  overflow: hidden;
  padding-bottom: 1px;
}

.quick-query-list .el-button {
  flex: 0 0 auto;
}

.chain-panel {
  max-width: 100%;
  min-width: 0;
  background: #fbfcff;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 16px;
  overflow: hidden;
}

.chain-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.chain-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 680;
  color: var(--wq-text);
}

.chain-collapse {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--wq-subtle);
  font-size: 12px;
  cursor: pointer;
}

.chain-collapse:hover {
  color: var(--wq-primary);
}

.chain-collapsed-summary {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chain-step { margin-bottom: 12px; min-width: 0; }

.step-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  min-width: 0;
}

.step-status { display: flex; align-items: center; }
.step-status.running { color: var(--wq-primary); }
.step-status.done { color: var(--wq-success); }
.step-status.pending { color: var(--wq-subtle); }
.step-label { font-weight: 650; color: #344054; min-width: 80px; }

.step-summary {
  color: var(--wq-subtle);
  font-size: 12px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-summary-button {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.step-summary-button span:first-child {
  color: var(--wq-primary);
  font-weight: 650;
}

.step-summary-button:hover span:first-child { text-decoration: underline; }

.step-reasoning { margin: 6px 0 6px 28px; }

.reasoning-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--wq-subtle);
  cursor: pointer;
  user-select: none;
}

.reasoning-toggle:hover { color: var(--wq-primary); }

.reasoning-content {
  margin-top: 6px;
  padding: 10px 12px;
  background: #f3f6fb;
  border-radius: 6px;
  font-size: 12px;
  color: var(--wq-muted);
  line-height: 1.65;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.step-output {
  max-width: calc(100% - 28px);
  min-width: 0;
  margin: 4px 0 0 28px;
  font-size: 12px;
  color: var(--wq-muted);
}

.output-sql {
  max-width: 100%;
  background: #101828;
  border-radius: 6px;
  padding: 8px;
  margin-top: 6px;
  overflow-x: auto;
}

.output-sql pre { margin: 0; min-width: 0; }
.output-sql code { color: #e6edf7; font-size: 12px; font-family: "SFMono-Regular", Consolas, monospace; }
.output-code-section { margin-top: 6px; }
.output-code-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--wq-primary);
  font-size: 12px;
  cursor: pointer;
}
.output-code-toggle:hover { text-decoration: underline; }
.output-python-code {
  max-height: 320px;
  overflow: auto;
}
.output-stream-text {
  margin-top: 8px;
  border: 1px solid #dbe6f5;
  border-radius: 8px;
  background: #fbfdff;
}

.output-stream-text pre {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  padding: 10px 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.output-stream-text code {
  color: #344054;
  font-size: 12px;
  line-height: 1.65;
  font-family: "SFMono-Regular", Consolas, monospace;
}
.output-result .error { color: var(--wq-danger); }

.output-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
  gap: 6px;
  margin-top: 6px;
}

.output-detail-item {
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid #e4eaf5;
  border-radius: 6px;
  background: #fbfdff;
}

.output-detail-item span {
  display: block;
  color: #8a97ad;
  font-size: 11px;
  line-height: 1.2;
}

.output-detail-item strong {
  display: block;
  margin-top: 3px;
  color: #344054;
  font-size: 12px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.output-list-grid {
  display: grid;
  gap: 6px;
  margin-top: 6px;
}

.output-list-block {
  padding: 8px 10px;
  border: 1px solid #e4eaf5;
  border-radius: 6px;
  background: #fff;
}

.output-list-block > span {
  display: block;
  margin-bottom: 4px;
  color: #667085;
  font-weight: 650;
}

.output-list-block ul {
  margin: 0;
  padding-left: 16px;
  color: #475467;
  line-height: 1.6;
}

.output-list-block li {
  word-break: break-word;
}

.insight-panel {
  min-width: 0;
  border-left: 1px solid var(--wq-border);
  background: #fbfcff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.insight-panel :deep(.el-tabs) {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.insight-panel :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 22px;
  background: #fff;
}

.insight-panel :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 20px;
}

.panel-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 16px;
}

.run-state,
.result-count {
  color: var(--wq-muted);
  font-size: 13px;
  white-space: nowrap;
}

.run-state::before {
  content: "";
  width: 7px;
  height: 7px;
  display: inline-block;
  margin-right: 7px;
  border-radius: 50%;
  background: var(--wq-success);
  vertical-align: 1px;
}

.run-state.running::before {
  background: var(--wq-primary);
}

.panel-timeline {
  border-left: 1px solid var(--wq-border-strong);
  margin-left: 8px;
  padding-left: 18px;
}

.panel-step {
  position: relative;
  display: flex;
  gap: 10px;
  padding-bottom: 22px;
}

.timeline-dot {
  position: absolute;
  left: -25px;
  top: 3px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid var(--wq-subtle);
}

.timeline-dot.done { border-color: var(--wq-success); background: #eaf8f1; }
.timeline-dot.running { border-color: var(--wq-primary); background: var(--wq-primary-soft); }

.panel-step strong {
  display: block;
  color: #344054;
  font-size: 14px;
  line-height: 1.35;
}

.panel-step p {
  margin-top: 5px;
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.panel-empty {
  min-height: 180px;
  display: grid;
  place-items: center;
  padding: 24px;
  color: var(--wq-subtle);
  line-height: 1.6;
  text-align: center;
  border: 1px dashed var(--wq-border-strong);
  border-radius: 8px;
  background: #fff;
}

.panel-sql {
  background: #101828;
  border-radius: 8px;
  padding: 14px;
  overflow-x: auto;
}

.panel-sql pre {
  margin: 0;
}

.panel-sql code {
  color: #e6edf7;
  font-size: 13px;
  line-height: 1.75;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.panel-result {
  display: grid;
  gap: 14px;
}

.result-meta-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fff;
}

.result-meta-card strong {
  display: block;
  color: var(--wq-text);
  font-size: 14px;
  line-height: 1.5;
}

.result-meta-card p {
  margin-top: 4px;
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1.5;
}

.result-column-tools {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.result-grid {
  border-radius: 8px;
  overflow: hidden;
}

.result-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.result-page-hint {
  color: var(--wq-subtle);
  font-size: 12px;
}

.empty-result-card {
  display: grid;
  gap: 10px;
  padding: 16px;
  border: 1px solid #fde68a;
  border-radius: 8px;
  background: #fffbeb;
  color: #92400e;
}

.empty-result-card strong {
  color: #78350f;
  font-size: 14px;
}

.empty-result-card p {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
}

.cell-detail-heading {
  margin-bottom: 12px;
}

.cell-detail strong {
  color: var(--wq-text);
  font-size: 15px;
}

.cell-detail pre {
  margin: 0;
  max-height: 420px;
  overflow: auto;
  padding: 14px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #f8fafc;
  color: #24324b;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.7;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.report-preview {
  display: grid;
  gap: 14px;
}

.report-preview-header {
  padding: 14px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fff;
}

.report-preview-header span,
.report-dialog-title span,
.report-status {
  color: var(--wq-primary);
  font-size: 12px;
  font-weight: 760;
}

.report-preview-header h3,
.report-dialog-title h2 {
  margin-top: 5px;
  color: var(--wq-text);
  font-size: 16px;
  line-height: 1.4;
  font-weight: 760;
}

.report-preview-header p,
.report-mini-section p,
.report-hero p {
  margin-top: 8px;
  color: var(--wq-muted);
  font-size: 13px;
  line-height: 1.65;
}

.report-highlight-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.report-highlight,
.report-card {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fff;
}

.report-highlight span,
.report-card span {
  display: block;
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1.35;
}

.report-highlight strong,
.report-card strong {
  display: block;
  margin-top: 7px;
  color: var(--wq-text);
  font-size: 17px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.report-section-preview,
.report-detail-grid {
  display: grid;
  gap: 12px;
}

.report-mini-section,
.report-section {
  padding: 14px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fff;
}

.report-mini-section strong,
.report-section h3 {
  color: var(--wq-text);
  font-size: 14px;
  line-height: 1.45;
  font-weight: 720;
}

.report-dialog-title h2 {
  font-size: 20px;
}

.report-workspace {
  max-height: min(74vh, 760px);
  overflow-y: auto;
  padding-right: 4px;
  display: grid;
  gap: 16px;
}

.report-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 140px;
  gap: 16px;
  align-items: stretch;
  padding: 18px;
  border: 1px solid #dbe6f5;
  border-radius: 8px;
  background: #f8fbff;
}

.report-hero-meta {
  display: grid;
  place-items: center;
  border-left: 1px solid #dbe6f5;
}

.report-hero-meta strong {
  color: var(--wq-primary);
  font-size: 30px;
  line-height: 1.1;
}

.report-hero-meta span {
  margin-top: 5px;
  color: var(--wq-subtle);
  font-size: 12px;
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.report-card code {
  display: inline-block;
  margin-top: 8px;
  max-width: 100%;
  color: var(--wq-subtle);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.report-detail-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.report-section ul {
  margin: 10px 0 0;
  padding-left: 18px;
}

.report-section li {
  color: #475467;
  font-size: 13px;
  line-height: 1.7;
  margin: 4px 0;
}

.report-section pre {
  margin: 10px 0 0;
  max-height: 260px;
  overflow: auto;
  padding: 12px;
  border-radius: 8px;
  background: #101828;
  color: #e6edf7;
  font-size: 12px;
  line-height: 1.65;
}

.report-document {
  max-height: min(78vh, 860px);
  overflow-y: auto;
  padding: 4px 2px 0;
  display: grid;
  gap: 18px;
}

.report-paper-head,
.report-doc-section {
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fff;
}

.report-paper-head {
  padding: 20px 22px;
}

.report-paper-head > span {
  color: var(--wq-primary);
  font-size: 12px;
  font-weight: 760;
}

.report-paper-head h1 {
  margin-top: 8px;
  color: var(--wq-text);
  font-size: 24px;
  line-height: 1.35;
  font-weight: 800;
}

.report-paper-head p {
  margin-top: 10px;
  color: var(--wq-muted);
  font-size: 14px;
  line-height: 1.75;
}

.report-meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 14px;
}

.report-meta-line span {
  color: var(--wq-subtle);
  font-size: 12px;
}

.report-doc-section {
  padding: 18px 20px;
}

.report-doc-section h2 {
  color: var(--wq-primary);
  font-size: 18px;
  line-height: 1.4;
  font-weight: 780;
}

.report-doc-section h3 {
  color: var(--wq-text);
  font-size: 15px;
  line-height: 1.4;
  font-weight: 720;
}

.report-doc-section p,
.report-doc-section li {
  color: #475467;
  font-size: 13px;
  line-height: 1.75;
}

.report-doc-section ul {
  margin: 10px 0 0;
  padding-left: 18px;
}

.report-kpi-table {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 14px 0;
}

.report-kpi-cell {
  padding: 12px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #f9fbff;
}

.report-kpi-cell span {
  display: block;
  color: var(--wq-subtle);
  font-size: 12px;
}

.report-kpi-cell strong {
  display: block;
  margin-top: 8px;
  color: var(--wq-text);
  font-size: 20px;
  line-height: 1.2;
}

.report-step-block,
.report-chart-card {
  margin-top: 12px;
  padding: 14px;
  border: 1px solid #e4eaf5;
  border-radius: 8px;
  background: #fbfdff;
}

.report-step-block p,
.report-step-result {
  margin-top: 8px;
}

.report-step-block pre,
.report-appendix pre {
  margin-top: 10px;
  max-height: 280px;
  overflow: auto;
  padding: 12px 14px;
  border-radius: 8px;
  background: #101828;
  color: #e6edf7;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.65;
}

.report-chart-head p {
  margin-top: 4px;
  color: var(--wq-subtle);
}

.report-bar-chart {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.report-bar-row {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.report-bar-row span,
.report-bar-row strong {
  font-size: 13px;
}

.report-bar-track {
  height: 10px;
  border-radius: 999px;
  background: #edf2fd;
  overflow: hidden;
}

.report-bar-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #4f8cff, #7bb5ff);
}

.report-data-table-wrap {
  margin-top: 12px;
  overflow-x: auto;
}

.report-data-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 10px;
  background: #fff;
}

.report-data-table th,
.report-data-table td {
  border: 1px solid #e4eaf5;
  padding: 8px 10px;
  font-size: 12px;
  text-align: left;
  white-space: nowrap;
}

.report-data-table th {
  background: #f8fbff;
  color: #344054;
  font-weight: 700;
}

.report-appendix {
  background: #fbfcff;
}

@media (max-width: 1260px) {
  .chat-layout {
    grid-template-columns: 260px minmax(440px, 1fr);
  }

  .insight-panel {
    display: none;
  }
}

@media (max-width: 860px) {
  .chat-layout {
    grid-template-columns: 1fr;
    height: calc(100vh - 114px);
  }

  .session-sidebar {
    display: none;
  }

  .workspace-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .chat-controls {
    width: 100%;
    justify-content: flex-start;
  }

  .chat-controls .el-select {
    width: 100% !important;
  }

  .composer-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .composer-footer > .el-button {
    width: 100%;
  }

  .result-pagination {
    align-items: flex-start;
    flex-direction: column;
  }

  .report-hero,
  .report-detail-grid {
    grid-template-columns: 1fr;
  }

  .report-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
