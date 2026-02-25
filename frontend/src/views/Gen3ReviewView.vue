<template>
  <div class="gen3-view">
    <div class="page-header">
      <el-button text @click="router.push('/')">
        <el-icon><ArrowLeft /></el-icon>
        返回
      </el-button>
      <h2>Gen 3.0 智能审阅</h2>
      <span v-if="store.taskId" class="task-id">任务: {{ store.taskId }}</span>
    </div>

    <el-alert
      v-if="store.phase === 'error'"
      type="error"
      :closable="false"
      show-icon
      :title="store.error || '审阅流程异常'"
    />

    <div v-if="isSetupPhase" class="setup-section">
      <el-card>
        <template #header>审阅配置</template>
        <div class="form-grid">
          <el-form-item label="领域">
            <el-select
              v-model="domainId"
              placeholder="请选择领域"
              style="width: 220px;"
              :disabled="store.phase === 'uploading' || !!domainLoadErrorMessage"
              :loading="domainsLoading"
              no-data-text="无法加载领域，请检查额度或网络后重试"
            >
              <el-option
                v-for="item in domains"
                :key="item.domain_id"
                :label="item.name"
                :value="item.domain_id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="我方身份">
            <el-input
              v-model="ourParty"
              placeholder="例如：发包人/承包人"
              :disabled="store.phase === 'uploading'"
            />
          </el-form-item>
          <el-form-item label="语言">
            <el-radio-group v-model="language" :disabled="store.phase === 'uploading'">
              <el-radio label="zh-CN">中文</el-radio>
              <el-radio label="en">English</el-radio>
            </el-radio-group>
          </el-form-item>
        </div>
        <el-alert
          v-if="domainLoadErrorMessage"
          :type="domainLoadErrorType === 'quota_exceeded' ? 'warning' : 'error'"
          :closable="false"
          show-icon
          :title="domainLoadErrorType === 'quota_exceeded' ? '额度不足，暂时无法加载领域' : '领域加载失败'"
          :description="domainLoadErrorMessage"
          style="margin-bottom: 12px;"
        />
        <el-button
          type="primary"
          :loading="store.isOperationInProgress"
          :disabled="store.phase === 'uploading' || !!domainLoadErrorMessage"
          @click="initSession"
        >
          创建任务
        </el-button>
      </el-card>

      <el-card v-if="store.phase === 'uploading'">
        <UploadPanel
          :documents="store.documents"
          :upload-jobs="store.uploadJobs"
          :loading="store.isOperationInProgress"
          @batch-upload="onBatchUpload"
          @retry-upload="onRetryUpload"
        />
        <div class="actions">
          <el-button type="success" :disabled="!store.canStartReview" @click="startReview">
            开始审阅
          </el-button>
        </div>
      </el-card>
    </div>

    <template v-else-if="isReviewPhase">
      <el-alert
        class="review-warning-alert"
        type="warning"
        :closable="false"
        show-icon
        title="审阅进行中，请勿部署或刷新页面"
        description="部署/刷新会中断实时连接；系统会自动重连，但建议等待当前批次处理完成后再发布。"
      />
      <div class="review-section">
      <ClauseProgress
        :current-index="store.currentClauseIndex"
        :total-clauses="store.totalClauses"
        :current-clause-id="store.currentClauseId || ''"
        :approved-diffs="store.approvedDiffs"
        :rejected-diffs="store.rejectedDiffs"
      />
      <div class="diff-area">
        <div class="diff-header">
          <h3>待审批修改</h3>
          <div class="bulk-actions">
            <el-button :disabled="store.pendingDiffs.length === 0" @click="approveAll('approve')">全部批准</el-button>
            <el-button
              type="danger"
              plain
              :disabled="store.pendingDiffs.length === 0"
              @click="approveAll('reject')"
            >
              全部拒绝
            </el-button>
            <el-button
              type="primary"
              :disabled="store.pendingDiffs.length > 0"
              @click="store.resumeAfterApproval"
            >
              继续审阅
            </el-button>
          </div>
        </div>

        <div v-if="store.phase === 'reviewing'" class="processing-banner">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>{{ store.progressMessage || '正在分析合同条款...' }}</span>
          <el-tag v-if="store.currentClauseId" size="small" effect="plain">
            {{ store.currentClauseId }}
          </el-tag>
        </div>

        <el-alert
          v-if="store.pendingDiffs.length === 0 && store.phase === 'interrupted'"
          type="info"
          :closable="false"
          show-icon
          title="所有修改建议已处理完毕"
          description="点击「继续审阅」让系统继续分析下一批条款。"
        />
        <el-empty
          v-else-if="store.pendingDiffs.length === 0 && store.phase === 'reviewing'"
          description="等待系统生成修改建议..."
          :image-size="60"
        />
        <div v-for="group in store.groupedPendingDiffs" :key="group.clauseId" class="clause-group">
          <div class="clause-group-header">
            <span class="clause-group-id">{{ group.clauseId }}</span>
            <el-tag size="small" effect="plain">{{ group.diffs.length }} 项修改</el-tag>
          </div>
          <DiffCard
            v-for="(item, index) in group.diffs"
            :key="item.diff_id"
            :diff="item"
            :task-id="store.taskId"
            class="animate-entry"
            :style="{ animationDelay: `${index * 50}ms` }"
            @approve="(id, feedback, userModifiedText) => approveSingle(id, 'approve', feedback, userModifiedText)"
            @reject="(id, feedback) => approveSingle(id, 'reject', feedback)"
          />
        </div>
        <el-collapse v-if="store.handledDiffs.length > 0" class="history-collapse">
          <el-collapse-item>
            <template #title>
              <span>决策历史</span>
              <el-tag size="small" type="success" effect="plain" style="margin-left: 8px;">
                {{ store.approvedDiffs.length }} 批准
              </el-tag>
              <el-tag size="small" type="danger" effect="plain" style="margin-left: 4px;">
                {{ store.rejectedDiffs.length }} 拒绝
              </el-tag>
            </template>
            <div v-for="item in store.handledDiffs" :key="item.diff_id" class="history-item">
              <el-tag :type="item.status === 'approved' ? 'success' : 'danger'" size="small">
                {{ item.status === 'approved' ? '批准' : '拒绝' }}
              </el-tag>
              <span class="history-clause">{{ item.clause_id || '未知' }}</span>
              <span class="history-reason">{{ item.reason || '' }}</span>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
      </div>
    </template>

    <div v-else-if="store.phase === 'complete'" class="complete-section">
      <ReviewSummary
        :task-id="store.taskId"
        :summary="store.summary"
        :approved-diffs="store.approvedDiffs"
        :rejected-diffs="store.rejectedDiffs"
        :total-clauses="store.totalClauses"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Loading } from '@element-plus/icons-vue'
import gen3Api from '@/api/gen3'
import { useGen3ReviewStore } from '@/store/gen3Review'
import UploadPanel from '@/components/gen3/UploadPanel.vue'
import DiffCard from '@/components/gen3/DiffCard.vue'
import ClauseProgress from '@/components/gen3/ClauseProgress.vue'
import ReviewSummary from '@/components/gen3/ReviewSummary.vue'

const router = useRouter()
const route = useRoute()
const store = useGen3ReviewStore()

const domains = ref([])
const domainId = ref('fidic')
const ourParty = ref('')
const language = ref('zh-CN')
const domainsLoading = ref(false)
const domainLoadErrorType = ref('')
const domainLoadErrorMessage = ref('')

const isSetupPhase = computed(() => ['idle', 'uploading'].includes(store.phase))
const isReviewPhase = computed(() => ['reviewing', 'interrupted'].includes(store.phase))

function handleBeforeUnload(event) {
  if (!isReviewPhase.value) return
  event.preventDefault()
  event.returnValue = ''
}

async function loadDomains() {
  domainsLoading.value = true
  domainLoadErrorType.value = ''
  domainLoadErrorMessage.value = ''
  try {
    const resp = await gen3Api.listDomains()
    domains.value = resp.data.domains || []
    if (!domains.value.find((item) => item.domain_id === domainId.value) && domains.value[0]) {
      domainId.value = domains.value[0].domain_id
    }
    if (!domains.value.length) {
      domainLoadErrorType.value = 'empty'
      domainLoadErrorMessage.value = '系统暂未返回可用领域，请稍后重试。'
    }
  } catch (error) {
    console.error('加载领域失败:', error)
    domainLoadErrorType.value = error?.errorInfo?.type || 'request_failed'
    domainLoadErrorMessage.value = domainLoadErrorType.value === 'quota_exceeded'
      ? '当前账号额度已用完。请先充值，然后刷新页面重试。'
      : (error.message || '请检查网络或稍后重试。')
  } finally {
    domainsLoading.value = false
  }
}

async function initSession() {
  try {
    await store.initReview({
      domainId: domainId.value,
      ourParty: ourParty.value,
      language: language.value
    })
    router.replace(`/gen3/${store.taskId}`)
    ElMessage.success('任务创建成功，请上传主合同')
  } catch (error) {
    ElMessage.error(error.message || '创建任务失败')
  }
}

async function onBatchUpload(items) {
  try {
    for (const item of items) {
      // eslint-disable-next-line no-await-in-loop
      await store.uploadDocument(item.file, item.role)
    }
    ElMessage.success('上传任务已创建，正在后台解析')
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
  }
}

async function onRetryUpload(jobId) {
  try {
    await store.retryUploadJob(jobId)
    ElMessage.success('重试任务已提交')
  } catch (error) {
    ElMessage.error(error.message || '重试失败')
  }
}

async function startReview() {
  try {
    await store.startListening()
    ElMessage.success('审阅已启动')
  } catch (error) {
    ElMessage.error(error.message || '启动失败')
  }
}

async function approveSingle(diffId, decision, feedback = '', userModifiedText = undefined) {
  try {
    await store.approveDiff(diffId, decision, feedback, userModifiedText)
  } catch (error) {
    ElMessage.error(error.message || '审批失败')
  }
}

async function approveAll(decision) {
  try {
    await store.approveAllPending(decision)
    ElMessage.success(decision === 'approve' ? '已全部批准' : '已全部拒绝')
  } catch (error) {
    ElMessage.error(error.message || '批量审批失败')
  }
}

onMounted(async () => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  await loadDomains()
  const routeTaskId = route.params.taskId
  if (typeof routeTaskId === 'string' && routeTaskId) {
    try {
      await store.recoverSession(routeTaskId)
      ElMessage.success('会话恢复成功')
    } catch (error) {
      console.warn('恢复会话失败:', error)
    }
  }
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  store.disconnect()
})
</script>

<style scoped>
.gen3-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - var(--header-height) - var(--spacing-6) * 2);
}

.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-header h2 {
  margin: 0;
}

.task-id {
  color: var(--el-text-color-secondary);
  margin-left: auto;
  font-size: 13px;
}

.setup-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.review-warning-alert {
  margin-bottom: 12px;
}

.review-section {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  min-height: 560px;
}

.diff-area {
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color);
  border-radius: 10px;
  padding: 16px;
  overflow: auto;
}

.diff-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.diff-header h3 {
  margin: 0;
}

.bulk-actions {
  display: flex;
  gap: 8px;
}

.processing-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: var(--el-color-primary-light-9);
  border-radius: 8px;
  margin-bottom: 12px;
  color: var(--el-color-primary);
  font-size: 14px;
}

.clause-group {
  margin-bottom: 16px;
}

.clause-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.clause-group-id {
  font-weight: 600;
  font-size: 14px;
}

.history-collapse {
  margin-top: 16px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
}

.history-clause {
  font-weight: 500;
  min-width: 60px;
}

.history-reason {
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1200px) {
  .review-section {
    grid-template-columns: 1fr;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
