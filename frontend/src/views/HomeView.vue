<template>
  <div class="home-view">
    <!-- 后端连接状态提示 -->
    <el-alert
      v-if="backendStatus === 'connecting'"
      type="info"
      :closable="false"
      show-icon
      class="status-alert"
    >
      <template #title>
        <span>
          <el-icon class="is-loading"><Loading /></el-icon>
          {{ connectionMessage || '正在连接后端服务...' }}
        </span>
      </template>
      <template #default>
        <span class="alert-detail">Render 免费版服务在空闲后会休眠，首次访问可能需要等待 30-60 秒</span>
      </template>
    </el-alert>

    <el-alert
      v-if="backendStatus === 'error'"
      type="error"
      :closable="false"
      show-icon
      class="status-alert"
    >
      <template #title>后端服务连接失败</template>
      <template #default>
        <div class="alert-content">
          <span class="alert-detail">{{ connectionError }}</span>
          <el-button type="primary" size="small" @click="retryConnection" :loading="isRetrying">
            重试连接
          </el-button>
        </div>
      </template>
    </el-alert>

    <el-alert
      v-if="backendStatus === 'ready' && showSuccessAlert"
      type="success"
      closable
      show-icon
      class="status-alert"
      @close="showSuccessAlert = false"
    >
      <template #title>后端服务已就绪</template>
    </el-alert>

    <!-- 欢迎区域 -->
    <div class="welcome-section">
      <div class="welcome-card">
        <div class="welcome-content">
          <h1>法务文本审阅系统</h1>
          <p>使用 AI 技术从法务角度审阅合同、营销材料等文本，自动识别风险点并提供专业的修改建议。</p>
          <el-button
            type="primary"
            size="large"
            @click="goToNewReview"
            :loading="isCreatingTask"
            :disabled="backendStatus !== 'ready'"
          >
            <el-icon v-if="!isCreatingTask"><Plus /></el-icon>
            {{ isCreatingTask ? creatingTaskMessage : '新建审阅任务' }}
          </el-button>
          <div v-if="backendStatus !== 'ready'" class="backend-hint">
            {{ backendStatus === 'connecting' ? '等待后端服务就绪...' : '请先连接后端服务' }}
          </div>
        </div>
        <div class="welcome-features">
          <div class="feature-item">
            <el-icon :size="32"><Search /></el-icon>
            <h3>智能风险识别</h3>
            <p>基于审核标准自动识别文本中的法务风险点</p>
          </div>
          <div class="feature-item">
            <el-icon :size="32"><Edit /></el-icon>
            <h3>修改建议</h3>
            <p>针对每个风险点提供具体的文本修改建议</p>
          </div>
          <div class="feature-item">
            <el-icon :size="32"><List /></el-icon>
            <h3>行动建议</h3>
            <p>除文本修改外还应采取的其他措施</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 最近任务 -->
    <div class="recent-section">
      <div class="section-header">
        <h2>最近任务</h2>
        <el-button text @click="refreshTasks" :loading="loading">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>

      <el-empty v-if="tasks.length === 0" description="暂无任务">
        <el-button type="primary" @click="goToNewReview">创建第一个任务</el-button>
      </el-empty>

      <div v-else class="task-list">
        <el-card
          v-for="task in tasks.slice(0, 6)"
          :key="task.id"
          class="task-card"
          shadow="hover"
          @click="goToTask(task)"
        >
          <div class="task-header">
            <div class="task-name">{{ task.name }}</div>
            <el-tag :type="statusType(task.status)" size="small">
              {{ statusText(task.status) }}
            </el-tag>
          </div>
          <div class="task-meta">
            <span>
              <el-icon><User /></el-icon>
              {{ task.our_party }}
            </span>
            <span>
              <el-icon><Clock /></el-icon>
              {{ formatTime(task.created_at) }}
            </span>
          </div>
          <div class="task-files">
            <el-tag v-if="task.document_filename" type="info" size="small">
              {{ task.document_filename }}
            </el-tag>
            <el-tag v-else type="warning" size="small">未上传文档</el-tag>
          </div>
          <div class="task-actions">
            <el-button
              v-if="task.status === 'completed'"
              type="primary"
              size="small"
              @click.stop="goToResult(task)"
            >
              查看结果
            </el-button>
            <el-button
              v-else
              type="primary"
              size="small"
              @click.stop="goToTask(task)"
            >
              继续审阅
            </el-button>
            <el-button
              type="danger"
              size="small"
              text
              @click.stop="deleteTask(task)"
            >
              删除
            </el-button>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useReviewStore } from '@/store'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'

const router = useRouter()
const store = useReviewStore()

const loading = ref(false)
const tasks = ref([])

// 后端连接状态
const backendStatus = ref('unknown') // 'unknown' | 'connecting' | 'ready' | 'error'
const connectionMessage = ref('')
const connectionError = ref('')
const isRetrying = ref(false)
const showSuccessAlert = ref(false)
let successAlertTimer = null

// 任务创建状态
const isCreatingTask = ref(false)
const creatingTaskMessage = ref('')

// 计算属性
const isOperationInProgress = computed(() => store.isOperationInProgress)

onMounted(async () => {
  // 首先检查后端连接
  await checkBackendConnection()
})

onUnmounted(() => {
  if (successAlertTimer) {
    clearTimeout(successAlertTimer)
  }
})

// 检查后端连接
async function checkBackendConnection() {
  backendStatus.value = 'connecting'
  connectionMessage.value = '正在连接后端服务...'

  const success = await store.checkBackendStatus((progress) => {
    connectionMessage.value = progress.message
  })

  if (success) {
    backendStatus.value = 'ready'
    showSuccessAlert.value = true
    // 3秒后自动隐藏成功提示
    successAlertTimer = setTimeout(() => {
      showSuccessAlert.value = false
    }, 3000)
    // 连接成功后加载任务列表
    await refreshTasks()
  } else {
    backendStatus.value = 'error'
    connectionError.value = store.operationError?.message || '无法连接到后端服务'
  }
}

// 重试连接
async function retryConnection() {
  isRetrying.value = true
  await checkBackendConnection()
  isRetrying.value = false
}

async function refreshTasks() {
  loading.value = true
  try {
    await store.fetchTasks()
    tasks.value = store.tasks
  } catch (error) {
    const errorInfo = error.errorInfo
    if (errorInfo?.retryable) {
      ElMessage.warning({
        message: errorInfo.message,
        duration: 5000
      })
    } else {
      ElMessage.error(errorInfo?.message || '获取任务列表失败')
    }
  } finally {
    loading.value = false
  }
}

async function goToNewReview() {
  if (backendStatus.value !== 'ready') {
    ElMessage.warning('请等待后端服务就绪')
    return
  }

  isCreatingTask.value = true
  creatingTaskMessage.value = '正在准备...'

  try {
    store.resetState()
    router.push('/review')
  } catch (error) {
    ElMessage.error('跳转失败，请重试')
  } finally {
    isCreatingTask.value = false
  }
}

function goToTask(task) {
  if (task.status === 'completed') {
    router.push(`/result/${task.id}`)
  } else {
    router.push(`/review/${task.id}`)
  }
}

function goToResult(task) {
  router.push(`/result/${task.id}`)
}

async function deleteTask(task) {
  try {
    await ElMessageBox.confirm(
      `确定要删除任务 "${task.name}" 吗？`,
      '确认删除',
      { type: 'warning' }
    )
    await store.deleteTask(task.id)
    tasks.value = store.tasks
    ElMessage.success('删除成功')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

function statusType(status) {
  const types = {
    created: 'info',
    uploading: 'info',
    reviewing: 'warning',
    completed: 'success',
    failed: 'danger'
  }
  return types[status] || 'info'
}

function statusText(status) {
  const texts = {
    created: '已创建',
    uploading: '上传中',
    reviewing: '审阅中',
    completed: '已完成',
    failed: '失败'
  }
  return texts[status] || status
}

function formatTime(isoString) {
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}
</script>

<style scoped>
.home-view {
  max-width: var(--max-width);
  margin: 0 auto;
}

/* 状态提示样式 */
.status-alert {
  margin-bottom: var(--spacing-4);
}

.status-alert :deep(.el-alert__title) {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.alert-detail {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

.alert-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-4);
}

.backend-hint {
  margin-top: var(--spacing-3);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

/* 欢迎区域 */
.welcome-section {
  margin-bottom: var(--spacing-8);
}

.welcome-card {
  background: var(--color-bg-card);
  border-radius: var(--radius-lg);
  padding: var(--spacing-10);
  box-shadow: var(--shadow-md);
}

.welcome-content {
  text-align: center;
  margin-bottom: var(--spacing-10);
}

.welcome-content h1 {
  font-size: var(--font-size-3xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-3);
}

.welcome-content p {
  color: var(--color-text-secondary);
  font-size: var(--font-size-md);
  margin-bottom: var(--spacing-6);
  line-height: var(--line-height-relaxed);
}

.welcome-features {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--spacing-6);
}

.feature-item {
  text-align: center;
  padding: var(--spacing-5);
}

.feature-item :deep(.el-icon) {
  color: var(--color-primary) !important;
}

.feature-item h3 {
  margin: var(--spacing-3) 0 var(--spacing-2);
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.feature-item p {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-base);
  line-height: var(--line-height-normal);
}

/* 最近任务区域 */
.recent-section {
  background: var(--color-bg-card);
  border-radius: var(--radius-lg);
  padding: var(--spacing-6);
  box-shadow: var(--shadow-md);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-5);
}

.section-header h2 {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
}

.task-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--spacing-4);
}

.task-card {
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.task-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-3);
}

.task-name {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  font-size: var(--font-size-base);
}

.task-meta {
  display: flex;
  gap: var(--spacing-4);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
  margin-bottom: var(--spacing-3);
}

.task-meta span {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
}

.task-files {
  margin-bottom: var(--spacing-3);
}

.task-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-2);
}

/* 响应式 */
@media (max-width: 768px) {
  .welcome-card {
    padding: var(--spacing-6);
  }

  .welcome-features {
    grid-template-columns: 1fr;
  }

  .task-list {
    grid-template-columns: 1fr;
  }
}
</style>
