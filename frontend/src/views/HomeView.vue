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
          <h1 class="welcome-title">十行合同</h1>
          <p class="welcome-desc">助力法务审阅合同、营销材料等文本，识别风险点并提供专业的修改建议。</p>
          <div class="welcome-actions">
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
            <el-button
              size="large"
              @click="goToDocuments"
              :disabled="backendStatus !== 'ready'"
            >
              <el-icon><FolderOpened /></el-icon>
              查看所有文档
            </el-button>
          </div>
          <div v-if="backendStatus !== 'ready'" class="backend-hint">
            {{ backendStatus === 'connecting' ? '等待后端服务就绪...' : '请先连接后端服务' }}
          </div>
        </div>
        <div class="welcome-features">
          <div class="feature-item">
            <div class="feature-icon">
              <el-icon :size="28"><Search /></el-icon>
            </div>
            <h3>智能风险识别</h3>
            <p>基于审核标准自动识别文本中的潜在法务风险</p>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <el-icon :size="28"><Edit /></el-icon>
            </div>
            <h3>修改建议</h3>
            <p>针对每个风险点提供具体可执行的文本修改方案</p>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <el-icon :size="28"><List /></el-icon>
            </div>
            <h3>行动建议</h3>
            <p>提供文本修改之外的补充措施与注意事项</p>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <el-icon :size="28"><Download /></el-icon>
            </div>
            <h3>修订版导出</h3>
            <p>一键导出带修订标记的 Word 文档，方便对照查阅</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 简单统计 -->
    <div class="stats-section" v-if="backendStatus === 'ready'">
      <div class="stats-card">
        <div class="stat-item">
          <div class="stat-value">{{ totalDocuments }}</div>
          <div class="stat-label">文档总数</div>
        </div>
        <div class="stat-divider"></div>
        <div class="stat-item">
          <div class="stat-value completed">{{ completedDocuments }}</div>
          <div class="stat-label">已完成</div>
        </div>
        <div class="stat-divider"></div>
        <div class="stat-item">
          <div class="stat-value in-progress">{{ inProgressDocuments }}</div>
          <div class="stat-label">进行中</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useReviewStore } from '@/store'
import { ElMessage } from 'element-plus'
import { Loading, Plus, FolderOpened, Search, Edit, List, Download } from '@element-plus/icons-vue'

const router = useRouter()
const store = useReviewStore()

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

// 统计数据
const totalDocuments = computed(() => tasks.value.length)
const completedDocuments = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const inProgressDocuments = computed(() =>
  tasks.value.filter(t => t.status === 'reviewing' || t.status === 'created' || t.status === 'uploading').length
)

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
    // 连接成功后加载任务列表（用于统计）
    await fetchTasks()
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

async function fetchTasks() {
  try {
    await store.fetchTasks()
    tasks.value = store.tasks
  } catch (error) {
    // 静默处理，仅用于统计
    console.error('获取任务列表失败:', error)
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

function goToDocuments() {
  router.push('/documents')
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
  margin-bottom: var(--spacing-6);
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

.welcome-title {
  font-size: var(--font-size-3xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-3);
}

.welcome-desc {
  color: var(--color-text-secondary);
  font-size: var(--font-size-md);
  margin-bottom: var(--spacing-6);
  line-height: var(--line-height-relaxed);
  max-width: 600px;
  margin-left: auto;
  margin-right: auto;
}

.welcome-actions {
  display: flex;
  justify-content: center;
  gap: var(--spacing-4);
}

.welcome-features {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--spacing-5);
}

.feature-item {
  text-align: center;
  padding: var(--spacing-5) var(--spacing-3);
  border-radius: var(--radius-lg);
  transition: all 0.2s;
}

.feature-item:hover {
  background: var(--color-bg-secondary);
}

.feature-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto var(--spacing-3);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary-bg);
  border-radius: var(--radius-lg);
  color: var(--color-primary);
}

.feature-item h3 {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.feature-item p {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-normal);
}

/* 统计区域 */
.stats-section {
  margin-bottom: var(--spacing-6);
}

.stats-card {
  background: var(--color-bg-card);
  border-radius: var(--radius-lg);
  padding: var(--spacing-6);
  box-shadow: var(--shadow-md);
  display: flex;
  justify-content: center;
  align-items: center;
  gap: var(--spacing-8);
}

.stat-item {
  text-align: center;
  padding: 0 var(--spacing-6);
}

.stat-value {
  font-size: var(--font-size-3xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-1);
}

.stat-value.completed {
  color: var(--color-success);
}

.stat-value.in-progress {
  color: var(--color-warning);
}

.stat-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
}

.stat-divider {
  width: 1px;
  height: 48px;
  background: var(--color-border);
}

/* 响应式 */
@media (max-width: 1024px) {
  .welcome-features {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .welcome-card {
    padding: var(--spacing-6);
  }

  .welcome-actions {
    flex-direction: column;
  }

  .welcome-features {
    grid-template-columns: 1fr;
  }

  .stats-card {
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .stat-divider {
    width: 100%;
    height: 1px;
  }
}
</style>
