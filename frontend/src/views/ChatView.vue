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
          <p>{{ semanticHintText }}</p>
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

              <div v-if="msg.role === 'assistant' && msg.steps.length > 0" class="analysis-process">
                <button
                  v-if="!isAssistantStreaming(msg)"
                  class="analysis-process-toggle"
                  type="button"
                  @click="toggleChain(msg.id)"
                >
                  <el-icon><ArrowRight v-if="msg.chainCollapsed" /><ArrowDown v-else /></el-icon>
                  <span>{{ msg.chainCollapsed ? '展开分析过程' : '收起分析过程' }}</span>
                  <small>{{ processBrief(msg) }}</small>
                </button>

                <div v-if="isAssistantStreaming(msg) || !msg.chainCollapsed" class="analysis-flow">
                  <section
                    v-for="(step, stepIndex) in narrativeSteps(msg)"
                    :key="`${msg.id}-${step.node}`"
                    :class="['analysis-step', step.status, `node-${step.node}`]"
                  >
                    <div class="analysis-step-heading">
                      <span v-if="analysisStepIndex(step, stepIndex)" class="analysis-step-number">{{ analysisStepIndex(step, stepIndex) }}</span>
                      <span v-else class="analysis-step-icon">
                        <el-icon v-if="step.status === 'running'" class="is-loading"><Loading /></el-icon>
                        <el-icon v-else-if="step.node === 'sql_execute'"><DocumentCopy /></el-icon>
                        <el-icon v-else-if="step.status === 'done'"><CircleCheck /></el-icon>
                        <el-icon v-else><Clock /></el-icon>
                      </span>
                      <h3>{{ displayStepLabel(step) }}</h3>
                      <span class="analysis-step-state">{{ narrativeStatusText(step) }}</span>
                    </div>

                    <p v-if="stepLeadLine(step)" class="analysis-lead">{{ stepLeadLine(step) }}</p>
                    <div v-if="visibleStepEvents(step).length" class="analysis-live-lines">
                      <p v-for="event in visibleStepEvents(step)" :key="event">{{ event }}</p>
                    </div>

                    <template v-if="step.node === 'semantic_enhance'">
                      <div v-if="semanticEnhanceLines(step).length" class="analysis-block">
                        <h4>问题改写</h4>
                        <ul class="compact-list">
                          <li v-for="item in semanticEnhanceLines(step)" :key="item">{{ item }}</li>
                        </ul>
                      </div>
                    </template>

                    <div v-if="step.node === 'semantic_runtime_recall' && semanticAssetLines(step).length" class="analysis-block">
                      <h4>命中的语义资产</h4>
                      <ul>
                        <li v-for="item in semanticAssetLines(step)" :key="item">{{ item }}</li>
                      </ul>
                    </div>

                    <template v-if="step.node === 'schema_recall'">
                      <div v-if="schemaTableLines(step).length" class="analysis-block">
                        <h4>候选表</h4>
                        <ul>
                          <li v-for="item in schemaTableLines(step)" :key="item">{{ item }}</li>
                        </ul>
                      </div>
                      <div v-if="schemaColumnLines(step).length" class="analysis-block">
                        <h4>候选字段</h4>
                        <ul class="compact-list">
                          <li v-for="item in schemaColumnLines(step)" :key="item">{{ item }}</li>
                        </ul>
                      </div>
                      <div v-if="schemaJoinLines(step).length" class="analysis-block">
                        <h4>关联提示</h4>
                        <ul class="compact-list">
                          <li v-for="item in schemaJoinLines(step)" :key="item">{{ item }}</li>
                        </ul>
                      </div>
                    </template>

                    <div v-if="step.node === 'nl2lf_generate'" class="analysis-code-block">
                      <pre><code>{{ logicFormText(step) }}</code></pre>
                    </div>

                    <template v-if="step.node === 'lf_validate' || step.node === 'semantic_check'">
                      <div v-if="validationDetailLines(step).length" class="analysis-block">
                        <h4>{{ step.node === 'semantic_check' ? '检查范围' : '校验信息' }}</h4>
                        <ul class="compact-list">
                          <li v-for="item in validationDetailLines(step)" :key="item">{{ item }}</li>
                        </ul>
                      </div>
                    </template>

                    <template v-if="step.node === 'sql_execute'">
                      <div v-if="sqlSampleRows(step).length" class="analysis-table">
                        <table>
                          <thead>
                            <tr>
                              <th v-for="col in sqlSampleColumns(step)" :key="col">
                                <span>{{ columnTitle(col) }}</span>
                                <small>{{ col }}</small>
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr v-for="(row, rowIndex) in sqlSampleRows(step)" :key="rowIndex">
                              <td v-for="col in sqlSampleColumns(step)" :key="col">{{ formatDisplayValue(col, row[col]) }}</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </template>

                    <div v-if="step.node === 'planner' && plannerStepLines(step).length" class="analysis-block">
                      <h4>{{ plannerStepLines(step).length }} 个步骤</h4>
                      <ul>
                        <li v-for="(item, itemIndex) in plannerStepLines(step)" :key="item">步骤{{ itemIndex + 1 }}：{{ item }}</li>
                      </ul>
                    </div>

                    <template v-if="step.node === 'python_generate'">
                      <div v-if="pythonTaskLines(step).length" class="analysis-block">
                        <h4>脚本会执行</h4>
                        <ul class="compact-list">
                          <li v-for="item in pythonTaskLines(step)" :key="item">{{ item }}</li>
                        </ul>
                      </div>
                      <h4 class="analysis-subtitle">脚本编写</h4>
                      <div class="analysis-code-block python">
                        <pre><code>{{ pythonCodeText(step) }}</code></pre>
                      </div>
                    </template>

                    <template v-if="step.node === 'python_analyze'">
                      <div v-if="pythonComputedLines(step).length" class="analysis-block">
                        <h4>已计算内容</h4>
                        <ul class="compact-list">
                          <li v-for="item in pythonComputedLines(step)" :key="item">{{ item }}</li>
                        </ul>
                      </div>
                      <h4 class="analysis-subtitle">输出内容</h4>
                      <div class="analysis-code-block json">
                        <pre><code>{{ pythonResultText(step) }}</code></pre>
                      </div>
                    </template>

                    <template v-if="step.node === 'report_generator'">
                      <div v-if="reportStreamText(step)" class="analysis-report-text">
                        <pre>{{ reportStreamText(step) }}</pre>
                      </div>
                      <div v-if="reportChartLines(step).length" class="analysis-chart-list">
                        <div v-for="chart in reportChartLines(step)" :key="chart.title" class="analysis-mini-chart">
                          <strong>{{ chart.title }}</strong>
                          <span>{{ chart.subtitle }}</span>
                          <div
                            v-for="row in chart.data"
                            :key="row.label"
                            class="analysis-mini-bar"
                          >
                            <em>{{ row.label }}</em>
                            <i :style="{ width: `${barPercent(row.value, chart.data)}%` }"></i>
                            <b>{{ formatReportValue(row.value) }}</b>
                          </div>
                        </div>
                      </div>
                    </template>

                    <div v-if="genericStreamText(step)" class="analysis-code-block">
                      <pre><code>{{ genericStreamText(step) }}</code></pre>
                    </div>
                  </section>

                  <div v-if="isAssistantStreaming(msg)" class="analysis-stream-cursor">
                    <span></span>
                    <p>正在持续生成...</p>
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
                    <h3>{{ msg.report_payload ? '深度分析报告' : '分析结论' }}</h3>
                    <p class="answer-subtitle">{{ msg.report_payload ? reportDisplayTitle(msg.report_payload) : panelResultTitle(msg) }}</p>
                  </div>
                  <div class="answer-badges">
                    <el-tag v-if="msg.intent" size="small" type="info">{{ msg.intent }}</el-tag>
                    <el-tag v-if="msg.sql" size="small" type="success">SQL 已生成</el-tag>
                    <el-tag v-if="msg.sql_result?.length" size="small" effect="plain">{{ msg.sql_result.length }} 行</el-tag>
                  </div>
                </div>
                <div v-if="msg.report_payload" class="answer-body answer-report-body">
                  <header class="inline-report-head">
                    <span>{{ reportStatusText(msg.report_payload) }} · {{ reportGenerationText(msg.report_payload) }}</span>
                    <h4>{{ reportDisplayTitle(msg.report_payload) }}</h4>
                    <p><InlineMarkdown :text="reportSummary(msg.report_payload)" /></p>
                    <div class="report-meta-line">
                      <span>生成时间：{{ reportGeneratedAt(msg.report_payload) }}</span>
                      <span>结果行数：{{ reportRowCount(msg.report_payload) }}</span>
                    </div>
                  </header>
                  <section class="inline-report-section report-body-section">
                    <div class="report-markdown-body inline-report-markdown">
                      <div
                        v-for="(block, index) in reportBodyBlocks(msg.report_payload)"
                        :key="`${msg.id}-inline-report-${index}`"
                        :class="['report-md-block', `report-md-${block.type}`]"
                      >
                        <h2 v-if="block.type === 'heading'">{{ stripInlineMarkdown(block.text) }}</h2>
                        <h3 v-else-if="block.type === 'subheading'">{{ stripInlineMarkdown(block.text) }}</h3>
                        <p v-else-if="block.type === 'paragraph'">
                          <template
                            v-for="(part, partIndex) in inlineMarkdownParts(block.text)"
                            :key="`${msg.id}-paragraph-${index}-${partIndex}`"
                          >
                            <strong v-if="part.type === 'bold'">{{ part.text }}</strong>
                            <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                            <span v-else>{{ part.text }}</span>
                          </template>
                        </p>
                        <ul v-else-if="block.type === 'list'">
                          <li v-for="item in block.items" :key="item">
                            <template
                              v-for="(part, partIndex) in inlineMarkdownParts(item)"
                              :key="`${msg.id}-list-${index}-${partIndex}`"
                            >
                              <strong v-if="part.type === 'bold'">{{ part.text }}</strong>
                              <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                              <span v-else>{{ part.text }}</span>
                            </template>
                          </li>
                        </ul>
                        <pre v-else-if="block.type === 'code'"><code>{{ block.text }}</code></pre>
                        <div v-else-if="block.type === 'chart'" class="report-chart-card report-md-chart-card">
                          <div class="report-chart-head">
                            <h3>{{ block.title }}</h3>
                            <p v-if="block.subtitle">{{ block.subtitle }}</p>
                          </div>
                          <ReportEChart :chart="block" />
                        </div>
                        <div v-else-if="block.type === 'table'" class="report-data-table-wrap">
                          <table class="report-data-table">
                            <thead>
                              <tr>
                                <th v-for="column in block.columns" :key="column">{{ stripInlineMarkdown(String(column)) }}</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
                                <td v-for="(cell, cellIndex) in row" :key="cellIndex">
                                  <InlineMarkdown :text="String(cell ?? '')" />
                                </td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  </section>
                </div>
                <div v-else class="answer-body">
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
                <div v-if="msg.sql || msg.report_payload" class="answer-assets">
                  <button v-if="msg.sql" class="asset-chip" type="button" @click="activeResultTab = 'sql'">
                    <span>SQL 详情</span>
                    <strong>{{ compactSql(msg.sql) }}</strong>
                  </button>
                  <button v-if="msg.report_payload" class="asset-chip" type="button" @click="openReport(msg)">
                    <span>展开查看</span>
                    <strong>在大视图中查看完整深度分析报告</strong>
                  </button>
                </div>
              </div>
              <div v-else class="text">{{ msg.content }}</div>
              <div v-if="msg.role === 'assistant' && msg.sql_result && msg.sql_result.length > 0 && !msg.report_payload" class="result-table compact-result">
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
                <p>{{ panelStepSummary(step) }}</p>
              </div>
            </div>
          </div>
          <div v-else class="panel-empty">发起查询后，这里会展示理解问题、语义增强、知识召回、生成 LogicForm、编译 SQL 和执行查询的过程。</div>
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
                <p>当前显示 {{ latestRowRangeText }}，表格只渲染当前页；导出会保留完整结果和全部字段。</p>
              </div>
              <div class="result-meta-tags">
                <el-tag effect="plain">{{ latestColumns.length }} 列</el-tag>
                <el-tag v-if="latestRows.length > resultPageSize" type="success" effect="plain">分页懒渲染</el-tag>
                <el-tag v-if="displayedLatestColumns.length < latestColumns.length" type="warning" effect="plain">已隐藏 {{ latestColumns.length - displayedLatestColumns.length }} 列</el-tag>
              </div>
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
              <span>{{ reportGenerationText(latestReport) }}</span>
              <h3>{{ reportDisplayTitle(latestReport) }}</h3>
              <p>{{ reportSummary(latestReport) }}</p>
            </div>
            <div class="report-markdown-preview">
              <div
                v-for="(block, index) in reportMarkdownBlocks(latestReport).slice(0, 5)"
                :key="`preview-${index}`"
                :class="['report-md-block', `report-md-${block.type}`]"
              >
                <strong v-if="block.type === 'heading'">{{ stripInlineMarkdown(block.text) }}</strong>
                <p v-else-if="block.type === 'paragraph'">
                  <InlineMarkdown :text="block.text" />
                </p>
                <ul v-else-if="block.type === 'list'">
                  <li v-for="item in block.items" :key="item">
                    <InlineMarkdown :text="item" />
                  </li>
                </ul>
                <div v-else-if="block.type === 'chart'" class="report-mini-chart">
                  <strong>{{ block.title }}</strong>
                  <span>{{ block.data.length }} 个数据点</span>
                </div>
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
      modal-class="report-dialog-overlay"
      width="min(1120px, 92vw)"
      align-center
      append-to-body
      destroy-on-close
    >
      <template #header>
        <div class="report-dialog-title">
          <span>深度分析报告</span>
        </div>
      </template>
      <div v-if="expandedReport" class="report-document">
        <header class="report-paper-head">
          <span>{{ reportStatusText(expandedReport) }} · {{ reportGenerationText(expandedReport) }}</span>
          <h1>{{ reportDisplayTitle(expandedReport) }}</h1>
          <p><InlineMarkdown :text="reportSummary(expandedReport)" /></p>
          <div class="report-meta-line">
            <span>生成时间：{{ reportGeneratedAt(expandedReport) }}</span>
            <span>结果行数：{{ reportRowCount(expandedReport) }}</span>
          </div>
        </header>

        <section class="report-doc-section report-body-section">
          <div class="report-markdown-body">
            <div
              v-for="(block, index) in reportBodyBlocks(expandedReport)"
              :key="`report-md-${index}`"
              :class="['report-md-block', `report-md-${block.type}`]"
            >
              <h2 v-if="block.type === 'heading'">{{ stripInlineMarkdown(block.text) }}</h2>
              <h3 v-else-if="block.type === 'subheading'">{{ stripInlineMarkdown(block.text) }}</h3>
              <p v-else-if="block.type === 'paragraph'">
                <template
                  v-for="(part, partIndex) in inlineMarkdownParts(block.text)"
                  :key="`paragraph-${index}-${partIndex}`"
                >
                  <strong v-if="part.type === 'bold'">{{ part.text }}</strong>
                  <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                  <span v-else>{{ part.text }}</span>
                </template>
              </p>
              <ul v-else-if="block.type === 'list'">
                <li v-for="item in block.items" :key="item">
                  <template
                    v-for="(part, partIndex) in inlineMarkdownParts(item)"
                    :key="`list-${index}-${partIndex}`"
                  >
                    <strong v-if="part.type === 'bold'">{{ part.text }}</strong>
                    <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                    <span v-else>{{ part.text }}</span>
                  </template>
                </li>
              </ul>
              <pre v-else-if="block.type === 'code'"><code>{{ block.text }}</code></pre>
              <div v-else-if="block.type === 'chart'" class="report-chart-card report-md-chart-card">
                <div class="report-chart-head">
                  <h3>{{ block.title }}</h3>
                  <p v-if="block.subtitle">{{ block.subtitle }}</p>
                </div>
                <ReportEChart :chart="block" />
              </div>
              <div v-else-if="block.type === 'table'" class="report-data-table-wrap">
                <table class="report-data-table">
                  <thead>
                    <tr>
                      <th v-for="column in block.columns" :key="column">{{ stripInlineMarkdown(String(column)) }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
                      <td v-for="(cell, cellIndex) in row" :key="cellIndex">
                        <InlineMarkdown :text="String(cell ?? '')" />
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>

        <section v-if="reportCharts(expandedReport).length" class="report-doc-section">
          <h2>图表与数据附件</h2>
          <div
            v-for="chart in reportCharts(expandedReport)"
            :key="chart.title"
            class="report-chart-card"
          >
            <div class="report-chart-head">
              <h3>{{ chart.title }}</h3>
              <p v-if="chart.subtitle">{{ chart.subtitle }}</p>
            </div>
            <ReportEChart :chart="chart" />
          </div>
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
                  <td v-for="column in table.columns" :key="column">
                    <InlineMarkdown :text="formatReportValue(row[column])" />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-if="reportAnalysisSummary(expandedReport).length" class="report-doc-section report-appendix">
          <h2>分析过程摘要</h2>
          <p>这里展示统计脚本产出的业务摘要，原始技术 JSON 不在报告正文中直接暴露。</p>
          <ul>
            <li v-for="item in reportAnalysisSummary(expandedReport)" :key="item">
              <InlineMarkdown :text="item" />
            </li>
          </ul>
        </section>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, nextTick, onUnmounted, watch, defineComponent, h, type PropType } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { Promotion, Loading, ChatDotRound, Plus, Delete, CircleCheck, Clock, Search, Refresh, Download, DocumentCopy, WarningFilled, ArrowDown, ArrowRight, InfoFilled, FullScreen } from '@element-plus/icons-vue'
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
  type ChatMessage,
  type ChatReasoningStep,
  type ChatStreamState,
} from '../stores/chatStream'

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

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
const semanticExampleQueries = ref<string[]>([])
const semanticHint = ref('')
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

const ReportEChart = defineComponent({
  name: 'ReportEChart',
  props: {
    chart: {
      type: Object as PropType<ReportChartBlock>,
      required: true,
    },
  },
  setup(props) {
    const chartRef = ref<HTMLElement | null>(null)
    let chartInstance: echarts.ECharts | null = null
    let resizeObserver: ResizeObserver | null = null
    const resize = () => chartInstance?.resize()
    const renderChart = () => {
      if (!chartRef.value) return
      if (!chartInstance) {
        chartInstance = echarts.init(chartRef.value, undefined, { renderer: 'canvas' })
      }
      chartInstance.setOption(buildReportEchartsOption(props.chart), true)
      resize()
    }
    onMounted(() => {
      nextTick(() => {
        renderChart()
        if (chartRef.value && typeof ResizeObserver !== 'undefined') {
          resizeObserver = new ResizeObserver(resize)
          resizeObserver.observe(chartRef.value)
        }
        window.addEventListener('resize', resize)
      })
    })
    watch(() => props.chart, () => nextTick(renderChart), { deep: true })
    onUnmounted(() => {
      window.removeEventListener('resize', resize)
      resizeObserver?.disconnect()
      chartInstance?.dispose()
      chartInstance = null
    })
    return () => h('div', { ref: chartRef, class: 'report-echart' })
  },
})

const defaultQuickQueries = [
  '按月份统计核心指标趋势',
  '排名前三的分类分别是多少',
  '不同类别的指标分布情况',
  '最近三个月的异常变化有哪些',
]
const quickQueries = computed(() => {
  const configured = semanticExampleQueries.value.filter(Boolean)
  return configured.length ? configured.slice(0, 4) : defaultQuickQueries
})
const semanticHintText = computed(() => semanticHint.value || '选择智能体和数据源后，可以用自然语言查询已授权的数据。')

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
      semanticLabels.value = {}
      semanticExampleQueries.value = []
      semanticHint.value = ''
      return
    }
    const assets = await fetchSemanticAssets(domain.id)
    semanticLabels.value = buildSemanticLabels(assets)
    semanticExampleQueries.value = buildSemanticExamples(assets)
    semanticHint.value = domain.description || `${domain.name} 语义层已启用。`
  } catch {
    semanticLabels.value = {}
    semanticExampleQueries.value = []
    semanticHint.value = ''
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

async function downloadResults() {
  if (latestRows.value.length === 0) return
  if (latestRows.value.length > 1000 || displayedLatestColumns.value.length < latestColumns.value.length) {
    try {
      await ElMessageBox.confirm(
        `将导出完整结果：${latestRows.value.length} 行、${latestColumns.value.length} 列。当前页面隐藏列和分页设置不会影响导出内容。`,
        '导出完整结果',
        { type: 'info' },
      )
    } catch {
      return
    }
  }
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

function displayStepLabel(step: ChatReasoningStep) {
  if (step.node === 'semantic_enhance') return '语义增强'
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
        streamText: step.streamText || '',
        events: step.events || [],
        progress: '',
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

function getOutputArray(output: Record<string, unknown> | null, key: string) {
  if (!output) return []
  const value = output[key]
  return Array.isArray(value) ? value : []
}

function processBrief(message: ChatMessage) {
  const done = message.steps.filter(step => step.status === 'done').length
  return `${done}/${message.steps.length} 个环节已完成`
}

function narrativeSteps(message: ChatMessage) {
  const order = [
    'intent_recognition',
    'semantic_enhance',
    'semantic_runtime_recall',
    'schema_recall',
    'nl2lf_generate',
    'lf_validate',
    'lf_to_sql_compile',
    'nl2sql_fallback',
    'semantic_check',
    'sql_execute',
    'planner',
    'python_generate',
    'python_analyze',
    'report_generator',
  ]
  return [...message.steps].sort((left, right) => {
    const leftIndex = order.indexOf(left.node)
    const rightIndex = order.indexOf(right.node)
    return (leftIndex === -1 ? 999 : leftIndex) - (rightIndex === -1 ? 999 : rightIndex)
  })
}

function analysisStepIndex(step: ChatReasoningStep, stepIndex: number) {
  if (['intent_recognition', 'semantic_enhance', 'semantic_runtime_recall', 'schema_recall'].includes(step.node)) {
    return String(stepIndex + 1)
  }
  return ''
}

function narrativeStatusText(step: ChatReasoningStep) {
  if (step.status === 'running') return '正在处理'
  if (step.status === 'done') return '完成'
  return '等待'
}

function stepLeadLine(step: ChatReasoningStep) {
  const output = step.output || {}
  if (step.node === 'intent_recognition') {
    const intent = String(output.intent || '').trim()
    return intent ? `→ ${intent}${intent === 'data_query' ? '智能问数' : ''}` : step.summary
  }
  if (step.node === 'semantic_enhance') {
    const enhanced = String(output.enhanced_question || '').trim()
    if (!enhanced && step.status === 'running') return '正在理解问题并补全业务口径'
    return enhanced || step.summary
  }
  if (step.node === 'semantic_runtime_recall') return step.summary
  if (step.node === 'lf_validate') {
    if (output.valid === true) return '校验通过'
    const errors = getStringArray(output, 'errors')
    return errors.length ? `校验未通过：${errors.join('；')}` : step.summary
  }
  if (step.node === 'lf_to_sql_compile') {
    if (getOutputString(output, 'compiled_sql')) return '已根据 LogicForm 编译受控 SQL'
    if (getOutputString(output, 'error')) return `SQL 编译失败：${getOutputString(output, 'error')}`
    return step.summary
  }
  if (step.node === 'nl2sql_fallback') {
    if (getOutputString(output, 'compiled_sql')) return '语义层未命中，已使用数据定位上下文生成兜底 SQL'
    if (getOutputString(output, 'error')) return `兜底生成失败：${getOutputString(output, 'error')}`
    return step.summary
  }
  if (step.node === 'semantic_check') {
    if (output.valid === true) return '一致性通过'
    const errors = getStringArray(output, 'errors')
    return errors.length ? `一致性未通过：${errors.join('；')}` : step.summary
  }
  if (step.node === 'sql_execute') {
    const error = getOutputString(output, 'error')
    if (error) return `SQL 执行失败：${error}`
    if (Object.prototype.hasOwnProperty.call(output, 'row_count')) return `${String(output.row_count ?? 0)} 条结果`
    return step.summary
  }
  if (step.node === 'planner') {
    const count = plannerStepLines(step).length
    return count ? `${count} 个步骤` : step.summary
  }
  if (step.node === 'python_generate') return step.summary || '正在编写统计脚本'
  if (step.node === 'python_analyze') return step.summary || '正在执行统计分析'
  if (step.node === 'report_generator') return step.summary || '正在输出业务报告'
  return step.summary
}

function visibleStepEvents(step: ChatReasoningStep) {
  if (step.status !== 'running') return []
  const lead = stepLeadLine(step).trim()
  const events = (step.events || [])
    .map(event => event.replace(/^完成：/, '').trim())
    .filter(event => event && !event.startsWith('开始') && event !== lead)
  const volatileEvents = events.filter(isVolatileProgressLine)
  if (volatileEvents.length) return [volatileEvents[volatileEvents.length - 1]]
  if (step.progress && step.progress !== lead) return [step.progress]
  return events.slice(-2)
}

function isVolatileProgressLine(text: string) {
  return text.startsWith('正在') && (text.endsWith('...') || text.endsWith('…'))
}

function panelStepSummary(step: ChatReasoningStep) {
  return step.summary || step.progress || statusText(step.status)
}

function semanticAssetLines(step: ChatReasoningStep) {
  return getOutputArray(step.output || {}, 'matched_assets')
    .map(item => formatSemanticAsset(item))
    .filter(Boolean)
    .slice(0, 8)
}

function semanticEnhanceLines(step: ChatReasoningStep) {
  const output = step.output || {}
  const lines: string[] = []
  const original = String(output.original_question || '').trim()
  const enhanced = String(output.enhanced_question || '').trim()
  const reason = String(output.reason || '').trim()
  const preserved = getStringArray(output, 'preserved_constraints')
  if (original) lines.push(`原始问题：${original}`)
  if (enhanced && enhanced !== original) lines.push(`增强问题：${enhanced}`)
  if (reason) lines.push(`改写说明：${reason}`)
  if (preserved.length) lines.push(`保留约束：${preserved.join('、')}`)
  return lines
}

function schemaTableLines(step: ChatReasoningStep) {
  return getOutputArray(step.output || {}, 'matched_tables')
    .map(item => formatSchemaTable(item))
    .filter(Boolean)
    .slice(0, 8)
}

function schemaColumnLines(step: ChatReasoningStep) {
  return getOutputArray(step.output || {}, 'matched_columns')
    .map(item => formatSchemaColumn(item))
    .filter(Boolean)
    .slice(0, 12)
}

function schemaJoinLines(step: ChatReasoningStep) {
  return getOutputArray(step.output || {}, 'likely_joins')
    .map(item => formatJoinHint(item))
    .filter(Boolean)
    .slice(0, 8)
}

function logicFormText(step: ChatReasoningStep) {
  const logicForm = getOutputObject(step.output || {}, 'logic_form')
  if (logicForm) return formatJson(logicForm)
  return step.streamText || '{\n  "status": "正在生成 LogicForm..."\n}'
}

function validationDetailLines(step: ChatReasoningStep) {
  const output = step.output || {}
  const lines: string[] = []
  const errors = getStringArray(output, 'errors')
  const warnings = getStringArray(output, 'warnings')
  if (errors.length) lines.push(...errors.map(item => `错误：${item}`))
  if (warnings.length) lines.push(...warnings.map(item => `提醒：${item}`))
  const checked = getOutputObject(output, 'checked_items')
  if (checked) {
    const metrics = getOutputArray(checked, 'metrics').map(String).filter(Boolean)
    const dimensions = getOutputArray(checked, 'dimensions').map(String).filter(Boolean)
    if (metrics.length) lines.push(`检查指标：${metrics.join('、')}`)
    if (dimensions.length) lines.push(`检查维度：${dimensions.join('、')}`)
  }
  const usedAssets = getOutputArray(output, 'used_assets').map(String).filter(Boolean)
  if (usedAssets.length) lines.push(`使用资产：${usedAssets.slice(0, 6).join('、')}`)
  return lines
}

function sqlSampleRows(step: ChatReasoningStep) {
  return getRecordArray(step.output || {}, 'sample_rows')
}

function sqlSampleColumns(step: ChatReasoningStep) {
  const output = step.output || {}
  const columns = getOutputArray(output, 'columns').map(String).filter(Boolean)
  if (columns.length) return columns
  const first = sqlSampleRows(step)[0]
  return first ? Object.keys(first) : []
}

function plannerStepLines(step: ChatReasoningStep) {
  const plan = getOutputObject(step.output || {}, 'plan')
  const steps = getOutputArray(plan || {}, 'analysis_steps')
  return steps
    .map((item) => {
      if (!item || typeof item !== 'object') return String(item || '')
      const record = item as Record<string, unknown>
      return String(record.description || record.name || '').trim()
    })
    .filter(Boolean)
}

function pythonTaskLines(step: ChatReasoningStep) {
  return getOutputArray(step.output || {}, 'generated_tasks').map(String).filter(Boolean)
}

function pythonCodeText(step: ChatReasoningStep) {
  return step.streamText || getOutputString(step.output || {}, 'python_code') || '# 正在生成统计脚本...'
}

function pythonComputedLines(step: ChatReasoningStep) {
  return getOutputArray(step.output || {}, 'computed_items').map(String).filter(Boolean)
}

function pythonResultText(step: ChatReasoningStep) {
  if (step.streamText) return step.streamText
  const result = getOutputObject(step.output || {}, 'python_result')
  return result ? formatJson(result) : '{\n  "status": "正在执行统计分析..."\n}'
}

function reportStreamText(step: ChatReasoningStep) {
  if (step.streamText) return step.streamText
  const output = step.output || {}
  const title = getOutputString(output, 'title')
  const summary = getOutputString(output, 'summary')
  if (!title && !summary) return ''
  return [title ? `# ${title}` : '', summary].filter(Boolean).join('\n\n')
}

function reportChartLines(step: ChatReasoningStep) {
  return getOutputArray(step.output || {}, 'charts')
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map(item => ({
      title: String(item.title || '图表'),
      subtitle: String(item.subtitle || ''),
      data: getRecordArray(item, 'data')
        .map(row => ({ label: String(row.label ?? '-'), value: row.value }))
        .slice(0, 8),
    }))
    .filter(chart => chart.data.length > 0)
}

function genericStreamText(step: ChatReasoningStep) {
  if (!step.streamText) return ''
  if (['semantic_enhance', 'nl2lf_generate', 'python_generate', 'python_analyze', 'report_generator'].includes(step.node)) return ''
  if (step.node === 'lf_to_sql_compile' || step.node === 'nl2sql_fallback') return step.streamText
  return ''
}

function getStringArray(output: Record<string, unknown>, key: string) {
  return getOutputArray(output, key).map(String).filter(Boolean)
}

function getRecordArray(output: Record<string, unknown> | null, key: string) {
  return getOutputArray(output, key).filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
}

function formatSemanticAsset(item: unknown) {
  if (!item || typeof item !== 'object') return ''
  const record = item as Record<string, unknown>
  const key = String(record.key || record.type || '')
  const content = String(record.content || '').trim()
  const score = record.score === undefined ? '' : ` · score ${record.score}`
  return `${key}${content ? `：${content}` : ''}${score}`
}

function formatSchemaTable(item: unknown) {
  if (!item || typeof item !== 'object') return ''
  const record = item as Record<string, unknown>
  const table = String(record.table_name || record.table || '')
  const comment = String(record.table_comment || record.comment || '')
  const reason = String(record.reason || '')
  const score = record.score === undefined ? '' : ` · score ${record.score}`
  return `${comment || table}${table ? ` (${table})` : ''}${reason ? ` · ${reason}` : ''}${score}`
}

function formatSchemaColumn(item: unknown) {
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
  const left = String(record.left || '')
  const right = String(record.right || '')
  return left && right ? `${left} = ${right}` : String(record.hint || '')
}

function statusText(status: string) {
  if (status === 'done') return '已完成'
  if (status === 'running') return '处理中'
  return '等待执行'
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

function reportTitle(report: Record<string, unknown>): string {
  return String(report.title || '查询结果分析')
}

function reportDisplayTitle(report: Record<string, unknown>): string {
  const markdownTitle = reportMarkdownBlocks(report).find(block => block.type === 'title')
  if (markdownTitle?.type === 'title' && markdownTitle.text.trim()) {
    return stripInlineMarkdown(markdownTitle.text.trim())
  }
  return humanizeReportTitle(reportTitle(report), report)
}

function humanizeReportTitle(title: string, report: Record<string, unknown>): string {
  const cleanTitle = stripInlineMarkdown(title).trim()
  if (!cleanTitle || cleanTitle === '查询结果分析') return '查询结果分析'
  const replaced = cleanTitle
    .replace(/[A-Za-z][A-Za-z0-9_]*/g, token => reportFieldLabel(token, report))
    .replace(/\s+按\s+/g, '按')
    .replace(/\s+分析$/g, '分析')
    .trim()
  return replaced || '查询结果分析'
}

function reportFieldLabel(key: string, report?: Record<string, unknown>): string {
  const label = semanticLabels.value[key]
  if (label) return label
  const pythonResult = report ? reportPythonResult(report) : null
  const candidates: ReportFieldDescriptor[] = [
    ...fieldDescriptorItems(pythonResult?.metrics),
    ...fieldDescriptorItems(pythonResult?.dimensions),
  ]
  const matched = candidates.find((item: ReportFieldDescriptor) => item.field === key || item.key === key || item.name === key)
  if (matched?.label) return matched.label
  return humanizeField(key)
}

type InlineMarkdownPart = { type: 'text' | 'bold' | 'code'; text: string }

function inlineMarkdownParts(text: string): InlineMarkdownPart[] {
  const parts: InlineMarkdownPart[] = []
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let cursor = 0
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > cursor) parts.push({ type: 'text', text: text.slice(cursor, index) })
    const raw = match[0]
    if (raw.startsWith('**')) {
      parts.push({ type: 'bold', text: raw.slice(2, -2) })
    } else {
      parts.push({ type: 'code', text: raw.slice(1, -1) })
    }
    cursor = index + raw.length
  }
  if (cursor < text.length) parts.push({ type: 'text', text: text.slice(cursor) })
  return parts.length ? parts : [{ type: 'text', text }]
}

function stripInlineMarkdown(text: string): string {
  return inlineMarkdownParts(text).map(part => part.text).join('')
}

const InlineMarkdown = defineComponent({
  name: 'InlineMarkdown',
  props: {
    text: {
      type: String,
      default: '',
    },
  },
  setup(props) {
    return () => inlineMarkdownParts(props.text).map((part, index) => {
      if (part.type === 'bold') return h('strong', { key: index }, part.text)
      if (part.type === 'code') return h('code', { key: index }, part.text)
      return h('span', { key: index }, part.text)
    })
  },
})

function reportSummary(report: Record<string, unknown>) {
  const text = String(report.summary || '')
  if (text) return stripInlineMarkdown(text)
  const markdownText = reportMarkdownText(report)
  if (markdownText) {
    const paragraph = reportMarkdownBlocks(report).find(block => block.type === 'paragraph')
    if (paragraph?.type === 'paragraph' && paragraph.text) return stripInlineMarkdown(paragraph.text)
  }
  const bullets = reportExecutiveBullets(report)
  if (bullets.length) return stripInlineMarkdown(bullets[0])
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

function reportGenerationText(report: Record<string, unknown>) {
  if (report.generation_source === 'llm_report_generator') return '后端流式报告'
  if (report.generation_source === 'fallback_template') return '安全模板报告'
  return '分析报告'
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

type ReportMarkdownBlock =
  | { type: 'title' | 'heading' | 'subheading' | 'paragraph' | 'code'; text: string }
  | { type: 'list'; items: string[] }
  | { type: 'chart'; title: string; subtitle: string; chartKind: 'bar' | 'pie' | 'line'; data: { label: string; value: unknown }[]; series?: ReportChartSeries[]; xAxis?: string[]; option?: Record<string, unknown> }
  | { type: 'table'; columns: string[]; rows: string[][] }

type ReportChartBlock = Extract<ReportMarkdownBlock, { type: 'chart' }>
type ReportChartSeries = { name: string; data: { label: string; value: unknown }[] }

type ReportFieldDescriptor = { field: string; key: string; name: string; label: string }

function reportMarkdownText(report: Record<string, unknown>) {
  return String(report.markdown || report.body || report.report || '').trim()
}

function reportMarkdownBlocks(report: Record<string, unknown>): ReportMarkdownBlock[] {
  const markdown = reportMarkdownText(report)
  if (!markdown) {
    return reportSections(report).map(section => ({
      type: 'paragraph',
      text: `${section.title}：${section.items.join('；')}`,
    }))
  }
  const blocks: ReportMarkdownBlock[] = []
  const lines = markdown.split(/\r?\n/)
  let paragraph: string[] = []
  let listItems: string[] = []
  let codeLines: string[] = []
  let inCode = false
  let codeLanguage = ''

  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push({ type: 'paragraph', text: paragraph.join(' ').trim() })
    paragraph = []
  }
  const flushList = () => {
    if (!listItems.length) return
    blocks.push({ type: 'list', items: [...listItems] })
    listItems = []
  }
  const flushCode = () => {
    if (!codeLines.length) return
    const code = codeLines.join('\n')
    const chart = chartFromCodeBlock(code, codeLanguage)
    if (chart) blocks.push(chart)
    else blocks.push({ type: 'code', text: code })
    codeLines = []
    codeLanguage = ''
  }

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const rawLine = lines[lineIndex]
    const line = rawLine.trimEnd()
    const trimmed = line.trim()
    if (trimmed.startsWith('```')) {
      if (inCode) {
        inCode = false
        flushCode()
      } else {
        flushParagraph()
        flushList()
        inCode = true
        codeLanguage = trimmed.replace(/^```/, '').trim().toLowerCase()
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
    if (looksLikeRawEchartsJson(trimmed)) {
      const rawChart = collectRawEchartsJson(lines, lineIndex)
      if (rawChart) {
        flushParagraph()
        flushList()
        if (!hasEquivalentChartBlock(blocks, rawChart.chart)) {
          blocks.push(rawChart.chart)
        }
        lineIndex += rawChart.consumed - 1
        continue
      }
    }
    if (isMarkdownTableLine(trimmed)) {
      flushParagraph()
      flushList()
      const tableLines = collectTableLines(lines, lineIndex)
      if (tableLines.length) {
        const table = parseMarkdownTable(tableLines)
        if (table) blocks.push(table)
        lineIndex += tableLines.length - 1
      }
      continue
    }
    if (trimmed.startsWith('### ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'subheading', text: trimmed.replace(/^###\s+/, '') })
    } else if (trimmed.startsWith('## ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'heading', text: trimmed.replace(/^##\s+/, '') })
    } else if (trimmed.startsWith('# ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'title', text: trimmed.replace(/^#\s+/, '') })
    } else if (/^[-*]\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed)) {
      flushParagraph()
      listItems.push(trimmed.replace(/^[-*]\s+/, '').replace(/^\d+\.\s+/, ''))
    } else {
      flushList()
      paragraph.push(trimmed)
    }
  }
  flushParagraph()
  flushList()
  flushCode()
  return blocks.length ? blocks : [{ type: 'paragraph', text: markdown }]
}

function reportBodyBlocks(report: Record<string, unknown>) {
  return reportMarkdownBlocks(report).filter(block => block.type !== 'title')
}

function looksLikeRawEchartsJson(text: string) {
  return text.startsWith('{') && text.includes('"series"') && (
    text.includes('"xAxis"') ||
    text.includes('"yAxis"') ||
    text.includes('"legend"') ||
    text.includes('"tooltip"')
  )
}

function collectRawEchartsJson(lines: string[], start: number) {
  const collected: string[] = []
  const maxLines = Math.min(lines.length, start + 120)
  for (let index = start; index < maxLines; index += 1) {
    collected.push(lines[index].trim())
    const text = collected.join('\n')
    const chart = chartFromCodeBlock(text, 'json')
    if (chart) return { chart, consumed: index - start + 1 }
  }
  return null
}

function hasEquivalentChartBlock(blocks: ReportMarkdownBlock[], chart: ReportChartBlock) {
  return blocks.some(block => block.type === 'chart' && block.title === chart.title)
}

function isMarkdownTableLine(line: string) {
  return line.startsWith('|') && line.endsWith('|')
}

function collectTableLines(lines: string[], start: number) {
  const tableLines: string[] = []
  for (let index = start; index < lines.length; index += 1) {
    const line = lines[index].trim()
    if (!isMarkdownTableLine(line)) break
    tableLines.push(line)
  }
  return tableLines
}

function parseMarkdownTable(lines: string[]): ReportMarkdownBlock | null {
  if (lines.length < 2) return null
  const columns = splitMarkdownTableRow(lines[0])
  const bodyLines = lines.slice(1).filter(line => !/^\|\s*[-:|\s]+\s*\|$/.test(line))
  const rows = bodyLines.map(splitMarkdownTableRow).filter(row => row.length)
  if (!columns.length || !rows.length) return null
  return { type: 'table', columns, rows }
}

function splitMarkdownTableRow(line: string) {
  return line
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map(cell => cell.trim())
}

function chartFromCodeBlock(code: string, language = ''): ReportChartBlock | null {
  const lowerLanguage = language.toLowerCase()
  if (lowerLanguage && !['json', 'echarts', 'chart'].includes(lowerLanguage)) return null
  try {
    const parsed = JSON.parse(code)
    return chartFromEchartsOption(parsed)
  } catch {
    return null
  }
}

function chartFromEchartsOption(option: unknown): ReportChartBlock | null {
  if (!option || typeof option !== 'object' || Array.isArray(option)) return null
  const record = option as Record<string, unknown>
  const seriesList = Array.isArray(record.series) ? record.series : []
  const firstSeries = seriesList.find((item): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item))
  if (!firstSeries || !Array.isArray(firstSeries.data)) return null
  const chartKind = echartsSeriesKind(firstSeries)
  const labels = echartsAxisLabels(record.xAxis)
  const series = normalizeEchartsSeries(seriesList, labels)
  const data = series.length ? series.flatMap(item => item.data) : firstSeries.data
    .map((item, index) => normalizeChartPoint(item, labels[index]))
    .filter((item): item is { label: string; value: unknown } => !!item)
  if (!data.length && !series.length) return null
  return {
    type: 'chart',
    title: echartsText(record.title) || String(firstSeries.name || '图表'),
    subtitle: echartsText(record.subtitle),
    chartKind,
    data,
    series: series.length ? series : undefined,
    xAxis: labels.length ? labels : undefined,
    option: record,
  }
}

function echartsSeriesKind(series: Record<string, unknown>): 'bar' | 'pie' | 'line' {
  const kind = normalizeChartKind(series.type)
  return kind === '' ? 'bar' : kind
}

function echartsAxisLabels(axis: unknown) {
  const axisRecord = Array.isArray(axis) ? axis[0] : axis
  if (!axisRecord || typeof axisRecord !== 'object' || Array.isArray(axisRecord)) return []
  const data = (axisRecord as Record<string, unknown>).data
  return Array.isArray(data) ? data.map(item => String(item)) : []
}

function echartsText(value: unknown) {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const text = (value as Record<string, unknown>).text
    if (typeof text === 'string') return text
  }
  return ''
}

function normalizeChartPoint(item: unknown, fallbackLabel?: string): { label: string; value: unknown } | null {
  if (Array.isArray(item)) {
    if (item.length < 2) return null
    return { label: String(item[0]), value: item[1] }
  }
  if (item && typeof item === 'object') {
    const record = item as Record<string, unknown>
    const label = record.name ?? record.label ?? fallbackLabel
    const value = record.value ?? record.y
    if (label === undefined && value === undefined) return null
    return { label: String(label ?? '-'), value }
  }
  return { label: String(fallbackLabel ?? '-'), value: item }
}

function normalizeEchartsSeries(seriesList: Record<string, unknown>[], labels: string[]): ReportChartSeries[] {
  return seriesList
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item))
    .map(series => {
      const rawData = Array.isArray(series.data) ? series.data : []
      const points = rawData
        .map((item, index) => normalizeChartPoint(item, labels[index]))
        .filter((item): item is { label: string; value: unknown } => !!item)
      return {
        name: String(series.name || '序列'),
        data: points,
      }
    })
    .filter(item => item.data.length > 0)
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
    .map(item => normalizeReportChart(item))
    .filter((item): item is ReportChartBlock => !!item)
    .filter(item => item.data.length > 0)
}

function normalizeReportChart(item: Record<string, unknown>): ReportChartBlock | null {
  const optionChart = chartFromEchartsOption(item.echarts_option || item.option)
  const explicitKind = normalizeChartKind(item.chart_kind || item.chartKind || item.type)
  if (optionChart) {
    return {
      type: 'chart',
      title: String(item.title || optionChart.title),
      subtitle: String(item.subtitle || optionChart.subtitle),
      chartKind: explicitKind === '' ? optionChart.chartKind : explicitKind,
      data: optionChart.data,
      series: optionChart.series,
      xAxis: optionChart.xAxis,
      option: optionChart.option,
    }
  }
  const rows = Array.isArray(item.data) ? item.data : []
  const data = rows
    .map(row => normalizeChartPoint(row))
    .filter((row): row is { label: string; value: unknown } => !!row)
  const title = String(item.title || '图表')
  const subtitle = String(item.subtitle || '')
  return {
    type: 'chart',
    title,
    subtitle,
    chartKind: explicitKind === '' ? inferChartKind(title, subtitle, data) : explicitKind,
    data,
  }
}

function buildReportEchartsOption(chart: ReportChartBlock): Record<string, unknown> {
  const base = normalizeEchartsOption(clonePlainObject(chart.option), chart)
  const kind = chart.chartKind
  const palette = chartPalette()
  const common = {
    color: palette,
    animationDuration: 650,
    animationEasing: 'cubicOut',
    backgroundColor: 'transparent',
    tooltip: {
      trigger: kind === 'pie' ? 'item' : 'axis',
      confine: true,
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderWidth: 0,
      borderRadius: 8,
      padding: [8, 10],
      textStyle: { color: '#fff', fontSize: 12 },
    },
    legend: {
      type: 'scroll',
      bottom: 0,
      icon: 'roundRect',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#475467', fontSize: 12 },
      pageIconColor: '#64748b',
      pageTextStyle: { color: '#64748b' },
    },
  }
  return {
    ...common,
    ...base,
    color: palette,
    title: undefined,
    series: prettifySeries(base.series, kind),
    grid: kind === 'pie' ? undefined : {
      ...(isPlainObject(base.grid) ? base.grid : {}),
      top: Math.max(toFiniteNumber(isPlainObject(base.grid) ? base.grid.top : undefined) || 0, 46),
      right: 18,
      bottom: 54,
      left: 46,
      containLabel: true,
    },
    xAxis: kind === 'pie' ? undefined : prettifyAxis(base.xAxis, 'x'),
    yAxis: kind === 'pie' ? undefined : prettifyAxis(base.yAxis, 'y'),
    tooltip: { ...common.tooltip, ...(isPlainObject(base.tooltip) ? base.tooltip : {}) },
    legend: { ...common.legend, ...(isPlainObject(base.legend) ? base.legend : {}) },
  }
}

function normalizeEchartsOption(option: Record<string, unknown> | null, chart: ReportChartBlock): Record<string, unknown> {
  if (option && Array.isArray(option.series) && option.series.length) return option
  if (chart.chartKind === 'pie') {
    return {
      series: [{
        type: 'pie',
        name: chart.title,
        data: chart.data.map(item => ({ name: item.label, value: toFiniteNumber(item.value) })),
      }],
    }
  }
  const series = chart.series?.length
    ? chart.series.map(item => ({ type: chart.chartKind, name: item.name, data: item.data.map(row => toFiniteNumber(row.value)) }))
    : [{ type: chart.chartKind, name: chart.title, data: chart.data.map(item => toFiniteNumber(item.value)) }]
  return {
    xAxis: { type: 'category', data: chart.xAxis?.length ? chart.xAxis : chart.data.map(item => item.label) },
    yAxis: { type: 'value' },
    series,
  }
}

function prettifySeries(series: unknown, kind: 'bar' | 'pie' | 'line') {
  const seriesList = Array.isArray(series) ? series : []
  if (kind === 'pie') {
    return seriesList.map((item) => {
      const record = isPlainObject(item) ? item : {}
      return {
        ...record,
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 3, ...(isPlainObject(record.itemStyle) ? record.itemStyle : {}) },
        label: {
          color: '#344054',
          fontSize: 12,
          formatter: '{b}\n{d}%',
          ...(isPlainObject(record.label) ? record.label : {}),
        },
        labelLine: { length: 14, length2: 8, smooth: true, ...(isPlainObject(record.labelLine) ? record.labelLine : {}) },
      }
    })
  }
  if (kind === 'line') {
    return seriesList.map((item) => {
      const record = isPlainObject(item) ? item : {}
      return {
        ...record,
        type: 'line',
        smooth: true,
        showSymbol: false,
        symbolSize: 7,
        lineStyle: { width: 3, ...(isPlainObject(record.lineStyle) ? record.lineStyle : {}) },
        areaStyle: {
          opacity: 0.08,
          ...(isPlainObject(record.areaStyle) ? record.areaStyle : {}),
        },
      }
    })
  }
  return seriesList.map((item) => {
    const record = isPlainObject(item) ? item : {}
    return {
      ...record,
      type: 'bar',
      barMaxWidth: 38,
      itemStyle: { borderRadius: [7, 7, 0, 0], ...(isPlainObject(record.itemStyle) ? record.itemStyle : {}) },
    }
  })
}

function prettifyAxis(axis: unknown, direction: 'x' | 'y') {
  const axisRecord = Array.isArray(axis) ? axis[0] : axis
  const base = isPlainObject(axisRecord) ? axisRecord : {}
  return {
    ...base,
    axisLine: { lineStyle: { color: '#d0d8e8' }, ...(isPlainObject(base.axisLine) ? base.axisLine : {}) },
    axisTick: { show: false, ...(isPlainObject(base.axisTick) ? base.axisTick : {}) },
    axisLabel: {
      color: '#667085',
      fontSize: 12,
      hideOverlap: true,
      ...(direction === 'x' ? { interval: 0, rotate: 0 } : {}),
      ...(isPlainObject(base.axisLabel) ? base.axisLabel : {}),
    },
    splitLine: direction === 'y'
      ? { show: true, lineStyle: { color: '#e9eef8', type: 'dashed' }, ...(isPlainObject(base.splitLine) ? base.splitLine : {}) }
      : { show: false, ...(isPlainObject(base.splitLine) ? base.splitLine : {}) },
    ...(direction === 'y'
      ? {
          nameGap: Math.max(toFiniteNumber(base.nameGap) || 0, 18),
          nameTextStyle: {
            color: '#98a2b3',
            fontSize: 12,
            padding: [0, 0, 8, 0],
            ...(isPlainObject(base.nameTextStyle) ? base.nameTextStyle : {}),
          },
        }
      : {}),
  }
}

function clonePlainObject(value: unknown): Record<string, unknown> | null {
  if (!isPlainObject(value)) return null
  try {
    return JSON.parse(JSON.stringify(value)) as Record<string, unknown>
  } catch {
    return { ...value }
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function toFiniteNumber(value: unknown) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function chartPalette() {
  return ['#2563eb', '#10b981', '#f97316', '#8b5cf6', '#06b6d4', '#ef4444', '#84cc16', '#f59e0b']
}

function normalizeChartKind(value: unknown): 'bar' | 'pie' | 'line' | '' {
  const kind = String(value || '').trim().toLowerCase()
  if (kind === 'pie' || kind === 'bar' || kind === 'line') return kind
  return ''
}

function inferChartKind(title: string, subtitle: string, data: { label: string; value: unknown }[]): 'bar' | 'pie' | 'line' {
  if (data.length < 2 || data.length > 8) return 'bar'
  const joined = `${title} ${subtitle}`.toLowerCase()
  if (/trend|time|timeline|line/.test(joined)) return 'line'
  if (/趋势|变化|走势|时间|按月|按日|同比|环比/.test(`${title}${subtitle}`)) return 'line'
  if (/pie|donut|ring|proportion|share|composition/.test(joined)) return 'pie'
  if (/占比|构成|分布|份额|比例/.test(`${title}${subtitle}`)) return 'pie'
  if (/数量|数|规模|笔数|金额|总量/.test(`${title}${subtitle}`) && data.length <= 6) return 'pie'
  return 'bar'
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

function reportPythonResult(report: Record<string, unknown>): Record<string, unknown> | null {
  const value = report.python_result
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function reportAnalysisSummary(report: Record<string, unknown>): string[] {
  const result = reportPythonResult(report)
  if (!result) return []
  const lines: string[] = []
  const mode = String(result.analysis_mode || result.mode || '')
  if (mode) lines.push(`分析模式：${analysisModeText(mode)}`)
  const rowCount = result.row_count ?? report.row_count
  if (rowCount !== undefined && rowCount !== null && rowCount !== '') lines.push(`参与分析的数据行数：${rowCount}`)
  const metrics = fieldDescriptorItems(result.metrics)
  if (metrics.length) lines.push(`识别指标：${metrics.map(item => item.label || item.name || item.field).filter(Boolean).join('、')}`)
  const dimensions = fieldDescriptorItems(result.dimensions)
  if (dimensions.length) lines.push(`识别维度：${dimensions.map(item => item.label || item.name || item.field).filter(Boolean).join('、')}`)
  const computedItems = Array.isArray(result.computed_items) ? result.computed_items : []
  computedItems.slice(0, 3).forEach((item) => {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      const record = item as Record<string, unknown>
      const label = String(record.label || record.name || record.title || '')
      const value = record.value
      if (label) lines.push(`${label}：${formatReportValue(value)}`)
    } else if (item !== undefined && item !== null) {
      lines.push(String(item))
    }
  })
  const insights = Array.isArray(result.insights) ? result.insights.map((item: unknown) => stripInlineMarkdown(String(item))).filter(Boolean) : []
  insights.slice(0, 3).forEach((item: string) => lines.push(item))
  return Array.from(new Set(lines)).slice(0, 8)
}

function fieldDescriptorItems(value: unknown): ReportFieldDescriptor[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item: unknown): ReportFieldDescriptor | null => {
      if (typeof item === 'string') return { field: item, key: item, name: item, label: reportFieldLabel(item) }
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        const record = item as Record<string, unknown>
        const field = String(record.field || record.key || record.name || '')
        return {
          field,
          key: String(record.key || field),
          name: String(record.name || field),
          label: String(record.label || record.title || (field ? reportFieldLabel(field) : '')),
        }
      }
      return null
    })
    .filter((item): item is { field: string; key: string; name: string; label: string } => !!item)
}

function analysisModeText(mode: string) {
  const labels: Record<string, string> = {
    ranking: '排名分析',
    trend: '趋势分析',
    compare: '对比分析',
    distribution: '分布分析',
    summary: '汇总分析',
  }
  return labels[mode] || mode
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
  return semanticLabels.value[key] || humanizeField(key)
}

function errorStageText(message: ChatMessage) {
  const node = message.error?.node || ''
  if (node === 'semantic_enhance') return '语义增强'
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
  const labels: Record<string, string> = {}
  for (const metric of assets.metric || []) {
    const key = String(metric.metric_key || '')
    const name = String(metric.name || '')
    if (key && name) labels[key] = name
  }
  for (const mapping of assets.mapping || []) {
    const key = String(mapping.asset_key || '')
    const name = String(mapping.name || mapping.description || mapping.column_name || '')
    if (key && name && !labels[key]) labels[key] = name
  }
  return labels
}

function buildSemanticExamples(assets: Record<string, Record<string, unknown>[]>) {
  const examples: string[] = []
  for (const template of assets.template || []) {
    if (Array.isArray(template.examples)) {
      examples.push(...template.examples.map(String))
    }
  }
  for (const rule of assets.rule || []) {
    const expression =
      rule.expression && typeof rule.expression === 'object'
        ? (rule.expression as Record<string, unknown>)
        : {}
    const rewrites = Array.isArray(expression.rewrites) ? expression.rewrites : []
    for (const item of rewrites) {
      if (!item || typeof item !== 'object') continue
      const record = item as Record<string, unknown>
      const template = String(record.template || '')
      if (template && !template.includes('{')) examples.push(template)
    }
  }
  return Array.from(new Set(examples)).slice(0, 4)
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

.answer-report-body {
  padding: 0;
}

.inline-report-head {
  padding: 16px 18px 10px;
  border-bottom: 1px solid var(--wq-border);
  background: #fff;
}

.inline-report-head > span {
  color: var(--wq-primary);
  font-size: 12px;
  font-weight: 760;
}

.inline-report-head h4 {
  margin: 8px 0 0;
  color: var(--wq-text);
  font-size: 22px;
  line-height: 1.35;
  font-weight: 800;
}

.inline-report-head p {
  margin: 10px 0 0;
  color: var(--wq-muted);
  font-size: 14px;
  line-height: 1.75;
}

.inline-report-section {
  border-top: 0;
  border-left: 0;
  border-right: 0;
  border-bottom: 0;
  border-radius: 0;
  background: transparent;
}

.inline-report-markdown {
  max-width: none;
  margin: 0;
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
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
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


.analysis-process {
  max-width: 100%;
  margin-bottom: 16px;
}

.analysis-process-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #dbe6f5;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
  color: #344054;
  font-size: 13px;
  cursor: pointer;
  text-align: left;
}

.analysis-process-toggle:hover {
  border-color: #b9c8ff;
  background: #f8fbff;
}

.analysis-process-toggle span {
  font-weight: 680;
}

.analysis-process-toggle small {
  margin-left: auto;
  color: var(--wq-subtle);
  font-size: 12px;
}

.analysis-flow {
  display: grid;
  gap: 20px;
  padding: 4px 0 2px;
}

.analysis-step {
  min-width: 0;
  padding-bottom: 2px;
}

.analysis-step + .analysis-step {
  border-top: 1px solid #eef2f7;
  padding-top: 18px;
}

.analysis-step-heading {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  margin-bottom: 8px;
}

.analysis-step-heading h3 {
  margin: 0;
  color: #1d2939;
  font-size: 16px;
  line-height: 1.35;
  font-weight: 760;
}

.analysis-step-number,
.analysis-step-icon {
  width: 24px;
  height: 24px;
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--wq-primary-soft);
  color: var(--wq-primary);
  font-size: 12px;
  font-weight: 760;
}

.analysis-step.done .analysis-step-number,
.analysis-step.done .analysis-step-icon {
  background: #ecfdf3;
  color: #079455;
}

.analysis-step-state {
  color: var(--wq-subtle);
  font-size: 12px;
}

.analysis-step.running .analysis-step-state {
  color: var(--wq-primary);
}

.analysis-lead,
.analysis-live-lines p {
  margin: 0;
  color: #344054;
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.analysis-live-lines {
  display: grid;
  gap: 4px;
  margin: 6px 0 0 33px;
}

.analysis-live-lines p {
  color: var(--wq-subtle);
  font-size: 13px;
}

.analysis-block {
  margin-top: 10px;
  margin-left: 33px;
  min-width: 0;
}

.analysis-block h4,
.analysis-subtitle {
  margin: 0 0 7px;
  color: #475467;
  font-size: 13px;
  line-height: 1.45;
  font-weight: 720;
}

.analysis-block ul {
  margin: 0;
  padding-left: 18px;
  color: #344054;
  font-size: 13px;
  line-height: 1.75;
}

.analysis-block li {
  margin: 2px 0;
  overflow-wrap: anywhere;
}

.compact-list {
  columns: 1;
}

.analysis-code-block {
  margin: 10px 0 0 33px;
  max-width: calc(100% - 33px);
  border: 1px solid #dbe6f5;
  border-radius: 8px;
  background: #fbfdff;
  overflow: hidden;
}

.analysis-code-block.python {
  background: #101828;
  border-color: #101828;
}

.analysis-code-block.json {
  background: #f8fafc;
}

.analysis-code-block pre {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  padding: 12px 14px;
  white-space: pre-wrap;
  word-break: break-word;
}

.analysis-code-block code {
  color: #344054;
  font-size: 12px;
  line-height: 1.7;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.analysis-code-block.python code {
  color: #e6edf7;
}

.analysis-subtitle {
  margin: 12px 0 0 33px;
}

.analysis-table {
  margin: 12px 0 0 33px;
  max-width: calc(100% - 33px);
  overflow-x: auto;
  border: 1px solid #dbe6f5;
  border-radius: 8px;
  background: #fff;
}

.analysis-table table {
  width: 100%;
  border-collapse: collapse;
  min-width: 420px;
}

.analysis-table th,
.analysis-table td {
  border-bottom: 1px solid #edf2f7;
  padding: 9px 10px;
  text-align: left;
  color: #344054;
  font-size: 13px;
  line-height: 1.45;
  white-space: nowrap;
}

.analysis-table th {
  position: sticky;
  top: 0;
  background: #f8fbff;
  font-weight: 720;
}

.analysis-table th span,
.analysis-table th small {
  display: block;
}

.analysis-table th small {
  margin-top: 2px;
  color: #98a2b3;
  font-weight: 400;
}

.analysis-report-text {
  margin: 10px 0 0 33px;
  color: #263448;
}

.analysis-report-text pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: inherit;
  font: inherit;
  line-height: 1.75;
}

.analysis-chart-list {
  display: grid;
  gap: 10px;
  margin: 12px 0 0 33px;
}

.analysis-mini-chart {
  padding: 12px;
  border: 1px solid #dbe6f5;
  border-radius: 8px;
  background: #fff;
}

.analysis-mini-chart strong,
.analysis-mini-chart span {
  display: block;
}

.analysis-mini-chart strong {
  color: #1d2939;
  font-size: 14px;
}

.analysis-mini-chart span {
  margin: 4px 0 10px;
  color: var(--wq-subtle);
  font-size: 12px;
}

.analysis-mini-bar {
  display: grid;
  grid-template-columns: minmax(72px, 120px) minmax(80px, 1fr) auto;
  gap: 8px;
  align-items: center;
  margin-top: 7px;
}

.analysis-mini-bar em {
  color: #475467;
  font-style: normal;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.analysis-mini-bar i {
  height: 8px;
  border-radius: 999px;
  background: var(--wq-primary);
}

.analysis-mini-bar b {
  color: #344054;
  font-size: 12px;
  font-weight: 680;
}

.analysis-stream-cursor {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--wq-subtle);
  font-size: 13px;
}

.analysis-stream-cursor span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--wq-primary);
  box-shadow: 0 0 0 0 rgba(63, 111, 243, 0.35);
  animation: analysisPulse 1.2s infinite;
}

.analysis-stream-cursor p {
  margin: 0;
}

@keyframes analysisPulse {
  0% { box-shadow: 0 0 0 0 rgba(63, 111, 243, 0.35); }
  70% { box-shadow: 0 0 0 8px rgba(63, 111, 243, 0); }
  100% { box-shadow: 0 0 0 0 rgba(63, 111, 243, 0); }
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

.result-meta-tags {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
  flex-wrap: wrap;
  flex: 0 0 auto;
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

:deep(.report-dialog.el-dialog) {
  margin: 0 auto;
  max-height: calc(100vh - 40px);
  display: flex;
  flex-direction: column;
}

:deep(.report-dialog .el-dialog__header) {
  padding: 18px 22px 14px;
  margin-right: 0;
  border-bottom: 1px solid var(--wq-border);
}

:deep(.report-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 18px;
  background: #f8fafc;
}

:deep(.report-dialog-overlay .el-overlay-dialog) {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px 24px;
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

.report-markdown-preview {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}

.report-markdown-preview .report-md-heading strong {
  color: var(--wq-text);
  font-size: 14px;
  line-height: 1.45;
}

.report-markdown-preview p,
.report-markdown-preview li {
  color: #475467;
  font-size: 13px;
  line-height: 1.7;
}

.report-mini-chart {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #dbe6f5;
  border-radius: 8px;
  background: #f8fbff;
}

.report-mini-chart strong {
  min-width: 0;
  color: var(--wq-text);
  font-size: 13px;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-mini-chart span {
  color: var(--wq-subtle);
  font-size: 12px;
  white-space: nowrap;
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
  max-height: calc(100vh - 140px);
  overflow-y: auto;
  padding: 0;
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
  padding: 16px 18px;
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
  padding: 14px 16px;
}

.report-body-section {
  padding: 16px 18px;
}

.report-markdown-body {
  max-width: 1040px;
  margin: 0 auto;
}

.report-md-block + .report-md-block {
  margin-top: 12px;
}

.report-md-title h1 {
  color: var(--wq-text);
  font-size: 26px;
  line-height: 1.35;
  font-weight: 820;
}

.report-md-heading h2 {
  margin-top: 22px;
  padding-top: 6px;
  color: var(--wq-primary);
  font-size: 19px;
  line-height: 1.45;
  font-weight: 800;
}

.report-md-subheading h3 {
  margin-top: 16px;
  color: #344054;
  font-size: 15px;
  line-height: 1.45;
  font-weight: 740;
}

.report-md-paragraph p {
  color: #344054;
  font-size: 14px;
  line-height: 1.9;
}

.report-md-paragraph code,
.report-md-list code {
  padding: 1px 5px;
  border-radius: 5px;
  background: #eef4ff;
  color: var(--wq-primary);
  font-size: 12px;
}

.report-md-list ul {
  margin: 8px 0 0;
  padding-left: 20px;
}

.report-md-list li {
  color: #344054;
  font-size: 14px;
  line-height: 1.85;
  margin: 4px 0;
}

.report-md-code pre {
  max-height: 360px;
  overflow: auto;
  padding: 14px;
  border-radius: 8px;
  background: #101828;
  color: #e6edf7;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.7;
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

.report-md-chart-card {
  margin: 18px 0;
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

.report-echart {
  width: 100%;
  height: 330px;
  margin-top: 12px;
  border: 1px solid #edf2f7;
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 251, 255, 0.96)),
    radial-gradient(circle at 18% 0%, rgba(37, 99, 235, 0.08), transparent 32%);
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

  .report-echart {
    height: 280px;
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
