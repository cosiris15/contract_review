<template>
  <div class="review-summary">
    <div class="stats">
      <el-card><div class="stat"><span>总条款</span><strong>{{ totalClauses }}</strong></div></el-card>
      <el-card><div class="stat"><span>已批准</span><strong>{{ approvedDiffs.length }}</strong></div></el-card>
      <el-card><div class="stat"><span>已拒绝</span><strong>{{ rejectedDiffs.length }}</strong></div></el-card>
    </div>

    <el-card class="summary-text">
      <template #header>审阅摘要</template>
      <p>{{ summary || '暂无摘要' }}</p>
    </el-card>

    <el-collapse>
      <el-collapse-item :title="`已批准修改 (${approvedDiffs.length})`" name="approved">
        <ul class="diff-list">
          <li v-for="diff in approvedDiffs" :key="diff.diff_id">
            {{ diff.clause_id }} - {{ shortText(diff.proposed_text || diff.reason) }}
          </li>
        </ul>
      </el-collapse-item>
      <el-collapse-item :title="`已拒绝修改 (${rejectedDiffs.length})`" name="rejected">
        <ul class="diff-list">
          <li v-for="diff in rejectedDiffs" :key="diff.diff_id">
            {{ diff.clause_id }} - {{ shortText(diff.original_text || diff.reason) }}
          </li>
        </ul>
      </el-collapse-item>
    </el-collapse>

    <div class="export-actions">
      <el-button type="primary" :loading="exporting" @click="handleExportRedline">
        导出红线文档
      </el-button>
      <el-button @click="handleExportJson">
        导出 JSON 报告
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useGen3ReviewStore } from '@/store/gen3Review'

const props = defineProps({
  taskId: { type: String, default: '' },
  summary: { type: String, default: '' },
  approvedDiffs: { type: Array, default: () => [] },
  rejectedDiffs: { type: Array, default: () => [] },
  totalClauses: { type: Number, default: 0 }
})

const store = useGen3ReviewStore()
const exporting = ref(false)

function shortText(text = '') {
  return text.length > 80 ? `${text.slice(0, 80)}...` : text
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

async function handleExportRedline() {
  exporting.value = true
  try {
    const blob = await store.exportRedline()
    downloadBlob(blob, `redline_${props.taskId || 'gen3'}.docx`)
    ElMessage.success('红线文档导出成功')
  } catch (error) {
    ElMessage.error(error.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

async function handleExportJson() {
  try {
    const result = await store.fetchResult()
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
    downloadBlob(blob, `review_${props.taskId || 'gen3'}.json`)
    ElMessage.success('JSON 报告导出成功')
  } catch (error) {
    ElMessage.error(error.message || '导出失败')
  }
}
</script>

<style scoped>
.review-summary {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stat strong {
  font-size: 22px;
}

.summary-text p {
  margin: 0;
  line-height: 1.7;
  white-space: pre-wrap;
}

.diff-list {
  margin: 0;
  padding-left: 20px;
}

.diff-list li {
  margin-bottom: 8px;
}

.export-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
</style>
