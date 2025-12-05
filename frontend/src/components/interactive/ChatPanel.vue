<template>
  <div class="chat-panel">
    <!-- 条目导航列表（可折叠） -->
    <div class="item-nav-section" :class="{ collapsed: navCollapsed }">
      <div class="nav-header" @click="navCollapsed = !navCollapsed">
        <div class="nav-title">
          <el-icon><List /></el-icon>
          <span>条目列表</span>
          <el-tag size="small" type="success">{{ completedItemsCount }}/{{ items.length }}</el-tag>
        </div>
        <el-icon class="collapse-icon" :class="{ rotated: !navCollapsed }">
          <ArrowDown />
        </el-icon>
      </div>

      <transition name="slide">
        <div v-show="!navCollapsed" class="nav-list">
          <!-- 批量操作栏 -->
          <div v-if="hasPendingLowPriority" class="batch-actions">
            <button
              class="batch-btn"
              @click="$emit('batch-accept', 'should')"
              :disabled="loading"
            >
              <el-icon><Check /></el-icon>
              采纳全部「建议」
            </button>
            <button
              class="batch-btn"
              @click="$emit('batch-accept', 'may')"
              :disabled="loading"
            >
              <el-icon><Check /></el-icon>
              采纳全部「可选」
            </button>
          </div>

          <!-- 条目列表 -->
          <div
            v-for="item in items"
            :key="item.id"
            class="nav-item"
            :class="{
              active: activeItem?.id === item.id,
              completed: item.status === 'completed' || item.chat_status === 'completed',
              skipped: item.is_skipped || item.chat_status === 'skipped'
            }"
          >
            <div class="nav-item-main" @click="$emit('select-item', item)">
              <div class="nav-item-status">
                <el-icon v-if="item.status === 'completed' || item.chat_status === 'completed'" color="#52c41a">
                  <CircleCheck />
                </el-icon>
                <el-icon v-else-if="item.is_skipped || item.chat_status === 'skipped'" color="#999">
                  <Remove />
                </el-icon>
                <el-icon v-else-if="item.status === 'in_progress'" color="#1890ff">
                  <Loading class="is-loading" />
                </el-icon>
                <el-icon v-else color="#d9d9d9">
                  <CirclePlus />
                </el-icon>
              </div>
              <div class="nav-item-content">
                <div class="nav-item-header">
                  <el-tag :type="getPriorityType(item.priority)" size="small">
                    {{ getPriorityLabel(item.priority) }}
                  </el-tag>
                </div>
                <p class="nav-item-text">{{ truncateText(item.original_text || item.description, 40) }}</p>
              </div>
            </div>
            <!-- 快速采纳按钮（仅对未处理且有建议的条目显示） -->
            <button
              v-if="canQuickAccept(item)"
              class="quick-accept-btn"
              @click.stop="$emit('quick-accept', item)"
              :title="'直接采纳: ' + truncateText(item.suggested_text, 30)"
            >
              <el-icon><Check /></el-icon>
            </button>
          </div>
        </div>
      </transition>
    </div>

    <!-- 对话历史 -->
    <div class="chat-history" ref="chatHistoryRef" @click="collapseNav">
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
    <div v-if="activeItem" class="input-area" @click="collapseNav">
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
            <span class="phase-hint">讨论完成后，点击右侧按钮生成修改方案</span>
            <div class="action-buttons">
              <button
                class="skip-btn"
                @click="$emit('skip')"
                :disabled="loading || confirmingRisk"
              >
                跳过
              </button>
              <button
                class="confirm-btn"
                @click="$emit('confirm-risk')"
                :disabled="loading || confirmingRisk"
              >
                <el-icon v-if="confirmingRisk" class="is-loading"><Loading /></el-icon>
                <el-icon v-else><EditPen /></el-icon>
                {{ confirmingRisk ? '生成中...' : '修改' }}
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
import { ref, watch, nextTick, onUnmounted, computed } from 'vue'
import { ChatDotRound, CircleCheck, CirclePlus, Close, Loading, Promotion, Check, EditPen, List, ArrowDown, Remove } from '@element-plus/icons-vue'
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

const emit = defineEmits(['select-item', 'send-message', 'complete', 'locate', 'confirm-risk', 'skip', 'quick-accept', 'batch-accept'])

// 导航折叠状态
const navCollapsed = ref(false)

// 点击聊天区域时收起条目列表
function collapseNav() {
  if (!navCollapsed.value) {
    navCollapsed.value = true
  }
}

// 已完成条目数
const completedItemsCount = computed(() => {
  return props.items.filter(item =>
    item.status === 'completed' || item.chat_status === 'completed' ||
    item.is_skipped || item.chat_status === 'skipped'
  ).length
})

// 是否有未处理的低优先级条目（用于显示批量操作按钮）
const hasPendingLowPriority = computed(() => {
  return props.items.some(item =>
    (item.priority === 'should' || item.priority === 'may') &&
    item.status !== 'completed' && item.chat_status !== 'completed' &&
    !item.is_skipped && item.chat_status !== 'skipped' &&
    item.suggested_text
  )
})

// 判断条目是否可以快速采纳
function canQuickAccept(item) {
  return (
    item.suggested_text &&
    item.status !== 'completed' && item.chat_status !== 'completed' &&
    !item.is_skipped && item.chat_status !== 'skipped'
  )
}

// 获取优先级标签类型
function getPriorityType(priority) {
  const types = { must: 'danger', should: 'warning', may: 'info' }
  return types[priority] || 'info'
}

// 获取优先级标签文本
function getPriorityLabel(priority) {
  const labels = { must: '必须', should: '建议', may: '可选' }
  return labels[priority] || priority
}

// 截断文本
function truncateText(text, maxLength) {
  if (!text) return ''
  return text.length > maxLength ? text.slice(0, maxLength) + '...' : text
}

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

/* 条目导航区域 */
.item-nav-section {
  flex-shrink: 0;
  background: #fff;
  border-bottom: 1px solid #e5e5e5;
}

.nav-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.nav-header:hover {
  background: #fafafa;
}

.nav-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
  color: #333;
}

.collapse-icon {
  color: #999;
  transition: transform 0.3s;
}

.collapse-icon.rotated {
  transform: rotate(180deg);
}

.nav-list {
  max-height: 240px;
  overflow-y: auto;
  padding: 0 12px 12px;
}

/* 批量操作栏 */
.batch-actions {
  display: flex;
  gap: 8px;
  padding: 8px 4px;
  margin-bottom: 8px;
  border-bottom: 1px dashed #e5e5e5;
}

.batch-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: #fff;
  color: #666;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.batch-btn:hover:not(:disabled) {
  border-color: #52c41a;
  color: #52c41a;
  background: #f6ffed;
}

.batch-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 导航条目 */
.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  padding-right: 12px;
  margin-bottom: 4px;
  border-radius: 8px;
  transition: all 0.2s;
}

.nav-item:hover {
  background: #f5f5f5;
}

.nav-item.active {
  background: #e6f7ff;
}

.nav-item.completed {
  opacity: 0.6;
}

.nav-item.skipped {
  opacity: 0.5;
}

.nav-item.completed .nav-item-text {
  text-decoration: line-through;
  color: #999;
}

.nav-item-main {
  flex: 1;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  cursor: pointer;
  min-width: 0;
}

.nav-item-status {
  flex-shrink: 0;
  padding-top: 2px;
}

.nav-item-content {
  flex: 1;
  min-width: 0;
}

.nav-item-header {
  margin-bottom: 4px;
}

.nav-item-text {
  margin: 0;
  font-size: 12px;
  color: #666;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* 快速采纳按钮 - 默认隐藏不占用空间，悬停时显示 */
.quick-accept-btn {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #52c41a;
  border-radius: 6px;
  background: #fff;
  color: #52c41a;
  cursor: pointer;
  opacity: 0;
  visibility: hidden;
  transition: all 0.2s;
}

.nav-item:hover .quick-accept-btn {
  opacity: 1;
  visibility: visible;
}

.quick-accept-btn:hover {
  background: #52c41a;
  color: #fff;
}

/* 过渡动画 */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.slide-enter-from,
.slide-leave-to {
  max-height: 0;
  opacity: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.slide-enter-to,
.slide-leave-from {
  max-height: 300px;
  opacity: 1;
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
