<template>
  <div class="review-view">
    <!-- 全局操作状态提示 -->
    <transition name="fade">
      <div v-if="store.isOperationInProgress" class="operation-status-bar">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>{{ store.currentOperationMessage }}</span>
      </div>
    </transition>

    <!-- 错误提示 -->
    <el-alert
      v-if="store.operationError && !store.isOperationInProgress"
      type="error"
      :title="store.operationError.message"
      :description="store.operationError.detail"
      show-icon
      closable
      class="error-alert"
      @close="clearError"
    />

    <el-row :gutter="24">
      <!-- 左侧面板：配置区 -->
      <el-col :span="10">
        <el-card class="config-card">
          <template #header>
            <div class="card-header">
              <span>审阅配置</span>
            </div>
          </template>

          <!-- 步骤 1: 基本信息 -->
          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            label-position="top"
          >
            <el-form-item label="任务名称" prop="name">
              <el-input
                v-model="form.name"
                placeholder="例如：XX合同审阅"
                :disabled="!!taskId"
              />
            </el-form-item>

            <el-form-item label="我方身份" prop="our_party">
              <el-input
                v-model="form.our_party"
                placeholder="例如：XX科技有限公司"
                :disabled="!!taskId"
              />
            </el-form-item>

            <el-form-item label="材料类型" prop="material_type">
              <el-radio-group v-model="form.material_type" :disabled="!!taskId">
                <el-radio value="contract">合同</el-radio>
                <el-radio value="marketing">营销材料</el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="审阅语言" prop="language">
              <el-radio-group v-model="form.language" :disabled="!!taskId">
                <el-radio value="zh-CN">中文（中国法律体系）</el-radio>
                <el-radio value="en">English (Common Law)</el-radio>
              </el-radio-group>
              <div v-if="detectedLanguage" class="language-detection-hint">
                <el-icon><InfoFilled /></el-icon>
                自动检测：{{ detectedLanguage === 'zh-CN' ? '中文' : 'English' }}
                (置信度 {{ Math.round(detectedConfidence * 100) }}%)
              </div>
            </el-form-item>
          </el-form>

          <el-divider />

          <!-- 步骤 2: 上传文档 -->
          <div class="upload-section">
            <h4>
              <el-icon><Document /></el-icon>
              上传待审阅文档
            </h4>
            <el-upload
              class="upload-box"
              drag
              :auto-upload="false"
              :show-file-list="false"
              :on-change="handleDocumentChange"
              accept=".md,.txt,.docx,.pdf"
            >
              <div v-if="currentTask?.document_filename" class="uploaded-file">
                <el-icon :size="40" color="#67c23a"><DocumentChecked /></el-icon>
                <span>{{ currentTask.document_filename }}</span>
                <el-button type="primary" text size="small">重新上传</el-button>
              </div>
              <div v-else class="upload-placeholder">
                <el-icon :size="40"><UploadFilled /></el-icon>
                <p>拖拽文件到此处或点击上传</p>
                <span>支持 .md, .txt, .docx, .pdf 格式</span>
              </div>
            </el-upload>
          </div>

          <el-divider />

          <!-- 步骤 3: 审核标准选择 -->
          <div class="standard-section">
            <h4>
              <el-icon><List /></el-icon>
              审核标准
            </h4>

            <!-- 标准选择入口 -->
            <div class="standard-selection-entry">
              <el-button type="primary" @click="openStandardSelector">
                <el-icon><Collection /></el-icon>
                选择审核标准
              </el-button>
              <el-dropdown trigger="click" @command="handleNewStandardInReview" style="margin-left: 12px;">
                <el-button>
                  <el-icon><Plus /></el-icon>
                  新建标准
                  <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="upload">
                      <el-icon><UploadFilled /></el-icon>
                      上传新标准
                    </el-dropdown-item>
                    <el-dropdown-item command="ai">
                      <el-icon><MagicStick /></el-icon>
                      AI辅助制作
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>

            <!-- 隐藏的上传组件 -->
            <el-upload
              ref="standardUploadRef"
              :auto-upload="false"
              :show-file-list="false"
              :on-change="handleStandardUpload"
              accept=".xlsx,.xls,.csv,.docx,.md,.txt"
              style="display: none;"
            />

            <!-- 已选标准显示 -->
            <div v-if="selectedStandards.length > 0" class="selected-standards-section">
              <div class="selected-header">
                <span class="selected-label">已选标准</span>
                <el-tag type="success" size="small">{{ selectedStandards.length }} 条</el-tag>
                <el-button text type="primary" size="small" @click="showStandardPreview = true">
                  查看详情
                </el-button>
              </div>
              <div class="selected-tags">
                <el-tag
                  v-for="s in selectedStandards.slice(0, 6)"
                  :key="s.id || s.item"
                  size="small"
                  style="margin: 2px"
                >
                  {{ s.item }}
                </el-tag>
                <span v-if="selectedStandards.length > 6" class="more-count">
                  +{{ selectedStandards.length - 6 }} 条
                </span>
              </div>
            </div>

            <!-- 特殊要求输入（可选） -->
            <div class="special-requirements">
              <div class="special-header" @click="showSpecialInput = !showSpecialInput">
                <el-icon><Edit /></el-icon>
                <span>本次特殊要求</span>
                <el-tag size="small" type="info">可选</el-tag>
                <el-icon class="expand-icon" :class="{ expanded: showSpecialInput }">
                  <ArrowDown />
                </el-icon>
              </div>
              <el-collapse-transition>
                <div v-show="showSpecialInput" class="special-content">
                  <el-input
                    v-model="specialRequirements"
                    type="textarea"
                    :rows="3"
                    placeholder="输入本次项目的特殊审核要求，例如：&#10;• 本项目为政府采购，需特别关注合规要求&#10;• 我方为乙方，重点关注付款条款和违约责任&#10;• 涉及数据跨境，需审核数据安全条款"
                  />
                  <div class="special-actions">
                    <el-button
                      type="primary"
                      size="small"
                      :loading="merging"
                      :disabled="!specialRequirements.trim() || !selectedStandards.length"
                      @click="mergeSpecialRequirements"
                    >
                      <el-icon><MagicStick /></el-icon>
                      整合到本次审核
                    </el-button>
                    <span class="special-tip">AI 将根据特殊要求调整本次审核使用的标准（不影响标准库）</span>
                  </div>
                </div>
              </el-collapse-transition>
            </div>

            <!-- 当前应用的标准状态 -->
            <div v-if="currentTask?.standard_filename" class="applied-standard">
              <el-icon color="#67c23a"><CircleCheck /></el-icon>
              <span>已应用: {{ currentTask.standard_filename }}</span>
              <el-button text type="primary" size="small" @click="reselect">重新选择</el-button>
            </div>
          </div>

          <!-- 标准推荐对话框 -->
          <el-dialog
            v-model="showRecommendDialog"
            title="智能推荐标准"
            width="700px"
          >
            <div v-if="recommendations.length">
              <el-alert type="info" :closable="false" style="margin-bottom: 16px">
                根据您上传的文档，推荐以下审核标准：
              </el-alert>

              <div class="recommend-list">
                <div
                  v-for="rec in recommendations"
                  :key="rec.standard_id"
                  class="recommend-item"
                  :class="{ selected: isStandardSelected(rec.standard_id) }"
                  @click="toggleStandard(rec)"
                >
                  <el-checkbox :model-value="isStandardSelected(rec.standard_id)" />
                  <div class="recommend-content">
                    <div class="recommend-header">
                      <span class="recommend-title">{{ rec.standard.item }}</span>
                      <el-tag size="small" :type="getRelevanceType(rec.relevance_score)">
                        相关度 {{ Math.round(rec.relevance_score * 100) }}%
                      </el-tag>
                    </div>
                    <p class="recommend-reason">{{ rec.match_reason }}</p>
                    <p class="recommend-desc">{{ rec.standard.description }}</p>
                  </div>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无推荐结果" />

            <template #footer>
              <el-button @click="showRecommendDialog = false">取消</el-button>
              <el-button type="primary" @click="confirmRecommendation">
                确认选择 ({{ selectedLibraryStandards.length }})
              </el-button>
            </template>
          </el-dialog>

          <!-- 标准集合选择对话框 -->
          <el-dialog
            v-model="showLibrarySelector"
            title="选择审核标准"
            width="800px"
          >
            <div class="library-selector">
              <!-- 搜索框 -->
              <el-input
                v-model="collectionSearch"
                placeholder="搜索标准集..."
                clearable
                style="margin-bottom: 16px"
              >
                <template #prefix>
                  <el-icon><Search /></el-icon>
                </template>
              </el-input>

              <!-- 标准集合列表 -->
              <div class="collection-list">
                <div
                  v-for="collection in filteredCollections"
                  :key="collection.id"
                  class="collection-card-dialog"
                  :class="{ selected: selectedCollection?.id === collection.id }"
                  @click="selectCollectionInDialog(collection)"
                >
                  <div class="collection-card-header">
                    <el-icon :size="24" :color="selectedCollection?.id === collection.id ? '#409eff' : '#909399'">
                      <Folder />
                    </el-icon>
                    <div class="collection-info">
                      <span class="collection-name">{{ collection.name }}</span>
                      <span class="collection-meta">
                        <el-tag size="small" type="info">{{ collection.standard_count }} 条审核条目</el-tag>
                        <el-tag v-if="collection.is_preset" size="small" type="success">预设</el-tag>
                      </span>
                    </div>
                    <el-icon v-if="selectedCollection?.id === collection.id" class="check-icon" color="#409eff">
                      <CircleCheck />
                    </el-icon>
                  </div>
                  <p v-if="collection.description" class="collection-desc">{{ collection.description }}</p>
                </div>

                <el-empty v-if="filteredCollections.length === 0" description="暂无标准集">
                  <el-button type="primary" @click="goToStandardsManagement">
                    前往标准管理
                  </el-button>
                </el-empty>
              </div>

              <!-- 当前选择状态 -->
              <div v-if="selectedCollection" class="selection-summary">
                <el-icon><InfoFilled /></el-icon>
                <span>已选择「{{ selectedCollection.name }}」，共 {{ selectedCollection.standard_count }} 条审核条目</span>
              </div>
            </div>

            <template #footer>
              <el-button @click="showLibrarySelector = false">取消</el-button>
              <el-button type="primary" @click="confirmCollectionSelection" :disabled="!selectedCollection">
                确认选择
              </el-button>
            </template>
          </el-dialog>

          <!-- 标准预览对话框 -->
          <el-dialog
            v-model="showStandardPreview"
            title="已选审核标准"
            width="750px"
          >
            <el-table :data="selectedStandards" max-height="450">
              <el-table-column prop="category" label="分类" width="100" />
              <el-table-column prop="item" label="审核要点" width="150" />
              <el-table-column prop="description" label="详细说明" show-overflow-tooltip />
              <el-table-column label="风险" width="60" align="center">
                <template #default="{ row }">
                  <el-tag :type="getRiskTagType(row.risk_level)" size="small">
                    {{ getRiskLabel(row.risk_level) }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
            <template #footer>
              <el-button @click="showStandardPreview = false">关闭</el-button>
              <el-button type="primary" @click="applyStandards" :loading="applyingStandards">
                应用标准
              </el-button>
            </template>
          </el-dialog>

          <!-- 整合预览对话框 -->
          <el-dialog
            v-model="showMergePreview"
            title="标准整合预览"
            width="850px"
            :close-on-click-modal="false"
          >
            <div class="merge-preview">
              <!-- 整合摘要 -->
              <div class="merge-summary">
                <el-alert :title="mergeResult?.merge_notes" type="info" :closable="false" show-icon />
                <div class="summary-stats">
                  <el-tag type="success">
                    <el-icon><CirclePlus /></el-icon>
                    新增 {{ mergeResult?.summary?.added_count || 0 }} 条
                  </el-tag>
                  <el-tag type="warning">
                    <el-icon><Edit /></el-icon>
                    修改 {{ mergeResult?.summary?.modified_count || 0 }} 条
                  </el-tag>
                  <el-tag type="danger">
                    <el-icon><Remove /></el-icon>
                    删除 {{ mergeResult?.summary?.removed_count || 0 }} 条
                  </el-tag>
                  <el-tag type="info">
                    <el-icon><Check /></el-icon>
                    未变 {{ mergeResult?.summary?.unchanged_count || 0 }} 条
                  </el-tag>
                </div>
              </div>

              <!-- 标准列表 -->
              <div class="merge-standards-list">
                <div
                  v-for="(s, idx) in mergeResult?.merged_standards || []"
                  :key="idx"
                  class="merge-standard-item"
                  :class="s.change_type"
                >
                  <div class="standard-change-badge">
                    <el-tag
                      :type="getChangeTagType(s.change_type)"
                      size="small"
                    >
                      {{ getChangeLabel(s.change_type) }}
                    </el-tag>
                  </div>
                  <div class="standard-content">
                    <div class="standard-header">
                      <span class="standard-category">{{ s.category }}</span>
                      <span class="standard-item">{{ s.item }}</span>
                      <el-tag :type="getRiskTagType(s.risk_level)" size="small">
                        {{ getRiskLabel(s.risk_level) }}
                      </el-tag>
                    </div>
                    <p class="standard-desc">{{ s.description }}</p>
                    <p v-if="s.change_reason" class="change-reason">
                      <el-icon><InfoFilled /></el-icon>
                      {{ s.change_reason }}
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <template #footer>
              <el-button @click="cancelMerge">取消，保留原标准</el-button>
              <el-button type="primary" @click="applyMergedStandards">
                应用整合后的标准
              </el-button>
            </template>
          </el-dialog>

          <el-divider />

          <!-- 开始审阅按钮 -->
          <el-button
            type="primary"
            size="large"
            class="start-btn"
            :loading="store.isReviewing"
            :disabled="!canStart"
            @click="startReview"
          >
            {{ store.isReviewing ? '审阅中...' : '开始审阅' }}
          </el-button>
        </el-card>
      </el-col>

      <!-- 右侧面板：进度/结果预览 -->
      <el-col :span="14">
        <el-card class="progress-card">
          <template #header>
            <div class="card-header">
              <span>审阅进度</span>
            </div>
          </template>

          <!-- 等待状态 -->
          <div v-if="!store.isReviewing && !isCompleted" class="waiting-state">
            <el-empty description="完成配置后点击开始审阅">
              <template #image>
                <el-icon :size="80" color="#909399"><Document /></el-icon>
              </template>
            </el-empty>
          </div>

          <!-- 审阅进度 -->
          <div v-else-if="store.isReviewing" class="progress-state">
            <div class="progress-content">
              <el-progress
                type="circle"
                :percentage="store.progress.percentage"
                :width="150"
                :stroke-width="10"
              />
              <div class="progress-info">
                <h3>{{ stageText }}</h3>
                <p>{{ store.progress.message }}</p>
              </div>
            </div>
            <div class="progress-steps">
              <el-steps :active="activeStep" align-center>
                <el-step title="分析文档" />
                <el-step title="识别风险" />
                <el-step title="生成建议" />
                <el-step title="完成" />
              </el-steps>
            </div>
          </div>

          <!-- 完成状态 -->
          <div v-else-if="isCompleted" class="completed-state">
            <el-result icon="success" title="审阅完成">
              <template #sub-title>
                <p v-if="store.reviewResult">
                  发现 {{ store.reviewResult.summary.total_risks }} 个风险点，
                  生成 {{ store.reviewResult.summary.total_modifications }} 条修改建议
                </p>
              </template>
              <template #extra>
                <el-button type="primary" @click="goToResult">
                  查看完整结果
                </el-button>
              </template>
            </el-result>
          </div>

          <!-- 失败状态 -->
          <div v-else-if="isFailed" class="failed-state">
            <el-result icon="error" title="审阅失败">
              <template #sub-title>
                <p>{{ currentTask?.message || '发生未知错误' }}</p>
              </template>
              <template #extra>
                <el-button type="primary" @click="retryReview">重试</el-button>
              </template>
            </el-result>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useReviewStore } from '@/store'
import { ElMessage } from 'element-plus'
import { Loading, Search, Folder, CircleCheck, InfoFilled } from '@element-plus/icons-vue'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const store = useReviewStore()

const formRef = ref(null)
const standardUploadRef = ref(null)
const taskId = ref(route.params.taskId || null)

const form = ref({
  name: '',
  our_party: '',
  material_type: 'contract',
  language: 'zh-CN'
})

// 语言检测相关状态
const detectedLanguage = ref(null)
const detectedConfidence = ref(0)

const rules = {
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  our_party: [{ required: true, message: '请输入我方身份', trigger: 'blur' }]
}

// 标准集合相关状态
const collections = ref([])
const selectedCollection = ref(null)
const selectedStandards = ref([]) // 当前选中的标准列表（来自集合）

// 标准选择相关状态
const showLibrarySelector = ref(false)
const collectionSearch = ref('')
const applyingStandards = ref(false)
const showStandardPreview = ref(false)

// 特殊要求相关状态
const showSpecialInput = ref(false)
const specialRequirements = ref('')
const merging = ref(false)
const showMergePreview = ref(false)
const mergeResult = ref(null)

// 推荐相关
const recommending = ref(false)
const showRecommendDialog = ref(false)
const recommendations = ref([])
const selectedLibraryStandards = ref([])

const currentTask = computed(() => store.currentTask)
const isCompleted = computed(() => currentTask.value?.status === 'completed')
const isFailed = computed(() => currentTask.value?.status === 'failed')

const canStart = computed(() => {
  if (!taskId.value) return false
  return store.canStartReview
})

const stageText = computed(() => {
  const stages = {
    idle: '准备中',
    analyzing: '分析文档',
    generating: '生成建议',
    completed: '已完成'
  }
  return stages[store.progress.stage] || '处理中'
})

const activeStep = computed(() => {
  const stage = store.progress.stage
  if (stage === 'idle') return 0
  if (stage === 'analyzing') return 1
  if (stage === 'generating') return 2
  if (stage === 'completed') return 4
  return 1
})

onMounted(async () => {
  // 加载标准集合列表
  try {
    const response = await api.getCollections()
    collections.value = response.data.map(c => ({
      id: c.id,
      name: c.name,
      description: c.description,
      material_type: c.material_type,
      standard_count: c.standard_count,
      is_preset: c.is_preset,
      standards: []  // 集合列表API不返回standards，需要单独获取
    }))
  } catch (error) {
    console.error('加载标准集合失败:', error)
  }

  // 如果有 taskId，加载任务
  if (taskId.value) {
    try {
      await store.loadTask(taskId.value)
      form.value = {
        name: currentTask.value.name,
        our_party: currentTask.value.our_party,
        material_type: currentTask.value.material_type
      }

      // 如果正在审阅中，恢复轮询
      if (currentTask.value.status === 'reviewing') {
        store.isReviewing = true
        store.startPolling(taskId.value)
      }
    } catch (error) {
      ElMessage.error('加载任务失败')
      router.push('/')
    }
  }
})

// 监听路由变化
watch(() => route.params.taskId, async (newId) => {
  if (newId && newId !== taskId.value) {
    taskId.value = newId
    await store.loadTask(newId)
  }
})

async function handleDocumentChange(file) {
  // 如果还没有任务，先创建
  if (!taskId.value) {
    const valid = await formRef.value.validate().catch(() => false)
    if (!valid) {
      ElMessage.warning('请先填写基本信息')
      return
    }

    try {
      const task = await store.createTask({
        name: form.value.name,
        our_party: form.value.our_party,
        material_type: form.value.material_type,
        language: form.value.language
      })
      taskId.value = task.id
      router.replace(`/review/${task.id}`)
    } catch (error) {
      ElMessage.error('创建任务失败')
      return
    }
  }

  // 上传文档
  try {
    await store.uploadDocument(taskId.value, file.raw)
    ElMessage.success('文档上传成功')

    // 文档上传成功后，尝试检测语言
    await detectDocumentLanguage(file.raw)
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
  }
}

// 检测文档语言
async function detectDocumentLanguage(file) {
  try {
    // 读取文件文本内容
    const text = await readFileAsText(file)
    if (!text || text.length < 50) return // 文本太短则跳过检测

    // 调用语言检测API
    const result = await api.detectLanguage(text.slice(0, 5000))
    if (result.data) {
      detectedLanguage.value = result.data.detected_language
      detectedConfidence.value = result.data.confidence

      // 如果置信度足够高且当前语言与检测结果不同，自动切换
      if (result.data.confidence > 0.7 && form.value.language !== result.data.detected_language) {
        form.value.language = result.data.detected_language
        ElMessage.info(`已根据文档内容自动切换为${result.data.detected_language === 'zh-CN' ? '中文' : 'English'}审阅模式`)
      }
    }
  } catch (error) {
    console.log('语言检测失败，使用默认语言:', error)
  }
}

// 读取文件为文本
function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => resolve(e.target.result)
    reader.onerror = reject
    // 对于 docx 和 pdf 文件，只读取部分内容
    if (file.type === 'application/pdf' || file.name.endsWith('.pdf')) {
      // PDF 文件暂不支持客户端读取，跳过检测
      resolve('')
    } else if (file.name.endsWith('.docx')) {
      // docx 文件暂不支持客户端读取，跳过检测
      resolve('')
    } else {
      reader.readAsText(file)
    }
  })
}

// ==================== 标准选择相关函数 ====================

// 过滤后的集合列表
const filteredCollections = computed(() => {
  if (!collectionSearch.value) return collections.value
  const keyword = collectionSearch.value.toLowerCase()
  return collections.value.filter(c =>
    c.name.toLowerCase().includes(keyword) ||
    (c.description && c.description.toLowerCase().includes(keyword))
  )
})

// 打开标准选择对话框
function openStandardSelector() {
  // 重置对话框内的临时选择状态
  selectedCollection.value = null
  showLibrarySelector.value = true
}

// 跳转到标准管理页面
function goToStandardsManagement() {
  showLibrarySelector.value = false
  router.push({ name: 'standards' })
}

// 对话框内选择集合
async function selectCollectionInDialog(collection) {
  if (selectedCollection.value?.id === collection.id) {
    // 再次点击取消选择
    selectedCollection.value = null
  } else {
    // 如果标准列表为空，需要从API获取完整集合详情
    if (!collection.standards || collection.standards.length === 0) {
      try {
        const response = await api.getCollection(collection.id)
        collection.standards = response.data.standards || []
        collection.standard_count = collection.standards.length
      } catch (error) {
        console.error('获取集合详情失败:', error)
        ElMessage.error('获取标准详情失败')
        return
      }
    }
    selectedCollection.value = collection
  }
}

// 确认集合选择
async function confirmCollectionSelection() {
  if (!taskId.value) {
    ElMessage.warning('请先上传文档')
    return
  }

  if (!selectedCollection.value) {
    ElMessage.warning('请先选择标准集')
    return
  }

  // 设置当前选中的标准（用于显示和特殊要求整合）
  selectedStandards.value = selectedCollection.value.standards.map(s => ({
    id: s.id,
    category: s.category,
    item: s.item,
    description: s.description,
    risk_level: s.risk_level,
    applicable_to: s.applicable_to || ['contract']
  }))

  showLibrarySelector.value = false

  // 直接应用标准到任务
  await applyStandardsImmediately(selectedStandards.value)
}

// 立即应用标准到任务
async function applyStandardsImmediately(standards) {
  applyingStandards.value = true
  try {
    // 创建 CSV 内容
    const csvContent = [
      '审核分类,审核要点,详细说明,风险等级,适用材料类型',
      ...standards.map(s =>
        `"${s.category}","${s.item}","${s.description}","${s.risk_level === 'high' ? '高' : s.risk_level === 'medium' ? '中' : '低'}","${(s.applicable_to || ['contract']).join(',')}"`
      )
    ].join('\n')

    // 创建 Blob 并上传
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' })
    const fileName = selectedCollection.value
      ? `${selectedCollection.value.name}.csv`
      : 'selected_standards.csv'
    const file = new File([blob], fileName, { type: 'text/csv' })

    await store.uploadStandard(taskId.value, file)
    ElMessage.success(`已应用 ${standards.length} 条审核标准`)
  } catch (error) {
    ElMessage.error('应用标准失败: ' + error.message)
  } finally {
    applyingStandards.value = false
  }
}


// 新建标准下拉菜单命令处理
function handleNewStandardInReview(command) {
  if (command === 'upload') {
    // 触发隐藏的上传组件
    const uploadInput = standardUploadRef.value?.$el?.querySelector('input[type="file"]')
    if (uploadInput) {
      uploadInput.click()
    }
  } else if (command === 'ai') {
    // 跳转到标准管理页面的AI制作功能
    router.push({ name: 'standards', query: { action: 'ai-create' } })
  }
}

// 上传自定义标准文件
async function handleStandardUpload(file) {
  if (!taskId.value) {
    ElMessage.warning('请先上传文档')
    return
  }

  try {
    await store.uploadStandard(taskId.value, file.raw)
    selectedPresetTemplate.value = null
    selectedStandards.value = []
    ElMessage.success('审核标准上传成功')
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
  }
}

// 重新选择标准
function reselect() {
  selectedCollection.value = null
  selectedStandards.value = []
  specialRequirements.value = ''
}

async function startReview() {
  if (!taskId.value) {
    ElMessage.warning('请先完成配置')
    return
  }

  try {
    await store.startReview(taskId.value)
  } catch (error) {
    ElMessage.error(error.message || '启动审阅失败')
  }
}

function retryReview() {
  store.progress = { stage: 'idle', percentage: 0, message: '' }
  if (currentTask.value) {
    currentTask.value.status = 'created'
  }
}

function goToResult() {
  router.push(`/result/${taskId.value}`)
}

function clearError() {
  store.operationState.lastError = null
}

// ==================== 辅助函数 ====================

// 风险等级辅助函数
function getRiskTagType(level) {
  return { high: 'danger', medium: 'warning', low: 'success' }[level] || 'info'
}

function getRiskLabel(level) {
  return { high: '高', medium: '中', low: '低' }[level] || level
}

// 变更类型辅助函数
function getChangeTagType(changeType) {
  const types = {
    added: 'success',
    modified: 'warning',
    removed: 'danger',
    unchanged: 'info'
  }
  return types[changeType] || 'info'
}

function getChangeLabel(changeType) {
  const labels = {
    added: '新增',
    modified: '修改',
    removed: '删除',
    unchanged: '未变'
  }
  return labels[changeType] || changeType
}

// ==================== 特殊要求整合相关函数 ====================

// 整合特殊要求到标准
async function mergeSpecialRequirements() {
  if (!selectedStandards.value.length) {
    ElMessage.warning('请先选择基础标准')
    return
  }
  if (!specialRequirements.value.trim()) {
    ElMessage.warning('请输入特殊要求')
    return
  }

  merging.value = true
  try {
    const response = await api.mergeSpecialRequirements({
      standards: selectedStandards.value.map(s => ({
        category: s.category,
        item: s.item,
        description: s.description,
        risk_level: s.risk_level,
        applicable_to: s.applicable_to || ['contract']
      })),
      special_requirements: specialRequirements.value.trim(),
      our_party: form.value.our_party,
      material_type: form.value.material_type
    })
    mergeResult.value = response.data
    showMergePreview.value = true
  } catch (error) {
    ElMessage.error('整合失败: ' + (error.message || '请重试'))
  } finally {
    merging.value = false
  }
}

// 取消整合，保留原标准
function cancelMerge() {
  showMergePreview.value = false
  mergeResult.value = null
}

// 应用整合后的标准
function applyMergedStandards() {
  if (!mergeResult.value) return

  // 将整合后的标准（排除已删除的）设为当前选中标准
  selectedStandards.value = mergeResult.value.merged_standards
    .filter(s => s.change_type !== 'removed')
    .map(s => ({
      id: s.id,
      category: s.category,
      item: s.item,
      description: s.description,
      risk_level: s.risk_level,
      applicable_to: ['contract'] // 默认值
    }))

  showMergePreview.value = false
  mergeResult.value = null
  ElMessage.success('已应用到本次审核')
}

// 应用选中的标准到任务
async function applyStandards() {
  if (!taskId.value) {
    ElMessage.warning('请先上传文档')
    return
  }
  if (!selectedStandards.value.length) {
    ElMessage.warning('请先选择标准')
    return
  }

  applyingStandards.value = true
  try {
    // 创建 CSV 内容
    const csvContent = [
      '审核分类,审核要点,详细说明,风险等级,适用材料类型',
      ...selectedStandards.value.map(s =>
        `"${s.category}","${s.item}","${s.description}","${s.risk_level === 'high' ? '高' : s.risk_level === 'medium' ? '中' : '低'}","${(s.applicable_to || ['contract']).join(',')}"`
      )
    ].join('\n')

    // 创建 Blob 并上传
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' })
    const fileName = selectedCollection.value
      ? `${selectedCollection.value.name}.csv`
      : 'selected_standards.csv'
    const file = new File([blob], fileName, { type: 'text/csv' })

    await store.uploadStandard(taskId.value, file)
    showStandardPreview.value = false
    ElMessage.success('标准应用成功')
  } catch (error) {
    ElMessage.error('应用标准失败: ' + error.message)
  } finally {
    applyingStandards.value = false
  }
}
</script>

<style scoped>
.review-view {
  max-width: 1400px;
  margin: 0 auto;
}

/* 操作状态提示栏 */
.operation-status-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  margin-bottom: 16px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border-radius: 8px;
  font-size: 14px;
  box-shadow: 0 2px 12px rgba(102, 126, 234, 0.4);
}

.operation-status-bar .el-icon {
  font-size: 18px;
}

.error-alert {
  margin-bottom: 16px;
}

/* 过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.config-card,
.progress-card {
  height: calc(100vh - 140px);
  overflow-y: auto;
}

.card-header {
  font-weight: 600;
  font-size: 16px;
}

.upload-section h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 14px;
  color: #303133;
}

.language-detection-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 8px 12px;
  background: #f0f9eb;
  border-radius: 4px;
  font-size: 12px;
  color: #67c23a;
}

.upload-box {
  width: 100%;
}

.upload-box :deep(.el-upload-dragger) {
  padding: 20px;
  border-radius: 8px;
}

.upload-placeholder {
  color: #909399;
  text-align: center;
}

.upload-placeholder p {
  margin: 8px 0 4px;
}

.upload-placeholder span {
  font-size: 12px;
}

.uploaded-file {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #67c23a;
}

.uploaded-file span {
  color: #303133;
  font-size: 14px;
}

.standard-status {
  margin-top: 12px;
}

.start-btn {
  width: 100%;
  margin-top: 16px;
}

.waiting-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
}

.progress-state {
  padding: 40px;
}

.progress-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
  margin-bottom: 40px;
}

.progress-info {
  text-align: center;
}

.progress-info h3 {
  margin: 0 0 8px;
  font-size: 18px;
  color: #303133;
}

.progress-info p {
  margin: 0;
  color: #909399;
}

.completed-state,
.failed-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
}

/* 标准库相关样式 */
.library-section {
  padding: 8px 0;
}

.library-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.library-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px;
  color: #909399;
  text-align: center;
}

.library-tip p {
  margin-top: 12px;
  font-size: 14px;
}

.selected-standards {
  padding: 12px;
  background: #f5f7fa;
  border-radius: 8px;
}

.selected-count {
  margin: 0 0 8px;
  font-size: 14px;
  color: #606266;
}

.standards-preview {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.more-count {
  color: #909399;
  font-size: 12px;
  margin-left: 8px;
}

/* 推荐列表样式 */
.recommend-list {
  max-height: 400px;
  overflow-y: auto;
}

.recommend-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  margin-bottom: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.recommend-item:hover {
  border-color: #409eff;
  background: #f5f7fa;
}

.recommend-item.selected {
  border-color: #409eff;
  background: #ecf5ff;
}

.recommend-content {
  flex: 1;
}

.recommend-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.recommend-title {
  font-weight: 600;
  color: #303133;
}

.recommend-reason {
  margin: 0 0 4px;
  font-size: 13px;
  color: #409eff;
}

.recommend-desc {
  margin: 0;
  font-size: 12px;
  color: #909399;
}

/* ==================== 标准集合选择界面样式 ==================== */

.standard-section h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  font-size: 14px;
  color: #303133;
}

/* 标准选择入口 */
.standard-selection-entry {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
}

.section-label {
  margin: 0 0 12px;
  font-size: 13px;
  color: #606266;
}

/* 集合列表 */
.collection-list {
  max-height: 400px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.collection-card-dialog {
  padding: 16px;
  border: 2px solid #ebeef5;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.collection-card-dialog:hover {
  border-color: #c0c4cc;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.collection-card-dialog.selected {
  border-color: #409eff;
  background: #ecf5ff;
}

.collection-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.collection-info {
  flex: 1;
  min-width: 0;
}

.collection-name {
  display: block;
  font-weight: 600;
  font-size: 15px;
  color: #303133;
  margin-bottom: 4px;
}

.collection-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.collection-desc {
  margin: 10px 0 0;
  font-size: 13px;
  color: #909399;
  line-height: 1.5;
  padding-left: 36px;
}

.check-icon {
  font-size: 22px;
}

.empty-tip {
  text-align: center;
  color: #909399;
  font-size: 13px;
  padding: 20px;
}

.selection-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding: 10px 14px;
  background: #ecf5ff;
  border-radius: 6px;
  font-size: 13px;
  color: #409eff;
}

/* 预设模板卡片（旧样式保留兼容） */
.template-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.template-card {
  padding: 14px;
  border: 2px solid #ebeef5;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.template-card:hover {
  border-color: #c0c4cc;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.template-card.selected {
  border-color: #409eff;
  background: #ecf5ff;
}

.template-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.template-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}

.template-desc {
  margin: 0 0 8px;
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}

.template-meta {
  display: flex;
  gap: 8px;
}

.other-options {
  display: flex;
  gap: 16px;
  padding-top: 8px;
  border-top: 1px dashed #ebeef5;
}

/* 已选标准显示 */
.selected-standards-section {
  margin-top: 16px;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 8px;
}

.selected-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.selected-label {
  font-size: 13px;
  color: #606266;
}

.selected-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* 特殊要求输入 */
.special-requirements {
  margin-top: 16px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
}

.special-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  background: #fafafa;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.special-header:hover {
  background: #f5f7fa;
}

.special-header span {
  font-size: 13px;
  color: #606266;
}

.expand-icon {
  margin-left: auto;
  transition: transform 0.3s;
}

.expand-icon.expanded {
  transform: rotate(180deg);
}

.special-content {
  padding: 14px;
  background: white;
}

.special-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}

.special-tip {
  font-size: 12px;
  color: #909399;
}

/* 已应用标准状态 */
.applied-standard {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding: 10px 14px;
  background: #f0f9eb;
  border-radius: 8px;
  font-size: 13px;
  color: #67c23a;
}

.applied-standard span {
  flex: 1;
}

/* ==================== 整合预览样式 ==================== */

.merge-preview {
  max-height: 500px;
  overflow-y: auto;
}

.merge-summary {
  margin-bottom: 20px;
}

.summary-stats {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.summary-stats .el-tag {
  display: flex;
  align-items: center;
  gap: 4px;
}

.merge-standards-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.merge-standard-item {
  display: flex;
  gap: 12px;
  padding: 14px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  transition: all 0.2s;
}

.merge-standard-item.added {
  background: #f0f9eb;
  border-color: #c2e7b0;
}

.merge-standard-item.modified {
  background: #fdf6ec;
  border-color: #f5dab1;
}

.merge-standard-item.removed {
  background: #fef0f0;
  border-color: #fbc4c4;
  opacity: 0.7;
}

.merge-standard-item.removed .standard-desc {
  text-decoration: line-through;
}

.standard-change-badge {
  flex-shrink: 0;
}

.standard-content {
  flex: 1;
  min-width: 0;
}

.standard-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.standard-category {
  font-size: 12px;
  color: #909399;
  padding: 2px 6px;
  background: #f5f7fa;
  border-radius: 4px;
}

.standard-item {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}

.standard-desc {
  margin: 0;
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
}

.change-reason {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 8px 0 0;
  font-size: 12px;
  color: #409eff;
  background: rgba(64, 158, 255, 0.1);
  padding: 6px 10px;
  border-radius: 4px;
}

.change-reason .el-icon {
  margin-top: 2px;
  flex-shrink: 0;
}
</style>
