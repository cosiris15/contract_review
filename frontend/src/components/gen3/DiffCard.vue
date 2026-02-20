<template>
  <el-card class="diff-card" shadow="hover">
    <div class="card-header">
      <div class="header-left">
        <span class="clause-id">{{ diff.clause_id || '未知条款' }}</span>
        <el-tag size="small" :type="riskTagType">{{ diff.risk_level || 'medium' }}</el-tag>
        <el-tag size="small" effect="plain">{{ actionLabel }}</el-tag>
      </div>
      <el-tag v-if="isHandled" :type="diff.status === 'approved' ? 'success' : 'danger'" size="small">
        {{ diff.status === 'approved' ? '已批准' : '已拒绝' }}
      </el-tag>
    </div>

    <div class="block">
      <div class="label">原文</div>
      <div class="text original">{{ diff.original_text || '（空）' }}</div>
    </div>

    <div class="block">
      <div class="label">建议文本</div>
      <div class="text proposed">{{ diff.proposed_text || '（空）' }}</div>
    </div>

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
import { computed, ref } from 'vue'

const props = defineProps({
  diff: { type: Object, required: true }
})

const emit = defineEmits(['approve', 'reject'])

const feedback = ref('')

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

function onApprove() {
  emit('approve', props.diff.diff_id, feedback.value.trim())
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
