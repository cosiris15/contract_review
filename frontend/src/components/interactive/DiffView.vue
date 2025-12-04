<template>
  <div class="diff-view">
    <div class="diff-header">
      <span class="diff-title">修改对比</span>
      <div class="diff-legend">
        <span class="legend-item removed">删除</span>
        <span class="legend-item added">新增</span>
      </div>
    </div>
    <div class="diff-content" v-html="diffHtml"></div>
  </div>
</template>

<script setup>
import { ref, watch, onUnmounted } from 'vue'
import { diffChars } from 'diff'

const props = defineProps({
  original: {
    type: String,
    default: ''
  },
  modified: {
    type: String,
    default: ''
  }
})

// 文本长度限制，避免超大文本卡顿
const MAX_TEXT_LENGTH = 10000

// 高效的 HTML 转义（使用字符串替换代替 DOM 操作）
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

// 计算 diff HTML
function computeDiff(original, modified) {
  if (!original && !modified) {
    return '<span class="no-diff">暂无内容</span>'
  }

  // 截断过长文本
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

// 使用 ref 存储结果，配合防抖
const diffHtml = ref('<span class="no-diff">暂无内容</span>')

// 防抖计算 diff
let debounceTimer = null

watch(
  [() => props.original, () => props.modified],
  ([original, modified]) => {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
    }

    debounceTimer = setTimeout(() => {
      diffHtml.value = computeDiff(original, modified)
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
}

.diff-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #e9ecef;
  border-bottom: 1px solid #dee2e6;
}

.diff-title {
  font-size: 13px;
  font-weight: 500;
  color: #495057;
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

.diff-content {
  padding: 12px;
  font-size: 14px;
  line-height: 1.8;
  color: #212529;
  white-space: pre-wrap;
  word-break: break-word;
}

.diff-content :deep(.diff-removed) {
  background: #fee2e2;
  color: #dc2626;
  text-decoration: line-through;
  padding: 1px 2px;
  border-radius: 2px;
}

.diff-content :deep(.diff-added) {
  background: #d1fae5;
  color: #059669;
  padding: 1px 2px;
  border-radius: 2px;
}

.diff-content :deep(.no-diff) {
  color: #6c757d;
  font-style: italic;
}
</style>
