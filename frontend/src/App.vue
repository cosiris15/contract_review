<template>
  <el-config-provider :locale="zhCn">
    <div id="app">
      <el-container class="app-container">
        <el-header class="app-header">
          <div class="header-left">
            <router-link to="/" class="logo">
              <img src="@/assets/Logo.png" alt="Paralaw" class="logo-img" />
            </router-link>
            <div class="header-divider"></div>
            <nav class="nav-links">
              <router-link to="/" class="nav-link">
                <el-icon><HomeFilled /></el-icon>
                <span>首页</span>
              </router-link>
              <router-link to="/documents" class="nav-link">
                <el-icon><FolderOpened /></el-icon>
                <span>文档管理</span>
              </router-link>
              <router-link to="/standards" class="nav-link">
                <el-icon><Setting /></el-icon>
                <span>标准管理</span>
              </router-link>
              <router-link to="/business" class="nav-link">
                <el-icon><Briefcase /></el-icon>
                <span>业务管理</span>
              </router-link>
            </nav>
          </div>
          <div class="header-right">
            <!-- 设置按钮 -->
            <el-tooltip content="设置" placement="bottom">
              <el-button
                text
                class="settings-btn"
                @click="settingsStore.openSettingsDrawer"
              >
                <el-icon :size="18"><Tools /></el-icon>
              </el-button>
            </el-tooltip>
            <!-- Clerk 用户认证 -->
            <SignedOut>
              <SignInButton mode="modal">
                <el-button type="primary" size="small">登录</el-button>
              </SignInButton>
            </SignedOut>
            <SignedIn>
              <UserButton />
            </SignedIn>
          </div>
        </el-header>

        <!-- 设置抽屉 -->
        <SettingsDrawer />
        <el-main class="app-main">
          <router-view />
        </el-main>
      </el-container>
    </div>
  </el-config-provider>
</template>

<script setup>
import { onMounted } from 'vue'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { HomeFilled, FolderOpened, Setting, Tools, Briefcase } from '@element-plus/icons-vue'
import { SignedIn, SignedOut, SignInButton, UserButton, useAuth } from '@clerk/vue'
import SettingsDrawer from '@/components/common/SettingsDrawer.vue'
import { useSettingsStore } from '@/store/settings'
import { setAuthTokenGetter } from '@/api'

const settingsStore = useSettingsStore()
const { getToken } = useAuth()

// 设置 API 认证 token getter
setAuthTokenGetter(() => getToken.value())

// 初始化设置（从 localStorage 加载）
onMounted(() => {
  settingsStore.init()
})
</script>

<style>
/* ========== CSS变量系统 ========== */
:root {
  /* 主色 - 深蓝色 */
  --color-primary: #2563eb;
  --color-primary-light: #3b82f6;
  --color-primary-lighter: #60a5fa;
  --color-primary-dark: #1d4ed8;
  --color-primary-bg: #eff6ff;
  --color-primary-bg-hover: #dbeafe;

  /* 功能色 */
  --color-success: #10b981;
  --color-success-bg: #ecfdf5;
  --color-warning: #f59e0b;
  --color-warning-bg: #fffbeb;
  --color-danger: #ef4444;
  --color-danger-bg: #fef2f2;
  --color-info: #6b7280;
  --color-info-bg: #f3f4f6;

  /* 文本色 */
  --color-text-primary: #1f2937;
  --color-text-secondary: #4b5563;
  --color-text-tertiary: #6b7280;
  --color-text-placeholder: #9ca3af;
  --color-text-disabled: #d1d5db;

  /* 背景色 */
  --color-bg-page: #f8fafc;
  --color-bg-card: #ffffff;
  --color-bg-secondary: #f1f5f9;
  --color-bg-hover: #f8fafc;

  /* 边框色 */
  --color-border: #e5e7eb;
  --color-border-light: #f3f4f6;
  --color-border-dark: #d1d5db;

  /* 字体系统 */
  --font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  --font-size-xs: 12px;
  --font-size-sm: 13px;
  --font-size-base: 14px;
  --font-size-md: 16px;
  --font-size-lg: 18px;
  --font-size-xl: 20px;
  --font-size-2xl: 24px;
  --font-size-3xl: 28px;

  /* 字重 */
  --font-weight-normal: 400;
  --font-weight-medium: 500;
  --font-weight-semibold: 600;
  --font-weight-bold: 700;

  /* 行高 */
  --line-height-tight: 1.25;
  --line-height-normal: 1.5;
  --line-height-relaxed: 1.75;

  /* 间距系统 */
  --spacing-1: 4px;
  --spacing-2: 8px;
  --spacing-3: 12px;
  --spacing-4: 16px;
  --spacing-5: 20px;
  --spacing-6: 24px;
  --spacing-8: 32px;
  --spacing-10: 40px;

  /* 圆角 */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;

  /* 阴影 */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);

  /* 布局 */
  --max-width: 1400px;
  --header-height: 64px;

  /* ========== Element Plus 主题覆盖 ========== */
  --el-color-primary: var(--color-primary);
  --el-color-primary-light-3: var(--color-primary-light);
  --el-color-primary-light-5: var(--color-primary-lighter);
  --el-color-primary-light-7: #93c5fd;
  --el-color-primary-light-8: #bfdbfe;
  --el-color-primary-light-9: var(--color-primary-bg);
  --el-color-primary-dark-2: var(--color-primary-dark);

  --el-color-success: var(--color-success);
  --el-color-warning: var(--color-warning);
  --el-color-danger: var(--color-danger);
  --el-color-info: var(--color-info);

  --el-text-color-primary: var(--color-text-primary);
  --el-text-color-regular: var(--color-text-secondary);
  --el-text-color-secondary: var(--color-text-tertiary);
  --el-text-color-placeholder: var(--color-text-placeholder);

  --el-border-color: var(--color-border);
  --el-border-color-light: var(--color-border-light);
  --el-border-color-lighter: var(--color-border-light);

  --el-fill-color-light: var(--color-bg-secondary);
  --el-fill-color-lighter: var(--color-bg-hover);

  --el-border-radius-base: var(--radius-md);
  --el-border-radius-small: var(--radius-sm);
}

/* ========== 全局重置 ========== */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  height: 100%;
  font-family: var(--font-family);
}

#app {
  height: 100%;
}

.app-container {
  height: 100%;
}

/* ========== Header 样式 ========== */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  padding: 0 var(--spacing-8);
  height: var(--header-height) !important;
  box-shadow: var(--shadow-sm);
  border-bottom: 1px solid var(--color-border);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-6);
}

.logo {
  display: flex;
  align-items: center;
  text-decoration: none;
}

.logo-img {
  height: 36px;
  width: auto;
  object-fit: contain;
}

.logo:hover .logo-img {
  opacity: 0.85;
  transition: opacity 0.2s;
}

.header-divider {
  width: 1px;
  height: var(--spacing-6);
  background-color: var(--color-border-dark);
}

.nav-links {
  display: flex;
  gap: var(--spacing-2);
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-secondary);
  text-decoration: none;
  font-size: var(--font-size-base);
  padding: var(--spacing-2) var(--spacing-4);
  border-radius: var(--radius-md);
  transition: all 0.2s;
}

.nav-link:hover {
  color: var(--color-primary);
  background-color: var(--color-primary-bg);
}

.nav-link.router-link-active {
  color: var(--color-primary);
  background-color: var(--color-primary-bg-hover);
  font-weight: var(--font-weight-medium);
}

.nav-link .el-icon {
  font-size: var(--font-size-md);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.settings-btn {
  padding: var(--spacing-2);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
}

.settings-btn:hover {
  background-color: var(--color-primary-bg);
  color: var(--color-primary);
}

/* ========== Main 样式 ========== */
.app-main {
  background-color: var(--color-bg-page);
  padding: var(--spacing-6);
  overflow-y: auto;
}
</style>
