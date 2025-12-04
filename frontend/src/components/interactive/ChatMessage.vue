<template>
  <div class="chat-message" :class="[message.role, { streaming: message.isStreaming, error: message.isError }]">
    <div class="message-avatar">
      <div v-if="message.role === 'assistant'" class="avatar ai">
        <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
        </svg>
      </div>
      <div v-else class="avatar user">
        <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
          <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
        </svg>
      </div>
    </div>
    <div class="message-content">
      <div class="message-header">
        <span class="sender-name">{{ message.role === 'assistant' ? '十行' : '您' }}</span>
      </div>
      <div class="message-text" v-html="renderContent(message.content)"></div>

      <!-- 上下文消息的定位按钮（第一条消息或标记为 isContext 的消息显示） -->
      <button v-if="message.isContext || showLocateBtn" class="locate-btn" @click="$emit('locate')">
        <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
          <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>
        </svg>
        在文档中定位
      </button>

      <!-- AI 消息中的建议更新 -->
      <div v-if="message.role === 'assistant' && message.suggestion_snapshot" class="suggestion-update">
        <div class="update-header">
          <span class="update-icon">✨</span>
          <span>建议已更新</span>
        </div>
        <div class="update-content">{{ message.suggestion_snapshot }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  message: {
    type: Object,
    required: true
  },
  showLocateBtn: {
    type: Boolean,
    default: false
  }
})

defineEmits(['locate'])

// 渲染消息内容（Markdown 处理）
function renderContent(content) {
  if (!content) return ''

  // 先处理引用块（在转义之前，因为需要识别 > 符号）
  // 将连续的引用行合并为一个引用块
  const lines = content.split('\n')
  const processedLines = []
  let inQuote = false
  let quoteContent = []

  for (const line of lines) {
    if (line.startsWith('> ')) {
      inQuote = true
      quoteContent.push(line.slice(2))
    } else {
      if (inQuote) {
        // 结束引用块
        processedLines.push(`<blockquote>${quoteContent.join('<br>')}</blockquote>`)
        quoteContent = []
        inQuote = false
      }
      processedLines.push(line)
    }
  }
  // 处理末尾的引用块
  if (inQuote) {
    processedLines.push(`<blockquote>${quoteContent.join('<br>')}</blockquote>`)
  }

  let html = processedLines.join('\n')
    // 转义 HTML（但保留已处理的 blockquote）
    .replace(/&(?!amp;|lt;|gt;)/g, '&amp;')
    .replace(/<(?!\/?blockquote>|br>)/g, '&lt;')
    .replace(/(?<!blockquote|br)>/g, '&gt;')
    // 换行（但不处理 blockquote 内的）
    .replace(/\n/g, '<br>')
    // 粗体
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // 斜体
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // 代码
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // 中文书名号样式
    .replace(/「(.+?)」/g, '<span class="cn-quote">$1</span>')

  return html
}
</script>

<style scoped>
.chat-message {
  display: flex;
  gap: 12px;
  padding: 16px 0;
}

.chat-message + .chat-message {
  border-top: 1px solid #f0f0f0;
}

/* 头像 */
.message-avatar {
  flex-shrink: 0;
}

.avatar {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
}

.avatar.ai {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

.avatar.user {
  background: #10a37f;
  color: #fff;
}

/* 内容区 */
.message-content {
  flex: 1;
  min-width: 0;
}

.message-header {
  margin-bottom: 6px;
}

.sender-name {
  font-size: 14px;
  font-weight: 600;
  color: #333;
}

.message-text {
  font-size: 15px;
  line-height: 1.7;
  color: #374151;
  word-break: break-word;
}

.message-text :deep(strong) {
  font-weight: 600;
  color: #111;
}

.message-text :deep(code) {
  padding: 2px 6px;
  background: #f3f4f6;
  border-radius: 4px;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  color: #111;
}

/* 引用块 */
.message-text :deep(blockquote) {
  margin: 8px 0;
  padding: 10px 16px;
  background: #f8f9fa;
  border-left: 3px solid #667eea;
  border-radius: 0 6px 6px 0;
  color: #555;
  font-size: 14px;
  line-height: 1.6;
}

/* 中文引号强调 */
.message-text :deep(.cn-quote) {
  color: #667eea;
  font-weight: 500;
}

/* 定位按钮 */
.locate-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding: 8px 14px;
  border: 1px solid #e5e5e5;
  border-radius: 6px;
  background: #fff;
  color: #666;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.locate-btn:hover {
  border-color: #1890ff;
  color: #1890ff;
}

/* 建议更新卡片 */
.suggestion-update {
  margin-top: 12px;
  padding: 12px 16px;
  background: #f0fdf4;
  border: 1px solid #86efac;
  border-radius: 8px;
}

.update-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 500;
  color: #166534;
}

.update-icon {
  font-size: 14px;
}

.update-content {
  font-size: 14px;
  line-height: 1.6;
  color: #166534;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 流式输出 - 打字光标 */
.chat-message.streaming .message-text::after {
  content: '';
  display: inline-block;
  width: 2px;
  height: 16px;
  margin-left: 2px;
  background: #667eea;
  animation: cursor-blink 1s step-end infinite;
  vertical-align: text-bottom;
}

@keyframes cursor-blink {
  50% { opacity: 0; }
}

/* 错误状态 */
.chat-message.error .message-text {
  color: #dc2626;
}

.chat-message.error .avatar.ai {
  background: #fee2e2;
  color: #dc2626;
}
</style>
