import { defineStore } from 'pinia'

const STORAGE_KEY = 'contract_review_settings'

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    // 智能水平: 'advanced' (高级/Gemini) | 'basic' (初级/DeepSeek)
    intelligenceLevel: 'advanced',
    // 设置抽屉是否显示
    settingsDrawerVisible: false,
  }),

  getters: {
    // 获取后端需要的 LLM 提供者标识
    llmProvider: (state) => {
      return state.intelligenceLevel === 'advanced' ? 'gemini' : 'deepseek'
    },

    // 获取显示文案
    intelligenceLevelText: (state) => {
      return state.intelligenceLevel === 'advanced' ? '高级' : '初级'
    },

    // 获取详细描述
    intelligenceLevelDescription: (state) => {
      return state.intelligenceLevel === 'advanced'
        ? '更精准的风险识别和建议'
        : '快速审阅，经济实惠'
    }
  },

  actions: {
    // 设置智能水平
    setIntelligenceLevel(level) {
      if (level === 'advanced' || level === 'basic') {
        this.intelligenceLevel = level
        this._saveToStorage()
      }
    },

    // 打开设置抽屉
    openSettingsDrawer() {
      this.settingsDrawerVisible = true
    },

    // 关闭设置抽屉
    closeSettingsDrawer() {
      this.settingsDrawerVisible = false
    },

    // 切换设置抽屉
    toggleSettingsDrawer() {
      this.settingsDrawerVisible = !this.settingsDrawerVisible
    },

    // 保存到 localStorage
    _saveToStorage() {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
          intelligenceLevel: this.intelligenceLevel
        }))
      } catch (e) {
        console.error('保存设置失败:', e)
      }
    },

    // 从 localStorage 加载
    _loadFromStorage() {
      try {
        const saved = localStorage.getItem(STORAGE_KEY)
        if (saved) {
          const data = JSON.parse(saved)
          if (data.intelligenceLevel === 'advanced' || data.intelligenceLevel === 'basic') {
            this.intelligenceLevel = data.intelligenceLevel
          }
        }
      } catch (e) {
        console.error('加载设置失败:', e)
      }
    },

    // 初始化（从 localStorage 加载设置）
    init() {
      this._loadFromStorage()
    }
  }
})
