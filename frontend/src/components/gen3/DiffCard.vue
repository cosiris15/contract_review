<template>
  <el-card class="diff-card" shadow="hover">
    <div class="card-header">
      <div class="header-left">
        <span class="clause-id">{{ diff.clause_id || '未知条款' }}</span>
        <el-tag size="small" :type="riskTagType">{{ diff.risk_level || 'medium' }}</el-tag>
        <el-tag size="small" effect="plain">{{ actionLabel }}</el-tag>
        <el-button text size="small" @click="showContext = !showContext">
          {{ showContext ? '隐藏上下文' : '查看上下文' }}
        </el-button>
      </div>
      <el-tag v-if="isHandled" :type="diff.status === 'approved' ? 'success' : 'danger'" size="small">
        {{ diff.status === 'approved' ? '已批准' : '已拒绝' }}
      </el-tag>
    </div>

    <ClauseContext
      :task-id="taskId"
      :clause-id="diff.clause_id"
      :original-text="diff.original_text || ''"
      :visible="showContext"
      @close="showContext = false"
    />

    <div class="view-toggle">
      <el-radio-group v-model="viewMode" size="small">
        <el-radio-button label="unified">对比</el-radio-button>
        <el-radio-button label="split">分栏</el-radio-button>
      </el-radio-group>
      <el-tag v-if="isEdited" type="warning" size="small" effect="plain">已修改</el-tag>
    </div>

    <div v-if="viewMode === 'unified'" class="block">
      <div class="label">变更对比</div>
      <div class="text unified-diff" v-html="inlineDiffHtml"></div>
    </div>
    <template v-else>
      <div class="block">
        <div class="label">原文</div>
        <div class="text original">{{ diff.original_text || '（空）' }}</div>
      </div>

      <div class="block">
        <div class="label">建议文本</div>
        <el-input
          v-if="!isHandled"
          v-model="editableProposed"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 8 }"
          class="editable-proposed"
        />
        <div v-else class="text proposed">{{ editableProposed || '（空）' }}</div>
      </div>
    </template>

    <div class="reason">{{ diff.reason || '无说明' }}</div>

    <div class="actions">
      <el-input
        v-model="feedback"
        type="textarea"
        :rows="2"
        placeholder="可选反馈（用于审批备注）"
        :disabled="isHandled"
      />
      <div class="buttons">
        <el-button type="success" :disabled="isHandled" @click="onApprove">批准</el-button>
        <el-button type="danger" plain :disabled="isHandled" @click="onReject">拒绝</el-button>
      </div>
    </div>
  </el-card>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { diffChars } from 'diff'
import ClauseContext from './ClauseContext.vue'

const props = defineProps({
  diff: { type: Object, required: true },
  taskId: { type: String, default: '' }
})

const emit = defineEmits(['approve', 'reject'])

const feedback = ref('')
const viewMode = ref('unified')
const showContext = ref(false)
const editableProposed = ref(props.diff.proposed_text || '')

const riskTagType = computed(() => {
  switch (props.diff.risk_level) {
    case 'high':
      return 'danger'
    case 'medium':
      return 'warning'
    default:
      return 'primary'
  }
})

const actionLabel = computed(() => {
  switch (props.diff.action_type) {
    case 'delete':
      return '删除'
    case 'insert':
      return '新增'
    default:
      return '修改'
  }
})

const isHandled = computed(() => ['approved', 'rejected'].includes(props.diff.status))
const isEdited = computed(() => editableProposed.value !== (props.diff.proposed_text || ''))

const htmlEscapeMap = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
}

function escapeHtml(text) {
  return (text || '')
    .replace(/[&<>"']/g, (char) => htmlEscapeMap[char])
    .replace(/\n/g, '<br>')
}

const inlineDiffHtml = computed(() => {
  const original = props.diff.original_text || ''
  const proposed = editableProposed.value || ''
  if (!original && !proposed) {
    return '<span class="no-diff">（空）</span>'
  }
  if (!original) {
    return `<span class="diff-added">${escapeHtml(proposed)}</span>`
  }
  if (!proposed) {
    return `<span class="diff-removed">${escapeHtml(original)}</span>`
  }
  return diffChars(original, proposed)
    .map((part) => {
      const text = escapeHtml(part.value)
      if (part.added) {
        return `<span class="diff-added">${text}</span>`
      }
      if (part.removed) {
        return `<span class="diff-removed">${text}</span>`
      }
      return text
    })
    .join('')
})

watch(
  () => props.diff.proposed_text,
  (value) => {
    if (!isEdited.value) {
      editableProposed.value = value || ''
    }
  }
)

function onApprove() {
  const userModifiedText = isEdited.value ? editableProposed.value : undefined
  emit('approve', props.diff.diff_id, feedback.value.trim(), userModifiedText)
}

function onReject() {
  emit('reject', props.diff.diff_id, feedback.value.trim())
}
</script>

<style scoped>
.diff-card {
  margin-bottom: 12px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.clause-id {
  font-weight: 600;
}

.block {
  margin-bottom: 10px;
}

.view-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}

.text {
  border-radius: 8px;
  padding: 10px;
  white-space: pre-wrap;
  line-height: 1.6;
}

.original {
  background: #fef2f2;
  border: 1px solid #fecaca;
}

.proposed {
  background: #ecfdf5;
  border: 1px solid #86efac;
}

.unified-diff {
  background: #fff;
  border: 1px solid var(--el-border-color);
}

.unified-diff :deep(.diff-removed) {
  background: #fee2e2;
  color: #dc2626;
  text-decoration: line-through;
  padding: 1px 2px;
  border-radius: 2px;
}

.unified-diff :deep(.diff-added) {
  background: #d1fae5;
  color: #059669;
  padding: 1px 2px;
  border-radius: 2px;
}

.editable-proposed :deep(.el-textarea__inner) {
  line-height: 1.6;
}

.reason {
  color: var(--el-text-color-regular);
  margin-bottom: 10px;
}

.actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.buttons {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
