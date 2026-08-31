<template>
  <div class="ontology-page" v-loading="loading">
    <header class="page-toolbar">
      <div class="title-group">
        <h2>企业本体建模</h2>
        <p v-if="currentDomain">{{ currentDomain.name }} · {{ currentDomain.domain_key }}</p>
      </div>
      <div class="toolbar-actions">
        <el-select v-model="domainId" class="domain-select" placeholder="选择领域">
          <el-option
            v-for="domain in domains"
            :key="domain.id"
            :label="domain.name"
            :value="domain.id"
          />
        </el-select>
        <el-tag v-if="summary?.latest_release" type="success" effect="plain">
          V{{ summary.latest_release.version }} 已发布
        </el-tag>
        <el-tag v-else type="info" effect="plain">未发布</el-tag>
        <input v-if="canManage" ref="importInput" class="file-input" type="file" accept="application/json,.json" @change="handleImport" />
        <el-button v-if="canManage" :icon="FolderOpened" :disabled="!domainId" @click="importInput?.click()">导入</el-button>
        <el-button v-if="canManage" :icon="Download" :disabled="!domainId" @click="handleExport">导出</el-button>
        <el-button v-if="canManage" :icon="CircleCheck" :disabled="!domainId" @click="handleValidate">
          校验
        </el-button>
        <el-button v-if="canManage" type="primary" :icon="Upload" :disabled="!domainId" @click="handlePublish">
          发布
        </el-button>
        <el-tag v-else type="info" effect="plain">业务视图 · 只读建模</el-tag>
      </div>
    </header>

    <el-empty v-if="!loading && domains.length === 0" description="暂无可用领域" />

    <template v-else-if="domainId">
      <section class="metric-strip">
        <div v-for="metric in metrics" :key="metric.label" class="metric-item">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <el-icon><component :is="metric.icon" /></el-icon>
        </div>
      </section>

      <el-tabs v-model="activeTab" class="workspace-tabs" @tab-change="handleTabChange">
        <el-tab-pane label="本体图谱" name="graph">
          <section class="graph-panel">
            <div ref="graphElement" class="ontology-graph" />
            <el-empty
              v-if="objectTypes.length === 0"
              class="graph-empty"
              description="尚未定义对象类型"
            />
          </section>
        </el-tab-pane>

        <el-tab-pane label="对象类型" name="objects">
          <section class="table-section">
            <div class="section-toolbar">
              <div>
                <strong>对象类型</strong>
                <span>{{ objectTypes.length }} 项</span>
              </div>
              <el-button v-if="canManage" type="primary" :icon="Plus" @click="openObjectTypeDialog()">
                新建对象
              </el-button>
            </div>
            <el-table :data="objectTypes" row-key="id" height="calc(100vh - 312px)">
              <el-table-column type="expand" width="42">
                <template #default="{ row }">
                  <div class="property-grid">
                    <div v-for="property in row.properties" :key="property.property_key" class="property-row">
                      <code>{{ property.property_key }}</code>
                      <span>{{ property.name }}</span>
                      <el-tag size="small" effect="plain">{{ typeLabel(property.data_type) }}</el-tag>
                      <el-tag v-if="property.property_key === row.primary_property" size="small" type="warning">主属性</el-tag>
                      <el-tag v-if="property.required" size="small" type="danger" effect="plain">必填</el-tag>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="业务对象" min-width="210">
                <template #default="{ row }">
                  <div class="primary-cell">
                    <strong>{{ row.name }}</strong>
                    <code>{{ row.object_key }}</code>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="description" label="业务定义" min-width="280" show-overflow-tooltip />
              <el-table-column label="属性" width="90">
                <template #default="{ row }">{{ row.properties.length }}</template>
              </el-table-column>
              <el-table-column label="业务库同步" width="170">
                <template #default="{ row }">
                  <div class="sync-status-cell">
                    <el-tooltip
                      v-if="row.sync_enabled"
                      :disabled="!row.last_sync_error"
                      :content="row.last_sync_error || ''"
                      placement="top"
                    >
                      <el-tag size="small" effect="plain" :type="syncStatusType(row.last_sync_status)">
                        {{ syncStatusLabel(row) }}
                      </el-tag>
                    </el-tooltip>
                    <span v-else class="muted">未启用</span>
                    <small v-if="row.last_synced_at">
                      {{ formatDateTime(row.last_synced_at) }} · {{ row.last_sync_total || row.last_sync_count || 0 }} 条
                    </small>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="statusType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="120" fixed="right" align="center" header-align="center">
                <template #default="{ row }">
                  <div class="table-actions">
                    <el-tooltip v-if="canManage" content="编辑" placement="top">
                      <el-button class="table-action-btn" text :icon="Edit" aria-label="编辑对象类型" @click="openObjectTypeDialog(row)" />
                    </el-tooltip>
                    <el-tooltip v-if="canManage" content="删除" placement="top">
                      <el-button class="table-action-btn is-danger" text type="danger" :icon="Delete" aria-label="删除对象类型" @click="removeObjectType(row)" />
                    </el-tooltip>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="关系类型" name="relations">
          <section class="table-section">
            <div class="section-toolbar">
              <div><strong>关系类型</strong><span>{{ linkTypes.length }} 项</span></div>
              <el-button v-if="canManage" type="primary" :icon="Plus" @click="openLinkTypeDialog()">新建关系</el-button>
            </div>
            <el-table :data="linkTypes" height="calc(100vh - 312px)">
              <el-table-column label="关系" min-width="200">
                <template #default="{ row }">
                  <div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.link_key }}</code></div>
                </template>
              </el-table-column>
              <el-table-column label="起点" min-width="150">
                <template #default="{ row }"><code>{{ row.source_object_key }}</code></template>
              </el-table-column>
              <el-table-column width="70" align="center"><template #default><ArrowRight /></template></el-table-column>
              <el-table-column label="终点" min-width="150">
                <template #default="{ row }"><code>{{ row.target_object_key }}</code></template>
              </el-table-column>
              <el-table-column label="基数" width="120">
                <template #default="{ row }">{{ cardinalityLabel(row.cardinality) }}</template>
              </el-table-column>
              <el-table-column prop="description" label="业务定义" min-width="240" show-overflow-tooltip />
              <el-table-column label="操作" width="120" fixed="right" align="center" header-align="center">
                <template #default="{ row }">
                  <div class="table-actions">
                    <el-tooltip v-if="canManage" content="编辑" placement="top">
                      <el-button class="table-action-btn" text :icon="Edit" aria-label="编辑关系类型" @click="openLinkTypeDialog(row)" />
                    </el-tooltip>
                    <el-tooltip v-if="canManage" content="删除" placement="top">
                      <el-button class="table-action-btn is-danger" text type="danger" :icon="Delete" aria-label="删除关系类型" @click="removeLinkType(row)" />
                    </el-tooltip>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="动作类型" name="actions">
          <section class="table-section">
            <div class="section-toolbar">
              <div><strong>业务动作</strong><span>{{ actionTypes.length }} 项</span></div>
              <el-button v-if="canManage" type="primary" :icon="Plus" @click="openActionTypeDialog()">新建动作</el-button>
            </div>
            <el-table :data="actionTypes" height="calc(100vh - 312px)">
              <el-table-column label="动作" min-width="210">
                <template #default="{ row }">
                  <div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.action_key }}</code></div>
                </template>
              </el-table-column>
              <el-table-column label="目标对象" min-width="140">
                <template #default="{ row }"><code>{{ row.target_object_key }}</code></template>
              </el-table-column>
              <el-table-column label="参数 / 条件 / 效果" width="170">
                <template #default="{ row }">{{ row.parameters.length }} / {{ row.preconditions.length }} / {{ row.effects.length }}</template>
              </el-table-column>
              <el-table-column label="授权角色" min-width="140">
                <template #default="{ row }">
                  <el-tag v-for="role in row.allowed_roles" :key="role" size="small" effect="plain">{{ role }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="审批要求" width="128" align="center" header-align="center">
                <template #default="{ row }">
                  <el-tooltip
                    :content="row.requires_approval ? '执行时必须填写审批单号' : '执行时不要求审批单号，但仍受角色、状态和前置条件限制'"
                    placement="top"
                  >
                    <el-tag
                      size="small"
                      effect="plain"
                      class="approval-tag"
                      :type="row.requires_approval ? 'warning' : 'info'"
                    >
                      {{ row.requires_approval ? '需审批单号' : '无需审批单号' }}
                    </el-tag>
                  </el-tooltip>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="176" fixed="right" align="center" header-align="center">
                <template #default="{ row }">
                  <div class="table-actions">
                    <el-tooltip v-if="canExecuteAction(row)" content="执行动作" placement="top">
                      <el-button class="table-action-btn is-primary" text type="primary" :icon="VideoPlay" aria-label="执行动作" @click="openExecuteDialog(row)" />
                    </el-tooltip>
                    <el-tooltip v-if="canManage" content="编辑动作" placement="top">
                      <el-button class="table-action-btn" text :icon="Edit" aria-label="编辑动作" @click="openActionTypeDialog(row)" />
                    </el-tooltip>
                    <el-tooltip v-if="canManage" content="删除动作" placement="top">
                      <el-button class="table-action-btn is-danger" text type="danger" :icon="Delete" aria-label="删除动作" @click="removeActionType(row)" />
                    </el-tooltip>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="对象实例" name="instances">
          <section class="table-section">
            <div class="section-toolbar instance-toolbar">
              <div class="instance-filter">
                <strong>业务对象</strong>
                <el-select v-model="instanceTypeId" placeholder="选择对象类型" @change="handleInstanceTypeChange">
                  <el-option v-for="item in objectTypes" :key="item.id" :label="item.name" :value="item.id" />
                </el-select>
              </div>
              <div>
                <el-button :icon="Refresh" :loading="syncing" :disabled="!instanceTypeId" @click="syncAndLoadInstances(true)">刷新</el-button>
                <el-button v-if="canManage" :icon="Connection" @click="openLinkInstanceDialog">建立关系</el-button>
                <el-button v-if="canManage" type="primary" :icon="Plus" @click="openObjectInstanceDialog()">新建实例</el-button>
              </div>
            </div>
            <el-table class="instance-table" :data="objects" height="calc(100% - 116px)" v-loading="syncing">
              <el-table-column label="对象" min-width="220">
                <template #default="{ row }">
                  <div class="primary-cell"><strong>{{ row.display_name }}</strong><code>{{ row.primary_value }}</code></div>
                </template>
              </el-table-column>
              <el-table-column label="类型" width="170">
                <template #default="{ row }">
                  <div class="object-source-cell">
                    <span>{{ row.object_type_name }}</span>
                    <div class="source-tags">
                      <el-tooltip
                        v-if="row.source_kind === 'database' && row.last_synced_at"
                        :content="`同步于 ${formatDateTime(row.last_synced_at)}`"
                        placement="top"
                      >
                        <el-tag size="small" type="success" effect="plain">业务库</el-tag>
                      </el-tooltip>
                      <el-tag v-else-if="row.source_kind === 'database'" size="small" type="success" effect="plain">业务库</el-tag>
                      <el-tag v-else size="small" type="info" effect="plain">本地</el-tag>
                      <el-tag v-if="hasLocalOverlay(row)" size="small" type="warning" effect="plain">本地覆盖</el-tag>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="属性" min-width="420">
                <template #default="{ row }">
                  <el-tooltip
                    v-if="objectPropertyEntries(row.properties).length"
                    placement="top-start"
                    effect="light"
                    :show-after="180"
                    popper-class="object-property-tooltip"
                  >
                    <div class="audit-field-list object-property-list">
                      <div v-for="entry in objectPropertyPreview(row.properties)" :key="entry.key" class="audit-field-row">
                        <span :class="['audit-field-key', `tone-${entry.tone}`]">{{ entry.key }}</span>
                        <span class="audit-field-value object-property-value">{{ formatStateValue(entry.value, entry.key) }}</span>
                      </div>
                      <span v-if="hiddenPropertyCount(row.properties)" class="object-property-more">+{{ hiddenPropertyCount(row.properties) }} 项</span>
                    </div>
                    <template #content>
                      <div class="audit-field-list object-property-tooltip-list">
                        <div v-for="entry in objectPropertyEntries(row.properties)" :key="entry.key" class="audit-field-row">
                          <span :class="['audit-field-key', `tone-${entry.tone}`]">{{ entry.key }}</span>
                          <span class="audit-field-value">{{ formatStateValue(entry.value, entry.key) }}</span>
                        </div>
                      </div>
                    </template>
                  </el-tooltip>
                  <span v-else class="audit-empty">-</span>
                </template>
              </el-table-column>
              <el-table-column label="版本" width="80"><template #default="{ row }">v{{ row.version }}</template></el-table-column>
              <el-table-column label="操作" width="120" fixed="right" align="center" header-align="center">
                <template #default="{ row }">
                  <div class="table-actions">
                    <el-tooltip v-if="canManage" content="编辑" placement="top">
                      <el-button class="table-action-btn" text :icon="Edit" aria-label="编辑对象实例" @click="openObjectInstanceDialog(row)" />
                    </el-tooltip>
                    <el-tooltip v-if="canManage" content="删除" placement="top">
                      <el-button class="table-action-btn is-danger" text type="danger" :icon="Delete" aria-label="删除对象实例" @click="removeObject(row)" />
                    </el-tooltip>
                  </div>
                </template>
              </el-table-column>
            </el-table>
            <div class="instance-pagination">
              <span>{{ instanceTotalLabel }}</span>
              <el-pagination
                v-model:current-page="instancePage"
                v-model:page-size="instancePageSize"
                :total="instanceTotal"
                :page-sizes="instancePageSizes"
                layout="sizes, prev, pager, next"
                background
                @current-change="handleInstancePageChange"
                @size-change="handleInstancePageSizeChange"
              />
            </div>
          </section>
        </el-tab-pane>

        <el-tab-pane label="决策活动" name="activity">
          <section class="table-section">
            <div class="section-toolbar">
              <div><strong>动作与决策审计</strong><span>{{ actionRuns.length }} 条</span></div>
              <el-button :icon="Refresh" @click="loadActivity">刷新</el-button>
            </div>
            <el-table :data="actionRuns" height="calc(100vh - 312px)">
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="runStatusType(row.status)">{{ runStatusLabel(row.status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="action_name" label="动作" min-width="160" />
              <el-table-column prop="target_name" label="目标对象" min-width="160" />
              <el-table-column label="执行人" width="130">
                <template #default="{ row }">{{ row.user_name || row.username || '-' }}</template>
              </el-table-column>
              <el-table-column label="决策上下文" min-width="320">
                <template #default="{ row }">
                  <div v-if="decisionContextEntries(row.decision_context).length" class="audit-field-list">
                    <div v-for="entry in decisionContextEntries(row.decision_context)" :key="entry.key" class="audit-field-row">
                      <span :class="['audit-field-key', `tone-${entry.tone}`]">{{ entry.key }}</span>
                        <span class="audit-field-value">{{ formatStateValue(entry.value, entry.key) }}</span>
                    </div>
                  </div>
                  <span v-else class="audit-empty">-</span>
                </template>
              </el-table-column>
              <el-table-column label="状态变化" min-width="460">
                <template #default="{ row }">
                  <div v-if="stateChangeEntries(row.before_state, row.after_state).length" class="state-change-list">
                    <div v-for="change in stateChangeEntries(row.before_state, row.after_state)" :key="change.key" class="state-change-row">
                      <span :class="['audit-field-key', `tone-${change.tone}`]">{{ change.key }}</span>
                      <div class="state-change-values">
                        <span class="state-value">{{ formatStateValue(change.before, change.key) }}</span>
                        <span class="state-arrow">→</span>
                        <span class="state-value is-after">{{ formatStateValue(change.after, change.key) }}</span>
                      </div>
                    </div>
                  </div>
                  <span v-else class="audit-empty">-</span>
                </template>
              </el-table-column>
              <el-table-column label="执行时间" width="180">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-dialog v-model="objectTypeDialog" :title="objectTypeForm.id ? '编辑对象类型' : '新建对象类型'" width="900px">
      <el-form :model="objectTypeForm" label-position="top">
        <div class="form-grid three">
          <el-form-item label="对象标识" required><el-input v-model="objectTypeForm.object_key" placeholder="如 WorkOrder" /></el-form-item>
          <el-form-item label="业务名称" required><el-input v-model="objectTypeForm.name" /></el-form-item>
          <el-form-item label="状态"><el-select v-model="objectTypeForm.status"><el-option label="草稿" value="draft" /><el-option label="生效" value="active" /><el-option label="废弃" value="deprecated" /></el-select></el-form-item>
        </div>
        <el-form-item label="业务定义"><el-input v-model="objectTypeForm.description" type="textarea" :rows="2" /></el-form-item>
        <div class="form-grid two">
          <el-form-item label="主属性" required><el-select v-model="objectTypeForm.primary_property"><el-option v-for="p in objectTypeForm.properties" :key="p.property_key" :label="p.name || p.property_key" :value="p.property_key" /></el-select></el-form-item>
          <el-form-item label="显示属性"><el-select v-model="objectTypeForm.display_property" clearable><el-option v-for="p in objectTypeForm.properties" :key="p.property_key" :label="p.name || p.property_key" :value="p.property_key" /></el-select></el-form-item>
        </div>
        <div class="form-grid two">
          <el-form-item label="业务库同步"><el-switch v-model="objectTypeForm.sync_enabled" /></el-form-item>
          <el-form-item label="默认分页大小"><el-input-number v-model="objectTypeForm.sync_limit" :min="1" :max="1000" controls-position="right" /></el-form-item>
        </div>
        <el-form-item v-if="objectTypeForm.sync_enabled" label="只读同步 SELECT" required>
          <el-input
            v-model="objectTypeForm.source_query"
            class="source-query-input"
            type="textarea"
            :rows="8"
            spellcheck="false"
            placeholder="SELECT physical_column AS property_key FROM business_table ORDER BY primary_key DESC"
          />
        </el-form-item>
        <div class="subsection-title"><strong>属性</strong><el-button text type="primary" :icon="Plus" @click="addProperty">添加属性</el-button></div>
        <div class="builder-list">
          <div v-for="(property, index) in objectTypeForm.properties" :key="index" class="builder-row property-builder">
            <el-input v-model="property.property_key" placeholder="属性标识" />
            <el-input v-model="property.name" placeholder="业务名称" />
            <el-select v-model="property.data_type"><el-option v-for="item in propertyTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select>
            <el-checkbox v-model="property.required">必填</el-checkbox>
            <el-checkbox v-model="property.unique">唯一</el-checkbox>
            <el-button text type="danger" :icon="Delete" title="移除" @click="removeProperty(index)" />
          </div>
        </div>
      </el-form>
      <template #footer><el-button @click="objectTypeDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveObjectType">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="linkTypeDialog" :title="linkTypeForm.id ? '编辑关系类型' : '新建关系类型'" width="720px">
      <el-form :model="linkTypeForm" label-position="top">
        <div class="form-grid two"><el-form-item label="关系标识" required><el-input v-model="linkTypeForm.link_key" /></el-form-item><el-form-item label="关系名称" required><el-input v-model="linkTypeForm.name" /></el-form-item></div>
        <div class="form-grid two"><el-form-item label="起点对象" required><el-select v-model="linkTypeForm.source_object_key"><el-option v-for="item in objectTypes" :key="item.id" :label="item.name" :value="item.object_key" /></el-select></el-form-item><el-form-item label="终点对象" required><el-select v-model="linkTypeForm.target_object_key"><el-option v-for="item in objectTypes" :key="item.id" :label="item.name" :value="item.object_key" /></el-select></el-form-item></div>
        <div class="form-grid two"><el-form-item label="关系基数"><el-select v-model="linkTypeForm.cardinality"><el-option v-for="item in cardinalities" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item><el-form-item label="状态"><el-select v-model="linkTypeForm.status"><el-option label="草稿" value="draft" /><el-option label="生效" value="active" /><el-option label="废弃" value="deprecated" /></el-select></el-form-item></div>
        <el-form-item label="业务定义"><el-input v-model="linkTypeForm.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="linkTypeDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveLinkType">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="actionTypeDialog" :title="actionTypeForm.id ? '编辑动作类型' : '新建动作类型'" width="960px">
      <el-form :model="actionTypeForm" label-position="top">
        <div class="form-grid three"><el-form-item label="动作标识" required><el-input v-model="actionTypeForm.action_key" /></el-form-item><el-form-item label="动作名称" required><el-input v-model="actionTypeForm.name" /></el-form-item><el-form-item label="目标对象" required><el-select v-model="actionTypeForm.target_object_key"><el-option v-for="item in objectTypes" :key="item.id" :label="item.name" :value="item.object_key" /></el-select></el-form-item></div>
        <el-form-item label="业务定义"><el-input v-model="actionTypeForm.description" type="textarea" :rows="2" /></el-form-item>
        <div class="form-grid three"><el-form-item label="授权角色"><el-select v-model="actionTypeForm.allowed_roles" multiple><el-option label="管理员" value="admin" /><el-option label="业务用户" value="user" /></el-select></el-form-item><el-form-item label="状态"><el-select v-model="actionTypeForm.status"><el-option label="草稿" value="draft" /><el-option label="生效" value="active" /><el-option label="废弃" value="deprecated" /></el-select></el-form-item><el-form-item label="审批单号要求"><el-switch v-model="actionTypeForm.requires_approval" active-text="需要审批单号" inactive-text="不要求审批单号" /></el-form-item></div>
        <div class="subsection-title"><strong>动作参数</strong><el-button text type="primary" :icon="Plus" @click="addActionParameter">添加参数</el-button></div>
        <div class="builder-list"><div v-for="(parameter, index) in actionTypeForm.parameters" :key="index" class="builder-row parameter-builder"><el-input v-model="parameter.parameter_key" placeholder="参数标识" /><el-input v-model="parameter.name" placeholder="业务名称" /><el-select v-model="parameter.data_type"><el-option v-for="item in propertyTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select><el-input v-model="parameter.options_text" placeholder="选项，逗号分隔" /><el-checkbox v-model="parameter.required">必填</el-checkbox><el-button text type="danger" :icon="Delete" @click="actionTypeForm.parameters.splice(index, 1)" /></div></div>
        <div class="subsection-title"><strong>前置条件</strong><el-button text type="primary" :icon="Plus" @click="addPrecondition">添加条件</el-button></div>
        <div class="builder-list"><div v-for="(condition, index) in actionTypeForm.preconditions" :key="index" class="builder-row condition-builder"><el-select v-model="condition.property" placeholder="对象属性"><el-option v-for="p in targetProperties" :key="p.property_key" :label="p.name" :value="p.property_key" /></el-select><el-select v-model="condition.operator"><el-option v-for="item in operators" :key="item.value" :label="item.label" :value="item.value" /></el-select><el-input v-model="condition.value_text" placeholder="期望值或 $param.x" /><el-input v-model="condition.message" placeholder="不满足时提示" /><el-button text type="danger" :icon="Delete" @click="actionTypeForm.preconditions.splice(index, 1)" /></div></div>
        <div class="subsection-title"><strong>状态效果</strong><el-button text type="primary" :icon="Plus" @click="addEffect">添加效果</el-button></div>
        <div class="builder-list"><div v-for="(effect, index) in actionTypeForm.effects" :key="index" class="builder-row effect-builder"><el-select v-model="effect.property" placeholder="写入属性"><el-option v-for="p in targetProperties" :key="p.property_key" :label="p.name" :value="p.property_key" /></el-select><el-input v-model="effect.value_text" placeholder="常量、$param.x、$now、$user.name" /><el-button text type="danger" :icon="Delete" @click="actionTypeForm.effects.splice(index, 1)" /></div></div>
      </el-form>
      <template #footer><el-button @click="actionTypeDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveActionType">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="objectInstanceDialog" :title="objectForm.id ? '编辑对象实例' : '新建对象实例'" width="700px">
      <el-form label-position="top">
        <el-form-item label="对象类型" required><el-select v-model="objectForm.object_type_id" :disabled="Boolean(objectForm.id)" @change="resetObjectProperties"><el-option v-for="item in objectTypes" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <div class="form-grid two">
          <el-form-item v-for="property in selectedInstanceType?.properties || []" :key="property.property_key" :label="property.name" :required="property.required">
            <el-switch v-if="property.data_type === 'boolean'" v-model="objectForm.properties[property.property_key]" />
            <el-input-number v-else-if="property.data_type === 'integer' || property.data_type === 'number'" v-model="objectForm.properties[property.property_key]" :precision="property.data_type === 'integer' ? 0 : undefined" controls-position="right" />
            <el-date-picker v-else-if="property.data_type === 'date'" v-model="objectForm.properties[property.property_key]" type="date" value-format="YYYY-MM-DD" />
            <el-date-picker v-else-if="property.data_type === 'datetime'" v-model="objectForm.properties[property.property_key]" type="datetime" format="YYYY-MM-DD HH:mm:ss" value-format="YYYY-MM-DDTHH:mm:ss" />
            <el-input v-else v-model="objectForm.properties[property.property_key]" :type="property.data_type === 'text' || property.data_type === 'json' ? 'textarea' : 'text'" :rows="2" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer><el-button @click="objectInstanceDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveObjectInstance">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="linkInstanceDialog" title="建立对象关系" width="620px">
      <el-form label-position="top"><el-form-item label="关系类型" required><el-select v-model="linkForm.link_type_id" @change="handleLinkInstanceTypeChange"><el-option v-for="item in linkTypes" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item><el-form-item label="起点对象" required><el-select v-model="linkForm.source_object_id" filterable :loading="objectChoicesLoading"><el-option v-for="item in linkSourceObjects" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item><el-form-item label="终点对象" required><el-select v-model="linkForm.target_object_id" filterable :loading="objectChoicesLoading"><el-option v-for="item in linkTargetObjects" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item></el-form>
      <template #footer><el-button @click="linkInstanceDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveLinkInstance">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="executeDialog" :title="`执行 · ${executeAction?.name || ''}`" width="620px">
      <el-form label-position="top"><el-form-item label="目标对象" required><el-select v-model="executeForm.target_object_id" filterable :loading="objectChoicesLoading"><el-option v-for="item in executeTargets" :key="item.id" :label="`${item.display_name} · ${item.primary_value}`" :value="item.id" /></el-select></el-form-item><el-form-item v-for="parameter in executeAction?.parameters || []" :key="parameter.parameter_key" :label="parameter.name" :required="parameter.required"><el-select v-if="parameter.options?.length" v-model="executeForm.parameters[parameter.parameter_key]"><el-option v-for="option in parameter.options" :key="String(option)" :label="String(option)" :value="option" /></el-select><el-switch v-else-if="parameter.data_type === 'boolean'" v-model="executeForm.parameters[parameter.parameter_key]" /><el-input-number v-else-if="parameter.data_type === 'integer' || parameter.data_type === 'number'" v-model="executeForm.parameters[parameter.parameter_key]" :precision="parameter.data_type === 'integer' ? 0 : undefined" /><el-input v-else v-model="executeForm.parameters[parameter.parameter_key]" /></el-form-item><el-form-item v-if="executeAction?.requires_approval" label="审批单号" required><el-input v-model="executeForm.approval_reference" /></el-form-item><el-form-item label="决策说明"><el-input v-model="executeForm.reason" type="textarea" :rows="3" /></el-form-item></el-form>
      <template #footer><el-button @click="executeDialog = false">取消</el-button><el-button type="primary" :loading="saving" :icon="VideoPlay" @click="runAction">执行动作</el-button></template>
    </el-dialog>

    <el-drawer v-model="validationDrawer" title="本体校验" size="520px">
      <div v-if="validationResult" class="validation-result">
        <el-result :icon="validationResult.valid ? 'success' : 'error'" :title="validationResult.valid ? '校验通过' : '校验未通过'" :sub-title="`${validationResult.errors.length} 个错误，${validationResult.warnings.length} 个提醒`" />
        <section v-if="validationResult.errors.length"><h4>错误</h4><div v-for="(item, index) in validationResult.errors" :key="index" class="validation-item error"><code>{{ item.asset }}</code><span>{{ item.message }}</span></div></section>
        <section v-if="validationResult.warnings.length"><h4>提醒</h4><div v-for="(item, index) in validationResult.warnings" :key="index" class="validation-item warning"><code>{{ item.asset }}</code><span>{{ item.message }}</span></div></section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  deleteOntologyActionType,
  deleteOntologyLinkType,
  deleteOntologyObject,
  deleteOntologyObjectType,
  executeOntologyAction,
  exportOntologyBundle,
  fetchOntologyDomains,
  fetchOntologyActionRuns,
  fetchOntologyActionTypes,
  fetchOntologyLinkTypes,
  fetchOntologyObjects,
  fetchOntologyObjectTypes,
  fetchOntologyReleases,
  fetchOntologySummary,
  importOntologyBundle,
  publishOntology,
  saveOntologyActionType,
  saveOntologyLink,
  saveOntologyLinkType,
  saveOntologyObject,
  saveOntologyObjectType,
  syncOntologyObjects,
  validateOntology,
  type OntologyActionRun,
  type OntologyActionType,
  type OntologyLinkType,
  type OntologyObject,
  type OntologyObjectType,
  type OntologyProperty,
  type OntologyPropertyType,
  type OntologySummary,
  type SemanticDomain,
} from '../api'
import { authState, isAdmin } from '../stores/auth'
import { formatDateTime, isDateTimeField, isDateTimeValue } from '../utils/datetime'
import { ArrowRight, CircleCheck, Connection, Delete, Download, Edit, FolderOpened, Plus, Refresh, Upload, VideoPlay } from '@element-plus/icons-vue'

const domains = ref<SemanticDomain[]>([])
const domainId = ref<number | null>(null)
const summary = ref<OntologySummary | null>(null)
const objectTypes = ref<OntologyObjectType[]>([])
const linkTypes = ref<OntologyLinkType[]>([])
const actionTypes = ref<OntologyActionType[]>([])
const objects = ref<OntologyObject[]>([])
const allObjects = ref<OntologyObject[]>([])
const actionRuns = ref<OntologyActionRun[]>([])
const releases = ref<Record<string, unknown>[]>([])
const activeTab = ref('graph')
const instanceTypeId = ref<number | undefined>()
const instancePage = ref(1)
const instancePageSize = ref(200)
const instanceTotal = ref(0)
const instanceTotalIsExact = ref(true)
const syncing = ref(false)
const objectChoicesLoading = ref(false)
const loading = ref(false)
const saving = ref(false)
const graphElement = ref<HTMLElement>()
const importInput = ref<HTMLInputElement>()
let graph: echarts.ECharts | null = null
let graphResizeObserver: ResizeObserver | null = null
let observedGraphElement: HTMLElement | null = null
let graphSize = { width: 0, height: 0 }
let resizeFrame: number | null = null
let instanceRequestId = 0
let objectChoiceRequestId = 0
let domainInitialized = false

const INSTANCE_CHOICE_LIMIT = 200

const currentDomain = computed(() => domains.value.find((item) => item.id === domainId.value))
const activeInstanceType = computed(() => objectTypes.value.find((item) => item.id === instanceTypeId.value))
const canManage = computed(() => isAdmin())
const currentRole = computed(() => authState.currentUser?.role || 'user')
const instancePageSizes = computed(() => [...new Set([20, 50, 100, 200, 500, 1000, instancePageSize.value])].sort((a, b) => a - b))
const instanceTotalLabel = computed(() => instanceTotalIsExact.value ? `共 ${instanceTotal.value} 条` : `至少 ${instanceTotal.value} 条`)
const metrics = computed(() => [
  { label: '对象类型', value: summary.value?.counts.object_types || 0, icon: 'Box' },
  { label: '关系类型', value: summary.value?.counts.link_types || 0, icon: 'Connection' },
  { label: '业务动作', value: summary.value?.counts.action_types || 0, icon: 'Operation' },
  { label: '对象实例', value: summary.value?.counts.source_objects || summary.value?.counts.objects || 0, icon: 'DataBoard' },
  { label: '决策活动', value: summary.value?.counts.action_runs || 0, icon: 'Clock' },
])

const propertyTypes: Array<{ value: OntologyPropertyType; label: string }> = [
  { value: 'string', label: '短文本' }, { value: 'text', label: '长文本' },
  { value: 'integer', label: '整数' }, { value: 'number', label: '数字' },
  { value: 'boolean', label: '布尔值' }, { value: 'date', label: '日期' },
  { value: 'datetime', label: '时间' }, { value: 'json', label: 'JSON' },
]
const cardinalities = [
  { value: 'one_to_one', label: '一对一' }, { value: 'one_to_many', label: '一对多' },
  { value: 'many_to_one', label: '多对一' }, { value: 'many_to_many', label: '多对多' },
]
const operators = [
  { value: 'eq', label: '等于' }, { value: 'ne', label: '不等于' },
  { value: 'in', label: '属于' }, { value: 'not_in', label: '不属于' },
  { value: 'gt', label: '大于' }, { value: 'gte', label: '大于等于' },
  { value: 'lt', label: '小于' }, { value: 'lte', label: '小于等于' },
  { value: 'exists', label: '存在' },
]

const objectTypeDialog = ref(false)
const objectTypeForm = reactive<any>(emptyObjectType())
const linkTypeDialog = ref(false)
const linkTypeForm = reactive<any>(emptyLinkType())
const actionTypeDialog = ref(false)
const actionTypeForm = reactive<any>(emptyActionType())
const objectInstanceDialog = ref(false)
const objectForm = reactive<any>({ id: null, object_type_id: null, properties: {} })
const linkInstanceDialog = ref(false)
const linkForm = reactive<any>({ link_type_id: null, source_object_id: null, target_object_id: null })
const executeDialog = ref(false)
const executeAction = ref<OntologyActionType | null>(null)
const executeForm = reactive<any>({ target_object_id: null, parameters: {}, approval_reference: '', reason: '' })
const validationDrawer = ref(false)
const validationResult = ref<any>(null)

const targetProperties = computed<OntologyProperty[]>(() => objectTypes.value.find((item) => item.object_key === actionTypeForm.target_object_key)?.properties || [])
const selectedInstanceType = computed(() => objectTypes.value.find((item) => item.id === objectForm.object_type_id))
const selectedLinkType = computed(() => linkTypes.value.find((item) => item.id === linkForm.link_type_id))
const linkSourceObjects = computed(() => allObjects.value.filter((item) => item.object_type_key === selectedLinkType.value?.source_object_key))
const linkTargetObjects = computed(() => allObjects.value.filter((item) => item.object_type_key === selectedLinkType.value?.target_object_key))
const executeTargets = computed(() => allObjects.value.filter((item) => item.object_type_key === executeAction.value?.target_object_key))
const PROPERTY_PREVIEW_LIMIT = 4

function canExecuteAction(action: OntologyActionType) {
  return action.status === 'active' && (canManage.value || action.allowed_roles?.includes(currentRole.value as 'admin' | 'user'))
}

function emptyObjectType() { return { id: null, object_key: '', name: '', description: '', primary_property: '', display_property: '', sync_enabled: false, source_query: '', sync_limit: 200, status: 'draft', properties: [] as any[] } }
function emptyLinkType() { return { id: null, link_key: '', name: '', source_object_key: '', target_object_key: '', cardinality: 'many_to_many', description: '', status: 'draft' } }
function emptyActionType() { return { id: null, action_key: '', name: '', target_object_key: '', description: '', parameters: [] as any[], preconditions: [] as any[], effects: [] as any[], allowed_roles: ['admin'], requires_approval: false, status: 'draft' } }
function replaceReactive(target: any, value: any) { Object.keys(target).forEach((key) => delete target[key]); Object.assign(target, value) }
function typeLabel(type: string) { return propertyTypes.find((item) => item.value === type)?.label || type }
function cardinalityLabel(value: string) { return cardinalities.find((item) => item.value === value)?.label || value }
function statusLabel(value: string) { return ({ draft: '草稿', active: '生效', deprecated: '废弃' } as any)[value] || value }
function statusType(value: string) { return value === 'active' ? 'success' : value === 'deprecated' ? 'info' : 'warning' }
function syncStatusLabel(row: OntologyObjectType) {
  if (!row.last_sync_status) return '待同步'
  return ({ succeeded: '同步成功', partial: '部分成功', failed: '同步失败' } as Record<string, string>)[row.last_sync_status] || row.last_sync_status
}
function syncStatusType(status: OntologyObjectType['last_sync_status']) {
  if (status === 'succeeded') return 'success'
  if (status === 'partial') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}
function runStatusLabel(value: string) { return ({ running: '执行中', succeeded: '成功', failed: '失败' } as any)[value] || value }
function runStatusType(value: string) { return value === 'succeeded' ? 'success' : value === 'failed' ? 'danger' : 'warning' }
function hasLocalOverlay(row: OntologyObject) { return Object.keys(row.overlay_properties || {}).length > 0 }
function formatStateValue(value: unknown, key = '') {
  if (value === undefined || value === null) return '未设置'
  if (isDateTimeField(key) || isDateTimeValue(value)) return formatDateTime(value, '未设置')
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}
function auditFieldTone(key: string) {
  const normalized = key.toLowerCase()
  if (normalized.endsWith('_status') || normalized.endsWith('_state') || normalized === 'status') return 'status'
  if (isDateTimeField(normalized) || normalized.includes('date')) return 'time'
  if (/(amount|principal|balance|rate|count|days|term|score|quantity|qty)/.test(normalized)) return 'number'
  if (/(reason|note|question|description|message)/.test(normalized)) return 'text'
  if (/(reference|_id$|_no$|_key$)/.test(normalized)) return 'reference'
  if (/(strategy|type|grade|bucket|channel)/.test(normalized)) return 'category'
  return 'default'
}
function decisionContextEntries(value: Record<string, unknown> | undefined) {
  return Object.entries(value || {}).map(([key, item]) => ({ key, value: item, tone: auditFieldTone(key) }))
}
function objectPropertyEntries(value: Record<string, unknown> | undefined) {
  return Object.entries(value || {}).map(([key, item]) => ({ key, value: item, tone: auditFieldTone(key) }))
}
function objectPropertyPreview(value: Record<string, unknown> | undefined) {
  return objectPropertyEntries(value).slice(0, PROPERTY_PREVIEW_LIMIT)
}
function hiddenPropertyCount(value: Record<string, unknown> | undefined) {
  return Math.max(objectPropertyEntries(value).length - PROPERTY_PREVIEW_LIMIT, 0)
}
function stateChangeEntries(before: any, after: any) {
  const oldValues = before?.properties || {}; const newValues = after?.properties || {}
  const keys = new Set([...Object.keys(oldValues), ...Object.keys(newValues)])
  return [...keys]
    .filter((key) => JSON.stringify(oldValues[key]) !== JSON.stringify(newValues[key]))
    .map((key) => ({ key, before: oldValues[key], after: newValues[key], tone: auditFieldTone(key) }))
}
function parseValue(value: string) {
  const text = String(value ?? '').trim(); if (!text) return ''
  if (text.startsWith('$')) return text
  if (text === 'true') return true; if (text === 'false') return false; if (text === 'null') return null
  if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text)
  if ((text.startsWith('[') && text.endsWith(']')) || (text.startsWith('{') && text.endsWith('}'))) { try { return JSON.parse(text) } catch { return text } }
  return text
}
function errorMessage(error: any) { return error?.response?.data?.detail?.message || error?.response?.data?.detail || error?.message || '操作失败' }

async function loadDomains() { domains.value = await fetchOntologyDomains(); if (!domainId.value && domains.value.length) domainId.value = domains.value[0].id }
function selectDefaultInstanceType() {
  const current = objectTypes.value.find((item) => item.id === instanceTypeId.value)
  if (current) return current
  const next = objectTypes.value.find((item) => item.sync_enabled) || objectTypes.value[0]
  instanceTypeId.value = next?.id
  instancePage.value = 1
  instancePageSize.value = Math.min(Math.max(Number(next?.sync_limit || 200), 1), 1000)
  return next
}

async function refreshAll() {
  if (!domainId.value) return
  loading.value = true
  try {
    const id = domainId.value
    const [nextSummary, nextObjects, nextLinks, nextActions, nextRuns, nextReleases] = await Promise.all([
      fetchOntologySummary(id), fetchOntologyObjectTypes(id), fetchOntologyLinkTypes(id),
      fetchOntologyActionTypes(id), fetchOntologyActionRuns(id), fetchOntologyReleases(id),
    ])
    summary.value = nextSummary; objectTypes.value = nextObjects; linkTypes.value = nextLinks
    actionTypes.value = nextActions; actionRuns.value = nextRuns; releases.value = nextReleases
    selectDefaultInstanceType()
    if (activeTab.value === 'instances') await syncAndLoadInstances(false)
    await nextTick(); renderGraph()
  } catch (error) { ElMessage.error(String(errorMessage(error))) } finally { loading.value = false }
}

async function loadLocalInstancePage(requestId: number) {
  if (!domainId.value || !instanceTypeId.value) return
  const pageSize = Math.min(Math.max(instancePageSize.value, 1), 1000)
  const offset = (instancePage.value - 1) * pageSize
  const pageObjects = await fetchOntologyObjects(domainId.value, instanceTypeId.value, pageSize, offset)
  if (requestId !== instanceRequestId) return
  if (!pageObjects.length && instancePage.value > 1) {
    instancePage.value -= 1
    await loadLocalInstancePage(requestId)
    return
  }
  objects.value = pageObjects
  const mayHaveMore = pageObjects.length === pageSize
  instanceTotal.value = offset + pageObjects.length + (mayHaveMore ? 1 : 0)
  instanceTotalIsExact.value = !mayHaveMore
}

function applySyncStatus(type: OntologyObjectType, result: { read: number; total: number; errors: string[] }) {
  const errors = result.errors || []
  type.last_sync_status = errors.length ? (result.read > 0 ? 'partial' : 'failed') : 'succeeded'
  type.last_sync_count = result.read || 0
  type.last_sync_total = result.total || 0
  type.last_sync_error = errors.join('；') || null
  type.last_synced_at = new Date().toISOString()
  if (summary.value) {
    summary.value.counts.source_objects = objectTypes.value
      .filter((item) => item.sync_enabled)
      .reduce((total, item) => total + Number(item.last_sync_total || 0), 0)
  }
}

async function syncAndLoadInstances(showSuccess = false) {
  const id = domainId.value
  const objectType = activeInstanceType.value
  if (!id || !objectType) {
    objects.value = []
    instanceTotal.value = 0
    return
  }
  const requestId = ++instanceRequestId
  syncing.value = true
  try {
    if (!objectType.sync_enabled) {
      await loadLocalInstancePage(requestId)
      return
    }
    const result = await syncOntologyObjects(id, {
      object_type_id: objectType.id,
      page: instancePage.value,
      page_size: instancePageSize.value,
      sync_links: true,
    })
    if (requestId !== instanceRequestId) return
    const typeResult = result.types.find((item) => item.object_type_id === objectType.id) || result.types[0]
    objects.value = typeResult?.objects || result.objects || []
    instanceTotal.value = typeResult?.total ?? result.total ?? objects.value.length
    instanceTotalIsExact.value = true
    if (typeResult) applySyncStatus(objectType, typeResult)
    if (typeResult?.errors?.length) {
      ElMessage.warning(typeResult.errors[0])
    } else if (showSuccess) {
      const changed = (typeResult?.created || 0) + (typeResult?.updated || 0)
      ElMessage.success(`已同步 ${typeResult?.read || objects.value.length} 条，变更 ${changed} 条`)
    }
  } catch (error) {
    if (requestId !== instanceRequestId) return
    try { await loadLocalInstancePage(requestId) } catch { objects.value = []; instanceTotal.value = 0 }
    ElMessage.error(String(errorMessage(error)))
  } finally {
    if (requestId === instanceRequestId) syncing.value = false
  }
}

async function handleInstanceTypeChange() {
  instancePage.value = 1
  instancePageSize.value = Math.min(Math.max(Number(activeInstanceType.value?.sync_limit || 200), 1), 1000)
  await syncAndLoadInstances(false)
}

async function handleInstancePageChange(page: number) {
  instancePage.value = page
  await syncAndLoadInstances(false)
}

async function handleInstancePageSizeChange(pageSize: number) {
  instancePageSize.value = pageSize
  instancePage.value = 1
  await syncAndLoadInstances(false)
}

async function loadActivity() { if (domainId.value) actionRuns.value = await fetchOntologyActionRuns(domainId.value) }
async function handleTabChange(name: any) {
  if (name === 'graph') nextTick(renderGraph)
  if (name === 'instances') {
    selectDefaultInstanceType()
    await syncAndLoadInstances(false)
  }
}

function scheduleGraphResize() {
  if (resizeFrame !== null) cancelAnimationFrame(resizeFrame)
  resizeFrame = requestAnimationFrame(() => {
    resizeFrame = null
    const element = graphElement.value
    if (!element || activeTab.value !== 'graph') return
    const width = element.clientWidth
    const height = element.clientHeight
    if (!width || !height) return
    if (width === graphSize.width && height === graphSize.height) {
      graph?.resize()
      return
    }
    renderGraph()
  })
}

function observeGraphElement() {
  const element = graphElement.value
  if (!element || observedGraphElement === element || typeof ResizeObserver === 'undefined') return
  graphResizeObserver?.disconnect()
  graphResizeObserver = new ResizeObserver(scheduleGraphResize)
  graphResizeObserver.observe(element)
  observedGraphElement = element
}

function renderGraph() {
  observeGraphElement()
  const element = graphElement.value
  if (!element || activeTab.value !== 'graph') return
  const width = element.clientWidth
  const height = element.clientHeight
  if (!width || !height) return
  const sizeChanged = graphSize.width > 0 && (graphSize.width !== width || graphSize.height !== height)
  if (sizeChanged && graph) {
    graph.dispose()
    graph = null
  }
  graph ||= echarts.init(graphElement.value)
  graph.resize({ width, height })
  const nodes = objectTypes.value.map((item) => ({ id: item.object_key, name: item.name, value: `${item.object_key}\n${item.properties.length} 个属性`, symbolSize: 78, category: 0 }))
  actionTypes.value.forEach((item) => nodes.push({ id: `action:${item.action_key}`, name: item.name, value: item.action_key, symbolSize: 58, category: 1 } as any))
  const edges: any[] = linkTypes.value.map((item) => ({ source: item.source_object_key, target: item.target_object_key, name: item.name }))
  actionTypes.value.forEach((item) => edges.push({ source: `action:${item.action_key}`, target: item.target_object_key, name: '作用于', lineStyle: { type: 'dashed' } }))
  graph.setOption({ tooltip: { formatter: (p: any) => p.dataType === 'edge' ? p.data.name : `${p.data.name}<br/>${p.data.value}` }, legend: [{ data: ['业务对象', '业务动作'], bottom: 12 }], series: [{ type: 'graph', layout: 'force', roam: true, draggable: true, top: 24, right: 24, bottom: 60, left: 24, categories: [{ name: '业务对象', itemStyle: { color: '#167c5a' } }, { name: '业务动作', itemStyle: { color: '#c36b18' } }], data: nodes, links: edges, label: { show: true, color: '#182230', fontSize: 13, position: 'bottom' }, edgeLabel: { show: true, formatter: (params: any) => params.data?.name || '', fontSize: 11, color: '#475467' }, lineStyle: { color: '#98a2b3', width: 1.5, curveness: 0.1 }, force: { initLayout: 'circular', repulsion: 360, edgeLength: 170, gravity: 0.08 }, emphasis: { focus: 'adjacency', lineStyle: { width: 3 } } }] }, true)
  graphSize = { width, height }
}

function addProperty() { objectTypeForm.properties.push({ property_key: '', name: '', data_type: 'string', required: false, unique: false, description: '', default_value: null, sort_order: objectTypeForm.properties.length }) }
function removeProperty(index: number) { objectTypeForm.properties.splice(index, 1) }
function openObjectTypeDialog(row?: OntologyObjectType) {
  const value = row ? { ...emptyObjectType(), ...JSON.parse(JSON.stringify(row)), source_query: row.source_query || '' } : emptyObjectType()
  replaceReactive(objectTypeForm, value)
  if (!row) addProperty()
  objectTypeDialog.value = true
}
async function saveObjectType() {
  if (!domainId.value || !objectTypeForm.object_key || !objectTypeForm.name || !objectTypeForm.primary_property) return ElMessage.warning('请完整填写对象标识、名称和主属性')
  const sourceQuery = String(objectTypeForm.source_query || '').trim()
  if (objectTypeForm.sync_enabled && !sourceQuery) return ElMessage.warning('启用业务库同步时必须配置只读 SELECT')
  const payload = { ...objectTypeForm, source_query: sourceQuery, sync_limit: Number(objectTypeForm.sync_limit || 200), domain_id: domainId.value }
  for (const key of ['last_sync_status', 'last_sync_count', 'last_sync_total', 'last_sync_error', 'last_synced_at']) delete payload[key]
  saving.value = true; try { await saveOntologyObjectType(domainId.value, payload); ElMessage.success('对象类型已保存'); objectTypeDialog.value = false; await refreshAll() } catch (error) { ElMessage.error(String(errorMessage(error))) } finally { saving.value = false }
}
async function removeObjectType(row: OntologyObjectType) { await ElMessageBox.confirm(`删除对象类型“${row.name}”将同时删除相关关系、动作和实例。`, '删除对象类型', { type: 'warning' }); await deleteOntologyObjectType(row.domain_id, row.id); ElMessage.success('已删除'); await refreshAll() }

function openLinkTypeDialog(row?: OntologyLinkType) { replaceReactive(linkTypeForm, row ? JSON.parse(JSON.stringify(row)) : { ...emptyLinkType(), source_object_key: objectTypes.value[0]?.object_key || '', target_object_key: objectTypes.value[1]?.object_key || objectTypes.value[0]?.object_key || '' }); linkTypeDialog.value = true }
async function saveLinkType() { if (!domainId.value || !linkTypeForm.link_key || !linkTypeForm.name) return ElMessage.warning('请完整填写关系标识和名称'); saving.value = true; try { await saveOntologyLinkType(domainId.value, { ...linkTypeForm, domain_id: domainId.value }); ElMessage.success('关系类型已保存'); linkTypeDialog.value = false; await refreshAll() } catch (error) { ElMessage.error(String(errorMessage(error))) } finally { saving.value = false } }
async function removeLinkType(row: OntologyLinkType) { await ElMessageBox.confirm(`删除关系类型“${row.name}”？`, '删除关系', { type: 'warning' }); await deleteOntologyLinkType(row.domain_id, row.id); await refreshAll() }

function openActionTypeDialog(row?: OntologyActionType) {
  const value: any = row ? JSON.parse(JSON.stringify(row)) : { ...emptyActionType(), target_object_key: objectTypes.value[0]?.object_key || '' }
  value.parameters = (value.parameters || []).map((item: any) => ({ ...item, options_text: (item.options || []).join(',') })); value.preconditions = (value.preconditions || []).map((item: any) => ({ ...item, value_text: typeof item.value === 'string' ? item.value : JSON.stringify(item.value) })); value.effects = (value.effects || []).map((item: any) => ({ ...item, value_text: typeof item.value === 'string' ? item.value : JSON.stringify(item.value) }))
  replaceReactive(actionTypeForm, value); actionTypeDialog.value = true
}
function addActionParameter() { actionTypeForm.parameters.push({ parameter_key: '', name: '', data_type: 'string', required: false, options_text: '', description: '' }) }
function addPrecondition() { actionTypeForm.preconditions.push({ property: targetProperties.value[0]?.property_key || '', operator: 'eq', value_text: '', message: '' }) }
function addEffect() { actionTypeForm.effects.push({ property: targetProperties.value[0]?.property_key || '', value_text: '' }) }
async function saveActionType() {
  if (!domainId.value || !actionTypeForm.action_key || !actionTypeForm.name || !actionTypeForm.target_object_key) return ElMessage.warning('请完整填写动作标识、名称和目标对象')
  const payload = { ...actionTypeForm, domain_id: domainId.value, parameters: actionTypeForm.parameters.map((item: any) => ({ parameter_key: item.parameter_key, name: item.name, data_type: item.data_type, required: item.required, options: String(item.options_text || '').split(',').map((x) => x.trim()).filter(Boolean), description: item.description || '' })), preconditions: actionTypeForm.preconditions.map((item: any) => ({ property: item.property, operator: item.operator, value: parseValue(item.value_text), message: item.message || '' })), effects: actionTypeForm.effects.map((item: any) => ({ property: item.property, value: parseValue(item.value_text) })) }
  saving.value = true; try { await saveOntologyActionType(domainId.value, payload); ElMessage.success('动作类型已保存'); actionTypeDialog.value = false; await refreshAll() } catch (error) { ElMessage.error(String(errorMessage(error))) } finally { saving.value = false }
}
async function removeActionType(row: OntologyActionType) { await ElMessageBox.confirm(`删除动作“${row.name}”？历史执行记录仍将保留。`, '删除动作', { type: 'warning' }); await deleteOntologyActionType(row.domain_id, row.id); await refreshAll() }

function openObjectInstanceDialog(row?: OntologyObject) { const value = row ? { id: row.id, object_type_id: row.object_type_id, properties: JSON.parse(JSON.stringify(row.properties)) } : { id: null, object_type_id: instanceTypeId.value || objectTypes.value[0]?.id || null, properties: {} }; replaceReactive(objectForm, value); if (!row) resetObjectProperties(); objectInstanceDialog.value = true }
function resetObjectProperties() { objectForm.properties = {}; for (const property of selectedInstanceType.value?.properties || []) if (property.default_value !== null && property.default_value !== undefined) objectForm.properties[property.property_key] = property.default_value }
async function saveObjectInstance() {
  if (!domainId.value || !selectedInstanceType.value) return ElMessage.warning('请选择对象类型')
  const properties = { ...objectForm.properties }; for (const property of selectedInstanceType.value.properties) if (property.data_type === 'json' && typeof properties[property.property_key] === 'string') { try { properties[property.property_key] = JSON.parse(String(properties[property.property_key])) } catch { return ElMessage.warning(`${property.name} 不是有效 JSON`) } }
  const primary = properties[selectedInstanceType.value.primary_property]; if (primary === undefined || primary === null || primary === '') return ElMessage.warning('请填写主属性')
  saving.value = true; try { await saveOntologyObject(domainId.value, { id: objectForm.id, domain_id: domainId.value, object_type_id: selectedInstanceType.value.id, primary_value: String(primary), properties, status: 'active' }); ElMessage.success('对象实例已保存'); objectInstanceDialog.value = false; await refreshAll() } catch (error) { ElMessage.error(String(errorMessage(error))) } finally { saving.value = false }
}
async function removeObject(row: OntologyObject) { await ElMessageBox.confirm(`删除对象“${row.display_name}”及其关系？`, '删除对象', { type: 'warning' }); await deleteOntologyObject(row.domain_id, row.id); await refreshAll() }

async function loadObjectChoices(objectKeys: string[]) {
  if (!domainId.value) return
  const typeIds = [...new Set(objectKeys)]
    .map((key) => objectTypes.value.find((item) => item.object_key === key)?.id)
    .filter((id): id is number => Boolean(id))
  const requestId = ++objectChoiceRequestId
  objectChoicesLoading.value = true
  try {
    const pages = await Promise.all(typeIds.map((typeId) => fetchOntologyObjects(domainId.value!, typeId, INSTANCE_CHOICE_LIMIT, 0)))
    if (requestId !== objectChoiceRequestId) return
    const byId = new Map<number, OntologyObject>()
    for (const item of [...objects.value, ...pages.flat()]) {
      if (typeIds.includes(item.object_type_id)) byId.set(item.id, item)
    }
    allObjects.value = [...byId.values()]
  } catch (error) {
    if (requestId === objectChoiceRequestId) ElMessage.error(String(errorMessage(error)))
  } finally {
    if (requestId === objectChoiceRequestId) objectChoicesLoading.value = false
  }
}

async function handleLinkInstanceTypeChange() {
  linkForm.source_object_id = null
  linkForm.target_object_id = null
  const linkType = selectedLinkType.value
  allObjects.value = []
  if (linkType) await loadObjectChoices([linkType.source_object_key, linkType.target_object_key])
}

async function openLinkInstanceDialog() {
  replaceReactive(linkForm, { link_type_id: linkTypes.value[0]?.id || null, source_object_id: null, target_object_id: null })
  linkInstanceDialog.value = true
  await handleLinkInstanceTypeChange()
}
async function saveLinkInstance() { if (!domainId.value || !linkForm.link_type_id || !linkForm.source_object_id || !linkForm.target_object_id) return ElMessage.warning('请选择关系和两端对象'); saving.value = true; try { await saveOntologyLink(domainId.value, { domain_id: domainId.value, ...linkForm, properties: {} }); ElMessage.success('对象关系已保存'); linkInstanceDialog.value = false; await refreshAll() } catch (error) { ElMessage.error(String(errorMessage(error))) } finally { saving.value = false } }

async function openExecuteDialog(action: OntologyActionType) {
  executeAction.value = action
  replaceReactive(executeForm, { target_object_id: null, parameters: {}, approval_reference: '', reason: '' })
  for (const parameter of action.parameters) if (parameter.data_type === 'boolean') executeForm.parameters[parameter.parameter_key] = false
  allObjects.value = []
  executeDialog.value = true
  await loadObjectChoices([action.target_object_key])
}
async function runAction() { if (!domainId.value || !executeAction.value || !executeForm.target_object_id) return ElMessage.warning('请选择目标对象'); const target = allObjects.value.find((item) => item.id === executeForm.target_object_id); saving.value = true; try { await executeOntologyAction(domainId.value, executeAction.value.id, { target_object_id: executeForm.target_object_id, expected_version: target?.version, parameters: executeForm.parameters, approval_reference: executeForm.approval_reference || null, decision_context: executeForm.reason ? { reason: executeForm.reason } : {} }); ElMessage.success('动作执行成功'); executeDialog.value = false; activeTab.value = 'activity'; await refreshAll() } catch (error) { ElMessage.error(String(errorMessage(error))) } finally { saving.value = false } }

async function handleValidate() { if (!domainId.value) return; validationResult.value = await validateOntology(domainId.value); validationDrawer.value = true }
async function handleExport() {
  if (!domainId.value) return
  const bundle = await exportOntologyBundle(domainId.value)
  const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob); const anchor = document.createElement('a')
  anchor.href = url; anchor.download = `${currentDomain.value?.domain_key || 'ontology'}-bundle.json`; anchor.click(); URL.revokeObjectURL(url)
}
async function handleImport(event: Event) {
  const input = event.target as HTMLInputElement; const file = input.files?.[0]; input.value = ''
  if (!domainId.value || !file) return
  try {
    const bundle = JSON.parse(await file.text())
    await importOntologyBundle(domainId.value, bundle, false)
    ElMessage.success('Ontology bundle 已导入'); await refreshAll()
  } catch (error) { ElMessage.error(String(errorMessage(error))) }
}
async function handlePublish() { if (!domainId.value) return; try { await ElMessageBox.confirm('发布后将生成不可变版本，可供业务动作运行。', '发布 Ontology', { type: 'warning', confirmButtonText: '发布' }); const result = await publishOntology(domainId.value, { description: '从 Ontology 工作台发布' }); ElMessage.success(`V${result.version} 已发布`); await refreshAll() } catch (error: any) { if (error === 'cancel' || error === 'close') return; const detail = error?.response?.data?.detail; if (detail?.errors) { validationResult.value = detail; validationDrawer.value = true } else ElMessage.error(String(errorMessage(error))) } }

function handleResize() { graph?.resize() }
watch(domainId, () => {
  if (!domainInitialized) return
  instanceRequestId += 1
  objectChoiceRequestId += 1
  instanceTypeId.value = undefined
  instancePage.value = 1
  instanceTotal.value = 0
  instanceTotalIsExact.value = true
  objects.value = []
  allObjects.value = []
  void refreshAll()
})
onMounted(async () => {
  window.addEventListener('resize', handleResize)
  loading.value = true
  try {
    await loadDomains()
    if (domainId.value) await refreshAll()
  } finally {
    domainInitialized = true
    loading.value = false
  }
})
onBeforeUnmount(() => {
  instanceRequestId += 1
  objectChoiceRequestId += 1
  window.removeEventListener('resize', handleResize)
  if (resizeFrame !== null) cancelAnimationFrame(resizeFrame)
  graphResizeObserver?.disconnect()
  graphResizeObserver = null
  observedGraphElement = null
  graph?.dispose()
  graph = null
})
</script>

<style scoped>
.ontology-page { width: 100%; max-width: var(--wq-page-max-width); height: 100%; min-width: 0; margin: 0 auto; padding-inline: var(--wq-page-gutter); display: flex; flex-direction: column; color: var(--wq-text); }
.page-toolbar { min-height: 66px; display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; padding-bottom: 14px; border-bottom: 1px solid var(--wq-border); }
.toolbar-actions, .section-toolbar, .instance-filter, .subsection-title { display: flex; align-items: center; }
.file-input { display: none; }
.title-group { min-width: 0; }.title-group h2 { color: var(--wq-text); font-size: 22px; line-height: 1.25; }.title-group p { margin-top: 8px; color: var(--wq-muted); font-size: 14px; }.toolbar-actions { justify-content: flex-end; gap: 8px; flex-wrap: wrap; }.domain-select { width: 210px; }
.metric-strip { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 1px; margin: 14px 0 8px; background: var(--wq-border); border: 1px solid var(--wq-border); border-radius: 7px; overflow: hidden; }.metric-item { position: relative; min-height: 72px; padding: 13px 16px; background: var(--wq-surface); }.metric-item span { display: block; color: var(--wq-muted); font-size: 12px; }.metric-item strong { display: block; margin-top: 3px; font-size: 23px; font-weight: 680; }.metric-item .el-icon { position: absolute; right: 14px; top: 22px; color: #98a2b3; font-size: 24px; }
.workspace-tabs { min-width: 0; min-height: 0; flex: 1; }.workspace-tabs :deep(.el-tabs__header) { margin: 0; }.workspace-tabs :deep(.el-tabs__content) { min-width: 0; height: calc(100% - 40px); }.workspace-tabs :deep(.el-tab-pane) { min-width: 0; height: 100%; }.graph-panel { position: relative; min-width: 0; height: 100%; min-height: 0; overflow: hidden; background: #fff; border-bottom: 1px solid var(--wq-border); }.ontology-graph { width: 100%; height: 100%; }.graph-empty { position: absolute; inset: 0; background: #fff; }
.table-section { height: 100%; background: var(--wq-surface); }.section-toolbar { height: 54px; justify-content: space-between; border-bottom: 1px solid var(--wq-border); }.section-toolbar > div { display: flex; align-items: baseline; gap: 8px; }.section-toolbar span { color: var(--wq-muted); font-size: 12px; }.instance-filter { gap: 12px !important; }.instance-filter .el-select { width: 190px; }
.sync-status-cell, .object-source-cell { display: flex; flex-direction: column; align-items: flex-start; gap: 5px; min-width: 0; }.sync-status-cell small { color: var(--wq-muted); font-size: 11px; white-space: nowrap; }.muted { color: var(--wq-muted); }.source-tags { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }.instance-pagination { position: relative; z-index: 2; min-height: 62px; display: flex; align-items: center; justify-content: flex-end; gap: 18px; padding: 8px 16px 14px; border-top: 1px solid var(--wq-border); background: var(--wq-surface); }.instance-pagination > span { color: var(--wq-muted); font-size: 12px; white-space: nowrap; }.source-query-input :deep(textarea) { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 1.6; }
.table-actions { display: flex; align-items: center; justify-content: center; gap: 4px; min-width: 0; flex-wrap: nowrap; white-space: nowrap; }
.table-actions :deep(.el-tooltip__trigger) { display: inline-flex; }
.table-action-btn { flex: 0 0 30px; width: 30px; height: 30px; min-height: 30px; padding: 0; margin: 0 !important; border-radius: 6px; color: var(--wq-muted); }
.table-action-btn :deep(.el-icon) { font-size: 16px; }
.table-action-btn:hover { color: var(--wq-primary-strong); background: var(--wq-primary-soft); }
.table-action-btn.is-primary { color: var(--wq-primary); }
.table-action-btn.is-primary:hover { color: var(--wq-primary-strong); background: var(--wq-primary-soft); }
.table-action-btn.is-danger { color: var(--wq-danger); }
.table-action-btn.is-danger:hover { color: #b42318; background: #fef3f2; }
.approval-tag { min-width: 92px; justify-content: center; }
.audit-field-list, .state-change-list { display: grid; gap: 7px; padding: 4px 0; }
.audit-field-row, .state-change-row { display: grid; grid-template-columns: max-content minmax(0, 1fr); align-items: start; gap: 8px; min-width: 0; }
.audit-field-key { display: inline-flex; align-items: center; min-height: 22px; padding: 1px 7px; border: 1px solid #d0d5dd; border-radius: 5px; background: #f2f4f7; color: #475467; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; font-weight: 650; line-height: 18px; white-space: nowrap; }
.audit-field-key.tone-status { border-color: #bfdbfe; background: #eff6ff; color: #1d4ed8; }
.audit-field-key.tone-time { border-color: #a5f0fc; background: #ecfdff; color: #0e7090; }
.audit-field-key.tone-number { border-color: #abefc6; background: #ecfdf3; color: #067647; }
.audit-field-key.tone-text { border-color: #fed7aa; background: #fff7ed; color: #b54708; }
.audit-field-key.tone-reference { border-color: #d9d6fe; background: #f4f3ff; color: #5925dc; }
.audit-field-key.tone-category { border-color: #fecdd6; background: #fff1f3; color: #c01048; }
.audit-field-value { min-width: 0; padding-top: 1px; color: #344054; font-size: 13px; line-height: 1.55; overflow-wrap: anywhere; }
.state-change-values { display: grid; grid-template-columns: minmax(0, 1fr) 16px minmax(0, 1fr); align-items: start; gap: 5px; min-width: 0; }
.state-value { min-width: 0; padding: 2px 6px; border-radius: 4px; background: #f2f4f7; color: #475467; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.state-value.is-after { background: #ecfdf3; color: #067647; }
.state-arrow { color: #98a2b3; font-size: 12px; line-height: 22px; text-align: center; }
.audit-empty { color: var(--wq-subtle); }
.primary-cell { display: flex; flex-direction: column; gap: 3px; }.primary-cell strong { font-weight: 620; }.primary-cell code, code { color: #344054; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }.property-grid { display: grid; gap: 5px; padding: 12px 58px; background: #f8fafc; }.property-row { display: grid; grid-template-columns: minmax(130px, 1fr) minmax(140px, 1fr) 80px 70px 60px; align-items: center; gap: 10px; min-height: 30px; }.object-property-list { gap: 6px; }.object-property-value { min-width: 0; display: block; overflow: hidden; cursor: help; text-overflow: ellipsis; white-space: nowrap; }.object-property-more { color: var(--wq-primary-strong); font-size: 12px; line-height: 1.5; cursor: help; }
:global(.object-property-tooltip) { max-width: min(680px, calc(100vw - 40px)); color: #344054; line-height: 1.6; white-space: normal; overflow-wrap: anywhere; }.object-property-tooltip-list { min-width: min(420px, calc(100vw - 56px)); max-width: min(640px, calc(100vw - 56px)); }
.form-grid { display: grid; gap: 14px; }.form-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }.form-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }.subsection-title { justify-content: space-between; min-height: 40px; margin-top: 4px; border-bottom: 1px solid var(--wq-border); }.builder-list { display: grid; gap: 7px; margin: 9px 0 14px; }.builder-row { display: grid; align-items: center; gap: 7px; padding: 7px; background: #f7f9fc; border: 1px solid var(--wq-border); border-radius: 6px; }.property-builder { grid-template-columns: 1.2fr 1.2fr 110px 62px 62px 32px; }.parameter-builder { grid-template-columns: 1fr 1fr 105px 1.2fr 62px 32px; }.condition-builder { grid-template-columns: 1fr 110px 1fr 1.2fr 32px; }.effect-builder { grid-template-columns: 1fr 2fr 32px; }
.validation-result section { margin-top: 18px; }.validation-result h4 { margin-bottom: 8px; }.validation-item { display: grid; grid-template-columns: 130px 1fr; gap: 10px; margin-bottom: 7px; padding: 10px; border-left: 3px solid; background: #f8fafc; }.validation-item.error { border-color: var(--wq-danger); }.validation-item.warning { border-color: var(--wq-warning); }
@media (max-width: 1100px) { .page-toolbar { align-items: flex-start; }.toolbar-actions { max-width: 60%; }.metric-strip { grid-template-columns: repeat(3, 1fr); }.form-grid.three { grid-template-columns: 1fr 1fr; } }
@media (max-width: 760px) { .ontology-page { padding-inline: 16px; }.page-toolbar { flex-direction: column; }.toolbar-actions { max-width: none; justify-content: flex-start; }.domain-select { width: 100%; }.metric-strip { grid-template-columns: repeat(2, 1fr); }.form-grid.two, .form-grid.three { grid-template-columns: 1fr; }.property-builder, .parameter-builder, .condition-builder, .effect-builder { grid-template-columns: 1fr; }.section-toolbar { height: auto; min-height: 54px; flex-wrap: wrap; } }
</style>
