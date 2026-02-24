<template>
  <el-card class="progress-card">
    <template #header>
      <div class="header">条款进度</div>
    </template>

    <el-progress :percentage="percentage" :stroke-width="4" />
    <div class="summary">已审阅 {{ reviewedCount }} / {{ totalClauses }} 条款</div>

    <el-empty v-if="totalClauses === 0" description="等待审阅数据" :image-size="70" />
    <ul v-else class="clause-list">
      <li
        v-for="item in clauseItems"
        :key="item.key"
        :class="['clause-item', item.status]"
      >
        <span :class="['status-dot', `status-dot--${item.status}`]"></span>
        <span class="text">{{ item.label }}</span>
      </li>
    </ul>
  </el-card>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  currentIndex: { type: Number, default: 0 },
  totalClauses: { type: Number, default: 0 },
  currentClauseId: { type: String, default: '' },
  approvedDiffs: { type: Array, default: () => [] },
  rejectedDiffs: { type: Array, default: () => [] }
})

const percentage = computed(() => (props.totalClauses > 0
  ? Math.round((props.currentIndex / props.totalClauses) * 100)
  : 0))

const reviewedCount = computed(() => Math.min(props.currentIndex, props.totalClauses))

const clauseItems = computed(() => {
  const items = []
  for (let i = 0; i < props.totalClauses; i += 1) {
    const isCurrent = i === props.currentIndex
    const isDone = i < props.currentIndex
    items.push({
      key: `clause_${i}`,
      label: isCurrent && props.currentClauseId
        ? props.currentClauseId
        : `条款 ${i + 1}`,
      status: isCurrent ? 'current' : (isDone ? 'done' : 'pending')
    })
  }
  return items
})
</script>

<style scoped>
.header {
  font-weight: 600;
}

.summary {
  margin-top: 10px;
  color: var(--el-text-color-secondary);
}

.clause-list {
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
  max-height: 360px;
  overflow: auto;
}

.clause-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.status-dot--done {
  background: var(--el-color-success);
}

.status-dot--current {
  background: var(--el-color-primary);
  animation: pulse 1.5s infinite;
}

.status-dot--pending {
  background: rgba(55, 53, 47, 0.12);
}

.clause-item.current {
  font-weight: 600;
  color: var(--el-color-primary);
}

.clause-item.done {
  color: var(--el-color-success);
}

.clause-item.pending {
  color: var(--el-text-color-secondary);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
