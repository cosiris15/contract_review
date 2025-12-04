<template>
  <div class="chat-panel">
    <!-- 对话历史 - 全屏聊天区域 -->
    <div class="chat-history" ref="chatHistoryRef">
      <!-- 系统消息：条目上下文 -->
      <div v-if="activeItem" class="system-context-message">
        <div class="context-avatar">
          <el-icon :size="20"><Document /></el-icon>
        </div>
        <div class="context-content">
          <div class="context-section">
            <div class="context-label">📄 原文</div>
            <div class="context-text original">{{ activeItem.original_text }}</div>
          </div>
          <div class="context-section">
            <div class="context-label">✏️ 建议修改</div>
            <div class="context-text suggestion">{{ currentSuggestion }}</div>
          </div>
          <div v-if="activeItem.risk_description || activeItem.modification_reason" class="context-section">
            <div class="context-label">⚠️ 风险说明</div>
            <div class="context-text risk">{{ activeItem.risk_description || activeItem.modification_reason }}</div>
          </div>
        </div>
      </div>

      <!-- 空状态提示 -->
      <div v-if="!activeItem" class="empty-chat">
        <el-icon :size="48"><ChatDotRound /></el-icon>
        <span>请选择一个条目开始审阅</span>
      </div>

      <!-- 对话消息列表 -->
      <ChatMessage
        v-for="(msg, index) in messages"
        :key="index"
        :message="msg"
        @copy-suggestion="copySuggestion"
      />

      <!-- 流式输出时的打字指示器 -->
      <div v-if="streaming" class="streaming-indicator">
        <span class="typing-cursor"></span>
      </div>
    </div>

    <!-- 底部输入区 -->
    <div v-if="activeItem" class="input-area">
      <!-- 已完成提示 -->
      <div v-if="activeItem.status === 'completed'" class="completed-banner">
        <el-icon><CircleCheck /></el-icon>
        <span>此条目已审阅完成</span>
      </div>

      <template v-else>
        <!-- 快捷回复按钮 -->
        <div class="quick-replies">
          <button
            class="quick-btn accept"
            @click="sendQuickMessage('同意这个修改建议')"
            :disabled="loading"
          >
            ✓ 同意
          </button>
          <button
            class="quick-btn"
            @click="sendQuickMessage('请详细解释为什么需要这样修改')"
            :disabled="loading"
          >
            请解释
          </button>
          <button
            class="quick-btn"
            @click="sendQuickMessage('这个修改过于保守，请给出更有利于我方的建议')"
            :disabled="loading"
          >
            更激进
          </button>
          <button
            class="quick-btn"
            @click="sendQuickMessage('保留原文，不需要修改')"
            :disabled="loading"
          >
            保留原文
          </button>
        </div>

        <!-- 输入框 -->
        <div class="input-container">
          <textarea
            ref="inputRef"
            v-model="inputText"
            class="chat-input"
            placeholder="输入您的意见或问题..."
            rows="1"
            @input="autoResize"
            @keydown.enter.exact="handleEnter"
            @keydown.enter.shift.exact="() => {}"
            :disabled="loading"
          ></textarea>
          <button
            class="send-btn"
            @click="send"
            :disabled="!inputText.trim() || loading"
          >
            <el-icon v-if="loading" class="is-loading"><Loading /></el-icon>
            <el-icon v-else><Promotion /></el-icon>
          </button>
        </div>

        <div class="input-hint">
          按 Enter 发送，Shift + Enter 换行
        </div>
      </template>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <button class="action-btn" @click="$emit('locate')">
          <el-icon><Location /></el-icon>
          定位原文
        </button>
        <button class="action-btn copy" @click="copySuggestion">
          <el-icon><CopyDocument /></el-icon>
          复制建议
        </button>
        <button
          class="action-btn confirm"
          @click="$emit('complete', currentSuggestion)"
          :disabled="loading || activeItem.status === 'completed'"
        >
          <el-icon><Check /></el-icon>
          确认此条目
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Document, ChatDotRound, CircleCheck, Loading, Promotion,
  Location, CopyDocument, Check
} from '@element-plus/icons-vue'
import ChatMessage from './ChatMessage.vue'

const props = defineProps({
  items: {
    type: Array,
    default: () => []
  },
  activeItem: {
    type: Object,
    default: null
  },
  messages: {
    type: Array,
    default: () => []
  },
  currentSuggestion: {
    type: String,
    default: ''
  },
  loading: {
    type: Boolean,
    default: false
  },
  streaming: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['select-item', 'send-message', 'complete', 'locate'])

const inputText = ref('')
const chatHistoryRef = ref(null)
const inputRef = ref(null)

// 自动调整输入框高度
function autoResize() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

// 滚动到底部
function scrollToBottom() {
  nextTick(() => {
    if (chatHistoryRef.value) {
      chatHistoryRef.value.scrollTop = chatHistoryRef.value.scrollHeight
    }
  })
}

// 监听消息变化，自动滚动
watch(() => props.messages.length, scrollToBottom)
watch(() => props.streaming, scrollToBottom)

// 切换条目时滚动到顶部
watch(() => props.activeItem?.id, () => {
  nextTick(() => {
    if (chatHistoryRef.value) {
      chatHistoryRef.value.scrollTop = 0
    }
  })
})

// 处理 Enter 键
function handleEnter(e) {
  if (!e.shiftKey) {
    e.preventDefault()
    send()
  }
}

// 发送消息
function send() {
  if (!inputText.value.trim() || props.loading) return
  emit('send-message', inputText.value.trim())
  inputText.value = ''
  // 重置输入框高度
  nextTick(() => {
    if (inputRef.value) {
      inputRef.value.style.height = 'auto'
    }
  })
}

// 发送快捷消息
function sendQuickMessage(message) {
  if (props.loading || props.activeItem?.status === 'completed') return
  emit('send-message', message)
}

// 复制建议
function copySuggestion() {
  const text = props.currentSuggestion
  if (!text) return

  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}
</script>

<style scoped>
.chat-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f7f7f8;
}

/* 对话历史区域 */
.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  padding-bottom: 0;
}

/* 系统上下文消息 - 条目信息 */
.system-context-message {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid #e5e5e5;
}

.context-avatar {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e8f4fd;
  border-radius: 8px;
  color: #1890ff;
}

.context-content {
  flex: 1;
  min-width: 0;
}

.context-section {
  margin-bottom: 16px;
}

.context-section:last-child {
  margin-bottom: 0;
}

.context-label {
  font-size: 13px;
  font-weight: 600;
  color: #666;
  margin-bottom: 8px;
}

.context-text {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.context-text.original {
  background: #fff;
  border: 1px solid #e5e5e5;
  color: #333;
}

.context-text.suggestion {
  background: #e6f7e6;
  border: 1px solid #b7eb8f;
  color: #135200;
}

.context-text.risk {
  background: #fff7e6;
  border: 1px solid #ffd591;
  color: #ad4e00;
}

/* 空状态 */
.empty-chat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #999;
  gap: 16px;
}

/* 流式输出指示器 */
.streaming-indicator {
  padding: 0 20px;
  height: 24px;
}

.typing-cursor {
  display: inline-block;
  width: 8px;
  height: 18px;
  background: #1890ff;
  border-radius: 2px;
  animation: blink 1s steps(2, start) infinite;
}

@keyframes blink {
  to { visibility: hidden; }
}

/* 底部输入区 */
.input-area {
  flex-shrink: 0;
  padding: 16px 20px;
  background: #fff;
  border-top: 1px solid #e5e5e5;
}

/* 已完成横幅 */
.completed-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  background: #f6ffed;
  border: 1px solid #b7eb8f;
  border-radius: 8px;
  color: #52c41a;
  font-size: 14px;
  margin-bottom: 12px;
}

/* 快捷回复按钮 */
.quick-replies {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.quick-btn {
  padding: 6px 14px;
  border: 1px solid #d9d9d9;
  border-radius: 16px;
  background: #fff;
  color: #666;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.quick-btn:hover:not(:disabled) {
  border-color: #1890ff;
  color: #1890ff;
}

.quick-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.quick-btn.accept {
  background: #52c41a;
  border-color: #52c41a;
  color: #fff;
}

.quick-btn.accept:hover:not(:disabled) {
  background: #73d13d;
  border-color: #73d13d;
  color: #fff;
}

/* 输入框容器 */
.input-container {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 8px 12px;
  background: #f7f7f8;
  border: 1px solid #e5e5e5;
  border-radius: 12px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.input-container:focus-within {
  border-color: #1890ff;
  box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.1);
}

.chat-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  min-height: 24px;
  max-height: 120px;
  font-family: inherit;
}

.chat-input::placeholder {
  color: #bbb;
}

.chat-input:disabled {
  opacity: 0.5;
}

.send-btn {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 8px;
  background: #1890ff;
  color: #fff;
  cursor: pointer;
  transition: background 0.2s;
}

.send-btn:hover:not(:disabled) {
  background: #40a9ff;
}

.send-btn:disabled {
  background: #d9d9d9;
  cursor: not-allowed;
}

.input-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #bbb;
  text-align: right;
}

/* 操作按钮栏 */
.action-bar {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: #fff;
  color: #666;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover:not(:disabled) {
  border-color: #1890ff;
  color: #1890ff;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn.copy {
  margin-left: auto;
}

.action-btn.confirm {
  background: #52c41a;
  border-color: #52c41a;
  color: #fff;
}

.action-btn.confirm:hover:not(:disabled) {
  background: #73d13d;
  border-color: #73d13d;
}

/* 响应式 */
@media (max-width: 480px) {
  .chat-history {
    padding: 16px;
  }

  .quick-replies {
    gap: 6px;
  }

  .quick-btn {
    padding: 5px 10px;
    font-size: 12px;
  }

  .action-bar {
    flex-wrap: wrap;
  }

  .action-btn.copy {
    margin-left: 0;
  }
}
</style>
