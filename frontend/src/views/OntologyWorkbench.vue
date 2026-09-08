<template>
  <div class="ontology-page" v-loading="loading" :aria-busy="loading">
    <header class="page-toolbar">
      <div class="title-group">
        <h2>业务本体与动作</h2>
        <p v-if="currentDomain">{{ currentDomain.name }} · 定义业务对象、关系、状态和可执行动作</p>
      </div>
      <div class="toolbar-actions">
        <div class="model-version-status" aria-label="本体版本状态">
          <el-tag v-if="summary?.latest_release" type="success" effect="plain">
            V{{ summary.latest_release.version }} 已发布
          </el-tag>
          <el-tag v-else type="info" effect="plain">未发布</el-tag>
        </div>
        <input v-if="canManage" ref="importInput" class="file-input" type="file" accept="application/json,.json" tabindex="-1" aria-hidden="true" @change="handleImport" />
        <el-button v-if="canManage" :icon="CircleCheck" :disabled="!domainId" @click="handleValidate">
          校验模型
        </el-button>
        <el-dropdown v-if="canManage" trigger="click" @command="handleModelCommand">
          <el-button class="model-more-button" :icon="MoreFilled" :disabled="!domainId">
            更多
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="import" :icon="FolderOpened">导入本体包</el-dropdown-item>
              <el-dropdown-item command="export" :icon="Download">导出本体包</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button v-if="canManage" type="primary" :icon="Upload" :disabled="!domainId" @click="handlePublish">
          发布本体版本
        </el-button>
        <el-tag v-else type="info" effect="plain">业务视图 · 只读建模</el-tag>
      </div>
    </header>

    <el-empty v-if="!loading && !domainId" description="暂无可用领域" />

    <template v-else-if="domainId">
      <section class="metric-strip" aria-label="企业模型资产概览">
        <button
          v-for="metric in metrics"
          :key="metric.label"
          type="button"
          class="metric-item"
          :aria-label="`${metric.label} ${metric.value}`"
          @click="handleMetricClick(metric.target)"
        >
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <el-icon aria-hidden="true"><component :is="metric.icon" /></el-icon>
        </button>
      </section>

      <el-tabs v-model="activeTab" class="workspace-tabs" @tab-change="handleTabChange">
        <el-tab-pane label="本体图谱" name="graph">
          <section class="graph-panel">
            <div class="graph-guide" role="note" aria-label="本体图谱阅读提示">
              <div class="graph-guide-heading">
                <strong>怎么看这张图</strong>
                <span>这里只画对象类型和业务动作，不是审批流程图</span>
              </div>
              <div class="graph-guide-items">
                <span><b>对象</b>实体或业务记录，如客户、贷款申请单</span>
                <span><b>关系</b>对象之间怎么连接</span>
                <span><b>动作</b>对对象执行的处理，如审批、催收</span>
                <span><b>事件/状态</b>记录发生过什么、现在到哪一步</span>
              </div>
              <div class="graph-guide-example">
                <span class="guide-object">贷款申请单 = 对象</span>
                <span class="guide-state">审批状态 = 状态</span>
                <span class="guide-action">审批贷款申请 = 动作</span>
              </div>
            </div>
            <div ref="graphElement" class="ontology-graph" role="img" :aria-label="graphAriaLabel" />
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
              <div class="section-heading">
                <div class="section-heading-main">
                  <strong>对象类型</strong>
                  <span class="section-count">{{ objectTypes.length }} 项</span>
                </div>
                <span class="section-heading-note">定义实体/业务记录、属性和数据来源</span>
              </div>
              <el-button v-if="canManage" type="primary" :icon="Plus" @click="openObjectTypeDialog()">
                新建对象
              </el-button>
            </div>
            <el-table class="ontology-table" :data="objectTypes" row-key="id" height="100%">
              <el-table-column type="expand" width="42">
                <template #default="{ row }">
                  <div class="property-grid">
                    <div class="property-grid-heading">
                      <strong>属性定义</strong>
                      <span>{{ row.properties.length }} 项</span>
                    </div>
                    <div class="property-grid-body">
                      <div v-for="property in row.properties" :key="property.property_key" class="property-row">
                        <code>{{ property.property_key }}</code>
                        <span>{{ property.name }}</span>
                        <el-tag size="small" effect="plain">{{ typeLabel(property.data_type) }}</el-tag>
                        <el-tag v-if="property.property_key === row.primary_property" size="small" type="warning">主属性</el-tag>
                        <el-tag v-if="property.required" size="small" type="danger" effect="plain">必填</el-tag>
                      </div>
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
              <div class="section-heading">
                <div class="section-heading-main">
                  <strong>关系类型</strong>
                  <span class="section-count">{{ linkTypes.length }} 项</span>
                </div>
                <span class="section-heading-note">描述对象之间的业务连接和基数</span>
              </div>
              <el-button v-if="canManage" type="primary" :icon="Plus" @click="openLinkTypeDialog()">新建关系</el-button>
            </div>
            <el-table class="ontology-table" :data="linkTypes" height="100%">
              <el-table-column label="关系" min-width="200">
                <template #default="{ row }">
                  <div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.link_key }}</code></div>
                </template>
              </el-table-column>
              <el-table-column label="关系路径" min-width="380">
                <template #default="{ row }">
                  <div class="relation-flow">
                    <div class="relation-endpoint">
                      <span>起点</span>
                      <code>{{ row.source_object_key }}</code>
                    </div>
                    <el-icon class="relation-arrow"><ArrowRight /></el-icon>
                    <div class="relation-endpoint">
                      <span>终点</span>
                      <code>{{ row.target_object_key }}</code>
                    </div>
                  </div>
                </template>
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
              <div class="section-heading">
                <div class="section-heading-main">
                  <strong>业务动作</strong>
                  <span class="section-count">{{ actionTypes.length }} 项</span>
                </div>
                <span class="section-heading-note">定义可执行动作、权限和状态效果</span>
              </div>
              <el-button v-if="canManage" type="primary" :icon="Plus" @click="openActionTypeDialog()">新建动作</el-button>
            </div>
            <el-table class="ontology-table" :data="actionTypes" height="100%">
              <el-table-column label="动作" min-width="210">
                <template #default="{ row }">
                  <div class="primary-cell"><strong>{{ row.name }}</strong><code>{{ row.action_key }}</code></div>
                </template>
              </el-table-column>
              <el-table-column label="目标对象" min-width="140">
                <template #default="{ row }"><code>{{ row.target_object_key }}</code></template>
              </el-table-column>
              <el-table-column label="配置概览" width="194">
                <template #default="{ row }">
                  <div class="action-counts" aria-label="动作组成">
                    <span><b>{{ row.parameters.length }}</b><small>参数</small></span>
                    <span><b>{{ row.preconditions.length }}</b><small>条件</small></span>
                    <span><b>{{ row.effects.length }}</b><small>效果</small></span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="授权角色" min-width="140">
                <template #default="{ row }">
                  <div v-if="row.allowed_roles?.length" class="role-tags">
                    <el-tag v-for="role in row.allowed_roles" :key="role" size="small" effect="plain">{{ role }}</el-tag>
                  </div>
                  <span v-else class="muted">未配置</span>
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
                      tabindex="0"
                      :aria-label="row.requires_approval ? '需要审批单号，执行时必须填写审批单号' : '无需审批单号，执行时仍受角色、状态和前置条件限制'"
                    >
                      {{ row.requires_approval ? '需审批单号' : '无需审批单号' }}
                    </el-tag>
                  </el-tooltip>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="120" fixed="right" align="center" header-align="center">
                <template #default="{ row }">
                  <div class="table-actions">
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

      </el-tabs>
    </template>

    <el-dialog v-model="objectTypeDialog" :title="objectTypeForm.id ? '编辑对象类型' : '新建对象类型'" width="900px" @opened="focusControl(objectKeyInput)">
      <el-form :model="objectTypeForm" label-position="top">
        <div class="form-grid three">
          <el-form-item label="对象标识" required><el-input ref="objectKeyInput" v-model="objectTypeForm.object_key" placeholder="如 WorkOrder" /></el-form-item>
          <el-form-item label="业务名称" required><el-input v-model="objectTypeForm.name" /></el-form-item>
          <el-form-item label="状态"><el-select v-model="objectTypeForm.status"><el-option label="草稿" value="draft" /><el-option label="生效" value="active" /><el-option label="废弃" value="deprecated" /></el-select></el-form-item>
        </div>
        <el-form-item label="业务定义">
          <el-input v-model="objectTypeForm.description" type="textarea" :rows="2" />
          <span class="form-help">填写对象代表什么，例如“贷款申请单”；流程步骤请配置为动作或事件。</span>
        </el-form-item>
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
            <el-button text type="danger" :icon="Delete" :aria-label="`移除属性 ${property.name || property.property_key || index + 1}`" title="移除属性" @click="removeProperty(index)" />
          </div>
        </div>
      </el-form>
      <template #footer><el-button @click="objectTypeDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveObjectType">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="linkTypeDialog" :title="linkTypeForm.id ? '编辑关系类型' : '新建关系类型'" width="720px" @opened="focusControl(linkKeyInput)">
      <el-form :model="linkTypeForm" label-position="top">
        <div class="form-grid two"><el-form-item label="关系标识" required><el-input ref="linkKeyInput" v-model="linkTypeForm.link_key" /></el-form-item><el-form-item label="关系名称" required><el-input v-model="linkTypeForm.name" /></el-form-item></div>
        <div class="form-grid two"><el-form-item label="起点对象" required><el-select v-model="linkTypeForm.source_object_key"><el-option v-for="item in objectTypes" :key="item.id" :label="item.name" :value="item.object_key" /></el-select></el-form-item><el-form-item label="终点对象" required><el-select v-model="linkTypeForm.target_object_key"><el-option v-for="item in objectTypes" :key="item.id" :label="item.name" :value="item.object_key" /></el-select></el-form-item></div>
        <div class="form-grid two"><el-form-item label="关系基数"><el-select v-model="linkTypeForm.cardinality"><el-option v-for="item in cardinalities" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item><el-form-item label="状态"><el-select v-model="linkTypeForm.status"><el-option label="草稿" value="draft" /><el-option label="生效" value="active" /><el-option label="废弃" value="deprecated" /></el-select></el-form-item></div>
        <el-form-item label="业务定义"><el-input v-model="linkTypeForm.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="linkTypeDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveLinkType">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="actionTypeDialog" :title="actionTypeForm.id ? '编辑动作类型' : '新建动作类型'" width="960px" @opened="focusControl(actionKeyInput)">
      <el-form :model="actionTypeForm" label-position="top">
        <div class="form-grid three"><el-form-item label="动作标识" required><el-input ref="actionKeyInput" v-model="actionTypeForm.action_key" /></el-form-item><el-form-item label="动作名称" required><el-input v-model="actionTypeForm.name" /></el-form-item><el-form-item label="目标对象" required><el-select v-model="actionTypeForm.target_object_key"><el-option v-for="item in objectTypes" :key="item.id" :label="item.name" :value="item.object_key" /></el-select></el-form-item></div>
        <el-form-item label="业务定义">
          <el-input v-model="actionTypeForm.description" type="textarea" :rows="2" />
          <span class="form-help">动作建议使用动词描述，例如“审批申请”“发起催收”。</span>
        </el-form-item>
        <div class="form-grid three"><el-form-item label="授权角色"><el-select v-model="actionTypeForm.allowed_roles" multiple><el-option label="管理员" value="admin" /><el-option label="业务用户" value="user" /></el-select></el-form-item><el-form-item label="状态"><el-select v-model="actionTypeForm.status"><el-option label="草稿" value="draft" /><el-option label="生效" value="active" /><el-option label="废弃" value="deprecated" /></el-select></el-form-item><el-form-item label="审批单号要求"><el-switch v-model="actionTypeForm.requires_approval" active-text="需要审批单号" inactive-text="不要求审批单号" /></el-form-item></div>
        <div class="subsection-title"><strong>动作参数</strong><el-button text type="primary" :icon="Plus" @click="addActionParameter">添加参数</el-button></div>
        <div class="builder-list"><div v-for="(parameter, index) in actionTypeForm.parameters" :key="index" class="builder-row parameter-builder"><el-input v-model="parameter.parameter_key" placeholder="参数标识" /><el-input v-model="parameter.name" placeholder="业务名称" /><el-select v-model="parameter.data_type"><el-option v-for="item in propertyTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select><el-input v-model="parameter.options_text" placeholder="选项，逗号分隔" /><el-checkbox v-model="parameter.required">必填</el-checkbox><el-button text type="danger" :icon="Delete" :aria-label="`移除动作参数 ${parameter.name || parameter.parameter_key || index + 1}`" @click="actionTypeForm.parameters.splice(index, 1)" /></div></div>
        <div class="subsection-title"><strong>前置条件</strong><el-button text type="primary" :icon="Plus" @click="addPrecondition">添加条件</el-button></div>
        <div class="builder-list"><div v-for="(condition, index) in actionTypeForm.preconditions" :key="index" class="builder-row condition-builder"><el-select v-model="condition.property" placeholder="对象属性"><el-option v-for="p in targetProperties" :key="p.property_key" :label="p.name" :value="p.property_key" /></el-select><el-select v-model="condition.operator"><el-option v-for="item in operators" :key="item.value" :label="item.label" :value="item.value" /></el-select><el-input v-model="condition.value_text" placeholder="期望值或 $param.x" /><el-input v-model="condition.message" placeholder="不满足时提示" /><el-button text type="danger" :icon="Delete" :aria-label="`移除前置条件 ${index + 1}`" @click="actionTypeForm.preconditions.splice(index, 1)" /></div></div>
        <div class="subsection-title"><strong>状态效果</strong><el-button text type="primary" :icon="Plus" @click="addEffect">添加效果</el-button></div>
        <div class="builder-list"><div v-for="(effect, index) in actionTypeForm.effects" :key="index" class="builder-row effect-builder"><el-select v-model="effect.property" placeholder="写入属性"><el-option v-for="p in targetProperties" :key="p.property_key" :label="p.name" :value="p.property_key" /></el-select><el-input v-model="effect.value_text" placeholder="常量、$param.x、$now、$user.name" /><el-button text type="danger" :icon="Delete" :aria-label="`移除状态效果 ${index + 1}`" @click="actionTypeForm.effects.splice(index, 1)" /></div></div>
      </el-form>
      <template #footer><el-button @click="actionTypeDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveActionType">保存</el-button></template>
    </el-dialog>

    <el-drawer v-model="validationDrawer" title="本体校验" size="520px">
      <div v-if="validationResult" class="validation-result" role="status" aria-live="polite">
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
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, toRefs, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  deleteOntologyActionType,
  deleteOntologyLinkType,
  deleteOntologyObjectType,
  exportOntologyBundle,
  fetchOntologyActionTypes,
  fetchOntologyLinkTypes,
  fetchOntologyObjectTypes,
  fetchOntologyReleases,
  fetchOntologySummary,
  importOntologyBundle,
  publishOntology,
  saveOntologyActionType,
  saveOntologyLinkType,
  saveOntologyObjectType,
  validateOntology,
  type OntologyActionType,
  type OntologyLinkType,
  type OntologyObjectType,
  type OntologyProperty,
  type OntologyPropertyType,
  type OntologySummary,
  type SemanticDomain,
} from '../api'
import { isAdmin } from '../stores/auth'
import { formatDateTime } from '../utils/datetime'
import { ArrowRight, CircleCheck, Delete, Download, Edit, FolderOpened, MoreFilled, Plus, Upload } from '@element-plus/icons-vue'

const props = defineProps<{
  domainId: number | null
  currentDomain: SemanticDomain | null
}>()
const router = useRouter()
const { domainId, currentDomain } = toRefs(props)
const summary = ref<OntologySummary | null>(null)
const objectTypes = ref<OntologyObjectType[]>([])
const linkTypes = ref<OntologyLinkType[]>([])
const actionTypes = ref<OntologyActionType[]>([])
const releases = ref<Record<string, unknown>[]>([])
const activeTab = ref('graph')
const loading = ref(false)
const saving = ref(false)
const graphElement = ref<HTMLElement>()
const importInput = ref<HTMLInputElement>()
type FocusableControl = { focus: () => void }
const objectKeyInput = ref<FocusableControl>()
const linkKeyInput = ref<FocusableControl>()
const actionKeyInput = ref<FocusableControl>()
let graph: echarts.ECharts | null = null
let graphResizeObserver: ResizeObserver | null = null
let observedGraphElement: HTMLElement | null = null
let graphSize = { width: 0, height: 0 }
let resizeFrame: number | null = null

const canManage = computed(() => isAdmin())
const metrics = computed(() => [
  { label: '对象类型', value: summary.value?.counts.object_types || 0, icon: 'Box', target: 'objects' },
  { label: '关系类型', value: summary.value?.counts.link_types || 0, icon: 'Connection', target: 'relations' },
  { label: '业务动作', value: summary.value?.counts.action_types || 0, icon: 'Operation', target: 'actions' },
  { label: '对象实例', value: summary.value?.counts.source_objects || summary.value?.counts.objects || 0, icon: 'DataBoard', target: 'twin-instances' },
  { label: '动作执行记录', value: summary.value?.counts.action_runs || 0, icon: 'Clock', target: 'twin-audit' },
])
const graphAriaLabel = computed(() => (
  `本体图谱：${objectTypes.value.length} 个对象类型，${linkTypes.value.length} 个关系类型，`
  + `${actionTypes.value.length} 个业务动作。详细定义可通过对象类型、关系类型和动作类型页签查看。`
))

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
const validationDrawer = ref(false)
const validationResult = ref<any>(null)

const targetProperties = computed<OntologyProperty[]>(() => objectTypes.value.find((item) => item.object_key === actionTypeForm.target_object_key)?.properties || [])

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
function parseValue(value: string) {
  const text = String(value ?? '').trim(); if (!text) return ''
  if (text.startsWith('$')) return text
  if (text === 'true') return true; if (text === 'false') return false; if (text === 'null') return null
  if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text)
  if ((text.startsWith('[') && text.endsWith(']')) || (text.startsWith('{') && text.endsWith('}'))) { try { return JSON.parse(text) } catch { return text } }
  return text
}
function errorMessage(error: any) { return error?.response?.data?.detail?.message || error?.response?.data?.detail || error?.message || '操作失败' }

function focusControl(control: FocusableControl | undefined) {
  requestAnimationFrame(() => control?.focus())
}

function handleMetricClick(target: string) {
  if (target === 'twin-instances' || target === 'twin-audit') {
    void router.push({
      path: '/twin-runtime',
      query: {
        domain_id: domainId.value ? String(domainId.value) : undefined,
        view: target === 'twin-instances' ? 'instances' : 'audit',
      },
    })
    return
  }
  activeTab.value = target
  if (target === 'graph') void nextTick(renderGraph)
}

async function refreshAll() {
  if (!domainId.value) return
  loading.value = true
  try {
    const id = domainId.value
    const [nextSummary, nextObjects, nextLinks, nextActions, nextReleases] = await Promise.all([
      fetchOntologySummary(id), fetchOntologyObjectTypes(id), fetchOntologyLinkTypes(id),
      fetchOntologyActionTypes(id), fetchOntologyReleases(id),
    ])
    if (domainId.value !== id) return
    summary.value = nextSummary; objectTypes.value = nextObjects; linkTypes.value = nextLinks
    actionTypes.value = nextActions; releases.value = nextReleases
    await nextTick(); renderGraph()
  } catch (error) { ElMessage.error(String(errorMessage(error))) } finally { loading.value = false }
}
async function handleTabChange(name: any) {
  if (name === 'graph') nextTick(renderGraph)
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
  graph ||= echarts.init(element)
  graph.resize({ width, height })
  const nodes = objectTypes.value.map((item) => ({ id: item.object_key, name: item.name, value: `对象类型 · ${item.object_key}\n${item.properties.length} 个属性`, symbolSize: 78, category: 0 }))
  actionTypes.value.forEach((item) => nodes.push({ id: `action:${item.action_key}`, name: item.name, value: `业务动作 · ${item.action_key}`, symbolSize: 58, category: 1 } as any))
  const edges: any[] = linkTypes.value.map((item) => ({ source: item.source_object_key, target: item.target_object_key, name: item.name }))
  actionTypes.value.forEach((item) => edges.push({ source: `action:${item.action_key}`, target: item.target_object_key, name: '作用于', lineStyle: { type: 'dashed' } }))
  const graphTooltip = (p: any) => {
    if (p.dataType === 'edge') return p.data.name
    const kind = p.data.category === 0 ? '对象类型（实体/业务记录）' : '业务动作（处理行为）'
    return `${p.data.name}<br/>${kind}<br/>${String(p.data.value || '').replace('\n', '<br/>')}`
  }
  graph.setOption({ tooltip: { formatter: graphTooltip }, legend: [{ data: ['对象（实体/记录）', '动作（处理行为）'], bottom: 12 }], series: [{ type: 'graph', layout: 'force', roam: true, draggable: true, top: 24, right: 24, bottom: 60, left: 24, categories: [{ name: '对象（实体/记录）', itemStyle: { color: '#167c5a' } }, { name: '动作（处理行为）', itemStyle: { color: '#c36b18' } }], data: nodes, links: edges, label: { show: true, color: '#182230', fontSize: 13, position: 'bottom' }, edgeLabel: { show: true, formatter: (params: any) => params.data?.name || '', fontSize: 11, color: '#475467' }, lineStyle: { color: '#98a2b3', width: 1.5, curveness: 0.1 }, force: { initLayout: 'circular', repulsion: 360, edgeLength: 170, gravity: 0.08 }, emphasis: { focus: 'adjacency', lineStyle: { width: 3 } } }] }, true)
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
function handleModelCommand(command: string) {
  if (command === 'import') importInput.value?.click()
  else if (command === 'export') void handleExport()
}
async function handlePublish() { if (!domainId.value) return; try { await ElMessageBox.confirm('发布后将生成不可变版本，可供业务动作运行。', '发布 Ontology', { type: 'warning', confirmButtonText: '发布' }); const result = await publishOntology(domainId.value, { description: '从 Ontology 工作台发布' }); ElMessage.success(`V${result.version} 已发布`); await refreshAll() } catch (error: any) { if (error === 'cancel' || error === 'close') return; const detail = error?.response?.data?.detail; if (detail?.errors) { validationResult.value = detail; validationDrawer.value = true } else ElMessage.error(String(errorMessage(error))) } }

function handleResize() { graph?.resize() }
watch(domainId, () => {
  activeTab.value = 'graph'
  if (domainId.value) {
    void refreshAll()
    return
  }
  summary.value = null
  objectTypes.value = []
  linkTypes.value = []
  actionTypes.value = []
  releases.value = []
})
onMounted(async () => {
  window.addEventListener('resize', handleResize)
  if (domainId.value) await refreshAll()
})
onBeforeUnmount(() => {
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
.ontology-page { width: 100%; max-width: var(--wq-page-max-width); height: 100%; min-height: 0; min-width: 0; margin: 0 auto; padding-inline: var(--wq-page-gutter); padding-bottom: var(--wq-page-bottom-gap); display: flex; flex-direction: column; overflow: hidden; color: var(--wq-text); }
.page-toolbar { min-height: 66px; display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; padding-bottom: 14px; border-bottom: 1px solid var(--wq-border); }
.toolbar-actions, .section-toolbar, .subsection-title { display: flex; align-items: center; }
.file-input { display: none; }
.title-group { min-width: 0; }.title-group h2 { color: var(--wq-text); font-size: 22px; line-height: 1.25; }.title-group p { margin-top: 8px; color: var(--wq-muted); font-size: 14px; }.toolbar-actions { justify-content: flex-end; gap: 8px; flex-wrap: nowrap; min-width: 0; }.toolbar-actions :deep(.el-button) { margin-left: 0; white-space: nowrap; }.toolbar-actions :deep(.el-dropdown) { flex: 0 0 auto; }.model-version-status { display: inline-flex; flex: 0 0 auto; align-items: center; min-height: 32px; padding-right: 4px; }.model-more-button { min-width: 76px; }
.metric-strip { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 1px; margin: 14px 0 8px; background: var(--wq-border); border: 1px solid var(--wq-border); border-radius: 7px; overflow: hidden; }.metric-item { position: relative; min-height: 72px; padding: 13px 16px; border: 0; color: inherit; font: inherit; text-align: left; cursor: pointer; appearance: none; background: var(--wq-surface); transition: background-color 140ms ease; }.metric-item:hover { background: var(--wq-primary-soft); }.metric-item:focus-visible { position: relative; z-index: 1; outline: 2px solid var(--wq-primary); outline-offset: -2px; }.metric-item span { display: block; color: var(--wq-muted); font-size: 12px; }.metric-item strong { display: block; margin-top: 3px; font-size: 23px; font-weight: 680; }.metric-item .el-icon { position: absolute; right: 14px; top: 22px; color: var(--wq-subtle); font-size: 24px; }
.workspace-tabs { min-width: 0; min-height: 0; flex: 1; }.workspace-tabs :deep(.el-tabs__header) { margin: 0; }.workspace-tabs :deep(.el-tabs__content) { min-width: 0; height: calc(100% - 40px); }.workspace-tabs :deep(.el-tab-pane) { min-width: 0; height: 100%; }.graph-panel { position: relative; display: grid; grid-template-rows: auto minmax(0, 1fr); min-width: 0; height: 100%; min-height: 0; overflow: hidden; background: #fff; border-bottom: 1px solid var(--wq-border); }.ontology-graph { width: 100%; height: 100%; min-height: 0; }.graph-empty { position: absolute; inset: 0; background: #fff; }
.graph-guide { display: grid; gap: 8px; padding: 12px 16px 11px; border-bottom: 1px solid #dbe4ef; background: linear-gradient(90deg, #f5f9ff 0%, #fbfdff 100%); color: var(--wq-muted); font-size: 12px; line-height: 1.45; }
.graph-guide-heading { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.graph-guide-heading strong { color: var(--wq-text); font-size: 13px; font-weight: 700; }
.graph-guide-heading span { color: var(--wq-muted); }
.graph-guide-items, .graph-guide-example { display: flex; align-items: center; gap: 8px 16px; flex-wrap: wrap; }
.graph-guide-items > span { white-space: nowrap; }
.graph-guide-items b { color: var(--wq-text); font-weight: 700; }
.graph-guide-example > span { display: inline-flex; align-items: center; min-height: 23px; padding: 0 7px; border: 1px solid #d0d5dd; border-radius: 5px; background: #fff; color: var(--wq-text); font-size: 11px; white-space: nowrap; }
.graph-guide-example .guide-object { border-color: #a6e4c9; color: #067647; background: #effaf4; }
.graph-guide-example .guide-state { border-color: #b2ddff; color: #175cd3; background: #eff8ff; }
.graph-guide-example .guide-action { border-color: #f7c58b; color: #b54708; background: #fff7ed; }
.table-section { height: 100%; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; background: var(--wq-surface); }.section-toolbar { height: auto; min-height: 54px; justify-content: space-between; border-bottom: 1px solid var(--wq-border); }.section-toolbar > div { display: flex; align-items: baseline; gap: 8px; }.section-toolbar span { color: var(--wq-muted); font-size: 12px; }.ontology-table { width: 100%; min-height: 0; height: 100%; }
.sync-status-cell { display: flex; flex-direction: column; align-items: flex-start; gap: 5px; min-width: 0; }.sync-status-cell small { color: var(--wq-muted); font-size: 11px; white-space: nowrap; }.muted { color: var(--wq-muted); }.source-query-input :deep(textarea) { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 1.6; }
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
.primary-cell { display: flex; flex-direction: column; gap: 3px; }.primary-cell strong { font-weight: 620; }.primary-cell code, code { color: #344054; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }.property-grid { display: grid; gap: 5px; padding: 12px 58px; background: #f8fafc; }.property-row { display: grid; grid-template-columns: minmax(130px, 1fr) minmax(140px, 1fr) 80px 70px 60px; align-items: center; gap: 10px; min-height: 30px; }
.form-grid { display: grid; gap: 14px; }.form-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }.form-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }.subsection-title { justify-content: space-between; min-height: 40px; margin-top: 4px; border-bottom: 1px solid var(--wq-border); }.builder-list { display: grid; gap: 7px; margin: 9px 0 14px; }.builder-row { display: grid; align-items: center; gap: 7px; padding: 7px; background: #f7f9fc; border: 1px solid var(--wq-border); border-radius: 6px; }.property-builder { grid-template-columns: 1.2fr 1.2fr 110px 62px 62px 32px; }.parameter-builder { grid-template-columns: 1fr 1fr 105px 1.2fr 62px 32px; }.condition-builder { grid-template-columns: 1fr 110px 1fr 1.2fr 32px; }.effect-builder { grid-template-columns: 1fr 2fr 32px; }
.validation-result section { margin-top: 18px; }.validation-result h4 { margin-bottom: 8px; }.validation-item { display: grid; grid-template-columns: 130px 1fr; gap: 10px; margin-bottom: 7px; padding: 10px; border-left: 3px solid; background: #f8fafc; }.validation-item.error { border-color: var(--wq-danger); }.validation-item.warning { border-color: var(--wq-warning); }
.form-help { display: block; margin-top: 5px; color: var(--wq-muted); font-size: 12px; line-height: 1.45; }
@media (max-width: 1100px) { .page-toolbar { align-items: flex-start; }.toolbar-actions { max-width: 64%; overflow-x: auto; padding-bottom: 2px; scrollbar-width: thin; }.metric-strip { grid-template-columns: repeat(3, 1fr); }.form-grid.three { grid-template-columns: 1fr 1fr; } }
@media (max-width: 760px) { .ontology-page { padding-inline: 16px; padding-bottom: 16px; overflow: auto; }.page-toolbar { flex-direction: column; }.toolbar-actions { width: 100%; max-width: none; justify-content: flex-start; overflow-x: auto; padding-bottom: 4px; }.metric-strip { grid-template-columns: repeat(2, 1fr); }.form-grid.two, .form-grid.three { grid-template-columns: 1fr; }.property-builder, .parameter-builder, .condition-builder, .effect-builder { grid-template-columns: 1fr; }.section-toolbar { flex-wrap: wrap; } }

/* Dense workbench surfaces use hierarchy, not more decoration, to separate scan paths. */
.section-toolbar { gap: 16px; padding: 8px 16px; background: var(--wq-surface); }
.section-toolbar > .section-heading { display: flex; align-items: flex-start; flex-direction: column; gap: 3px; min-width: 0; }
.section-heading-main { display: flex; align-items: baseline; gap: 9px; min-width: 0; }
.section-heading-main strong { color: var(--wq-text); font-size: 14px; font-weight: 680; }
.section-count { color: var(--wq-primary-strong) !important; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px !important; font-weight: 650; }
.section-heading-note { color: var(--wq-muted) !important; font-size: 11px !important; line-height: 1.4; }
.section-toolbar > .el-button { flex: 0 0 auto; }
.ontology-table :deep(.el-table__header-wrapper th.el-table__cell) {
  color: #475467;
  background: #f5f7fa;
  font-size: 12px;
  font-weight: 680;
}
.ontology-table :deep(.el-table__body tr) { transition: background-color 160ms ease; }
.ontology-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: #f5f9ff !important; }
.ontology-table :deep(.el-table__body tr:hover .primary-cell strong) { color: var(--wq-primary-strong); }
.ontology-table :deep(.el-table__body td.el-table__cell) { padding: 11px 0; }
.table-action-btn { border: 1px solid transparent; transition: color 150ms ease, background-color 150ms ease, border-color 150ms ease, transform 150ms ease; }
.table-action-btn:hover { border-color: #b2ddff; }
.table-action-btn:active { transform: scale(0.96); }
.table-action-btn.is-danger:hover { border-color: #fecdca; }

.property-grid { gap: 0; padding: 14px 58px 16px; border-top: 1px solid #e4e7ec; }
.property-grid-heading { display: flex; align-items: baseline; gap: 8px; color: var(--wq-text); font-size: 12px; }
.property-grid-heading span { color: var(--wq-muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.property-grid-body { display: grid; gap: 6px; margin-top: 10px; }
.property-row { min-height: 32px; padding: 3px 0; }

.relation-flow { display: grid; grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr); align-items: center; gap: 8px; min-width: 320px; }
.relation-endpoint { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.relation-endpoint > span { color: var(--wq-muted); font-size: 10px; line-height: 1; }
.relation-endpoint code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.relation-arrow { justify-self: center; color: var(--wq-primary); font-size: 17px; }
.action-counts { display: flex; align-items: stretch; gap: 10px; }
.action-counts > span { display: inline-flex; align-items: baseline; gap: 4px; min-width: 42px; padding: 3px 6px; border-left: 2px solid var(--wq-border-strong); background: #f8fafc; }
.action-counts b { color: var(--wq-text); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
.action-counts small { color: var(--wq-muted); font-size: 10px; }
.role-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.approval-tag { font-weight: 650; }

.ontology-table :deep(.el-table__body-wrapper) { scrollbar-color: #cbd5e1 transparent; scrollbar-width: thin; }

@media (max-width: 960px) {
  .section-heading-note { display: none; }
  .relation-flow { min-width: 280px; }
}

@media (max-width: 760px) {
  .workspace-tabs :deep(.el-tabs__nav-wrap) { overflow-x: auto; }
  .workspace-tabs :deep(.el-tabs__nav) { min-width: max-content; }
  .section-toolbar { align-items: flex-start; padding: 10px 12px; }
  .section-toolbar > .section-heading { flex: 1 1 100%; }
  .section-toolbar > .el-button { margin-left: auto; }
  .ontology-table :deep(.el-table__body-wrapper) { overflow-x: auto; }
  .ontology-table :deep(.el-table__inner-wrapper) { min-width: 760px; }
  .property-grid { padding-inline: 20px; }
  .property-row { grid-template-columns: minmax(110px, 1fr) minmax(120px, 1fr) 70px 60px 50px; gap: 6px; }
  .relation-flow { min-width: 250px; }
  .action-counts { gap: 5px; }
  .action-counts > span { min-width: 36px; padding-inline: 4px; }
}

@media (prefers-reduced-motion: reduce) {
  .ontology-table :deep(.el-table__body tr), .table-action-btn, .metric-item { transition: none; }
  .table-action-btn:active { transform: none; }
}
</style>
