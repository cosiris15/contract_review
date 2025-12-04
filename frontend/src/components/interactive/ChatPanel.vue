<template>
  <div class="chat-panel">
    <!-- Tab 切换条目 -->
    <div class="item-tabs" ref="tabsRef">
      <div
        v-for="(item, index) in items"
        :key="item.id"
        class="item-tab"
        :class="{
          active: item.id === activeItem?.id,
          completed: item.status === 'completed',
          'in-progress': item.status === 'in_progress'
        }"
        @click="$emit('select-item', item)"
      >
        <span class="tab-number">{{ index + 1 }}</span>
        <el-icon v-if="item.status === 'completed'" class="tab-icon" :size="12">
          <Check />
        </el-icon>
      </div>
    </div>

    <!-- 当前条目信息 -->
    <div v-if="activeItem" class="item-info">
      <!-- 原文 vs 建议 对比区 -->
      <div class="comparison-section" :class="{ collapsed: comparisonCollapsed }">
        <div class="comparison-header" @click="comparisonCollapsed = !comparisonCollapsed">
          <span>
            <el-icon><Right /></el-icon>
            条款对比
          </span>
          <el-icon :class="{ rotated: !comparisonCollapsed }">
            <ArrowDown />
          </el-icon>
        </div>

        <div v-show="!comparisonCollapsed" class="comparison-content">
          <div class="comparison-item original">
            <div class="comparison-label">
              <el-icon><Document /></el-icon>
              原文
            </div>
            <div class="comparison-text">{{ activeItem.original_text }}</div>
          </div>

          <div class="comparison-arrow">
            <el-icon><Right /></el-icon>
          </div>

          <div class="comparison-item suggestion">
            <div class="comparison-label">
              <el-icon><Edit /></el-icon>
              建议
              <el-button
                type="primary"
                text
                size="small"
                @click.stop="copySuggestion"
              >
                <el-icon><CopyDocument /></el-icon>
              </el-button>
            </div>
            <div class="comparison-text">{{ currentSuggestion }}</div>
          </div>
        </div>

        <!-- 风险说明 -->
        <div v-if="activeItem.risk_description || activeItem.modification_reason" class="risk-hint">
          <el-icon><Warning /></el-icon>
          <span>{{ activeItem.risk_description || activeItem.modification_reason }}</span>
        </div>
      </div>
    </div>

    <!-- 对话历史 -->
    <div class="chat-history" ref="chatHistoryRef">
      <div v-if="messages.length === 0 && !loading" class="empty-chat">
        <el-icon :size="32"><ChatDotRound /></el-icon>
        <span>开始与 AI 讨论这个条款</span>
      </div>

      <ChatMessage
        v-for="(msg, index) in messages"
        :key="index"
        :message="msg"
        compact
        @copy-suggestion="copySuggestion"
      />

      <!-- 正在加载（仅在 loading 且非 streaming 时显示，因为 streaming 时会显示实时内容） -->
      <div v-if="loading && !streaming && messages.length === 0" class="loading-message">
        <el-icon class="is-loading" :size="16"><Loading /></el-icon>
        <span>AI 思考中...</span>
      </div>

      <!-- 流式输出中的打字光标 -->
      <div v-if="streaming" class="streaming-indicator">
        <span class="typing-cursor"></span>
      </div>
    </div>

    <!-- 输入区域 -->
    <div v-if="activeItem" class="input-area">
      <!-- 快捷按钮 -->
      <div class="quick-actions">
        <el-button size="small" @click="sendQuickMessage('同意这个建议')">
          <el-icon><Check /></el-icon>
          同意
        </el-button>
        <el-button size="small" @click="sendQuickMessage('请解释一下为什么这样修改')">
          请解释
        </el-button>
        <el-button size="small" @click="sendQuickMessage('这个建议太保守了')">
          更激进
        </el-button>
      </div>

      <!-- 输入框 -->
      <div class="input-row">
        <el-input
          v-model="inputText"
          type="textarea"
          :rows="2"
          :autosize="{ minRows: 2, maxRows: 4 }"
          placeholder="输入您的意见..."
          @keydown.enter.ctrl="send"
          @keydown.enter.meta="send"
          :disabled="loading || activeItem.status === 'completed'"
        />
      </div>

      <!-- 操作按钮 -->
      <div class="action-row">
        <el-button @click="$emit('locate')" :disabled="!activeItem">
          <el-icon><Location /></el-icon>
          定位原文
        </el-button>

        <div class="action-right">
          <el-button
            type="primary"
            :loading="loading"
            :disabled="!inputText.trim() || activeItem.status === 'completed'"
            @click="send"
          >
            <el-icon><Promotion /></el-icon>
            发送
          </el-button>

          <el-button
            type="success"
            :disabled="loading || activeItem.status === 'completed'"
            @click="$emit('complete', currentSuggestion)"
          >
            <el-icon><Check /></el-icon>
            确认
          </el-button>
        </div>
      </div>

      <div v-if="activeItem.status === 'completed'" class="completed-hint">
        <el-icon><CircleCheck /></el-icon>
        此条目已完成
      </div>
    </div>

    <!-- 无选中状态 -->
    <div v-else class="empty-state">
      <el-empty description="请从上方选择条目开始审阅" />
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Check, Right, ArrowDown, Document, Edit, CopyDocument, Warning,
  ChatDotRound, Loading, Location, Promotion, CircleCheck
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
const comparisonCollapsed = ref(false)
const chatHistoryRef = ref(null)
const tabsRef = ref(null)

// 滚动聊天历史到底部
function scrollChatToBottom() {
  nextTick(() => {
    if (chatHistoryRef.value) {
      chatHistoryRef.value.scrollTop = chatHistoryRef.value.scrollHeight
    }
  })
}

// 监听消息变化，自动滚动
watch(() => props.messages.length, scrollChatToBottom)
watch(() => props.loading, scrollChatToBottom)

// 当切换条目时，滚动 Tab 到可见区域
watch(() => props.activeItem?.id, () => {
  nextTick(() => {
    if (tabsRef.value && props.activeItem) {
      const activeTab = tabsRef.value.querySelector('.item-tab.active')
      if (activeTab) {
        activeTab.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
      }
    }
  })
})

// 发送消息
function send() {
  if (!inputText.value.trim() || props.loading) return
  emit('send-message', inputText.value.trim())
  inputText.value = ''
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
    ElMessage.success('已复制')
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
  background: var(--color-bg-secondary);
}

/* Tab 切换 */
.item-tabs {
  display: flex;
  gap: var(--spacing-1);
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border-light);
  overflow-x: auto;
  flex-shrink: 0;
}

.item-tabs::-webkit-scrollbar {
  height: 4px;
}

.item-tabs::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 2px;
}

.item-tab {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}

.item-tab:hover {
  background: var(--color-bg-hover);
}

.item-tab.active {
  background: var(--color-primary);
  color: white;
}

.item-tab.completed {
  background: var(--color-success-bg);
  color: var(--color-success);
}

.item-tab.completed.active {
  background: var(--color-success);
  color: white;
}

.item-tab.in-progress:not(.active) {
  border: 2px solid var(--color-primary);
}

.tab-number {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
}

.tab-icon {
  position: absolute;
  top: -2px;
  right: -2px;
  background: var(--color-success);
  color: white;
  border-radius: 50%;
  padding: 1px;
}

/* 条目信息 */
.item-info {
  flex-shrink: 0;
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border-light);
}

.comparison-section {
  padding: var(--spacing-3);
}

.comparison-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-2);
  cursor: pointer;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  border-radius: var(--radius-md);
  transition: background 0.2s;
}

.comparison-header:hover {
  background: var(--color-bg-hover);
}

.comparison-header span {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
}

.comparison-header .el-icon.rotated {
  transform: rotate(180deg);
}

.comparison-content {
  display: flex;
  gap: var(--spacing-2);
  margin-top: var(--spacing-2);
  padding: var(--spacing-2);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.comparison-item {
  flex: 1;
  min-width: 0;
}

.comparison-label {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
  margin-bottom: var(--spacing-1);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.comparison-text {
  padding: var(--spacing-2);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
  border-radius: var(--radius-sm);
  max-height: 80px;
  overflow-y: auto;
}

.comparison-item.original .comparison-text {
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
}

.comparison-item.suggestion .comparison-text {
  background: var(--color-success-bg);
  color: var(--color-success-dark, #529b2e);
}

.comparison-arrow {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  color: var(--color-text-tertiary);
}

.risk-hint {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-2);
  margin-top: var(--spacing-2);
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-warning-bg);
  border-radius: var(--radius-md);
  font-size: var(--font-size-xs);
  color: var(--color-warning-dark, #a6711c);
}

.risk-hint .el-icon {
  flex-shrink: 0;
  margin-top: 2px;
}

/* 对话历史 */
.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-3);
}

.empty-chat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-2);
  height: 100%;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

.loading-message {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-2) var(--spacing-3);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

.streaming-indicator {
  padding: 0 var(--spacing-3);
  height: 20px;
}

.typing-cursor {
  display: inline-block;
  width: 8px;
  height: 16px;
  background: var(--color-primary);
  animation: blink 1s steps(2, start) infinite;
  border-radius: 1px;
}

@keyframes blink {
  to { visibility: hidden; }
}

/* 输入区域 */
.input-area {
  flex-shrink: 0;
  padding: var(--spacing-3);
  background: var(--color-bg-card);
  border-top: 1px solid var(--color-border-light);
}

.quick-actions {
  display: flex;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-2);
  flex-wrap: wrap;
}

.quick-actions .el-button {
  font-size: var(--font-size-xs);
}

.input-row {
  margin-bottom: var(--spacing-2);
}

.action-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.action-right {
  display: flex;
  gap: var(--spacing-2);
}

.completed-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-1);
  margin-top: var(--spacing-2);
  padding: var(--spacing-2);
  background: var(--color-success-bg);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--color-success);
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
