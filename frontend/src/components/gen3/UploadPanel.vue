<template>
  <div class="upload-panel">
    <div class="panel-header">
      <h3>文档上传</h3>
      <el-button
        type="primary"
        :disabled="disabled || loading || selectedUploads.length === 0"
        @click="submitBatch"
      >
        开始上传
      </el-button>
    </div>

    <div class="role-grid">
      <div v-for="item in roleSections" :key="item.value" class="role-card">
        <div class="role-card-header">
          <span>{{ item.label }}</span>
          <el-tag size="small" :type="item.required ? 'danger' : 'info'" effect="plain">
            {{ item.required ? '必需项' : '可选项' }}
          </el-tag>
        </div>
        <p class="role-desc">{{ item.description }}</p>
        <el-upload
          drag
          action="#"
          :auto-upload="false"
          :show-file-list="false"
          :disabled="disabled || loading"
          accept=".txt,.docx,.pdf,.md,.xlsx"
          :on-change="(uploadFile) => handleFileChange(item.value, uploadFile)"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖拽或点击选择 {{ item.label }}</div>
        </el-upload>
        <div v-if="selectedFilesByRole[item.value]" class="selected-file">
          <span>{{ selectedFilesByRole[item.value].name }}</span>
          <el-button text type="danger" @click="removeSelected(item.value)">移除</el-button>
        </div>
      </div>
    </div>

    <div class="jobs-block" v-if="uploadJobs.length > 0">
      <h4>上传任务</h4>
      <div v-for="job in uploadJobs" :key="job.job_id" class="job-item">
        <div class="job-main">
          <div class="job-name">{{ job.filename }} <el-tag size="small" effect="plain">{{ job.role }}</el-tag></div>
          <div class="job-stage">{{ formatStage(job.stage) }} · {{ job.status }}</div>
        </div>
        <el-progress :percentage="Number(job.progress || 0)" :stroke-width="6" />
        <div v-if="job.status === 'failed'" class="job-error">
          <span>{{ job.error_message || '解析失败' }}</span>
          <el-button size="small" @click="$emit('retry-upload', job.job_id)">重试</el-button>
        </div>
      </div>
    </div>

    <div class="doc-list">
      <h4>已上传文档</h4>
      <el-empty v-if="documents.length === 0" description="暂无文档" :image-size="80" />
      <el-table v-else :data="documents" size="small">
        <el-table-column prop="filename" label="文件名" min-width="220" />
        <el-table-column prop="role" label="角色" width="120" />
        <el-table-column prop="total_clauses" label="条款数" width="100" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'

const props = defineProps({
  documents: { type: Array, default: () => [] },
  uploadJobs: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits(['batch-upload', 'retry-upload'])

const MAX_SIZE = 20 * 1024 * 1024
const roleSections = [
  {
    value: 'primary',
    label: '主合同',
    required: true,
    description: '待审阅的合同文本。至少上传 1 份主合同才能开始审阅。'
  },
  {
    value: 'baseline',
    label: '基线文本',
    required: false,
    description: '标准版本或对照模板（如 FIDIC 银皮书），用于条款对比分析。'
  },
  {
    value: 'supplement',
    label: '补充材料',
    required: false,
    description: '补充协议、附件、会议纪要等支持性材料。'
  },
  {
    value: 'reference',
    label: '参考资料',
    required: false,
    description: '用于语义检索或背景参考的历史/标准文档。'
  }
]

const selectedFilesByRole = reactive({
  primary: null,
  baseline: null,
  supplement: null,
  reference: null
})

const selectedUploads = computed(() => {
  return Object.entries(selectedFilesByRole)
    .filter(([, file]) => !!file)
    .map(([role, file]) => ({ role, file }))
})

function handleFileChange(role, uploadFile) {
  const file = uploadFile?.raw
  if (!file) return
  if (file.size > MAX_SIZE) {
    ElMessage.error('文件大小不能超过 20MB')
    return
  }
  selectedFilesByRole[role] = file
}

function removeSelected(role) {
  selectedFilesByRole[role] = null
}

function submitBatch() {
  if (!selectedUploads.value.length) {
    ElMessage.warning('请先选择至少一个文件')
    return
  }
  emit('batch-upload', selectedUploads.value)
  for (const role of Object.keys(selectedFilesByRole)) {
    selectedFilesByRole[role] = null
  }
}

function formatStage(stage) {
  const mapping = {
    uploaded: '已上传',
    loading: '读取中',
    detecting: '模式检测',
    parsing: '结构解析',
    extracting_defs: '提取定义',
    extracting_refs: '提取引用',
    injecting: '写入状态',
    finished: '完成',
    failed: '失败'
  }
  return mapping[stage] || stage || '排队中'
}
</script>

<style scoped>
.upload-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-header h3 {
  margin: 0;
}

.role-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.role-card {
  border: 1px solid var(--el-border-color);
  border-radius: 10px;
  padding: 12px;
}

.role-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.role-desc {
  margin: 8px 0 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.selected-file {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}

.jobs-block h4,
.doc-list h4 {
  margin: 0 0 12px;
}

.job-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
}

.job-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.job-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.job-stage {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.job-error {
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  color: var(--el-color-danger);
  font-size: 12px;
}

@media (max-width: 900px) {
  .role-grid {
    grid-template-columns: 1fr;
  }
}
</style>
