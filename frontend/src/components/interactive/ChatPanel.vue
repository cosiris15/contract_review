<template>
  <div class="chat-panel">
    <!-- 对话历史 -->
    <div class="chat-history" ref="chatHistoryRef">
      <!-- 空状态 -->
      <div v-if="!activeItem" class="empty-chat">
        <el-icon :size="48"><ChatDotRound /></el-icon>
        <span>请选择一个条目开始审阅</span>
      </div>

      <!-- 对话消息列表（第一条是后端初始化的上下文消息） -->
      <ChatMessage
        v-for="(msg, index) in messages"
        :key="index"
        :message="msg"
        :show-locate-btn="index === 0"
        @locate="$emit('locate')"
      />

      <!-- 流式输出时的打字指示器 -->
      <div v-if="streaming" class="streaming-indicator">
        <span class="typing-cursor"></span>
      </div>
    </div>

    <!-- 底部输入区 -->
    <div v-if="activeItem" class="input-area">
      <!-- 已完成提示 -->
      <div v-if="activeItem.chat_status === 'completed'" class="completed-banner">
        <el-icon><CircleCheck /></el-icon>
        <span>此条目已审阅完成</span>
      </div>

      <!-- 已跳过提示 -->
      <div v-else-if="activeItem.is_skipped || activeItem.chat_status === 'skipped'" class="skipped-banner">
        <el-icon><Close /></el-icon>
        <span>此风险点已跳过</span>
      </div>

      <template v-else>
        <!-- 阶段1: 分析讨论阶段（未生成修改建议时） -->
        <template v-if="!activeItem.has_modification">
          <!-- 输入框 -->
          <div class="input-container">
            <textarea
              ref="inputRef"
              v-model="inputText"
              class="chat-input"
              placeholder="与AI讨论这个风险点..."
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
          <div class="input-footer">
            <span class="phase-hint">讨论阶段 - 点击生成修改建议</span>
            <div class="action-buttons">
              <button
                class="skip-btn"
                @click="$emit('skip')"
                :disabled="loading"
              >
                跳过
              </button>
              <button
                class="confirm-btn"
                @click="$emit('confirm-risk')"
                :disabled="loading"
              >
                <el-icon v-if="confirmingRisk" class="is-loading"><Loading /></el-icon>
                <el-icon v-else><EditPen /></el-icon>
                修改建议
              </button>
            </div>
          </div>
        </template>

        <!-- 阶段2: 修改确认阶段（已生成修改建议） -->
        <template v-else>
          <!-- Diff 对比视图 -->
          <DiffView
            v-if="activeItem?.original_text && editableSuggestion"
            :original="activeItem.original_text"
            :modified="editableSuggestion"
          />

          <!-- 可编辑的修改建议 -->
          <div class="modification-editor">
            <div class="editor-label">
              <span>修改建议（可编辑）</span>
              <el-tag size="small" type="success">已生成</el-tag>
            </div>
            <textarea
              v-model="editableSuggestion"
              class="suggestion-textarea"
              rows="4"
              :disabled="loading"
            ></textarea>
          </div>
          <!-- 仍可继续对话 -->
          <div class="input-container secondary">
            <textarea
              ref="inputRef"
              v-model="inputText"
              class="chat-input"
              placeholder="如有问题，可继续讨论..."
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
          <div class="input-footer">
            <span class="phase-hint">修改阶段 - 确认建议后提交</span>
            <div class="action-buttons">
              <button
                class="skip-btn"
                @click="$emit('skip')"
                :disabled="loading"
              >
                跳过
              </button>
              <button
                class="submit-btn"
                @click="$emit('complete', editableSuggestion)"
                :disabled="loading"
              >
                <el-icon><Check /></el-icon>
                提交修改
              </button>
            </div>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onUnmounted } from 'vue'
import { ChatDotRound, CircleCheck, Close, Loading, Promotion, Check, EditPen } from '@element-plus/icons-vue'
import ChatMessage from './ChatMessage.vue'
import DiffView from './DiffView.vue'

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
  },
  confirmingRisk: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['select-item', 'send-message', 'complete', 'locate', 'confirm-risk', 'skip'])

const inputText = ref('')
const chatHistoryRef = ref(null)
const inputRef = ref(null)
const editableSuggestion = ref('')

// 定时器引用
let resizeTimer = null

// 监听 currentSuggestion 变化，同步到可编辑文本框
watch(() => props.currentSuggestion, (newVal) => {
  editableSuggestion.value = newVal
}, { immediate: true })

// 监听 activeItem 变化，重置可编辑文本框
watch(() => props.activeItem?.id, () => {
  if (props.activeItem?.suggested_text) {
    editableSuggestion.value = props.activeItem.suggested_text
  } else if (props.currentSuggestion) {
    editableSuggestion.value = props.currentSuggestion
  } else {
    editableSuggestion.value = ''
  }
})

// 防抖自动调整输入框高度
function autoResize() {
  if (resizeTimer) {
    clearTimeout(resizeTimer)
  }
  resizeTimer = setTimeout(() => {
    const el = inputRef.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }, 50)
}

// 滚动到底部
function scrollToBottom() {
  nextTick(() => {
    if (chatHistoryRef.value) {
      chatHistoryRef.value.scrollTop = chatHistoryRef.value.scrollHeight
    }
  })
}

// 合并 watch：监听消息变化和流式状态，自动滚动
watch(
  [() => props.messages.length, () => props.streaming],
  scrollToBottom,
  { flush: 'post' }
)

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

// 清理定时器
onUnmounted(() => {
  if (resizeTimer) {
    clearTimeout(resizeTimer)
  }
})
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
  max-height: 60vh;
  overflow-y: auto;
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

/* 已跳过横幅 */
.skipped-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px;
  background: #f5f5f5;
  border-radius: 8px;
  color: #999;
  font-size: 14px;
}

/* 输入框容器 */
.input-container {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 12px;
  background: #f5f5f5;
  border: 1px solid transparent;
  border-radius: 12px;
  transition: all 0.2s;
}

.input-container.secondary {
  margin-top: 12px;
  background: #fafafa;
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

/* 修改建议编辑器 */
.modification-editor {
  margin-bottom: 12px;
}

.editor-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
  color: #666;
}

.suggestion-textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid #d9d9d9;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  min-height: 80px;
  font-family: inherit;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.suggestion-textarea:focus {
  outline: none;
  border-color: #1890ff;
  box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.1);
}

.suggestion-textarea:disabled {
  background: #f5f5f5;
  opacity: 0.7;
}

/* 输入框底部 */
.input-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}

.phase-hint {
  font-size: 12px;
  color: #999;
}

.action-buttons {
  display: flex;
  gap: 8px;
}

/* 跳过按钮 */
.skip-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: #fff;
  color: #666;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.skip-btn:hover:not(:disabled) {
  border-color: #1890ff;
  color: #1890ff;
}

.skip-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 确认风险按钮 */
.confirm-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: #1890ff;
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.confirm-btn:hover:not(:disabled) {
  background: #40a9ff;
}

.confirm-btn:disabled {
  background: #d9d9d9;
  cursor: not-allowed;
}

/* 提交按钮 */
.submit-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: #52c41a;
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.submit-btn:hover:not(:disabled) {
  background: #73d13d;
}

.submit-btn:disabled {
  background: #d9d9d9;
  cursor: not-allowed;
}

/* 响应式 */
@media (max-width: 480px) {
  .chat-history {
    padding: 16px;
  }

  .action-buttons {
    flex-direction: column;
    width: 100%;
  }

  .skip-btn,
  .confirm-btn,
  .submit-btn {
    justify-content: center;
  }
}
</style>
