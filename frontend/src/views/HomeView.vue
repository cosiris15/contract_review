<template>
  <div class="home-view">
    <!-- 后端连接错误提示（仅在出错时显示） -->
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
              class="action-btn"
            >
              <el-icon><Plus /></el-icon>
              新建审阅任务
            </el-button>
            <el-button
              size="large"
              @click="goToDocuments"
              class="action-btn"
            >
              <el-icon><FolderOpened /></el-icon>
              查看所有文档
            </el-button>
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
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useReviewStore } from '@/store'
import { Plus, FolderOpened, Search, Edit, List, Download } from '@element-plus/icons-vue'

const router = useRouter()
const store = useReviewStore()

const tasks = ref([])

// 后端连接状态（简化版，仅在出错时显示）
const backendStatus = ref('ready') // 默认就绪，付费版不需要冷启动等待
const connectionError = ref('')
const isRetrying = ref(false)

// 统计数据
const totalDocuments = computed(() => tasks.value.length)
const completedDocuments = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const inProgressDocuments = computed(() =>
  tasks.value.filter(t => t.status === 'reviewing' || t.status === 'created' || t.status === 'uploading').length
)

onMounted(() => {
  // 后台静默加载任务列表（不阻塞 UI）
  fetchTasks()
})

// 重试连接
async function retryConnection() {
  isRetrying.value = true
  backendStatus.value = 'ready'
  connectionError.value = ''
  await fetchTasks()
  isRetrying.value = false
}

async function fetchTasks() {
  try {
    await store.fetchTasks()
    tasks.value = store.tasks
    backendStatus.value = 'ready'
  } catch (error) {
    console.error('获取任务列表失败:', error)
    // 仅在严重错误时显示错误状态
    if (error.errorInfo?.type === 'network' || error.errorInfo?.type === 'backend_unavailable') {
      backendStatus.value = 'error'
      connectionError.value = error.message || '无法连接到后端服务'
    }
  }
}

function goToNewReview() {
  // 立即跳转，不阻塞
  store.resetState()
  router.push('/review')
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

/* 按钮点击即时反馈 */
.action-btn {
  transition: transform 0.1s ease, box-shadow 0.1s ease !important;
}

.action-btn:active {
  transform: scale(0.97) !important;
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
