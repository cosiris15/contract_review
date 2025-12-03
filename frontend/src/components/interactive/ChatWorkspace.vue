<template>
  <div class="chat-workspace">
    <!-- 顶部：条款信息 -->
    <div class="workspace-header">
      <div class="clause-info">
        <div class="clause-section">
          <h4>
            <el-icon><Document /></el-icon>
            原始条款
          </h4>
          <div class="clause-text original">
            {{ item.original_text }}
          </div>
        </div>

        <div class="clause-arrow">
          <el-icon :size="24"><Right /></el-icon>
        </div>

        <div class="clause-section">
          <h4>
            <el-icon><Edit /></el-icon>
            当前建议
            <el-button
              type="primary"
              text
              size="small"
              @click="copySuggestion"
            >
              <el-icon><CopyDocument /></el-icon>
              复制
            </el-button>
          </h4>
          <div class="clause-text suggestion">
            {{ currentSuggestion }}
          </div>
        </div>
      </div>

      <!-- 风险说明 -->
      <div v-if="item.risk_description || item.modification_reason" class="risk-info">
        <el-icon><Warning /></el-icon>
        <span>{{ item.risk_description || item.modification_reason }}</span>
      </div>
    </div>

    <!-- 中部：对话历史 -->
    <div class="chat-history" ref="chatHistoryRef">
      <ChatMessage
        v-for="(msg, index) in messages"
        :key="index"
        :message="msg"
        @copy-suggestion="copySuggestion"
      />

      <!-- 正在加载 -->
      <div v-if="loading" class="loading-message">
        <el-icon class="is-loading" :size="20"><Loading /></el-icon>
        <span>AI 正在思考...</span>
      </div>
    </div>

    <!-- 底部：输入区域 -->
    <div class="chat-input-area">
      <div class="quick-actions">
        <el-button size="small" @click="sendQuickMessage('同意这个建议')">
          同意建议
        </el-button>
        <el-button size="small" @click="sendQuickMessage('请解释一下为什么这样修改')">
          请解释
        </el-button>
        <el-button size="small" @click="sendQuickMessage('这个建议太保守了，请给出更激进的方案')">
          更激进
        </el-button>
      </div>

      <div class="input-row">
        <el-input
          v-model="inputMessage"
          type="textarea"
          :rows="2"
          :autosize="{ minRows: 2, maxRows: 5 }"
          placeholder="输入您的意见或问题..."
          @keydown.enter.ctrl="sendMessage"
          @keydown.enter.meta="sendMessage"
          :disabled="loading || item.status === 'completed'"
        />
        <div class="input-actions">
          <el-button
            type="primary"
            :loading="loading"
            :disabled="!inputMessage.trim() || item.status === 'completed'"
            @click="sendMessage"
          >
            <el-icon><Promotion /></el-icon>
            发送
          </el-button>
          <el-button
            type="success"
            :disabled="loading || item.status === 'completed'"
            @click="completeItem"
          >
            <el-icon><Check /></el-icon>
            确认并继续
          </el-button>
        </div>
      </div>

      <div class="input-hint">
        <span>按 Ctrl+Enter 发送</span>
        <span v-if="item.status === 'completed'" class="completed-hint">
          <el-icon><CircleCheck /></el-icon>
          此条目已完成
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Document, Edit, Right, Warning, Loading, Promotion, Check, CircleCheck, CopyDocument
} from '@element-plus/icons-vue'
import ChatMessage from './ChatMessage.vue'

const props = defineProps({
  item: {
    type: Object,
    required: true
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
  }
})

const emit = defineEmits(['send-message', 'complete'])

const inputMessage = ref('')
const chatHistoryRef = ref(null)

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
watch(() => props.loading, scrollToBottom)

// 发送消息
function sendMessage() {
  if (!inputMessage.value.trim() || props.loading) return

  emit('send-message', inputMessage.value.trim())
  inputMessage.value = ''
}

// 发送快捷消息
function sendQuickMessage(message) {
  if (props.loading || props.item.status === 'completed') return
  emit('send-message', message)
}

// 确认完成
function completeItem() {
  emit('complete', props.currentSuggestion)
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
.chat-workspace {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-secondary);
}

/* 顶部条款信息 */
.workspace-header {
  padding: var(--spacing-4);
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border-light);
}

.clause-info {
  display: flex;
  gap: var(--spacing-4);
  align-items: stretch;
}

.clause-section {
  flex: 1;
  min-width: 0;
}

.clause-section h4 {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.clause-section h4 .el-button {
  margin-left: auto;
}

.clause-text {
  padding: var(--spacing-3);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
  max-height: 120px;
  overflow-y: auto;
}

.clause-text.original {
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border-light);
  color: var(--color-text-secondary);
}

.clause-text.suggestion {
  background: var(--color-success-bg);
  border: 1px solid #c2e7b0;
  color: var(--color-success-dark, #529b2e);
}

.clause-arrow {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  color: var(--color-text-tertiary);
}

.risk-info {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-2);
  margin-top: var(--spacing-3);
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-warning-bg);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--color-warning-dark, #a6711c);
}

.risk-info .el-icon {
  flex-shrink: 0;
  margin-top: 2px;
}

/* 聊天历史 */
.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-4);
}

.loading-message {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-3) var(--spacing-4);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

/* 输入区域 */
.chat-input-area {
  padding: var(--spacing-4);
  background: var(--color-bg-card);
  border-top: 1px solid var(--color-border-light);
}

.quick-actions {
  display: flex;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-3);
  flex-wrap: wrap;
}

.quick-actions .el-button {
  font-size: var(--font-size-xs);
}

.input-row {
  display: flex;
  gap: var(--spacing-3);
}

.input-row .el-input {
  flex: 1;
}

.input-actions {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}

.input-hint {
  display: flex;
  justify-content: space-between;
  margin-top: var(--spacing-2);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.completed-hint {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
  color: var(--color-success);
}
</style>
