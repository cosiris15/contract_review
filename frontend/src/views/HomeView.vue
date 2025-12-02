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

    <!-- 主内容区 - 全屏Hero布局 -->
    <div class="hero-section">
      <!-- 左侧：主标题和操作区 -->
      <div class="hero-content">
        <div class="hero-badge">
          <el-icon><Cpu /></el-icon>
          <span>AI 驱动的智能审阅</span>
        </div>
        <h1 class="hero-title">十行合同</h1>
        <p class="hero-subtitle">
          专业的法务文本智能审阅平台，助力法务团队高效审阅合同、营销材料等各类文本，
          快速识别风险点并提供专业的修改建议。
        </p>
        <div class="hero-actions">
          <el-button
            type="primary"
            size="large"
            @click="goToNewReview"
            class="action-btn primary-action"
          >
            <el-icon><Plus /></el-icon>
            新建审阅任务
          </el-button>
        </div>
      </div>

      <!-- 右侧：功能特性展示 -->
      <div class="hero-features">
        <div class="features-grid">
          <div class="feature-card">
            <div class="feature-icon">
              <el-icon :size="32"><Search /></el-icon>
            </div>
            <div class="feature-content">
              <h3>智能风险识别</h3>
              <p>基于定制化审核标准，自动识别文本中的潜在法务风险，不遗漏任何关键问题</p>
            </div>
          </div>

          <div class="feature-card">
            <div class="feature-icon">
              <el-icon :size="32"><Edit /></el-icon>
            </div>
            <div class="feature-content">
              <h3>专业修改建议</h3>
              <p>针对每个风险点提供具体可执行的文本修改方案，直接复制使用</p>
            </div>
          </div>

          <div class="feature-card">
            <div class="feature-icon">
              <el-icon :size="32"><List /></el-icon>
            </div>
            <div class="feature-content">
              <h3>行动建议清单</h3>
              <p>提供文本修改之外的补充措施与注意事项，全面把控风险</p>
            </div>
          </div>

          <div class="feature-card">
            <div class="feature-icon">
              <el-icon :size="32"><Download /></el-icon>
            </div>
            <div class="feature-content">
              <h3>一键导出修订版</h3>
              <p>导出带修订标记的 Word 文档，方便对照查阅与团队协作</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部装饰 -->
    <div class="hero-decoration">
      <div class="decoration-line"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useReviewStore } from '@/store'
import { Plus, Search, Edit, List, Download, Cpu } from '@element-plus/icons-vue'

const router = useRouter()
const store = useReviewStore()

// 后端连接状态（简化版，仅在出错时显示）
const backendStatus = ref('ready') // 默认就绪，付费版不需要冷启动等待
const connectionError = ref('')
const isRetrying = ref(false)

onMounted(() => {
  // 后台静默加载（预热连接）
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
</script>

<style scoped>
.home-view {
  min-height: calc(100vh - var(--header-height) - var(--spacing-6) * 2);
  display: flex;
  flex-direction: column;
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

/* Hero 区域 */
.hero-section {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--spacing-10);
  align-items: center;
  max-width: var(--max-width);
  margin: 0 auto;
  padding: var(--spacing-8) 0;
}

/* 左侧内容区 */
.hero-content {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-5);
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-2) var(--spacing-4);
  background: linear-gradient(135deg, var(--color-primary-bg) 0%, var(--color-primary-bg-hover) 100%);
  border: 1px solid var(--color-primary-lighter);
  border-radius: 999px;
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  width: fit-content;
}

.hero-title {
  font-size: 56px;
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  line-height: 1.1;
  letter-spacing: -1px;
  background: linear-gradient(135deg, var(--color-text-primary) 0%, var(--color-primary) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-subtitle {
  font-size: var(--font-size-lg);
  color: var(--color-text-secondary);
  line-height: var(--line-height-relaxed);
  max-width: 520px;
}

.hero-actions {
  display: flex;
  justify-content: center;
  margin-top: var(--spacing-3);
}

.action-btn {
  padding: var(--spacing-4) var(--spacing-6);
  font-size: var(--font-size-md);
  height: auto;
  transition: transform 0.15s ease, box-shadow 0.15s ease !important;
}

.action-btn:active {
  transform: scale(0.97) !important;
}

.primary-action {
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.25);
}

.primary-action:hover {
  box-shadow: 0 6px 20px rgba(37, 99, 235, 0.35);
}

/* 右侧功能展示 */
.hero-features {
  display: flex;
  align-items: center;
}

.features-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--spacing-4);
  width: 100%;
}

.feature-card {
  display: flex;
  gap: var(--spacing-4);
  padding: var(--spacing-5);
  background: var(--color-bg-card);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border-light);
  transition: all 0.25s ease;
}

.feature-card:hover {
  border-color: var(--color-primary-lighter);
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.08);
  transform: translateY(-2px);
}

.feature-icon {
  flex-shrink: 0;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--color-primary-bg) 0%, var(--color-primary-bg-hover) 100%);
  border-radius: var(--radius-lg);
  color: var(--color-primary);
}

.feature-content h3 {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-2);
}

.feature-content p {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  line-height: var(--line-height-normal);
}

/* 底部装饰 */
.hero-decoration {
  padding: var(--spacing-8) 0 var(--spacing-4);
}

.decoration-line {
  height: 3px;
  background: linear-gradient(90deg,
    transparent 0%,
    var(--color-primary-lighter) 20%,
    var(--color-primary) 50%,
    var(--color-primary-lighter) 80%,
    transparent 100%);
  border-radius: 999px;
  opacity: 0.4;
}

/* 响应式布局 */
@media (max-width: 1200px) {
  .hero-section {
    grid-template-columns: 1fr;
    gap: var(--spacing-8);
    text-align: center;
  }

  .hero-content {
    align-items: center;
  }

  .hero-subtitle {
    max-width: 600px;
  }

  .features-grid {
    max-width: 600px;
    margin: 0 auto;
  }
}

@media (max-width: 768px) {
  .hero-title {
    font-size: 40px;
  }

  .hero-subtitle {
    font-size: var(--font-size-base);
  }

  .features-grid {
    grid-template-columns: 1fr;
  }

  .feature-card {
    flex-direction: column;
    text-align: center;
  }

  .feature-icon {
    margin: 0 auto;
  }
}
</style>
