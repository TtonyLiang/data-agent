<template>
  <div class="page-shell twin-runtime-page" v-loading="loading" :aria-busy="loading">
    <header class="page-header">
      <div>
        <h2>孪生运行</h2>
        <p>把业务数据库中的记录同步成可识别、可关联、可追踪的企业对象。</p>
      </div>
      <div class="header-actions">
        <el-select v-model="domainId" class="domain-select" placeholder="选择业务领域" aria-label="选择业务领域">
          <el-option
            v-for="domain in domains"
            :key="domain.id"
            :label="`${domain.name} · ${domain.domain_key}`"
            :value="domain.id"
          />
        </el-select>
        <el-button :disabled="!domainId" @click="loadRuntime">
          <el-icon><Refresh /></el-icon>
          刷新状态
        </el-button>
      </div>
    </header>

    <el-empty v-if="!loading && domains.length === 0" description="暂无可用业务领域" />

    <template v-else-if="currentDomain">
      <section class="runtime-flow" aria-label="孪生数据处理流程">
        <div :class="{ ready: Boolean(currentDomain.datasource_id) }">
          <span>1</span>
          <strong>连接数据</strong>
          <small>{{ currentDomain.datasource_id ? `数据源 #${currentDomain.datasource_id}` : '未绑定数据源' }}</small>
        </div>
        <i aria-hidden="true">→</i>
        <div :class="{ ready: mappingCount > 0 }">
          <span>2</span>
          <strong>统一数据含义</strong>
          <small>{{ mappingCount }} 项字段映射</small>
        </div>
        <i aria-hidden="true">→</i>
        <div :class="{ ready: syncEnabledCount > 0 }">
          <span>3</span>
          <strong>同步业务对象</strong>
          <small>{{ syncEnabledCount }} 类对象已配置</small>
        </div>
        <i aria-hidden="true">→</i>
        <div :class="{ ready: sourceObjectCount > 0 }">
          <span>4</span>
          <strong>形成当前孪生</strong>
          <small>{{ sourceObjectCount }} 个对象实例</small>
        </div>
      </section>

      <section class="runtime-summary">
        <div>
          <span>同步对象类型</span>
          <strong>{{ syncEnabledCount }} / {{ objectTypes.length }}</strong>
          <small>已配置 / 全部</small>
        </div>
        <div>
          <span>业务对象实例</span>
          <strong>{{ sourceObjectCount }}</strong>
          <small>源数据统计</small>
        </div>
        <div>
          <span>最近同步</span>
          <strong class="summary-time">{{ lastSyncedAt ? formatDateTime(lastSyncedAt) : '尚未同步' }}</strong>
          <small>{{ lastSyncStatusText }}</small>
        </div>
        <div>
          <span>当前模型版本</span>
          <strong>{{ activeModelRelease ? `V${activeModelRelease.version}` : '未激活' }}</strong>
          <small>{{ activeModelRelease?.name || '同步前必须激活统一企业模型' }}</small>
        </div>
      </section>

      <el-alert
        v-if="!activeModelRelease"
        class="runtime-release-alert"
        type="warning"
        :closable="false"
        title="当前领域没有激活的统一企业模型版本，预览和执行均会被阻断。"
      />

      <el-tabs v-model="activeView" class="runtime-tabs" @tab-change="handleRuntimeViewChange">
        <el-tab-pane label="同步运行" name="sync">
      <section class="runtime-content">
        <div class="runtime-table-panel">
          <div class="panel-heading">
            <div>
              <h3>对象同步任务</h3>
              <p>每次手动读取一个对象类型的一页数据，并更新同步状态。</p>
            </div>
            <el-button text type="primary" @click="openModelConfig">配置业务对象</el-button>
          </div>

          <el-table v-if="objectTypes.length" :data="objectTypes" class="runtime-table" border>
            <el-table-column label="业务对象" min-width="200">
              <template #default="{ row }">
                <div class="primary-cell">
                  <strong>{{ row.name }}</strong>
                  <code>{{ row.object_key }}</code>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="数据同步" min-width="150">
              <template #default="{ row }">
                <el-tag v-if="row.sync_enabled" type="success" effect="plain">已配置</el-tag>
                <el-tag v-else type="info" effect="plain">未配置</el-tag>
                <span class="cell-note">{{ row.source_query ? '只读查询已配置' : '未配置来源查询' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="运行状态" min-width="170">
              <template #default="{ row }">
                <el-tag :type="syncStatusType(row.last_sync_status)" effect="plain">
                  {{ syncStatusLabel(row) }}
                </el-tag>
                <span class="cell-note">
                  {{ row.last_synced_at ? formatDateTime(row.last_synced_at) : '暂无运行记录' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="源记录" width="110" align="right">
              <template #default="{ row }">{{ row.last_sync_total || row.last_sync_count || 0 }}</template>
            </el-table-column>
            <el-table-column label="操作" width="196" fixed="right" align="center">
              <template #default="{ row }">
                <span class="sync-actions">
                  <el-tooltip
                    :disabled="row.sync_enabled && Boolean(activeModelRelease)"
                    :content="syncActionHint(row, true)"
                    placement="top"
                  >
                    <span
                      :tabindex="row.sync_enabled && activeModelRelease ? -1 : 0"
                      :role="row.sync_enabled && activeModelRelease ? undefined : 'note'"
                      :aria-label="row.sync_enabled && activeModelRelease ? undefined : syncActionHint(row, true)"
                    >
                      <el-button
                        size="small"
                        :disabled="!row.sync_enabled || !activeModelRelease"
                        :loading="previewingTypeId === row.id"
                        @click="runObjectType(row, true)"
                      >预览</el-button>
                    </span>
                  </el-tooltip>
                  <el-tooltip
                    :disabled="row.sync_enabled && Boolean(activeModelRelease) && canManage"
                    :content="syncActionHint(row, false)"
                    placement="top"
                  >
                    <span
                      :tabindex="row.sync_enabled && activeModelRelease && canManage ? -1 : 0"
                      :role="row.sync_enabled && activeModelRelease && canManage ? undefined : 'note'"
                      :aria-label="row.sync_enabled && activeModelRelease && canManage ? undefined : syncActionHint(row, false)"
                    >
                      <el-button
                        type="primary"
                        plain
                        size="small"
                        :disabled="!row.sync_enabled || !activeModelRelease || !canManage"
                        :loading="syncingTypeId === row.id"
                        @click="runObjectType(row, false)"
                      >执行</el-button>
                    </span>
                  </el-tooltip>
                </span>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-else description="当前领域还没有业务对象">
            <el-button type="primary" @click="openModelConfig">开始本体建模</el-button>
          </el-empty>
        </div>

        <aside class="runtime-boundary">
          <h3>当前运行边界</h3>
          <ul>
            <li class="available">
              <b>已可用</b>
              <span>业务库只读分页同步</span>
            </li>
            <li class="available">
              <b>已可用</b>
              <span>源数据与本地动作结果合并</span>
            </li>
            <li class="available">
              <b>已可用</b>
              <span>同步数量、时间和错误记录</span>
            </li>
            <li class="available">
              <b>已可用</b>
              <span>激活模型版本与数据源一致性校验</span>
            </li>
            <li>
              <b>下一步</b>
              <span>后台定时与增量调度</span>
            </li>
            <li>
              <b>下一步</b>
              <span>对象身份合并与状态历史</span>
            </li>
          </ul>
          <el-alert
            type="info"
            :closable="false"
            title="当前页面是手动运行入口，不表示已经接入 CDC 或自动调度。"
          />
        </aside>
      </section>

      <section class="sync-history-panel">
        <div class="panel-heading">
          <div>
            <h3>最近同步记录</h3>
            <p>预览不会写入对象；执行记录可按 trace 定位同步数量和错误。</p>
          </div>
        </div>
        <el-table v-if="syncRuns.length" :data="syncRuns" border size="small" :scrollbar-tabindex="-1">
          <el-table-column label="运行" min-width="180">
            <template #default="{ row }">
              <div class="primary-cell">
                <strong>#{{ row.id }} · {{ row.dry_run ? '预览' : '执行' }}</strong>
                <code>{{ row.trace_id }}</code>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="runStatusType(row.status)" effect="plain">
                {{ runStatusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="统计" min-width="270">
            <template #default="{ row }">
              读取 {{ runStat(row, 'read') }}，新增 {{ runStat(row, 'created') }}，更新
              {{ runStat(row, 'updated') }}，跳过 {{ runStat(row, 'skipped') }}
            </template>
          </el-table-column>
          <el-table-column label="模型版本" width="110">
            <template #default="{ row }">
              {{ row.model_release_id ? `#${row.model_release_id}` : '历史未记录' }}
            </template>
          </el-table-column>
          <el-table-column label="完成时间" min-width="170">
            <template #default="{ row }">
              {{ row.completed_at ? formatDateTime(row.completed_at) : '运行中' }}
            </template>
          </el-table-column>
          <el-table-column label="错误" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ row.error_summary || '-' }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无同步运行记录" :image-size="72" />
      </section>
        </el-tab-pane>

        <el-tab-pane label="对象实例" name="instances">
          <section class="runtime-entity-panel instance-panel">
            <div class="panel-heading runtime-view-heading">
              <div>
                <h3>对象实例</h3>
                <p>查看当前孪生对象、来源、属性和版本。</p>
              </div>
              <div class="view-actions">
                <el-select v-model="instanceTypeId" clearable placeholder="全部对象类型" aria-label="筛选对象类型" @change="handleInstanceTypeChange">
                  <el-option v-for="item in objectTypes" :key="item.id" :label="item.name" :value="item.id" />
                </el-select>
                <el-button :icon="Refresh" :loading="runtimeViewLoading" @click="loadObjects">刷新</el-button>
                <el-button v-if="canManage" type="primary" :icon="Plus" @click="openObjectDialog()">新建实例</el-button>
              </div>
            </div>
            <el-table :data="objects" border class="runtime-data-table" v-loading="runtimeViewLoading">
              <el-table-column label="对象" min-width="220">
                <template #default="{ row }">
                  <div class="primary-cell"><strong>{{ row.display_name }}</strong><code>{{ row.primary_value }}</code></div>
                </template>
              </el-table-column>
              <el-table-column prop="object_type_name" label="对象类型" min-width="150" />
              <el-table-column label="来源" width="120">
                <template #default="{ row }">
                  <el-tag :type="row.source_kind === 'database' ? 'success' : 'info'" effect="plain">
                    {{ row.source_kind === 'database' ? '业务库' : '本地' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="属性" min-width="420">
                <template #default="{ row }">
                  <el-tooltip
                    v-if="objectPropertyEntries(row.properties).length"
                    placement="top-start"
                    effect="light"
                    :show-after="120"
                    :hide-after="80"
                    transition="object-property-popover-fade"
                    popper-class="object-property-tooltip"
                  >
                    <div
                      class="audit-field-list object-property-list object-property-trigger"
                      role="note"
                      tabindex="0"
                      :aria-label="objectPropertyAriaLabel(row.properties)"
                    >
                      <div class="object-property-preview-heading">
                        <span>关键属性</span>
                        <small>{{ objectPropertyEntries(row.properties).length }} 项</small>
                      </div>
                      <div v-for="entry in objectPropertyPreview(row.properties)" :key="entry.key" class="audit-field-row">
                        <span :class="['audit-field-key', `tone-${entry.tone}`]">{{ entry.key }}</span>
                        <span class="audit-field-value object-property-value">{{ formatStateValue(entry.value, entry.key) }}</span>
                      </div>
                      <span v-if="hiddenPropertyCount(row.properties)" class="object-property-more">+{{ hiddenPropertyCount(row.properties) }} 项</span>
                    </div>
                    <template #content>
                      <div class="object-property-tooltip-content">
                        <div class="object-property-tooltip-heading">
                          <span>完整属性</span>
                          <b>{{ objectPropertyEntries(row.properties).length }} 项</b>
                        </div>
                        <div class="audit-field-list object-property-tooltip-list">
                          <div v-for="entry in objectPropertyEntries(row.properties)" :key="entry.key" class="audit-field-row">
                            <span :class="['audit-field-key', `tone-${entry.tone}`]">{{ entry.key }}</span>
                            <span class="audit-field-value">{{ formatStateValue(entry.value, entry.key) }}</span>
                          </div>
                        </div>
                      </div>
                    </template>
                  </el-tooltip>
                  <span v-else class="audit-empty">-</span>
                </template>
              </el-table-column>
              <el-table-column label="版本" width="80"><template #default="{ row }">v{{ row.version }}</template></el-table-column>
              <el-table-column v-if="canManage" label="操作" width="120" fixed="right" align="center">
                <template #default="{ row }">
                  <span class="row-actions">
                    <el-button text :icon="Edit" :aria-label="`编辑对象实例 ${row.display_name || row.primary_value}`" @click="openObjectDialog(row)" />
                    <el-button text type="danger" :icon="Delete" :aria-label="`删除对象实例 ${row.display_name || row.primary_value}`" @click="removeObject(row)" />
                  </span>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!runtimeViewLoading && objects.length === 0" description="暂无对象实例" />
            <div v-if="instanceTotal > 0" class="instance-pagination">
              <span>共 {{ instanceTotal }} 条</span>
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

        <el-tab-pane label="关系实例" name="links">
          <section class="runtime-entity-panel">
            <div class="panel-heading runtime-view-heading">
              <div>
                <h3>关系实例</h3>
                <p>查看当前对象之间已经建立的业务关联。</p>
              </div>
              <div class="view-actions">
                <el-button :icon="Refresh" :loading="runtimeViewLoading" @click="loadLinks">刷新</el-button>
                <el-button v-if="canManage" type="primary" :icon="Connection" :disabled="linkTypes.length === 0" @click="openLinkDialog">建立关系</el-button>
              </div>
            </div>
            <el-table :data="links" border class="runtime-data-table" v-loading="runtimeViewLoading">
              <el-table-column label="关系" min-width="190">
                <template #default="{ row }"><div class="primary-cell"><strong>{{ row.link_type_name }}</strong><code>{{ row.link_key }}</code></div></template>
              </el-table-column>
              <el-table-column label="起点对象" min-width="220">
                <template #default="{ row }"><strong>{{ row.source_name }}</strong><span class="cell-note">{{ row.source_primary_value }}</span></template>
              </el-table-column>
              <el-table-column label="终点对象" min-width="220">
                <template #default="{ row }"><strong>{{ row.target_name }}</strong><span class="cell-note">{{ row.target_primary_value }}</span></template>
              </el-table-column>
              <el-table-column label="属性" min-width="300">
                <template #default="{ row }">
                  <div v-if="objectPropertyEntries(row.properties).length" class="audit-field-list compact-audit-list">
                    <div v-for="entry in objectPropertyPreview(row.properties)" :key="entry.key" class="audit-field-row">
                      <span :class="['audit-field-key', `tone-${entry.tone}`]">{{ entry.key }}</span>
                      <span class="audit-field-value">{{ formatStateValue(entry.value, entry.key) }}</span>
                    </div>
                  </div>
                  <span v-else class="audit-empty">-</span>
                </template>
              </el-table-column>
              <el-table-column v-if="canManage" label="操作" width="80" fixed="right" align="center">
                <template #default="{ row }"><span class="row-actions"><el-button text type="danger" :icon="Delete" :aria-label="`删除关系实例 ${row.link_type_name}：${row.source_name} 到 ${row.target_name}`" @click="removeLink(row)" /></span></template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!runtimeViewLoading && links.length === 0" description="暂无关系实例" />
          </section>
        </el-tab-pane>

        <el-tab-pane label="动作执行记录" name="audit">
          <section class="runtime-entity-panel">
            <div class="panel-heading runtime-view-heading">
              <div>
                <h3>动作执行记录</h3>
                <p>记录受控 Ontology Action 的执行结果和状态变化，不代表通用 Decision Capability 已完成。</p>
              </div>
              <div class="view-actions">
                <el-button :icon="Refresh" :loading="runtimeViewLoading" @click="loadActionRuns">刷新</el-button>
                <el-button type="primary" :icon="VideoPlay" :disabled="!activeModelRelease || availableActions.length === 0" @click="openExecuteDialog">执行动作</el-button>
              </div>
            </div>
            <el-table :data="actionRuns" border class="runtime-data-table" v-loading="runtimeViewLoading">
              <el-table-column label="状态" width="100">
                <template #default="{ row }"><el-tag :type="actionRunStatusType(row.status)" effect="plain">{{ actionRunStatusLabel(row.status) }}</el-tag></template>
              </el-table-column>
              <el-table-column label="动作 / 目标" min-width="230">
                <template #default="{ row }"><div class="primary-cell"><strong>{{ row.action_name }}</strong><span>{{ row.target_name || '未指定目标' }}</span></div></template>
              </el-table-column>
              <el-table-column label="执行人" width="130"><template #default="{ row }">{{ row.user_name || row.username || '-' }}</template></el-table-column>
              <el-table-column label="执行上下文" min-width="320">
                <template #default="{ row }">
                  <div v-if="decisionContextEntries(row.decision_context).length" class="audit-field-list compact-audit-list">
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
                  <div v-if="stateChangeEntries(row.before_state, row.after_state).length" class="state-change-list compact-state-list">
                    <div v-for="change in stateChangeEntries(row.before_state, row.after_state)" :key="change.key" class="state-change-row">
                      <span :class="['audit-field-key', `tone-${change.tone}`]">{{ change.key }}</span>
                      <div class="state-change-values">
                        <span class="state-value">{{ formatStateValue(change.before, change.key) }}</span>
                        <span class="state-arrow">→</span>
                        <span class="state-value is-after">{{ formatStateValue(change.after, change.key) }}</span>
                      </div>
                    </div>
                  </div>
                  <span v-else class="audit-empty">无属性变化</span>
                </template>
              </el-table-column>
              <el-table-column label="执行时间" min-width="170"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column>
            </el-table>
            <el-empty v-if="!runtimeViewLoading && actionRuns.length === 0" description="暂无动作执行记录" />
          </section>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-dialog v-model="objectDialog" :title="objectForm.id ? '编辑对象实例' : '新建对象实例'" width="700px" @opened="focusControl(objectTypeSelect)">
      <el-form label-position="top">
        <el-form-item label="对象类型" required>
          <el-select ref="objectTypeSelect" v-model="objectForm.object_type_id" :disabled="Boolean(objectForm.id)" @change="resetObjectProperties">
            <el-option v-for="item in objectTypes" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <div class="form-grid">
          <el-form-item v-for="property in selectedObjectType?.properties || []" :key="property.property_key" :label="property.name" :required="property.required">
            <el-switch v-if="property.data_type === 'boolean'" v-model="objectForm.properties[property.property_key]" />
            <el-input-number v-else-if="property.data_type === 'integer' || property.data_type === 'number'" v-model="objectForm.properties[property.property_key]" :precision="property.data_type === 'integer' ? 0 : undefined" controls-position="right" />
            <el-date-picker v-else-if="property.data_type === 'date'" v-model="objectForm.properties[property.property_key]" type="date" value-format="YYYY-MM-DD" />
            <el-date-picker v-else-if="property.data_type === 'datetime'" v-model="objectForm.properties[property.property_key]" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" />
            <el-input v-else v-model="objectForm.properties[property.property_key]" :type="property.data_type === 'text' || property.data_type === 'json' ? 'textarea' : 'text'" :rows="2" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer><el-button @click="objectDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveObject">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="linkDialog" title="建立对象关系" width="620px" @opened="focusControl(linkTypeSelect)">
      <el-form label-position="top">
        <el-form-item label="关系类型" required><el-select ref="linkTypeSelect" v-model="linkForm.link_type_id" @change="loadLinkChoices"><el-option v-for="item in linkTypes" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="起点对象" required><el-select v-model="linkForm.source_object_id" filterable :loading="choiceLoading"><el-option v-for="item in linkSourceChoices" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="终点对象" required><el-select v-model="linkForm.target_object_id" filterable :loading="choiceLoading"><el-option v-for="item in linkTargetChoices" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="linkDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveLink">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="executeDialog" title="执行受控动作" width="640px" @opened="focusControl(actionTypeSelect)">
      <el-form label-position="top">
        <el-form-item label="动作" required><el-select ref="actionTypeSelect" v-model="executeForm.action_type_id" @change="loadExecuteTargets"><el-option v-for="item in availableActions" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="目标对象" required><el-select v-model="executeForm.target_object_id" filterable :loading="choiceLoading"><el-option v-for="item in executeTargets" :key="item.id" :label="`${item.display_name} · ${item.primary_value}`" :value="item.id" /></el-select></el-form-item>
        <el-form-item v-for="parameter in selectedAction?.parameters || []" :key="parameter.parameter_key" :label="parameter.name" :required="parameter.required">
          <el-select v-if="parameter.options?.length" v-model="executeForm.parameters[parameter.parameter_key]"><el-option v-for="option in parameter.options" :key="String(option)" :label="String(option)" :value="option" /></el-select>
          <el-switch v-else-if="parameter.data_type === 'boolean'" v-model="executeForm.parameters[parameter.parameter_key]" />
          <el-input-number v-else-if="parameter.data_type === 'integer' || parameter.data_type === 'number'" v-model="executeForm.parameters[parameter.parameter_key]" :precision="parameter.data_type === 'integer' ? 0 : undefined" />
          <el-input v-else v-model="executeForm.parameters[parameter.parameter_key]" />
        </el-form-item>
        <el-form-item v-if="selectedAction?.requires_approval" label="审批单号" required><el-input v-model="executeForm.approval_reference" /></el-form-item>
        <el-form-item label="执行说明"><el-input v-model="executeForm.reason" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="executeDialog = false">取消</el-button><el-button type="primary" :icon="VideoPlay" :loading="saving" @click="runAction">执行动作</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import {
  deleteOntologyLink,
  deleteOntologyObject,
  executeOntologyAction,
  fetchOntologyActionRuns,
  fetchOntologyActionTypes,
  fetchOntologyAgentContext,
  fetchOntologyDomains,
  fetchOntologyLinks,
  fetchOntologyLinkTypes,
  fetchOntologyObjects,
  fetchOntologyObjectTypes,
  fetchOntologySummary,
  fetchSemanticAssets,
  queryOntologyObjects,
  createTwinSyncRun,
  fetchTwinSyncRuns,
  saveOntologyLink,
  saveOntologyObject,
  type OntologyActionRun,
  type OntologyActionType,
  type OntologyAgentContext,
  type OntologyLink,
  type OntologyLinkType,
  type OntologyObject,
  type OntologyObjectType,
  type OntologySummary,
  type SemanticDomain,
  type TwinSyncRun,
} from '../api'
import { authState, isAdmin } from '../stores/auth'
import { formatDateTime, isDateTimeField, isDateTimeValue } from '../utils/datetime'
import { Connection, Delete, Edit, Plus, Refresh, VideoPlay } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const domains = ref<SemanticDomain[]>([])
const domainId = ref<number | null>(null)
const summary = ref<OntologySummary | null>(null)
const context = ref<OntologyAgentContext | null>(null)
const objectTypes = ref<OntologyObjectType[]>([])
const mappingCount = ref(0)
const loading = ref(true)
const syncingTypeId = ref<number | null>(null)
const previewingTypeId = ref<number | null>(null)
const syncRuns = ref<TwinSyncRun[]>([])
const activeView = ref<'sync' | 'instances' | 'links' | 'audit'>('sync')
const runtimeViewLoading = ref(false)
const saving = ref(false)
const instanceTypeId = ref<number | null>(null)
const instancePage = ref(1)
const instancePageSize = ref(50)
const instanceTotal = ref(0)
const objects = ref<OntologyObject[]>([])
const linkTypes = ref<OntologyLinkType[]>([])
const links = ref<OntologyLink[]>([])
const actionTypes = ref<OntologyActionType[]>([])
const actionRuns = ref<OntologyActionRun[]>([])
const objectChoices = ref<OntologyObject[]>([])
const choiceLoading = ref(false)
const objectDialog = ref(false)
const objectForm = reactive<Record<string, any>>({ id: null, object_type_id: null, properties: {} })
const linkDialog = ref(false)
const linkForm = reactive<Record<string, number | null>>({ link_type_id: null, source_object_id: null, target_object_id: null })
const executeDialog = ref(false)
const executeForm = reactive<Record<string, any>>({ action_type_id: null, target_object_id: null, parameters: {}, approval_reference: '', reason: '' })
type FocusableControl = { focus: () => void }
const objectTypeSelect = ref<FocusableControl>()
const linkTypeSelect = ref<FocusableControl>()
const actionTypeSelect = ref<FocusableControl>()
let instanceRequestId = 0

const INSTANCE_CHOICE_LIMIT = 200
const PROPERTY_PREVIEW_LIMIT = 4

const currentDomain = computed(() => domains.value.find((item) => item.id === domainId.value) || null)
const activeModelRelease = computed(() => context.value?.model_release || null)
const canManage = computed(() => isAdmin())
const currentRole = computed(() => authState.currentUser?.role || 'user')
const selectedObjectType = computed(() => objectTypes.value.find((item) => item.id === objectForm.object_type_id))
const selectedLinkType = computed(() => linkTypes.value.find((item) => item.id === linkForm.link_type_id))
const linkSourceChoices = computed(() => objectChoices.value.filter((item) => item.object_type_key === selectedLinkType.value?.source_object_key))
const linkTargetChoices = computed(() => objectChoices.value.filter((item) => item.object_type_key === selectedLinkType.value?.target_object_key))
const availableActions = computed(() => actionTypes.value.filter((item) => item.status === 'active' && (canManage.value || item.allowed_roles?.includes(currentRole.value as 'admin' | 'user'))))
const selectedAction = computed(() => availableActions.value.find((item) => item.id === executeForm.action_type_id))
const executeTargets = computed(() => objectChoices.value.filter((item) => item.object_type_key === selectedAction.value?.target_object_key))
const instancePageSizes = computed(() => [20, 50, 100])
const syncEnabledCount = computed(() => objectTypes.value.filter((item) => item.sync_enabled).length)
const sourceObjectCount = computed(() => Number(summary.value?.counts.source_objects || summary.value?.counts.objects || 0))
const lastSyncedAt = computed(() => objectTypes.value
  .map((item) => item.last_synced_at)
  .filter((value): value is string => Boolean(value))
  .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0] || '')
const lastSyncStatusText = computed(() => {
  const synced = objectTypes.value.filter((item) => item.last_sync_status)
  if (!synced.length) return '等待首次运行'
  if (synced.some((item) => item.last_sync_status === 'failed')) return '存在同步失败'
  if (synced.some((item) => item.last_sync_status === 'partial')) return '存在部分成功'
  return '最近任务运行成功'
})

function focusControl(control: FocusableControl | undefined) {
  requestAnimationFrame(() => control?.focus())
}

onMounted(async () => {
  try {
    domains.value = await fetchOntologyDomains()
    const requestedDomainId = Number(route.query.domain_id || 0)
    domainId.value = domains.value.some((item) => item.id === requestedDomainId)
      ? requestedDomainId
      : domains.value[0]?.id || null
    const requestedView = String(route.query.view || '')
    if (['sync', 'instances', 'links', 'audit'].includes(requestedView)) {
      activeView.value = requestedView as typeof activeView.value
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    if (!domainId.value) loading.value = false
  }
})

watch(domainId, () => {
  instanceRequestId += 1
  instancePage.value = 1
  instanceTotal.value = 0
  objects.value = []
  void loadRuntime()
})

async function loadRuntime() {
  if (!domainId.value) {
    summary.value = null
    context.value = null
    objectTypes.value = []
    linkTypes.value = []
    actionTypes.value = []
    objects.value = []
    instanceTotal.value = 0
    links.value = []
    actionRuns.value = []
    syncRuns.value = []
    mappingCount.value = 0
    return
  }
  loading.value = true
  try {
    const [nextSummary, nextContext, nextTypes, nextLinkTypes, nextActionTypes, assets, nextRuns] = await Promise.all([
      fetchOntologySummary(domainId.value),
      fetchOntologyAgentContext(domainId.value),
      fetchOntologyObjectTypes(domainId.value),
      fetchOntologyLinkTypes(domainId.value),
      fetchOntologyActionTypes(domainId.value),
      fetchSemanticAssets(domainId.value),
      fetchTwinSyncRuns(domainId.value),
    ])
    summary.value = nextSummary
    context.value = nextContext
    objectTypes.value = nextTypes
    linkTypes.value = nextLinkTypes
    actionTypes.value = nextActionTypes
    if (!objectTypes.value.some((item) => item.id === instanceTypeId.value)) {
      instanceTypeId.value = objectTypes.value[0]?.id || null
      instancePage.value = 1
    }
    mappingCount.value = Array.isArray(assets.mapping) ? assets.mapping.length : 0
    syncRuns.value = nextRuns
    await loadActiveRuntimeView()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadActiveRuntimeView() {
  if (activeView.value === 'instances') await loadObjects()
  else if (activeView.value === 'links') await loadLinks()
  else if (activeView.value === 'audit') await loadActionRuns()
}

async function handleRuntimeViewChange(name: string | number) {
  activeView.value = String(name) as typeof activeView.value
  await loadActiveRuntimeView()
}

async function loadObjects() {
  if (!domainId.value) {
    objects.value = []
    instanceTotal.value = 0
    return
  }
  const requestId = ++instanceRequestId
  const pageSize = Math.min(Math.max(instancePageSize.value, 1), 100)
  const offset = (instancePage.value - 1) * pageSize
  const objectTypeKey = objectTypes.value.find((item) => item.id === instanceTypeId.value)?.object_key
  runtimeViewLoading.value = true
  try {
    const result = await queryOntologyObjects(domainId.value, {
      ...(objectTypeKey ? { object_type_key: objectTypeKey } : {}),
      limit: pageSize,
      offset,
    })
    if (requestId !== instanceRequestId) return
    const nextObjects = Array.isArray(result.objects) ? result.objects : []
    const nextTotal = Number(result.total || 0)
    if (!nextObjects.length && nextTotal > 0 && instancePage.value > 1) {
      instancePage.value = Math.max(1, Math.ceil(nextTotal / pageSize))
      await loadObjects()
      return
    }
    objects.value = nextObjects
    instanceTotal.value = nextTotal
  } catch (error) {
    if (requestId !== instanceRequestId) return
    objects.value = []
    instanceTotal.value = 0
    ElMessage.error(errorMessage(error))
  } finally {
    if (requestId === instanceRequestId) runtimeViewLoading.value = false
  }
}

async function handleInstanceTypeChange() {
  instancePage.value = 1
  await loadObjects()
}

async function handleInstancePageChange(page: number) {
  instancePage.value = page
  await loadObjects()
}

async function handleInstancePageSizeChange(pageSize: number) {
  instancePageSize.value = pageSize
  instancePage.value = 1
  await loadObjects()
}

function openObjectDialog(row?: OntologyObject) {
  objectForm.id = row?.id || null
  objectForm.object_type_id = row?.object_type_id || instanceTypeId.value || objectTypes.value[0]?.id || null
  objectForm.properties = row ? JSON.parse(JSON.stringify(row.properties || {})) : {}
  if (row) {
    for (const property of selectedObjectType.value?.properties || []) {
      const value = objectForm.properties[property.property_key]
      if (property.data_type === 'json' && value !== undefined && typeof value !== 'string') {
        objectForm.properties[property.property_key] = JSON.stringify(value, null, 2)
      }
    }
  } else {
    resetObjectProperties()
  }
  objectDialog.value = true
}

function resetObjectProperties() {
  objectForm.properties = {}
  for (const property of selectedObjectType.value?.properties || []) {
    if (property.default_value !== null && property.default_value !== undefined) {
      objectForm.properties[property.property_key] = property.data_type === 'json' && typeof property.default_value !== 'string'
        ? JSON.stringify(property.default_value, null, 2)
        : property.default_value
    }
  }
}

async function saveObject() {
  const objectType = selectedObjectType.value
  if (!domainId.value || !objectType) {
    ElMessage.warning('请选择对象类型')
    return
  }
  const properties = { ...objectForm.properties }
  for (const property of objectType.properties) {
    if (property.data_type !== 'json' || typeof properties[property.property_key] !== 'string') continue
    const value = String(properties[property.property_key]).trim()
    if (!value) continue
    try {
      properties[property.property_key] = JSON.parse(value)
    } catch {
      ElMessage.warning(`${property.name} 不是有效 JSON`)
      return
    }
  }
  const primaryValue = properties[objectType.primary_property]
  if (primaryValue === undefined || primaryValue === null || primaryValue === '') {
    ElMessage.warning('请填写主属性')
    return
  }
  saving.value = true
  try {
    await saveOntologyObject(domainId.value, {
      id: objectForm.id,
      domain_id: domainId.value,
      object_type_id: objectType.id,
      primary_value: primaryValue,
      properties,
      status: 'active',
    })
    ElMessage.success('对象实例已保存')
    objectDialog.value = false
    await loadRuntime()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

async function removeObject(row: OntologyObject) {
  try {
    await ElMessageBox.confirm(`删除对象“${row.display_name}”及其关系？`, '删除对象', { type: 'warning' })
    await deleteOntologyObject(row.domain_id, row.id)
    ElMessage.success('对象实例已删除')
    await loadRuntime()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error))
  }
}

async function loadLinks() {
  if (!domainId.value) {
    links.value = []
    return
  }
  runtimeViewLoading.value = true
  try {
    links.value = await fetchOntologyLinks(domainId.value)
  } catch (error) {
    links.value = []
    ElMessage.error(errorMessage(error))
  } finally {
    runtimeViewLoading.value = false
  }
}

async function loadObjectChoices(objectKeys: string[]) {
  if (!domainId.value) {
    objectChoices.value = []
    return
  }
  const typeIds = [...new Set(objectKeys)]
    .map((key) => objectTypes.value.find((item) => item.object_key === key)?.id)
    .filter((id): id is number => Boolean(id))
  choiceLoading.value = true
  try {
    const pages = await Promise.all(
      typeIds.map((typeId) => fetchOntologyObjects(domainId.value!, typeId, INSTANCE_CHOICE_LIMIT, 0)),
    )
    objectChoices.value = pages.flat()
  } catch (error) {
    objectChoices.value = []
    ElMessage.error(errorMessage(error))
  } finally {
    choiceLoading.value = false
  }
}

async function loadLinkChoices() {
  linkForm.source_object_id = null
  linkForm.target_object_id = null
  objectChoices.value = []
  const linkType = selectedLinkType.value
  if (linkType) {
    await loadObjectChoices([linkType.source_object_key, linkType.target_object_key])
  }
}

async function openLinkDialog() {
  if (!linkTypes.value.length) {
    ElMessage.warning('请先定义关系类型')
    return
  }
  linkForm.link_type_id = linkTypes.value[0].id
  linkDialog.value = true
  await loadLinkChoices()
}

async function saveLink() {
  if (!domainId.value || !linkForm.link_type_id || !linkForm.source_object_id || !linkForm.target_object_id) {
    ElMessage.warning('请选择关系和两端对象')
    return
  }
  saving.value = true
  try {
    await saveOntologyLink(domainId.value, {
      domain_id: domainId.value,
      ...linkForm,
      properties: {},
    })
    ElMessage.success('关系实例已保存')
    linkDialog.value = false
    await loadLinks()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

async function removeLink(row: OntologyLink) {
  try {
    await ElMessageBox.confirm(`删除关系“${row.link_type_name}”？`, '删除关系实例', { type: 'warning' })
    if (!domainId.value) return
    await deleteOntologyLink(domainId.value, row.id)
    ElMessage.success('关系实例已删除')
    await loadLinks()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error))
  }
}

async function loadActionRuns() {
  if (!domainId.value) {
    actionRuns.value = []
    return
  }
  runtimeViewLoading.value = true
  try {
    actionRuns.value = await fetchOntologyActionRuns(domainId.value)
  } catch (error) {
    actionRuns.value = []
    ElMessage.error(errorMessage(error))
  } finally {
    runtimeViewLoading.value = false
  }
}

async function loadExecuteTargets() {
  executeForm.target_object_id = null
  executeForm.parameters = {}
  executeForm.approval_reference = ''
  objectChoices.value = []
  const action = selectedAction.value
  if (!action) return
  for (const parameter of action.parameters || []) {
    if (parameter.data_type === 'boolean') executeForm.parameters[parameter.parameter_key] = false
  }
  await loadObjectChoices([action.target_object_key])
}

async function openExecuteDialog() {
  if (!activeModelRelease.value) {
    ElMessage.warning('请先激活统一企业模型版本')
    return
  }
  const action = availableActions.value[0]
  if (!action) {
    ElMessage.warning('当前角色没有可执行动作')
    return
  }
  executeForm.action_type_id = action.id
  executeForm.reason = ''
  executeDialog.value = true
  await loadExecuteTargets()
}

async function runAction() {
  const action = selectedAction.value
  const target = objectChoices.value.find((item) => item.id === executeForm.target_object_id)
  if (!domainId.value || !action || !target) {
    ElMessage.warning('请选择动作和目标对象')
    return
  }
  if (action.requires_approval && !String(executeForm.approval_reference || '').trim()) {
    ElMessage.warning('请填写审批单号')
    return
  }
  saving.value = true
  try {
    await executeOntologyAction(domainId.value, action.id, {
      target_object_id: target.id,
      expected_version: target.version,
      parameters: executeForm.parameters,
      approval_reference: executeForm.approval_reference || null,
      decision_context: executeForm.reason ? { reason: executeForm.reason } : {},
    })
    ElMessage.success('动作执行成功')
    executeDialog.value = false
    await loadRuntime()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

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

function objectPropertyAriaLabel(value: Record<string, unknown> | undefined) {
  const entries = objectPropertyEntries(value)
  if (!entries.length) return '无对象属性'
  return `完整属性：${entries.map((entry) => `${entry.key}，${formatStateValue(entry.value, entry.key)}`).join('；')}`
}

function objectPropertyPreview(value: Record<string, unknown> | undefined) {
  return objectPropertyEntries(value).slice(0, PROPERTY_PREVIEW_LIMIT)
}

function hiddenPropertyCount(value: Record<string, unknown> | undefined) {
  return Math.max(objectPropertyEntries(value).length - PROPERTY_PREVIEW_LIMIT, 0)
}

function stateChangeEntries(before: Record<string, unknown> | undefined, after: Record<string, unknown> | undefined) {
  const oldValues = (before?.properties || {}) as Record<string, unknown>
  const newValues = (after?.properties || {}) as Record<string, unknown>
  const keys = new Set([...Object.keys(oldValues), ...Object.keys(newValues)])
  return [...keys]
    .filter((key) => JSON.stringify(oldValues[key]) !== JSON.stringify(newValues[key]))
    .map((key) => ({ key, before: oldValues[key], after: newValues[key], tone: auditFieldTone(key) }))
}

function actionRunStatusLabel(status: OntologyActionRun['status']) {
  return ({ running: '执行中', succeeded: '成功', failed: '失败' })[status]
}

function actionRunStatusType(status: OntologyActionRun['status']) {
  return ({ running: 'info', succeeded: 'success', failed: 'danger' } as const)[status]
}

async function runObjectType(objectType: OntologyObjectType, dryRun: boolean) {
  if (!domainId.value || !objectType.sync_enabled) return
  if (dryRun) previewingTypeId.value = objectType.id
  else syncingTypeId.value = objectType.id
  try {
    const response = await createTwinSyncRun(domainId.value, {
      object_type_id: objectType.id,
      page: 1,
      page_size: Math.min(Math.max(Number(objectType.sync_limit || 200), 1), 1000),
      sync_links: true,
      dry_run: dryRun,
    })
    const result = response.result
    const typeResult = result.types.find((item) => item.object_type_id === objectType.id) || result.types[0]
    if (typeResult?.errors?.length) {
      ElMessage.warning(`同步完成，但有 ${typeResult.errors.length} 个问题：${typeResult.errors[0]}`)
    } else {
      const changed = Number(typeResult?.created || 0) + Number(typeResult?.updated || 0)
      const action = dryRun ? '预览' : '同步'
      ElMessage.success(`${action}读取 ${typeResult?.read || result.objects.length} 条，变化 ${changed} 条`)
    }
    await loadRuntime()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    if (dryRun) previewingTypeId.value = null
    else syncingTypeId.value = null
  }
}

function runStat(run: TwinSyncRun, key: string) {
  return Number(run.statistics_json?.[key] || 0)
}

function syncActionHint(row: OntologyObjectType, dryRun: boolean) {
  if (!row.sync_enabled) return '请先在企业模型中配置只读同步查询'
  if (!activeModelRelease.value) return '请先创建、校验并激活统一企业模型版本'
  if (!dryRun && !canManage.value) return '只有管理员可以执行写入型同步'
  return ''
}

function runStatusLabel(status: TwinSyncRun['status']) {
  return ({ running: '运行中', succeeded: '成功', partial: '部分成功', failed: '失败' })[status]
}

function runStatusType(status: TwinSyncRun['status']) {
  return ({
    running: 'info',
    succeeded: 'success',
    partial: 'warning',
    failed: 'danger',
  } as const)[status]
}

function openModelConfig() {
  router.push({ path: '/enterprise-model', query: { section: 'ontology' } })
}

function syncStatusLabel(row: OntologyObjectType) {
  if (!row.sync_enabled) return '未配置'
  return ({
    succeeded: '同步成功',
    partial: '部分成功',
    failed: '同步失败',
  } as Record<string, string>)[String(row.last_sync_status || '')] || '等待同步'
}

function syncStatusType(status: OntologyObjectType['last_sync_status']) {
  if (status === 'succeeded') return 'success'
  if (status === 'partial') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}

function errorMessage(error: unknown) {
  const candidate = error as { response?: { data?: { detail?: string | { message?: string } } }; message?: string }
  const detail = candidate?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return candidate?.message || '孪生运行状态加载失败'
}
</script>

<style scoped>
.twin-runtime-page {
  height: 100%;
  min-height: 0;
  overflow: auto;
}

.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
}

.header-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.domain-select {
  width: 280px;
}

.runtime-release-alert {
  margin-bottom: 16px;
}

.runtime-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.runtime-flow {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr);
  align-items: center;
  padding: 16px 18px;
  margin-bottom: 16px;
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  box-shadow: var(--wq-shadow-sm);
}

.runtime-flow > div {
  min-width: 0;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  column-gap: 9px;
  align-items: center;
}

.runtime-flow > div > span {
  width: 28px;
  height: 28px;
  grid-row: 1 / 3;
  display: grid;
  place-items: center;
  color: var(--wq-muted);
  font-size: 12px;
  font-weight: 700;
  background: var(--wq-surface-raised);
  border: 1px solid var(--wq-border);
  border-radius: 7px;
}

.runtime-flow > div.ready > span {
  color: var(--wq-success);
  background: #ecfdf3;
  border-color: #abefc6;
}

.runtime-flow strong,
.runtime-flow small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-flow strong {
  color: var(--wq-text);
  font-size: 14px;
}

.runtime-flow small {
  color: var(--wq-muted);
  font-size: 12px;
}

.runtime-flow i {
  color: var(--wq-subtle);
  font-style: normal;
  text-align: center;
}

.runtime-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 16px;
  overflow: hidden;
  border: 1px solid var(--wq-border);
}

.runtime-summary > div {
  min-width: 0;
  padding: 15px 18px;
  display: grid;
  gap: 4px;
  border-right: 1px solid var(--wq-border);
}

.runtime-summary > div:last-child {
  border-right: 0;
}

.runtime-summary span,
.runtime-summary small {
  color: var(--wq-muted);
  font-size: 12px;
}

.runtime-summary strong {
  color: var(--wq-text);
  font-size: 22px;
  line-height: 1.25;
}

.runtime-summary .summary-time {
  font-size: 15px;
  line-height: 1.6;
}

.runtime-content {
  min-height: 360px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 290px;
  gap: 16px;
  align-items: start;
}

.runtime-table-panel,
.runtime-boundary {
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  box-shadow: var(--wq-shadow-sm);
}

.runtime-table-panel {
  overflow: hidden;
}

.sync-actions {
  display: inline-flex;
  gap: 6px;
}

.sync-history-panel {
  margin-top: 16px;
  overflow: hidden;
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  box-shadow: var(--wq-shadow-sm);
}

.runtime-entity-panel {
  min-width: 0;
  overflow: hidden;
  background: var(--wq-surface);
  border: 1px solid var(--wq-border);
  border-radius: var(--wq-radius);
  box-shadow: var(--wq-shadow-sm);
}

.runtime-view-heading {
  min-height: 68px;
}

.view-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.view-actions .el-select {
  width: 190px;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  white-space: nowrap;
}

.row-actions :deep(.el-button) {
  width: 30px;
  height: 30px;
  padding: 0;
  margin: 0;
}

.runtime-data-table {
  width: 100%;
}

.runtime-data-table code {
  display: block;
  overflow: hidden;
  color: #344054;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.instance-pagination {
  min-height: 58px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 18px;
  padding: 9px 16px;
  border-top: 1px solid var(--wq-border);
  background: var(--wq-surface);
}

.instance-pagination > span {
  color: var(--wq-muted);
  font-size: 12px;
  white-space: nowrap;
}

.audit-field-list,
.state-change-list {
  display: grid;
  gap: 7px;
  padding: 4px 0;
}

.audit-field-row,
.state-change-row {
  min-width: 0;
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: start;
  gap: 8px;
}

.audit-field-key {
  min-height: 22px;
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  color: #475467;
  background: #f2f4f7;
  border: 1px solid #d0d5dd;
  border-radius: 5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 650;
  line-height: 18px;
  white-space: nowrap;
}

.audit-field-key.tone-status { color: #1d4ed8; background: #eff6ff; border-color: #bfdbfe; }
.audit-field-key.tone-time { color: #0e7090; background: #ecfdff; border-color: #a5f0fc; }
.audit-field-key.tone-number { color: #067647; background: #ecfdf3; border-color: #abefc6; }
.audit-field-key.tone-text { color: #b54708; background: #fff7ed; border-color: #fed7aa; }
.audit-field-key.tone-reference { color: #5925dc; background: #f4f3ff; border-color: #d9d6fe; }
.audit-field-key.tone-category { color: #c01048; background: #fff1f3; border-color: #fecdd6; }

.audit-field-value {
  min-width: 0;
  padding-top: 1px;
  color: #344054;
  font-size: 13px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.state-change-values {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 16px minmax(0, 1fr);
  align-items: start;
  gap: 5px;
}

.state-value {
  min-width: 0;
  padding: 2px 6px;
  color: #475467;
  background: #f2f4f7;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.state-value.is-after {
  color: #067647;
  background: #ecfdf3;
}

.state-arrow {
  color: var(--wq-subtle);
  font-size: 12px;
  line-height: 22px;
  text-align: center;
}

.audit-empty {
  color: var(--wq-subtle);
}

.compact-audit-list,
.compact-state-list {
  gap: 5px;
  padding: 2px 0;
}

.compact-audit-list .audit-field-row,
.compact-state-list .state-change-row {
  gap: 7px;
}

.compact-audit-list .audit-field-value,
.compact-state-list .state-value {
  font-size: 12px;
}

.object-property-list {
  position: relative;
  gap: 5px;
  padding: 8px 10px;
  background: #f8fbff;
  border: 1px solid #7489ca;
  border-radius: 6px;
}

.object-property-trigger {
  transition: border-color 150ms ease, background-color 150ms ease, transform 150ms ease;
}

.object-property-trigger:hover {
  background: #eff8ff;
  border-color: var(--wq-primary);
  transform: translateY(-1px);
}

.object-property-trigger:focus-visible {
  outline: 2px solid var(--wq-primary);
  outline-offset: 2px;
}

.object-property-preview-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 2px;
  color: #344054;
  font-size: 11px;
  font-weight: 680;
}

.object-property-preview-heading small {
  color: var(--wq-primary-strong);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
}

.object-property-value {
  min-width: 0;
  display: block;
  overflow: hidden;
  cursor: help;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.object-property-more {
  padding-top: 1px;
  color: var(--wq-primary-strong);
  cursor: help;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.5;
}

:global(.object-property-tooltip.el-popper) {
  max-width: min(680px, calc(100vw - 40px));
  padding: 0 !important;
  overflow: hidden;
  color: #182230;
  background: #fff;
  border: 1px solid var(--wq-border-strong) !important;
  border-radius: 8px !important;
  box-shadow: 0 16px 36px rgba(16, 24, 40, 0.18), 0 3px 8px rgba(16, 24, 40, 0.1) !important;
  line-height: 1.6;
  overflow-wrap: anywhere;
  white-space: normal;
}

.object-property-tooltip-content {
  overflow: hidden;
}

.object-property-tooltip-heading {
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
  color: #344054;
  background: #eef4fb;
  border-bottom: 1px solid #d0d5dd;
  font-size: 12px;
  font-weight: 700;
}

.object-property-tooltip-heading b {
  min-height: 20px;
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
  color: #175cd3;
  background: #eff8ff;
  border: 1px solid #b2ddff;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
}

.object-property-tooltip-list {
  min-width: min(420px, calc(100vw - 56px));
  max-width: min(640px, calc(100vw - 56px));
  max-height: min(420px, calc(100vh - 120px));
  gap: 0;
  padding: 7px 12px 9px;
  overflow: auto;
}

.object-property-tooltip-list .audit-field-row {
  min-height: 34px;
  grid-template-columns: minmax(120px, max-content) minmax(0, 1fr);
  gap: 10px;
  padding: 5px 0;
  border-bottom: 1px solid #eaecf0;
}

.object-property-tooltip-list .audit-field-row:last-child {
  border-bottom: 0;
}

.object-property-tooltip-list .audit-field-value {
  padding-top: 2px;
  color: #182230;
  font-size: 13px;
  font-weight: 560;
  line-height: 1.55;
}

:global(.object-property-tooltip.el-popper .el-popper__arrow::before) {
  background: #fff;
  border-color: var(--wq-border-strong);
}

:global(.object-property-popover-fade-enter-active),
:global(.object-property-popover-fade-leave-active) {
  transition: opacity 160ms ease, transform 160ms cubic-bezier(0.22, 1, 0.36, 1);
  transform-origin: top left;
}

:global(.object-property-popover-fade-enter-from),
:global(.object-property-popover-fade-leave-to) {
  opacity: 0;
  transform: translateY(6px) scale(0.98);
}

.form-grid {
  display: grid;
  gap: 2px 16px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.form-grid :deep(.el-select),
.form-grid :deep(.el-input-number),
.form-grid :deep(.el-date-editor) {
  width: 100%;
}

.panel-heading {
  min-height: 72px;
  padding: 13px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--wq-border);
}

.panel-heading h3,
.runtime-boundary h3 {
  color: var(--wq-text);
  font-size: 15px;
}

.panel-heading p {
  margin-top: 4px;
  color: var(--wq-muted);
  font-size: 12px;
}

.primary-cell,
.runtime-table :deep(.cell) {
  display: grid;
  gap: 4px;
}

.primary-cell code {
  width: fit-content;
  color: #31506f;
  font-size: 12px;
}

.cell-note {
  color: var(--wq-muted);
  font-size: 12px;
}

.runtime-boundary {
  padding: 17px;
}

.runtime-boundary ul {
  list-style: none;
  margin: 13px 0 16px;
  border-top: 1px solid var(--wq-border);
}

.runtime-boundary li {
  padding: 11px 0;
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 8px;
  border-bottom: 1px solid var(--wq-border);
}

.runtime-boundary li b {
  color: var(--wq-warning);
  font-size: 12px;
}

.runtime-boundary li.available b {
  color: var(--wq-success);
}

.runtime-boundary li span {
  color: #344054;
  font-size: 13px;
}

@media (max-width: 980px) {
  .runtime-flow {
    grid-template-columns: 1fr 18px 1fr;
    row-gap: 14px;
  }

  .runtime-flow > i:nth-of-type(2) {
    display: none;
  }

  .runtime-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .runtime-summary > div:nth-child(2) {
    border-right: 0;
  }

  .runtime-summary > div:nth-child(-n + 2) {
    border-bottom: 1px solid var(--wq-border);
  }

  .runtime-content {
    grid-template-columns: 1fr;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .page-header,
  .header-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .domain-select {
    width: min(100%, 360px);
  }

  .header-actions,
  .view-actions {
    width: 100%;
  }

  .view-actions {
    justify-content: flex-start;
  }

  .view-actions .el-select {
    width: min(100%, 280px);
  }

  .runtime-flow {
    grid-template-columns: 1fr;
  }

  .runtime-flow > i {
    display: none;
  }

  .runtime-summary {
    grid-template-columns: 1fr;
  }

  .runtime-summary > div {
    border-right: 0;
    border-bottom: 1px solid var(--wq-border);
  }

  .runtime-entity-panel {
    overflow-x: auto;
  }

  .runtime-data-table {
    min-width: 840px;
  }

  .instance-pagination {
    min-width: 840px;
    justify-content: flex-start;
    overflow-x: auto;
  }

  .object-property-tooltip-list {
    min-width: min(300px, calc(100vw - 40px));
    max-width: calc(100vw - 40px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .object-property-trigger {
    transition: none;
  }

  .object-property-trigger:hover {
    transform: none;
  }

  :global(.object-property-popover-fade-enter-active),
  :global(.object-property-popover-fade-leave-active) {
    transition: none;
  }
}
</style>
