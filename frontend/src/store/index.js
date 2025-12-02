import { defineStore } from 'pinia'
import api, { connectionState } from '@/api'
import { useSettingsStore } from './settings'
import { useQuotaStore } from './quota'

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
    pollTimer: null,

    // 新增：详细的操作状态追踪
    operationState: {
      // 当前正在进行的操作
      currentOperation: null, // 'creating_task' | 'loading_tasks' | 'uploading_document' | 'uploading_standard' | 'starting_review' | null
      // 操作开始时间（用于显示耗时）
      operationStartTime: null,
      // 操作进度消息
      operationMessage: '',
      // 是否正在加载
      isLoading: false,
      // 最后一次错误
      lastError: null,
      // 后端连接状态
      backendStatus: 'unknown' // 'unknown' | 'connecting' | 'ready' | 'error'
    }
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
    isFailed: (state) => state.currentTask?.status === 'failed',

    // 新增 getters
    isOperationInProgress: (state) => state.operationState.isLoading,
    currentOperationMessage: (state) => state.operationState.operationMessage,
    operationError: (state) => state.operationState.lastError,
    isBackendReady: (state) => state.operationState.backendStatus === 'ready'
  },

  actions: {
    // 辅助方法：开始操作
    _startOperation(operation, message) {
      this.operationState.currentOperation = operation
      this.operationState.operationStartTime = Date.now()
      this.operationState.operationMessage = message
      this.operationState.isLoading = true
      this.operationState.lastError = null
    },

    // 辅助方法：结束操作
    _endOperation(error = null) {
      this.operationState.currentOperation = null
      this.operationState.operationStartTime = null
      this.operationState.operationMessage = ''
      this.operationState.isLoading = false
      if (error) {
        this.operationState.lastError = error.errorInfo || {
          type: 'unknown',
          message: error.message || '操作失败',
          detail: null
        }
      }
    },

    // 辅助方法：更新操作消息
    _updateOperationMessage(message) {
      this.operationState.operationMessage = message
    },

    // 检查后端连接状态
    async checkBackendStatus(onProgress) {
      this.operationState.backendStatus = 'connecting'
      this._startOperation('checking_backend', '正在检查后端服务状态...')

      const result = await api.warmupBackend(onProgress)

      if (result.success) {
        this.operationState.backendStatus = 'ready'
        this._endOperation()
        return true
      } else {
        this.operationState.backendStatus = 'error'
        this._endOperation({ message: result.error })
        return false
      }
    },

    async fetchTasks() {
      this._startOperation('loading_tasks', '正在加载任务列表...')
      try {
        const response = await api.getTasks()
        this.tasks = response.data
        this._endOperation()
      } catch (error) {
        console.error('获取任务列表失败:', error)
        this._endOperation(error)
        throw error
      }
    },

    async fetchTemplates() {
      this._startOperation('loading_templates', '正在加载审核模板...')
      try {
        const response = await api.getTemplates()
        this.templates = response.data
        this._endOperation()
      } catch (error) {
        console.error('获取模板列表失败:', error)
        this._endOperation(error)
        throw error
      }
    },

    async createTask(payload) {
      this._startOperation('creating_task', '正在创建审阅任务...')
      try {
        const response = await api.createTask(payload)
        this.currentTask = response.data
        this._updateOperationMessage('任务创建成功，正在刷新任务列表...')
        await this.fetchTasks()
        this._endOperation()
        return response.data
      } catch (error) {
        console.error('创建任务失败:', error)
        this._endOperation(error)
        throw error
      }
    },

    async loadTask(taskId) {
      this._startOperation('loading_task', '正在加载任务详情...')
      try {
        const response = await api.getTask(taskId)
        this.currentTask = response.data
        this._endOperation()
        return response.data
      } catch (error) {
        console.error('加载任务失败:', error)
        this._endOperation(error)
        throw error
      }
    },

    async deleteTask(taskId) {
      this._startOperation('deleting_task', '正在删除任务...')
      try {
        await api.deleteTask(taskId)
        if (this.currentTask?.id === taskId) {
          this.currentTask = null
        }
        await this.fetchTasks()
        this._endOperation()
      } catch (error) {
        console.error('删除任务失败:', error)
        this._endOperation(error)
        throw error
      }
    },

    async uploadDocument(taskId, file) {
      this._startOperation('uploading_document', `正在上传文档: ${file.name}...`)
      try {
        await api.uploadDocument(taskId, file)
        this._updateOperationMessage('上传成功，正在刷新任务状态...')
        await this.loadTask(taskId)
        this._endOperation()
      } catch (error) {
        console.error('上传文档失败:', error)
        this._endOperation(error)
        throw error
      }
    },

    async uploadStandard(taskId, file) {
      this._startOperation('uploading_standard', `正在上传审核标准: ${file.name}...`)
      try {
        await api.uploadStandard(taskId, file)
        this._updateOperationMessage('上传成功，正在刷新任务状态...')
        await this.loadTask(taskId)
        this._endOperation()
      } catch (error) {
        console.error('上传审核标准失败:', error)
        this._endOperation(error)
        throw error
      }
    },

    async useTemplate(taskId, templateName) {
      this._startOperation('applying_template', `正在应用模板: ${templateName}...`)
      try {
        await api.useTemplate(taskId, templateName)
        this._updateOperationMessage('模板应用成功，正在刷新任务状态...')
        await this.loadTask(taskId)
        this._endOperation()
      } catch (error) {
        console.error('应用模板失败:', error)
        this._endOperation(error)
        throw error
      }
    },

    async startReview(taskId, businessLineId = null) {
      this._startOperation('starting_review', '正在启动审阅任务...')
      try {
        this.isReviewing = true
        this.progress = { stage: 'analyzing', percentage: 0, message: '正在启动...' }

        // 获取设置 Store 中的 LLM 提供者
        const settingsStore = useSettingsStore()
        const llmProvider = settingsStore.llmProvider

        await api.startReview(taskId, llmProvider, businessLineId)
        this._updateOperationMessage('审阅任务已启动，正在处理中...')
        this._endOperation()

        // 开始轮询进度
        this.startPolling(taskId)
      } catch (error) {
        this.isReviewing = false
        console.error('启动审阅失败:', error)

        // 检查是否是配额不足错误
        if (error.errorInfo?.type === 'quota_exceeded') {
          this._endOperation({
            errorInfo: {
              type: 'quota_exceeded',
              message: '免费额度已用完',
              detail: '您的免费试用额度已全部使用完毕。如需继续使用，请联系我们获取更多额度。'
            }
          })
        } else {
          this._endOperation(error)
        }
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
            // 刷新配额（审阅完成后会扣费）
            const quotaStore = useQuotaStore()
            quotaStore.refreshQuota()
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
        // 本地更新，避免重新加载覆盖UI状态
        if (this.reviewResult?.modifications) {
          const mod = this.reviewResult.modifications.find(m => m.id === modificationId)
          if (mod) {
            if (updates.user_modified_text !== undefined) {
              mod.user_modified_text = updates.user_modified_text
            }
            if (updates.user_confirmed !== undefined) {
              mod.user_confirmed = updates.user_confirmed
            }
          }
        }
      } catch (error) {
        console.error('更新修改建议失败:', error)
        throw error
      }
    },

    async updateAction(taskId, actionId, updates) {
      try {
        await api.updateAction(taskId, actionId, updates)
        // 本地更新，避免重新加载
        if (this.reviewResult?.actions) {
          const action = this.reviewResult.actions.find(a => a.id === actionId)
          if (action) {
            if (typeof updates === 'object') {
              Object.assign(action, updates)
            } else if (typeof updates === 'boolean') {
              action.user_confirmed = updates
            }
          }
        }
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
