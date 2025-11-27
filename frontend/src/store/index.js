import { defineStore } from 'pinia'
import api from '@/api'

export const useReviewStore = defineStore('review', {
  state: () => ({
    currentTask: null,
    tasks: [],
    templates: [],
    reviewResult: null,
    isReviewing: false,
    progress: {
      stage: 'idle',
      percentage: 0,
      message: ''
    },
    pollTimer: null
  }),

  getters: {
    hasDocument: (state) => !!state.currentTask?.document_filename,
    hasStandard: (state) => !!state.currentTask?.standard_filename,
    canStartReview: (state) => {
      return state.currentTask &&
             state.currentTask.document_filename &&
             state.currentTask.standard_filename &&
             state.currentTask.status !== 'reviewing'
    },
    isCompleted: (state) => state.currentTask?.status === 'completed',
    isFailed: (state) => state.currentTask?.status === 'failed'
  },

  actions: {
    async fetchTasks() {
      try {
        const response = await api.getTasks()
        this.tasks = response.data
      } catch (error) {
        console.error('获取任务列表失败:', error)
        throw error
      }
    },

    async fetchTemplates() {
      try {
        const response = await api.getTemplates()
        this.templates = response.data
      } catch (error) {
        console.error('获取模板列表失败:', error)
        throw error
      }
    },

    async createTask(payload) {
      try {
        const response = await api.createTask(payload)
        this.currentTask = response.data
        await this.fetchTasks()
        return response.data
      } catch (error) {
        console.error('创建任务失败:', error)
        throw error
      }
    },

    async loadTask(taskId) {
      try {
        const response = await api.getTask(taskId)
        this.currentTask = response.data
        return response.data
      } catch (error) {
        console.error('加载任务失败:', error)
        throw error
      }
    },

    async deleteTask(taskId) {
      try {
        await api.deleteTask(taskId)
        if (this.currentTask?.id === taskId) {
          this.currentTask = null
        }
        await this.fetchTasks()
      } catch (error) {
        console.error('删除任务失败:', error)
        throw error
      }
    },

    async uploadDocument(taskId, file) {
      try {
        await api.uploadDocument(taskId, file)
        await this.loadTask(taskId)
      } catch (error) {
        console.error('上传文档失败:', error)
        throw error
      }
    },

    async uploadStandard(taskId, file) {
      try {
        await api.uploadStandard(taskId, file)
        await this.loadTask(taskId)
      } catch (error) {
        console.error('上传审核标准失败:', error)
        throw error
      }
    },

    async useTemplate(taskId, templateName) {
      try {
        await api.useTemplate(taskId, templateName)
        await this.loadTask(taskId)
      } catch (error) {
        console.error('应用模板失败:', error)
        throw error
      }
    },

    async startReview(taskId) {
      try {
        this.isReviewing = true
        this.progress = { stage: 'analyzing', percentage: 0, message: '正在启动...' }

        await api.startReview(taskId)

        // 开始轮询进度
        this.startPolling(taskId)
      } catch (error) {
        this.isReviewing = false
        console.error('启动审阅失败:', error)
        throw error
      }
    },

    startPolling(taskId) {
      // 清除之前的定时器
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
      }

      const poll = async () => {
        try {
          const response = await api.getTaskStatus(taskId)
          const { status, message, progress } = response.data

          this.progress = progress

          if (this.currentTask) {
            this.currentTask.status = status
            this.currentTask.message = message
          }

          if (status === 'completed') {
            this.isReviewing = false
            this.stopPolling()
            // 加载结果
            await this.loadResult(taskId)
          } else if (status === 'failed') {
            this.isReviewing = false
            this.stopPolling()
          }
        } catch (error) {
          console.error('轮询状态失败:', error)
        }
      }

      // 立即执行一次
      poll()
      // 每 2 秒轮询一次
      this.pollTimer = setInterval(poll, 2000)
    },

    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },

    async loadResult(taskId) {
      try {
        const response = await api.getResult(taskId)
        this.reviewResult = response.data
        return response.data
      } catch (error) {
        console.error('加载结果失败:', error)
        throw error
      }
    },

    async updateModification(taskId, modificationId, updates) {
      try {
        await api.updateModification(taskId, modificationId, updates)
        // 重新加载结果
        await this.loadResult(taskId)
      } catch (error) {
        console.error('更新修改建议失败:', error)
        throw error
      }
    },

    async updateAction(taskId, actionId, confirmed) {
      try {
        await api.updateAction(taskId, actionId, confirmed)
        await this.loadResult(taskId)
      } catch (error) {
        console.error('更新行动建议失败:', error)
        throw error
      }
    },

    resetState() {
      this.currentTask = null
      this.reviewResult = null
      this.isReviewing = false
      this.progress = { stage: 'idle', percentage: 0, message: '' }
      this.stopPolling()
    }
  }
})
