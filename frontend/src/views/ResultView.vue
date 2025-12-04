<template>
  <div class="result-view" v-loading="loading">
    <!-- 系统提示（如风险点截取提示） -->
    <el-alert
      v-for="(notice, index) in result?.notices || []"
      :key="index"
      :title="notice"
      type="info"
      show-icon
      :closable="true"
      style="margin-bottom: 12px;"
    />

    <!-- 顶部信息栏 -->
    <div class="result-header">
      <div class="header-info">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          {{ i18n.labels.back }}
        </el-button>
        <h2>{{ result?.document_name || i18n.labels.reviewResult }}</h2>
        <div class="header-meta">
          <el-tag>{{ materialTypeText }}</el-tag>
          <el-tag v-if="isEnglish" type="success" size="small">EN</el-tag>
          <span>{{ i18n.labels.ourParty }} {{ result?.our_party }}</span>
          <span>{{ i18n.labels.reviewTime }} {{ formatTime(result?.reviewed_at) }}</span>
        </div>
      </div>
      <div class="header-actions">
        <el-tooltip
          :content="redlineDisabledReason"
          :disabled="canExportRedline"
          placement="bottom"
        >
          <span>
            <el-button
              type="success"
              @click="showRedlineDialog = true"
              :disabled="!canExportRedline"
            >
              <el-icon><EditPen /></el-icon>
              {{ i18n.labels.exportRedline }}
            </el-button>
          </span>
        </el-tooltip>
        <el-dropdown @command="handleExport">
          <el-button type="primary">
            <el-icon><Download /></el-icon>
            {{ i18n.labels.export }}
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="excel">{{ isEnglish ? 'Export Excel' : '导出 Excel' }}</el-dropdown-item>
              <el-dropdown-item command="csv">{{ isEnglish ? 'Export CSV' : '导出 CSV' }}</el-dropdown-item>
              <el-dropdown-item command="json">{{ isEnglish ? 'Export JSON' : '导出 JSON' }}</el-dropdown-item>
              <el-dropdown-item command="report">{{ isEnglish ? 'Export Report' : '导出报告' }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- Redline 导出对话框 -->
    <el-dialog
      v-model="showRedlineDialog"
      title="导出修订版 Word"
      width="500px"
    >
      <!-- 如果已有持久化的 Redline 文件，直接显示下载选项 -->
      <div v-if="persistedRedlineInfo" class="redline-dialog-content">
        <el-result
          icon="success"
          title="修订版文档已生成"
          :sub-title="`生成时间：${formatTime(persistedRedlineInfo.generated_at)}`"
        >
          <template #extra>
            <div class="persisted-info">
              <p>应用 <strong>{{ persistedRedlineInfo.applied_count || 0 }}</strong> 条修改</p>
              <p v-if="persistedRedlineInfo.comments_count">添加 <strong>{{ persistedRedlineInfo.comments_count }}</strong> 条批注</p>
            </div>
          </template>
        </el-result>
      </div>

      <!-- 如果没有持久化文件，显示生成选项 -->
      <div v-else class="redline-dialog-content">
        <el-alert
          v-if="!redlinePreview?.can_export && redlinePreview?.reason"
          :title="redlinePreview.reason"
          type="warning"
          show-icon
          :closable="false"
          style="margin-bottom: 16px;"
        />

        <!-- 时间提示 -->
        <el-alert
          v-if="!redlineExportStatus"
          title="提示：生成修订版文档预计需要 2-3 分钟，请耐心等待"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom: 16px;"
        />

        <div class="export-option">
          <div class="option-header">
            <el-icon><Document /></el-icon>
            <span>修改建议（修订标记）</span>
          </div>
          <div class="option-desc">
            将已确认的修改建议以删除线和插入标记形式显示
          </div>
          <div class="option-count">
            已确认 <strong>{{ confirmedCount }}</strong> 条 / 共 {{ redlinePreview?.total_modifications || 0 }} 条
          </div>
        </div>

        <el-divider />

        <div class="export-option">
          <div class="option-header">
            <el-checkbox v-model="includeComments" :disabled="!hasCommentableActions">
              <el-icon><ChatLineSquare /></el-icon>
              <span>行动建议（批注）</span>
            </el-checkbox>
          </div>
          <div class="option-desc">
            将已确认的行动建议作为批注添加到对应风险点的文本位置
          </div>
          <div class="option-count" v-if="redlinePreview">
            已确认 <strong>{{ confirmedActionsCount }}</strong> 条，可添加 <strong>{{ redlinePreview.commentable_actions || 0 }}</strong> 条批注 / 共 {{ redlinePreview.total_actions || 0 }} 条行动建议
          </div>
          <el-alert
            v-if="redlinePreview?.confirmed_actions > 0 && redlinePreview?.commentable_actions === 0"
            title="已确认的行动建议未关联风险点原文，无法生成批注"
            type="info"
            show-icon
            :closable="false"
            style="margin-top: 8px;"
          />
          <el-alert
            v-else-if="redlinePreview?.total_actions > 0 && (redlinePreview?.confirmed_actions || 0) === 0"
            title="请先在行动建议列表中勾选确认要导出的建议"
            type="info"
            show-icon
            :closable="false"
            style="margin-top: 8px;"
          />
        </div>

        <!-- 导出进度显示 -->
        <div v-if="redlineExportStatus" class="export-progress">
          <el-divider />
          <div class="progress-header">
            <span>{{ redlineExportStatus.message }}</span>
            <el-tag v-if="redlineExportStatus.status === 'completed'" type="success" size="small">完成</el-tag>
            <el-tag v-else-if="redlineExportStatus.status === 'failed'" type="danger" size="small">失败</el-tag>
            <el-tag v-else type="info" size="small">{{ redlineExportStatus.progress }}%</el-tag>
          </div>
          <el-progress
            :percentage="redlineExportStatus.progress"
            :status="redlineExportStatus.status === 'completed' ? 'success' : redlineExportStatus.status === 'failed' ? 'exception' : ''"
            :stroke-width="10"
            style="margin-top: 8px;"
          />
          <div v-if="redlineExportStatus.status === 'completed'" class="export-result">
            <p>应用 {{ redlineExportStatus.applied_count }} 条修改，跳过 {{ redlineExportStatus.skipped_count }} 条</p>
            <p v-if="includeComments">添加 {{ redlineExportStatus.comments_added }} 条批注</p>
          </div>
          <div v-if="redlineExportStatus.status === 'failed'" class="export-error">
            <el-alert :title="redlineExportStatus.error || '导出失败'" type="error" show-icon :closable="false" />
          </div>
        </div>
      </div>

      <template #footer>
        <!-- 如果有持久化文件 -->
        <template v-if="persistedRedlineInfo">
          <el-button @click="closeRedlineDialog">关闭</el-button>
          <el-button
            type="primary"
            @click="downloadPersistedRedline"
            :loading="redlineDownloading"
          >
            下载文件
          </el-button>
        </template>
        <!-- 如果没有持久化文件 -->
        <template v-else>
          <el-button @click="closeRedlineDialog">{{ redlineExportStatus?.status === 'completed' ? '关闭' : '取消' }}</el-button>
          <el-button
            v-if="redlineExportStatus?.status === 'completed'"
            type="success"
            @click="handleDownloadRedline"
            :loading="redlineDownloading"
          >
            下载文件
          </el-button>
          <el-button
            v-else
            type="primary"
            @click="handleExportRedline"
            :loading="redlineExporting"
            :disabled="confirmedCount === 0 && (!includeComments || !hasCommentableActions)"
          >
            {{ redlineExporting ? '正在导出...' : '开始导出' }}
          </el-button>
        </template>
      </template>
    </el-dialog>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-cards">
      <el-col :span="6">
        <el-card class="stat-card danger">
          <div class="stat-value">{{ summary.total_risks }}</div>
          <div class="stat-label">{{ i18n.labels.totalRisks }}</div>
          <div class="stat-detail">
            {{ i18n.labels.highDetail }} {{ summary.high_risks }} / {{ i18n.labels.mediumDetail }} {{ summary.medium_risks }} / {{ i18n.labels.lowDetail }} {{ summary.low_risks }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card warning">
          <div class="stat-value">{{ summary.high_risks }}</div>
          <div class="stat-label">{{ i18n.labels.highRisks }}</div>
          <div class="stat-detail">{{ i18n.labels.priorityNeeded }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card primary">
          <div class="stat-value">{{ summary.total_modifications }}</div>
          <div class="stat-label">{{ i18n.labels.modifications }}</div>
          <div class="stat-detail">
            {{ i18n.labels.mustModify }} {{ summary.must_modify }} / {{ i18n.labels.shouldModify }} {{ summary.should_modify }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card success">
          <div class="stat-value">{{ summary.total_actions }}</div>
          <div class="stat-label">{{ i18n.labels.actions }}</div>
          <div class="stat-detail">
            {{ i18n.labels.immediateActions }} {{ summary.immediate_actions }}
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 详细内容 Tabs -->
    <el-card class="content-card">
      <el-tabs v-model="activeTab">
        <!-- 风险点列表 -->
        <el-tab-pane :label="i18n.labels.risks" name="risks">
          <template #label>
            <span>
              {{ i18n.labels.risks }}
              <el-badge :value="result?.risks?.length || 0" type="danger" />
            </span>
          </template>
          <el-table :data="result?.risks || []" stripe border>
            <el-table-column :label="i18n.labels.riskLevelCol" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="riskLevelType(row.risk_level)">
                  {{ riskLevelText(row.risk_level) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="risk_type" :label="i18n.labels.riskType" width="120" />
            <el-table-column prop="description" :label="i18n.labels.riskDescription" min-width="200" />
            <el-table-column prop="reason" :label="i18n.labels.reason" min-width="200" />
            <el-table-column :label="i18n.labels.originalText" width="200">
              <template #default="{ row }">
                <el-popover
                  v-if="row.location?.original_text"
                  trigger="hover"
                  width="400"
                  placement="top"
                >
                  <template #reference>
                    <span class="text-ellipsis">
                      {{ row.location.original_text.slice(0, 50) }}...
                    </span>
                  </template>
                  <div>{{ row.location.original_text }}</div>
                </el-popover>
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 修改建议列表 -->
        <el-tab-pane :label="i18n.labels.modifications" name="modifications">
          <template #label>
            <span>
              {{ i18n.labels.modifications }}
              <el-badge :value="result?.modifications?.length || 0" type="primary" />
            </span>
          </template>
          <div class="modification-list">
            <el-card
              v-for="mod in result?.modifications || []"
              :key="mod.id"
              class="modification-card"
              :class="{ confirmed: mod.user_confirmed }"
            >
              <div class="mod-header">
                <el-tag :type="priorityType(mod.priority)">
                  {{ priorityText(mod.priority) }}
                </el-tag>
                <span class="mod-reason">{{ mod.modification_reason }}</span>
                <div class="mod-actions">
                  <el-switch
                    v-model="getModUIState(mod.id).showDiff"
                    :active-text="i18n.labels.diff"
                    :inactive-text="i18n.labels.fullText"
                    size="small"
                    style="margin-right: 12px;"
                  />
                  <el-checkbox
                    v-model="mod.user_confirmed"
                    @change="(val) => updateModification(mod, { user_confirmed: val })"
                  >
                    {{ i18n.labels.confirmAdopt }}
                  </el-checkbox>
                </div>
              </div>
              <el-row :gutter="20" class="mod-content">
                <el-col :span="12">
                  <div class="text-label">{{ i18n.labels.currentText }}</div>
                  <div
                    v-if="getModUIState(mod.id).showDiff"
                    class="text-box diff-view"
                    v-html="getDiffHtml(mod).originalHtml"
                  ></div>
                  <div v-else class="text-box original">{{ mod.original_text }}</div>
                </el-col>
                <el-col :span="12">
                  <div class="text-label">
                    {{ i18n.labels.suggestedText }}
                    <el-button
                      v-if="!getModUIState(mod.id).isEditing"
                      type="primary"
                      link
                      size="small"
                      @click="getModUIState(mod.id).isEditing = true"
                    >
                      {{ i18n.labels.edit }}
                    </el-button>
                    <el-button
                      v-else
                      type="success"
                      link
                      size="small"
                      @click="saveModification(mod)"
                    >
                      {{ i18n.labels.save }}
                    </el-button>
                  </div>
                  <div
                    v-if="getModUIState(mod.id).showDiff && !getModUIState(mod.id).isEditing"
                    class="text-box diff-view suggested"
                    v-html="getDiffHtml(mod).modifiedHtml"
                  ></div>
                  <div
                    v-else-if="!getModUIState(mod.id).isEditing"
                    class="text-box suggested"
                  >{{ getModUIState(mod.id).editText || mod.suggested_text }}</div>
                  <template v-else>
                    <el-input
                      type="textarea"
                      :rows="4"
                      v-model="getModUIState(mod.id).editText"
                    />
                  </template>
                </el-col>
              </el-row>
            </el-card>
            <el-empty v-if="!result?.modifications?.length" :description="i18n.labels.noModifications" />
          </div>
        </el-tab-pane>

        <!-- 行动建议列表 -->
        <el-tab-pane :label="i18n.labels.actions" name="actions">
          <template #label>
            <span>
              {{ i18n.labels.actions }}
              <el-badge :value="result?.actions?.length || 0" type="success" />
            </span>
          </template>
          <el-table :data="result?.actions || []" stripe border>
            <el-table-column :label="i18n.labels.urgencyCol" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="urgencyType(row.urgency)">
                  {{ urgencyText(row.urgency) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="action_type" :label="i18n.labels.actionType" width="120" />
            <el-table-column prop="description" :label="i18n.labels.specificAction" min-width="250" />
            <el-table-column prop="responsible_party" :label="i18n.labels.responsibleParty" width="100" />
            <el-table-column prop="deadline_suggestion" :label="i18n.labels.deadline" width="120">
              <template #default="{ row }">
                {{ row.deadline_suggestion || '-' }}
              </template>
            </el-table-column>
            <el-table-column :label="i18n.labels.operation" width="130" align="center">
              <template #default="{ row }">
                <el-checkbox
                  v-model="row.user_confirmed"
                  @change="(val) => updateAction(row, val)"
                  style="margin-right: 8px;"
                >{{ i18n.labels.confirm }}</el-checkbox>
                <el-button type="primary" link size="small" @click="openActionEditDialog(row)">
                  {{ i18n.labels.edit }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!result?.actions?.length" :description="i18n.labels.noActions" />
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 行动建议编辑弹窗 -->
    <el-dialog
      v-model="actionEditDialogVisible"
      title="编辑行动建议"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form :model="actionEditForm" label-width="80px">
        <el-form-item label="具体行动">
          <el-input
            v-model="actionEditForm.description"
            type="textarea"
            :rows="3"
            placeholder="请输入具体行动描述"
          />
        </el-form-item>
        <el-form-item label="行动类型">
          <el-select v-model="actionEditForm.action_type" style="width: 100%">
            <el-option label="沟通协商" value="沟通协商" />
            <el-option label="补充材料" value="补充材料" />
            <el-option label="法务确认" value="法务确认" />
            <el-option label="内部审批" value="内部审批" />
            <el-option label="核实信息" value="核实信息" />
          </el-select>
        </el-form-item>
        <el-form-item label="紧急程度">
          <el-select v-model="actionEditForm.urgency" style="width: 100%">
            <el-option label="立即处理" value="immediate" />
            <el-option label="尽快处理" value="soon" />
            <el-option label="一般" value="normal" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责方">
          <el-input v-model="actionEditForm.responsible_party" placeholder="请输入负责方" />
        </el-form-item>
        <el-form-item label="建议时限">
          <el-input v-model="actionEditForm.deadline_suggestion" placeholder="如：签署前、3个工作日内" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="actionEditDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveActionFromDialog" :loading="actionSaving">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useReviewStore } from '@/store'
import { ElMessage } from 'element-plus'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const store = useReviewStore()

const loading = ref(false)
const activeTab = ref('risks')
const taskId = computed(() => route.params.taskId)

// Redline 相关
const redlineExporting = ref(false)
const redlinePreview = ref(null)
const showRedlineDialog = ref(false)
const includeComments = ref(false)
const redlineExportStatus = ref(null)  // 导出任务状态
const redlineDownloading = ref(false)  // 下载中状态
let redlineStatusPoller = null  // 状态轮询定时器
const persistedRedlineInfo = ref(null)  // 已持久化的 Redline 文件信息

// 独立存储 UI 状态，不受 store 重载影响
const modificationUIStates = ref({}) // { modId: { showDiff: true, isEditing: false, editText: '' } }

// 行动建议编辑弹窗状态
const actionEditDialogVisible = ref(false)
const actionSaving = ref(false)
const editingActionId = ref(null)
const actionEditForm = ref({
  description: '',
  action_type: '',
  urgency: 'normal',
  responsible_party: '',
  deadline_suggestion: ''
})

const result = computed(() => store.reviewResult)
const summary = computed(() => result.value?.summary || {
  total_risks: 0,
  high_risks: 0,
  medium_risks: 0,
  low_risks: 0,
  total_modifications: 0,
  must_modify: 0,
  should_modify: 0,
  total_actions: 0,
  immediate_actions: 0
})

// 获取当前结果的语言
const resultLanguage = computed(() => result.value?.language || 'zh-CN')
const isEnglish = computed(() => resultLanguage.value === 'en')

// 多语言文本映射
const i18n = computed(() => {
  if (isEnglish.value) {
    return {
      materialType: { contract: 'Contract', marketing: 'Marketing Material' },
      riskLevel: { high: 'High', medium: 'Medium', low: 'Low' },
      priority: { must: 'Must', should: 'Should', may: 'May' },
      urgency: { immediate: 'Immediate', soon: 'Soon', normal: 'Normal' },
      labels: {
        back: 'Back',
        reviewResult: 'Review Result',
        ourParty: 'Our Party:',
        reviewTime: 'Review Time:',
        exportRedline: 'Export Redline Word',
        export: 'Export',
        totalRisks: 'Total Risks',
        highRisks: 'High Risks',
        priorityNeeded: 'Priority needed',
        modifications: 'Modifications',
        actions: 'Actions',
        risks: 'Risks',
        highDetail: 'H',
        mediumDetail: 'M',
        lowDetail: 'L',
        mustModify: 'must',
        shouldModify: 'should',
        immediateActions: 'immediate',
        riskLevelCol: 'Risk Level',
        riskType: 'Risk Type',
        riskDescription: 'Description',
        reason: 'Reason',
        originalText: 'Original Text',
        urgencyCol: 'Urgency',
        actionType: 'Action Type',
        specificAction: 'Specific Action',
        responsibleParty: 'Responsible Party',
        deadline: 'Deadline',
        operation: 'Operation',
        confirm: 'Confirm',
        edit: 'Edit',
        currentText: 'Current Text',
        suggestedText: 'Suggested Modification',
        save: 'Save',
        confirmAdopt: 'Confirm',
        diff: 'Diff',
        fullText: 'Full',
        noModifications: 'No modification suggestions',
        noActions: 'No action recommendations'
      }
    }
  }
  return {
    materialType: { contract: '合同', marketing: '营销材料' },
    riskLevel: { high: '高', medium: '中', low: '低' },
    priority: { must: '必须', should: '应该', may: '可以' },
    urgency: { immediate: '立即', soon: '尽快', normal: '一般' },
    labels: {
      back: '返回',
      reviewResult: '审阅结果',
      ourParty: '我方:',
      reviewTime: '审阅时间:',
      exportRedline: '导出修订版 Word',
      export: '导出',
      totalRisks: '风险总数',
      highRisks: '高风险',
      priorityNeeded: '需优先处理',
      modifications: '修改建议',
      actions: '行动建议',
      risks: '风险点',
      highDetail: '高',
      mediumDetail: '中',
      lowDetail: '低',
      mustModify: '必须',
      shouldModify: '应该',
      immediateActions: '立即处理',
      riskLevelCol: '风险等级',
      riskType: '风险类型',
      riskDescription: '风险描述',
      reason: '判定理由',
      originalText: '原文摘录',
      urgencyCol: '紧急程度',
      actionType: '行动类型',
      specificAction: '具体行动',
      responsibleParty: '负责方',
      deadline: '建议时限',
      operation: '操作',
      confirm: '确认',
      edit: '编辑',
      currentText: '当前文本',
      suggestedText: '建议修改为',
      save: '保存',
      confirmAdopt: '确认采纳',
      diff: '差异',
      fullText: '全文',
      noModifications: '无修改建议',
      noActions: '无行动建议'
    }
  }
})

const materialTypeText = computed(() => {
  const type = result.value?.material_type
  return i18n.value.materialType[type] || type
})

// 已确认的修改建议数量
const confirmedCount = computed(() => {
  if (!result.value?.modifications) return 0
  return result.value.modifications.filter(m => m.user_confirmed).length
})

// 已确认的行动建议数量
const confirmedActionsCount = computed(() => {
  if (!result.value?.actions) return 0
  return result.value.actions.filter(a => a.user_confirmed).length
})

// 是否有可添加批注的行动建议（需要用户已确认且有关联风险点原文）
const hasCommentableActions = computed(() => {
  return redlinePreview.value?.commentable_actions > 0
})

// 是否可以导出 Redline
const canExportRedline = computed(() => {
  // 需要有已确认的修改或可批注的行动建议，且原文档为 docx 格式
  if (redlinePreview.value && !redlinePreview.value.can_export) return false
  if (confirmedCount.value === 0 && !hasCommentableActions.value) return false
  return true
})

// Redline 按钮禁用原因
const redlineDisabledReason = computed(() => {
  if (redlinePreview.value?.reason) {
    return redlinePreview.value.reason
  }
  if (confirmedCount.value === 0 && !hasCommentableActions.value) {
    return '请先确认至少一条修改建议或行动建议'
  }
  return ''
})

// 获取修改建议的 UI 状态
function getModUIState(modId) {
  if (!modificationUIStates.value[modId]) {
    const mod = result.value?.modifications?.find(m => m.id === modId)
    modificationUIStates.value[modId] = {
      showDiff: true,
      isEditing: false,
      editText: mod?.user_modified_text || mod?.suggested_text || ''
    }
  }
  return modificationUIStates.value[modId]
}

// 初始化所有修改建议的 UI 状态
function initModUIStates() {
  if (result.value?.modifications) {
    result.value.modifications.forEach(mod => {
      if (!modificationUIStates.value[mod.id]) {
        modificationUIStates.value[mod.id] = {
          showDiff: true,
          isEditing: false,
          editText: mod.user_modified_text || mod.suggested_text || ''
        }
      }
    })
  }
}

onMounted(async () => {
  if (taskId.value) {
    loading.value = true
    try {
      await store.loadResult(taskId.value)
      // 初始化 UI 状态（独立于 store 数据）
      initModUIStates()
      // 获取 Redline 预览信息和已持久化的文件信息
      await Promise.all([
        loadRedlinePreview(),
        loadPersistedRedlineInfo()
      ])
    } catch (error) {
      ElMessage.error('加载结果失败')
    } finally {
      loading.value = false
    }
  }
})

async function loadRedlinePreview() {
  try {
    const res = await api.getRedlinePreview(taskId.value)
    redlinePreview.value = res.data
  } catch (error) {
    console.error('获取 Redline 预览失败:', error)
  }
}

async function loadPersistedRedlineInfo() {
  try {
    const res = await api.getRedlineInfo(taskId.value)
    if (res.data.exists) {
      persistedRedlineInfo.value = res.data
    } else {
      persistedRedlineInfo.value = null
    }
  } catch (error) {
    console.error('获取 Redline 信息失败:', error)
    persistedRedlineInfo.value = null
  }
}

async function downloadPersistedRedline() {
  redlineDownloading.value = true
  try {
    const res = await api.downloadPersistedRedline(taskId.value)

    // 从响应头获取文件名
    const contentDisposition = res.headers['content-disposition']
    let filename = persistedRedlineInfo.value?.filename || 'document_redline.docx'
    if (contentDisposition) {
      const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;\s]+)/)
      if (utf8Match) {
        filename = decodeURIComponent(utf8Match[1])
      } else {
        const match = contentDisposition.match(/filename="?([^"]+)"?/)
        if (match) filename = match[1]
      }
    }

    // 创建下载链接
    const blob = new Blob([res.data], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)

    ElMessage.success('文件下载成功')
    closeRedlineDialog()
  } catch (error) {
    console.error('下载失败:', error)
    ElMessage.error(error.message || '下载失败，请重试')
  } finally {
    redlineDownloading.value = false
  }
}

function goBack() {
  router.push('/')
}

function formatTime(isoString) {
  if (!isoString) return '-'
  const date = new Date(isoString)
  const locale = isEnglish.value ? 'en-US' : 'zh-CN'
  return date.toLocaleString(locale)
}

function riskLevelType(level) {
  const types = { high: 'danger', medium: 'warning', low: 'info' }
  return types[level] || 'info'
}

function riskLevelText(level) {
  return i18n.value.riskLevel[level] || level
}

function priorityType(priority) {
  const types = { must: 'danger', should: 'warning', may: 'info' }
  return types[priority] || 'info'
}

function priorityText(priority) {
  return i18n.value.priority[priority] || priority
}

function urgencyType(urgency) {
  const types = { immediate: 'danger', soon: 'warning', normal: 'info' }
  return types[urgency] || 'info'
}

function urgencyText(urgency) {
  return i18n.value.urgency[urgency] || urgency
}

/**
 * 计算两个文本之间的词级别 diff
 * 返回 HTML 字符串，删除的部分用 <del> 标记，新增的部分用 <ins> 标记
 */
function computeWordDiff(original, modified) {
  if (!original || !modified) return { originalHtml: original || '', modifiedHtml: modified || '' }
  if (original === modified) return { originalHtml: original, modifiedHtml: modified }

  // 按字符分割（中文）或按词分割（英文混合）
  const splitText = (text) => {
    // 使用更细粒度的分割：按中文字符、英文单词、标点符号分割
    const tokens = []
    let current = ''
    let currentType = null // 'cn' | 'en' | 'space' | 'punct'

    for (const char of text) {
      const isChinese = /[\u4e00-\u9fa5]/.test(char)
      const isEnglish = /[a-zA-Z0-9]/.test(char)
      const isSpace = /\s/.test(char)

      let charType
      if (isChinese) charType = 'cn'
      else if (isEnglish) charType = 'en'
      else if (isSpace) charType = 'space'
      else charType = 'punct'

      // 中文每个字符单独处理
      if (charType === 'cn') {
        if (current) tokens.push(current)
        tokens.push(char)
        current = ''
        currentType = null
      } else if (charType === currentType && charType === 'en') {
        // 英文字母和数字连续
        current += char
      } else {
        if (current) tokens.push(current)
        current = char
        currentType = charType
      }
    }
    if (current) tokens.push(current)
    return tokens
  }

  const origTokens = splitText(original)
  const modTokens = splitText(modified)

  // 使用简化的 LCS (最长公共子序列) 算法找出相同部分
  const m = origTokens.length
  const n = modTokens.length

  // 创建 DP 表
  const dp = Array(m + 1).fill(null).map(() => Array(n + 1).fill(0))

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (origTokens[i - 1] === modTokens[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }

  // 回溯找出 LCS
  const lcs = []
  let i = m, j = n
  while (i > 0 && j > 0) {
    if (origTokens[i - 1] === modTokens[j - 1]) {
      lcs.unshift({ origIdx: i - 1, modIdx: j - 1, token: origTokens[i - 1] })
      i--
      j--
    } else if (dp[i - 1][j] > dp[i][j - 1]) {
      i--
    } else {
      j--
    }
  }

  // 根据 LCS 生成 diff 结果
  const escapeHtml = (str) => {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  }

  // 生成原文的 HTML（标记删除部分）
  let originalHtml = ''
  let lastOrigIdx = -1
  for (const item of lcs) {
    // 添加删除的部分
    for (let k = lastOrigIdx + 1; k < item.origIdx; k++) {
      originalHtml += `<del class="diff-del">${escapeHtml(origTokens[k])}</del>`
    }
    // 添加相同的部分
    originalHtml += escapeHtml(item.token)
    lastOrigIdx = item.origIdx
  }
  // 处理剩余的删除部分
  for (let k = lastOrigIdx + 1; k < m; k++) {
    originalHtml += `<del class="diff-del">${escapeHtml(origTokens[k])}</del>`
  }

  // 生成修改后文本的 HTML（标记新增部分）
  let modifiedHtml = ''
  let lastModIdx = -1
  for (const item of lcs) {
    // 添加新增的部分
    for (let k = lastModIdx + 1; k < item.modIdx; k++) {
      modifiedHtml += `<ins class="diff-ins">${escapeHtml(modTokens[k])}</ins>`
    }
    // 添加相同的部分
    modifiedHtml += escapeHtml(item.token)
    lastModIdx = item.modIdx
  }
  // 处理剩余的新增部分
  for (let k = lastModIdx + 1; k < n; k++) {
    modifiedHtml += `<ins class="diff-ins">${escapeHtml(modTokens[k])}</ins>`
  }

  return { originalHtml, modifiedHtml }
}

// 获取 diff HTML
function getDiffHtml(mod) {
  const original = mod.original_text || ''
  const uiState = getModUIState(mod.id)
  const modified = uiState.editText || mod.user_modified_text || mod.suggested_text || ''
  return computeWordDiff(original, modified)
}

// 保存修改
async function saveModification(mod) {
  const uiState = getModUIState(mod.id)
  try {
    // 同时更新文本和确认状态（编辑后自动确认）
    await store.updateModification(taskId.value, mod.id, {
      user_modified_text: uiState.editText,
      user_confirmed: true
    })
    uiState.isEditing = false
    // 同步更新本地状态
    mod.user_confirmed = true
    mod.user_modified_text = uiState.editText
    ElMessage.success('保存成功')
    // 刷新 Redline 预览
    loadRedlinePreview()
  } catch (error) {
    console.error('保存失败详情:', error)
    ElMessage.error('保存失败: ' + (error?.response?.data?.detail || error.message || '请检查网络连接'))
  }
}

async function updateModification(mod, updates) {
  try {
    await store.updateModification(taskId.value, mod.id, updates)
    // UI 状态独立存储，不需要额外处理
  } catch (error) {
    ElMessage.error('更新失败')
  }
}

async function updateAction(action, confirmed) {
  // 先乐观更新 UI
  action.user_confirmed = confirmed

  try {
    await store.updateAction(taskId.value, action.id, confirmed)
    // 后台静默刷新 Redline 预览信息，不阻塞 UI
    loadRedlinePreview()
  } catch (error) {
    // 如果失败，回滚 UI 状态
    action.user_confirmed = !confirmed
    ElMessage.error('更新失败')
  }
}

// 打开行动建议编辑弹窗
function openActionEditDialog(action) {
  editingActionId.value = action.id
  actionEditForm.value = {
    description: action.description || '',
    action_type: action.action_type || '',
    urgency: action.urgency || 'normal',
    responsible_party: action.responsible_party || '',
    deadline_suggestion: action.deadline_suggestion || ''
  }
  actionEditDialogVisible.value = true
}

// 保存行动建议编辑
async function saveActionFromDialog() {
  actionSaving.value = true
  try {
    await store.updateAction(taskId.value, editingActionId.value, {
      ...actionEditForm.value,
      user_confirmed: true  // 编辑后自动确认
    })
    // 更新本地数据
    const action = result.value?.actions?.find(a => a.id === editingActionId.value)
    if (action) {
      Object.assign(action, actionEditForm.value)
      action.user_confirmed = true
    }
    actionEditDialogVisible.value = false
    ElMessage.success('保存成功')
    loadRedlinePreview()
  } catch (error) {
    console.error('保存失败详情:', error)
    ElMessage.error('保存失败: ' + (error?.response?.data?.detail || error.message || '请检查网络连接'))
  } finally {
    actionSaving.value = false
  }
}

function handleExport(command) {
  const urls = {
    excel: api.exportExcel(taskId.value),
    csv: api.exportCsv(taskId.value),
    json: api.exportJson(taskId.value),
    report: api.exportReport(taskId.value)
  }
  const url = urls[command]
  if (url) {
    window.open(url, '_blank')
  }
}

// 关闭 Redline 对话框
function closeRedlineDialog() {
  // 停止轮询
  if (redlineStatusPoller) {
    clearInterval(redlineStatusPoller)
    redlineStatusPoller = null
  }
  showRedlineDialog.value = false
  // 重置状态（延迟重置，让关闭动画完成）
  setTimeout(() => {
    redlineExportStatus.value = null
  }, 300)
}

// 轮询导出状态
async function pollRedlineStatus() {
  try {
    const res = await api.getRedlineExportStatus(taskId.value)
    redlineExportStatus.value = res.data

    // 如果完成或失败，停止轮询
    if (res.data.status === 'completed' || res.data.status === 'failed') {
      if (redlineStatusPoller) {
        clearInterval(redlineStatusPoller)
        redlineStatusPoller = null
      }
      redlineExporting.value = false
    }
  } catch (error) {
    console.error('获取导出状态失败:', error)
  }
}

// 启动异步导出
async function handleExportRedline() {
  redlineExporting.value = true
  redlineExportStatus.value = { status: 'pending', progress: 0, message: '正在启动导出...' }

  try {
    // 启动后台导出任务
    const res = await api.startRedlineExport(taskId.value, null, includeComments.value)
    redlineExportStatus.value = res.data

    // 开始轮询状态
    if (redlineStatusPoller) {
      clearInterval(redlineStatusPoller)
    }
    redlineStatusPoller = setInterval(pollRedlineStatus, 1000)  // 每秒轮询一次
  } catch (error) {
    console.error('启动导出失败:', error)
    redlineExportStatus.value = { status: 'failed', progress: 0, message: '启动失败', error: error.message }
    redlineExporting.value = false
  }
}

// 组件卸载时清理轮询
onUnmounted(() => {
  if (redlineStatusPoller) {
    clearInterval(redlineStatusPoller)
    redlineStatusPoller = null
  }
})

// 下载已完成的导出文件
async function handleDownloadRedline() {
  redlineDownloading.value = true
  try {
    const res = await api.downloadRedlineExport(taskId.value)

    // 从响应头获取文件名
    const contentDisposition = res.headers['content-disposition']
    let filename = 'document_redline.docx'
    if (contentDisposition) {
      const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;\s]+)/)
      if (utf8Match) {
        filename = decodeURIComponent(utf8Match[1])
      } else {
        const match = contentDisposition.match(/filename="?([^"]+)"?/)
        if (match) filename = match[1]
      }
    }

    // 创建下载链接
    const blob = new Blob([res.data], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)

    ElMessage.success('文件下载成功')
    // 下载成功后刷新持久化信息
    await loadPersistedRedlineInfo()
    closeRedlineDialog()
  } catch (error) {
    console.error('下载失败:', error)
    ElMessage.error(error.message || '下载失败，请重试')
  } finally {
    redlineDownloading.value = false
  }
}
</script>

<style scoped>
.result-view {
  max-width: var(--max-width);
  margin: 0 auto;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--spacing-6);
  background: var(--color-bg-card);
  padding: var(--spacing-5) var(--spacing-6);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
}

.header-info h2 {
  margin: var(--spacing-2) 0;
  font-size: var(--font-size-xl);
  color: var(--color-text-primary);
}

.header-meta {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-base);
}

.header-actions {
  display: flex;
  gap: var(--spacing-3);
  align-items: center;
}

.stat-cards {
  margin-bottom: var(--spacing-6);
}

.stat-card {
  text-align: center;
  padding: var(--spacing-3);
}

.stat-card .stat-value {
  font-size: var(--font-size-3xl);
  font-weight: var(--font-weight-bold);
  margin-bottom: var(--spacing-1);
}

.stat-card .stat-label {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
  margin-bottom: var(--spacing-1);
}

.stat-card .stat-detail {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.stat-card.danger .stat-value { color: var(--color-danger); }
.stat-card.warning .stat-value { color: var(--color-warning); }
.stat-card.primary .stat-value { color: var(--color-primary); }
.stat-card.success .stat-value { color: var(--color-success); }

.content-card {
  min-height: 500px;
}

.text-ellipsis {
  display: inline-block;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  color: var(--color-primary);
}

.modification-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-4);
}

.modification-card {
  border-left: 4px solid var(--color-warning);
}

.modification-card.confirmed {
  border-left-color: var(--color-success);
}

.mod-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  margin-bottom: var(--spacing-4);
}

.mod-reason {
  flex: 1;
  color: var(--color-text-secondary);
}

.mod-content {
  margin-top: var(--spacing-3);
}

.text-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin-bottom: var(--spacing-2);
}

.text-box {
  background: var(--color-bg-secondary);
  padding: var(--spacing-3);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-base);
  line-height: var(--line-height-relaxed);
  min-height: 100px;
}

.text-box.original {
  color: var(--color-text-tertiary);
  text-decoration: line-through;
}

.text-box.suggested {
  color: var(--color-text-primary);
}

.text-box.diff-view {
  color: var(--color-text-primary);
  text-decoration: none;
  line-height: 1.8;
}

/* Diff 样式 */
.text-box :deep(.diff-del),
.text-box.diff-view :deep(.diff-del) {
  background-color: var(--color-danger-bg);
  color: var(--color-danger);
  text-decoration: line-through;
  padding: 0 2px;
  border-radius: 2px;
}

.text-box :deep(.diff-ins),
.text-box.diff-view :deep(.diff-ins) {
  background-color: var(--color-success-bg);
  color: var(--color-success);
  text-decoration: none;
  padding: 0 2px;
  border-radius: 2px;
  font-weight: var(--font-weight-medium);
}

.mod-actions {
  display: flex;
  align-items: center;
}

/* Redline 导出对话框样式 */
.redline-dialog-content {
  padding: var(--spacing-2) 0;
}

.export-option {
  padding: var(--spacing-3) 0;
}

.option-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-2);
}

.option-header .el-icon {
  color: var(--color-primary);
}

.option-desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin-bottom: var(--spacing-2);
  padding-left: var(--spacing-6);
}

.option-count {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  padding-left: var(--spacing-6);
}

.option-count strong {
  color: var(--color-primary);
}

/* 导出进度样式 */
.export-progress {
  margin-top: var(--spacing-2);
}

.progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.export-result {
  margin-top: var(--spacing-3);
  padding: var(--spacing-3);
  background: var(--color-success-bg);
  border-radius: var(--radius-base);
  font-size: var(--font-size-sm);
  color: var(--color-success);
}

.export-result p {
  margin: 0;
  line-height: 1.6;
}

.export-error {
  margin-top: var(--spacing-3);
}

/* 持久化文件信息样式 */
.persisted-info {
  text-align: center;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.persisted-info p {
  margin: var(--spacing-1) 0;
}

.persisted-info strong {
  color: var(--color-primary);
}
</style>
