<template>
  <div class="interactive-review-view">
    <!-- 简化顶栏 -->
    <div class="review-header">
      <div class="header-left">
        <button class="back-btn" @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </button>
        <span class="document-name">{{ task?.document_filename || '合同审阅' }}</span>
      </div>

      <!-- 条目切换器 -->
      <div class="item-switcher">
        <button
          class="switch-btn"
          :disabled="!canGoPrev"
          @click="goPrevItem"
        >
          <el-icon><ArrowLeft /></el-icon>
        </button>
        <div class="item-indicator">
          <span class="current-index">{{ currentItemIndex + 1 }}</span>
          <span class="separator">/</span>
          <span class="total-count">{{ items.length }}</span>
          <!-- 增量加载提示 -->
          <span v-if="isLoadingMore" class="loading-more-hint">
            <el-icon class="is-loading"><Loading /></el-icon>
          </span>
        </div>
        <button
          class="switch-btn"
          :disabled="!canGoNext"
          @click="goNextItem"
        >
          <el-icon><ArrowRight /></el-icon>
        </button>
      </div>

      <div class="header-right">
        <div class="progress-info">
          <span class="progress-text">{{ completedCount }} 已完成</span>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: completionPercentage + '%' }"></div>
          </div>
        </div>
        <el-dropdown trigger="click" @command="handleExport">
          <button class="export-btn" :disabled="completedCount === 0">
            <el-icon><Download /></el-icon>
            导出
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="word">
                <el-icon><Document /></el-icon>
                导出 Word
              </el-dropdown-item>
              <el-dropdown-item command="json">
                <el-icon><Files /></el-icon>
                导出 JSON
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="review-content" v-loading="loading">
      <!-- 左侧：文档全文 -->
      <div class="content-left">
        <DocumentViewer
          ref="documentViewerRef"
          :document-name="task?.document_filename"
          :paragraphs="documentParagraphs"
          :highlight-text="activeItem?.original_text"
          :loading="documentLoading"
        />
      </div>

      <!-- 右侧：聊天面板 -->
      <div class="content-right">
        <ChatPanel
          :items="items"
          :active-item="activeItem"
          :messages="activeMessages"
          :current-suggestion="currentSuggestion"
          :loading="chatLoading"
          :streaming="isStreaming"
          :confirming-risk="confirmingRisk"
          @select-item="selectItem"
          @send-message="sendMessage"
          @complete="completeCurrentItem"
          @confirm-risk="confirmRisk"
          @skip="skipItem"
          @locate="scrollToHighlight"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, ArrowDown, Download, Document, Files, Loading } from '@element-plus/icons-vue'
import DocumentViewer from '@/components/interactive/DocumentViewer.vue'
import ChatPanel from '@/components/interactive/ChatPanel.vue'
import interactiveApi from '@/api/interactive'
import api from '@/api'

const route = useRoute()
const router = useRouter()

const taskId = computed(() => route.params.taskId)

// 状态
const loading = ref(false)
const documentLoading = ref(false)
const chatLoading = ref(false)
const confirmingRisk = ref(false)
const task = ref(null)
const items = ref([])
const activeItemId = ref(null)  // 用于 UI 选中状态 (item.id)
const activeItemApiId = ref(null)  // 用于 API 调用 (item.item_id)
const activeMessages = ref([])
const currentSuggestion = ref('')
const documentParagraphs = ref([])
const documentViewerRef = ref(null)

// 计算属性
const activeItem = computed(() => {
  return items.value.find(item => item.id === activeItemId.value)
})

const completedCount = computed(() => {
  return items.value.filter(item =>
    item.chat_status === 'completed' || item.chat_status === 'skipped' ||
    item.status === 'completed' || item.status === 'skipped'
  ).length
})

const completionPercentage = computed(() => {
  if (items.value.length === 0) return 0
  return Math.round((completedCount.value / items.value.length) * 100)
})

// 当前条目索引
const currentItemIndex = computed(() => {
  if (!activeItemId.value) return -1
  return items.value.findIndex(item => item.id === activeItemId.value)
})

// 是否可以切换到上一个/下一个
const canGoPrev = computed(() => currentItemIndex.value > 0)
const canGoNext = computed(() => currentItemIndex.value < items.value.length - 1)

// 切换到上一个条目
function goPrevItem() {
  if (!canGoPrev.value) return
  const prevItem = items.value[currentItemIndex.value - 1]
  if (prevItem) selectItem(prevItem)
}

// 切换到下一个条目
function goNextItem() {
  if (!canGoNext.value) return
  const nextItem = items.value[currentItemIndex.value + 1]
  if (nextItem) selectItem(nextItem)
}

// 判断当前是否有流式输出进行中
const isStreaming = computed(() => {
  return activeMessages.value.some(msg => msg.isStreaming)
})

// 增量加载状态
const isLoadingMore = ref(false)
let incrementalPollInterval = null

// 加载数据
onMounted(async () => {
  await loadData()

  // 如果任务状态是 partial_ready，启动增量轮询获取新条目
  if (task.value?.status === 'partial_ready') {
    startIncrementalPolling()
  }
})

// 组件卸载时清理轮询
onUnmounted(() => {
  stopIncrementalPolling()
})

async function loadData() {
  loading.value = true
  try {
    // 并行加载任务信息、交互条目和文档内容
    const [taskResponse, itemsResponse] = await Promise.all([
      api.getTask(taskId.value),
      interactiveApi.getInteractiveItems(taskId.value),
    ])

    task.value = taskResponse.data
    // itemsResponse.data 是 { task_id, items, summary } 结构
    items.value = itemsResponse.data?.items || []

    // 异步加载文档内容（不阻塞主流程）
    loadDocumentText()

    // 自动选择第一个未完成的条目
    const firstPending = items.value.find(item => item.status !== 'completed')
    if (firstPending) {
      await selectItem(firstPending)
    } else if (items.value.length > 0) {
      await selectItem(items.value[0])
    }
  } catch (error) {
    console.error('加载数据失败:', error)
    ElMessage.error('加载数据失败: ' + (error.message || '请重试'))
  } finally {
    loading.value = false
  }
}

// 加载文档全文
async function loadDocumentText() {
  documentLoading.value = true
  try {
    const response = await interactiveApi.getDocumentText(taskId.value)
    documentParagraphs.value = response.data.paragraphs || []
  } catch (error) {
    console.error('加载文档内容失败:', error)
    // 不显示错误消息，因为这不是关键功能
  } finally {
    documentLoading.value = false
  }
}

// 增量轮询：当任务处于 partial_ready 状态时，持续获取新条目
function startIncrementalPolling() {
  isLoadingMore.value = true

  incrementalPollInterval = setInterval(async () => {
    try {
      // 获取最新的条目列表
      const itemsResponse = await interactiveApi.getInteractiveItems(taskId.value)
      const newItems = itemsResponse.data?.items || []

      // 检查是否有新条目（保持当前选中状态）
      if (newItems.length > items.value.length) {
        const currentActiveId = activeItemId.value
        items.value = newItems

        // 恢复选中状态
        if (currentActiveId) {
          const stillExists = newItems.find(i => i.id === currentActiveId)
          if (!stillExists && newItems.length > 0) {
            // 如果当前选中的条目不存在了，选择第一个
            await selectItem(newItems[0])
          }
        }
      }

      // 检查任务是否已完成
      const taskResponse = await api.getTaskStatus(taskId.value)
      if (taskResponse.data.status === 'completed') {
        stopIncrementalPolling()
        // 更新本地任务状态
        task.value.status = 'completed'
      }
    } catch (error) {
      console.error('增量轮询失败:', error)
    }
  }, 3000)  // 每3秒检查一次

  // 2分钟超时（防止无限轮询）
  setTimeout(() => {
    stopIncrementalPolling()
  }, 2 * 60 * 1000)
}

// 停止增量轮询
function stopIncrementalPolling() {
  if (incrementalPollInterval) {
    clearInterval(incrementalPollInterval)
    incrementalPollInterval = null
  }
  isLoadingMore.value = false
}

// 选择条目
async function selectItem(item) {
  if (activeItemId.value === item.id) return

  activeItemId.value = item.id
  activeItemApiId.value = item.item_id  // 保存 API 调用需要的 item_id
  activeMessages.value = []
  currentSuggestion.value = item.current_suggestion || item.suggested_text || ''

  // 加载条目详情（含对话历史）
  try {
    const response = await interactiveApi.getItemDetail(taskId.value, item.item_id)
    const detail = response.data

    activeMessages.value = detail.messages || []
    currentSuggestion.value = detail.current_suggestion || item.suggested_text || ''

    // 更新本地条目状态
    const localItem = items.value.find(i => i.id === item.id)
    if (localItem) {
      localItem.status = detail.status
      localItem.message_count = detail.messages?.length || 0
    }
  } catch (error) {
    console.error('加载条目详情失败:', error)
    // 如果加载失败，使用条目列表中的信息
    activeMessages.value = item.messages || []
  }
}

// 滚动到高亮文本
function scrollToHighlight() {
  if (documentViewerRef.value && activeItem.value?.original_text) {
    documentViewerRef.value.scrollToText(activeItem.value.original_text)
  }
}

// 发送消息（流式输出）
async function sendMessage(message) {
  if (!activeItemApiId.value || chatLoading.value) return

  // 添加用户消息到界面
  activeMessages.value.push({
    role: 'user',
    content: message,
    timestamp: new Date().toISOString()
  })

  // 添加一个空的 AI 回复占位，用于流式填充
  const aiMessageIndex = activeMessages.value.length
  activeMessages.value.push({
    role: 'assistant',
    content: '',
    timestamp: new Date().toISOString(),
    suggestion_snapshot: null,
    isStreaming: true // 标记为正在流式输出
  })

  chatLoading.value = true
  let streamedContent = ''

  try {
    await interactiveApi.sendChatMessageStream(
      taskId.value,
      activeItemApiId.value,
      message,
      'deepseek',
      {
        onChunk: (chunk) => {
          // 实时更新 AI 回复内容
          streamedContent += chunk
          activeMessages.value[aiMessageIndex].content = streamedContent
        },
        onSuggestion: (suggestion) => {
          // 更新当前建议
          currentSuggestion.value = suggestion
          activeMessages.value[aiMessageIndex].suggestion_snapshot = suggestion
        },
        onDone: (fullContent) => {
          // 流式完成，移除 streaming 标记
          activeMessages.value[aiMessageIndex].isStreaming = false

          // 更新本地条目状态
          const localItem = items.value.find(i => i.id === activeItemId.value)
          if (localItem) {
            localItem.status = 'in_progress'
            localItem.current_suggestion = currentSuggestion.value
            localItem.message_count = activeMessages.value.length
          }
        },
        onError: (error) => {
          console.error('流式对话失败:', error)
          // 更新 AI 消息显示错误
          activeMessages.value[aiMessageIndex].content = '抱歉，对话出错了：' + error.message
          activeMessages.value[aiMessageIndex].isStreaming = false
          activeMessages.value[aiMessageIndex].isError = true
        }
      }
    )
  } catch (error) {
    console.error('发送消息失败:', error)
    ElMessage.error('发送消息失败: ' + (error.message || '请重试'))
    // 如果 AI 回复是空的，移除它
    if (!streamedContent) {
      activeMessages.value.pop() // 移除空的 AI 回复
      activeMessages.value.pop() // 移除用户消息
    }
  } finally {
    chatLoading.value = false
  }
}

// 完成当前条目
async function completeCurrentItem(finalSuggestion) {
  if (!activeItemApiId.value) return

  try {
    await interactiveApi.completeItem(taskId.value, activeItemApiId.value, finalSuggestion)

    // 更新本地状态
    const localItem = items.value.find(i => i.id === activeItemId.value)
    if (localItem) {
      localItem.chat_status = 'completed'
      localItem.status = 'completed'
      localItem.current_suggestion = finalSuggestion
    }

    ElMessage.success('条目已确认')

    // 自动跳转到下一个未完成的条目
    goToNextPendingItem()
  } catch (error) {
    console.error('完成条目失败:', error)
    ElMessage.error('完成条目失败: ' + (error.message || '请重试'))
  }
}

// 确认风险并生成修改建议
async function confirmRisk() {
  if (!activeItemApiId.value || confirmingRisk.value) return

  confirmingRisk.value = true

  try {
    // 构建讨论摘要（从对话历史中提取）
    const discussionSummary = buildDiscussionSummary(activeMessages.value)
    const userDecision = '用户确认此风险需要处理'

    // 调用单条修改建议生成 API
    const response = await interactiveApi.generateSingleModification(
      taskId.value,
      activeItemApiId.value,
      discussionSummary,
      userDecision
    )

    // 更新本地状态
    const localItem = items.value.find(i => i.id === activeItemId.value)
    if (localItem) {
      localItem.has_modification = true
      localItem.modification_id = response.data.id
      localItem.suggested_text = response.data.suggested_text
      localItem.modification_reason = response.data.modification_reason
    }
    currentSuggestion.value = response.data.suggested_text

    ElMessage.success('已生成修改建议')
  } catch (error) {
    console.error('生成修改建议失败:', error)
    ElMessage.error('生成修改建议失败: ' + (error.message || '请重试'))
  } finally {
    confirmingRisk.value = false
  }
}

// 跳过当前条目
async function skipItem() {
  if (!activeItemApiId.value) return

  try {
    await interactiveApi.skipItem(taskId.value, activeItemApiId.value)

    // 更新本地状态
    const localItem = items.value.find(i => i.id === activeItemId.value)
    if (localItem) {
      localItem.is_skipped = true
      localItem.chat_status = 'skipped'
      localItem.status = 'skipped'
    }

    ElMessage.info('已跳过此条目')

    // 自动跳转到下一个未完成的条目
    goToNextPendingItem()
  } catch (error) {
    console.error('跳过条目失败:', error)
    ElMessage.error('跳过条目失败: ' + (error.message || '请重试'))
  }
}

// 构建讨论摘要
function buildDiscussionSummary(messages) {
  if (!messages || messages.length === 0) return ''

  return messages.map(msg =>
    `${msg.role === 'user' ? '用户' : 'AI'}: ${msg.content}`
  ).join('\n\n')
}

// 跳转到下一个未完成条目
async function goToNextPendingItem() {
  const nextPending = items.value.find(item =>
    item.chat_status !== 'completed' && item.chat_status !== 'skipped' &&
    item.status !== 'completed' && item.status !== 'skipped'
  )

  if (nextPending) {
    await selectItem(nextPending)
  } else {
    // 全部完成
    ElMessageBox.confirm(
      '恭喜！所有条目已审阅完成。是否导出结果？',
      '审阅完成',
      {
        confirmButtonText: '导出 Word',
        cancelButtonText: '稍后导出',
        type: 'success'
      }
    ).then(() => {
      handleExport('word')
    }).catch(() => {
      // 用户取消
    })
  }
}

// 导出
async function handleExport(format) {
  if (format === 'word') {
    // 调用现有的导出 Word 功能
    try {
      ElMessage.info('正在生成修订版 Word 文档...')
      const response = await api.exportRedline(taskId.value)
      // 下载文件
      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${task.value?.document_filename || 'result'}_修订版.docx`
      link.click()
      window.URL.revokeObjectURL(url)
      ElMessage.success('导出成功')
    } catch (error) {
      console.error('导出失败:', error)
      ElMessage.error('导出失败: ' + (error.message || '请重试'))
    }
  } else if (format === 'json') {
    // 导出 JSON
    const exportData = {
      task_id: taskId.value,
      document_name: task.value?.document_filename,
      exported_at: new Date().toISOString(),
      items: items.value.map(item => ({
        id: item.id,
        type: item.item_type,
        priority: item.priority,
        original_text: item.original_text,
        final_suggestion: item.current_suggestion,
        status: item.status,
        risk_description: item.risk_description || item.modification_reason
      }))
    }

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${task.value?.document_filename || 'result'}_审阅结果.json`
    link.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  }
}

// 返回
function goBack() {
  if (completedCount.value < items.value.length) {
    ElMessageBox.confirm(
      '还有未完成的条目，确定要离开吗？',
      '确认离开',
      {
        confirmButtonText: '离开',
        cancelButtonText: '继续审阅',
        type: 'warning'
      }
    ).then(() => {
      router.push('/')
    }).catch(() => {
      // 用户取消
    })
  } else {
    router.push('/')
  }
}
</script>

<style scoped>
.interactive-review-view {
  height: calc(100vh - var(--header-height, 0px));
  display: flex;
  flex-direction: column;
  background: #f5f5f5;
}

/* 简化顶栏 */
.review-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: #fff;
  border-bottom: 1px solid #e5e5e5;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #666;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.back-btn:hover {
  background: #f5f5f5;
  color: #333;
}

.document-name {
  font-size: 15px;
  font-weight: 600;
  color: #333;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 条目切换器 */
.item-switcher {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px;
  background: #f5f5f5;
  border-radius: 8px;
}

.switch-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #666;
  cursor: pointer;
  transition: all 0.2s;
}

.switch-btn:hover:not(:disabled) {
  background: #fff;
  color: #1890ff;
}

.switch-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.item-indicator {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 0 8px;
  font-size: 14px;
  font-weight: 500;
}

.current-index {
  color: #1890ff;
}

.separator {
  color: #999;
}

.total-count {
  color: #666;
}

.loading-more-hint {
  margin-left: 6px;
  color: #1890ff;
  font-size: 12px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.progress-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-text {
  font-size: 13px;
  color: #666;
  white-space: nowrap;
}

.progress-bar {
  width: 60px;
  height: 4px;
  background: #e5e5e5;
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #52c41a;
  border-radius: 2px;
  transition: width 0.3s;
}

.export-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: #fff;
  color: #333;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.export-btn:hover:not(:disabled) {
  border-color: #1890ff;
  color: #1890ff;
}

.export-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 主内容区 - 左右布局 */
.review-content {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* 左侧：文档区域 60% */
.content-left {
  flex: 6;
  overflow: hidden;
  background: #fff;
}

/* 右侧：聊天面板 40% */
.content-right {
  flex: 4;
  min-width: 400px;
  max-width: 560px;
  overflow: hidden;
  border-left: 1px solid #e5e5e5;
}

/* 响应式 */
@media (max-width: 1200px) {
  .content-right {
    min-width: 360px;
    flex: 5;
  }

  .content-left {
    flex: 5;
  }

  .document-name {
    max-width: 150px;
  }
}

@media (max-width: 1024px) {
  .progress-info {
    display: none;
  }

  .content-right {
    min-width: 320px;
  }
}

@media (max-width: 768px) {
  .review-header {
    padding: 10px 16px;
  }

  .document-name {
    display: none;
  }

  .review-content {
    flex-direction: column;
  }

  .content-left {
    flex: none;
    height: 35%;
    min-height: 180px;
  }

  .content-right {
    flex: 1;
    min-width: 100%;
    max-width: 100%;
    border-left: none;
    border-top: 1px solid #e5e5e5;
  }
}
</style>
