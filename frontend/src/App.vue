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
              <router-link to="/standards" class="nav-link">
                <el-icon><Setting /></el-icon>
                <span>标准管理</span>
              </router-link>
            </nav>
          </div>
          <div class="header-right">
            <el-tag type="info" effect="plain" size="small" class="version-tag">v1.0.0</el-tag>
          </div>
        </el-header>
        <el-main class="app-main">
          <router-view />
        </el-main>
      </el-container>
    </div>
  </el-config-provider>
</template>

<script setup>
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { HomeFilled, Setting } from '@element-plus/icons-vue'
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

#app {
  height: 100%;
}

.app-container {
  height: 100%;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  color: #303133;
  padding: 0 32px;
  height: 64px !important;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
  border-bottom: 1px solid #e4e7ed;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 24px;
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
  height: 24px;
  background-color: #dcdfe6;
}

.nav-links {
  display: flex;
  gap: 8px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #606266;
  text-decoration: none;
  font-size: 14px;
  padding: 8px 16px;
  border-radius: 6px;
  transition: all 0.2s;
}

.nav-link:hover {
  color: #2563eb;
  background-color: #f0f5ff;
}

.nav-link.router-link-active {
  color: #2563eb;
  background-color: #e8f0fe;
  font-weight: 500;
}

.nav-link .el-icon {
  font-size: 16px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.version-tag {
  background-color: #f4f4f5;
  border-color: #e4e7ed;
  color: #909399;
}

.app-main {
  background-color: #f5f7fa;
  padding: 24px;
  overflow-y: auto;
}
</style>
