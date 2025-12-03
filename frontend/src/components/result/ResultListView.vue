<template>
  <div class="result-list-view">
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
                    @change="(val) => handleUpdateModification(mod, { user_confirmed: val })"
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
                      @click="handleSaveModification(mod)"
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
                  @change="(val) => handleUpdateAction(row, val)"
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
        <el-button type="primary" @click="handleSaveActionFromDialog" :loading="actionSaving">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  result: {
    type: Object,
    default: null
  },
  language: {
    type: String,
    default: 'zh-CN'
  }
})

const emit = defineEmits(['update-modification', 'update-action', 'refresh'])

const activeTab = ref('risks')

// 独立存储 UI 状态
const modificationUIStates = ref({})

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

// 计算属性
const isEnglish = computed(() => props.language === 'en')

const summary = computed(() => props.result?.summary || {
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

// 多语言文本映射
const i18n = computed(() => {
  if (isEnglish.value) {
    return {
      materialType: { contract: 'Contract', marketing: 'Marketing Material' },
      riskLevel: { high: 'High', medium: 'Medium', low: 'Low' },
      priority: { must: 'Must', should: 'Should', may: 'May' },
      urgency: { immediate: 'Immediate', soon: 'Soon', normal: 'Normal' },
      labels: {
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

// 监听 result 变化，初始化 UI 状态
watch(() => props.result, () => {
  initModUIStates()
}, { immediate: true })

// 获取修改建议的 UI 状态
function getModUIState(modId) {
  if (!modificationUIStates.value[modId]) {
    const mod = props.result?.modifications?.find(m => m.id === modId)
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
  if (props.result?.modifications) {
    props.result.modifications.forEach(mod => {
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

// 辅助函数
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

// Diff 计算
function computeWordDiff(original, modified) {
  if (!original || !modified) return { originalHtml: original || '', modifiedHtml: modified || '' }
  if (original === modified) return { originalHtml: original, modifiedHtml: modified }

  const splitText = (text) => {
    const tokens = []
    let current = ''
    let currentType = null

    for (const char of text) {
      const isChinese = /[\u4e00-\u9fa5]/.test(char)
      const isEnglish = /[a-zA-Z0-9]/.test(char)
      const isSpace = /\s/.test(char)

      let charType
      if (isChinese) charType = 'cn'
      else if (isEnglish) charType = 'en'
      else if (isSpace) charType = 'space'
      else charType = 'punct'

      if (charType === 'cn') {
        if (current) tokens.push(current)
        tokens.push(char)
        current = ''
        currentType = null
      } else if (charType === currentType && charType === 'en') {
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

  const m = origTokens.length
  const n = modTokens.length

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

  const escapeHtml = (str) => {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  }

  let originalHtml = ''
  let lastOrigIdx = -1
  for (const item of lcs) {
    for (let k = lastOrigIdx + 1; k < item.origIdx; k++) {
      originalHtml += `<del class="diff-del">${escapeHtml(origTokens[k])}</del>`
    }
    originalHtml += escapeHtml(item.token)
    lastOrigIdx = item.origIdx
  }
  for (let k = lastOrigIdx + 1; k < m; k++) {
    originalHtml += `<del class="diff-del">${escapeHtml(origTokens[k])}</del>`
  }

  let modifiedHtml = ''
  let lastModIdx = -1
  for (const item of lcs) {
    for (let k = lastModIdx + 1; k < item.modIdx; k++) {
      modifiedHtml += `<ins class="diff-ins">${escapeHtml(modTokens[k])}</ins>`
    }
    modifiedHtml += escapeHtml(item.token)
    lastModIdx = item.modIdx
  }
  for (let k = lastModIdx + 1; k < n; k++) {
    modifiedHtml += `<ins class="diff-ins">${escapeHtml(modTokens[k])}</ins>`
  }

  return { originalHtml, modifiedHtml }
}

function getDiffHtml(mod) {
  const original = mod.original_text || ''
  const uiState = getModUIState(mod.id)
  const modified = uiState.editText || mod.user_modified_text || mod.suggested_text || ''
  return computeWordDiff(original, modified)
}

// 事件处理
async function handleSaveModification(mod) {
  const uiState = getModUIState(mod.id)
  try {
    emit('update-modification', mod.id, {
      user_modified_text: uiState.editText,
      user_confirmed: true
    })
    uiState.isEditing = false
    mod.user_confirmed = true
    mod.user_modified_text = uiState.editText
    ElMessage.success('保存成功')
  } catch (error) {
    ElMessage.error('保存失败')
  }
}

async function handleUpdateModification(mod, updates) {
  emit('update-modification', mod.id, updates)
}

async function handleUpdateAction(action, confirmed) {
  action.user_confirmed = confirmed
  emit('update-action', action.id, confirmed)
}

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

async function handleSaveActionFromDialog() {
  actionSaving.value = true
  try {
    const action = props.result?.actions?.find(a => a.id === editingActionId.value)
    if (action) {
      Object.assign(action, actionEditForm.value)
      action.user_confirmed = true
    }
    emit('update-action', editingActionId.value, {
      ...actionEditForm.value,
      user_confirmed: true
    })
    actionEditDialogVisible.value = false
    ElMessage.success('保存成功')
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    actionSaving.value = false
  }
}
</script>

<style scoped>
.result-list-view {
  padding: var(--spacing-4);
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
  min-height: 400px;
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
</style>
