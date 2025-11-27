<template>
  <el-drawer
    v-model="settingsStore.settingsDrawerVisible"
    title="设置"
    direction="rtl"
    size="360px"
    :close-on-click-modal="true"
    :close-on-press-escape="true"
  >
    <div class="settings-content">
      <!-- 智能水平设置 -->
      <div class="settings-section">
        <div class="section-header">
          <el-icon class="section-icon"><Cpu /></el-icon>
          <span class="section-title">智能水平</span>
        </div>
        <div class="section-description">
          选择审阅时使用的智能分析能力
        </div>

        <el-radio-group
          v-model="settingsStore.intelligenceLevel"
          class="intelligence-radio-group"
          @change="handleIntelligenceLevelChange"
        >
          <el-radio value="advanced" class="intelligence-radio">
            <div class="radio-content">
              <div class="radio-header">
                <span class="radio-title">高级</span>
                <el-tag type="success" size="small" effect="plain">推荐</el-tag>
              </div>
              <div class="radio-description">
                更精准的风险识别和建议
              </div>
            </div>
          </el-radio>

          <el-radio value="basic" class="intelligence-radio">
            <div class="radio-content">
              <div class="radio-header">
                <span class="radio-title">初级</span>
              </div>
              <div class="radio-description">
                快速审阅，经济实惠
              </div>
            </div>
          </el-radio>
        </el-radio-group>
      </div>

      <!-- 预留：账号设置区域 -->
      <!--
      <el-divider />
      <div class="settings-section">
        <div class="section-header">
          <el-icon class="section-icon"><User /></el-icon>
          <span class="section-title">账号</span>
        </div>
        <div class="section-description">
          账号相关设置（即将推出）
        </div>
      </div>
      -->

      <!-- 预留：其他设置区域 -->
      <!--
      <el-divider />
      <div class="settings-section">
        <div class="section-header">
          <el-icon class="section-icon"><Setting /></el-icon>
          <span class="section-title">其他</span>
        </div>
      </div>
      -->
    </div>

    <!-- 底部信息 -->
    <template #footer>
      <div class="drawer-footer">
        <span class="version-info">设置会自动保存</span>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { Cpu } from '@element-plus/icons-vue'
import { useSettingsStore } from '@/store/settings'

const settingsStore = useSettingsStore()

const handleIntelligenceLevelChange = (value) => {
  settingsStore.setIntelligenceLevel(value)
}
</script>

<style scoped>
.settings-content {
  padding: 0 4px;
}

.settings-section {
  margin-bottom: 24px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.section-icon {
  font-size: 18px;
  color: #409eff;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.section-description {
  font-size: 13px;
  color: #909399;
  margin-bottom: 16px;
}

.intelligence-radio-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.intelligence-radio {
  display: flex;
  align-items: flex-start;
  padding: 16px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  margin-right: 0 !important;
  height: auto !important;
  transition: all 0.2s;
}

.intelligence-radio:hover {
  border-color: #c0c4cc;
  background-color: #fafafa;
}

.intelligence-radio.is-checked {
  border-color: #409eff;
  background-color: #ecf5ff;
}

.intelligence-radio :deep(.el-radio__input) {
  margin-top: 2px;
}

.intelligence-radio :deep(.el-radio__label) {
  padding-left: 12px;
  flex: 1;
}

.radio-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.radio-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.radio-title {
  font-size: 15px;
  font-weight: 500;
  color: #303133;
}

.radio-description {
  font-size: 13px;
  color: #909399;
  line-height: 1.4;
}

.drawer-footer {
  display: flex;
  justify-content: center;
  padding: 12px 0;
}

.version-info {
  font-size: 12px;
  color: #c0c4cc;
}
</style>
