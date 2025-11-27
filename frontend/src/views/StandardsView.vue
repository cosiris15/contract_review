<template>
  <div class="standards-view">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <h1>审核标准管理</h1>
        <p class="subtitle">管理和维护审核标准库，支持导入、编辑、删除标准</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="showImportDialog = true">
          <el-icon><Upload /></el-icon>
          上传标准
        </el-button>
        <el-button @click="handleExport">
          <el-icon><Download /></el-icon>
          导出
        </el-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-row" v-if="stats">
      <el-card class="stat-card">
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-label">标准总数</div>
      </el-card>
      <el-card class="stat-card">
        <div class="stat-value high">{{ stats.by_risk_level?.high || 0 }}</div>
        <div class="stat-label">高风险</div>
      </el-card>
      <el-card class="stat-card">
        <div class="stat-value medium">{{ stats.by_risk_level?.medium || 0 }}</div>
        <div class="stat-label">中风险</div>
      </el-card>
      <el-card class="stat-card">
        <div class="stat-value low">{{ stats.by_risk_level?.low || 0 }}</div>
        <div class="stat-label">低风险</div>
      </el-card>
    </div>

    <!-- 筛选和搜索 -->
    <el-card class="filter-card">
      <div class="filter-row">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索标准..."
          clearable
          style="width: 300px"
          @input="handleSearch"
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
          @change="loadStandards"
        >
          <el-option
            v-for="cat in categories"
            :key="cat"
            :label="cat"
            :value="cat"
          />
        </el-select>

        <el-select
          v-model="filterRiskLevel"
          placeholder="风险等级"
          clearable
          style="width: 150px"
          @change="loadStandards"
        >
          <el-option label="高" value="high" />
          <el-option label="中" value="medium" />
          <el-option label="低" value="low" />
        </el-select>

        <el-select
          v-model="filterMaterialType"
          placeholder="适用类型"
          clearable
          style="width: 150px"
          @change="loadStandards"
        >
          <el-option label="合同" value="contract" />
          <el-option label="营销材料" value="marketing" />
        </el-select>

        <el-button type="primary" text @click="showAddDialog = true">
          <el-icon><Plus /></el-icon>
          手动添加
        </el-button>
      </div>
    </el-card>

    <!-- 标准列表表格 -->
    <el-card class="table-card">
      <el-table
        :data="standards"
        v-loading="loading"
        stripe
        style="width: 100%"
      >
        <el-table-column prop="category" label="分类" width="120" />
        <el-table-column prop="item" label="审核要点" min-width="180" />
        <el-table-column prop="description" label="说明" min-width="250" show-overflow-tooltip />
        <el-table-column label="风险等级" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="getRiskTagType(row.risk_level)" size="small">
              {{ getRiskLabel(row.risk_level) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="适用类型" width="120">
          <template #default="{ row }">
            <span>{{ formatApplicableTo(row.applicable_to) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="usage_instruction" label="适用说明" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.usage_instruction">{{ row.usage_instruction }}</span>
            <el-button
              v-else
              type="primary"
              text
              size="small"
              @click="generateUsageInstruction(row)"
              :loading="generatingIds.includes(row.id)"
            >
              生成
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" text size="small" @click="editStandard(row)">
              编辑
            </el-button>
            <el-button type="danger" text size="small" @click="deleteStandard(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <span>共 {{ standards.length }} 条标准</span>
      </div>
    </el-card>

    <!-- 导入对话框 -->
    <el-dialog
      v-model="showImportDialog"
      title="上传审核标准"
      width="700px"
      @close="resetImportDialog"
    >
      <div v-if="!previewStandards.length">
        <el-upload
          ref="uploadRef"
          drag
          :auto-upload="false"
          :on-change="handleFileChange"
          accept=".xlsx,.xls,.csv,.docx,.md,.txt"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">
            拖拽文件到此处，或 <em>点击上传</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              支持 Excel (.xlsx/.xls)、CSV、Word (.docx)、Markdown (.md)、文本 (.txt) 格式
            </div>
          </template>
        </el-upload>
      </div>

      <div v-else>
        <el-alert
          type="success"
          :closable="false"
          style="margin-bottom: 16px"
        >
          解析成功，共 {{ previewStandards.length }} 条标准
        </el-alert>

        <el-table :data="previewStandards" max-height="400" size="small">
          <el-table-column prop="category" label="分类" width="100" />
          <el-table-column prop="item" label="审核要点" width="150" />
          <el-table-column prop="description" label="说明" show-overflow-tooltip />
          <el-table-column label="风险" width="60">
            <template #default="{ row }">
              {{ getRiskLabel(row.risk_level) }}
            </template>
          </el-table-column>
        </el-table>

        <div style="margin-top: 16px">
          <el-checkbox v-model="replaceExisting">
            替换现有标准库（清空后导入）
          </el-checkbox>
        </div>
      </div>

      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
        <el-button
          v-if="!previewStandards.length"
          type="primary"
          @click="previewFile"
          :loading="previewing"
          :disabled="!selectedFile"
        >
          预览
        </el-button>
        <el-button
          v-else
          type="primary"
          @click="saveToLibrary"
          :loading="saving"
        >
          确认入库
        </el-button>
      </template>
    </el-dialog>

    <!-- 添加标准对话框（手动添加） -->
    <el-dialog
      v-model="showAddDialog"
      title="添加标准"
      width="600px"
      @close="resetEditDialog"
    >
      <el-form :model="standardForm" label-width="100px">
        <el-form-item label="分类" required>
          <el-input v-model="standardForm.category" placeholder="如：主体资格、权利义务" />
        </el-form-item>
        <el-form-item label="审核要点" required>
          <el-input v-model="standardForm.item" placeholder="简要描述审核要点" />
        </el-form-item>
        <el-form-item label="详细说明" required>
          <el-input
            v-model="standardForm.description"
            type="textarea"
            :rows="3"
            placeholder="详细的审核说明"
          />
        </el-form-item>
        <el-form-item label="风险等级">
          <el-select v-model="standardForm.risk_level" style="width: 100%">
            <el-option label="高" value="high" />
            <el-option label="中" value="medium" />
            <el-option label="低" value="low" />
          </el-select>
        </el-form-item>
        <el-form-item label="适用类型">
          <el-checkbox-group v-model="standardForm.applicable_to">
            <el-checkbox label="contract">合同</el-checkbox>
            <el-checkbox label="marketing">营销材料</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="适用说明">
          <el-input
            v-model="standardForm.usage_instruction"
            type="textarea"
            :rows="2"
            placeholder="可选，说明何时使用该标准"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="saveStandard" :loading="saving">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- AI 辅助编辑对话框 -->
    <el-dialog
      v-model="showEditDialog"
      title="编辑标准"
      width="800px"
      @close="resetAIEditDialog"
    >
      <div class="ai-edit-container">
        <!-- 当前标准展示 -->
        <div class="current-standard">
          <div class="section-title">当前标准</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="分类">{{ editingStandard?.category }}</el-descriptions-item>
            <el-descriptions-item label="风险等级">
              <el-tag :type="getRiskTagType(editingStandard?.risk_level)" size="small">
                {{ getRiskLabel(editingStandard?.risk_level) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="审核要点" :span="2">{{ editingStandard?.item }}</el-descriptions-item>
            <el-descriptions-item label="详细说明" :span="2">{{ editingStandard?.description }}</el-descriptions-item>
            <el-descriptions-item label="适用类型">{{ formatApplicableTo(editingStandard?.applicable_to) }}</el-descriptions-item>
            <el-descriptions-item label="适用说明">{{ editingStandard?.usage_instruction || '（无）' }}</el-descriptions-item>
          </el-descriptions>
        </div>

        <!-- AI 修改输入区 -->
        <div class="ai-input-section">
          <div class="section-title">
            <el-icon><MagicStick /></el-icon>
            告诉 AI 如何修改
          </div>
          <el-input
            v-model="aiInstruction"
            type="textarea"
            :rows="3"
            placeholder="用自然语言描述您想要的修改，例如：&#10;• 把风险等级提高到高&#10;• 在说明中增加关于违约金比例的要求&#10;• 这个标准只适用于采购合同&#10;• 让描述更加具体，包含具体的检查步骤"
          />
          <div class="ai-input-actions">
            <el-button
              type="primary"
              @click="handleAIModify"
              :loading="aiModifying"
              :disabled="!aiInstruction.trim()"
            >
              <el-icon><MagicStick /></el-icon>
              生成修改建议
            </el-button>
          </div>
        </div>

        <!-- AI 修改结果预览 -->
        <div class="ai-result-section" v-if="aiModifiedResult">
          <div class="section-title">
            <el-icon><Check /></el-icon>
            AI 修改建议
            <el-tag type="info" size="small" style="margin-left: 8px;">
              {{ aiModifiedResult.modification_summary }}
            </el-tag>
          </div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="分类">
              <span :class="{ 'changed': aiModifiedResult.category !== editingStandard?.category }">
                {{ aiModifiedResult.category }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="风险等级">
              <el-tag
                :type="getRiskTagType(aiModifiedResult.risk_level)"
                size="small"
                :class="{ 'changed': aiModifiedResult.risk_level !== editingStandard?.risk_level }"
              >
                {{ getRiskLabel(aiModifiedResult.risk_level) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="审核要点" :span="2">
              <span :class="{ 'changed': aiModifiedResult.item !== editingStandard?.item }">
                {{ aiModifiedResult.item }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="详细说明" :span="2">
              <span :class="{ 'changed': aiModifiedResult.description !== editingStandard?.description }">
                {{ aiModifiedResult.description }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="适用类型">
              <span :class="{ 'changed': formatApplicableTo(aiModifiedResult.applicable_to) !== formatApplicableTo(editingStandard?.applicable_to) }">
                {{ formatApplicableTo(aiModifiedResult.applicable_to) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="适用说明">
              <span :class="{ 'changed': aiModifiedResult.usage_instruction !== editingStandard?.usage_instruction }">
                {{ aiModifiedResult.usage_instruction || '（无）' }}
              </span>
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </div>

      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button
          type="primary"
          @click="confirmAIModification"
          :loading="saving"
          :disabled="!aiModifiedResult"
        >
          确认修改
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Upload, Download, Search, Plus, UploadFilled, MagicStick, Check
} from '@element-plus/icons-vue'
import api from '@/api'

// 数据状态
const loading = ref(false)
const standards = ref([])
const stats = ref(null)
const categories = ref([])

// 筛选状态
const searchKeyword = ref('')
const filterCategory = ref('')
const filterRiskLevel = ref('')
const filterMaterialType = ref('')

// 导入对话框状态
const showImportDialog = ref(false)
const selectedFile = ref(null)
const previewStandards = ref([])
const previewing = ref(false)
const saving = ref(false)
const replaceExisting = ref(false)

// 添加对话框状态（手动添加）
const showAddDialog = ref(false)
const standardForm = reactive({
  category: '',
  item: '',
  description: '',
  risk_level: 'medium',
  applicable_to: ['contract', 'marketing'],
  usage_instruction: '',
})

// AI 编辑对话框状态
const showEditDialog = ref(false)
const editingStandard = ref(null)
const aiInstruction = ref('')
const aiModifying = ref(false)
const aiModifiedResult = ref(null)

// 生成适用说明状态
const generatingIds = ref([])

// 加载标准列表
async function loadStandards() {
  loading.value = true
  try {
    const params = {}
    if (filterCategory.value) params.category = filterCategory.value
    if (filterMaterialType.value) params.material_type = filterMaterialType.value
    if (searchKeyword.value) params.keyword = searchKeyword.value

    const response = await api.getLibraryStandards(params)
    standards.value = response.data

    // 如果有风险等级筛选，前端过滤
    if (filterRiskLevel.value) {
      standards.value = standards.value.filter(
        s => s.risk_level === filterRiskLevel.value
      )
    }
  } catch (error) {
    ElMessage.error('加载标准失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

// 加载统计信息
async function loadStats() {
  try {
    const response = await api.getLibraryStats()
    stats.value = response.data
  } catch (error) {
    console.error('加载统计失败:', error)
  }
}

// 加载分类列表
async function loadCategories() {
  try {
    const response = await api.getLibraryCategories()
    categories.value = response.data.categories
  } catch (error) {
    console.error('加载分类失败:', error)
  }
}

// 搜索处理（防抖）
let searchTimer = null
function handleSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    loadStandards()
  }, 300)
}

// 风险等级标签
function getRiskTagType(level) {
  return { high: 'danger', medium: 'warning', low: 'success' }[level] || 'info'
}

function getRiskLabel(level) {
  return { high: '高', medium: '中', low: '低' }[level] || level
}

// 格式化适用类型
function formatApplicableTo(types) {
  if (!types) return ''
  return types.map(t => t === 'contract' ? '合同' : '营销').join('、')
}

// 文件选择处理
function handleFileChange(file) {
  selectedFile.value = file.raw
  previewStandards.value = []
}

// 预览文件
async function previewFile() {
  if (!selectedFile.value) return

  previewing.value = true
  try {
    const response = await api.previewStandards(selectedFile.value)
    previewStandards.value = response.data.standards
    ElMessage.success(`解析成功，共 ${response.data.total_count} 条标准`)
  } catch (error) {
    ElMessage.error('解析失败: ' + error.message)
  } finally {
    previewing.value = false
  }
}

// 保存到标准库
async function saveToLibrary() {
  if (!previewStandards.value.length) return

  saving.value = true
  try {
    const response = await api.saveToLibrary({
      standards: previewStandards.value,
      replace: replaceExisting.value,
    })
    ElMessage.success(response.data.message)
    showImportDialog.value = false
    resetImportDialog()
    loadStandards()
    loadStats()
    loadCategories()
  } catch (error) {
    ElMessage.error('保存失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

// 重置导入对话框
function resetImportDialog() {
  selectedFile.value = null
  previewStandards.value = []
  replaceExisting.value = false
}

// 编辑标准 - 打开 AI 编辑对话框
function editStandard(row) {
  editingStandard.value = row
  aiInstruction.value = ''
  aiModifiedResult.value = null
  showEditDialog.value = true
}

// 保存标准（添加或更新）
async function saveStandard() {
  if (!standardForm.category || !standardForm.item || !standardForm.description) {
    ElMessage.warning('请填写必填字段')
    return
  }

  saving.value = true
  try {
    if (editingStandard.value) {
      await api.updateLibraryStandard(editingStandard.value.id, standardForm)
      ElMessage.success('更新成功')
    } else {
      await api.createLibraryStandard(standardForm)
      ElMessage.success('添加成功')
    }
    showAddDialog.value = false
    resetEditDialog()
    loadStandards()
    loadStats()
    loadCategories()
  } catch (error) {
    ElMessage.error('保存失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

// 删除标准
async function deleteStandard(row) {
  try {
    await ElMessageBox.confirm(
      `确定要删除标准「${row.item}」吗？`,
      '确认删除',
      { type: 'warning' }
    )
    await api.deleteLibraryStandard(row.id)
    ElMessage.success('删除成功')
    loadStandards()
    loadStats()
    loadCategories()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + error.message)
    }
  }
}

// 重置手动添加对话框
function resetEditDialog() {
  Object.assign(standardForm, {
    category: '',
    item: '',
    description: '',
    risk_level: 'medium',
    applicable_to: ['contract', 'marketing'],
    usage_instruction: '',
  })
}

// 重置 AI 编辑对话框
function resetAIEditDialog() {
  editingStandard.value = null
  aiInstruction.value = ''
  aiModifiedResult.value = null
}

// AI 辅助修改
async function handleAIModify() {
  if (!aiInstruction.value.trim() || !editingStandard.value) return

  aiModifying.value = true
  try {
    const response = await api.aiModifyStandard(editingStandard.value.id, aiInstruction.value)
    aiModifiedResult.value = response.data.modified_standard
    ElMessage.success('AI 已生成修改建议，请确认')
  } catch (error) {
    ElMessage.error('AI 修改失败: ' + error.message)
  } finally {
    aiModifying.value = false
  }
}

// 确认 AI 修改
async function confirmAIModification() {
  if (!aiModifiedResult.value || !editingStandard.value) return

  saving.value = true
  try {
    await api.updateLibraryStandard(editingStandard.value.id, {
      category: aiModifiedResult.value.category,
      item: aiModifiedResult.value.item,
      description: aiModifiedResult.value.description,
      risk_level: aiModifiedResult.value.risk_level,
      applicable_to: aiModifiedResult.value.applicable_to,
      usage_instruction: aiModifiedResult.value.usage_instruction,
    })
    ElMessage.success('标准已更新')
    showEditDialog.value = false
    resetAIEditDialog()
    loadStandards()
    loadStats()
    loadCategories()
  } catch (error) {
    ElMessage.error('保存失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

// 生成适用说明
async function generateUsageInstruction(row) {
  generatingIds.value.push(row.id)
  try {
    const response = await api.generateUsageInstruction({
      standard_ids: [row.id],
    })
    if (response.data.success_count > 0) {
      row.usage_instruction = response.data.results[0].usage_instruction
      ElMessage.success('生成成功')
    } else {
      ElMessage.error('生成失败: ' + response.data.errors[0])
    }
  } catch (error) {
    ElMessage.error('生成失败: ' + error.message)
  } finally {
    generatingIds.value = generatingIds.value.filter(id => id !== row.id)
  }
}

// 导出标准库
async function handleExport() {
  try {
    window.open(api.exportLibrary('csv'), '_blank')
  } catch (error) {
    ElMessage.error('导出失败: ' + error.message)
  }
}

// 初始化
onMounted(() => {
  loadStandards()
  loadStats()
  loadCategories()
})
</script>

<style scoped>
.standards-view {
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
  color: #303133;
}

.subtitle {
  margin: 0;
  color: #909399;
  font-size: 14px;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  text-align: center;
  padding: 16px;
}

.stat-value {
  font-size: 32px;
  font-weight: bold;
  color: #409eff;
}

.stat-value.high {
  color: #f56c6c;
}

.stat-value.medium {
  color: #e6a23c;
}

.stat-value.low {
  color: #67c23a;
}

.stat-label {
  margin-top: 8px;
  color: #909399;
  font-size: 14px;
}

.filter-card {
  margin-bottom: 16px;
}

.filter-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
}

.table-card {
  margin-bottom: 24px;
}

.table-footer {
  margin-top: 16px;
  text-align: right;
  color: #909399;
  font-size: 14px;
}

/* AI 编辑对话框样式 */
.ai-edit-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.current-standard {
  background: #f5f7fa;
  padding: 16px;
  border-radius: 8px;
}

.ai-input-section {
  padding: 16px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
}

.ai-input-actions {
  margin-top: 12px;
  text-align: right;
}

.ai-result-section {
  padding: 16px;
  border: 2px solid #67c23a;
  border-radius: 8px;
  background: #f0f9eb;
}

.ai-result-section .changed {
  background: #fef0f0;
  color: #f56c6c;
  padding: 2px 4px;
  border-radius: 4px;
  font-weight: 500;
}
</style>
