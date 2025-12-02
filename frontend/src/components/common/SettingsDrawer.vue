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
      <!-- 模型选择设置 -->
      <div class="settings-section">
        <div class="section-header">
          <el-icon class="section-icon"><Cpu /></el-icon>
          <span class="section-title">审阅模型</span>
        </div>
        <div class="section-description">
          选择审阅时使用的 AI 模型
        </div>

        <el-radio-group
          v-model="settingsStore.intelligenceLevel"
          class="intelligence-radio-group"
          @change="handleIntelligenceLevelChange"
        >
          <el-radio value="advanced" class="intelligence-radio">
            <div class="radio-content">
              <div class="radio-header">
                <span class="radio-title">国际模型</span>
              </div>
              <div class="radio-description">
                使用 Gemini，适合国际化场景
              </div>
            </div>
          </el-radio>

          <el-radio value="basic" class="intelligence-radio">
            <div class="radio-content">
              <div class="radio-header">
                <span class="radio-title">国内模型</span>
              </div>
              <div class="radio-description">
                使用 DeepSeek，国内访问更稳定
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
        <span class="footer-text">设置会自动保存</span>
        <span class="footer-divider">·</span>
        <span class="version-tag">v1.0.0</span>
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
  padding: 0 var(--spacing-1);
}

.settings-section {
  margin-bottom: var(--spacing-6);
}

.section-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-2);
}

.section-icon {
  font-size: var(--font-size-lg);
  color: var(--color-primary);
}

.section-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.section-description {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin-bottom: var(--spacing-4);
}

.intelligence-radio-group {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
  width: 100%;
}

.intelligence-radio {
  display: flex;
  align-items: flex-start;
  padding: var(--spacing-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  margin-right: 0 !important;
  height: auto !important;
  transition: all 0.2s;
}

.intelligence-radio:hover {
  border-color: var(--color-border-dark);
  background-color: var(--color-bg-hover);
}

.intelligence-radio.is-checked {
  border-color: var(--color-primary);
  background-color: var(--color-primary-bg);
}

.intelligence-radio :deep(.el-radio__input) {
  margin-top: 2px;
}

.intelligence-radio :deep(.el-radio__label) {
  padding-left: var(--spacing-3);
  flex: 1;
}

.radio-content {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.radio-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.radio-title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.radio-description {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  line-height: var(--line-height-normal);
}

.drawer-footer {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-3) 0;
}

.footer-text {
  font-size: var(--font-size-xs);
  color: var(--color-text-disabled);
}

.footer-divider {
  color: var(--color-text-disabled);
}

.version-tag {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--font-weight-medium);
}
</style>
