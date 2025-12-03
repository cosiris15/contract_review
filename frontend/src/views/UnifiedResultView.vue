<template>
  <div class="unified-result-view" v-loading="loading">
    <!-- 顶栏 -->
    <div class="result-header">
      <div class="header-left">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <el-divider direction="vertical" />
        <span class="document-name">{{ task?.document_filename || '审阅结果' }}</span>
        <el-tag v-if="usedStandards" type="success" size="small">已应用标准</el-tag>
        <el-tag v-else type="info" size="small">AI 自主审阅</el-tag>
      </div>

      <div class="header-center">
        <!-- 视图切换 -->
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="interactive">
            <el-icon><ChatDotRound /></el-icon>
            交互视图
          </el-radio-button>
          <el-radio-button value="list">
            <el-icon><List /></el-icon>
            列表视图
          </el-radio-button>
        </el-radio-group>
      </div>

      <div class="header-right">
        <!-- 进度显示（交互视图时） -->
        <div v-if="viewMode === 'interactive'" class="progress-info">
          <el-progress
            :percentage="completionPercentage"
            :stroke-width="8"
            style="width: 120px"
          />
          <span class="progress-text">{{ completedCount }}/{{ items.length }}</span>
        </div>

        <!-- 导出按钮 -->
        <el-dropdown trigger="click" @command="handleExport">
          <el-button type="primary">
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
              <el-dropdown-item command="excel">
                <el-icon><Document /></el-icon>
                导出 Excel
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="result-content">
      <!-- 交互视图 -->
      <template v-if="viewMode === 'interactive'">
        <div class="content-left">
          <DocumentViewer
            ref="documentViewerRef"
            :document-name="task?.document_filename"
            :paragraphs="documentParagraphs"
            :highlight-text="activeItem?.original_text"
            :loading="documentLoading"
          />
        </div>
        <div class="content-right">
          <ChatPanel
            :items="items"
            :active-item="activeItem"
            :messages="activeMessages"
            :current-suggestion="currentSuggestion"
            :loading="chatLoading"
            @select-item="selectItem"
            @send-message="sendMessage"
            @complete="completeCurrentItem"
            @locate="scrollToHighlight"
          />
        </div>
      </template>

      <!-- 列表视图 -->
      <template v-else>
        <ResultListView
          :result="reviewResult"
          :language="task?.language || 'zh-CN'"
          @update-modification="handleUpdateModification"
          @update-action="handleUpdateAction"
          @refresh="loadData"
        />
      </template>
    </div>

    <!-- Redline 导出对话框 -->
    <el-dialog
      v-model="showRedlineDialog"
      title="导出修订版 Word"
      width="500px"
    >
      <div class="redline-dialog-content">
        <el-alert
          v-if="!redlineExportStatus"
          title="提示：生成修订版文档预计需要 2-3 分钟，请耐心等待"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom: 16px;"
        />

        <div class="export-option">
          <div class="option-header">
            <el-icon><Document /></el-icon>
            <span>修改建议（修订标记）</span>
          </div>
          <div class="option-desc">
            将已确认的修改建议以删除线和插入标记形式显示
          </div>
          <div class="option-count">
            已确认 <strong>{{ confirmedModCount }}</strong> 条 / 共 {{ reviewResult?.modifications?.length || 0 }} 条
          </div>
        </div>

        <el-divider />

        <div class="export-option">
          <div class="option-header">
            <el-checkbox v-model="includeComments">
              <el-icon><ChatLineSquare /></el-icon>
              <span>行动建议（批注）</span>
            </el-checkbox>
          </div>
          <div class="option-desc">
            将已确认的行动建议作为批注添加到对应风险点的文本位置
          </div>
          <div class="option-count">
            已确认 <strong>{{ confirmedActionCount }}</strong> 条
          </div>
        </div>

        <!-- 导出进度显示 -->
        <div v-if="redlineExportStatus" class="export-progress">
          <el-divider />
          <div class="progress-header">
            <span>{{ redlineExportStatus.message }}</span>
            <el-tag v-if="redlineExportStatus.status === 'completed'" type="success" size="small">完成</el-tag>
            <el-tag v-else-if="redlineExportStatus.status === 'failed'" type="danger" size="small">失败</el-tag>
            <el-tag v-else type="info" size="small">{{ redlineExportStatus.progress }}%</el-tag>
          </div>
          <el-progress
            :percentage="redlineExportStatus.progress"
            :status="redlineExportStatus.status === 'completed' ? 'success' : redlineExportStatus.status === 'failed' ? 'exception' : ''"
            :stroke-width="10"
            style="margin-top: 8px;"
          />
        </div>
      </div>

      <template #footer>
        <el-button @click="showRedlineDialog = false">
          {{ redlineExportStatus?.status === 'completed' ? '关闭' : '取消' }}
        </el-button>
        <el-button
          v-if="redlineExportStatus?.status === 'completed'"
          type="success"
          @click="downloadRedlineExport"
          :loading="redlineDownloading"
        >
          下载文件
        </el-button>
        <el-button
          v-else
          type="primary"
          @click="startRedlineExport"
          :loading="redlineExporting"
          :disabled="confirmedModCount === 0 && confirmedActionCount === 0"
        >
          {{ redlineExporting ? '正在导出...' : '开始导出' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft, ArrowDown, Download, Document, Files, List,
  ChatDotRound, ChatLineSquare
} from '@element-plus/icons-vue'
import DocumentViewer from '@/components/interactive/DocumentViewer.vue'
import ChatPanel from '@/components/interactive/ChatPanel.vue'
import ResultListView from '@/components/result/ResultListView.vue'
import { useReviewStore } from '@/store'
import interactiveApi from '@/api/interactive'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const store = useReviewStore()

const taskId = computed(() => route.params.taskId)

// 主状态
const loading = ref(false)
const viewMode = ref('interactive') // 'interactive' | 'list'
const task = ref(null)
const reviewResult = ref(null)

// 交互视图状态
const documentLoading = ref(false)
const chatLoading = ref(false)
const items = ref([])
const activeItemId = ref(null)
const activeMessages = ref([])
const currentSuggestion = ref('')
const documentParagraphs = ref([])
const documentViewerRef = ref(null)

// Redline 导出状态
const showRedlineDialog = ref(false)
const redlineExporting = ref(false)
const redlineExportStatus = ref(null)
const redlineDownloading = ref(false)
const includeComments = ref(false)
let redlineStatusPoller = null

// 计算属性
const usedStandards = computed(() => !!task.value?.standard_filename)

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

const confirmedModCount = computed(() => {
  if (!reviewResult.value?.modifications) return 0
  return reviewResult.value.modifications.filter(m => m.user_confirmed).length
})

const confirmedActionCount = computed(() => {
  if (!reviewResult.value?.actions) return 0
  return reviewResult.value.actions.filter(a => a.user_confirmed).length
})

// 加载数据
onMounted(async () => {
  await loadData()
})

async function loadData() {
  loading.value = true
  try {
    // 并行加载任务信息、交互条目和审阅结果
    const [taskResponse, itemsResponse] = await Promise.all([
      api.getTask(taskId.value),
      interactiveApi.getInteractiveItems(taskId.value),
    ])

    task.value = taskResponse.data
    items.value = itemsResponse.data || []

    // 加载审阅结果（用于列表视图）
    await store.loadResult(taskId.value)
    reviewResult.value = store.reviewResult

    // 异步加载文档内容
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

async function loadDocumentText() {
  documentLoading.value = true
  try {
    const response = await interactiveApi.getDocumentText(taskId.value)
    documentParagraphs.value = response.data.paragraphs || []
  } catch (error) {
    console.error('加载文档内容失败:', error)
  } finally {
    documentLoading.value = false
  }
}

// 交互视图方法
async function selectItem(item) {
  if (activeItemId.value === item.id) return

  activeItemId.value = item.id
  activeMessages.value = []
  currentSuggestion.value = item.current_suggestion || item.suggested_text || ''

  try {
    const response = await interactiveApi.getItemDetail(taskId.value, item.id)
    const detail = response.data

    activeMessages.value = detail.messages || []
    currentSuggestion.value = detail.current_suggestion || item.suggested_text || ''

    const localItem = items.value.find(i => i.id === item.id)
    if (localItem) {
      localItem.status = detail.status
      localItem.message_count = detail.messages?.length || 0
    }
  } catch (error) {
    console.error('加载条目详情失败:', error)
    activeMessages.value = item.messages || []
  }
}

function scrollToHighlight() {
  if (documentViewerRef.value && activeItem.value?.original_text) {
    documentViewerRef.value.scrollToText(activeItem.value.original_text)
  }
}

async function sendMessage(message) {
  if (!activeItemId.value || chatLoading.value) return

  activeMessages.value.push({
    role: 'user',
    content: message,
    timestamp: new Date().toISOString()
  })

  chatLoading.value = true
  try {
    const response = await interactiveApi.sendChatMessage(
      taskId.value,
      activeItemId.value,
      message,
      'deepseek'
    )

    const result = response.data

    activeMessages.value.push({
      role: 'assistant',
      content: result.assistant_reply,
      timestamp: new Date().toISOString(),
      suggestion_snapshot: result.updated_suggestion
    })

    currentSuggestion.value = result.updated_suggestion

    const localItem = items.value.find(i => i.id === activeItemId.value)
    if (localItem) {
      localItem.status = 'in_progress'
      localItem.current_suggestion = result.updated_suggestion
      localItem.message_count = activeMessages.value.length
    }
  } catch (error) {
    console.error('发送消息失败:', error)
    ElMessage.error('发送消息失败: ' + (error.message || '请重试'))
    activeMessages.value.pop()
  } finally {
    chatLoading.value = false
  }
}

async function completeCurrentItem(finalSuggestion) {
  if (!activeItemId.value) return

  try {
    await interactiveApi.completeItem(taskId.value, activeItemId.value, finalSuggestion)

    const localItem = items.value.find(i => i.id === activeItemId.value)
    if (localItem) {
      localItem.status = 'completed'
      localItem.current_suggestion = finalSuggestion
    }

    ElMessage.success('条目已确认')

    const nextPending = items.value.find(item => item.status !== 'completed')
    if (nextPending) {
      await selectItem(nextPending)
    } else {
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
      }).catch(() => {})
    }
  } catch (error) {
    console.error('完成条目失败:', error)
    ElMessage.error('完成条目失败: ' + (error.message || '请重试'))
  }
}

// 列表视图方法
async function handleUpdateModification(modId, updates) {
  try {
    await store.updateModification(taskId.value, modId, updates)
  } catch (error) {
    ElMessage.error('更新失败')
  }
}

async function handleUpdateAction(actionId, updates) {
  try {
    if (typeof updates === 'boolean') {
      await store.updateAction(taskId.value, actionId, updates)
    } else {
      await store.updateAction(taskId.value, actionId, updates)
    }
  } catch (error) {
    ElMessage.error('更新失败')
  }
}

// 导出方法
async function handleExport(format) {
  if (format === 'word') {
    showRedlineDialog.value = true
    redlineExportStatus.value = null
  } else if (format === 'json') {
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
  } else if (format === 'excel') {
    const url = api.exportExcel(taskId.value)
    if (url) {
      window.open(url, '_blank')
    }
  }
}

async function startRedlineExport() {
  redlineExporting.value = true
  redlineExportStatus.value = { status: 'pending', progress: 0, message: '正在启动导出...' }

  try {
    const res = await api.startRedlineExport(taskId.value, null, includeComments.value)
    redlineExportStatus.value = res.data

    if (redlineStatusPoller) {
      clearInterval(redlineStatusPoller)
    }
    redlineStatusPoller = setInterval(pollRedlineStatus, 1000)
  } catch (error) {
    console.error('启动导出失败:', error)
    redlineExportStatus.value = { status: 'failed', progress: 0, message: '启动失败', error: error.message }
    redlineExporting.value = false
  }
}

async function pollRedlineStatus() {
  try {
    const res = await api.getRedlineExportStatus(taskId.value)
    redlineExportStatus.value = res.data

    if (res.data.status === 'completed' || res.data.status === 'failed') {
      if (redlineStatusPoller) {
        clearInterval(redlineStatusPoller)
        redlineStatusPoller = null
      }
      redlineExporting.value = false
    }
  } catch (error) {
    console.error('获取导出状态失败:', error)
  }
}

async function downloadRedlineExport() {
  redlineDownloading.value = true
  try {
    const res = await api.downloadRedlineExport(taskId.value)

    const contentDisposition = res.headers['content-disposition']
    let filename = 'document_redline.docx'
    if (contentDisposition) {
      const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;\s]+)/)
      if (utf8Match) {
        filename = decodeURIComponent(utf8Match[1])
      } else {
        const match = contentDisposition.match(/filename="?([^"]+)"?/)
        if (match) filename = match[1]
      }
    }

    const blob = new Blob([res.data], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)

    ElMessage.success('文件下载成功')
    showRedlineDialog.value = false
  } catch (error) {
    console.error('下载失败:', error)
    ElMessage.error(error.message || '下载失败，请重试')
  } finally {
    redlineDownloading.value = false
  }
}

function goBack() {
  if (viewMode.value === 'interactive' && completedCount.value < items.value.length) {
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
    }).catch(() => {})
  } else {
    router.push('/')
  }
}
</script>

<style scoped>
.unified-result-view {
  height: calc(100vh - var(--header-height));
  display: flex;
  flex-direction: column;
  background: var(--color-bg-secondary);
}

/* 顶栏 */
.result-header {
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

.header-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
}

.progress-info {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.progress-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

/* 主内容区 */
.result-content {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* 交互视图 - 左右布局 */
.content-left {
  flex: 7;
  overflow: hidden;
}

.content-right {
  flex: 3;
  min-width: 360px;
  max-width: 480px;
  overflow: hidden;
  border-left: 1px solid var(--color-border-light);
}

/* Redline 导出对话框样式 */
.redline-dialog-content {
  padding: var(--spacing-2) 0;
}

.export-option {
  padding: var(--spacing-3) 0;
}

.option-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-2);
}

.option-header .el-icon {
  color: var(--color-primary);
}

.option-desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin-bottom: var(--spacing-2);
  padding-left: var(--spacing-6);
}

.option-count {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  padding-left: var(--spacing-6);
}

.option-count strong {
  color: var(--color-primary);
}

.export-progress {
  margin-top: var(--spacing-2);
}

.progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
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
  .result-content {
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
