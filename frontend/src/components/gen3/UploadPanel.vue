<template>
  <div class="upload-panel">
    <div class="panel-header">
      <h3>文档上传</h3>
      <el-radio-group v-model="selectedRole" size="small" :disabled="disabled || loading">
        <el-tooltip
          v-for="item in roleTabs"
          :key="item.value"
          :content="item.tooltip"
          placement="top"
          effect="dark"
        >
          <el-radio-button :label="item.value">
            {{ item.label }}
          </el-radio-button>
        </el-tooltip>
      </el-radio-group>
    </div>

    <div class="role-desc">
      <el-tag size="small" :type="selectedRoleMeta.required ? 'danger' : 'info'" effect="plain">
        {{ selectedRoleMeta.required ? '必需项' : '可选项' }}
      </el-tag>
      <span>{{ selectedRoleMeta.description }}</span>
    </div>

    <el-alert
      v-if="hasSameRoleDoc"
      type="warning"
      :closable="false"
      show-icon
      class="replace-alert"
      title="同角色文档会被替换"
    />

    <el-upload
      drag
      action="#"
      :auto-upload="false"
      :show-file-list="false"
      :disabled="disabled || loading"
      accept=".txt,.docx,.pdf,.md"
      :on-change="handleFileChange"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">拖拽文件到此处，或 <em>点击上传</em></div>
      <template #tip>
        <div class="el-upload__tip">支持 .txt/.docx/.pdf/.md，单文件不超过 20MB</div>
      </template>
    </el-upload>

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
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'

const props = defineProps({
  documents: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits(['upload'])

const selectedRole = ref('primary')
const MAX_SIZE = 20 * 1024 * 1024
const roleTabs = [
  {
    value: 'primary',
    label: '主合同',
    required: true,
    description: '待审阅的合同文本。至少上传 1 份主合同才能开始审阅。',
    tooltip: '必需：上传待审阅合同（不上传无法开始审阅）'
  },
  {
    value: 'baseline',
    label: '基线文本',
    required: false,
    description: '标准版本或对照模板（如 FIDIC 银皮书），用于条款对比分析。',
    tooltip: '建议：上传标准模板/对照版本（提升对比能力）'
  },
  {
    value: 'supplement',
    label: '补充材料',
    required: false,
    description: '与合同条款相关的补充文件（会议纪要、补充协议、附件等）。',
    tooltip: '可选：上传补充协议、纪要、附件等'
  },
  {
    value: 'reference',
    label: '参考资料',
    required: false,
    description: '供审阅模型检索参考的资料（标准条款库、历史案例等）。',
    tooltip: '可选：上传参考文档用于检索增强'
  }
]

const hasSameRoleDoc = computed(() => props.documents.some((item) => item.role === selectedRole.value))
const selectedRoleMeta = computed(() => roleTabs.find((item) => item.value === selectedRole.value) || roleTabs[0])

function handleFileChange(uploadFile) {
  const file = uploadFile?.raw
  if (!file) {
    return
  }
  if (file.size > MAX_SIZE) {
    ElMessage.error('文件大小不能超过 20MB')
    return
  }
  emit('upload', file, selectedRole.value)
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

.replace-alert {
  margin-bottom: 4px;
}

.role-desc {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.doc-list h4 {
  margin: 0 0 12px;
}
</style>
