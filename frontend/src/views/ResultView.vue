<template>
  <div class="result-view" v-loading="loading">
    <!-- 顶部信息栏 -->
    <div class="result-header">
      <div class="header-info">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <h2>{{ result?.document_name || '审阅结果' }}</h2>
        <div class="header-meta">
          <el-tag>{{ materialTypeText }}</el-tag>
          <span>我方: {{ result?.our_party }}</span>
          <span>审阅时间: {{ formatTime(result?.reviewed_at) }}</span>
        </div>
      </div>
      <div class="header-actions">
        <el-dropdown @command="handleExport">
          <el-button type="primary">
            <el-icon><Download /></el-icon>
            导出
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="excel">导出 Excel</el-dropdown-item>
              <el-dropdown-item command="csv">导出 CSV</el-dropdown-item>
              <el-dropdown-item command="json">导出 JSON</el-dropdown-item>
              <el-dropdown-item command="report">导出报告</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-cards">
      <el-col :span="6">
        <el-card class="stat-card danger">
          <div class="stat-value">{{ summary.total_risks }}</div>
          <div class="stat-label">风险总数</div>
          <div class="stat-detail">
            高 {{ summary.high_risks }} / 中 {{ summary.medium_risks }} / 低 {{ summary.low_risks }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card warning">
          <div class="stat-value">{{ summary.high_risks }}</div>
          <div class="stat-label">高风险</div>
          <div class="stat-detail">需优先处理</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card primary">
          <div class="stat-value">{{ summary.total_modifications }}</div>
          <div class="stat-label">修改建议</div>
          <div class="stat-detail">
            必须 {{ summary.must_modify }} / 应该 {{ summary.should_modify }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card success">
          <div class="stat-value">{{ summary.total_actions }}</div>
          <div class="stat-label">行动建议</div>
          <div class="stat-detail">
            立即处理 {{ summary.immediate_actions }}
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 详细内容 Tabs -->
    <el-card class="content-card">
      <el-tabs v-model="activeTab">
        <!-- 风险点列表 -->
        <el-tab-pane label="风险点" name="risks">
          <template #label>
            <span>
              风险点
              <el-badge :value="result?.risks?.length || 0" type="danger" />
            </span>
          </template>
          <el-table :data="result?.risks || []" stripe border>
            <el-table-column label="风险等级" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="riskLevelType(row.risk_level)">
                  {{ riskLevelText(row.risk_level) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="risk_type" label="风险类型" width="120" />
            <el-table-column prop="description" label="风险描述" min-width="200" />
            <el-table-column prop="reason" label="判定理由" min-width="200" />
            <el-table-column label="原文摘录" width="200">
              <template #default="{ row }">
                <el-popover
                  v-if="row.location?.original_text"
                  trigger="hover"
                  width="400"
                  placement="top"
                >
                  <template #reference>
                    <span class="text-ellipsis">
                      {{ row.location.original_text.slice(0, 50) }}...
                    </span>
                  </template>
                  <div>{{ row.location.original_text }}</div>
                </el-popover>
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 修改建议列表 -->
        <el-tab-pane label="修改建议" name="modifications">
          <template #label>
            <span>
              修改建议
              <el-badge :value="result?.modifications?.length || 0" type="primary" />
            </span>
          </template>
          <div class="modification-list">
            <el-card
              v-for="mod in result?.modifications || []"
              :key="mod.id"
              class="modification-card"
              :class="{ confirmed: mod.user_confirmed }"
            >
              <div class="mod-header">
                <el-tag :type="priorityType(mod.priority)">
                  {{ priorityText(mod.priority) }}
                </el-tag>
                <span class="mod-reason">{{ mod.modification_reason }}</span>
                <el-checkbox
                  v-model="mod.user_confirmed"
                  @change="(val) => updateModification(mod, { user_confirmed: val })"
                >
                  确认采纳
                </el-checkbox>
              </div>
              <el-row :gutter="20" class="mod-content">
                <el-col :span="12">
                  <div class="text-label">当前文本</div>
                  <div class="text-box original">{{ mod.original_text }}</div>
                </el-col>
                <el-col :span="12">
                  <div class="text-label">建议修改为</div>
                  <el-input
                    type="textarea"
                    :rows="4"
                    v-model="mod.editText"
                    @blur="updateModification(mod, { user_modified_text: mod.editText })"
                  />
                </el-col>
              </el-row>
            </el-card>
            <el-empty v-if="!result?.modifications?.length" description="无修改建议" />
          </div>
        </el-tab-pane>

        <!-- 行动建议列表 -->
        <el-tab-pane label="行动建议" name="actions">
          <template #label>
            <span>
              行动建议
              <el-badge :value="result?.actions?.length || 0" type="success" />
            </span>
          </template>
          <el-table :data="result?.actions || []" stripe border>
            <el-table-column label="紧急程度" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="urgencyType(row.urgency)">
                  {{ urgencyText(row.urgency) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="action_type" label="行动类型" width="120" />
            <el-table-column prop="description" label="具体行动" min-width="250" />
            <el-table-column prop="responsible_party" label="负责方" width="100" />
            <el-table-column prop="deadline_suggestion" label="建议时限" width="120">
              <template #default="{ row }">
                {{ row.deadline_suggestion || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="确认" width="80" align="center">
              <template #default="{ row }">
                <el-checkbox
                  v-model="row.user_confirmed"
                  @change="(val) => updateAction(row, val)"
                />
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!result?.actions?.length" description="无行动建议" />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useReviewStore } from '@/store'
import { ElMessage } from 'element-plus'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const store = useReviewStore()

const loading = ref(false)
const activeTab = ref('risks')
const taskId = computed(() => route.params.taskId)

const result = computed(() => store.reviewResult)
const summary = computed(() => result.value?.summary || {
  total_risks: 0,
  high_risks: 0,
  medium_risks: 0,
  low_risks: 0,
  total_modifications: 0,
  must_modify: 0,
  should_modify: 0,
  total_actions: 0,
  immediate_actions: 0
})

const materialTypeText = computed(() => {
  return result.value?.material_type === 'contract' ? '合同' : '营销材料'
})

onMounted(async () => {
  if (taskId.value) {
    loading.value = true
    try {
      await store.loadResult(taskId.value)
      // 初始化编辑文本
      if (result.value?.modifications) {
        result.value.modifications.forEach(mod => {
          mod.editText = mod.user_modified_text || mod.suggested_text
        })
      }
    } catch (error) {
      ElMessage.error('加载结果失败')
    } finally {
      loading.value = false
    }
  }
})

function goBack() {
  router.push('/')
}

function formatTime(isoString) {
  if (!isoString) return '-'
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN')
}

function riskLevelType(level) {
  const types = { high: 'danger', medium: 'warning', low: 'info' }
  return types[level] || 'info'
}

function riskLevelText(level) {
  const texts = { high: '高', medium: '中', low: '低' }
  return texts[level] || level
}

function priorityType(priority) {
  const types = { must: 'danger', should: 'warning', may: 'info' }
  return types[priority] || 'info'
}

function priorityText(priority) {
  const texts = { must: '必须', should: '应该', may: '可以' }
  return texts[priority] || priority
}

function urgencyType(urgency) {
  const types = { immediate: 'danger', soon: 'warning', normal: 'info' }
  return types[urgency] || 'info'
}

function urgencyText(urgency) {
  const texts = { immediate: '立即', soon: '尽快', normal: '一般' }
  return texts[urgency] || urgency
}

async function updateModification(mod, updates) {
  try {
    await store.updateModification(taskId.value, mod.id, updates)
    // 重新初始化编辑文本
    if (result.value?.modifications) {
      result.value.modifications.forEach(m => {
        m.editText = m.user_modified_text || m.suggested_text
      })
    }
  } catch (error) {
    ElMessage.error('更新失败')
  }
}

async function updateAction(action, confirmed) {
  try {
    await store.updateAction(taskId.value, action.id, confirmed)
  } catch (error) {
    ElMessage.error('更新失败')
  }
}

function handleExport(command) {
  const urls = {
    excel: api.exportExcel(taskId.value),
    csv: api.exportCsv(taskId.value),
    json: api.exportJson(taskId.value),
    report: api.exportReport(taskId.value)
  }
  const url = urls[command]
  if (url) {
    window.open(url, '_blank')
  }
}
</script>

<style scoped>
.result-view {
  max-width: 1400px;
  margin: 0 auto;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  background: white;
  padding: 20px 24px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.header-info h2 {
  margin: 8px 0;
  font-size: 20px;
  color: #303133;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  color: #909399;
  font-size: 14px;
}

.stat-cards {
  margin-bottom: 24px;
}

.stat-card {
  text-align: center;
  padding: 12px;
}

.stat-card .stat-value {
  font-size: 32px;
  font-weight: 700;
  margin-bottom: 4px;
}

.stat-card .stat-label {
  font-size: 14px;
  color: #606266;
  margin-bottom: 4px;
}

.stat-card .stat-detail {
  font-size: 12px;
  color: #909399;
}

.stat-card.danger .stat-value { color: #f56c6c; }
.stat-card.warning .stat-value { color: #e6a23c; }
.stat-card.primary .stat-value { color: #409eff; }
.stat-card.success .stat-value { color: #67c23a; }

.content-card {
  min-height: 500px;
}

.text-ellipsis {
  display: inline-block;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  color: #409eff;
}

.modification-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.modification-card {
  border-left: 4px solid #e6a23c;
}

.modification-card.confirmed {
  border-left-color: #67c23a;
}

.mod-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.mod-reason {
  flex: 1;
  color: #606266;
}

.mod-content {
  margin-top: 12px;
}

.text-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.text-box {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.6;
  min-height: 100px;
}

.text-box.original {
  color: #909399;
  text-decoration: line-through;
}
</style>
