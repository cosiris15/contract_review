<template>
  <div class="documents-view">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <h1>文档管理</h1>
        <p class="subtitle">管理所有审阅任务和文档</p>
      </div>
      <div class="header-actions">
        <el-button
          v-if="selectedIds.length > 0"
          type="danger"
          @click="batchDelete"
        >
          <el-icon><Delete /></el-icon>
          删除选中 ({{ selectedIds.length }})
        </el-button>
        <el-button type="primary" @click="goToNewReview">
          <el-icon><Plus /></el-icon>
          新建审阅任务
        </el-button>
      </div>
    </div>

    <!-- 筛选区域 -->
    <el-card class="filter-card">
      <div class="filter-row">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索文档名称、我方身份..."
          clearable
          style="width: 280px"
          @input="handleSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>

        <el-select
          v-model="filterStatus"
          placeholder="状态"
          clearable
          style="width: 130px"
        >
          <el-option label="已创建" value="created" />
          <el-option label="审阅中" value="reviewing" />
          <el-option label="已完成" value="completed" />
          <el-option label="失败" value="failed" />
        </el-select>

        <el-select
          v-model="filterMaterialType"
          placeholder="材料类型"
          clearable
          style="width: 130px"
        >
          <el-option label="合同" value="contract" />
          <el-option label="营销材料" value="marketing" />
        </el-select>

        <el-select
          v-model="sortField"
          placeholder="排序"
          style="width: 140px"
        >
          <el-option label="创建时间" value="created_at" />
          <el-option label="更新时间" value="updated_at" />
          <el-option label="文档名称" value="name" />
        </el-select>

        <el-button
          :icon="sortOrder === 'desc' ? 'SortDown' : 'SortUp'"
          @click="toggleSortOrder"
        >
          {{ sortOrder === 'desc' ? '降序' : '升序' }}
        </el-button>

        <el-button text @click="resetFilters">
          <el-icon><Refresh /></el-icon>
          重置
        </el-button>
      </div>
    </el-card>

    <!-- 统计信息 -->
    <div class="stats-bar" v-if="tasks.length > 0">
      <span>共 {{ filteredTasks.length }} 个文档</span>
      <span class="stats-divider">|</span>
      <span>已完成 {{ completedCount }} 个</span>
      <span class="stats-divider">|</span>
      <span>进行中 {{ inProgressCount }} 个</span>
    </div>

    <!-- 文档列表 -->
    <div class="documents-list" v-loading="loading">
      <!-- 全选 -->
      <div class="select-all-row" v-if="paginatedTasks.length > 0">
        <el-checkbox
          v-model="selectAll"
          :indeterminate="isIndeterminate"
          @change="handleSelectAll"
        >
          全选当前页
        </el-checkbox>
      </div>

      <el-empty v-if="filteredTasks.length === 0 && !loading" description="暂无文档">
        <el-button type="primary" @click="goToNewReview">创建第一个任务</el-button>
      </el-empty>

      <div
        v-for="task in paginatedTasks"
        :key="task.id"
        class="document-card"
        :class="{ selected: selectedIds.includes(task.id) }"
      >
        <el-checkbox
          :model-value="selectedIds.includes(task.id)"
          @change="(val) => handleSelect(task.id, val)"
          class="document-checkbox"
          @click.stop
        />

        <div class="document-card-main" @click="goToTask(task)">
          <div class="document-icon">
            <el-icon :size="24"><Document /></el-icon>
          </div>
          <div class="document-info">
            <div class="document-name">
              {{ task.document_filename || task.name }}
              <el-tag :type="statusType(task.status)" size="small">
                {{ statusText(task.status) }}
              </el-tag>
              <el-tag type="info" size="small">
                {{ formatMaterialType(task.material_type) }}
              </el-tag>
            </div>
            <div class="document-meta">
              <span v-if="task.our_party">
                <el-icon><User /></el-icon>
                {{ task.our_party }}
              </span>
              <span class="meta-sep">|</span>
              <span>
                <el-icon><Clock /></el-icon>
                {{ formatTime(task.created_at) }}
              </span>
              <span v-if="task.language === 'en'" class="meta-sep">|</span>
              <el-tag v-if="task.language === 'en'" size="small" type="success">EN</el-tag>
            </div>
          </div>
        </div>

        <div class="document-actions">
          <el-button
            v-if="task.status === 'completed'"
            text
            type="primary"
            @click.stop="goToResult(task)"
          >
            <el-icon><View /></el-icon>
            查看结果
          </el-button>
          <el-button
            v-else
            text
            type="primary"
            @click.stop="goToTask(task)"
          >
            <el-icon><Edit /></el-icon>
            继续审阅
          </el-button>
          <el-button
            text
            type="danger"
            @click.stop="deleteTask(task)"
          >
            <el-icon><Delete /></el-icon>
            删除
          </el-button>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div class="pagination-wrapper" v-if="filteredTasks.length > pageSize">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="filteredTasks.length"
        layout="prev, pager, next, jumper"
        @current-change="handlePageChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useReviewStore } from '@/store'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Search, Plus, Delete, Refresh, Document,
  User, Clock, View, Edit
} from '@element-plus/icons-vue'

const router = useRouter()
const store = useReviewStore()

// 数据
const loading = ref(false)
const tasks = ref([])

// 筛选和排序
const searchKeyword = ref('')
const filterStatus = ref('')
const filterMaterialType = ref('')
const sortField = ref('created_at')
const sortOrder = ref('desc')

// 分页
const currentPage = ref(1)
const pageSize = 10

// 选择
const selectedIds = ref([])

// 防抖定时器
let searchTimer = null

// 计算属性
const filteredTasks = computed(() => {
  let result = [...tasks.value]

  // 搜索过滤
  if (searchKeyword.value) {
    const keyword = searchKeyword.value.toLowerCase()
    result = result.filter(task =>
      (task.document_filename || '').toLowerCase().includes(keyword) ||
      (task.name || '').toLowerCase().includes(keyword) ||
      (task.our_party || '').toLowerCase().includes(keyword)
    )
  }

  // 状态过滤
  if (filterStatus.value) {
    result = result.filter(task => task.status === filterStatus.value)
  }

  // 材料类型过滤
  if (filterMaterialType.value) {
    result = result.filter(task => task.material_type === filterMaterialType.value)
  }

  // 排序
  result.sort((a, b) => {
    let aVal, bVal

    if (sortField.value === 'name') {
      aVal = (a.document_filename || a.name || '').toLowerCase()
      bVal = (b.document_filename || b.name || '').toLowerCase()
    } else {
      aVal = new Date(a[sortField.value] || 0).getTime()
      bVal = new Date(b[sortField.value] || 0).getTime()
    }

    if (sortOrder.value === 'desc') {
      return aVal > bVal ? -1 : 1
    } else {
      return aVal < bVal ? -1 : 1
    }
  })

  return result
})

const paginatedTasks = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  const end = start + pageSize
  return filteredTasks.value.slice(start, end)
})

const completedCount = computed(() =>
  tasks.value.filter(t => t.status === 'completed').length
)

const inProgressCount = computed(() =>
  tasks.value.filter(t => t.status === 'reviewing' || t.status === 'created' || t.status === 'uploading').length
)

const selectAll = computed({
  get: () => {
    const currentIds = paginatedTasks.value.map(t => t.id)
    return currentIds.length > 0 && currentIds.every(id => selectedIds.value.includes(id))
  },
  set: () => {}
})

const isIndeterminate = computed(() => {
  const currentIds = paginatedTasks.value.map(t => t.id)
  const selectedInPage = currentIds.filter(id => selectedIds.value.includes(id))
  return selectedInPage.length > 0 && selectedInPage.length < currentIds.length
})

// 监听筛选变化，重置页码
watch([filterStatus, filterMaterialType, sortField, sortOrder], () => {
  currentPage.value = 1
})

// 加载数据
onMounted(async () => {
  await loadTasks()
})

async function loadTasks() {
  loading.value = true
  try {
    await store.fetchTasks()
    tasks.value = store.tasks
  } catch (error) {
    ElMessage.error(error.errorInfo?.message || '获取任务列表失败')
  } finally {
    loading.value = false
  }
}

// 搜索防抖
function handleSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
  }, 300)
}

// 排序切换
function toggleSortOrder() {
  sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
}

// 重置筛选
function resetFilters() {
  searchKeyword.value = ''
  filterStatus.value = ''
  filterMaterialType.value = ''
  sortField.value = 'created_at'
  sortOrder.value = 'desc'
  currentPage.value = 1
}

// 分页
function handlePageChange() {
  // 滚动到顶部
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

// 选择操作
function handleSelect(id, checked) {
  if (checked) {
    selectedIds.value.push(id)
  } else {
    selectedIds.value = selectedIds.value.filter(i => i !== id)
  }
}

function handleSelectAll(checked) {
  const currentIds = paginatedTasks.value.map(t => t.id)
  if (checked) {
    // 添加当前页所有未选中的
    currentIds.forEach(id => {
      if (!selectedIds.value.includes(id)) {
        selectedIds.value.push(id)
      }
    })
  } else {
    // 移除当前页所有已选中的
    selectedIds.value = selectedIds.value.filter(id => !currentIds.includes(id))
  }
}

// 批量删除
async function batchDelete() {
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedIds.value.length} 个文档吗？此操作不可恢复。`,
      '批量删除',
      { type: 'warning' }
    )

    loading.value = true
    let successCount = 0
    let failCount = 0

    for (const id of selectedIds.value) {
      try {
        await store.deleteTask(id)
        successCount++
      } catch {
        failCount++
      }
    }

    tasks.value = store.tasks
    selectedIds.value = []

    if (failCount === 0) {
      ElMessage.success(`成功删除 ${successCount} 个文档`)
    } else {
      ElMessage.warning(`删除完成：成功 ${successCount} 个，失败 ${failCount} 个`)
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  } finally {
    loading.value = false
  }
}

// 单个删除
async function deleteTask(task) {
  try {
    await ElMessageBox.confirm(
      `确定要删除 "${task.document_filename || task.name}" 吗？`,
      '确认删除',
      { type: 'warning' }
    )
    await store.deleteTask(task.id)
    tasks.value = store.tasks
    selectedIds.value = selectedIds.value.filter(id => id !== task.id)
    ElMessage.success('删除成功')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

// 导航
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

// 格式化函数
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

function formatMaterialType(type) {
  return type === 'contract' ? '合同' : '营销材料'
}

function formatTime(isoString) {
  if (!isoString) return ''
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}
</script>

<style scoped>
.documents-view {
  max-width: var(--max-width);
  margin: 0 auto;
}

/* 页面头部 */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--spacing-5);
}

.header-left h1 {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-1);
}

.subtitle {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-base);
}

.header-actions {
  display: flex;
  gap: var(--spacing-3);
}

/* 筛选卡片 */
.filter-card {
  margin-bottom: var(--spacing-4);
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-3);
  align-items: center;
}

/* 统计信息 */
.stats-bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  margin-bottom: var(--spacing-4);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.stats-divider {
  color: var(--color-border-dark);
}

/* 全选行 */
.select-all-row {
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  border-bottom: none;
}

/* 文档列表 */
.documents-list {
  background: var(--color-bg-card);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.document-card {
  display: flex;
  align-items: center;
  padding: var(--spacing-4);
  border-bottom: 1px solid var(--color-border-light);
  transition: background-color 0.15s ease, transform 0.1s ease;
}

.document-card:last-child {
  border-bottom: none;
}

.document-card:hover {
  background: var(--color-bg-hover);
}

.document-card:active {
  background: var(--color-primary-bg);
}

.document-card.selected {
  background: var(--color-primary-bg);
}

.document-checkbox {
  margin-right: var(--spacing-3);
}

.document-card-main {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
  cursor: pointer;
}

.document-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary-bg);
  border-radius: var(--radius-md);
  color: var(--color-primary);
}

.document-info {
  flex: 1;
}

.document-name {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-2);
}

.document-meta {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

.document-meta span {
  display: flex;
  align-items: center;
  gap: 4px;
}

.meta-sep {
  color: var(--color-border-dark);
}

.document-actions {
  display: flex;
  gap: var(--spacing-1);
}

/* 分页 */
.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding: var(--spacing-5) 0;
}

/* 响应式 */
@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .header-actions {
    width: 100%;
  }

  .header-actions .el-button {
    flex: 1;
  }

  .filter-row {
    flex-direction: column;
  }

  .filter-row > * {
    width: 100% !important;
  }

  .document-card-main {
    flex-direction: column;
    align-items: flex-start;
  }

  .document-actions {
    flex-direction: column;
    width: 100%;
    margin-top: var(--spacing-3);
  }
}
</style>
