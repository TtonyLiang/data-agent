<template>
  <div class="page-shell" :class="`mode-${mode}`">
    <div class="page-header">
      <div>
        <h2>{{ mode === 'business' ? '指标与业务规则' : '数据绑定' }}</h2>
        <p v-if="mode === 'business'">选择一个业务对象，在同一处维护它的查询词汇、指标口径和业务规则。</p>
        <p v-else>把已定义的业务对象、关系和指标绑定到已采集的数据表与字段。</p>
      </div>
    </div>

    <el-empty v-if="!domainId || !currentDomain" description="请先选择业务领域" />

    <template v-else-if="mode === 'business'">
      <div v-if="ontologyObjectTypes.length" class="business-object-layout">
        <aside class="object-index" aria-label="业务对象列表">
          <div class="object-index-heading">
            <strong>业务对象</strong>
            <span>{{ ontologyObjectTypes.length }} 个</span>
          </div>
          <button
            v-for="item in ontologyObjectTypes"
            :key="item.object_key"
            type="button"
            :class="{ active: selectedObjectKey === item.object_key }"
            :aria-pressed="selectedObjectKey === item.object_key"
            @click="selectedObjectKey = item.object_key"
          >
            <span><b>{{ item.name }}</b><code>{{ item.object_key }}</code></span>
            <small>{{ metricCountForObject(item.object_key) }} 个指标</small>
          </button>
          <button
            type="button"
            :class="{ active: selectedObjectKey === DOMAIN_METRICS_KEY }"
            :aria-pressed="selectedObjectKey === DOMAIN_METRICS_KEY"
            @click="selectedObjectKey = DOMAIN_METRICS_KEY"
          >
            <span><b>领域级指标</b><code>domain_metrics</code></span>
            <small>{{ unassignedMetrics.length }} 个指标</small>
          </button>
        </aside>

        <section class="object-model-surface">
          <header class="object-model-header">
            <div>
              <h3>{{ selectedObject?.name || '领域级指标与规则' }}</h3>
              <p>{{ selectedObject?.description || '用于不只属于单个业务对象的统计口径。' }}</p>
            </div>
            <code>{{ selectedObject?.object_key || 'domain' }}</code>
          </header>

          <div v-if="selectedObject" class="object-context-strip">
            <div><span>属性</span><strong>{{ selectedObject.properties.length }}</strong></div>
            <div><span>关联关系</span><strong>{{ relationCountForObject(selectedObject.object_key) }}</strong></div>
            <div><span>指标</span><strong>{{ objectMetricRows.length }}</strong></div>
            <div><span>业务规则</span><strong>{{ objectRuleRows.length }}</strong></div>
          </div>

          <section v-if="selectedObject" class="model-block vocabulary-block">
            <div class="model-block-heading">
              <div>
                <h4>查询词汇</h4>
                <p>业务对象直接来自本体，这里只补充用户可能使用的别名和口语。</p>
              </div>
              <el-button size="small" @click="openConceptForObject">
                {{ selectedObjectConcept ? '编辑查询词汇' : '补充查询词汇' }}
              </el-button>
            </div>
            <div v-if="selectedObjectConcept" class="vocabulary-content">
              <strong>{{ selectedObjectConcept.name }}</strong>
              <div class="dim-chips">
                <el-tag v-for="word in selectedObjectConcept.synonyms || []" :key="String(word)" size="small" effect="plain">{{ word }}</el-tag>
                <span v-if="!(selectedObjectConcept.synonyms || []).length" class="muted-copy">尚未配置同义词</span>
              </div>
            </div>
            <el-alert v-else type="info" :closable="false" title="对象定义已经生效，不需要再创建第二个语义对象；只有存在业务别名时才补充查询词汇。" />
          </section>

          <section class="model-block">
            <div class="model-block-heading">
              <div><h4>业务指标</h4><p>先定义算什么、按什么维度拆分，数据实现稍后在“数据绑定”完成。</p></div>
              <el-button type="primary" size="small" @click="openMetricForObject">新建指标</el-button>
            </div>
            <el-table v-if="objectMetricRows.length" :data="objectMetricRows" size="small" class="compact-model-table">
              <el-table-column label="指标" min-width="190">
                <template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.metric_key }}</code></div></template>
              </el-table-column>
              <el-table-column label="业务口径" min-width="260" prop="description" show-overflow-tooltip />
              <el-table-column label="可用维度" min-width="230">
                <template #default="{ row }"><div class="dim-chips"><el-tag v-for="dim in row.dimensions || []" :key="String(dim)" size="small" effect="plain">{{ semanticLabel(String(dim)) }}</el-tag><span v-if="!(row.dimensions || []).length" class="muted-copy">未配置</span></div></template>
              </el-table-column>
              <el-table-column label="数据绑定" width="120">
                <template #default="{ row }"><el-tag :type="metricBindingComplete(row) ? 'success' : 'warning'" effect="plain">{{ metricBindingComplete(row) ? '已完成' : '待补充' }}</el-tag></template>
              </el-table-column>
              <el-table-column label="操作" width="150" fixed="right">
                <template #default="{ row }"><el-button link type="primary" @click="openAssetDetail('metric', row)">详情</el-button><el-button link type="primary" @click="openEditAsset('metric', row)">编辑</el-button></template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="当前对象尚未定义指标" :image-size="72" />
          </section>

          <section class="model-block">
            <div class="model-block-heading">
              <div><h4>业务规则</h4><p>只维护口径、过滤、时间和约束规则；查询改写等技术规则放在高级配置。</p></div>
              <el-button size="small" @click="openRuleForObject">新建规则</el-button>
            </div>
            <el-table v-if="objectRuleRows.length" :data="objectRuleRows" size="small" class="compact-model-table">
              <el-table-column label="规则" min-width="190"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.rule_key }}</code></div></template></el-table-column>
              <el-table-column label="类型" width="110"><template #default="{ row }">{{ ruleTypeLabel(String(row.rule_type || '')) }}</template></el-table-column>
              <el-table-column label="说明" min-width="280" prop="description" show-overflow-tooltip />
              <el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openAssetDetail('rule', row)">详情</el-button><el-button link type="primary" @click="openEditAsset('rule', row)">编辑</el-button></template></el-table-column>
            </el-table>
            <el-empty v-else description="当前对象尚未定义业务规则" :image-size="72" />
            <el-alert
              v-if="objectTechnicalRuleRows.length"
              class="technical-rule-note"
              type="info"
              :closable="false"
              :title="`另有 ${objectTechnicalRuleRows.length} 条查询运行规则，已放入“数据绑定 → 高级查询配置”。`"
            />
          </section>
        </section>
      </div>
      <el-empty v-else description="请先在“业务对象与动作”中创建业务对象" />
    </template>

    <template v-else>
      <div class="binding-summary" aria-label="数据绑定完成情况">
        <div><span>对象数据源</span><strong>{{ boundObjectCount }} / {{ ontologyObjectTypes.length }}</strong></div>
        <div><span>指标计算</span><strong>{{ boundMetricCount }} / {{ assetCounts.metric }}</strong></div>
        <div><span>关系连接</span><strong>{{ boundRelationCount }} / {{ ontologyLinkTypes.length }}</strong></div>
        <div><span>字段映射</span><strong>{{ assetCounts.mapping }}</strong></div>
      </div>
      <el-alert v-if="!currentDomain?.datasource_id" class="datasource-warning" type="warning" :closable="false" title="当前业务领域尚未绑定默认数据源，请先到领域管理或数据源页面完成连接与 Schema 采集。" />

      <div class="binding-layout">
        <nav class="binding-steps" aria-label="数据绑定步骤">
          <button v-for="step in bindingSteps" :key="step.key" type="button" :class="{ active: bindingSection === step.key }" :aria-current="bindingSection === step.key ? 'step' : undefined" @click="bindingSection = step.key">
            <span>{{ step.label }}</span><small>{{ step.description }}</small>
          </button>
        </nav>
        <section class="binding-workspace">
          <ObjectDataBindingPanel v-if="bindingSection === 'object'" :domain-id="domainId" :current-domain="currentDomain" @updated="loadOntologyObjectOptions" />

          <template v-else-if="bindingSection === 'metric'">
            <div class="binding-section-heading"><div><h3>指标计算</h3><p>业务口径在业务模型中维护，这里只确认基础表、时间字段和计算公式。</p></div></div>
            <el-table :data="assets.metric || []" size="small" class="binding-table">
              <el-table-column label="业务对象" min-width="150"><template #default="{ row }">{{ objectName(metricObjectKeys(row)[0]) }}</template></el-table-column>
              <el-table-column label="指标" min-width="180"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.metric_key }}</code></div></template></el-table-column>
              <el-table-column label="基础表" min-width="190"><template #default="{ row }"><code>{{ row.base_table || '未配置' }}</code></template></el-table-column>
              <el-table-column label="时间字段" min-width="190"><template #default="{ row }"><code>{{ row.time_field || '未配置' }}</code></template></el-table-column>
              <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="metricBindingComplete(row) ? 'success' : 'warning'" effect="plain">{{ metricBindingComplete(row) ? '已绑定' : '待补充' }}</el-tag></template></el-table-column>
              <el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openAssetDetail('metric', row)">详情</el-button><el-button v-if="canManageTechnical" link type="primary" @click="openEditAsset('metric', row)">配置</el-button></template></el-table-column>
            </el-table>
          </template>

          <template v-else-if="bindingSection === 'relation'">
            <div class="binding-section-heading"><div><h3>关系连接</h3><p>业务关系只维护一次，这里为已有本体关系补充数据库 JOIN。</p></div></div>
            <el-table :data="relationBindingRows" size="small" class="binding-table">
              <el-table-column label="业务关系" min-width="210"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.link_key }}</code></div></template></el-table-column>
              <el-table-column label="关系方向" min-width="250"><template #default="{ row }"><code>{{ row.source_object_key }}</code><span class="relation-inline-arrow">→</span><code>{{ row.target_object_key }}</code></template></el-table-column>
              <el-table-column label="物理连接" min-width="300"><template #default="{ row }">{{ relationJoinLabel(row.semantic_relation) }}</template></el-table-column>
              <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="relationHasJoin(row.semantic_relation) ? 'success' : 'warning'" effect="plain">{{ relationHasJoin(row.semantic_relation) ? '已绑定' : '待配置' }}</el-tag></template></el-table-column>
              <el-table-column label="操作" width="130" fixed="right"><template #default="{ row }"><el-button v-if="canManageTechnical" link type="primary" @click="openRelationForLink(row)">{{ row.semantic_relation ? '编辑' : '配置' }}</el-button><span v-else class="muted-copy">技术人员配置</span></template></el-table-column>
            </el-table>
          </template>

          <template v-else-if="bindingSection === 'mapping'">
            <div class="binding-section-heading"><div><h3>字段映射</h3><p>从已采集 Schema 选择表和字段，将维度、过滤项和对象属性绑定到真实数据。</p></div><el-button v-if="canManageTechnical" type="primary" size="small" @click="openAssetDialog('mapping')">新增映射</el-button></div>
            <el-table :data="assets.mapping || []" size="small" class="binding-table">
              <el-table-column label="业务字段" min-width="180"><template #default="{ row }"><div class="primary-cell"><strong>{{ semanticLabel(String(row.asset_key || '')) }}</strong><code>{{ row.asset_key }}</code></div></template></el-table-column>
              <el-table-column label="查询角色" width="120"><template #default="{ row }">{{ roleLabel(String(row.role || '')) }}</template></el-table-column>
              <el-table-column label="物理表" min-width="180"><template #default="{ row }"><code>{{ row.table_name }}</code></template></el-table-column>
              <el-table-column label="字段或表达式" min-width="250"><template #default="{ row }"><code>{{ row.column_name || row.expression_sql || '未配置' }}</code></template></el-table-column>
              <el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openAssetDetail('mapping', row)">详情</el-button><el-button v-if="canManageTechnical" link type="primary" @click="openEditAsset('mapping', row)">编辑</el-button></template></el-table-column>
            </el-table>
          </template>

          <template v-else>
            <div class="binding-section-heading"><div><h3>高级查询配置</h3><p>仅用于查询改写、召回和 LogicForm 调试，不属于业务建模主流程。</p></div></div>
            <el-collapse>
              <el-collapse-item title="查询运行规则" name="rules">
                <el-table :data="technicalRules" size="small">
                  <el-table-column label="规则" min-width="190"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.rule_key }}</code></div></template></el-table-column>
                  <el-table-column label="类型" width="120"><template #default="{ row }">{{ row.rule_type }}</template></el-table-column>
                  <el-table-column label="说明" min-width="280" prop="description" show-overflow-tooltip />
                  <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click="openAssetDetail('rule', row)">查看</el-button></template></el-table-column>
                </el-table>
              </el-collapse-item>
              <el-collapse-item title="LogicForm 模板" name="templates">
                <div class="advanced-section-action"><el-button v-if="canManageTechnical" size="small" @click="openAssetDialog('template')">新增模板</el-button></div>
                <el-table :data="assets.template || []" size="small">
                  <el-table-column label="模板" min-width="190"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.template_key }}</code></div></template></el-table-column>
                  <el-table-column label="意图" width="130"><template #default="{ row }">{{ intentTypeLabel(String(row.intent_type || '')) }}</template></el-table-column>
                  <el-table-column label="示例问法" min-width="280"><template #default="{ row }">{{ (row.examples || []).join('；') || '-' }}</template></el-table-column>
                  <el-table-column label="操作" width="140"><template #default="{ row }"><el-button link type="primary" @click="openAssetDetail('template', row)">详情</el-button><el-button v-if="canManageTechnical" link type="primary" @click="openEditAsset('template', row)">编辑</el-button></template></el-table-column>
                </el-table>
              </el-collapse-item>
            </el-collapse>
          </template>
        </section>
      </div>
    </template>

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
              <div class="asset-boundary-note" role="note">
                <strong>业务对象直接引用企业本体</strong>
                <span>这里不再创建第二套对象，只补充用户查询时可能使用的别名和口语。</span>
              </div>
              <el-form-item label="业务对象">
                <el-select v-model="assetDraft.concept_key" filterable @change="handleConceptObjectSelect">
                  <el-option v-for="item in ontologyObjectTypes" :key="item.object_key" :label="`${item.name} (${item.object_key})`" :value="item.object_key" />
                </el-select>
              </el-form-item>
              <el-form-item label="对象名称"><el-input v-model="assetDraft.name" disabled /></el-form-item>
              <el-form-item label="业务定义"><el-input v-model="assetDraft.description" type="textarea" :rows="3" disabled /></el-form-item>
              <el-form-item label="查询同义词">
                <el-input v-model="assetDraft.synonyms_text" placeholder="多个词用逗号或换行分隔" />
              </el-form-item>
            </template>

            <template v-else-if="editingAssetType === 'relation'">
              <div class="asset-boundary-note" role="note">
                <strong>引用本体关系，不重复定义业务关系</strong>
                <span>业务关系只在“业务对象与动作”中维护一份。这里选择已有关系，并为查询运行时补充物理 JOIN 绑定。</span>
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
                  <span class="form-help">找不到所需关系时，请先到“业务对象与动作”创建业务关系，再回到这里配置查询路径。</span>
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
                <summary>物理 JOIN 绑定（技术人员高级配置）</summary>
                <div class="advanced-asset-note">
                  这里只说明该业务关系在数据库中如何连接，不改变关系本身的业务含义。字段格式建议为“表名.字段名”。
                </div>
                <el-form-item label="左侧物理字段"><el-select v-model="assetDraft.join_left" :disabled="!canManageTechnical" filterable allow-create default-first-option placeholder="选择已采集字段"><el-option v-for="item in qualifiedColumnOptions" :key="`left-${item.value}`" :label="item.label" :value="item.value" /></el-select></el-form-item>
                <el-form-item label="右侧物理字段"><el-select v-model="assetDraft.join_right" :disabled="!canManageTechnical" filterable allow-create default-first-option placeholder="选择已采集字段"><el-option v-for="item in qualifiedColumnOptions" :key="`right-${item.value}`" :label="item.label" :value="item.value" /></el-select></el-form-item>
              </details>
            </template>

            <template v-else-if="editingAssetType === 'metric'">
              <div class="asset-boundary-note" role="note">
                <strong>先确认业务口径，再绑定物理数据</strong>
                <span>业务人员负责确认指标名称、含义和适用维度；技术人员负责表、字段和 SQL 公式。</span>
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
                <el-form-item label="归属业务对象">
                  <el-select v-model="assetDraft.object_keys" multiple clearable filterable collapse-tags placeholder="可选，留空表示领域级指标">
                    <el-option v-for="item in ontologyObjectTypes" :key="item.object_key" :label="`${item.name} (${item.object_key})`" :value="item.object_key" />
                  </el-select>
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
                <el-form-item label="可用维度"><el-select :model-value="splitList(assetDraft.dimensions_text)" multiple filterable allow-create collapse-tags placeholder="选择对象属性或已映射维度" @change="setListDraft('dimensions_text', $event)"><el-option v-for="item in metricDimensionOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
                <el-form-item label="默认过滤">
                  <div class="inline-fields">
                    <el-select v-model="assetDraft.default_filter_field" clearable filterable allow-create placeholder="选择语义字段"><el-option v-for="item in metricDimensionOptions" :key="`filter-${item.value}`" :label="item.label" :value="item.value" /></el-select>
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
                <summary>物理数据绑定（技术人员高级配置）</summary>
                <div class="advanced-asset-note">以下配置决定查询运行时如何从数据库计算该指标，不应由业务人员自行修改。</div>
                <el-form-item label="基础物理表"><el-select v-model="assetDraft.base_table" :disabled="!canManageTechnical" filterable allow-create default-first-option placeholder="发布前必须选择已采集表"><el-option v-for="item in tableOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
                <el-form-item label="物理时间字段"><el-select v-model="assetDraft.time_field" :disabled="!canManageTechnical" clearable filterable allow-create default-first-option placeholder="选择已采集时间字段"><el-option v-for="item in qualifiedColumnOptions" :key="`time-${item.value}`" :label="item.label" :value="item.value" /></el-select></el-form-item>
                <el-form-item label="SQL 计算公式">
                  <el-input v-model="assetDraft.formula_sql" :disabled="!canManageTechnical" type="textarea" :rows="3" placeholder="支持 {base} 表别名占位" />
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
              <el-form-item label="适用对象"><el-select :model-value="splitList(assetDraft.applies_to_text)" multiple filterable allow-create collapse-tags placeholder="选择业务对象、指标或属性" @change="setListDraft('applies_to_text', $event)"><el-option v-for="item in ruleTargetOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
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
                <span>业务人员先在对象、指标和规则中确认口径；本页由技术人员把语义资产绑定到真实表字段。</span>
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
                <el-select v-model="assetDraft.asset_type" :disabled="!canManageTechnical">
                    <el-option label="维度" value="dimension" />
                    <el-option label="过滤项" value="filter" />
                    <el-option label="指标" value="metric" />
                    <el-option label="概念" value="concept" />
                  </el-select>
                </el-form-item>
                <el-form-item label="语义资产"><el-select v-model="assetDraft.asset_key" :disabled="!canManageTechnical" filterable allow-create default-first-option placeholder="选择业务字段或指标"><el-option v-for="item in mappingAssetOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
                <el-form-item label="查询角色">
                  <el-select v-model="assetDraft.role" :disabled="!canManageTechnical">
                    <el-option label="维度" value="dimension" />
                    <el-option label="过滤" value="filter" />
                    <el-option label="时间" value="time" />
                    <el-option label="字段" value="field" />
                    <el-option label="度量" value="measure" />
                  </el-select>
                </el-form-item>
              </section>
              <details class="advanced-asset-settings">
                <summary>物理数据绑定（技术人员高级配置）</summary>
                <div class="advanced-asset-note">表名、字段名和 SQL 表达式属于技术实现。数据库结构变化时，只调整这里，不改变上层业务语义。</div>
                <el-form-item label="物理表名" required><el-select v-model="assetDraft.table_name" :disabled="!canManageTechnical" filterable allow-create default-first-option placeholder="选择已采集表" @change="handleMappingTableSelect"><el-option v-for="item in tableOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
                <el-form-item label="物理字段名"><el-select v-model="assetDraft.column_name" :disabled="!canManageTechnical" clearable filterable allow-create default-first-option placeholder="选择已采集字段" @change="handleMappingColumnSelect"><el-option v-for="item in mappingColumnOptions" :key="item.value" :label="item.label" :value="item.columnName" /></el-select></el-form-item>
                <el-form-item label="SQL 表达式">
                  <el-input v-model="assetDraft.expression_sql" :disabled="!canManageTechnical" placeholder="可选，字段映射为空时使用" />
                </el-form-item>
                <el-form-item label="数据类型">
                  <el-input v-model="assetDraft.data_type" :disabled="!canManageTechnical" placeholder="如 varchar / int / decimal" />
                </el-form-item>
              </details>
            </template>

            <template v-else>
              <el-form-item label="标识">
                <el-input v-model="assetDraft.template_key" :disabled="!canManageTechnical" placeholder="如 metric_query" />
              </el-form-item>
              <el-form-item label="意图类型">
                <el-select v-model="assetDraft.intent_type" :disabled="!canManageTechnical">
                  <el-option label="指标查询" value="metric_query" />
                  <el-option label="元数据查询" value="metadata_query" />
                  <el-option label="普通问答" value="chat" />
                </el-select>
              </el-form-item>
              <el-form-item label="名称">
                <el-input v-model="assetDraft.name" />
              </el-form-item>
              <el-form-item label="必填槽位">
                <el-input v-model="assetDraft.required_slots_text" :disabled="!canManageTechnical" placeholder="如 metrics" />
              </el-form-item>
              <el-form-item label="可选槽位">
                <el-input v-model="assetDraft.optional_slots_text" :disabled="!canManageTechnical" placeholder="如 dimensions, filters, time_range" />
              </el-form-item>
              <el-form-item label="编译策略">
                <el-select v-model="assetDraft.compile_strategy_type" :disabled="!canManageTechnical">
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

        <section v-if="mode === 'binding'" class="json-preview-panel">
          <div class="preview-title">JSON 预览</div>
          <pre>{{ assetJsonPreview }}</pre>
        </section>
      </div>
      <template #footer>
        <el-button @click="showAssetDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!canEditAsset(editingAssetType)" @click="handleSaveAsset">保存</el-button>
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
          <el-button v-if="canEditAsset(selectedAssetType)" type="primary" :disabled="!selectedAsset" @click="selectedAsset && openEditAsset(selectedAssetType, selectedAsset)">
            编辑
          </el-button>
          <el-button v-if="canEditAsset(selectedAssetType)" type="danger" plain :disabled="!selectedAsset" @click="selectedAsset && handleDeleteAsset(selectedAssetType, selectedAsset)">
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

  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import {
  deleteSemanticAsset,
  fetchDatasourceSchema,
  fetchOntologyLinkTypes,
  fetchOntologyObjectTypes,
  fetchSemanticAssets,
  upsertSemanticAsset,
  type DatasourceTableMeta,
  type OntologyLinkType,
  type OntologyObjectType,
  type SemanticDomain,
} from '../api'
import { canEditModel, isTechnicalUser } from '../stores/auth'
import ObjectDataBindingPanel from './ObjectDataBindingPanel.vue'

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
  mode?: 'business' | 'binding'
  domainId: number | null
  currentDomain: SemanticDomain | null
}>()

const emit = defineEmits<{
  (event: 'domain-updated'): void
}>()

const assetTabs = [
  { name: 'concept', label: '查询词汇', description: '直接引用本体对象，只补充用户查询时使用的同义词和口语。' },
  { name: 'relation', label: '关系查询路径', description: '引用本体中已有业务关系，为跨对象查询补充物理 JOIN 绑定。' },
  { name: 'metric', label: '指标', description: '业务人员确认口径；技术人员绑定表、字段和 SQL 公式。' },
  { name: 'rule', label: '规则', description: '过滤规则、时间规则、权限边界和动作约束。' },
  { name: 'mapping', label: '数据映射', description: '技术人员将既有语义资产绑定到物理表字段或受控 SQL 表达式。' },
  { name: 'template', label: 'LogicForm 模板', description: '自然语言意图到结构化槽位的模板。' },
]

const DOMAIN_METRICS_KEY = '__domain_metrics__'
const BUSINESS_RULE_TYPES = new Set(['definition', 'filter', 'time', 'constraint'])
const bindingSteps = [
  { key: 'object', label: '对象数据源', description: '对象记录从哪里来' },
  { key: 'metric', label: '指标计算', description: '指标如何从数据计算' },
  { key: 'relation', label: '关系连接', description: '对象在数据库中如何关联' },
  { key: 'mapping', label: '字段映射', description: '维度和过滤项对应哪些字段' },
  { key: 'advanced', label: '高级查询配置', description: '规则改写与 LogicForm' },
] as const

const assetGuidePages: Record<string, AssetGuidePage> = {
  concept: {
    title: '查询词汇填写说明',
    subtitle: '业务对象来自企业本体，这里只补充用户查询时可能使用的别名和口语。',
    fields: [
      {
        key: 'concept_key',
        label: '标识',
        title: '标识 concept_key',
        purpose: '与业务模型中的 object_key 保持一致，系统自动引用，不需要重新命名。',
        instructions: ['从已有业务对象中选择。', '不要在这里创建第二个同义对象。'],
        examples: ['LoanApplication', 'Customer', 'LoanAccount'],
      },
      {
        key: 'name',
        label: '名称',
        title: '名称',
        purpose: '直接显示业务模型中的对象名称。',
        instructions: ['如需修改名称，请回到业务对象与动作。'],
        examples: ['订单', '支付成功', '订单状态'],
      },
      {
        key: 'description',
        label: '描述',
        title: '描述',
        purpose: '直接显示业务模型中的对象定义。',
        instructions: ['如需修改定义，请回到业务对象与动作。'],
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
    subtitle: '这里不创建第二份业务关系。先引用企业本体中已有的 link_key，再由技术人员补充查询所需的物理 JOIN。',
    fields: [
      {
        key: 'relation_key',
        label: '已有本体业务关系',
        title: '本体关系 link_key',
        purpose: '引用“业务对象与动作”中已维护的业务关系，确保业务含义只有一个权威来源。',
        instructions: ['从下拉列表选择已有关系。', '关系名称、起点对象、终点对象和业务定义会从企业本体带入。', '找不到所需关系时，先回到企业本体创建，不要在查询语义中另建一份。'],
        examples: ['选择“客户提交贷款申请 (customer_submits_application)”'],
      },
      {
        key: 'join_path',
        label: '物理 JOIN 绑定',
        title: '物理 JOIN 绑定',
        purpose: '告诉查询编译器，这条既有业务关系在真实数据库中如何连接。',
        instructions: ['由技术人员填写。', '左右字段建议使用“表名.字段名”。', '字段必须存在于已采集 Schema。', '数据库结构变化时只调整绑定，不改变本体关系。'],
        examples: ['orders.customer_id = customers.customer_id'],
      },
    ],
  },
  metric: {
    title: '指标填写说明',
    subtitle: '业务人员先确认指标名称、含义、维度和过滤口径；技术人员再配置物理表、时间字段和 SQL 公式。',
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
    subtitle: '映射是技术人员维护的技术绑定。它引用已有业务口径，把语义资产连接到真实数据库表字段。',
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
        purpose: '技术人员指定映射到哪张真实数据库表。',
        instructions: ['这是高级技术配置。', '填写已采集 Schema 里的英文表名。', '不要填写中文表名。'],
        examples: ['orders'],
      },
      {
        key: 'column_name',
        label: '字段名',
        title: '字段名',
        purpose: '技术人员指定映射到表里的哪个真实字段。',
        instructions: ['这是高级技术配置。', '填写字段英文名。', '如果不是单字段映射，可留空并填写表达式。'],
        examples: ['product_type', 'region', 'region'],
      },
      {
        key: 'expression_sql',
        label: '表达式',
        title: '表达式',
        purpose: '当语义资产不是单一字段时，由技术人员配置 SQL 表达式。',
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

const assets = ref<Record<string, Record<string, unknown>[]>>({})
const showAssetDialog = ref(false)
const showAssetGuide = ref(false)
const showAssetDetail = ref(false)
const ontologyLinkTypes = ref<OntologyLinkType[]>([])
const ontologyObjectTypes = ref<OntologyObjectType[]>([])
const datasourceSchema = ref<DatasourceTableMeta[]>([])
const editingAssetType = ref('concept')
const assetDialogMode = ref<'create' | 'edit'>('create')
const assetDraft = ref<AssetDraft>({})
const selectedAssetType = ref('concept')
const selectedAsset = ref<Record<string, unknown> | null>(null)
const selectedObjectKey = ref('')
const bindingSection = ref<(typeof bindingSteps)[number]['key']>('object')

const canManageTechnical = computed(() => isTechnicalUser())

function canEditAsset(assetType: string) {
  if (!canEditModel()) return false
  return !['relation', 'mapping', 'template'].includes(assetType) || canManageTechnical.value
}

const currentAssetTab = computed(() => assetTabs.find(tab => tab.name === editingAssetType.value))
const currentDetailTab = computed(() => assetTabs.find(tab => tab.name === selectedAssetType.value))
const assetPayload = computed(() => buildAssetPayload(editingAssetType.value, assetDraft.value))
const assetJsonPreview = computed(() => JSON.stringify(assetPayload.value, null, 2))
const currentAssetGuide = computed(() => assetGuidePages[editingAssetType.value])
const selectedObject = computed(() => (
  ontologyObjectTypes.value.find(item => item.object_key === selectedObjectKey.value) || null
))
const selectedObjectConcept = computed<Record<string, any> | null>(() => {
  if (!selectedObject.value) return null
  return (assets.value.concept || []).find(item => item.concept_key === selectedObject.value?.object_key) || null
})
const unassignedMetrics = computed(() => (assets.value.metric || []).filter(item => metricObjectKeys(item).length === 0))
const objectMetricRows = computed(() => {
  if (selectedObjectKey.value === DOMAIN_METRICS_KEY) return unassignedMetrics.value
  return (assets.value.metric || []).filter(item => metricObjectKeys(item).includes(selectedObjectKey.value))
})
const objectRuleRows = computed(() => {
  const rows = (assets.value.rule || []).filter(item => BUSINESS_RULE_TYPES.has(String(item.rule_type || '')))
  if (selectedObjectKey.value === DOMAIN_METRICS_KEY) {
    return rows.filter(item => !Array.isArray(item.applies_to) || item.applies_to.length === 0)
  }
  return rows.filter(ruleAppliesToSelectedObject)
})
const technicalRules = computed(() => (
  (assets.value.rule || []).filter(item => !BUSINESS_RULE_TYPES.has(String(item.rule_type || '')))
))
const objectTechnicalRuleRows = computed(() => technicalRules.value.filter(ruleAppliesToSelectedObject))
const relationBindingRows = computed(() => ontologyLinkTypes.value.map(link => ({
  ...link,
  semantic_relation: (assets.value.relation || []).find(item => item.relation_key === link.link_key) || null,
})))
const mappingKeys = computed(() => new Set((assets.value.mapping || []).map(item => String(item.asset_key || ''))))
const boundObjectCount = computed(() => ontologyObjectTypes.value.filter(item => item.sync_enabled && cleanText(item.source_query)).length)
const boundMetricCount = computed(() => (assets.value.metric || []).filter(metricBindingComplete).length)
const boundRelationCount = computed(() => relationBindingRows.value.filter(item => relationHasJoin(item.semantic_relation)).length)
const tableOptions = computed(() => datasourceSchema.value.map(table => ({
  value: table.table_name,
  label: table.table_comment ? `${table.table_comment} (${table.table_name})` : table.table_name,
})))
const qualifiedColumnOptions = computed(() => datasourceSchema.value.flatMap(table => (
  table.columns.map(column => ({
    value: `${table.table_name}.${column.column_name}`,
    label: column.column_comment
      ? `${column.column_comment} (${table.table_name}.${column.column_name})`
      : `${table.table_name}.${column.column_name}`,
    tableName: table.table_name,
    columnName: column.column_name,
    dataType: column.data_type,
  }))
)))
const metricDimensionOptions = computed(() => {
  const options = new Map<string, string>()
  for (const mapping of assets.value.mapping || []) {
    const key = String(mapping.asset_key || '')
    if (key) options.set(key, semanticLabel(key))
  }
  for (const objectType of ontologyObjectTypes.value) {
    for (const property of objectType.properties || []) {
      if (!options.has(property.property_key)) options.set(property.property_key, property.name)
    }
  }
  return [...options].map(([value, label]) => ({ value, label: `${label} (${value})` }))
})
const mappingAssetOptions = computed(() => {
  const options = new Map<string, string>()
  for (const metric of assets.value.metric || []) {
    options.set(String(metric.metric_key || ''), String(metric.name || metric.metric_key || ''))
  }
  for (const concept of assets.value.concept || []) {
    options.set(String(concept.concept_key || ''), String(concept.name || concept.concept_key || ''))
  }
  for (const objectType of ontologyObjectTypes.value) {
    for (const property of objectType.properties || []) {
      options.set(property.property_key, property.name)
    }
  }
  return [...options]
    .filter(([value]) => Boolean(value))
    .map(([value, label]) => ({ value, label: `${label} (${value})` }))
})
const ruleTargetOptions = computed(() => {
  const options = new Map<string, string>()
  for (const objectType of ontologyObjectTypes.value) {
    options.set(objectType.object_key, objectType.name)
    for (const property of objectType.properties || []) {
      options.set(property.property_key, property.name)
    }
  }
  for (const metric of assets.value.metric || []) {
    options.set(String(metric.metric_key || ''), String(metric.name || metric.metric_key || ''))
  }
  return [...options]
    .filter(([value]) => Boolean(value))
    .map(([value, label]) => ({ value, label: `${label} (${value})` }))
})
const mappingColumnOptions = computed(() => {
  const tableName = cleanText(assetDraft.value.table_name)
  if (!tableName) return qualifiedColumnOptions.value
  return qualifiedColumnOptions.value.filter(item => item.tableName === tableName)
})
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
const assetCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const tab of assetTabs) counts[tab.name] = assets.value[tab.name]?.length || 0
  return counts
})

watch(() => [props.domainId, props.currentDomain?.datasource_id] as const, async () => {
  await Promise.all([
    loadAssets(),
    loadOntologyRelationOptions(),
    loadOntologyObjectOptions(),
    loadDatasourceSchema(),
  ])
  bindingSection.value = 'object'
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

async function loadOntologyObjectOptions() {
  if (!props.domainId) {
    ontologyObjectTypes.value = []
    selectedObjectKey.value = ''
    return
  }
  const requestedDomainId = props.domainId
  try {
    const nextObjectTypes = await fetchOntologyObjectTypes(requestedDomainId)
    if (props.domainId !== requestedDomainId) return
    ontologyObjectTypes.value = nextObjectTypes
    const selectedStillExists = nextObjectTypes.some(item => item.object_key === selectedObjectKey.value)
    if (!selectedStillExists && selectedObjectKey.value !== DOMAIN_METRICS_KEY) {
      selectedObjectKey.value = nextObjectTypes[0]?.object_key || DOMAIN_METRICS_KEY
    }
  } catch {
    if (props.domainId !== requestedDomainId) return
    ontologyObjectTypes.value = []
    selectedObjectKey.value = DOMAIN_METRICS_KEY
  }
}

async function loadDatasourceSchema() {
  const datasourceId = props.currentDomain?.datasource_id
  if (!datasourceId) {
    datasourceSchema.value = []
    return
  }
  try {
    datasourceSchema.value = await fetchDatasourceSchema(Number(datasourceId))
  } catch {
    datasourceSchema.value = []
  }
}

function metricObjectKeys(metric: Record<string, unknown>) {
  const metadata = isPlainObject(metric.metadata) ? metric.metadata : {}
  const keys = [metadata.object_key, ...(Array.isArray(metadata.object_keys) ? metadata.object_keys : [])]
  return [...new Set(keys.map(item => cleanText(item)).filter(Boolean))]
}

function metricCountForObject(objectKey: string) {
  return (assets.value.metric || []).filter(item => metricObjectKeys(item).includes(objectKey)).length
}

function relationCountForObject(objectKey: string) {
  return ontologyLinkTypes.value.filter(item => item.source_object_key === objectKey || item.target_object_key === objectKey).length
}

function ruleAppliesToSelectedObject(rule: Record<string, unknown>) {
  if (selectedObjectKey.value === DOMAIN_METRICS_KEY) {
    return !Array.isArray(rule.applies_to) || rule.applies_to.length === 0
  }
  const relatedKeys = new Set([
    selectedObjectKey.value,
    ...objectMetricRows.value.map(item => String(item.metric_key || '')),
    ...(selectedObject.value?.properties || []).map(item => item.property_key),
  ])
  const appliesTo = Array.isArray(rule.applies_to) ? rule.applies_to.map(String) : []
  return appliesTo.some(key => relatedKeys.has(key))
}

function objectName(objectKey: unknown) {
  const key = cleanText(objectKey)
  if (!key) return '领域级指标'
  return ontologyObjectTypes.value.find(item => item.object_key === key)?.name || key
}

function metricBindingComplete(metric: Record<string, unknown>) {
  const dimensions = Array.isArray(metric.dimensions) ? metric.dimensions.map(String) : []
  return Boolean(
    cleanText(metric.base_table)
    && cleanText(metric.formula_sql)
    && dimensions.every(dimension => mappingKeys.value.has(dimension)),
  )
}

function relationJoinLabel(relation: Record<string, any> | null) {
  const path = Array.isArray(relation?.join_path) ? relation.join_path : []
  if (!path.length) return '尚未配置 JOIN'
  return path
    .map(item => `${cleanText(item.left) || '?'} = ${cleanText(item.right) || '?'}`)
    .join('；')
}

function relationHasJoin(relation: Record<string, any> | null) {
  return Array.isArray(relation?.join_path) && relation.join_path.length > 0
}

function openAssetDialog(assetType: string, objectKey = '') {
  editingAssetType.value = assetType
  assetDialogMode.value = 'create'
  assetDraft.value = defaultAssetDraft(assetType)
  if (assetType === 'metric' && objectKey) {
    assetDraft.value.object_keys = objectKey === DOMAIN_METRICS_KEY ? [] : [objectKey]
  }
  if (assetType === 'rule' && objectKey && objectKey !== DOMAIN_METRICS_KEY) {
    assetDraft.value.applies_to_text = objectKey
  }
  showAssetDialog.value = true
  if (assetType === 'relation') void loadOntologyRelationOptions()
}

function openMetricForObject() {
  openAssetDialog('metric', selectedObjectKey.value)
}

function openRuleForObject() {
  openAssetDialog('rule', selectedObjectKey.value)
}

function openConceptForObject() {
  if (!selectedObject.value) return
  if (selectedObjectConcept.value) {
    openEditAsset('concept', selectedObjectConcept.value)
    return
  }
  editingAssetType.value = 'concept'
  assetDialogMode.value = 'create'
  assetDraft.value = {
    ...defaultAssetDraft('concept'),
    concept_key: selectedObject.value.object_key,
    concept_type: 'object',
    name: selectedObject.value.name,
    description: selectedObject.value.description || '',
  }
  showAssetDialog.value = true
}

function openRelationForLink(row: Record<string, any>) {
  if (row.semantic_relation) {
    openEditAsset('relation', row.semantic_relation)
    return
  }
  editingAssetType.value = 'relation'
  assetDialogMode.value = 'create'
  assetDraft.value = {
    ...defaultAssetDraft('relation'),
    relation_key: row.link_key,
    relation_type: 'join_path',
    source_concept: row.source_object_key,
    target_concept: row.target_object_key,
    name: row.name,
    description: row.description || '',
  }
  showAssetDialog.value = true
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

function setListDraft(field: string, value: unknown) {
  assetDraft.value[field] = Array.isArray(value) ? value.map(String).join(', ') : cleanText(value)
}

function handleConceptObjectSelect(objectKey: string) {
  const objectType = ontologyObjectTypes.value.find(item => item.object_key === objectKey)
  if (!objectType) return
  assetDraft.value.concept_type = 'object'
  assetDraft.value.name = objectType.name
  assetDraft.value.description = objectType.description || ''
}

function handleMappingTableSelect() {
  const currentColumn = cleanText(assetDraft.value.column_name)
  if (!currentColumn) return
  if (!mappingColumnOptions.value.some(item => item.columnName === currentColumn)) {
    assetDraft.value.column_name = ''
    assetDraft.value.data_type = ''
  }
}

function handleMappingColumnSelect(columnName: string) {
  const option = mappingColumnOptions.value.find(item => item.columnName === columnName)
  if (option) assetDraft.value.data_type = option.dataType
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
      `确定删除「${label}」？删除后需要到“校验发布”重新校验、创建版本并更新检索索引。`,
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
    return { concept_key: '', concept_type: 'object', name: '', description: '', synonyms_text: '', metadata: {} }
  }
  if (type === 'relation') {
    return {
      relation_key: '', relation_type: 'join_path', source_concept: '', target_concept: '',
      name: '', description: '', join_left: '', join_right: '', _original_join_path: [], conditions: [], metadata: {},
    }
  }
  if (type === 'metric') {
    return {
      metric_key: '', name: '', description: '', synonyms_text: '', metric_type: 'measure',
      formula_sql: '', base_table: '', time_field: '', dimensions_text: '',
      default_filter_field: '', default_filter_operator: '=', default_filter_value: '',
      _original_default_filters: [], object_keys: [], metadata: {},
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
      expression_sql: '', data_type: '', role: 'dimension', filters: [],
    }
  }
  return {
    template_key: '', intent_type: 'metric_query', name: '', description: '',
    required_slots_text: 'metrics', optional_slots_text: 'dimensions, filters, time_range, sort, limit',
    compile_strategy_type: 'metric_select', examples_text: '', _original_compile_strategy: {},
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
      metadata: isPlainObject(row.metadata) ? row.metadata : {},
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
      _original_join_path: Array.isArray(row.join_path) ? row.join_path : [],
      conditions: Array.isArray(row.conditions) ? row.conditions : [],
      metadata: isPlainObject(row.metadata) ? row.metadata : {},
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
      _original_default_filters: Array.isArray(row.default_filters) ? row.default_filters : [],
      object_keys: metricObjectKeys(row),
      metadata: isPlainObject(row.metadata) ? row.metadata : {},
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
      _original_expression: expression,
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
      filters: Array.isArray(row.filters) ? row.filters : [],
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
    _original_compile_strategy: compileStrategy,
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
      metadata: isPlainObject(draft.metadata) ? draft.metadata : {},
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
      join_path: buildJoinPath(draft),
      conditions: Array.isArray(draft.conditions) ? draft.conditions : [],
      metadata: isPlainObject(draft.metadata) ? draft.metadata : {},
    }
  }
  if (type === 'metric') {
    const metadata = isPlainObject(draft.metadata) ? { ...draft.metadata } : {}
    delete metadata.object_key
    delete metadata.object_keys
    const objectKeys = Array.isArray(draft.object_keys)
      ? [...new Set(draft.object_keys.map(cleanText).filter(Boolean))]
      : []
    if (objectKeys.length === 1) metadata.object_key = objectKeys[0]
    else if (objectKeys.length > 1) metadata.object_keys = objectKeys
    return {
      metric_key: cleanText(draft.metric_key),
      name: cleanText(draft.name),
      description: cleanText(draft.description),
      synonyms: splitList(draft.synonyms_text),
      metric_type: draft.metric_type || 'measure',
      formula_sql: cleanText(draft.formula_sql),
      base_table: cleanText(draft.base_table),
      time_field: cleanText(draft.time_field) || null,
      default_filters: buildMetricFilters(draft),
      dimensions: splitList(draft.dimensions_text),
      metadata,
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
      filters: Array.isArray(draft.filters) ? draft.filters : [],
    }
  }
  return {
    template_key: cleanText(draft.template_key),
    intent_type: draft.intent_type || 'metric_query',
    name: cleanText(draft.name),
    description: cleanText(draft.description),
    required_slots: splitList(draft.required_slots_text),
    optional_slots: splitList(draft.optional_slots_text),
    compile_strategy: {
      ...(isPlainObject(draft._original_compile_strategy) ? draft._original_compile_strategy : {}),
      type: draft.compile_strategy_type || 'metric_select',
    },
    examples: splitList(draft.examples_text),
  }
}

function validateAssetPayload(type: string, payload: Record<string, unknown>) {
  const requiredMap: Record<string, string[]> = {
    concept: ['concept_key', 'name'],
    relation: ['relation_key', 'name', 'source_concept', 'target_concept'],
    metric: ['metric_key', 'name'],
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

function buildMetricFilters(draft: AssetDraft) {
  const originalFilters = Array.isArray(draft._original_default_filters)
    ? draft._original_default_filters.map((item: unknown) => isPlainObject(item) ? { ...item } : item)
    : []
  const originalFirst = isPlainObject(originalFilters[0]) ? originalFilters[0] : null
  const field = cleanText(draft.default_filter_field)
  const operator = draft.default_filter_operator || '='
  const valueText = cleanText(draft.default_filter_value)
  if (
    originalFirst
    && field === cleanText(originalFirst.field)
    && operator === (originalFirst.operator || '=')
    && valueText === cleanText(formValueToText(originalFirst.value))
  ) {
    return originalFilters
  }
  const nextFirst = buildSingleFilter(draft)[0]
  if (!nextFirst) return originalFilters.slice(1)
  return [nextFirst, ...originalFilters.slice(1)]
}

function buildJoinPath(draft: AssetDraft) {
  const originalPath = Array.isArray(draft._original_join_path)
    ? draft._original_join_path.map((item: unknown) => isPlainObject(item) ? { ...item } : item)
    : []
  const originalFirst = isPlainObject(originalPath[0]) ? originalPath[0] : null
  const left = cleanText(draft.join_left)
  const right = cleanText(draft.join_right)
  if (originalFirst && left === cleanText(originalFirst.left) && right === cleanText(originalFirst.right)) {
    return originalPath
  }
  if (!left || !right) return []
  return [{ left, right }, ...originalPath.slice(1)]
}

function buildExpression(draft: AssetDraft) {
  const originalExpression = isPlainObject(draft._original_expression)
    ? draft._original_expression
    : {}
  const originalEntry = Object.entries(originalExpression)[0]
  const originalKey = originalEntry?.[0] || ''
  const originalValueText = formValueToText(originalEntry?.[1])
  const key = cleanText(draft.expression_key)
  const valueText = cleanText(draft.expression_value)

  if (key === originalKey && valueText === cleanText(originalValueText)) {
    return originalExpression
  }

  const expression = { ...originalExpression }
  if (originalKey && originalKey !== key) delete expression[originalKey]
  if (!key) return expression
  expression[key] = parseExpressionValue(draft.expression_value)
  return expression
}

function parseExpressionValue(value: unknown): unknown {
  const text = cleanText(value)
  if ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))) {
    try {
      return JSON.parse(text)
    } catch {
      // Fall through to the existing scalar/list parser for malformed JSON-like text.
    }
  }
  return parseFormValue(value)
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
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 14px var(--wq-page-gutter) 20px !important;
  background: var(--wq-bg);
}

.page-header {
  flex: 0 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  margin-bottom: 12px;
}

.page-header h2 {
  font-size: 20px;
  line-height: 1.25;
  color: var(--wq-text);
}

.page-header p {
  margin-top: 4px;
  color: var(--wq-muted);
  font-size: 12px;
  line-height: 1.45;
}

@media (min-width: 901px) and (max-height: 820px) {
  .page-header { margin-bottom: 8px; }
  .page-header h2 { font-size: 18px; }
  .page-header p { margin-top: 2px; font-size: 11px; }
  .object-model-surface { padding: 12px; }
  .object-context-strip { margin: 7px 0; }
  .model-block { margin-top: 9px; padding: 12px; }
  .binding-workspace { padding: 10px; }
}

.business-object-layout {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid var(--wq-border);
  border-radius: 8px;
  background: var(--wq-surface);
  box-shadow: var(--wq-shadow);
}

.object-index {
  min-width: 0;
  padding: 10px 8px;
  overflow-y: auto;
  border-right: 1px solid var(--wq-border);
  background: #f8fafc;
}

.object-index-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 8px 10px;
  color: var(--wq-text);
  font-size: 13px;
}

.object-index-heading span { color: var(--wq-subtle); font-size: 11px; }

.object-index button {
  width: 100%;
  min-height: 50px;
  margin: 0 0 5px;
  padding: 7px 9px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--wq-muted);
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 7px;
  cursor: pointer;
  transition: background .16s ease, border-color .16s ease, color .16s ease;
}

.object-index button:hover { color: var(--wq-text); background: #fff; border-color: var(--wq-border); }
.object-index button:focus-visible { outline: 2px solid var(--wq-primary); outline-offset: 1px; }
.object-index button.active { color: var(--wq-primary-strong); background: var(--wq-primary-soft); border-color: #b2ccff; }
.object-index button > span { min-width: 0; display: grid; gap: 2px; }
.object-index button b { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.object-index button code { color: inherit; font-size: 10px; }
.object-index button small { flex: 0 0 auto; color: var(--wq-subtle); font-size: 10px; }

.object-model-surface {
  min-width: 0;
  padding: 16px;
  overflow-y: auto;
}

.object-model-header,
.model-block-heading,
.binding-section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.object-model-header h3,
.binding-section-heading h3 { margin: 0; color: var(--wq-text); font-size: 19px; }
.object-model-header p,
.model-block-heading p,
.binding-section-heading p { margin: 5px 0 0; color: var(--wq-muted); font-size: 12px; }
.object-model-header > code { flex: 0 0 auto; padding: 4px 7px; border: 1px solid var(--wq-border); border-radius: 5px; background: #f8fafc; color: #475467; font-size: 11px; }

.object-context-strip,
.binding-summary {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 10px 0;
  min-height: 58px;
  overflow: hidden;
  border: 1px solid var(--wq-border);
  border-radius: 7px;
  background: #f8fafc;
}

.object-context-strip > div,
.binding-summary > div { min-width: 0; padding: 8px 12px; }
.object-context-strip > div + div,
.binding-summary > div + div { border-left: 1px solid var(--wq-border); }
.object-context-strip span,
.binding-summary span { display: block; color: var(--wq-muted); font-size: 11px; }
.object-context-strip strong,
.binding-summary strong { display: block; margin-top: 2px; color: var(--wq-text); font-size: 17px; }

.model-block {
  margin-top: 14px;
  padding: 16px;
  border: 1px solid var(--wq-border);
  border-radius: 7px;
  background: #fff;
}

.model-block-heading { margin-bottom: 12px; }
.model-block-heading h4 { margin: 0; color: var(--wq-text); font-size: 15px; }
.model-block-heading .el-button { flex: 0 0 auto; margin-left: 0; }
.vocabulary-block { background: #f8fbff; }
.technical-rule-note { margin-top: 10px; }
.vocabulary-content { display: flex; align-items: center; gap: 16px; min-height: 34px; }
.vocabulary-content > strong { flex: 0 0 auto; color: var(--wq-text); font-size: 13px; }
.muted-copy { color: var(--wq-subtle); font-size: 12px; }

.compact-model-table,
.binding-table { width: 100%; }
.compact-model-table :deep(.el-table__header-wrapper th.el-table__cell),
.binding-table :deep(.el-table__header-wrapper th.el-table__cell) { color: #475467; background: #f5f7fa; font-size: 12px; font-weight: 680; }
.compact-model-table :deep(.el-table__body tr:hover > td.el-table__cell),
.binding-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: #f5f9ff !important; }
.primary-cell { min-width: 0; display: grid; gap: 3px; }
.primary-cell strong { overflow: hidden; color: var(--wq-text); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.primary-cell code { color: var(--wq-subtle); font-size: 10px; }

.datasource-warning { margin-bottom: 10px; }
.binding-layout { flex: 1 1 auto; min-height: 0; display: grid; grid-template-columns: 230px minmax(0, 1fr); overflow: hidden; border: 1px solid var(--wq-border); border-radius: 8px; background: var(--wq-surface); box-shadow: var(--wq-shadow); }
.binding-steps { padding: 8px; overflow-y: auto; border-right: 1px solid var(--wq-border); background: #f8fafc; }
.binding-steps button { width: 100%; min-height: 50px; margin-bottom: 5px; padding: 7px 10px; display: grid; gap: 2px; color: var(--wq-muted); text-align: left; background: transparent; border: 1px solid transparent; border-radius: 7px; cursor: pointer; transition: background .16s ease, border-color .16s ease, color .16s ease; }
.binding-steps button:hover { color: var(--wq-text); background: #fff; border-color: var(--wq-border); }
.binding-steps button:focus-visible { outline: 2px solid var(--wq-primary); outline-offset: 1px; }
.binding-steps button.active { color: var(--wq-primary-strong); background: var(--wq-primary-soft); border-color: #b2ccff; }
.binding-steps span { font-size: 13px; font-weight: 650; }
.binding-steps small { color: var(--wq-subtle); font-size: 11px; line-height: 1.4; }
.binding-workspace { min-width: 0; padding: 14px; overflow: auto; }
.binding-section-heading { margin-bottom: 14px; }
.relation-inline-arrow { display: inline-block; margin: 0 8px; color: var(--wq-primary); }
.advanced-section-action { display: flex; justify-content: flex-end; margin-bottom: 8px; }

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

.mode-business .asset-editor { grid-template-columns: minmax(0, 1fr); }

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

  .business-object-layout { grid-template-columns: 220px minmax(0, 1fr); }
  .binding-layout { grid-template-columns: 205px minmax(0, 1fr); }
}

@media (max-width: 900px) {
  .page-shell { display: block; overflow: auto; padding: 16px !important; }
  .business-object-layout,
  .binding-layout { min-height: 0; grid-template-columns: 1fr; overflow: visible; }
  .object-index,
  .binding-steps { display: flex; gap: 7px; overflow-x: auto; border-right: 0; border-bottom: 1px solid var(--wq-border); }
  .object-index-heading { display: none; }
  .object-index button,
  .binding-steps button { flex: 0 0 205px; margin-bottom: 0; }
  .object-model-surface,
  .binding-workspace { padding: 16px; overflow: visible; }
  .object-context-strip,
  .binding-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .object-context-strip > div:nth-child(3),
  .binding-summary > div:nth-child(3) { border-left: 0; border-top: 1px solid var(--wq-border); }
  .object-context-strip > div:nth-child(4),
  .binding-summary > div:nth-child(4) { border-top: 1px solid var(--wq-border); }

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

@media (max-width: 620px) {
  .object-model-header,
  .model-block-heading,
  .binding-section-heading,
  .vocabulary-content { align-items: stretch; flex-direction: column; }
  .object-model-header > code { width: fit-content; }
  .model-block-heading .el-button,
  .binding-section-heading .el-button { width: 100%; }
  .object-context-strip,
  .binding-summary { grid-template-columns: 1fr; }
  .object-context-strip > div + div,
  .binding-summary > div + div { border-top: 1px solid var(--wq-border); border-left: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .object-index button,
  .binding-steps button { transition: none; }
}
</style>
