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
import { computed } from 'vue'
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

// 生成 diff HTML
const diffHtml = computed(() => {
  if (!props.original && !props.modified) {
    return '<span class="no-diff">暂无内容</span>'
  }

  if (!props.original) {
    return `<span class="diff-added">${escapeHtml(props.modified)}</span>`
  }

  if (!props.modified) {
    return `<span class="diff-removed">${escapeHtml(props.original)}</span>`
  }

  const diff = diffChars(props.original, props.modified)

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
})

// HTML 转义
function escapeHtml(text) {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML.replace(/\n/g, '<br>')
}
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
