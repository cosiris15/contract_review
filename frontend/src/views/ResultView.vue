<template>
  <div class="result-view" v-loading="loading">
    <!-- 顶部信息栏 -->
    <div class="result-header">
      <div class="header-info">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <h2>{{ result?.document_name || '审阅结果' }}</h2>
        <div class="header-meta">
          <el-tag>{{ materialTypeText }}</el-tag>
          <span>我方: {{ result?.our_party }}</span>
          <span>审阅时间: {{ formatTime(result?.reviewed_at) }}</span>
        </div>
      </div>
      <div class="header-actions">
        <el-button
          type="success"
          @click="showRedlineDialog = true"
          :disabled="!canExportRedline"
        >
          <el-icon><EditPen /></el-icon>
          导出修订版 Word
        </el-button>
        <el-dropdown @command="handleExport">
          <el-button type="primary">
            <el-icon><Download /></el-icon>
            导出
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="excel">导出 Excel</el-dropdown-item>
              <el-dropdown-item command="csv">导出 CSV</el-dropdown-item>
              <el-dropdown-item command="json">导出 JSON</el-dropdown-item>
              <el-dropdown-item command="report">导出报告</el-dropdown-item>
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
      <div class="redline-dialog-content">
        <el-alert
          v-if="!redlinePreview?.can_export && redlinePreview?.reason"
          :title="redlinePreview.reason"
          type="warning"
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
      </div>

      <template #footer>
        <el-button @click="showRedlineDialog = false">取消</el-button>
        <el-button
          type="primary"
          @click="handleExportRedline"
          :loading="redlineExporting"
          :disabled="confirmedCount === 0 && (!includeComments || !hasCommentableActions)"
        >
          导出
        </el-button>
      </template>
    </el-dialog>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-cards">
      <el-col :span="6">
        <el-card class="stat-card danger">
          <div class="stat-value">{{ summary.total_risks }}</div>
          <div class="stat-label">风险总数</div>
          <div class="stat-detail">
            高 {{ summary.high_risks }} / 中 {{ summary.medium_risks }} / 低 {{ summary.low_risks }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card warning">
          <div class="stat-value">{{ summary.high_risks }}</div>
          <div class="stat-label">高风险</div>
          <div class="stat-detail">需优先处理</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card primary">
          <div class="stat-value">{{ summary.total_modifications }}</div>
          <div class="stat-label">修改建议</div>
          <div class="stat-detail">
            必须 {{ summary.must_modify }} / 应该 {{ summary.should_modify }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card success">
          <div class="stat-value">{{ summary.total_actions }}</div>
          <div class="stat-label">行动建议</div>
          <div class="stat-detail">
            立即处理 {{ summary.immediate_actions }}
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 详细内容 Tabs -->
    <el-card class="content-card">
      <el-tabs v-model="activeTab">
        <!-- 风险点列表 -->
        <el-tab-pane label="风险点" name="risks">
          <template #label>
            <span>
              风险点
              <el-badge :value="result?.risks?.length || 0" type="danger" />
            </span>
          </template>
          <el-table :data="result?.risks || []" stripe border>
            <el-table-column label="风险等级" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="riskLevelType(row.risk_level)">
                  {{ riskLevelText(row.risk_level) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="risk_type" label="风险类型" width="120" />
            <el-table-column prop="description" label="风险描述" min-width="200" />
            <el-table-column prop="reason" label="判定理由" min-width="200" />
            <el-table-column label="原文摘录" width="200">
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
        <el-tab-pane label="修改建议" name="modifications">
          <template #label>
            <span>
              修改建议
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
                    active-text="差异"
                    inactive-text="全文"
                    size="small"
                    style="margin-right: 12px;"
                  />
                  <el-checkbox
                    v-model="mod.user_confirmed"
                    @change="(val) => updateModification(mod, { user_confirmed: val })"
                  >
                    确认采纳
                  </el-checkbox>
                </div>
              </div>
              <el-row :gutter="20" class="mod-content">
                <el-col :span="12">
                  <div class="text-label">当前文本</div>
                  <div
                    v-if="getModUIState(mod.id).showDiff"
                    class="text-box diff-view"
                    v-html="getDiffHtml(mod).originalHtml"
                  ></div>
                  <div v-else class="text-box original">{{ mod.original_text }}</div>
                </el-col>
                <el-col :span="12">
                  <div class="text-label">
                    建议修改为
                    <el-button
                      v-if="!getModUIState(mod.id).isEditing"
                      type="primary"
                      link
                      size="small"
                      @click="getModUIState(mod.id).isEditing = true"
                    >
                      编辑
                    </el-button>
                    <el-button
                      v-else
                      type="success"
                      link
                      size="small"
                      @click="saveModification(mod)"
                    >
                      保存
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
                    <!-- 编辑时的实时diff预览 -->
                    <div
                      v-if="getModUIState(mod.id).showDiff"
                      class="text-box diff-view suggested preview-box"
                      v-html="getDiffHtml(mod).modifiedHtml"
                      style="margin-top: 8px; opacity: 0.9; font-size: 12px;"
                    ></div>
                  </template>
                </el-col>
              </el-row>
            </el-card>
            <el-empty v-if="!result?.modifications?.length" description="无修改建议" />
          </div>
        </el-tab-pane>

        <!-- 行动建议列表 -->
        <el-tab-pane label="行动建议" name="actions">
          <template #label>
            <span>
              行动建议
              <el-badge :value="result?.actions?.length || 0" type="success" />
            </span>
          </template>
          <el-table :data="result?.actions || []" stripe border>
            <el-table-column label="紧急程度" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="urgencyType(row.urgency)">
                  {{ urgencyText(row.urgency) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="action_type" label="行动类型" width="120" />
            <el-table-column prop="description" label="具体行动" min-width="250" />
            <el-table-column prop="responsible_party" label="负责方" width="100" />
            <el-table-column prop="deadline_suggestion" label="建议时限" width="120">
              <template #default="{ row }">
                {{ row.deadline_suggestion || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="130" align="center">
              <template #default="{ row }">
                <el-checkbox
                  v-model="row.user_confirmed"
                  @change="(val) => updateAction(row, val)"
                  style="margin-right: 8px;"
                >确认</el-checkbox>
                <el-button type="primary" link size="small" @click="openActionEditDialog(row)">
                  编辑
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!result?.actions?.length" description="无行动建议" />
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
import { ref, computed, onMounted, watch } from 'vue'
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

const materialTypeText = computed(() => {
  return result.value?.material_type === 'contract' ? '合同' : '营销材料'
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
      // 获取 Redline 预览信息
      await loadRedlinePreview()
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

function goBack() {
  router.push('/')
}

function formatTime(isoString) {
  if (!isoString) return '-'
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN')
}

function riskLevelType(level) {
  const types = { high: 'danger', medium: 'warning', low: 'info' }
  return types[level] || 'info'
}

function riskLevelText(level) {
  const texts = { high: '高', medium: '中', low: '低' }
  return texts[level] || level
}

function priorityType(priority) {
  const types = { must: 'danger', should: 'warning', may: 'info' }
  return types[priority] || 'info'
}

function priorityText(priority) {
  const texts = { must: '必须', should: '应该', may: '可以' }
  return texts[priority] || priority
}

function urgencyType(urgency) {
  const types = { immediate: 'danger', soon: 'warning', normal: 'info' }
  return types[urgency] || 'info'
}

function urgencyText(urgency) {
  const texts = { immediate: '立即', soon: '尽快', normal: '一般' }
  return texts[urgency] || urgency
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

async function handleExportRedline() {
  redlineExporting.value = true
  try {
    const res = await api.exportRedline(taskId.value, null, includeComments.value)

    // 从响应头获取文件名（支持 UTF-8 编码）
    const contentDisposition = res.headers['content-disposition']
    let filename = 'document_redline.docx'
    if (contentDisposition) {
      // 优先匹配 filename*=UTF-8'' 格式（RFC 5987）
      const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;\s]+)/)
      if (utf8Match) {
        filename = decodeURIComponent(utf8Match[1])
      } else {
        // 回退到普通 filename 格式
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

    // 显示成功信息
    const applied = res.headers['x-redline-applied'] || 0
    const commentsAdded = res.headers['x-comments-added'] || 0
    let message = '导出成功！'
    if (applied > 0) {
      message += `已应用 ${applied} 条修改`
    }
    if (commentsAdded > 0) {
      message += `${applied > 0 ? '，' : ''}添加 ${commentsAdded} 条批注`
    }
    ElMessage.success(message)

    // 关闭对话框
    showRedlineDialog.value = false
  } catch (error) {
    console.error('导出 Redline 失败:', error)
    ElMessage.error(error.message || '导出失败，请重试')
  } finally {
    redlineExporting.value = false
  }
}
</script>

<style scoped>
.result-view {
  max-width: 1400px;
  margin: 0 auto;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  background: white;
  padding: 20px 24px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.header-info h2 {
  margin: 8px 0;
  font-size: 20px;
  color: #303133;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  color: #909399;
  font-size: 14px;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.stat-cards {
  margin-bottom: 24px;
}

.stat-card {
  text-align: center;
  padding: 12px;
}

.stat-card .stat-value {
  font-size: 32px;
  font-weight: 700;
  margin-bottom: 4px;
}

.stat-card .stat-label {
  font-size: 14px;
  color: #606266;
  margin-bottom: 4px;
}

.stat-card .stat-detail {
  font-size: 12px;
  color: #909399;
}

.stat-card.danger .stat-value { color: #f56c6c; }
.stat-card.warning .stat-value { color: #e6a23c; }
.stat-card.primary .stat-value { color: #409eff; }
.stat-card.success .stat-value { color: #67c23a; }

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
  color: #409eff;
}

.modification-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.modification-card {
  border-left: 4px solid #e6a23c;
}

.modification-card.confirmed {
  border-left-color: #67c23a;
}

.mod-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.mod-reason {
  flex: 1;
  color: #606266;
}

.mod-content {
  margin-top: 12px;
}

.text-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.text-box {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.6;
  min-height: 100px;
}

.text-box.original {
  color: #909399;
  text-decoration: line-through;
}

.text-box.suggested {
  color: #303133;
}

.text-box.diff-view {
  color: #303133;
  text-decoration: none;
  line-height: 1.8;
}

/* Diff 样式 */
.text-box :deep(.diff-del),
.text-box.diff-view :deep(.diff-del) {
  background-color: #fde2e2;
  color: #f56c6c;
  text-decoration: line-through;
  padding: 0 2px;
  border-radius: 2px;
}

.text-box :deep(.diff-ins),
.text-box.diff-view :deep(.diff-ins) {
  background-color: #e1f3d8;
  color: #67c23a;
  text-decoration: none;
  padding: 0 2px;
  border-radius: 2px;
  font-weight: 500;
}

.mod-actions {
  display: flex;
  align-items: center;
}

/* Redline 导出对话框样式 */
.redline-dialog-content {
  padding: 8px 0;
}

.export-option {
  padding: 12px 0;
}

.option-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 8px;
}

.option-header .el-icon {
  color: #409eff;
}

.option-desc {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
  padding-left: 24px;
}

.option-count {
  font-size: 13px;
  color: #606266;
  padding-left: 24px;
}

.option-count strong {
  color: #409eff;
}
</style>
