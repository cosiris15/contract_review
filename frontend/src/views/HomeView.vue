<template>
  <div class="home-view">
    <!-- 欢迎区域 -->
    <div class="welcome-section">
      <div class="welcome-card">
        <div class="welcome-content">
          <h1>法务文本审阅系统</h1>
          <p>使用 AI 技术从法务角度审阅合同、营销材料等文本，自动识别风险点并提供专业的修改建议。</p>
          <el-button type="primary" size="large" @click="goToNewReview">
            <el-icon><Plus /></el-icon>
            新建审阅任务
          </el-button>
        </div>
        <div class="welcome-features">
          <div class="feature-item">
            <el-icon :size="32" color="#667eea"><Search /></el-icon>
            <h3>智能风险识别</h3>
            <p>基于审核标准自动识别文本中的法务风险点</p>
          </div>
          <div class="feature-item">
            <el-icon :size="32" color="#667eea"><Edit /></el-icon>
            <h3>修改建议</h3>
            <p>针对每个风险点提供具体的文本修改建议</p>
          </div>
          <div class="feature-item">
            <el-icon :size="32" color="#667eea"><List /></el-icon>
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
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useReviewStore } from '@/store'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()
const store = useReviewStore()

const loading = ref(false)
const tasks = ref([])

onMounted(async () => {
  await refreshTasks()
})

async function refreshTasks() {
  loading.value = true
  try {
    await store.fetchTasks()
    tasks.value = store.tasks
  } catch (error) {
    ElMessage.error('获取任务列表失败')
  } finally {
    loading.value = false
  }
}

function goToNewReview() {
  store.resetState()
  router.push('/review')
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
  max-width: 1200px;
  margin: 0 auto;
}

.welcome-section {
  margin-bottom: 32px;
}

.welcome-card {
  background: white;
  border-radius: 12px;
  padding: 40px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.welcome-content {
  text-align: center;
  margin-bottom: 40px;
}

.welcome-content h1 {
  font-size: 28px;
  color: #303133;
  margin-bottom: 12px;
}

.welcome-content p {
  color: #606266;
  font-size: 16px;
  margin-bottom: 24px;
}

.welcome-features {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}

.feature-item {
  text-align: center;
  padding: 20px;
}

.feature-item h3 {
  margin: 12px 0 8px;
  font-size: 16px;
  color: #303133;
}

.feature-item p {
  color: #909399;
  font-size: 14px;
}

.recent-section {
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.section-header h2 {
  font-size: 18px;
  color: #303133;
  margin: 0;
}

.task-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.task-card {
  cursor: pointer;
  transition: transform 0.2s;
}

.task-card:hover {
  transform: translateY(-2px);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.task-name {
  font-weight: 600;
  color: #303133;
  font-size: 15px;
}

.task-meta {
  display: flex;
  gap: 16px;
  color: #909399;
  font-size: 13px;
  margin-bottom: 12px;
}

.task-meta span {
  display: flex;
  align-items: center;
  gap: 4px;
}

.task-files {
  margin-bottom: 12px;
}

.task-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 768px) {
  .welcome-features {
    grid-template-columns: 1fr;
  }

  .task-list {
    grid-template-columns: 1fr;
  }
}
</style>
