<template>
  <div class="chat-panel">
    <!-- 对话历史 -->
    <div class="chat-history" ref="chatHistoryRef">
      <!-- 空状态 -->
      <div v-if="!activeItem" class="empty-chat">
        <el-icon :size="48"><ChatDotRound /></el-icon>
        <span>请选择一个条目开始审阅</span>
      </div>

      <!-- AI 的第一条消息：条目上下文 -->
      <ChatMessage
        v-if="activeItem"
        :message="contextMessage"
        @locate="$emit('locate')"
      />

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
            class="next-btn"
            @click="$emit('complete', currentSuggestion)"
            :disabled="loading"
          >
            下一条
            <el-icon><ArrowRight /></el-icon>
          </button>
        </div>
        <div class="input-hint">Enter 发送 · Shift+Enter 换行</div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { ChatDotRound, CircleCheck, Loading, Promotion, ArrowRight } from '@element-plus/icons-vue'
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

// 构造 AI 的第一条消息（条目上下文）
const contextMessage = computed(() => {
  if (!props.activeItem) return null

  let content = `**原文**\n${props.activeItem.original_text}\n\n**建议修改**\n${props.currentSuggestion}`

  if (props.activeItem.risk_description || props.activeItem.modification_reason) {
    content += `\n\n**风险说明**\n${props.activeItem.risk_description || props.activeItem.modification_reason}`
  }

  return {
    role: 'assistant',
    content,
    isContext: true  // 标记为上下文消息，用于显示定位按钮
  }
})

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

/* 下一条按钮 */
.next-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 4px;
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

.next-btn:hover:not(:disabled) {
  background: #73d13d;
}

.next-btn:disabled {
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

  .next-btn {
    width: 100%;
    height: 44px;
    justify-content: center;
  }
}
</style>
