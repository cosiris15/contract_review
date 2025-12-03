<template>
  <div class="document-viewer" ref="containerRef">
    <div class="document-header">
      <h3 class="document-title">
        <el-icon><Document /></el-icon>
        {{ documentName || '合同文档' }}
      </h3>
      <span class="paragraph-count">共 {{ paragraphs.length }} 段</span>
    </div>

    <div class="document-content" ref="contentRef">
      <div
        v-for="para in paragraphs"
        :key="para.index"
        :id="`para-${para.index}`"
        class="paragraph"
        :class="{
          highlighted: highlightedIndex === para.index,
          pulse: pulseIndex === para.index
        }"
      >
        <span class="para-number">{{ para.index + 1 }}</span>
        <span class="para-text">{{ para.text }}</span>
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
import { ref, computed, watch, nextTick } from 'vue'
import { Document, Loading } from '@element-plus/icons-vue'

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

const containerRef = ref(null)
const contentRef = ref(null)
const pulseIndex = ref(-1)

// 计算哪个段落应该高亮
const highlightedIndex = computed(() => {
  if (!props.highlightText || props.paragraphs.length === 0) return -1

  // 取前80个字符做匹配（避免太长的文本匹配问题）
  const searchText = props.highlightText.slice(0, 80)

  // 精确匹配
  let targetIndex = props.paragraphs.findIndex(p => p.text.includes(searchText))

  // 如果没找到，尝试用前40个字符
  if (targetIndex === -1 && searchText.length > 40) {
    const shorterText = searchText.slice(0, 40)
    targetIndex = props.paragraphs.findIndex(p => p.text.includes(shorterText))
  }

  // 如果还没找到，尝试用前20个字符
  if (targetIndex === -1 && searchText.length > 20) {
    const shorterText = searchText.slice(0, 20)
    targetIndex = props.paragraphs.findIndex(p => p.text.includes(shorterText))
  }

  return targetIndex
})

// 滚动到高亮的段落
function scrollToHighlight() {
  if (highlightedIndex.value === -1) return

  nextTick(() => {
    const element = document.getElementById(`para-${highlightedIndex.value}`)
    if (element && contentRef.value) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })

      // 添加脉冲动画
      pulseIndex.value = highlightedIndex.value
      setTimeout(() => {
        pulseIndex.value = -1
      }, 2000)
    }
  })
}

// 滚动到指定文本（供外部调用）
function scrollToText(text) {
  if (!text || props.paragraphs.length === 0) return false

  const searchText = text.slice(0, 80)
  let targetIndex = props.paragraphs.findIndex(p => p.text.includes(searchText))

  if (targetIndex === -1 && searchText.length > 40) {
    const shorterText = searchText.slice(0, 40)
    targetIndex = props.paragraphs.findIndex(p => p.text.includes(shorterText))
  }

  if (targetIndex === -1) return false

  nextTick(() => {
    const element = document.getElementById(`para-${targetIndex}`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
      pulseIndex.value = targetIndex
      setTimeout(() => {
        pulseIndex.value = -1
      }, 2000)
    }
  })

  return true
}

// 监听 highlightText 变化，自动滚动
watch(() => props.highlightText, (newVal) => {
  if (newVal) {
    scrollToHighlight()
  }
})

// 暴露给父组件的方法
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
}

.paragraph:hover {
  background: var(--color-bg-hover);
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

.paragraph.highlighted .para-number {
  background: #fcd34d;
  color: #92400e;
}

.para-text {
  flex: 1;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
  color: var(--color-text-primary);
  word-break: break-word;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-3);
  padding: var(--spacing-8);
  color: var(--color-text-tertiary);
}

/* 滚动条样式 */
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
