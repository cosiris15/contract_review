<template>
  <div class="document-viewer" ref="containerRef">
    <div class="document-header">
      <h3 class="document-title">
        <el-icon><Document /></el-icon>
        {{ documentName || '合同文档' }}
      </h3>
      <span class="paragraph-count">共 {{ paragraphs.length }} 段</span>
    </div>

    <!-- 变更状态图例 -->
    <div v-if="hasChanges" class="change-legend">
      <span class="legend-title">变更标记：</span>
      <span class="legend-item pending-badge">待处理</span>
      <span class="legend-item applied-badge">已应用</span>
      <span class="legend-item reverted-badge">已回滚</span>
    </div>

    <div class="document-content" ref="contentRef">
      <div
        v-for="para in paragraphs"
        :key="para.index"
        :id="`para-${para.index}`"
        class="paragraph"
        :class="{
          highlighted: highlightedIndex === para.index,
          pulse: pulseIndex === para.index,
          'has-pending-change': paragraphChangeStatus[para.index + 1] === 'pending',
          'has-applied-change': paragraphChangeStatus[para.index + 1] === 'applied',
          'has-reverted-change': paragraphChangeStatus[para.index + 1] === 'reverted',
        }"
        @click="handleParagraphClick(para)"
      >
        <span class="para-number">{{ para.index + 1 }}</span>
        <span class="para-text">{{ para.text }}</span>

        <!-- 变更状态徽章 -->
        <span v-if="paragraphChangeStatus[para.index + 1]" class="change-badge" :class="`${paragraphChangeStatus[para.index + 1]}-badge`">
          <el-icon v-if="paragraphChangeStatus[para.index + 1] === 'pending'"><Clock /></el-icon>
          <el-icon v-else-if="paragraphChangeStatus[para.index + 1] === 'applied'"><Check /></el-icon>
          <el-icon v-else-if="paragraphChangeStatus[para.index + 1] === 'reverted'"><RefreshLeft /></el-icon>
          {{ paragraphChangeStatus[para.index + 1] === 'pending' ? '待处理' : paragraphChangeStatus[para.index + 1] === 'applied' ? '已应用' : '已回滚' }}
        </span>
      </div>

      <el-empty v-if="paragraphs.length === 0 && !loading" description="暂无文档内容" />

      <div v-if="loading" class="loading-state">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <span>正在加载文档...</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import { Document, Loading, Clock, Check, RefreshLeft } from '@element-plus/icons-vue'
import { useDocumentStore } from '@/store/document'

const props = defineProps({
  documentName: {
    type: String,
    default: ''
  },
  paragraphs: {
    type: Array,
    default: () => []
  },
  highlightText: {
    type: String,
    default: ''
  },
  loading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['paragraphClick'])

const documentStore = useDocumentStore()

const containerRef = ref(null)
const contentRef = ref(null)
const pulseIndex = ref(-1)

// 定时器引用，用于清理
let scrollDebounceTimer = null
let pulseTimer = null

// ========== 段落变更状态映射 ==========
/**
 * 计算每个段落的变更状态
 * 返回: { paragraph_id: 'pending' | 'applied' | 'reverted' }
 */
const paragraphChangeStatus = computed(() => {
  const statusMap = {}

  // 遍历所有变更，记录每个段落的最新状态
  const allChanges = [
    ...documentStore.pendingChanges,
    ...documentStore.appliedChanges,
    ...documentStore.revertedChanges
  ].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)) // 最新的在前

  for (const change of allChanges) {
    const { tool_name, data, status } = change

    // 根据不同的工具类型，提取受影响的paragraph_id
    let affectedParagraphIds = []

    // 防御性编程：确保 data 存在再访问其属性
    if (tool_name === 'modify_paragraph' && data && data.paragraph_id) {
      affectedParagraphIds.push(data.paragraph_id)
    } else if (tool_name === 'insert_clause' && data && data.after_paragraph_id !== undefined) {
      // 插入条款影响后续段落，这里简化为标记插入点
      affectedParagraphIds.push(data.after_paragraph_id + 1)
    }
    // batch_replace_text 影响多个段落，暂时不标记单个段落

    // 为每个受影响的段落设置状态（如果尚未设置）
    for (const paraId of affectedParagraphIds) {
      if (!statusMap[paraId]) {
        statusMap[paraId] = status
      }
    }
  }

  return statusMap
})

/**
 * 是否有任何变更
 */
const hasChanges = computed(() => {
  return documentStore.hasPendingChanges ||
         documentStore.appliedChanges.length > 0 ||
         documentStore.revertedChanges.length > 0
})

// ========== 段落点击事件 ==========
function handleParagraphClick(para) {
  const paragraphId = para.index + 1
  const changeStatus = paragraphChangeStatus.value[paragraphId]

  if (changeStatus) {
    // 如果段落有变更，触发事件，由父组件处理（显示变更详情）
    emit('paragraphClick', {
      paragraph: para,
      paragraphId,
      changeStatus
    })
  }
}

// ========== 原有的高亮和滚动功能 ==========
function findParagraphIndex(text) {
  if (!text || props.paragraphs.length === 0) return -1

  const searchVariants = [
    text.slice(0, 80),
    text.slice(0, 40),
    text.slice(0, 20)
  ].filter(s => s.length > 0)

  for (const variant of searchVariants) {
    const idx = props.paragraphs.findIndex(p => p.text.includes(variant))
    if (idx !== -1) return idx
  }

  return -1
}

const highlightedIndex = computed(() => {
  return findParagraphIndex(props.highlightText)
})

function scrollToHighlight() {
  if (highlightedIndex.value === -1) return

  if (scrollDebounceTimer) {
    clearTimeout(scrollDebounceTimer)
  }

  scrollDebounceTimer = setTimeout(() => {
    nextTick(() => {
      const element = document.getElementById(`para-${highlightedIndex.value}`)
      if (element && contentRef.value) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' })

        pulseIndex.value = highlightedIndex.value

        if (pulseTimer) {
          clearTimeout(pulseTimer)
        }
        pulseTimer = setTimeout(() => {
          pulseIndex.value = -1
        }, 2000)
      }
    })
  }, 150)
}

function scrollToText(text) {
  const targetIndex = findParagraphIndex(text)
  if (targetIndex === -1) return false

  nextTick(() => {
    const element = document.getElementById(`para-${targetIndex}`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
      pulseIndex.value = targetIndex

      if (pulseTimer) {
        clearTimeout(pulseTimer)
      }
      pulseTimer = setTimeout(() => {
        pulseIndex.value = -1
      }, 2000)
    }
  })

  return true
}

watch(() => props.highlightText, (newVal) => {
  if (newVal) {
    scrollToHighlight()
  }
})

onUnmounted(() => {
  if (scrollDebounceTimer) {
    clearTimeout(scrollDebounceTimer)
  }
  if (pulseTimer) {
    clearTimeout(pulseTimer)
  }
})

defineExpose({
  scrollToHighlight,
  scrollToText
})
</script>

<style scoped>
.document-viewer {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-card);
  border-right: 1px solid var(--color-border-light);
}

.document-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-3) var(--spacing-4);
  border-bottom: 1px solid var(--color-border-light);
  background: var(--color-bg-secondary);
  flex-shrink: 0;
}

.document-title {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin: 0;
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.paragraph-count {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
}

/* ========== 变更图例 ========== */
.change-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: #f8f9fa;
  border-bottom: 1px solid #e9ecef;
  font-size: 12px;
  flex-shrink: 0;
}

.legend-title {
  font-weight: 500;
  color: #6c757d;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
}

.pending-badge {
  background: #fff3cd;
  color: #856404;
  border: 1px solid #ffc107;
}

.applied-badge {
  background: #d1e7dd;
  color: #0f5132;
  border: 1px solid #28a745;
}

.reverted-badge {
  background: #f8d7da;
  color: #721c24;
  border: 1px solid #dc3545;
}

/* ========== 文档内容 ========== */
.document-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-4);
}

.paragraph {
  display: flex;
  gap: var(--spacing-3);
  padding: var(--spacing-3) var(--spacing-4);
  margin-bottom: var(--spacing-2);
  border-radius: var(--radius-md);
  transition: all 0.3s ease;
  border-left: 3px solid transparent;
  position: relative;
  cursor: default;
}

.paragraph:hover {
  background: var(--color-bg-hover);
}

/* 变更状态段落样式 */
.paragraph.has-pending-change {
  background: linear-gradient(to right, #fff3cd, #fffbeb);
  border-left-color: #ffc107;
  cursor: pointer;
}

.paragraph.has-applied-change {
  background: linear-gradient(to right, #d1e7dd, #e8f5e9);
  border-left-color: #28a745;
  cursor: pointer;
}

.paragraph.has-reverted-change {
  background: linear-gradient(to right, #f8d7da, #ffebee);
  border-left-color: #dc3545;
  cursor: pointer;
}

.paragraph.highlighted {
  background: linear-gradient(to right, #fef3c7, #fef9c3);
  border-left-color: #f59e0b;
}

.paragraph.pulse {
  animation: highlight-pulse 1s ease-in-out 2;
}

@keyframes highlight-pulse {
  0%, 100% {
    background-color: #fef3c7;
  }
  50% {
    background-color: #fde68a;
  }
}

.para-number {
  flex-shrink: 0;
  width: 28px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-sm);
}

.paragraph.highlighted .para-number,
.paragraph.has-pending-change .para-number,
.paragraph.has-applied-change .para-number,
.paragraph.has-reverted-change .para-number {
  font-weight: 600;
}

.paragraph.has-pending-change .para-number {
  background: #ffc107;
  color: #856404;
}

.paragraph.has-applied-change .para-number {
  background: #28a745;
  color: #fff;
}

.paragraph.has-reverted-change .para-number {
  background: #dc3545;
  color: #fff;
}

.para-text {
  flex: 1;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
  color: var(--color-text-primary);
  word-break: break-word;
}

/* ========== 变更徽章 ========== */
.change-badge {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  align-self: flex-start;
}

.change-badge .el-icon {
  font-size: 12px;
}

/* ========== 加载状态 ========== */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-3);
  padding: var(--spacing-8);
  color: var(--color-text-tertiary);
}

/* ========== 滚动条样式 ========== */
.document-content::-webkit-scrollbar {
  width: 6px;
}

.document-content::-webkit-scrollbar-track {
  background: transparent;
}

.document-content::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 3px;
}

.document-content::-webkit-scrollbar-thumb:hover {
  background: var(--color-text-tertiary);
}
</style>
