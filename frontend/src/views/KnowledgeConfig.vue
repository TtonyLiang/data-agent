<template>
  <div class="page-shell">
    <div class="page-header">
      <div>
        <h2>语义与数据口径</h2>
        <p>沉淀可供 Agent 复用的业务口径，并将其绑定到真实数据；业务关系统一引用企业本体。</p>
      </div>
      <div class="header-actions">
        <div class="toolbar-row">
          <div class="toolbar-group toolbar-group-primary">
            <el-button :loading="runtimeLoading" :disabled="!currentDomain" @click="handleBuildRuntime">
              构建查询运行时
            </el-button>
            <el-button type="primary" :loading="syncLoading" :disabled="!currentDomain" @click="handleSyncVector">
              更新验证检索索引
            </el-button>
            <el-dropdown @command="handleToolbarCommand">
              <el-button>
                更多
                <el-icon class="toolbar-caret"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="validate" :disabled="!currentDomain">保存前校验</el-dropdown-item>
                  <el-dropdown-item command="snapshot" :disabled="!currentDomain">创建快照</el-dropdown-item>
                  <el-dropdown-item command="snapshots" :disabled="!currentDomain">查看快照</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </div>
    </div>

    <div class="runtime-summary">
      <div class="summary-item">
        <span>当前业务领域</span>
        <strong>{{ currentDomain?.name || '暂无' }}</strong>
      </div>
      <div class="summary-item">
        <span>对象/事件/状态</span>
        <strong>{{ assetCounts.concept }}</strong>
      </div>
      <div class="summary-item">
        <span>关系查询路径</span>
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
      <el-empty v-if="!domainId || !currentDomain" description="请先选择业务领域" />
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
            <el-button type="primary" size="small" @click="openAssetDialog(tab.name)">
              {{ tab.name === 'relation' ? '配置查询路径' : '添加资产' }}
            </el-button>
          </div>

          <div class="asset-table-wrap">
            <el-table
              :data="assets[tab.name] || []"
              border
              stripe
              size="small"
              class="asset-table"
            >
              <el-table-column v-if="tab.name !== 'mapping'" :label="tab.name === 'relation' ? '本体关系标识' : '标识'" min-width="170">
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
                  <el-option label="动作词汇（不可执行）" value="action" />
                </el-select>
              </el-form-item>
              <div v-if="assetDraft.concept_type === 'action'" class="asset-boundary-note" role="note">
                <strong>这里只维护动作词汇，不提供执行能力</strong>
                <span>它用于帮助 Agent 理解“审批、驳回、分配”等业务表达。带权限、前置条件和状态效果的可执行业务动作，请在“业务本体与动作”中维护。</span>
              </div>
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
              <div class="asset-boundary-note" role="note">
                <strong>引用本体关系，不重复定义业务关系</strong>
                <span>业务关系只在“业务本体与动作”中维护一份。这里选择已有的本体关系，并为查询运行时补充物理 JOIN 绑定。</span>
              </div>
              <section class="asset-form-section" aria-labelledby="relation-reference-title">
                <div class="asset-form-section-heading">
                  <div>
                    <strong id="relation-reference-title">业务语义引用</strong>
                    <span>业务人员确认要用于查询的关系，名称、方向和业务定义来自企业本体。</span>
                  </div>
                  <el-tag size="small" effect="plain">业务口径</el-tag>
                </div>
                <el-form-item label="已有本体业务关系" required>
                  <el-select
                    v-model="assetDraft.relation_key"
                    filterable
                    placeholder="选择已定义的业务关系"
                    no-data-text="当前领域尚未定义业务关系"
                    @change="handleOntologyLinkSelect"
                  >
                    <el-option
                      v-if="hasLegacyRelationReference"
                      :label="`历史关系（待补齐本体） ${assetDraft.relation_key}`"
                      :value="assetDraft.relation_key"
                      disabled
                    />
                    <el-option
                      v-for="item in ontologyLinkTypes"
                      :key="item.id"
                      :label="`${item.name} (${item.link_key})`"
                      :value="item.link_key"
                    />
                  </el-select>
                  <span class="form-help">找不到所需关系时，请先到“业务本体与动作”创建业务关系，再回到这里配置查询路径。</span>
                </el-form-item>
                <div v-if="assetDraft.relation_key" class="relation-reference-summary">
                  <div class="relation-reference-title">
                    <strong>{{ relationReferenceName }}</strong>
                    <el-tag v-if="selectedOntologyLink" size="small" type="success" effect="plain">已引用本体</el-tag>
                    <el-tag v-else size="small" type="warning" effect="plain">旧数据待关联</el-tag>
                  </div>
                  <code>{{ assetDraft.relation_key }}</code>
                  <span>{{ relationReferenceDirection }}</span>
                  <p>{{ relationReferenceDescription }}</p>
                </div>
              </section>
              <details class="advanced-asset-settings">
                <summary>物理 JOIN 绑定（管理员 / 数据工程师高级配置）</summary>
                <div class="advanced-asset-note">
                  这里只说明该业务关系在数据库中如何连接，不改变关系本身的业务含义。字段格式建议为“表名.字段名”。
                </div>
                <el-form-item label="左侧物理字段">
                  <el-input v-model="assetDraft.join_left" placeholder="如 orders.customer_id" />
                </el-form-item>
                <el-form-item label="右侧物理字段">
                  <el-input v-model="assetDraft.join_right" placeholder="如 customers.customer_id" />
                </el-form-item>
              </details>
            </template>

            <template v-else-if="editingAssetType === 'metric'">
              <div class="asset-boundary-note" role="note">
                <strong>先确认业务口径，再绑定物理数据</strong>
                <span>业务人员负责确认指标名称、含义和适用维度；管理员或数据工程师负责表、字段和 SQL 公式。</span>
              </div>
              <section class="asset-form-section" aria-labelledby="metric-business-title">
                <div class="asset-form-section-heading">
                  <div>
                    <strong id="metric-business-title">指标业务口径</strong>
                    <span>这些定义会直接影响 Agent 对用户问题的理解和口径选择。</span>
                  </div>
                  <el-tag size="small" effect="plain">业务人员确认</el-tag>
                </div>
                <el-form-item label="指标标识">
                  <el-input v-model="assetDraft.metric_key" placeholder="如 order_count" />
                </el-form-item>
                <el-form-item label="指标名称">
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
                <el-form-item label="业务口径说明">
                  <el-input v-model="assetDraft.description" type="textarea" :rows="3" placeholder="说明统计范围、排除项和时间口径" />
                </el-form-item>
                <el-form-item label="同义词">
                  <el-input v-model="assetDraft.synonyms_text" placeholder="多个词用逗号或换行分隔" />
                </el-form-item>
                <el-form-item label="可用维度">
                  <el-input v-model="assetDraft.dimensions_text" placeholder="如 product_type, region, channel" />
                </el-form-item>
                <el-form-item label="默认过滤">
                  <div class="inline-fields">
                    <el-input v-model="assetDraft.default_filter_field" placeholder="语义字段" />
                    <el-select v-model="assetDraft.default_filter_operator" class="operator-select">
                      <el-option label="=" value="=" />
                      <el-option label="!=" value="!=" />
                      <el-option label="in" value="in" />
                    </el-select>
                    <el-input v-model="assetDraft.default_filter_value" placeholder="值" />
                  </div>
                </el-form-item>
              </section>
              <details class="advanced-asset-settings">
                <summary>物理数据绑定（管理员 / 数据工程师高级配置）</summary>
                <div class="advanced-asset-note">以下配置决定查询运行时如何从数据库计算该指标，不应由业务人员自行修改。</div>
                <el-form-item label="基础物理表" required>
                  <el-input v-model="assetDraft.base_table" placeholder="如 orders" />
                </el-form-item>
                <el-form-item label="物理时间字段">
                  <el-input v-model="assetDraft.time_field" placeholder="如 orders.created_at" />
                </el-form-item>
                <el-form-item label="SQL 计算公式" required>
                  <el-input v-model="assetDraft.formula_sql" type="textarea" :rows="3" placeholder="支持 {base} 表别名占位" />
                </el-form-item>
              </details>
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
              <div class="asset-boundary-note" role="note">
                <strong>映射只负责技术落地，不重新定义业务含义</strong>
                <span>业务人员先在对象、指标和规则中确认口径；本页由管理员或数据工程师把语义资产绑定到真实表字段。</span>
              </div>
              <section class="asset-form-section" aria-labelledby="mapping-semantic-title">
                <div class="asset-form-section-heading">
                  <div>
                    <strong id="mapping-semantic-title">业务语义引用</strong>
                    <span>选择要落到数据库的语义资产及其查询角色。</span>
                  </div>
                  <el-tag size="small" effect="plain">引用既有口径</el-tag>
                </div>
                <el-form-item label="资产类型">
                  <el-select v-model="assetDraft.asset_type">
                    <el-option label="维度" value="dimension" />
                    <el-option label="过滤项" value="filter" />
                    <el-option label="指标" value="metric" />
                    <el-option label="概念" value="concept" />
                  </el-select>
                </el-form-item>
                <el-form-item label="语义资产键">
                  <el-input v-model="assetDraft.asset_key" placeholder="如 product_type" />
                </el-form-item>
                <el-form-item label="查询角色">
                  <el-select v-model="assetDraft.role">
                    <el-option label="维度" value="dimension" />
                    <el-option label="过滤" value="filter" />
                    <el-option label="时间" value="time" />
                    <el-option label="字段" value="field" />
                    <el-option label="度量" value="measure" />
                  </el-select>
                </el-form-item>
              </section>
              <details class="advanced-asset-settings">
                <summary>物理数据绑定（管理员 / 数据工程师高级配置）</summary>
                <div class="advanced-asset-note">表名、字段名和 SQL 表达式属于技术实现。数据库结构变化时，只调整这里，不改变上层业务语义。</div>
                <el-form-item label="物理表名" required>
                  <el-input v-model="assetDraft.table_name" placeholder="如 orders" />
                </el-form-item>
                <el-form-item label="物理字段名">
                  <el-input v-model="assetDraft.column_name" placeholder="如 product_type" />
                </el-form-item>
                <el-form-item label="SQL 表达式">
                  <el-input v-model="assetDraft.expression_sql" placeholder="可选，字段映射为空时使用" />
                </el-form-item>
                <el-form-item label="数据类型">
                  <el-input v-model="assetDraft.data_type" placeholder="如 varchar / int / decimal" />
                </el-form-item>
              </details>
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
      title="领域语义快照"
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
            <small>{{ formatDateTime(item.created_at) }}</small>
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
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, QuestionFilled } from '@element-plus/icons-vue'
import {
  buildSemanticRuntime,
  createSemanticSnapshot,
  deleteSemanticAsset,
  diffSemanticSnapshot,
  fetchOntologyLinkTypes,
  fetchSemanticAssets,
  fetchSemanticSnapshots,
  rollbackSemanticSnapshot,
  syncSemanticVector,
  upsertSemanticAsset,
  validateSemanticDomain,
  type OntologyLinkType,
  type SemanticDomain,
} from '../api'
import { formatDateTime } from '../utils/datetime'

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

const props = defineProps<{
  domainId: number | null
  currentDomain: SemanticDomain | null
}>()

const emit = defineEmits<{
  (event: 'domain-updated'): void
}>()

const assetTabs = [
  { name: 'concept', label: '对象/事件/状态', description: '业务对象、业务事件、状态、维度和不可执行的动作词汇。' },
  { name: 'relation', label: '关系查询路径', description: '引用本体中已有业务关系，为跨对象查询补充物理 JOIN 绑定。' },
  { name: 'metric', label: '指标', description: '先定义业务口径，再由管理员或数据工程师绑定表、字段和 SQL 公式。' },
  { name: 'rule', label: '规则', description: '过滤规则、时间规则、权限边界和动作约束。' },
  { name: 'mapping', label: '数据映射', description: '管理员或数据工程师将既有语义资产绑定到物理表字段或受控 SQL 表达式。' },
  { name: 'template', label: 'LogicForm 模板', description: '自然语言意图到结构化槽位的模板。' },
]

const assetGuidePages: Record<string, AssetGuidePage> = {
  concept: {
    title: '对象/事件/状态填写说明',
    subtitle: '用于定义业务世界里的对象、事件、状态、维度和词汇。动作词汇只帮助 Agent 理解表达，不代表可执行能力。',
    fields: [
      {
        key: 'concept_key',
        label: '标识',
        title: '标识 concept_key',
        purpose: '概念在企业模型语义中的唯一英文键，关系、规则和检索都会引用它。',
        instructions: ['使用稳定的英文 PascalCase 或 snake_case。', '对象建议用名词，事件建议用动词过去式或业务动作，状态建议用状态名。', '保存后不要随意改名，避免关系和规则引用失效。'],
        examples: ['Order', 'RepaymentPaid', 'OverdueBucket'],
      },
      {
        key: 'concept_type',
        label: '类型',
        title: '类型 concept_type',
        purpose: '告诉系统这个概念是对象、事件、状态、维度还是不可执行的动作词汇。',
        instructions: ['对象：业务实体，如订单、客户。', '事件：已经发生的业务事实，如支付完成。', '状态：某个对象所处阶段，如审批状态。', '动作词汇：帮助 Agent 识别“审批、驳回”等表达，不包含权限、前置条件和执行效果。'],
        examples: ['Order 选择“对象”', 'OrderPaid 选择“事件”', 'OrderStatus 选择“状态”', 'Approve 选择“动作词汇（不可执行）”'],
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
    title: '关系查询路径填写说明',
    subtitle: '这里不创建第二份业务关系。先引用企业本体中已有的 link_key，再由管理员或数据工程师补充查询所需的物理 JOIN。',
    fields: [
      {
        key: 'relation_key',
        label: '已有本体业务关系',
        title: '本体关系 link_key',
        purpose: '引用“业务本体与动作”中已维护的业务关系，确保业务含义只有一个权威来源。',
        instructions: ['从下拉列表选择已有关系。', '关系名称、起点对象、终点对象和业务定义会从企业本体带入。', '找不到所需关系时，先回到企业本体创建，不要在查询语义中另建一份。'],
        examples: ['选择“客户提交贷款申请 (customer_submits_application)”'],
      },
      {
        key: 'join_path',
        label: '物理 JOIN 绑定',
        title: '物理 JOIN 绑定',
        purpose: '告诉查询编译器，这条既有业务关系在真实数据库中如何连接。',
        instructions: ['由管理员或数据工程师填写。', '左右字段建议使用“表名.字段名”。', '字段必须存在于已采集 Schema。', '数据库结构变化时只调整绑定，不改变本体关系。'],
        examples: ['orders.customer_id = customers.customer_id'],
      },
    ],
  },
  metric: {
    title: '指标填写说明',
    subtitle: '业务人员先确认指标名称、含义、维度和过滤口径；管理员或数据工程师再配置物理表、时间字段和 SQL 公式。',
    fields: [
      {
        key: 'metric_key',
        label: '标识',
        title: '标识 metric_key',
    purpose: '这是指标在企业模型语义中的唯一英文键，会出现在 LogicForm、语义校验、SQL 别名和结果字段中。',
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
    purpose: '用于声明该指标的计算形态，影响业务理解、校验和后续展示。',
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
    purpose: '用户问“本月、近三个月、按天/按月”时，查询运行时默认用这个字段做时间过滤或分组。',
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
        purpose: '规则在企业模型语义中的唯一英文键。',
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
    subtitle: '映射是管理员或数据工程师维护的技术绑定。它引用已有业务口径，把语义资产连接到真实数据库表字段。',
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
        purpose: '企业模型语义引用的英文键，必须和指标可用维度、规则或概念保持一致。',
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
        purpose: '管理员或数据工程师指定映射到哪张真实数据库表。',
        instructions: ['这是高级技术配置。', '填写已采集 Schema 里的英文表名。', '不要填写中文表名。'],
        examples: ['orders'],
      },
      {
        key: 'column_name',
        label: '字段名',
        title: '字段名',
        purpose: '管理员或数据工程师指定映射到表里的哪个真实字段。',
        instructions: ['这是高级技术配置。', '填写字段英文名。', '如果不是单字段映射，可留空并填写表达式。'],
        examples: ['product_type', 'region', 'region'],
      },
      {
        key: 'expression_sql',
        label: '表达式',
        title: '表达式',
        purpose: '当语义资产不是单一字段时，由管理员或数据工程师配置 SQL 表达式。',
        instructions: ['这是高级技术配置。', '只填写 SQL 表达式。', '能用字段名解决时优先用字段名。'],
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
        purpose: '模板在企业模型语义中的唯一英文键。',
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

const activeTab = ref('concept')
const assets = ref<Record<string, Record<string, unknown>[]>>({})
const runtimeLoading = ref(false)
const syncLoading = ref(false)
const showAssetDialog = ref(false)
const showAssetGuide = ref(false)
const showAssetDetail = ref(false)
const showSnapshotDrawer = ref(false)
const showSnapshotDiffDialog = ref(false)
const snapshots = ref<Record<string, unknown>[]>([])
const ontologyLinkTypes = ref<OntologyLinkType[]>([])
const snapshotDiff = ref<Record<string, any> | null>(null)
const editingAssetType = ref('concept')
const assetDialogMode = ref<'create' | 'edit'>('create')
const assetDraft = ref<AssetDraft>({})
const selectedAssetType = ref('concept')
const selectedAsset = ref<Record<string, unknown> | null>(null)

const currentAssetTab = computed(() => assetTabs.find(tab => tab.name === editingAssetType.value))
const currentDetailTab = computed(() => assetTabs.find(tab => tab.name === selectedAssetType.value))
const assetPayload = computed(() => buildAssetPayload(editingAssetType.value, assetDraft.value))
const assetJsonPreview = computed(() => JSON.stringify(assetPayload.value, null, 2))
const currentAssetGuide = computed(() => assetGuidePages[editingAssetType.value])
const selectedOntologyLink = computed(() => ontologyLinkTypes.value.find(item => item.link_key === assetDraft.value.relation_key))
const hasLegacyRelationReference = computed(() => Boolean(
  editingAssetType.value === 'relation'
  && assetDraft.value.relation_key
  && !selectedOntologyLink.value,
))
const relationReferenceName = computed(() => selectedOntologyLink.value?.name || cleanText(assetDraft.value.name) || '未命名关系')
const relationReferenceDirection = computed(() => {
  const source = selectedOntologyLink.value?.source_object_key || cleanText(assetDraft.value.source_concept)
  const target = selectedOntologyLink.value?.target_object_key || cleanText(assetDraft.value.target_concept)
  return source && target ? `${source} → ${target}` : '关系方向待补齐'
})
const relationReferenceDescription = computed(() => (
  selectedOntologyLink.value?.description
  || cleanText(assetDraft.value.description)
  || '企业本体中暂未填写业务定义。'
))
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

watch(() => props.domainId, async () => {
  await Promise.all([loadAssets(), loadOntologyRelationOptions()])
}, { immediate: true })

async function loadAssets() {
  if (!props.domainId) {
    assets.value = {}
    return
  }
  const requestedDomainId = props.domainId
  try {
    const nextAssets = await fetchSemanticAssets(requestedDomainId)
    if (props.domainId !== requestedDomainId) return
    assets.value = nextAssets
  } catch {
    if (props.domainId !== requestedDomainId) return
    assets.value = {}
    ElMessage.error('语义资产加载失败')
  }
}

async function loadOntologyRelationOptions() {
  if (!props.domainId) {
    ontologyLinkTypes.value = []
    return
  }
  const requestedDomainId = props.domainId
  try {
    const nextLinkTypes = await fetchOntologyLinkTypes(requestedDomainId)
    if (props.domainId !== requestedDomainId) return
    ontologyLinkTypes.value = nextLinkTypes
  } catch {
    if (props.domainId !== requestedDomainId) return
    ontologyLinkTypes.value = []
  }
}

async function handleBuildRuntime() {
  if (!props.currentDomain) return
  runtimeLoading.value = true
  try {
    await buildSemanticRuntime({
      agent_id: props.currentDomain.agent_id || undefined,
      datasource_id: props.currentDomain.datasource_id || undefined,
      domain_id: props.currentDomain.id,
      domain_key: props.currentDomain.domain_key,
    })
    ElMessage.success('查询运行时构建成功')
  } catch {
    ElMessage.error('查询运行时构建失败')
  } finally {
    runtimeLoading.value = false
  }
}

async function handleSyncVector() {
  if (!props.currentDomain) return
  syncLoading.value = true
  try {
    const result = await syncSemanticVector(props.currentDomain.id)
    ElMessage.success(result.message || '向量同步完成')
  } catch {
    ElMessage.error('向量同步失败')
  } finally {
    syncLoading.value = false
  }
}

function handleToolbarCommand(command: string) {
  if (command === 'validate') {
    handleValidateDomain()
  } else if (command === 'snapshot') {
    handleCreateSnapshot()
  } else if (command === 'snapshots') {
    openSnapshots()
  }
}

async function handleValidateDomain() {
  if (!props.currentDomain) return
  try {
    const result = await validateSemanticDomain(props.currentDomain.id)
    const errors = Array.isArray(result.errors) ? result.errors : []
    const warnings = Array.isArray(result.warnings) ? result.warnings : []
    if (errors.length) {
      await ElMessageBox.alert(errors.join('\n'), '企业模型语义校验未通过', { type: 'error' })
      return
    }
    const message = warnings.length ? warnings.join('\n') : '未发现阻断问题。'
    await ElMessageBox.alert(message, result.valid ? '企业模型语义校验通过' : '企业模型语义校验结果', { type: warnings.length ? 'warning' : 'success' })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '校验失败')
  }
}

async function handleCreateSnapshot() {
  if (!props.currentDomain) return
  try {
    const { value } = await ElMessageBox.prompt('请输入快照说明，便于之后识别本次配置状态。', '创建语义资产快照', {
      inputValue: '配置调整前快照',
    })
    const result = await createSemanticSnapshot(props.currentDomain.id, {
      name: `${props.currentDomain.name} 快照`,
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
  if (!props.currentDomain) return
  try {
    snapshots.value = await fetchSemanticSnapshots(props.currentDomain.id)
    showSnapshotDrawer.value = true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '快照加载失败')
  }
}

async function handleDiffSnapshot(item: Record<string, unknown>) {
  if (!props.currentDomain || !item.id) return
  try {
    snapshotDiff.value = await diffSemanticSnapshot(props.currentDomain.id, Number(item.id))
    showSnapshotDiffDialog.value = true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '快照差异加载失败')
  }
}

async function handleRollbackSnapshot(item: Record<string, unknown>) {
  if (!props.currentDomain || !item.id) return
  try {
    await ElMessageBox.confirm(
      `确定将业务领域「${props.currentDomain.name}」的语义资产回滚到快照「${item.name || item.id}」？当前资产会被快照内容覆盖，建议先创建新快照。`,
      '回滚语义资产快照',
      { type: 'warning' },
    )
    const result = await rollbackSemanticSnapshot(props.currentDomain.id, Number(item.id))
    ElMessage.success(result.message || '语义资产已回滚')
    await loadAssets()
    emit('domain-updated')
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

function openAssetDialog(assetType: string) {
  editingAssetType.value = assetType
  assetDialogMode.value = 'create'
  assetDraft.value = defaultAssetDraft(assetType)
  showAssetDialog.value = true
  if (assetType === 'relation') void loadOntologyRelationOptions()
}

function openEditAsset(assetType: string, row: Record<string, unknown>) {
  editingAssetType.value = assetType
  assetDialogMode.value = 'edit'
  assetDraft.value = assetRowToDraft(assetType, row)
  showAssetDetail.value = false
  showAssetDialog.value = true
  if (assetType === 'relation') void loadOntologyRelationOptions()
}

function openAssetDetail(assetType: string, row: Record<string, unknown>) {
  selectedAssetType.value = assetType
  selectedAsset.value = row
  showAssetDetail.value = true
}

function openAssetGuide() {
  showAssetGuide.value = true
}

function handleOntologyLinkSelect(linkKey: string) {
  const link = ontologyLinkTypes.value.find(item => item.link_key === linkKey)
  if (!link) return
  Object.assign(assetDraft.value, {
    relation_key: link.link_key,
    relation_type: 'join_path',
    source_concept: link.source_object_key,
    target_concept: link.target_object_key,
    name: link.name,
    description: link.description || '',
    join_left: '',
    join_right: '',
  })
}

async function handleSaveAsset() {
  if (!props.domainId) return
  try {
    const payload = { ...assetPayload.value }
    if (assetDraft.value.id) payload.id = Number(assetDraft.value.id)
    validateAssetPayload(editingAssetType.value, payload)
    await upsertSemanticAsset(props.domainId, editingAssetType.value, payload)
    ElMessage.success('保存成功')
    showAssetDialog.value = false
    await loadAssets()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  }
}

async function handleDeleteAsset(assetType: string, row: Record<string, unknown>) {
  if (!props.domainId) return
  const assetId = Number(row.id)
  if (!assetId) {
    ElMessage.error('缺少资产 ID，无法删除')
    return
  }
  const label = assetDisplayName(assetType, row)
  try {
    await ElMessageBox.confirm(
      `确定删除「${label}」？删除后需要重新构建查询运行时并更新验证检索索引，验证问数才会完全更新。`,
      '删除语义资产',
      { type: 'warning' },
    )
    await deleteSemanticAsset(props.domainId, assetType, assetId)
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
    const relationKey = cleanText(draft.relation_key)
    const ontologyLink = ontologyLinkTypes.value.find(item => item.link_key === relationKey)
    return {
      relation_key: relationKey,
      relation_type: ontologyLink ? 'join_path' : draft.relation_type || 'join_path',
      source_concept: ontologyLink?.source_object_key || cleanText(draft.source_concept),
      target_concept: ontologyLink?.target_object_key || cleanText(draft.target_concept),
      name: ontologyLink?.name || cleanText(draft.name),
      description: ontologyLink?.description || cleanText(draft.description),
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
  relation_key: '本体关系标识',
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
  join_path: '物理 JOIN 绑定',
  conditions: '条件',
  base_table: '基础物理表',
  time_field: '物理时间字段',
  formula_sql: 'SQL 计算公式',
  aggregation: '聚合方式',
  dimensions: '可用维度',
  default_filters: '默认过滤',
  applies_to: '适用对象',
  expression: '表达式',
  severity: '级别',
  asset_type: '资产类型',
  asset_key: '资产键',
  role: '角色',
  table_name: '物理表名',
  column_name: '物理字段名',
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
    object: '对象', event: '事件', state: '状态', dimension: '维度', action: '动作词汇（不可执行）',
  }
  return map[type] || type
}

function relationTypeLabel(type: string) {
  const map: Record<string, string> = {
    join_path: '查询关联路径', relationship: '对象关系', event_flow: '事件链路', state_transition: '状态流转',
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
  height: 100%;
  min-height: 0;
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
  min-width: min(100%, 980px);
  gap: 10px;
  align-items: center;
  justify-content: flex-end;
}

.toolbar-row {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px;
  border: 1px solid var(--wq-border);
  border-radius: 10px;
  background: #fff;
}

.toolbar-group-primary {
  background: #f8fafc;
}

.toolbar-group :deep(.el-button) {
  margin-left: 0;
}

.toolbar-group :deep(.el-button:not(.el-button--primary):not(.el-button--danger)) {
  border-color: transparent;
  background: transparent;
}

.toolbar-caret {
  margin-left: 5px;
  font-size: 12px;
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
  border: 1px solid var(--wq-border-strong);
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

.asset-boundary-note {
  display: grid;
  gap: 5px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border-left: 3px solid var(--wq-primary);
  border-radius: 6px;
  background: #f5f9ff;
  color: #475467;
  font-size: 13px;
  line-height: 1.65;
}

.asset-boundary-note strong {
  color: var(--wq-text);
  font-size: 14px;
}

.asset-form-section {
  margin-bottom: 16px;
  padding: 14px 14px 2px;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: #fff;
}

.asset-form-section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  padding-bottom: 11px;
  border-bottom: 1px solid #e8edf4;
}

.asset-form-section-heading > div {
  display: grid;
  gap: 4px;
}

.asset-form-section-heading strong {
  color: var(--wq-text);
  font-size: 14px;
}

.asset-form-section-heading span {
  color: var(--wq-muted);
  font-size: 12px;
  line-height: 1.55;
}

.form-help {
  display: block;
  width: 100%;
  margin-top: 6px;
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 1.55;
}

.relation-reference-summary {
  display: grid;
  gap: 6px;
  margin: 0 0 12px 112px;
  padding: 12px;
  border: 1px solid #cddcf0;
  border-radius: 7px;
  background: #f8fbff;
}

.relation-reference-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.relation-reference-title strong {
  color: var(--wq-text);
  font-size: 14px;
}

.relation-reference-summary code {
  width: fit-content;
  max-width: 100%;
  color: #526172;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.relation-reference-summary > span,
.relation-reference-summary p {
  margin: 0;
  color: #475467;
  font-size: 12px;
  line-height: 1.55;
}

.advanced-asset-settings {
  margin-bottom: 14px;
  padding: 0 14px 2px;
  border: 1px solid #cfd8e6;
  border-radius: 8px;
  background: #f8fafc;
}

.advanced-asset-settings summary {
  padding: 13px 0;
  color: var(--wq-text);
  font-size: 13px;
  font-weight: 720;
  cursor: pointer;
}

.advanced-asset-note {
  margin: 0 0 14px;
  padding: 9px 11px;
  border-radius: 6px;
  background: #eef3f8;
  color: #526172;
  font-size: 12px;
  line-height: 1.6;
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
    min-width: 0;
  }

  .toolbar-row {
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

  .asset-form-section-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .relation-reference-summary {
    margin-left: 0;
  }
}
</style>
