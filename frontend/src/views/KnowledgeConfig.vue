<template>
  <div class="page-shell">
    <div class="page-header">
      <div>
        <span class="page-kicker">Semantic Layer</span>
        <h2>语义层配置</h2>
        <p>管理领域本体、指标口径、关系路径、规则和 LogicForm 模板。</p>
      </div>
      <div class="header-actions">
        <el-select
          v-model="domainId"
          placeholder="选择语义层"
          style="width: 260px"
          :disabled="domains.length === 0"
        >
          <el-option
            v-for="domain in domains"
            :key="domain.id"
            :label="`${domain.name} (${domain.domain_key})`"
            :value="domain.id"
          />
        </el-select>
        <el-button :icon="Plus" @click="openCreateDomain">
          新增语义层
        </el-button>
        <el-button :icon="EditPen" :disabled="!selectedDomain" @click="openEditDomain">
          编辑
        </el-button>
        <el-button :icon="Delete" type="danger" plain :disabled="!selectedDomain" @click="handleDeleteDomain">
          删除
        </el-button>
        <el-button :disabled="!selectedDomain" @click="handleCopyDomain">
          复制
        </el-button>
        <el-button @click="handleImportDomain">
          导入
        </el-button>
        <el-button :disabled="!selectedDomain" @click="handleExportDomain">
          导出
        </el-button>
        <el-button :disabled="!selectedDomain" @click="handleValidateDomain">
          保存前校验
        </el-button>
        <el-button :disabled="!selectedDomain" @click="handleCreateSnapshot">
          创建快照
        </el-button>
        <el-button :disabled="!selectedDomain" @click="openSnapshots">
          快照
        </el-button>
        <el-button :loading="runtimeLoading" :disabled="!selectedDomain" @click="handleBuildRuntime">
          构建语义层
        </el-button>
        <el-button type="primary" :loading="syncLoading" :disabled="!selectedDomain" @click="handleSyncVector">
          同步向量
        </el-button>
      </div>
    </div>

    <div class="runtime-summary">
      <div class="summary-item">
        <span>当前语义层</span>
        <strong>{{ selectedDomain?.name || '暂无' }}</strong>
      </div>
      <div class="summary-item">
        <span>对象/事件/状态</span>
        <strong>{{ assetCounts.concept }}</strong>
      </div>
      <div class="summary-item">
        <span>关系</span>
        <strong>{{ assetCounts.relation }}</strong>
      </div>
      <div class="summary-item">
        <span>指标</span>
        <strong>{{ assetCounts.metric }}</strong>
      </div>
      <div class="summary-item">
        <span>规则</span>
        <strong>{{ assetCounts.rule }}</strong>
      </div>
      <div class="summary-item">
        <span>模板</span>
        <strong>{{ assetCounts.template }}</strong>
      </div>
    </div>

    <div class="knowledge-surface">
      <el-empty v-if="domains.length === 0" description="暂无语义层，请先新增一套语义层配置" />
      <el-tabs v-else v-model="activeTab">
        <el-tab-pane
          v-for="tab in assetTabs"
          :key="tab.name"
          :label="tab.label"
          :name="tab.name"
        >
          <div class="tab-header">
            <div>
              <h3>{{ tab.label }}</h3>
              <p>{{ tab.description }}</p>
            </div>
            <el-button type="primary" size="small" @click="openAssetDialog(tab.name)">添加资产</el-button>
          </div>

          <div class="asset-table-wrap">
            <el-table
              :data="assets[tab.name] || []"
              border
              stripe
              size="small"
              class="asset-table"
            >
              <el-table-column v-if="tab.name !== 'mapping'" label="标识" min-width="170">
                <template #default="{ row }">{{ assetKey(row, tab.name) }}</template>
              </el-table-column>
              <el-table-column v-if="tab.name !== 'mapping'" prop="name" label="名称" min-width="150" />
              <el-table-column v-if="tab.name !== 'mapping'" label="类型/角色" min-width="120">
                <template #default="{ row }">{{ assetKind(row, tab.name) }}</template>
              </el-table-column>
              <el-table-column
                v-if="tab.name === 'mapping'"
                label="中文名"
                min-width="150"
              >
                <template #default="{ row }">
                  <div class="mapping-primary">{{ semanticLabel(String(row.asset_key || '')) }}</div>
                </template>
              </el-table-column>
              <el-table-column
                v-if="tab.name === 'mapping'"
                label="资产键"
                min-width="170"
              >
                <template #default="{ row }"><code class="inline-code">{{ row.asset_key }}</code></template>
              </el-table-column>
              <el-table-column
                v-if="tab.name === 'mapping'"
                label="资产类型/角色"
                min-width="130"
              >
                <template #default="{ row }">{{ assetTypeLabel(String(row.asset_type || '')) }} / {{ roleLabel(String(row.role || '')) }}</template>
              </el-table-column>
              <el-table-column
                v-if="tab.name === 'metric'"
                label="可用维度"
                min-width="240"
              >
                <template #default="{ row }">
                  <div class="dim-chips">
                    <el-tag
                      v-for="dim in (row.dimensions || [])"
                      :key="dim"
                      size="small"
                      effect="plain"
                      round
                    >{{ semanticLabel(String(dim)) }}</el-tag>
                  </div>
                </template>
              </el-table-column>
              <el-table-column
                v-if="tab.name === 'metric'"
                label="指标类型"
                width="120"
              >
                <template #default="{ row }">{{ metricTypeLabel(String(row.metric_type || '')) }}</template>
              </el-table-column>
              <el-table-column
                v-if="tab.name === 'mapping'"
                label="表中文名"
                min-width="180"
              >
                <template #default="{ row }">{{ tableNameLabel(String(row.table_name || '')) }}</template>
              </el-table-column>
              <el-table-column
                v-if="tab.name === 'mapping'"
                label="表名"
                min-width="220"
              >
                <template #default="{ row }"><code class="inline-code">{{ row.table_name }}</code></template>
              </el-table-column>
              <el-table-column
                v-if="tab.name === 'mapping'"
                label="字段中文名"
                min-width="150"
              >
                <template #default="{ row }">{{ columnNameLabel(String(row.asset_key || ''), String(row.column_name || '')) }}</template>
              </el-table-column>
              <el-table-column
                v-if="tab.name === 'mapping'"
                label="字段名"
                min-width="190"
              >
                <template #default="{ row }"><code class="inline-code">{{ row.column_name || '-' }}</code></template>
              </el-table-column>
              <el-table-column
                v-if="tab.name === 'mapping'"
                prop="data_type"
                label="数据类型"
                width="100"
              >
                <template #default="{ row }"><code class="inline-code">{{ row.data_type || '-' }}</code></template>
              </el-table-column>
              <el-table-column v-if="tab.name !== 'mapping'" prop="description" label="描述" min-width="260" show-overflow-tooltip />
              <el-table-column label="操作" width="178" fixed="right">
                <template #default="{ row }">
                  <div class="asset-actions">
                    <el-button link type="primary" size="small" @click="openAssetDetail(tab.name, row)">详情</el-button>
                    <el-button link type="primary" size="small" @click="openEditAsset(tab.name, row)">编辑</el-button>
                    <el-button link type="danger" size="small" @click="handleDeleteAsset(tab.name, row)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog
      v-model="showDomainDialog"
      :title="domainDialogMode === 'edit' ? '编辑语义层' : '新增语义层'"
      width="620px"
      class="domain-dialog"
    >
      <el-form :model="domainForm" label-width="110px" label-position="left">
        <el-form-item label="名称">
          <el-input v-model="domainForm.name" placeholder="如 订单分析" />
        </el-form-item>
        <el-form-item label="标识">
          <el-input v-model="domainForm.domain_key" placeholder="如 order_analysis" :disabled="domainDialogMode === 'edit'" />
        </el-form-item>
        <el-form-item label="默认数据源">
          <el-select v-model="domainForm.datasource_id" clearable filterable placeholder="可选，选择语义层默认数据源">
            <el-option
              v-for="ds in datasources"
              :key="ds.id"
              :label="`${ds.name} · ${ds.database_name}`"
              :value="ds.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="domainForm.status">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="inactive" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="domainForm.description"
            type="textarea"
            :rows="3"
            placeholder="说明这套语义层适用的业务范围、数据口径和使用边界"
          />
        </el-form-item>
      </el-form>
      <div class="domain-form-note">
        智能体使用哪套语义层，请在“智能体管理”里绑定；这里负责维护可复用的语义层配置。
      </div>
      <template #footer>
        <el-button @click="showDomainDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSaveDomain">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showAssetDialog" width="1040" class="asset-dialog">
      <template #header>
        <div class="asset-dialog-header">
          <h3>{{ assetDialogMode === 'edit' ? '编辑' : '添加' }}{{ currentAssetTab?.label || '语义资产' }}</h3>
          <el-tooltip content="查看填写说明" placement="top">
            <button
              class="asset-guide-button"
              type="button"
              :aria-label="`查看${currentAssetTab?.label || '语义资产'}填写说明`"
              @click="openAssetGuide"
            >
              <el-icon><QuestionFilled /></el-icon>
            </button>
          </el-tooltip>
        </div>
      </template>
      <div class="asset-editor">
        <section class="asset-form-panel">
          <el-form :model="assetDraft" label-width="112px" label-position="left">
            <template v-if="editingAssetType === 'concept'">
              <el-form-item label="标识">
                <el-input v-model="assetDraft.concept_key" placeholder="如 Order" />
              </el-form-item>
              <el-form-item label="类型">
                <el-select v-model="assetDraft.concept_type">
                  <el-option label="对象" value="object" />
                  <el-option label="事件" value="event" />
                  <el-option label="状态" value="state" />
                  <el-option label="维度" value="dimension" />
                  <el-option label="动作" value="action" />
                </el-select>
              </el-form-item>
              <el-form-item label="名称">
                <el-input v-model="assetDraft.name" placeholder="如 订单" />
              </el-form-item>
              <el-form-item label="描述">
                <el-input v-model="assetDraft.description" type="textarea" :rows="3" />
              </el-form-item>
              <el-form-item label="同义词">
                <el-input v-model="assetDraft.synonyms_text" placeholder="多个词用逗号或换行分隔" />
              </el-form-item>
            </template>

            <template v-else-if="editingAssetType === 'relation'">
              <el-form-item label="标识">
                <el-input v-model="assetDraft.relation_key" placeholder="如 order_to_customer" />
              </el-form-item>
              <el-form-item label="类型">
                <el-select v-model="assetDraft.relation_type">
                  <el-option label="关联路径" value="join_path" />
                  <el-option label="对象关系" value="relationship" />
                  <el-option label="事件链路" value="event_flow" />
                  <el-option label="状态流转" value="state_transition" />
                </el-select>
              </el-form-item>
              <el-form-item label="名称">
                <el-input v-model="assetDraft.name" />
              </el-form-item>
              <el-form-item label="源概念">
                <el-input v-model="assetDraft.source_concept" placeholder="如 Order" />
              </el-form-item>
              <el-form-item label="目标概念">
                <el-input v-model="assetDraft.target_concept" placeholder="如 Customer" />
              </el-form-item>
              <el-form-item label="左表字段">
                <el-input v-model="assetDraft.join_left" placeholder="如 orders.customer_id" />
              </el-form-item>
              <el-form-item label="右表字段">
                <el-input v-model="assetDraft.join_right" placeholder="如 customers.customer_id" />
              </el-form-item>
              <el-form-item label="描述">
                <el-input v-model="assetDraft.description" type="textarea" :rows="3" />
              </el-form-item>
            </template>

            <template v-else-if="editingAssetType === 'metric'">
              <el-form-item label="标识">
                <el-input v-model="assetDraft.metric_key" placeholder="如 order_count" />
              </el-form-item>
              <el-form-item label="名称">
                <el-input v-model="assetDraft.name" placeholder="如 订单数" />
              </el-form-item>
              <el-form-item label="指标类型">
                <el-select v-model="assetDraft.metric_type">
                  <el-option label="度量" value="measure" />
                  <el-option label="比率" value="ratio" />
                  <el-option label="计数" value="count" />
                  <el-option label="维度指标" value="dimension_metric" />
                </el-select>
              </el-form-item>
              <el-form-item label="基础表">
                <el-input v-model="assetDraft.base_table" placeholder="如 orders" />
              </el-form-item>
              <el-form-item label="时间字段">
                <el-input v-model="assetDraft.time_field" placeholder="如 orders.created_at" />
              </el-form-item>
              <el-form-item label="计算公式">
                <el-input v-model="assetDraft.formula_sql" type="textarea" :rows="3" placeholder="支持 {base} 表别名占位" />
              </el-form-item>
              <el-form-item label="可用维度">
                <el-input v-model="assetDraft.dimensions_text" placeholder="如 product_type, region, channel" />
              </el-form-item>
              <el-form-item label="同义词">
                <el-input v-model="assetDraft.synonyms_text" placeholder="多个词用逗号或换行分隔" />
              </el-form-item>
              <el-form-item label="默认过滤">
                <div class="inline-fields">
                  <el-input v-model="assetDraft.default_filter_field" placeholder="字段" />
                  <el-select v-model="assetDraft.default_filter_operator" class="operator-select">
                    <el-option label="=" value="=" />
                    <el-option label="!=" value="!=" />
                    <el-option label="in" value="in" />
                  </el-select>
                  <el-input v-model="assetDraft.default_filter_value" placeholder="值" />
                </div>
              </el-form-item>
              <el-form-item label="描述">
                <el-input v-model="assetDraft.description" type="textarea" :rows="3" />
              </el-form-item>
            </template>

            <template v-else-if="editingAssetType === 'rule'">
              <el-form-item label="标识">
                <el-input v-model="assetDraft.rule_key" placeholder="如 order_count_definition" />
              </el-form-item>
              <el-form-item label="规则类型">
                <el-select v-model="assetDraft.rule_type">
                  <el-option label="口径定义" value="definition" />
                  <el-option label="过滤规则" value="filter" />
                  <el-option label="时间规则" value="time" />
                  <el-option label="约束规则" value="constraint" />
                </el-select>
              </el-form-item>
              <el-form-item label="名称">
                <el-input v-model="assetDraft.name" />
              </el-form-item>
              <el-form-item label="适用对象">
                <el-input v-model="assetDraft.applies_to_text" placeholder="如 order_count, product_type" />
              </el-form-item>
              <el-form-item label="表达式键">
                <el-input v-model="assetDraft.expression_key" placeholder="如 status" />
              </el-form-item>
              <el-form-item label="表达式值">
                <el-input v-model="assetDraft.expression_value" placeholder="如 paid, shipped" />
              </el-form-item>
              <el-form-item label="级别">
                <el-select v-model="assetDraft.severity">
                  <el-option label="提示" value="info" />
                  <el-option label="警告" value="warning" />
                  <el-option label="错误" value="error" />
                </el-select>
              </el-form-item>
              <el-form-item label="描述">
                <el-input v-model="assetDraft.description" type="textarea" :rows="3" />
              </el-form-item>
            </template>

            <template v-else-if="editingAssetType === 'mapping'">
              <el-form-item label="资产类型">
                <el-select v-model="assetDraft.asset_type">
                  <el-option label="维度" value="dimension" />
                  <el-option label="过滤项" value="filter" />
                  <el-option label="指标" value="metric" />
                  <el-option label="概念" value="concept" />
                </el-select>
              </el-form-item>
              <el-form-item label="资产键">
                <el-input v-model="assetDraft.asset_key" placeholder="如 product_type" />
              </el-form-item>
              <el-form-item label="角色">
                <el-select v-model="assetDraft.role">
                  <el-option label="维度" value="dimension" />
                  <el-option label="过滤" value="filter" />
                  <el-option label="时间" value="time" />
                  <el-option label="字段" value="field" />
                  <el-option label="度量" value="measure" />
                </el-select>
              </el-form-item>
              <el-form-item label="表名">
                <el-input v-model="assetDraft.table_name" placeholder="如 orders" />
              </el-form-item>
              <el-form-item label="字段名">
                <el-input v-model="assetDraft.column_name" placeholder="如 product_type" />
              </el-form-item>
              <el-form-item label="表达式">
                <el-input v-model="assetDraft.expression_sql" placeholder="可选，字段映射为空时使用" />
              </el-form-item>
              <el-form-item label="数据类型">
                <el-input v-model="assetDraft.data_type" placeholder="如 varchar / int / decimal" />
              </el-form-item>
            </template>

            <template v-else>
              <el-form-item label="标识">
                <el-input v-model="assetDraft.template_key" placeholder="如 metric_query" />
              </el-form-item>
              <el-form-item label="意图类型">
                <el-select v-model="assetDraft.intent_type">
                  <el-option label="指标查询" value="metric_query" />
                  <el-option label="元数据查询" value="metadata_query" />
                  <el-option label="普通问答" value="chat" />
                </el-select>
              </el-form-item>
              <el-form-item label="名称">
                <el-input v-model="assetDraft.name" />
              </el-form-item>
              <el-form-item label="必填槽位">
                <el-input v-model="assetDraft.required_slots_text" placeholder="如 metrics" />
              </el-form-item>
              <el-form-item label="可选槽位">
                <el-input v-model="assetDraft.optional_slots_text" placeholder="如 dimensions, filters, time_range" />
              </el-form-item>
              <el-form-item label="编译策略">
                <el-select v-model="assetDraft.compile_strategy_type">
                  <el-option label="指标查询" value="metric_select" />
                  <el-option label="元数据查询" value="metadata_select" />
                </el-select>
              </el-form-item>
              <el-form-item label="示例问法">
                <el-input v-model="assetDraft.examples_text" type="textarea" :rows="3" placeholder="每行一个示例" />
              </el-form-item>
              <el-form-item label="描述">
                <el-input v-model="assetDraft.description" type="textarea" :rows="3" />
              </el-form-item>
            </template>
          </el-form>
        </section>

        <section class="json-preview-panel">
          <div class="preview-title">JSON 预览</div>
          <pre>{{ assetJsonPreview }}</pre>
        </section>
      </div>
      <template #footer>
        <el-button @click="showAssetDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSaveAsset">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="showAssetDetail"
      :title="assetDetailTitle"
      size="640px"
      append-to-body
      class="asset-detail-drawer"
    >
      <div v-if="selectedAsset" class="asset-detail">
        <div class="detail-identity">
          <span>{{ currentDetailTab?.label || '语义资产' }}</span>
          <strong>{{ detailPrimaryName }}</strong>
          <code>{{ assetKey(selectedAsset, selectedAssetType) }}</code>
        </div>

        <section class="detail-section">
          <h4>配置详情</h4>
          <dl class="detail-grid">
            <template v-for="item in assetDetailRows" :key="item.key">
              <dt>{{ item.label }}</dt>
              <dd>
                <pre v-if="item.multiline">{{ item.value }}</pre>
                <span v-else>{{ item.value }}</span>
              </dd>
            </template>
          </dl>
        </section>

        <section class="detail-section">
          <h4>原始 JSON</h4>
          <pre class="detail-json">{{ selectedAssetJson }}</pre>
        </section>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <el-button @click="showAssetDetail = false">关闭</el-button>
          <el-button type="primary" :disabled="!selectedAsset" @click="selectedAsset && openEditAsset(selectedAssetType, selectedAsset)">
            编辑
          </el-button>
          <el-button type="danger" plain :disabled="!selectedAsset" @click="selectedAsset && handleDeleteAsset(selectedAssetType, selectedAsset)">
            删除
          </el-button>
        </div>
      </template>
    </el-drawer>

    <el-drawer
      v-model="showAssetGuide"
      :title="currentAssetGuide?.title || '语义资产填写说明'"
      size="560px"
      append-to-body
      class="asset-guide-drawer"
    >
      <div v-if="currentAssetGuide" class="asset-guide">
        <p class="asset-guide-subtitle">{{ currentAssetGuide.subtitle }}</p>
        <section v-for="field in currentAssetGuide.fields" :key="field.key" class="asset-guide-section">
          <div class="asset-guide-field-title">
            <h4>{{ field.label }}</h4>
            <code>{{ field.key }}</code>
          </div>
          <p>{{ field.purpose }}</p>
          <div class="asset-guide-block">
            <strong>怎么填写</strong>
            <ul>
              <li v-for="item in field.instructions" :key="item">{{ item }}</li>
            </ul>
          </div>
          <div class="asset-guide-block">
            <strong>示例</strong>
            <div v-for="example in field.examples" :key="example" class="guide-example">
              {{ example }}
            </div>
          </div>
          <div v-if="field.tips?.length" class="asset-guide-block">
            <strong>注意事项</strong>
            <ul>
              <li v-for="tip in field.tips" :key="tip">{{ tip }}</li>
            </ul>
          </div>
        </section>
      </div>
    </el-drawer>

    <el-drawer
      v-model="showSnapshotDrawer"
      title="语义层快照"
      size="620px"
      append-to-body
    >
      <el-empty v-if="snapshots.length === 0" description="暂无快照" />
      <div v-else class="snapshot-list">
        <article v-for="item in snapshots" :key="String(item.id)" class="snapshot-card">
          <div>
            <strong>{{ item.name }}</strong>
            <p>{{ item.description || '无说明' }}</p>
          </div>
          <div class="snapshot-meta">
            <span>{{ formatSnapshotCounts(item.asset_counts) }}</span>
            <small>{{ item.created_at }}</small>
          </div>
          <div class="snapshot-actions">
            <el-button size="small" @click="handleDiffSnapshot(item)">差异</el-button>
            <el-button size="small" type="warning" plain @click="handleRollbackSnapshot(item)">回滚</el-button>
          </div>
        </article>
      </div>
    </el-drawer>

    <el-dialog v-model="showSnapshotDiffDialog" title="快照差异" width="760px" append-to-body>
      <div v-if="snapshotDiff" class="snapshot-diff">
        <div class="snapshot-diff-summary">
          <div>
            <span>新增</span>
            <strong>{{ snapshotDiffSummary.added }}</strong>
          </div>
          <div>
            <span>删除</span>
            <strong>{{ snapshotDiffSummary.removed }}</strong>
          </div>
          <div>
            <span>变更</span>
            <strong>{{ snapshotDiffSummary.changed }}</strong>
          </div>
          <div>
            <span>领域配置</span>
            <strong>{{ snapshotDiffSummary.domain_changed ? '有变化' : '无变化' }}</strong>
          </div>
        </div>
        <section v-if="snapshotDomainChanges.length" class="snapshot-diff-section">
          <h4>领域配置差异</h4>
          <div v-for="item in snapshotDomainChanges" :key="item.field" class="snapshot-change-row">
            <span>{{ detailFieldLabels[item.field] || item.field }}</span>
            <p>当前：{{ formatDiffValue(item.current) }}</p>
            <p>快照：{{ formatDiffValue(item.snapshot) }}</p>
          </div>
        </section>
        <section v-for="section in snapshotAssetDiffSections" :key="section.type" class="snapshot-diff-section">
          <h4>{{ assetTypeName(section.type) }}</h4>
          <p>新增 {{ section.added.length }} 项，删除 {{ section.removed.length }} 项，变更 {{ section.changed.length }} 项</p>
          <div v-if="section.added.length" class="snapshot-key-list"><strong>当前新增：</strong>{{ section.added.join('、') }}</div>
          <div v-if="section.removed.length" class="snapshot-key-list"><strong>快照中存在但当前已删除：</strong>{{ section.removed.join('、') }}</div>
          <div v-if="section.changed.length" class="snapshot-key-list"><strong>内容变更：</strong>{{ snapshotChangedKeys(section.changed) }}</div>
        </section>
      </div>
      <template #footer>
        <el-button @click="showSnapshotDiffDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, EditPen, Plus, QuestionFilled } from '@element-plus/icons-vue'
import {
  buildSemanticRuntime,
  copySemanticDomain,
  createSemanticSnapshot,
  deleteSemanticDomain,
  deleteSemanticAsset,
  diffSemanticSnapshot,
  exportSemanticDomain,
  fetchAgents,
  fetchAllDatasources,
  fetchAllSemanticDomains,
  fetchSemanticAssets,
  fetchSemanticSnapshots,
  importSemanticDomain,
  rollbackSemanticSnapshot,
  syncSemanticVector,
  upsertSemanticDomain,
  upsertSemanticAsset,
  validateSemanticDomain,
  type AgentItem,
  type DatasourceItem,
  type SemanticDomain,
  type SemanticDomainRequest,
} from '../api'

type AssetDraft = Record<string, any>
type AssetGuideField = {
  key: string
  label: string
  title: string
  purpose: string
  instructions: string[]
  examples: string[]
  tips?: string[]
}
type AssetGuidePage = {
  title: string
  subtitle: string
  fields: AssetGuideField[]
}

const assetTabs = [
  { name: 'concept', label: '对象/事件/状态', description: '业务对象、业务事件、状态和动作边界。' },
  { name: 'relation', label: '关系', description: '对象关系、事件链路、状态变化和 JOIN 路径。' },
  { name: 'metric', label: '指标', description: '指标口径、公式、默认时间字段和可切维度。' },
  { name: 'rule', label: '规则', description: '过滤规则、时间规则、权限边界和动作约束。' },
  { name: 'mapping', label: '映射', description: '语义资产到物理表字段或受控表达式的映射。' },
  { name: 'template', label: 'LogicForm 模板', description: '自然语言意图到结构化槽位的模板。' },
]

const assetGuidePages: Record<string, AssetGuidePage> = {
  concept: {
    title: '对象/事件/状态填写说明',
    subtitle: '用于定义业务世界里有哪些核心对象、发生过哪些事件、会经历哪些状态。它是后续关系、指标和规则的业务语境。',
    fields: [
      {
        key: 'concept_key',
        label: '标识',
        title: '标识 concept_key',
        purpose: '概念在语义层里的唯一英文键，关系、规则和向量召回都会引用它。',
        instructions: ['使用稳定的英文 PascalCase 或 snake_case。', '对象建议用名词，事件建议用动词过去式或业务动作，状态建议用状态名。', '保存后不要随意改名，避免关系和规则引用失效。'],
        examples: ['Order', 'RepaymentPaid', 'OverdueBucket'],
      },
      {
        key: 'concept_type',
        label: '类型',
        title: '类型 concept_type',
        purpose: '告诉系统这个概念是对象、事件、状态、维度还是动作。',
        instructions: ['对象：业务实体，如订单、客户。', '事件：发生过的动作，如下单、支付、发货。', '状态：某个对象所处阶段，如订单状态、审批状态。'],
        examples: ['Order 选择“对象”', 'OrderPaid 选择“事件”', 'OrderStatus 选择“状态”'],
      },
      {
        key: 'name',
        label: '名称',
        title: '名称',
        purpose: '业务人员看到的中文名称，也帮助大模型理解用户问法。',
        instructions: ['使用业务团队日常叫法。', '短而明确，不要写成一整句描述。'],
        examples: ['订单', '支付成功', '订单状态'],
      },
      {
        key: 'description',
        label: '描述',
        title: '描述',
        purpose: '说明这个概念的业务边界，降低模型误解。',
        instructions: ['写清楚它代表什么，不代表什么。', '必要时说明生命周期或取值范围。'],
        examples: ['客户提交并完成支付的业务订单。'],
      },
      {
        key: 'synonyms',
        label: '同义词',
        title: '同义词',
        purpose: '把用户口语、旧系统名称、业务黑话映射到这个概念。',
        instructions: ['多个词用逗号或换行分隔。', '优先填真实问数时会出现的叫法。'],
        examples: ['订单, 交易, 下单'],
      },
    ],
  },
  relation: {
    title: '关系填写说明',
    subtitle: '用于定义概念之间怎样关联，尤其是跨表查询时从一张表 JOIN 到另一张表的路径。',
    fields: [
      {
        key: 'relation_key',
        label: '标识',
        title: '标识 relation_key',
        purpose: '关系在语义层里的唯一英文键。',
        instructions: ['使用英文 snake_case。', '建议按“源概念_to_目标概念”命名。'],
        examples: ['order_to_customer', 'order_to_payment'],
      },
      {
        key: 'relation_type',
        label: '类型',
        title: '类型 relation_type',
        purpose: '说明这条关系的业务性质或技术用途。',
        instructions: ['关联路径：用于 SQL JOIN。', '对象关系：描述两个业务对象的关系。', '事件链路/状态流转：描述业务过程。'],
        examples: ['订单到客户选择“关联路径”'],
      },
      {
        key: 'name',
        label: '名称',
        title: '名称',
        purpose: '关系的中文展示名。',
        instructions: ['用“源到目标”的业务说法。', '让配置人员一眼能理解这条关系。'],
        examples: ['订单到客户', '订单到支付'],
      },
      {
        key: 'source_concept',
        label: '源概念',
        title: '源概念',
        purpose: '关系起点，必须引用已经配置过的概念标识。',
        instructions: ['填写概念的英文标识。', '一般对应 JOIN 左侧或查询主对象。'],
        examples: ['Order'],
      },
      {
        key: 'target_concept',
        label: '目标概念',
        title: '目标概念',
        purpose: '关系终点，必须引用已经配置过的概念标识。',
        instructions: ['填写概念的英文标识。', '一般对应 JOIN 右侧或被关联对象。'],
        examples: ['Customer'],
      },
      {
        key: 'join_path',
        label: '左右表字段',
        title: '左右表字段',
        purpose: '告诉 SQL 编译器两张表用哪些字段连接。',
        instructions: ['左表字段和右表字段都建议填写“表名.字段名”。', '字段必须存在于已采集 Schema。', '只配置稳定、真实的一对关系，不要写临时过滤条件。'],
        examples: ['orders.customer_id = customers.customer_id'],
      },
      {
        key: 'description',
        label: '描述',
        title: '描述',
        purpose: '说明这条关系成立的业务条件。',
        instructions: ['写清楚一对一、一对多或多对一。', '如果关系只适用于部分场景，也要说明。'],
        examples: ['一个客户可以产生多个订单。'],
      },
    ],
  },
  metric: {
    title: '指标填写说明',
    subtitle: '用于定义指标口径、公式、默认时间字段和可切维度，是自然语言问数能否稳定生成 SQL 的核心配置。',
    fields: [
      {
        key: 'metric_key',
        label: '标识',
        title: '标识 metric_key',
    purpose: '这是指标在语义层里的唯一英文键，会出现在 LogicForm、语义校验、SQL 别名和结果字段中。',
    instructions: [
      '使用稳定的英文 snake_case，不要使用中文、空格或特殊符号。',
      '命名要表达业务含义，推荐按“指标对象 + 计算含义”组织。',
      '保存后不要随意改名，否则历史问法、维度校验和结果字段都可能失效。',
    ],
    examples: ['order_count', 'conversion_rate', 'revenue'],
    tips: ['如果页面展示需要中文，请填“名称”，不要把中文写进标识。'],
      },
      {
        key: 'name',
        label: '名称',
        title: '名称',
    purpose: '这是业务人员看到的中文指标名，也会帮助大模型把自然语言问题匹配到正确指标。',
    instructions: [
      '用业务团队日常叫法，尽量短而明确。',
      '如果有缩写，可以保留缩写并补充中文含义。',
      '避免只写“比率”“金额”这种过泛名称。',
    ],
    examples: ['订单数', '转化率', '销售额'],
      },
      {
        key: 'metric_type',
        label: '指标类型',
        title: '指标类型',
    purpose: '用于告诉语义层这个指标的计算形态，影响大模型理解、校验和后续展示。',
    instructions: [
      '度量：金额、余额、天数、概率等可聚合数值，例如交易金额、评分。',
      '比率：分子除以分母，例如转化率、复购率。',
      '计数：数量类指标，例如订单数、客户数。',
      '维度指标：本质是维度，但用户会像指标一样提问，例如客户等级、产品类型。',
    ],
    examples: ['转化率选择“比率”', '交易金额选择“度量”', '订单数选择“计数”'],
    tips: ['不确定时先按公式判断：有除法口径通常选“比率”。'],
      },
      {
        key: 'base_table',
        label: '基础表',
        title: '基础表',
    purpose: '指标计算默认从哪张物理表出发，SQL 编译时会把这张表作为 {base} 对应的主表。',
    instructions: [
      '填写已采集 Schema 中真实存在的表名。',
      '选择包含指标核心字段的事实表或指标表。',
      '如果指标需要跨表维度，必须在“关系”里存在可用 JOIN 路径。',
    ],
    examples: ['orders', 'orders', 'payments'],
    tips: ['基础表不是中文表名，必须填数据库里的英文表名。'],
      },
      {
        key: 'time_field',
        label: '时间字段',
        title: '时间字段',
    purpose: '用户问“本月、近三个月、按天/按月”时，语义层默认用这个字段做时间过滤或时间分组。',
    instructions: [
      '推荐填写“表名.字段名”的完整形式。',
      '选择最符合指标统计口径的日期字段，例如创建时间、支付时间、快照时间、事件时间。',
      '如果指标没有时间口径可以留空，但自然语言时间过滤能力会变弱。',
    ],
    examples: ['orders.created_at', 'orders.created_at', 'orders.created_at'],
    tips: ['同一个指标换时间字段，业务结果可能完全不同，配置前要确认口径。'],
      },
      {
        key: 'formula_sql',
        label: '计算公式',
        title: '计算公式',
    purpose: '这是指标真正的 SQL 聚合表达式，编译器会把它放进 SELECT 里生成查询。',
    instructions: [
      '只填写表达式，不要写 SELECT、FROM、WHERE。',
      '用 {base} 表示基础表别名，例如 {base}.`amount`。',
      '比率指标请用 NULLIF 保护分母，避免除零。',
      '字段名建议用反引号包起来，降低关键字冲突风险。',
    ],
    examples: [
      'SUM({base}.`amount`)',
      "SUM(CASE WHEN {base}.`status` = 'paid' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0)",
    ],
    tips: ['如果公式里写了不存在的字段，SQL 执行阶段才会报错；配置前最好对照数据源 Schema。'],
      },
      {
        key: 'dimensions',
        label: '可用维度',
        title: '可用维度',
    purpose: '限定这个指标允许按哪些维度切分。语义校验会用它阻止不合理组合。',
    instructions: [
      '填写语义维度键，不是中文名，也不是物理字段名。',
      '多个维度用逗号或换行分隔。',
      '每个维度最好在“映射”里能找到对应表字段。',
      '跨表维度需要有“关系”路径支撑。',
    ],
    examples: ['product_type, region, channel', 'customer_segment, region, channel'],
    tips: ['用户问“按产品类型看订单数”时，product_type 必须在该指标的可用维度里。'],
      },
      {
        key: 'synonyms',
        label: '同义词',
        title: '同义词',
    purpose: '帮助大模型把用户的不同叫法、缩写、口语表达匹配到这个指标。',
    instructions: [
      '填写用户真实会说的词，不要求和系统字段一致。',
      '多个词用逗号或换行分隔。',
      '优先补充缩写、行业黑话、历史报表里的旧名称。',
    ],
    examples: ['订单量, 下单数, 成交数', '转化率, 成交率, 完成率'],
    tips: ['同义词太泛会误召回，例如只写“率”会让很多比率指标混在一起。'],
      },
      {
        key: 'default_filters',
        label: '默认过滤',
        title: '默认过滤',
    purpose: '给指标附加固定过滤条件，用户不明确说明时也会自动生效。',
    instructions: [
      '字段填写语义字段键，例如 status。',
      '操作符支持 =、!=、in。',
      '值会自动解析数字、true/false；多个值可用逗号分隔。',
      '只配置业务口径里永远成立的条件，不要放临时筛选。',
    ],
    examples: ['status = 1', "status in paid, shipped"],
    tips: ['默认过滤对所有查询都会生效，配置前要确认它是指标定义的一部分。'],
      },
      {
        key: 'description',
        label: '描述',
        title: '描述',
    purpose: '说明指标业务口径，供配置人员理解，也供模型在歧义场景下选择正确指标。',
    instructions: [
      '写清楚分子、分母、统计范围和排除规则。',
      '必要时说明时间口径，例如按创建时间、支付时间或快照时间统计。',
      '说明业务缩写或内部口径，例如 GMV、ARPU、留存率的含义。',
    ],
    examples: ['支付转化率 = 支付成功订单数 / 创建订单数，统计口径按订单创建时间。'],
    tips: ['描述越清楚，后续自然语言解释和指标治理越省心。'],
      },
    ],
  },
  rule: {
    title: '规则填写说明',
    subtitle: '用于沉淀业务口径、过滤约束、时间默认规则和校验边界，帮助系统解释和约束问数结果。',
    fields: [
      {
        key: 'rule_key',
        label: '标识',
        title: '标识 rule_key',
        purpose: '规则在语义层里的唯一英文键。',
        instructions: ['使用英文 snake_case。', '建议表达规则适用对象和规则含义。'],
        examples: ['order_count_definition', 'status_filter', 'default_created_at'],
      },
      {
        key: 'rule_type',
        label: '规则类型',
        title: '规则类型',
        purpose: '说明规则用于定义口径、过滤、时间还是约束。',
        instructions: ['口径定义：解释指标或维度含义。', '过滤规则：提供固定筛选条件。', '时间规则：定义默认时间口径。', '约束规则：限制不允许的组合。'],
        examples: ['订单数口径选择“口径定义”', '状态识别选择“过滤规则”'],
      },
      {
        key: 'name',
        label: '名称',
        title: '名称',
        purpose: '规则的中文展示名。',
        instructions: ['用短语概括规则。', '避免写成长句，详细内容放到描述。'],
        examples: ['订单数口径', '状态识别'],
      },
      {
        key: 'applies_to',
        label: '适用对象',
        title: '适用对象',
        purpose: '说明这条规则约束或解释哪些指标、维度或字段。',
        instructions: ['填写语义资产键，多个用逗号或换行分隔。', '优先填写指标或维度的英文标识。'],
        examples: ['order_count, product_type'],
      },
      {
        key: 'expression',
        label: '表达式',
        title: '表达式键和值',
        purpose: '用结构化方式记录规则内容，后续可用于校验或编译。',
        instructions: ['表达式键填写规则字段，如 status。', '表达式值填写对应值，多个值用逗号分隔。'],
        examples: ['status = paid, shipped'],
      },
      {
        key: 'severity',
        label: '级别',
        title: '级别',
        purpose: '表示规则触发后的严重程度。',
        instructions: ['提示：只做解释。', '警告：配置或查询可能有风险。', '错误：应该阻止执行。'],
        examples: ['口径解释用“提示”', '不允许的维度组合用“错误”'],
      },
      {
        key: 'description',
        label: '描述',
        title: '描述',
        purpose: '用自然语言完整描述规则。',
        instructions: ['写清楚业务含义。', '必要时说明来源、适用范围和例外。'],
        examples: ['有效订单只包含已支付、已发货、已完成状态，不包含已取消或测试订单。'],
      },
    ],
  },
  mapping: {
    title: '映射填写说明',
    subtitle: '用于把语义资产连接到真实数据库表字段，是语义层能编译 SQL 的落地点。',
    fields: [
      {
        key: 'asset_type',
        label: '资产类型',
        title: '资产类型',
        purpose: '说明被映射的语义资产属于维度、过滤项、指标还是概念。',
        instructions: ['维度：可 group by 或过滤。', '过滤项：主要用于 where 条件。', '指标：映射到表达式或字段。', '概念：映射到业务实体表。'],
        examples: ['product_type 选择“维度”', 'status 选择“过滤项”'],
      },
      {
        key: 'asset_key',
        label: '资产键',
        title: '资产键',
        purpose: '语义层引用的英文键，必须和指标可用维度、规则或概念保持一致。',
        instructions: ['填写语义资产键，不是中文名。', '同一个键应保持唯一业务含义。'],
        examples: ['product_type', 'region', 'channel'],
      },
      {
        key: 'role',
        label: '角色',
        title: '角色',
        purpose: '告诉编译器这个映射在 SQL 中主要扮演什么角色。',
        instructions: ['维度用于分组。', '过滤用于 where。', '时间用于时间过滤。', '度量用于聚合计算。'],
        examples: ['product_type 的角色是“维度”', 'created_at 的角色是“时间”'],
      },
      {
        key: 'table_name',
        label: '表名',
        title: '表名',
        purpose: '映射到哪张真实数据库表。',
        instructions: ['填写已采集 Schema 里的英文表名。', '不要填写中文表名。'],
        examples: ['orders'],
      },
      {
        key: 'column_name',
        label: '字段名',
        title: '字段名',
        purpose: '映射到表里的哪个真实字段。',
        instructions: ['填写字段英文名。', '如果不是单字段映射，可留空并填写表达式。'],
        examples: ['product_type', 'region', 'region'],
      },
      {
        key: 'expression_sql',
        label: '表达式',
        title: '表达式',
        purpose: '当语义资产不是单一字段，而是计算表达式时使用。',
        instructions: ['只填写 SQL 表达式。', '能用字段名解决时优先用字段名。'],
        examples: ["CASE WHEN status = 'paid' THEN '已支付' ELSE '未支付' END"],
      },
      {
        key: 'data_type',
        label: '数据类型',
        title: '数据类型',
        purpose: '记录字段类型，帮助后续展示、过滤和校验。',
        instructions: ['填写数据库字段类型或通用类型。', '不确定时可参考数据源 Schema。'],
        examples: ['varchar', 'int', 'decimal', 'date'],
      },
    ],
  },
  template: {
    title: 'LogicForm 模板填写说明',
    subtitle: '用于定义自然语言意图如何转成结构化槽位，例如指标、维度、过滤、时间范围。',
    fields: [
      {
        key: 'template_key',
        label: '标识',
        title: '标识 template_key',
        purpose: '模板在语义层里的唯一英文键。',
        instructions: ['使用英文 snake_case。', '建议按意图类型命名。'],
        examples: ['metric_query', 'product_type_analysis'],
      },
      {
        key: 'intent_type',
        label: '意图类型',
        title: '意图类型',
        purpose: '说明模板处理哪类用户问题。',
        instructions: ['指标查询：统计分析类问题。', '元数据查询：问表、字段、口径。', '普通问答：不走 SQL 的回答。'],
        examples: ['本月订单数选择“指标查询”'],
      },
      {
        key: 'name',
        label: '名称',
        title: '名称',
        purpose: '模板中文名，方便配置人员识别。',
        instructions: ['用短语描述模板用途。', '不要和标识重复。'],
        examples: ['指标查询', '分类分析'],
      },
      {
        key: 'required_slots',
        label: '必填槽位',
        title: '必填槽位',
        purpose: '没有这些槽位时，LogicForm 不应进入编译。',
        instructions: ['填写槽位英文名。', '多个用逗号或换行分隔。'],
        examples: ['metrics', 'metrics, dimensions'],
      },
      {
        key: 'optional_slots',
        label: '可选槽位',
        title: '可选槽位',
        purpose: '用户可以补充但不是必须的查询信息。',
        instructions: ['填写槽位英文名。', '常见有 dimensions、filters、time_range、sort、limit。'],
        examples: ['dimensions, filters, time_range, sort, limit'],
      },
      {
        key: 'compile_strategy',
        label: '编译策略',
        title: '编译策略',
        purpose: '告诉系统这个模板生成的 LogicForm 应该用哪种编译方式。',
        instructions: ['指标查询通常选择 metric_select。', '元数据查询通常选择 metadata_select。'],
        examples: ['metric_select'],
      },
      {
        key: 'examples',
        label: '示例问法',
        title: '示例问法',
        purpose: '给模型参考典型用户表达，提升意图识别和槽位抽取稳定性。',
        instructions: ['每行一个真实问法。', '覆盖常见指标、维度和时间表达。'],
        examples: ['本月订单数是多少', '按产品类型看近三个月销售额趋势'],
      },
      {
        key: 'description',
        label: '描述',
        title: '描述',
        purpose: '说明模板的适用范围。',
        instructions: ['写清楚这个模板解决什么问题。', '说明不适用的场景也有帮助。'],
        examples: ['查询单个或多个指标，可带维度、过滤、时间窗口和排序。'],
      },
    ],
  },
}

const agentId = ref<number>(Number(localStorage.getItem('wenqu_agent_id')) || 1)
const agents = ref<AgentItem[]>([])
const datasources = ref<DatasourceItem[]>([])
const domains = ref<SemanticDomain[]>([])
const domainId = ref<number | null>(null)
const activeTab = ref('concept')
const assets = ref<Record<string, Record<string, unknown>[]>>({})
const runtimeLoading = ref(false)
const syncLoading = ref(false)
const showDomainDialog = ref(false)
const showAssetDialog = ref(false)
const showAssetGuide = ref(false)
const showAssetDetail = ref(false)
const showSnapshotDrawer = ref(false)
const showSnapshotDiffDialog = ref(false)
const snapshots = ref<Record<string, unknown>[]>([])
const snapshotDiff = ref<Record<string, any> | null>(null)
const domainDialogMode = ref<'create' | 'edit'>('create')
const editingAssetType = ref('concept')
const assetDialogMode = ref<'create' | 'edit'>('create')
const domainForm = ref<SemanticDomainRequest>({
  agent_id: agentId.value,
  datasource_id: null,
  domain_key: '',
  name: '',
  description: '',
  status: 'active',
})
const assetDraft = ref<AssetDraft>({})
const selectedAssetType = ref('concept')
const selectedAsset = ref<Record<string, unknown> | null>(null)

const selectedDomain = computed(() => domains.value.find(domain => domain.id === domainId.value) || null)
const currentAssetTab = computed(() => assetTabs.find(tab => tab.name === editingAssetType.value))
const currentDetailTab = computed(() => assetTabs.find(tab => tab.name === selectedAssetType.value))
const assetPayload = computed(() => buildAssetPayload(editingAssetType.value, assetDraft.value))
const assetJsonPreview = computed(() => JSON.stringify(assetPayload.value, null, 2))
const currentAssetGuide = computed(() => assetGuidePages[editingAssetType.value])
const assetDetailTitle = computed(() => {
  if (!selectedAsset.value) return '语义资产详情'
  return `${currentDetailTab.value?.label || '语义资产'}详情`
})
const detailPrimaryName = computed(() => {
  if (!selectedAsset.value) return ''
  if (selectedAssetType.value === 'mapping') return semanticLabel(String(selectedAsset.value.asset_key || ''))
  return String(selectedAsset.value.name || assetKey(selectedAsset.value, selectedAssetType.value))
})
const selectedAssetJson = computed(() => JSON.stringify(selectedAsset.value || {}, null, 2))
const assetDetailRows = computed(() => {
  if (!selectedAsset.value) return []
  return buildAssetDetailRows(selectedAssetType.value, selectedAsset.value)
})
const snapshotDiffSummary = computed(() => snapshotDiff.value?.summary || {
  added: 0,
  removed: 0,
  changed: 0,
  domain_changed: false,
})
const snapshotDomainChanges = computed(() => Array.isArray(snapshotDiff.value?.domain) ? snapshotDiff.value.domain : [])
const snapshotAssetDiffSections = computed(() => {
  const assets = snapshotDiff.value?.assets || {}
  return assetTabs
    .map(tab => ({
      type: tab.name,
      added: Array.isArray(assets[tab.name]?.added) ? assets[tab.name].added : [],
      removed: Array.isArray(assets[tab.name]?.removed) ? assets[tab.name].removed : [],
      changed: Array.isArray(assets[tab.name]?.changed) ? assets[tab.name].changed : [],
    }))
    .filter(section => section.added.length || section.removed.length || section.changed.length)
})

const assetCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const tab of assetTabs) counts[tab.name] = assets.value[tab.name]?.length || 0
  return counts
})

onMounted(async () => {
  await Promise.all([loadAgents(), loadDatasources()])
  await loadDomains()
})

watch(domainId, async () => {
  await loadAssets()
})

async function loadAgents() {
  try {
    agents.value = await fetchAgents()
    if (agents.value.length > 0 && !agents.value.some(agent => agent.id === agentId.value)) {
      agentId.value = agents.value[0].id
    }
  } catch {
    agents.value = []
    ElMessage.error('智能体配置加载失败')
  }
}

async function loadDatasources() {
  try {
    datasources.value = await fetchAllDatasources()
  } catch {
    datasources.value = []
    ElMessage.error('数据源配置加载失败')
  }
}

async function loadDomains() {
  try {
    const previousDomainId = domainId.value
    domains.value = await fetchAllSemanticDomains()
    const preferredDomainId = previousDomainId && domains.value.some(domain => domain.id === previousDomainId)
      ? previousDomainId
      : domains.value[0]?.id || null
    domainId.value = preferredDomainId
  } catch {
    domains.value = []
    domainId.value = null
    ElMessage.error('语义领域加载失败')
  }
  await loadAssets()
}

async function loadAssets() {
  if (!domainId.value) {
    assets.value = {}
    return
  }
  try {
    assets.value = await fetchSemanticAssets(domainId.value)
  } catch {
    assets.value = {}
    ElMessage.error('语义资产加载失败')
  }
}

async function handleBuildRuntime() {
  if (!selectedDomain.value) return
  runtimeLoading.value = true
  try {
    await buildSemanticRuntime({
      agent_id: selectedDomain.value.agent_id || agentId.value,
      datasource_id: selectedDomain.value.datasource_id || undefined,
      domain_id: selectedDomain.value.id,
      domain_key: selectedDomain.value.domain_key,
    })
    ElMessage.success('语义层构建成功')
  } catch {
    ElMessage.error('语义层构建失败')
  } finally {
    runtimeLoading.value = false
  }
}

async function handleSyncVector() {
  if (!selectedDomain.value) return
  syncLoading.value = true
  try {
    const result = await syncSemanticVector(selectedDomain.value.id)
    ElMessage.success(result.message || '向量同步完成')
  } catch {
    ElMessage.error('向量同步失败')
  } finally {
    syncLoading.value = false
  }
}

function openCreateDomain() {
  domainDialogMode.value = 'create'
  domainForm.value = {
    agent_id: defaultDomainAgentId(),
    datasource_id: datasources.value[0]?.id || null,
    domain_key: '',
    name: '',
    description: '',
    status: 'active',
  }
  showDomainDialog.value = true
}

function openEditDomain() {
  if (!selectedDomain.value) return
  domainDialogMode.value = 'edit'
  domainForm.value = {
    id: selectedDomain.value.id,
    agent_id: selectedDomain.value.agent_id || defaultDomainAgentId(),
    datasource_id: selectedDomain.value.datasource_id || null,
    domain_key: selectedDomain.value.domain_key,
    name: selectedDomain.value.name,
    description: selectedDomain.value.description || '',
    status: selectedDomain.value.status || 'active',
  }
  showDomainDialog.value = true
}

async function handleSaveDomain() {
  const payload: SemanticDomainRequest = {
    ...domainForm.value,
    agent_id: Number(domainForm.value.agent_id || defaultDomainAgentId()),
    datasource_id: domainForm.value.datasource_id ? Number(domainForm.value.datasource_id) : null,
    domain_key: cleanText(domainForm.value.domain_key),
    name: cleanText(domainForm.value.name),
    description: cleanText(domainForm.value.description),
    status: domainForm.value.status || 'active',
  }
  if (!payload.name) {
    ElMessage.warning('请输入语义层名称')
    return
  }
  if (!payload.domain_key) {
    ElMessage.warning('请输入语义层标识')
    return
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(payload.domain_key)) {
    ElMessage.warning('语义层标识只能使用英文、数字和下划线，且不能以数字开头')
    return
  }
  try {
    const result = await upsertSemanticDomain(payload)
    ElMessage.success(result.message || '语义层已保存')
    showDomainDialog.value = false
    await loadDomains()
    if (result.id) domainId.value = Number(result.id)
    await loadAssets()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '语义层保存失败')
  }
}

async function handleDeleteDomain() {
  if (!selectedDomain.value) return
  const domain = selectedDomain.value
  try {
    await ElMessageBox.confirm(
      `确定删除语义层「${domain.name}」？它下面的对象、关系、指标、规则、映射和模板都会被删除，已绑定该语义层的智能体会被清空绑定。`,
      '删除语义层',
      { type: 'warning' },
    )
    await deleteSemanticDomain(domain.id)
    ElMessage.success('语义层已删除')
    domainId.value = null
    await loadDomains()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '语义层删除失败')
  }
}

async function handleCopyDomain() {
  if (!selectedDomain.value) return
  const source = selectedDomain.value
  try {
    const { value } = await ElMessageBox.prompt(
      '请输入新语义层标识，复制后会包含当前语义层的全部资产。',
      '复制语义层',
      {
        inputValue: `${source.domain_key}_copy`,
        inputPattern: /^[A-Za-z_][A-Za-z0-9_]*$/,
        inputErrorMessage: '只能使用英文、数字和下划线，且不能以数字开头',
      },
    )
    const result = await copySemanticDomain(source.id, {
      domain_key: value,
      name: `${source.name} 副本`,
    })
    ElMessage.success(result.message || '语义层已复制')
    await loadDomains()
    if (result.id) domainId.value = Number(result.id)
    await loadAssets()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '复制失败')
  }
}

async function handleExportDomain() {
  if (!selectedDomain.value) return
  try {
    const bundle = await exportSemanticDomain(selectedDomain.value.id)
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${selectedDomain.value.domain_key}.semantic.json`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('语义层已导出')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导出失败')
  }
}

function handleImportDomain() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'application/json,.json'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return
    try {
      const text = await file.text()
      const result = await importSemanticDomain(JSON.parse(text))
      ElMessage.success(result.message || '语义层已导入')
      await loadDomains()
      if (result.id) domainId.value = Number(result.id)
      await loadAssets()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '导入失败')
    }
  }
  input.click()
}

async function handleValidateDomain() {
  if (!selectedDomain.value) return
  try {
    const result = await validateSemanticDomain(selectedDomain.value.id)
    const errors = Array.isArray(result.errors) ? result.errors : []
    const warnings = Array.isArray(result.warnings) ? result.warnings : []
    if (errors.length) {
      await ElMessageBox.alert(errors.join('\n'), '语义层校验未通过', { type: 'error' })
      return
    }
    const message = warnings.length ? warnings.join('\n') : '未发现阻断问题。'
    await ElMessageBox.alert(message, result.valid ? '语义层校验通过' : '语义层校验结果', { type: warnings.length ? 'warning' : 'success' })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '校验失败')
  }
}

async function handleCreateSnapshot() {
  if (!selectedDomain.value) return
  try {
    const { value } = await ElMessageBox.prompt('请输入快照说明，便于之后识别本次配置状态。', '创建语义层快照', {
      inputValue: '配置调整前快照',
    })
    const result = await createSemanticSnapshot(selectedDomain.value.id, {
      name: `${selectedDomain.value.name} 快照`,
      description: value,
    })
    ElMessage.success(result.message || '快照已创建')
    await openSnapshots()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '创建快照失败')
  }
}

async function openSnapshots() {
  if (!selectedDomain.value) return
  try {
    snapshots.value = await fetchSemanticSnapshots(selectedDomain.value.id)
    showSnapshotDrawer.value = true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '快照加载失败')
  }
}

async function handleDiffSnapshot(item: Record<string, unknown>) {
  if (!selectedDomain.value || !item.id) return
  try {
    snapshotDiff.value = await diffSemanticSnapshot(selectedDomain.value.id, Number(item.id))
    showSnapshotDiffDialog.value = true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '快照差异加载失败')
  }
}

async function handleRollbackSnapshot(item: Record<string, unknown>) {
  if (!selectedDomain.value || !item.id) return
  try {
    await ElMessageBox.confirm(
      `确定将语义层「${selectedDomain.value.name}」回滚到快照「${item.name || item.id}」？当前资产会被快照内容覆盖，建议先导出或创建新快照。`,
      '回滚语义层快照',
      { type: 'warning' },
    )
    const result = await rollbackSemanticSnapshot(selectedDomain.value.id, Number(item.id))
    ElMessage.success(result.message || '语义层已回滚')
    await loadDomains()
    if (selectedDomain.value?.id) domainId.value = selectedDomain.value.id
    await loadAssets()
    await openSnapshots()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '快照回滚失败')
  }
}

function formatSnapshotCounts(value: unknown) {
  if (!value || typeof value !== 'object') return '无资产统计'
  const record = value as Record<string, unknown>
  return [
    `对象 ${record.concept ?? 0}`,
    `关系 ${record.relation ?? 0}`,
    `指标 ${record.metric ?? 0}`,
    `映射 ${record.mapping ?? 0}`,
  ].join(' · ')
}

function assetTypeName(type: string) {
  return assetTabs.find(tab => tab.name === type)?.label || type
}

function formatDiffValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function snapshotChangedKeys(items: Record<string, unknown>[]) {
  return items.map(item => String(item.key || '')).filter(Boolean).join('、')
}

function defaultDomainAgentId() {
  return agents.value.find(agent => agent.id === agentId.value)?.id || agents.value[0]?.id || agentId.value || 1
}

function openAssetDialog(assetType: string) {
  editingAssetType.value = assetType
  assetDialogMode.value = 'create'
  assetDraft.value = defaultAssetDraft(assetType)
  showAssetDialog.value = true
}

function openEditAsset(assetType: string, row: Record<string, unknown>) {
  editingAssetType.value = assetType
  assetDialogMode.value = 'edit'
  assetDraft.value = assetRowToDraft(assetType, row)
  showAssetDetail.value = false
  showAssetDialog.value = true
}

function openAssetDetail(assetType: string, row: Record<string, unknown>) {
  selectedAssetType.value = assetType
  selectedAsset.value = row
  showAssetDetail.value = true
}

function openAssetGuide() {
  showAssetGuide.value = true
}

async function handleSaveAsset() {
  if (!domainId.value) return
  try {
    const payload = { ...assetPayload.value }
    if (assetDraft.value.id) payload.id = Number(assetDraft.value.id)
    validateAssetPayload(editingAssetType.value, payload)
    await upsertSemanticAsset(domainId.value, editingAssetType.value, payload)
    ElMessage.success('保存成功')
    showAssetDialog.value = false
    await loadAssets()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  }
}

async function handleDeleteAsset(assetType: string, row: Record<string, unknown>) {
  if (!domainId.value) return
  const assetId = Number(row.id)
  if (!assetId) {
    ElMessage.error('缺少资产 ID，无法删除')
    return
  }
  const label = assetDisplayName(assetType, row)
  try {
    await ElMessageBox.confirm(
      `确定删除「${label}」？删除后需要重新构建语义层并同步向量，线上问数才会完全更新。`,
      '删除语义资产',
      { type: 'warning' },
    )
    await deleteSemanticAsset(domainId.value, assetType, assetId)
    ElMessage.success('删除成功')
    if (selectedAsset.value?.id === assetId && selectedAssetType.value === assetType) {
      showAssetDetail.value = false
      selectedAsset.value = null
    }
    await loadAssets()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  }
}

function defaultAssetDraft(type: string): AssetDraft {
  if (type === 'concept') {
    return { concept_key: '', concept_type: 'object', name: '', description: '', synonyms_text: '' }
  }
  if (type === 'relation') {
    return {
      relation_key: '', relation_type: 'join_path', source_concept: '', target_concept: '',
      name: '', description: '', join_left: '', join_right: '',
    }
  }
  if (type === 'metric') {
    return {
      metric_key: '', name: '', description: '', synonyms_text: '', metric_type: 'measure',
      formula_sql: '', base_table: '', time_field: '', dimensions_text: '',
      default_filter_field: '', default_filter_operator: '=', default_filter_value: '',
    }
  }
  if (type === 'rule') {
    return {
      rule_key: '', rule_type: 'definition', name: '', description: '', applies_to_text: '',
      expression_key: '', expression_value: '', severity: 'info',
    }
  }
  if (type === 'mapping') {
    return {
      asset_type: 'dimension', asset_key: '', table_name: '', column_name: '',
      expression_sql: '', data_type: '', role: 'dimension',
    }
  }
  return {
    template_key: '', intent_type: 'metric_query', name: '', description: '',
    required_slots_text: 'metrics', optional_slots_text: 'dimensions, filters, time_range, sort, limit',
    compile_strategy_type: 'metric_select', examples_text: '',
  }
}

function assetRowToDraft(type: string, row: Record<string, unknown>): AssetDraft {
  const base = { id: row.id }
  if (type === 'concept') {
    return {
      ...base,
      concept_key: row.concept_key || '',
      concept_type: row.concept_type || 'object',
      name: row.name || '',
      description: row.description || '',
      synonyms_text: listToText(row.synonyms),
    }
  }
  if (type === 'relation') {
    const joinPath = Array.isArray(row.join_path) ? row.join_path[0] as Record<string, unknown> | undefined : undefined
    return {
      ...base,
      relation_key: row.relation_key || '',
      relation_type: row.relation_type || 'join_path',
      source_concept: row.source_concept || '',
      target_concept: row.target_concept || '',
      name: row.name || '',
      description: row.description || '',
      join_left: joinPath?.left || '',
      join_right: joinPath?.right || '',
    }
  }
  if (type === 'metric') {
    const defaultFilter = Array.isArray(row.default_filters) ? row.default_filters[0] as Record<string, unknown> | undefined : undefined
    return {
      ...base,
      metric_key: row.metric_key || '',
      name: row.name || '',
      description: row.description || '',
      synonyms_text: listToText(row.synonyms),
      metric_type: row.metric_type || 'measure',
      formula_sql: row.formula_sql || '',
      base_table: row.base_table || '',
      time_field: row.time_field || '',
      dimensions_text: listToText(row.dimensions),
      default_filter_field: defaultFilter?.field || '',
      default_filter_operator: defaultFilter?.operator || '=',
      default_filter_value: formValueToText(defaultFilter?.value),
    }
  }
  if (type === 'rule') {
    const expression = isPlainObject(row.expression) ? row.expression : {}
    const expressionEntry = Object.entries(expression)[0]
    return {
      ...base,
      rule_key: row.rule_key || '',
      rule_type: row.rule_type || 'definition',
      name: row.name || '',
      description: row.description || '',
      applies_to_text: listToText(row.applies_to),
      expression_key: expressionEntry?.[0] || '',
      expression_value: formValueToText(expressionEntry?.[1]),
      severity: row.severity || 'info',
    }
  }
  if (type === 'mapping') {
    return {
      ...base,
      asset_type: row.asset_type || 'dimension',
      asset_key: row.asset_key || '',
      table_name: row.table_name || '',
      column_name: row.column_name || '',
      expression_sql: row.expression_sql || '',
      data_type: row.data_type || '',
      role: row.role || 'dimension',
    }
  }
  const compileStrategy = isPlainObject(row.compile_strategy) ? row.compile_strategy : {}
  return {
    ...base,
    template_key: row.template_key || '',
    intent_type: row.intent_type || 'metric_query',
    name: row.name || '',
    description: row.description || '',
    required_slots_text: listToText(row.required_slots),
    optional_slots_text: listToText(row.optional_slots),
    compile_strategy_type: compileStrategy.type || 'metric_select',
    examples_text: listToText(row.examples),
  }
}

function buildAssetPayload(type: string, draft: AssetDraft): Record<string, unknown> {
  if (type === 'concept') {
    return {
      concept_key: cleanText(draft.concept_key),
      concept_type: draft.concept_type || 'object',
      name: cleanText(draft.name),
      description: cleanText(draft.description),
      synonyms: splitList(draft.synonyms_text),
    }
  }
  if (type === 'relation') {
    return {
      relation_key: cleanText(draft.relation_key),
      relation_type: draft.relation_type || 'join_path',
      source_concept: cleanText(draft.source_concept),
      target_concept: cleanText(draft.target_concept),
      name: cleanText(draft.name),
      description: cleanText(draft.description),
      join_path: draft.join_left && draft.join_right
        ? [{ left: cleanText(draft.join_left), right: cleanText(draft.join_right) }]
        : [],
      conditions: [],
    }
  }
  if (type === 'metric') {
    return {
      metric_key: cleanText(draft.metric_key),
      name: cleanText(draft.name),
      description: cleanText(draft.description),
      synonyms: splitList(draft.synonyms_text),
      metric_type: draft.metric_type || 'measure',
      formula_sql: cleanText(draft.formula_sql),
      base_table: cleanText(draft.base_table),
      time_field: cleanText(draft.time_field) || null,
      default_filters: buildSingleFilter(draft),
      dimensions: splitList(draft.dimensions_text),
    }
  }
  if (type === 'rule') {
    return {
      rule_key: cleanText(draft.rule_key),
      rule_type: draft.rule_type || 'definition',
      name: cleanText(draft.name),
      description: cleanText(draft.description),
      expression: buildExpression(draft),
      applies_to: splitList(draft.applies_to_text),
      severity: draft.severity || 'info',
    }
  }
  if (type === 'mapping') {
    return {
      asset_type: draft.asset_type || 'dimension',
      asset_key: cleanText(draft.asset_key),
      table_name: cleanText(draft.table_name),
      column_name: cleanText(draft.column_name) || null,
      expression_sql: cleanText(draft.expression_sql) || null,
      data_type: cleanText(draft.data_type) || null,
      role: draft.role || 'dimension',
    }
  }
  return {
    template_key: cleanText(draft.template_key),
    intent_type: draft.intent_type || 'metric_query',
    name: cleanText(draft.name),
    description: cleanText(draft.description),
    required_slots: splitList(draft.required_slots_text),
    optional_slots: splitList(draft.optional_slots_text),
    compile_strategy: { type: draft.compile_strategy_type || 'metric_select' },
    examples: splitList(draft.examples_text),
  }
}

function validateAssetPayload(type: string, payload: Record<string, unknown>) {
  const requiredMap: Record<string, string[]> = {
    concept: ['concept_key', 'name'],
    relation: ['relation_key', 'name', 'source_concept', 'target_concept'],
    metric: ['metric_key', 'name', 'formula_sql', 'base_table'],
    rule: ['rule_key', 'name'],
    mapping: ['asset_key', 'table_name'],
    template: ['template_key', 'name'],
  }
  const missing = (requiredMap[type] || []).filter(key => !payload[key])
  if (missing.length) throw new Error(`缺少必填字段: ${missing.join(', ')}`)
}

function cleanText(value: unknown) {
  return String(value ?? '').trim()
}

function splitList(value: unknown): string[] {
  return cleanText(value)
    .split(/[\n,，]/)
    .map(item => item.trim())
    .filter(Boolean)
}

function buildSingleFilter(draft: AssetDraft) {
  if (!cleanText(draft.default_filter_field)) return []
  return [{
    field: cleanText(draft.default_filter_field),
    operator: draft.default_filter_operator || '=',
    value: parseFormValue(draft.default_filter_value),
  }]
}

function buildExpression(draft: AssetDraft) {
  const key = cleanText(draft.expression_key)
  if (!key) return {}
  return { [key]: parseFormValue(draft.expression_value) }
}

function parseFormValue(value: unknown): unknown {
  const text = cleanText(value)
  const values = splitList(text)
  if (values.length > 1) return values.map(parseScalar)
  return parseScalar(text)
}

function parseScalar(value: string): unknown {
  if (value === 'true') return true
  if (value === 'false') return false
  if (value !== '' && !Number.isNaN(Number(value))) return Number(value)
  return value
}

function listToText(value: unknown) {
  return Array.isArray(value) ? value.join(', ') : cleanText(value)
}

function formValueToText(value: unknown) {
  if (Array.isArray(value)) return value.join(', ')
  if (isPlainObject(value)) return JSON.stringify(value, null, 2)
  return cleanText(value)
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function assetKey(row: Record<string, unknown>, type: string) {
  const keyMap: Record<string, string> = {
    concept: 'concept_key',
    relation: 'relation_key',
    metric: 'metric_key',
    rule: 'rule_key',
    mapping: 'asset_key',
    template: 'template_key',
  }
  return String(row[keyMap[type]] || '')
}

function assetDisplayName(type: string, row: Record<string, unknown>) {
  if (type === 'mapping') {
    const key = String(row.asset_key || '')
    return `${semanticLabel(key)} (${key})`
  }
  return String(row.name || assetKey(row, type) || row.id || '语义资产')
}

function assetKind(row: Record<string, unknown>, type: string) {
  if (type === 'concept') return conceptTypeLabel(String(row.concept_type || ''))
  if (type === 'relation') return relationTypeLabel(String(row.relation_type || ''))
  if (type === 'metric') return metricTypeLabel(String(row.metric_type || ''))
  if (type === 'rule') return ruleTypeLabel(String(row.rule_type || ''))
  if (type === 'mapping') return `${assetTypeLabel(String(row.asset_type || ''))}/${roleLabel(String(row.role || ''))}`
  if (type === 'template') return intentTypeLabel(String(row.intent_type || ''))
  return ''
}

const detailFieldOrders: Record<string, string[]> = {
  concept: ['id', 'concept_key', 'concept_type', 'name', 'description', 'synonyms', 'metadata'],
  relation: ['id', 'relation_key', 'relation_type', 'name', 'source_concept', 'target_concept', 'join_path', 'conditions', 'description', 'metadata'],
  metric: ['id', 'metric_key', 'name', 'metric_type', 'base_table', 'time_field', 'formula_sql', 'dimensions', 'synonyms', 'default_filters', 'aggregation', 'description', 'metadata'],
  rule: ['id', 'rule_key', 'rule_type', 'name', 'applies_to', 'expression', 'severity', 'description'],
  mapping: ['id', 'asset_type', 'asset_key', 'role', 'table_name', 'column_name', 'expression_sql', 'data_type', 'filters'],
  template: ['id', 'template_key', 'intent_type', 'name', 'required_slots', 'optional_slots', 'compile_strategy', 'examples', 'description'],
}

const detailFieldLabels: Record<string, string> = {
  id: 'ID',
  concept_key: '概念标识',
  concept_type: '概念类型',
  relation_key: '关系标识',
  relation_type: '关系类型',
  metric_key: '指标标识',
  metric_type: '指标类型',
  rule_key: '规则标识',
  rule_type: '规则类型',
  template_key: '模板标识',
  intent_type: '意图类型',
  name: '名称',
  description: '描述',
  synonyms: '同义词',
  metadata: '扩展信息',
  source_concept: '源概念',
  target_concept: '目标概念',
  join_path: '关联路径',
  conditions: '条件',
  base_table: '基础表',
  time_field: '时间字段',
  formula_sql: '计算公式',
  aggregation: '聚合方式',
  dimensions: '可用维度',
  default_filters: '默认过滤',
  applies_to: '适用对象',
  expression: '表达式',
  severity: '级别',
  asset_type: '资产类型',
  asset_key: '资产键',
  role: '角色',
  table_name: '表名',
  column_name: '字段名',
  expression_sql: 'SQL 表达式',
  data_type: '数据类型',
  filters: '过滤条件',
  required_slots: '必填槽位',
  optional_slots: '可选槽位',
  compile_strategy: '编译策略',
  examples: '示例问法',
}

function buildAssetDetailRows(type: string, row: Record<string, unknown>) {
  const orderedKeys = detailFieldOrders[type] || []
  const extraKeys = Object.keys(row).filter(key => !orderedKeys.includes(key) && key !== 'domain_id')
  return [...orderedKeys, ...extraKeys]
    .filter(key => key in row && key !== 'domain_id')
    .map(key => {
      const formatted = formatAssetDetailValue(key, row[key])
      return {
        key,
        label: detailFieldLabels[key] || key,
        value: formatted.value,
        multiline: formatted.multiline,
      }
    })
}

function formatAssetDetailValue(key: string, value: unknown) {
  if (value === null || value === undefined || value === '') return { value: '-', multiline: false }
  if (key === 'concept_type') return { value: conceptTypeLabel(String(value)), multiline: false }
  if (key === 'relation_type') return { value: relationTypeLabel(String(value)), multiline: false }
  if (key === 'metric_type') return { value: metricTypeLabel(String(value)), multiline: false }
  if (key === 'rule_type') return { value: ruleTypeLabel(String(value)), multiline: false }
  if (key === 'intent_type') return { value: intentTypeLabel(String(value)), multiline: false }
  if (key === 'asset_type') return { value: assetTypeLabel(String(value)), multiline: false }
  if (key === 'role') return { value: roleLabel(String(value)), multiline: false }
  if (key === 'asset_key') {
    const assetKeyValue = String(value)
    return { value: `${semanticLabel(assetKeyValue)} (${assetKeyValue})`, multiline: false }
  }
  if (key === 'table_name') {
    const table = String(value)
    return { value: `${tableNameLabel(table)} (${table})`, multiline: false }
  }
  if (key === 'column_name') {
    const column = String(value)
    return { value: `${columnNameLabel(String(selectedAsset.value?.asset_key || ''), column)} (${column})`, multiline: false }
  }
  if (key === 'dimensions' && Array.isArray(value)) {
    return { value: value.map(item => `${semanticLabel(String(item))} (${String(item)})`).join('、') || '-', multiline: false }
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return { value: '-', multiline: false }
    if (value.every(item => typeof item !== 'object')) return { value: value.map(String).join('、'), multiline: false }
    return { value: JSON.stringify(value, null, 2), multiline: true }
  }
  if (isPlainObject(value)) return { value: JSON.stringify(value, null, 2), multiline: true }
  const text = String(value)
  return { value: text, multiline: text.length > 80 || text.includes('\n') }
}

function semanticLabel(key: string) {
  for (const metric of assets.value.metric || []) {
    if (metric.metric_key === key && metric.name) return String(metric.name)
  }
  for (const mapping of assets.value.mapping || []) {
    if (mapping.asset_key === key) {
      const desc = mapping.description || mapping.column_name || mapping.expression_sql
      if (desc) return String(desc)
    }
  }
  return key
}

function metricTypeLabel(type: string) {
  const map: Record<string, string> = {
    measure: '度量', ratio: '比率', count: '计数', dimension_metric: '维度指标',
  }
  return map[type] || type
}

function conceptTypeLabel(type: string) {
  const map: Record<string, string> = {
    object: '对象', event: '事件', state: '状态',
  }
  return map[type] || type
}

function relationTypeLabel(type: string) {
  const map: Record<string, string> = {
    join_path: '关联路径', event_flow: '事件链路', state_transition: '状态流转',
  }
  return map[type] || type
}

function ruleTypeLabel(type: string) {
  const map: Record<string, string> = {
    definition: '口径定义', filter: '过滤规则', time: '时间规则', constraint: '约束规则',
  }
  return map[type] || type
}

function intentTypeLabel(type: string) {
  const map: Record<string, string> = {
    metric_query: '指标查询', metadata_query: '元数据查询', chat: '普通问答',
  }
  return map[type] || type
}

function roleLabel(role: string) {
  const map: Record<string, string> = {
    dimension: '维度', filter: '过滤', time: '时间', field: '字段', measure: '度量',
  }
  return map[role] || role
}

function assetTypeLabel(type: string) {
  const map: Record<string, string> = {
    dimension: '维度', filter: '过滤项', metric: '指标', concept: '概念',
  }
  return map[type] || type
}

function tableNameLabel(tableName: string) {
  return tableName || '-'
}

function columnNameLabel(assetKey: string, columnName: string) {
  const label = semanticLabel(assetKey)
  return label && label !== assetKey ? label : columnName || '-'
}
</script>

<style scoped>
.page-shell {
  height: calc(100vh - 68px);
  overflow: auto;
  padding: 28px;
  background: var(--wq-bg);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  margin-bottom: 18px;
}

.page-kicker {
  display: block;
  margin-bottom: 7px;
  color: var(--wq-primary);
  font-size: 12px;
  font-weight: 720;
}

.page-header h2 {
  font-size: 22px;
  line-height: 1.25;
  color: var(--wq-text);
}

.page-header p {
  margin-top: 8px;
  color: var(--wq-muted);
  font-size: 14px;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.runtime-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(120px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.summary-item {
  min-width: 0;
  background: #fff;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  padding: 14px;
}

.summary-item span {
  display: block;
  color: var(--wq-subtle);
  font-size: 12px;
  margin-bottom: 7px;
}

.summary-item strong {
  display: block;
  min-width: 0;
  color: var(--wq-text);
  font-size: 18px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.knowledge-surface {
  background: #fff;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: var(--wq-shadow);
}

.knowledge-surface :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 22px;
  background: #fff;
}

.knowledge-surface :deep(.el-tabs__content) {
  padding: 20px 22px 22px;
}

.tab-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
}

.tab-header h3 {
  font-size: 16px;
  color: var(--wq-text);
}

.tab-header p {
  margin-top: 5px;
  color: var(--wq-subtle);
  font-size: 13px;
}

.dim-chips {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}

.field-zh {
  display: block;
  margin-top: 3px;
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1.3;
}

.mapping-primary {
  color: var(--wq-text);
  font-weight: 660;
  line-height: 1.4;
}

.inline-code {
  color: #667085;
  background: #f3f6fb;
  border: 1px solid var(--wq-border);
  border-radius: 5px;
  padding: 2px 5px;
  font-size: 12px;
  font-family: "SFMono-Regular", Consolas, monospace;
  white-space: nowrap;
}

.asset-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.asset-table {
  min-width: 760px;
}

.asset-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.domain-form-note {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid #dbeafe;
  border-radius: 6px;
  background: #f8fbff;
  color: #52637a;
  font-size: 13px;
  line-height: 1.6;
}

:global(.domain-dialog .el-select) {
  width: 100%;
}

:global(.asset-dialog) {
  max-width: calc(100vw - 32px);
}

.asset-dialog-header {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.asset-dialog-header h3 {
  margin: 0;
  color: var(--wq-text);
  font-size: 20px;
  font-weight: 780;
  line-height: 1.35;
}

.asset-guide-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 1px solid #cbd5e1;
  border-radius: 50%;
  padding: 0;
  color: #64748b;
  background: #fff;
  cursor: pointer;
  transition: all 0.16s ease;
}

.asset-guide-button:hover {
  border-color: var(--wq-primary);
  color: var(--wq-primary);
  background: #f8fbff;
}

.asset-guide-button .el-icon {
  font-size: 15px;
}

.asset-editor {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 390px;
  gap: 16px;
  min-height: 520px;
}

.asset-form-panel,
.json-preview-panel {
  min-width: 0;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
}

.asset-form-panel {
  max-height: 62vh;
  overflow: auto;
  padding: 18px 18px 4px;
  background: #fff;
}

.asset-form-panel :deep(.el-form-item) {
  margin-bottom: 14px;
}

.asset-form-panel :deep(.el-form-item__label) {
  color: var(--wq-muted);
  font-weight: 640;
}

.asset-form-panel :deep(.el-select) {
  width: 100%;
}

.asset-form-panel :deep(.el-textarea__inner) {
  font-family: inherit;
}

.json-preview-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #111827;
}

.preview-title {
  padding: 12px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  color: #e5e7eb;
  font-size: 13px;
  font-weight: 700;
}

.json-preview-panel pre {
  flex: 1;
  margin: 0;
  overflow: auto;
  padding: 14px;
  color: #d1d5db;
  font-size: 12px;
  line-height: 1.65;
  font-family: "SFMono-Regular", Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-word;
}

.inline-fields {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 1fr) 104px minmax(0, 1fr);
  gap: 8px;
}

.operator-select {
  width: 104px;
}

:global(.asset-detail-drawer .el-drawer__header),
:global(.asset-guide-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--wq-border);
  color: var(--wq-text);
  font-weight: 760;
}

.asset-detail {
  padding: 2px 2px 20px;
  color: #344054;
}

.detail-identity {
  display: grid;
  gap: 6px;
  margin-bottom: 18px;
  padding: 14px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #f8fafc;
}

.detail-identity span {
  color: var(--wq-subtle);
  font-size: 12px;
}

.detail-identity strong {
  color: var(--wq-text);
  font-size: 18px;
  line-height: 1.35;
}

.detail-identity code {
  width: fit-content;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #667085;
  background: #fff;
  border: 1px solid var(--wq-border);
  border-radius: 5px;
  padding: 3px 7px;
  font-size: 12px;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.detail-section {
  margin-top: 18px;
}

.detail-section h4 {
  margin: 0 0 10px;
  color: var(--wq-text);
  font-size: 14px;
  font-weight: 760;
}

.detail-grid {
  margin: 0;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  overflow: hidden;
}

.detail-grid dt,
.detail-grid dd {
  margin: 0;
  padding: 11px 12px;
  border-bottom: 1px solid var(--wq-border);
  font-size: 13px;
  line-height: 1.65;
}

.detail-grid dt {
  float: left;
  clear: left;
  width: 128px;
  min-height: 46px;
  color: var(--wq-muted);
  background: #f8fafc;
  font-weight: 700;
}

.detail-grid dd {
  min-height: 46px;
  margin-left: 128px;
  color: var(--wq-text);
  word-break: break-word;
}

.detail-grid dd:last-child,
.detail-grid dt:has(+ dd:last-child) {
  border-bottom: 0;
}

.detail-grid pre,
.detail-json {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #263448;
  font-size: 12px;
  line-height: 1.7;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.detail-json {
  max-height: 360px;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #111827;
  color: #d1d5db;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.asset-guide {
  padding: 2px 2px 20px;
  color: #344054;
}

.asset-guide-subtitle {
  margin: 0 0 4px;
  color: #475467;
  font-size: 13px;
  line-height: 1.75;
}

.asset-guide-section {
  padding: 16px 0;
  border-bottom: 1px solid #eef2f7;
}

.asset-guide-section:first-of-type {
  padding-top: 0;
}

.asset-guide-section:last-child {
  border-bottom: 0;
}

.asset-guide-field-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.asset-guide-field-title h4 {
  margin: 0;
  color: var(--wq-text);
  font-size: 14px;
  font-weight: 760;
}

.asset-guide-field-title code {
  color: #667085;
  background: #f3f6fb;
  border: 1px solid var(--wq-border);
  border-radius: 5px;
  padding: 2px 6px;
  font-size: 12px;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.asset-guide p {
  margin: 0;
  color: #475467;
  font-size: 13px;
  line-height: 1.75;
}

.asset-guide-block {
  margin-top: 12px;
}

.asset-guide-block strong {
  display: block;
  margin-bottom: 6px;
  color: var(--wq-text);
  font-size: 12px;
  font-weight: 760;
}

.asset-guide ul {
  margin: 0;
  padding-left: 18px;
  color: #475467;
  font-size: 13px;
  line-height: 1.8;
}

.guide-example {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid #dbe4f0;
  border-radius: 6px;
  background: #f8fafc;
  color: #263448;
  font-size: 12px;
  line-height: 1.65;
  font-family: "SFMono-Regular", Consolas, monospace;
  word-break: break-word;
}

.snapshot-list {
  display: grid;
  gap: 12px;
}

.snapshot-card {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fff;
}

.snapshot-card strong {
  color: var(--wq-text);
  font-size: 14px;
}

.snapshot-card p {
  margin: 6px 0 0;
  color: var(--wq-muted);
  font-size: 13px;
  line-height: 1.6;
}

.snapshot-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--wq-subtle);
  font-size: 12px;
}

.snapshot-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.snapshot-diff {
  display: grid;
  gap: 16px;
}

.snapshot-diff-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.snapshot-diff-summary > div {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #f8fbff;
}

.snapshot-diff-summary span,
.snapshot-diff-summary strong {
  display: block;
}

.snapshot-diff-summary span {
  color: var(--wq-subtle);
  font-size: 12px;
}

.snapshot-diff-summary strong {
  margin-top: 5px;
  color: var(--wq-text);
  font-size: 18px;
}

.snapshot-diff-section {
  padding: 12px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fff;
}

.snapshot-diff-section h4 {
  margin: 0 0 8px;
  color: var(--wq-text);
  font-size: 14px;
  font-weight: 760;
}

.snapshot-diff-section p,
.snapshot-key-list {
  margin: 6px 0 0;
  color: #475467;
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.snapshot-change-row {
  padding: 10px 0;
  border-top: 1px solid var(--wq-border);
}

.snapshot-change-row:first-of-type {
  border-top: 0;
}

.snapshot-change-row span {
  display: block;
  color: var(--wq-text);
  font-size: 13px;
  font-weight: 700;
}

@media (max-width: 1100px) {
  .page-header {
    align-items: stretch;
    flex-direction: column;
  }

  .header-actions {
    justify-content: flex-start;
  }

  .runtime-summary {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}

@media (max-width: 900px) {
  :global(.asset-dialog) {
    width: calc(100vw - 20px) !important;
  }

  .asset-editor {
    grid-template-columns: 1fr;
    min-height: 0;
  }

  .asset-form-panel,
  .json-preview-panel {
    max-height: none;
  }

  .json-preview-panel pre {
    max-height: 260px;
  }

  .inline-fields {
    grid-template-columns: 1fr;
  }

  .operator-select {
    width: 100%;
  }
}
</style>
