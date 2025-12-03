<template>
  <div class="chat-message" :class="[message.role, { 'has-suggestion': message.suggestion_snapshot }]">
    <div class="message-avatar">
      <el-icon v-if="message.role === 'assistant'" :size="24" color="#409eff">
        <Service />
      </el-icon>
      <el-icon v-else :size="24" color="#67c23a">
        <User />
      </el-icon>
    </div>
    <div class="message-content">
      <div class="message-header">
        <span class="message-sender">{{ message.role === 'assistant' ? 'AI 助手' : '您' }}</span>
        <span class="message-time">{{ formatTime(message.timestamp) }}</span>
      </div>
      <div class="message-body" v-html="renderMarkdown(message.content)"></div>

      <!-- AI 消息中的建议快照 -->
      <div v-if="message.role === 'assistant' && message.suggestion_snapshot" class="suggestion-snapshot">
        <div class="snapshot-header">
          <el-icon><Edit /></el-icon>
          <span>当前修改建议</span>
          <el-button
            type="primary"
            text
            size="small"
            @click="$emit('copy-suggestion', message.suggestion_snapshot)"
          >
            <el-icon><CopyDocument /></el-icon>
            复制
          </el-button>
        </div>
        <div class="snapshot-content">
          {{ message.suggestion_snapshot }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Service, User, Edit, CopyDocument } from '@element-plus/icons-vue'

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
})

defineEmits(['copy-suggestion'])

function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

// 简单的文本处理（不依赖外部 Markdown 库）
function renderMarkdown(content) {
  if (!content) return ''

  // 基本的文本处理
  let html = content
    // 转义 HTML
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // 换行
    .replace(/\n/g, '<br>')
    // 粗体
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // 斜体
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // 代码
    .replace(/`([^`]+)`/g, '<code>$1</code>')

  return html
}
</script>

<style scoped>
.chat-message {
  display: flex;
  gap: var(--spacing-3);
  padding: var(--spacing-4);
  border-radius: var(--radius-lg);
  transition: background 0.2s;
}

.chat-message:hover {
  background: var(--color-bg-hover);
}

.chat-message.user {
  flex-direction: row-reverse;
}

.chat-message.user .message-content {
  align-items: flex-end;
}

.chat-message.user .message-header {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-secondary);
  border-radius: 50%;
}

.chat-message.assistant .message-avatar {
  background: var(--color-primary-bg);
}

.chat-message.user .message-avatar {
  background: var(--color-success-bg);
}

.message-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-width: 85%;
}

.message-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-1);
}

.message-sender {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.message-time {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.message-body {
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-bg-card);
  border-radius: var(--radius-md);
  font-size: var(--font-size-base);
  line-height: var(--line-height-relaxed);
  color: var(--color-text-primary);
}

.chat-message.assistant .message-body {
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border-light);
}

.chat-message.user .message-body {
  background: var(--color-primary);
  color: white;
  border: none;
}

/* Markdown 内容样式 */
.message-body :deep(p) {
  margin: 0 0 var(--spacing-2);
}

.message-body :deep(p:last-child) {
  margin-bottom: 0;
}

.message-body :deep(code) {
  padding: 2px 6px;
  background: var(--color-bg-hover);
  border-radius: var(--radius-sm);
  font-family: monospace;
  font-size: 0.9em;
}

.chat-message.user .message-body :deep(code) {
  background: rgba(255, 255, 255, 0.2);
}

.message-body :deep(pre) {
  padding: var(--spacing-3);
  background: var(--color-bg-hover);
  border-radius: var(--radius-md);
  overflow-x: auto;
  margin: var(--spacing-2) 0;
}

.message-body :deep(ul),
.message-body :deep(ol) {
  padding-left: var(--spacing-5);
  margin: var(--spacing-2) 0;
}

.message-body :deep(li) {
  margin: var(--spacing-1) 0;
}

/* 建议快照样式 */
.suggestion-snapshot {
  margin-top: var(--spacing-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.snapshot-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-hover);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border-light);
}

.snapshot-header span {
  flex: 1;
  font-weight: var(--font-weight-medium);
}

.snapshot-content {
  padding: var(--spacing-3);
  background: var(--color-bg-card);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
  color: var(--color-text-primary);
  white-space: pre-wrap;
}
</style>
