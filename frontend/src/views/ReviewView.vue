<template>
  <div class="review-view">
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

          <!-- 步骤 3: 上传审核标准 -->
          <div class="upload-section">
            <h4>
              <el-icon><List /></el-icon>
              审核标准
            </h4>

            <!-- 选择模板或上传 -->
            <el-tabs v-model="standardTab">
              <el-tab-pane label="使用模板" name="template">
                <el-select
                  v-model="selectedTemplate"
                  placeholder="选择审核标准模板"
                  style="width: 100%"
                  @change="handleTemplateSelect"
                >
                  <el-option
                    v-for="tpl in templates"
                    :key="tpl.name"
                    :label="tpl.name"
                    :value="tpl.name"
                  >
                    <span>{{ tpl.name }}</span>
                    <span style="color: #909399; font-size: 12px; margin-left: 8px">
                      {{ tpl.description }}
                    </span>
                  </el-option>
                </el-select>
              </el-tab-pane>

              <el-tab-pane label="上传自定义" name="upload">
                <el-upload
                  class="upload-box"
                  drag
                  :auto-upload="false"
                  :show-file-list="false"
                  :on-change="handleStandardChange"
                  accept=".xlsx,.xls,.csv,.docx,.md,.txt"
                >
                  <div v-if="currentTask?.standard_filename && !selectedTemplate" class="uploaded-file">
                    <el-icon :size="40" color="#67c23a"><DocumentChecked /></el-icon>
                    <span>{{ currentTask.standard_filename }}</span>
                    <el-button type="primary" text size="small">重新上传</el-button>
                  </div>
                  <div v-else class="upload-placeholder">
                    <el-icon :size="40"><UploadFilled /></el-icon>
                    <p>上传自定义审核标准</p>
                    <span>支持 .xlsx, .csv, .docx, .md 格式</span>
                  </div>
                </el-upload>
              </el-tab-pane>
            </el-tabs>

            <div v-if="currentTask?.standard_filename" class="standard-status">
              <el-tag type="success">
                已选择: {{ currentTask.standard_filename }}
              </el-tag>
            </div>
          </div>

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

const route = useRoute()
const router = useRouter()
const store = useReviewStore()

const formRef = ref(null)
const taskId = ref(route.params.taskId || null)

const form = ref({
  name: '',
  our_party: '',
  material_type: 'contract'
})

const rules = {
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  our_party: [{ required: true, message: '请输入我方身份', trigger: 'blur' }]
}

const standardTab = ref('template')
const selectedTemplate = ref('')
const templates = ref([])

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
  // 加载模板列表
  await store.fetchTemplates()
  templates.value = store.templates

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
        material_type: form.value.material_type
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
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
  }
}

async function handleStandardChange(file) {
  if (!taskId.value) {
    ElMessage.warning('请先上传文档')
    return
  }

  try {
    selectedTemplate.value = ''
    await store.uploadStandard(taskId.value, file.raw)
    ElMessage.success('审核标准上传成功')
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
  }
}

async function handleTemplateSelect(templateName) {
  if (!taskId.value) {
    ElMessage.warning('请先上传文档')
    selectedTemplate.value = ''
    return
  }

  try {
    await store.useTemplate(taskId.value, templateName)
    ElMessage.success('模板应用成功')
  } catch (error) {
    ElMessage.error(error.message || '应用模板失败')
    selectedTemplate.value = ''
  }
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
</script>

<style scoped>
.review-view {
  max-width: 1400px;
  margin: 0 auto;
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
</style>
