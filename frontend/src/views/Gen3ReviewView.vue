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
              :disabled="store.phase === 'uploading'"
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
        <el-button
          type="primary"
          :loading="store.isOperationInProgress"
          :disabled="store.phase === 'uploading'"
          @click="initSession"
        >
          初始化审阅
        </el-button>
      </el-card>

      <el-card v-if="store.phase === 'uploading'">
        <UploadPanel
          :documents="store.documents"
          :loading="store.isOperationInProgress"
          @upload="onUpload"
        />
        <div class="actions">
          <el-button type="success" :disabled="!store.canStartReview" @click="startReview">
            开始审阅
          </el-button>
        </div>
      </el-card>
    </div>

    <div v-else-if="isReviewPhase" class="review-section">
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

        <el-empty v-if="store.pendingDiffs.length === 0" description="当前无待审批 diff" />
        <DiffCard
          v-for="item in store.pendingDiffs"
          :key="item.diff_id"
          :diff="item"
          @approve="(id, feedback) => approveSingle(id, 'approve', feedback)"
          @reject="(id, feedback) => approveSingle(id, 'reject', feedback)"
        />
      </div>
    </div>

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
import { ArrowLeft } from '@element-plus/icons-vue'
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

const isSetupPhase = computed(() => ['idle', 'uploading'].includes(store.phase))
const isReviewPhase = computed(() => ['reviewing', 'interrupted'].includes(store.phase))

async function loadDomains() {
  try {
    const resp = await gen3Api.listDomains()
    domains.value = resp.data.domains || []
    if (!domains.value.find((item) => item.domain_id === domainId.value) && domains.value[0]) {
      domainId.value = domains.value[0].domain_id
    }
  } catch (error) {
    console.error('加载领域失败:', error)
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
    ElMessage.success('初始化成功，请上传主合同')
  } catch (error) {
    ElMessage.error(error.message || '初始化失败')
  }
}

async function onUpload(file, role) {
  try {
    const data = await store.uploadDocument(file, role)
    ElMessage.success(`${data.filename} 上传成功`)
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
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

async function approveSingle(diffId, decision, feedback = '') {
  try {
    await store.approveDiff(diffId, decision, feedback)
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

@media (max-width: 1200px) {
  .review-section {
    grid-template-columns: 1fr;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
