<template>
  <div class="interactive-review-view">
    <!-- 顶栏 -->
    <div class="review-header">
      <div class="header-left">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <el-divider direction="vertical" />
        <span class="document-name">{{ task?.document_filename || '深度交互审阅' }}</span>
        <el-tag type="success" size="small">交互模式</el-tag>
      </div>

      <div class="header-center">
        <el-progress
          :percentage="completionPercentage"
          :stroke-width="8"
          style="width: 200px"
        />
        <span class="progress-text">{{ completedCount }}/{{ items.length }} 已完成</span>
      </div>

      <div class="header-right">
        <el-dropdown trigger="click" @command="handleExport">
          <el-button type="primary" :disabled="completedCount === 0">
            <el-icon><Download /></el-icon>
            导出
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="word">
                <el-icon><Document /></el-icon>
                导出 Word（修订版）
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
          @select-item="selectItem"
          @send-message="sendMessage"
          @complete="completeCurrentItem"
          @locate="scrollToHighlight"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowDown, Download, Document, Files } from '@element-plus/icons-vue'
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
const task = ref(null)
const items = ref([])
const activeItemId = ref(null)
const activeMessages = ref([])
const currentSuggestion = ref('')
const documentParagraphs = ref([])
const documentViewerRef = ref(null)

// 计算属性
const activeItem = computed(() => {
  return items.value.find(item => item.id === activeItemId.value)
})

const completedCount = computed(() => {
  return items.value.filter(item => item.status === 'completed').length
})

const completionPercentage = computed(() => {
  if (items.value.length === 0) return 0
  return Math.round((completedCount.value / items.value.length) * 100)
})

// 判断当前是否有流式输出进行中
const isStreaming = computed(() => {
  return activeMessages.value.some(msg => msg.isStreaming)
})

// 加载数据
onMounted(async () => {
  await loadData()
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
    items.value = itemsResponse.data || []

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

// 选择条目
async function selectItem(item) {
  if (activeItemId.value === item.id) return

  activeItemId.value = item.id
  activeMessages.value = []
  currentSuggestion.value = item.current_suggestion || item.suggested_text || ''

  // 加载条目详情（含对话历史）
  try {
    const response = await interactiveApi.getItemDetail(taskId.value, item.id)
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
  if (!activeItemId.value || chatLoading.value) return

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
      activeItemId.value,
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
  if (!activeItemId.value) return

  try {
    await interactiveApi.completeItem(taskId.value, activeItemId.value, finalSuggestion)

    // 更新本地状态
    const localItem = items.value.find(i => i.id === activeItemId.value)
    if (localItem) {
      localItem.status = 'completed'
      localItem.current_suggestion = finalSuggestion
    }

    ElMessage.success('条目已确认')

    // 自动跳转到下一个未完成的条目
    const nextPending = items.value.find(item => item.status !== 'completed')
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
  } catch (error) {
    console.error('完成条目失败:', error)
    ElMessage.error('完成条目失败: ' + (error.message || '请重试'))
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
  height: calc(100vh - var(--header-height));
  display: flex;
  flex-direction: column;
  background: var(--color-bg-secondary);
}

/* 顶栏 */
.review-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-3) var(--spacing-5);
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-sm);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.document-name {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.header-center {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.progress-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

/* 主内容区 - 左右布局 */
.review-content {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* 左侧：文档区域 70% */
.content-left {
  flex: 7;
  overflow: hidden;
}

/* 右侧：聊天面板 30% */
.content-right {
  flex: 3;
  min-width: 360px;
  max-width: 480px;
  overflow: hidden;
  border-left: 1px solid var(--color-border-light);
}

/* 响应式 */
@media (max-width: 1200px) {
  .content-right {
    min-width: 320px;
    flex: 4;
  }

  .content-left {
    flex: 6;
  }
}

@media (max-width: 1024px) {
  .header-center {
    display: none;
  }

  .content-right {
    min-width: 300px;
  }
}

@media (max-width: 768px) {
  .review-content {
    flex-direction: column;
  }

  .content-left {
    flex: none;
    height: 40%;
    min-height: 200px;
  }

  .content-right {
    flex: 1;
    min-width: 100%;
    max-width: 100%;
    border-left: none;
    border-top: 1px solid var(--color-border-light);
  }
}
</style>
