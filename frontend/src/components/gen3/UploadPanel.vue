<template>
  <div class="upload-panel">
    <div class="panel-header">
      <h3>文档上传</h3>
      <el-radio-group v-model="selectedRole" size="small" :disabled="disabled || loading">
        <el-radio-button label="primary">主合同</el-radio-button>
        <el-radio-button label="baseline">基线文本</el-radio-button>
        <el-radio-button label="supplement">补充材料</el-radio-button>
        <el-radio-button label="reference">参考资料</el-radio-button>
      </el-radio-group>
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

const hasSameRoleDoc = computed(() => props.documents.some((item) => item.role === selectedRole.value))

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

.doc-list h4 {
  margin: 0 0 12px;
}
</style>
