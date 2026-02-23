<template>
  <el-card v-if="visible" class="clause-context" shadow="never">
    <template #header>
      <div class="ctx-header">
        <span>条款上下文: {{ clauseId }}</span>
        <el-button text size="small" @click="$emit('close')">收起</el-button>
      </div>
    </template>
    <div v-if="loading" class="loading">
      <el-icon class="is-loading"><Loading /></el-icon>
    </div>
    <div v-else-if="clauseText" class="clause-text" v-html="highlightedText"></div>
    <el-empty v-else description="无法加载条款上下文" :image-size="40" />
  </el-card>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import gen3Api from '@/api/gen3'

const props = defineProps({
  taskId: { type: String, default: '' },
  clauseId: { type: String, default: '' },
  originalText: { type: String, default: '' },
  visible: { type: Boolean, default: false }
})

defineEmits(['close'])

const clauseText = ref('')
const loading = ref(false)

function escapeHtml(text) {
  return (text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/\n/g, '<br>')
}

const highlightedText = computed(() => {
  if (!clauseText.value) {
    return ''
  }
  const escapedText = escapeHtml(clauseText.value)
  if (!props.originalText) {
    return escapedText
  }
  const escapedNeedle = escapeHtml(props.originalText)
  const index = escapedText.indexOf(escapedNeedle)
  if (index < 0) {
    return escapedText
  }
  return [
    escapedText.slice(0, index),
    `<mark class="diff-highlight">${escapedNeedle}</mark>`,
    escapedText.slice(index + escapedNeedle.length)
  ].join('')
})

watch(
  [() => props.clauseId, () => props.visible, () => props.taskId],
  async ([clauseId, visible, taskId]) => {
    if (!clauseId || !visible || !taskId) {
      clauseText.value = ''
      return
    }
    loading.value = true
    try {
      const response = await gen3Api.getClauseContext(taskId, clauseId)
      clauseText.value = response.data?.text || ''
    } catch (_error) {
      clauseText.value = ''
    } finally {
      loading.value = false
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.clause-context {
  margin-bottom: 12px;
}

.ctx-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.loading {
  text-align: center;
  padding: 16px;
}

.clause-text {
  white-space: pre-wrap;
  line-height: 1.7;
  font-size: 13px;
  max-height: 220px;
  overflow: auto;
}

.clause-text :deep(.diff-highlight) {
  background: #fef3c7;
  border-bottom: 2px solid #f59e0b;
  padding: 1px 0;
}
</style>
