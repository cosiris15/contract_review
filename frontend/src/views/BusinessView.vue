<template>
  <div class="business-view">
    <!-- 第一层：业务条线列表 -->
    <template v-if="!selectedLine">
      <!-- 页面头部 -->
      <div class="page-header">
        <div class="header-left">
          <h1>业务条线管理</h1>
          <p class="subtitle">管理业务背景信息，在审阅时提供业务上下文</p>
        </div>
        <div class="header-actions">
          <el-button type="primary" @click="showCreateDialog = true">
            <el-icon><Plus /></el-icon>
            新建业务条线
          </el-button>
        </div>
      </div>

      <!-- 筛选 -->
      <el-card class="filter-card">
        <div class="filter-row">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索业务条线..."
            clearable
            style="width: 300px"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-select
            v-model="filterLanguage"
            placeholder="语言"
            clearable
            style="width: 150px"
            @change="loadBusinessLines"
          >
            <el-option label="中文" value="zh-CN" />
            <el-option label="English" value="en" />
          </el-select>
        </div>
      </el-card>

      <!-- 业务条线列表 -->
      <div class="lines-list" v-loading="loading">
        <el-empty v-if="filteredLines.length === 0" description="暂无业务条线" />
        <div
          v-for="line in filteredLines"
          :key="line.id"
          class="line-card"
        >
          <div class="line-card-main" @click="openLine(line)">
            <div class="line-icon">
              <el-icon :size="24"><Briefcase /></el-icon>
            </div>
            <div class="line-info">
              <div class="line-name">
                {{ line.name }}
                <el-tag v-if="line.is_preset" size="small" type="info">系统预设</el-tag>
                <el-tag v-if="line.language === 'en'" size="small" type="success">EN</el-tag>
              </div>
              <div class="line-desc">{{ line.description || '暂无描述' }}</div>
              <div class="line-meta">
                <span>{{ line.context_count }} 条背景信息</span>
                <span v-if="line.industry" class="meta-sep">|</span>
                <span v-if="line.industry">{{ line.industry }}</span>
              </div>
            </div>
          </div>
          <div class="line-actions">
            <el-button text type="primary" @click.stop="openLine(line)">
              <el-icon><View /></el-icon>
              查看
            </el-button>
            <el-button text type="primary" @click.stop="editLineInfo(line)" :disabled="line.is_preset">
              <el-icon><Edit /></el-icon>
              编辑
            </el-button>
            <el-button
              text
              type="danger"
              @click.stop="deleteLine(line)"
              :disabled="line.is_preset"
            >
              <el-icon><Delete /></el-icon>
              删除
            </el-button>
          </div>
        </div>
      </div>
    </template>

    <!-- 第二层：业务条线详情（背景信息管理） -->
    <template v-else>
      <!-- 详情头部 -->
      <div class="detail-header">
        <el-button text @click="backToList">
          <el-icon><ArrowLeft /></el-icon>
          返回列表
        </el-button>
        <div class="detail-title">
          <h2>{{ selectedLine.name }}</h2>
          <div class="detail-tags">
            <el-tag v-if="selectedLine.is_preset" size="small" type="info">系统预设</el-tag>
            <el-tag v-if="selectedLine.language === 'en'" size="small" type="success">EN</el-tag>
            <el-tag v-if="selectedLine.industry" size="small">{{ selectedLine.industry }}</el-tag>
          </div>
        </div>
        <el-button type="primary" text @click="editLineInfo(selectedLine)" :disabled="selectedLine.is_preset">
          <el-icon><Edit /></el-icon>
          编辑信息
        </el-button>
      </div>

      <!-- 业务条线信息卡片 -->
      <el-card class="line-info-card">
        <div class="info-grid">
          <div class="info-block">
            <div class="info-block-label">业务描述</div>
            <div class="info-block-value">{{ selectedLine.description || '暂无描述' }}</div>
          </div>
          <div class="info-block stats">
            <div class="stat-box">
              <div class="stat-number">{{ contexts.length }}</div>
              <div class="stat-text">背景信息</div>
            </div>
            <div class="stat-box">
              <div class="stat-number">{{ contextCategories.length }}</div>
              <div class="stat-text">分类</div>
            </div>
          </div>
        </div>
      </el-card>

      <!-- 背景信息筛选和操作 -->
      <el-card class="filter-card">
        <div class="filter-row">
          <el-input
            v-model="contextSearch"
            placeholder="搜索背景信息..."
            clearable
            style="width: 300px"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>

          <el-select
            v-model="filterCategory"
            placeholder="选择分类"
            clearable
            style="width: 200px"
          >
            <el-option
              v-for="cat in categories"
              :key="cat.id"
              :label="cat.name"
              :value="cat.id"
            />
          </el-select>

          <el-select
            v-model="filterPriority"
            placeholder="重要程度"
            clearable
            style="width: 150px"
          >
            <el-option label="高" value="high" />
            <el-option label="中" value="medium" />
            <el-option label="低" value="low" />
          </el-select>

          <el-button type="primary" @click="showAddContextDialog = true" :disabled="selectedLine.is_preset">
            <el-icon><Plus /></el-icon>
            添加背景信息
          </el-button>
        </div>
      </el-card>

      <!-- 背景信息列表表格 -->
      <el-card class="table-card">
        <el-table
          :data="filteredContexts"
          v-loading="loadingContexts"
          stripe
          style="width: 100%"
        >
          <el-table-column label="分类" width="140">
            <template #default="{ row }">
              <el-tag :type="getCategoryTagType(row.category)" size="small">
                {{ getCategoryName(row.category) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="item" label="要点" min-width="180" />
          <el-table-column prop="description" label="详细说明" min-width="280" show-overflow-tooltip />
          <el-table-column label="重要程度" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="getPriorityTagType(row.priority)" size="small">
                {{ getPriorityLabel(row.priority) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button
                type="primary"
                text
                size="small"
                @click="editContext(row)"
                :disabled="selectedLine.is_preset"
              >
                编辑
              </el-button>
              <el-button
                type="danger"
                text
                size="small"
                @click="deleteContext(row)"
                :disabled="selectedLine.is_preset"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="table-footer">
          <span>共 {{ filteredContexts.length }} 条背景信息</span>
        </div>
      </el-card>
    </template>

    <!-- 创建业务条线对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      title="创建业务条线"
      width="500px"
      @close="resetLineForm"
    >
      <el-form :model="lineForm" label-width="100px">
        <el-form-item label="条线名称" required>
          <el-input v-model="lineForm.name" placeholder="如：科技业务线、电商平台业务线" />
        </el-form-item>
        <el-form-item label="业务描述">
          <el-input
            v-model="lineForm.description"
            type="textarea"
            :rows="3"
            placeholder="描述该业务条线的主要特点和关注点"
          />
        </el-form-item>
        <el-form-item label="所属行业">
          <el-input v-model="lineForm.industry" placeholder="如：科技、电商、金融" />
        </el-form-item>
        <el-form-item label="语言">
          <el-select v-model="lineForm.language" style="width: 100%">
            <el-option label="中文" value="zh-CN" />
            <el-option label="English" value="en" />
          </el-select>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createLine" :loading="saving">
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑业务条线对话框 -->
    <el-dialog
      v-model="showEditDialog"
      title="编辑业务条线"
      width="500px"
    >
      <el-form :model="lineForm" label-width="100px">
        <el-form-item label="条线名称" required>
          <el-input v-model="lineForm.name" placeholder="如：科技业务线、电商平台业务线" />
        </el-form-item>
        <el-form-item label="业务描述">
          <el-input
            v-model="lineForm.description"
            type="textarea"
            :rows="3"
            placeholder="描述该业务条线的主要特点和关注点"
          />
        </el-form-item>
        <el-form-item label="所属行业">
          <el-input v-model="lineForm.industry" placeholder="如：科技、电商、金融" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="updateLine" :loading="saving">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 添加/编辑背景信息对话框 -->
    <el-dialog
      v-model="showAddContextDialog"
      :title="editingContext ? '编辑背景信息' : '添加背景信息'"
      width="600px"
      @close="resetContextForm"
    >
      <el-form :model="contextForm" label-width="100px">
        <el-form-item label="分类" required>
          <el-select v-model="contextForm.category" style="width: 100%">
            <el-option
              v-for="cat in categories"
              :key="cat.id"
              :label="cat.name"
              :value="cat.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="要点名称" required>
          <el-input v-model="contextForm.item" placeholder="简要描述该要点" />
        </el-form-item>
        <el-form-item label="详细说明" required>
          <el-input
            v-model="contextForm.description"
            type="textarea"
            :rows="4"
            placeholder="详细描述该要点的具体内容和注意事项"
          />
        </el-form-item>
        <el-form-item label="重要程度">
          <el-select v-model="contextForm.priority" style="width: 100%">
            <el-option label="高" value="high" />
            <el-option label="中" value="medium" />
            <el-option label="低" value="low" />
          </el-select>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showAddContextDialog = false">取消</el-button>
        <el-button type="primary" @click="saveContext" :loading="savingContext">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus,
  Search,
  View,
  Edit,
  Delete,
  ArrowLeft,
  Briefcase
} from '@element-plus/icons-vue'
import api from '@/api'

// ==================== 状态 ====================

// 业务条线列表
const businessLines = ref([])
const loading = ref(false)
const searchKeyword = ref('')
const filterLanguage = ref('')

// 选中的业务条线
const selectedLine = ref(null)

// 背景信息
const contexts = ref([])
const loadingContexts = ref(false)
const contextSearch = ref('')
const filterCategory = ref('')
const filterPriority = ref('')

// 分类列表
const categories = ref([])

// 对话框状态
const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const showAddContextDialog = ref(false)

// 表单
const lineForm = ref({
  name: '',
  description: '',
  industry: '',
  language: 'zh-CN'
})

const contextForm = ref({
  category: 'core_focus',
  item: '',
  description: '',
  priority: 'medium'
})

// 编辑状态
const editingLineId = ref(null)
const editingContext = ref(null)
const saving = ref(false)
const savingContext = ref(false)

// ==================== 计算属性 ====================

const filteredLines = computed(() => {
  return businessLines.value.filter(line => {
    const matchKeyword = !searchKeyword.value ||
      line.name.toLowerCase().includes(searchKeyword.value.toLowerCase()) ||
      (line.description && line.description.toLowerCase().includes(searchKeyword.value.toLowerCase()))
    return matchKeyword
  })
})

const filteredContexts = computed(() => {
  return contexts.value.filter(ctx => {
    const matchKeyword = !contextSearch.value ||
      ctx.item.toLowerCase().includes(contextSearch.value.toLowerCase()) ||
      ctx.description.toLowerCase().includes(contextSearch.value.toLowerCase())
    const matchCategory = !filterCategory.value || ctx.category === filterCategory.value
    const matchPriority = !filterPriority.value || ctx.priority === filterPriority.value
    return matchKeyword && matchCategory && matchPriority
  })
})

const contextCategories = computed(() => {
  const cats = new Set(contexts.value.map(c => c.category))
  return Array.from(cats)
})

// ==================== 方法 ====================

// 加载业务条线列表
async function loadBusinessLines() {
  loading.value = true
  try {
    const params = { include_preset: true }
    if (filterLanguage.value) {
      params.language = filterLanguage.value
    }
    const response = await api.getBusinessLines(params)
    businessLines.value = response.data
  } catch (error) {
    ElMessage.error('加载业务条线失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

// 加载分类列表
async function loadCategories() {
  try {
    const response = await api.getBusinessCategories()
    categories.value = response.data
  } catch (error) {
    console.error('加载分类失败:', error)
    // 使用默认分类
    categories.value = [
      { id: 'core_focus', name: '核心关注点' },
      { id: 'typical_risks', name: '典型风险' },
      { id: 'compliance', name: '合规要求' },
      { id: 'business_practices', name: '业务惯例' },
      { id: 'negotiation_priorities', name: '谈判要点' }
    ]
  }
}

// 打开业务条线详情
async function openLine(line) {
  selectedLine.value = line
  loadingContexts.value = true
  try {
    const response = await api.getBusinessLine(line.id)
    selectedLine.value = response.data
    contexts.value = response.data.contexts || []
  } catch (error) {
    ElMessage.error('加载业务条线详情失败: ' + error.message)
  } finally {
    loadingContexts.value = false
  }
}

// 返回列表
function backToList() {
  selectedLine.value = null
  contexts.value = []
  contextSearch.value = ''
  filterCategory.value = ''
  filterPriority.value = ''
}

// 创建业务条线
async function createLine() {
  if (!lineForm.value.name) {
    ElMessage.warning('请输入业务条线名称')
    return
  }

  saving.value = true
  try {
    await api.createBusinessLine(lineForm.value)
    ElMessage.success('创建成功')
    showCreateDialog.value = false
    resetLineForm()
    loadBusinessLines()
  } catch (error) {
    ElMessage.error('创建失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

// 编辑业务条线信息
function editLineInfo(line) {
  editingLineId.value = line.id
  lineForm.value = {
    name: line.name,
    description: line.description || '',
    industry: line.industry || '',
    language: line.language || 'zh-CN'
  }
  showEditDialog.value = true
}

// 更新业务条线
async function updateLine() {
  if (!lineForm.value.name) {
    ElMessage.warning('请输入业务条线名称')
    return
  }

  saving.value = true
  try {
    await api.updateBusinessLine(editingLineId.value, {
      name: lineForm.value.name,
      description: lineForm.value.description,
      industry: lineForm.value.industry
    })
    ElMessage.success('保存成功')
    showEditDialog.value = false

    // 刷新数据
    loadBusinessLines()
    if (selectedLine.value && selectedLine.value.id === editingLineId.value) {
      selectedLine.value.name = lineForm.value.name
      selectedLine.value.description = lineForm.value.description
      selectedLine.value.industry = lineForm.value.industry
    }
    editingLineId.value = null
  } catch (error) {
    ElMessage.error('保存失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

// 删除业务条线
async function deleteLine(line) {
  try {
    await ElMessageBox.confirm(
      `确定要删除业务条线「${line.name}」吗？这将同时删除所有相关的背景信息。`,
      '确认删除',
      { type: 'warning' }
    )

    await api.deleteBusinessLine(line.id)
    ElMessage.success('删除成功')
    loadBusinessLines()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + error.message)
    }
  }
}

// 重置业务条线表单
function resetLineForm() {
  lineForm.value = {
    name: '',
    description: '',
    industry: '',
    language: 'zh-CN'
  }
  editingLineId.value = null
}

// 编辑背景信息
function editContext(ctx) {
  editingContext.value = ctx
  contextForm.value = {
    category: ctx.category,
    item: ctx.item,
    description: ctx.description,
    priority: ctx.priority
  }
  showAddContextDialog.value = true
}

// 保存背景信息
async function saveContext() {
  if (!contextForm.value.item || !contextForm.value.description) {
    ElMessage.warning('请填写必填字段')
    return
  }

  savingContext.value = true
  try {
    if (editingContext.value) {
      // 更新
      await api.updateBusinessContext(editingContext.value.id, contextForm.value)
      ElMessage.success('更新成功')
    } else {
      // 创建
      await api.addBusinessContext(selectedLine.value.id, contextForm.value)
      ElMessage.success('添加成功')
    }

    showAddContextDialog.value = false
    resetContextForm()

    // 重新加载
    const response = await api.getBusinessLine(selectedLine.value.id)
    contexts.value = response.data.contexts || []
    selectedLine.value.context_count = contexts.value.length
  } catch (error) {
    ElMessage.error('保存失败: ' + error.message)
  } finally {
    savingContext.value = false
  }
}

// 删除背景信息
async function deleteContext(ctx) {
  try {
    await ElMessageBox.confirm(
      `确定要删除「${ctx.item}」吗？`,
      '确认删除',
      { type: 'warning' }
    )

    await api.deleteBusinessContext(ctx.id)
    ElMessage.success('删除成功')

    // 重新加载
    const response = await api.getBusinessLine(selectedLine.value.id)
    contexts.value = response.data.contexts || []
    selectedLine.value.context_count = contexts.value.length
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + error.message)
    }
  }
}

// 重置背景信息表单
function resetContextForm() {
  contextForm.value = {
    category: 'core_focus',
    item: '',
    description: '',
    priority: 'medium'
  }
  editingContext.value = null
}

// 辅助方法
function getCategoryName(categoryId) {
  const cat = categories.value.find(c => c.id === categoryId)
  return cat ? cat.name : categoryId
}

function getCategoryTagType(category) {
  const types = {
    core_focus: 'primary',
    typical_risks: 'danger',
    compliance: 'warning',
    business_practices: 'info',
    negotiation_priorities: 'success'
  }
  return types[category] || ''
}

function getPriorityTagType(priority) {
  const types = {
    high: 'danger',
    medium: 'warning',
    low: 'info'
  }
  return types[priority] || ''
}

function getPriorityLabel(priority) {
  const labels = {
    high: '高',
    medium: '中',
    low: '低'
  }
  return labels[priority] || priority
}

// ==================== 生命周期 ====================

onMounted(() => {
  loadBusinessLines()
  loadCategories()
})
</script>

<style scoped>
.business-view {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.header-left h1 {
  margin: 0 0 8px 0;
  font-size: 24px;
  font-weight: 600;
}

.subtitle {
  margin: 0;
  color: #909399;
  font-size: 14px;
}

.filter-card {
  margin-bottom: 16px;
}

.filter-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.lines-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.line-card {
  background: white;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  transition: all 0.2s;
}

.line-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 12px rgba(64, 158, 255, 0.1);
}

.line-card-main {
  display: flex;
  gap: 16px;
  flex: 1;
  cursor: pointer;
}

.line-icon {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.line-info {
  flex: 1;
  min-width: 0;
}

.line-name {
  font-size: 16px;
  font-weight: 500;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.line-desc {
  color: #909399;
  font-size: 13px;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.line-meta {
  font-size: 12px;
  color: #909399;
}

.meta-sep {
  margin: 0 8px;
  color: #dcdfe6;
}

.line-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

/* 详情页样式 */
.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.detail-title {
  flex: 1;
}

.detail-title h2 {
  margin: 0 0 8px 0;
  font-size: 20px;
}

.detail-tags {
  display: flex;
  gap: 8px;
}

.line-info-card {
  margin-bottom: 16px;
}

.info-grid {
  display: flex;
  gap: 32px;
}

.info-block {
  flex: 1;
}

.info-block.stats {
  flex: 0 0 auto;
  display: flex;
  gap: 24px;
}

.info-block-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.info-block-value {
  font-size: 14px;
  color: #303133;
}

.stat-box {
  text-align: center;
  padding: 8px 16px;
  background: #f5f7fa;
  border-radius: 8px;
}

.stat-number {
  font-size: 24px;
  font-weight: 600;
  color: #409eff;
}

.stat-text {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.table-card {
  margin-top: 16px;
}

.table-footer {
  padding: 12px 0 0;
  font-size: 13px;
  color: #909399;
}
</style>
