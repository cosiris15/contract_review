<template>
  <div class="item-navigator">
    <div class="navigator-header">
      <h3>审阅条目</h3>
      <div class="progress-info">
        <el-tag type="success" size="small">
          {{ completedCount }}/{{ items.length }} 已完成
        </el-tag>
      </div>
    </div>

    <div class="navigator-list">
      <div
        v-for="item in items"
        :key="item.id"
        class="navigator-item"
        :class="{
          active: activeItemId === item.id,
          completed: item.status === 'completed',
          'in-progress': item.status === 'in_progress'
        }"
        @click="$emit('select', item)"
      >
        <div class="item-status">
          <el-icon v-if="item.status === 'completed'" color="#67c23a" :size="18">
            <CircleCheck />
          </el-icon>
          <el-icon v-else-if="item.status === 'in_progress'" color="#409eff" :size="18">
            <ChatDotRound />
          </el-icon>
          <el-icon v-else color="#909399" :size="18">
            <CirclePlus />
          </el-icon>
        </div>

        <div class="item-content">
          <div class="item-header">
            <el-tag
              :type="getPriorityType(item.priority)"
              size="small"
              class="priority-tag"
            >
              {{ getPriorityLabel(item.priority) }}
            </el-tag>
            <span class="item-type">{{ item.item_type === 'modification' ? '修改' : '行动' }}</span>
          </div>
          <p class="item-title">{{ truncateText(item.original_text || item.description, 50) }}</p>
          <div v-if="item.message_count" class="item-meta">
            <el-icon :size="12"><ChatDotSquare /></el-icon>
            <span>{{ item.message_count }} 条对话</span>
          </div>
        </div>
      </div>

      <el-empty v-if="items.length === 0" description="暂无审阅条目" />
    </div>

    <div class="navigator-footer">
      <el-button
        type="primary"
        :disabled="completedCount < items.length"
        @click="$emit('export')"
      >
        <el-icon><Download /></el-icon>
        导出结果
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { CircleCheck, CirclePlus, ChatDotRound, ChatDotSquare, Download } from '@element-plus/icons-vue'

const props = defineProps({
  items: {
    type: Array,
    default: () => []
  },
  activeItemId: {
    type: String,
    default: null
  }
})

defineEmits(['select', 'export'])

const completedCount = computed(() => {
  return props.items.filter(item => item.status === 'completed').length
})

function getPriorityType(priority) {
  const types = {
    must: 'danger',
    should: 'warning',
    may: 'info'
  }
  return types[priority] || 'info'
}

function getPriorityLabel(priority) {
  const labels = {
    must: '必须',
    should: '建议',
    may: '可选'
  }
  return labels[priority] || priority
}

function truncateText(text, maxLength) {
  if (!text) return ''
  return text.length > maxLength ? text.slice(0, maxLength) + '...' : text
}
</script>

<style scoped>
.item-navigator {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-card);
  border-right: 1px solid var(--color-border-light);
}

.navigator-header {
  padding: var(--spacing-4);
  border-bottom: 1px solid var(--color-border-light);
}

.navigator-header h3 {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.progress-info {
  display: flex;
  align-items: center;
}

.navigator-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-2);
}

.navigator-item {
  display: flex;
  gap: var(--spacing-3);
  padding: var(--spacing-3);
  margin-bottom: var(--spacing-2);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s;
  border: 2px solid transparent;
}

.navigator-item:hover {
  background: var(--color-bg-hover);
}

.navigator-item.active {
  background: var(--color-primary-bg);
  border-color: var(--color-primary);
}

.navigator-item.completed {
  opacity: 0.8;
}

.navigator-item.completed .item-title {
  text-decoration: line-through;
  color: var(--color-text-tertiary);
}

.item-status {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  padding-top: 2px;
}

.item-content {
  flex: 1;
  min-width: 0;
}

.item-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-1);
}

.priority-tag {
  font-size: 10px;
}

.item-type {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.item-title {
  margin: 0;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-normal);
  color: var(--color-text-primary);
  word-break: break-word;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
  margin-top: var(--spacing-1);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.navigator-footer {
  padding: var(--spacing-4);
  border-top: 1px solid var(--color-border-light);
}

.navigator-footer .el-button {
  width: 100%;
}
</style>
