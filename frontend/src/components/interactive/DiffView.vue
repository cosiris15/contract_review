<template>
  <div class="diff-view">
    <div class="diff-header">
      <div class="header-left">
        <span class="diff-title">修改对比</span>

        <!-- 变更状态标记 -->
        <span v-if="changeData" class="change-status-badge" :class="`status-${changeData.status}`">
          {{ changeData.status === 'pending' ? '待处理' : changeData.status === 'applied' ? '已应用' : '已回滚' }}
        </span>
      </div>

      <!-- 视图模式切换 -->
      <div class="view-mode-toggle">
        <button
          class="mode-btn"
          :class="{ active: viewMode === 'inline' }"
          @click="viewMode = 'inline'"
          title="内联视图"
        >
          <el-icon><Reading /></el-icon>
          内联
        </button>
        <button
          class="mode-btn"
          :class="{ active: viewMode === 'split' }"
          @click="viewMode = 'split'"
          title="并排视图"
        >
          <el-icon><Grid /></el-icon>
          并排
        </button>
      </div>

      <div class="header-right">
        <!-- 操作按钮（仅在有changeId且store有数据时显示） -->
        <div v-if="changeData" class="change-actions">
          <el-button
            v-if="changeData.status === 'pending'"
            type="success"
            size="small"
            :loading="applyLoading"
            @click="handleApplyChange"
          >
            应用变更
          </el-button>
          <el-button
            v-if="changeData.status === 'applied'"
            type="warning"
            size="small"
            :loading="revertLoading"
            @click="handleRevertChange"
          >
            回滚变更
          </el-button>
        </div>

        <!-- 图例 -->
        <div class="diff-legend">
          <span class="legend-item removed">删除</span>
          <span class="legend-item added">新增</span>
        </div>
      </div>
    </div>

    <!-- 内联视图 -->
    <div v-if="viewMode === 'inline'" class="diff-content inline-view" v-html="inlineDiffHtml"></div>

    <!-- 并排视图 -->
    <div v-else class="diff-content split-view">
      <div class="split-pane left-pane">
        <div class="pane-header">原始内容</div>
        <div class="pane-content" ref="leftPaneRef" @scroll="syncScroll($event, 'left')">
          <div
            v-for="(line, idx) in originalLines"
            :key="`orig-${idx}`"
            class="diff-line"
            :class="{ removed: line.removed, context: !line.removed }"
          >
            <span class="line-number">{{ idx + 1 }}</span>
            <span class="line-content" v-html="escapeHtml(line.text)"></span>
          </div>
        </div>
      </div>

      <div class="split-pane right-pane">
        <div class="pane-header">修改后内容</div>
        <div class="pane-content" ref="rightPaneRef" @scroll="syncScroll($event, 'right')">
          <div
            v-for="(line, idx) in modifiedLines"
            :key="`mod-${idx}`"
            class="diff-line"
            :class="{ added: line.added, context: !line.added }"
          >
            <span class="line-number">{{ idx + 1 }}</span>
            <span class="line-content" v-html="escapeHtml(line.text)"></span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed, onUnmounted } from 'vue'
import { diffChars, diffLines } from 'diff'
import { Reading, Grid } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useDocumentStore } from '@/store/document'

const props = defineProps({
  original: {
    type: String,
    default: ''
  },
  modified: {
    type: String,
    default: ''
  },
  // 新增：变更ID（可选，用于从store获取变更数据）
  changeId: {
    type: String,
    default: null
  }
})

const documentStore = useDocumentStore()

// 视图模式：inline（内联）或 split（并排）
const viewMode = ref('inline')

// 文本长度限制，避免超大文本卡顿
const MAX_TEXT_LENGTH = 10000

// Refs for split view panes (for scroll syncing)
const leftPaneRef = ref(null)
const rightPaneRef = ref(null)
let isSyncing = false

// 操作按钮加载状态
const applyLoading = ref(false)
const revertLoading = ref(false)

// ========== 从store获取变更数据 ==========
const changeData = computed(() => {
  if (!props.changeId) return null
  return documentStore.allChanges.find(c => c.change_id === props.changeId)
})

// ========== 操作函数 ==========
async function handleApplyChange() {
  if (!props.changeId) return

  applyLoading.value = true
  try {
    const result = await documentStore.applyChange(props.changeId)
    if (result.success) {
      ElMessage.success(result.message || '变更已应用')
    } else {
      ElMessage.error(result.message || '应用变更失败')
    }
  } catch (error) {
    console.error('应用变更失败:', error)
    ElMessage.error('应用变更失败')
  } finally {
    applyLoading.value = false
  }
}

async function handleRevertChange() {
  if (!props.changeId) return

  revertLoading.value = true
  try {
    const result = await documentStore.revertChange(props.changeId)
    if (result.success) {
      ElMessage.success(result.message || '变更已回滚')
    } else {
      ElMessage.error(result.message || '回滚变更失败')
    }
  } catch (error) {
    console.error('回滚变更失败:', error)
    ElMessage.error('回滚变更失败')
  } finally {
    revertLoading.value = false
  }
}

// HTML 转义
const htmlEscapeMap = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
}

function escapeHtml(text) {
  return text
    .replace(/[&<>"']/g, char => htmlEscapeMap[char])
    .replace(/\n/g, '<br>')
}

// ========== 内联视图的 diff 计算 ==========
function computeInlineDiff(original, modified) {
  if (!original && !modified) {
    return '<span class="no-diff">暂无内容</span>'
  }

  const truncatedOriginal = original?.slice(0, MAX_TEXT_LENGTH) || ''
  const truncatedModified = modified?.slice(0, MAX_TEXT_LENGTH) || ''

  if (!truncatedOriginal) {
    return `<span class="diff-added">${escapeHtml(truncatedModified)}</span>`
  }

  if (!truncatedModified) {
    return `<span class="diff-removed">${escapeHtml(truncatedOriginal)}</span>`
  }

  const diff = diffChars(truncatedOriginal, truncatedModified)

  return diff.map(part => {
    const text = escapeHtml(part.value)
    if (part.added) {
      return `<span class="diff-added">${text}</span>`
    }
    if (part.removed) {
      return `<span class="diff-removed">${text}</span>`
    }
    return text
  }).join('')
}

const inlineDiffHtml = ref('<span class="no-diff">暂无内容</span>')

// ========== 并排视图的 diff 计算 ==========
function computeSplitDiff(original, modified) {
  const truncatedOriginal = original?.slice(0, MAX_TEXT_LENGTH) || ''
  const truncatedModified = modified?.slice(0, MAX_TEXT_LENGTH) || ''

  if (!truncatedOriginal && !truncatedModified) {
    return {
      originalLines: [{ text: '', removed: false }],
      modifiedLines: [{ text: '', added: false }]
    }
  }

  const diff = diffLines(truncatedOriginal, truncatedModified)

  const originalLines = []
  const modifiedLines = []

  diff.forEach(part => {
    const lines = part.value.split('\n').filter(l => l !== '')

    if (part.removed) {
      // 删除的行只出现在左侧
      lines.forEach(line => {
        originalLines.push({ text: line, removed: true })
      })
    } else if (part.added) {
      // 新增的行只出现在右侧
      lines.forEach(line => {
        modifiedLines.push({ text: line, added: true })
      })
    } else {
      // 未修改的行同时出现在两侧
      lines.forEach(line => {
        originalLines.push({ text: line, removed: false })
        modifiedLines.push({ text: line, added: false })
      })
    }
  })

  // 如果为空，至少显示一行
  if (originalLines.length === 0) originalLines.push({ text: '', removed: false })
  if (modifiedLines.length === 0) modifiedLines.push({ text: '', added: false })

  return { originalLines, modifiedLines }
}

const originalLines = ref([])
const modifiedLines = ref([])

// ========== 同步滚动 ==========
function syncScroll(event, source) {
  if (isSyncing) return

  isSyncing = true
  const sourcePane = event.target
  const targetPane = source === 'left' ? rightPaneRef.value : leftPaneRef.value

  if (targetPane) {
    targetPane.scrollTop = sourcePane.scrollTop
  }

  // 使用 setTimeout 确保滚动事件完成后重置标志
  setTimeout(() => {
    isSyncing = false
  }, 50)
}

// ========== 防抖计算 diff ==========
let debounceTimer = null

watch(
  [() => props.original, () => props.modified, viewMode],
  ([original, modified, mode]) => {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
    }

    debounceTimer = setTimeout(() => {
      if (mode === 'inline') {
        inlineDiffHtml.value = computeInlineDiff(original, modified)
      } else {
        const result = computeSplitDiff(original, modified)
        originalLines.value = result.originalLines
        modifiedLines.value = result.modifiedLines
      }
    }, 100)
  },
  { immediate: true }
)

// 清理定时器
onUnmounted(() => {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
  }
})
</script>

<style scoped>
.diff-view {
  background: #f8f9fa;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.diff-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #e9ecef;
  border-bottom: 1px solid #dee2e6;
  flex-shrink: 0;
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.diff-title {
  font-size: 13px;
  font-weight: 500;
  color: #495057;
}

/* 变更状态徽章 */
.change-status-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.change-status-badge.status-pending {
  background: #fff3cd;
  color: #856404;
  border: 1px solid #ffc107;
}

.change-status-badge.status-applied {
  background: #d1e7dd;
  color: #0f5132;
  border: 1px solid #28a745;
}

.change-status-badge.status-reverted {
  background: #f8d7da;
  color: #721c24;
  border: 1px solid #dc3545;
}

/* 操作按钮区域 */
.change-actions {
  display: flex;
  gap: 8px;
}

/* 视图模式切换按钮 */
.view-mode-toggle {
  display: flex;
  gap: 4px;
  background: #fff;
  border-radius: 6px;
  padding: 2px;
}

.mode-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #6c757d;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.mode-btn:hover {
  background: #f1f3f5;
  color: #495057;
}

.mode-btn.active {
  background: #1890ff;
  color: #fff;
}

.mode-btn .el-icon {
  font-size: 14px;
}

.diff-legend {
  display: flex;
  gap: 12px;
}

.legend-item {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
}

.legend-item.removed {
  background: #fee2e2;
  color: #dc2626;
  text-decoration: line-through;
}

.legend-item.added {
  background: #d1fae5;
  color: #059669;
}

/* ========== 内联视图样式 ========== */
.diff-content {
  flex: 1;
  overflow-y: auto;
}

.inline-view {
  padding: 12px;
  font-size: 14px;
  line-height: 1.8;
  color: #212529;
  white-space: pre-wrap;
  word-break: break-word;
}

.inline-view :deep(.diff-removed) {
  background: #fee2e2;
  color: #dc2626;
  text-decoration: line-through;
  padding: 1px 2px;
  border-radius: 2px;
}

.inline-view :deep(.diff-added) {
  background: #d1fae5;
  color: #059669;
  padding: 1px 2px;
  border-radius: 2px;
}

.inline-view :deep(.no-diff) {
  color: #6c757d;
  font-style: italic;
}

/* ========== 并排视图样式 ========== */
.split-view {
  display: flex;
  gap: 1px;
  background: #dee2e6;
  padding: 0;
}

.split-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
  overflow: hidden;
}

.pane-header {
  padding: 8px 12px;
  background: #f8f9fa;
  border-bottom: 1px solid #dee2e6;
  font-size: 12px;
  font-weight: 600;
  color: #495057;
  text-align: center;
  flex-shrink: 0;
}

.pane-content {
  flex: 1;
  overflow-y: auto;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
}

.diff-line {
  display: flex;
  align-items: flex-start;
  min-height: 20px;
  padding: 2px 0;
  transition: background 0.1s;
}

.diff-line:hover {
  background: #f1f3f5;
}

.diff-line.removed {
  background: #fee2e2;
}

.diff-line.added {
  background: #d1fae5;
}

.diff-line.context {
  background: #fff;
}

.line-number {
  flex-shrink: 0;
  width: 40px;
  padding: 0 8px;
  text-align: right;
  color: #adb5bd;
  font-size: 11px;
  user-select: none;
  border-right: 1px solid #e9ecef;
}

.diff-line.removed .line-number {
  background: #fecaca;
  color: #dc2626;
  border-right-color: #dc2626;
}

.diff-line.added .line-number {
  background: #a7f3d0;
  color: #059669;
  border-right-color: #059669;
}

.line-content {
  flex: 1;
  padding: 0 12px;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 滚动条样式 */
.pane-content::-webkit-scrollbar,
.inline-view::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.pane-content::-webkit-scrollbar-track,
.inline-view::-webkit-scrollbar-track {
  background: transparent;
}

.pane-content::-webkit-scrollbar-thumb,
.inline-view::-webkit-scrollbar-thumb {
  background: #ced4da;
  border-radius: 3px;
}

.pane-content::-webkit-scrollbar-thumb:hover,
.inline-view::-webkit-scrollbar-thumb:hover {
  background: #adb5bd;
}
</style>
