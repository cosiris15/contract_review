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
            <div class="context-label">原文</div>
            <div class="context-text original">{{ activeItem.original_text }}</div>
          </div>
          <div class="context-section">
            <div class="context-label">建议修改</div>
            <div class="context-text suggestion">{{ currentSuggestion }}</div>
          </div>
          <div v-if="activeItem.risk_description || activeItem.modification_reason" class="context-section">
            <div class="context-label">风险说明</div>
            <div class="context-text risk">{{ activeItem.risk_description || activeItem.modification_reason }}</div>
          </div>
          <!-- 定位按钮放在条目信息区域 -->
          <button class="locate-btn" @click="$emit('locate')">
            <el-icon><Location /></el-icon>
            在文档中定位
          </button>
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
        <!-- 输入框 -->
        <div class="input-row">
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
          <button
            class="confirm-btn"
            @click="$emit('complete', currentSuggestion)"
            :disabled="loading"
          >
            <el-icon><Check /></el-icon>
            确认
          </button>
        </div>
        <div class="input-hint">Enter 发送 · Shift+Enter 换行</div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import {
  Document, ChatDotRound, CircleCheck, Loading, Promotion,
  Location, Check
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
</script>

<style scoped>
.chat-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fafafa;
}

/* 对话历史区域 */
.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

/* 系统上下文消息 - 条目信息 */
.system-context-message {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  padding-bottom: 20px;
  border-bottom: 1px solid #eee;
}

.context-avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e8f4fd;
  border-radius: 6px;
  color: #1890ff;
}

.context-content {
  flex: 1;
  min-width: 0;
}

.context-section {
  margin-bottom: 12px;
}

.context-label {
  font-size: 12px;
  font-weight: 500;
  color: #999;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.context-text {
  padding: 12px 14px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.context-text.original {
  background: #fff;
  border: 1px solid #e8e8e8;
  color: #333;
}

.context-text.suggestion {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
  color: #135200;
}

.context-text.risk {
  background: #fffbe6;
  border: 1px solid #ffe58f;
  color: #ad6800;
}

.locate-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #1890ff;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s;
}

.locate-btn:hover {
  background: #e6f7ff;
}

/* 空状态 */
.empty-chat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #bbb;
  gap: 12px;
}

/* 流式输出指示器 */
.streaming-indicator {
  padding: 8px 0;
}

.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 16px;
  background: #1890ff;
  animation: cursor-blink 1s step-end infinite;
}

@keyframes cursor-blink {
  50% { opacity: 0; }
}

/* 底部输入区 */
.input-area {
  flex-shrink: 0;
  padding: 16px 20px;
  background: #fff;
  border-top: 1px solid #eee;
}

/* 已完成横幅 */
.completed-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px;
  background: #f6ffed;
  border-radius: 8px;
  color: #52c41a;
  font-size: 14px;
}

/* 输入行 */
.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

/* 输入框容器 */
.input-container {
  flex: 1;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 12px;
  background: #f5f5f5;
  border: 1px solid transparent;
  border-radius: 12px;
  transition: all 0.2s;
}

.input-container:focus-within {
  background: #fff;
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
  min-height: 22px;
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

/* 确认按钮 */
.confirm-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 20px;
  height: 52px;
  border: none;
  border-radius: 12px;
  background: #52c41a;
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.confirm-btn:hover:not(:disabled) {
  background: #73d13d;
}

.confirm-btn:disabled {
  background: #d9d9d9;
  cursor: not-allowed;
}

.input-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #bbb;
}

/* 响应式 */
@media (max-width: 480px) {
  .chat-history {
    padding: 16px;
  }

  .input-row {
    flex-direction: column;
    gap: 8px;
  }

  .confirm-btn {
    width: 100%;
    height: 44px;
    justify-content: center;
  }
}
</style>
