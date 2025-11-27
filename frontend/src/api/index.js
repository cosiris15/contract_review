import axios from 'axios'

const API_BASE_URL = 'https://contract-review-z9te.onrender.com/api'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // 增加到 120 秒，适应 Render 免费版冷启动
  headers: {
    'Content-Type': 'application/json'
  }
})

// 连接状态追踪
export const connectionState = {
  isConnecting: false,
  isBackendReady: false,
  lastError: null,
  retryCount: 0,
  maxRetries: 3,
  listeners: new Set(),

  notify() {
    this.listeners.forEach(fn => fn(this.getState()))
  },

  subscribe(fn) {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  },

  getState() {
    return {
      isConnecting: this.isConnecting,
      isBackendReady: this.isBackendReady,
      lastError: this.lastError,
      retryCount: this.retryCount
    }
  },

  setConnecting(value) {
    this.isConnecting = value
    this.notify()
  },

  setBackendReady(value) {
    this.isBackendReady = value
    this.notify()
  },

  setError(error) {
    this.lastError = error
    this.notify()
  },

  clearError() {
    this.lastError = null
    this.notify()
  },

  incrementRetry() {
    this.retryCount++
    this.notify()
    return this.retryCount <= this.maxRetries
  },

  resetRetry() {
    this.retryCount = 0
    this.notify()
  }
}

// 请求拦截器 - 添加请求追踪
api.interceptors.request.use(
  config => {
    console.log(`[API] 请求: ${config.method?.toUpperCase()} ${config.url}`)
    connectionState.setConnecting(true)
    return config
  },
  error => {
    connectionState.setConnecting(false)
    return Promise.reject(error)
  }
)

// 响应拦截器 - 详细错误处理
api.interceptors.response.use(
  response => {
    connectionState.setConnecting(false)
    connectionState.setBackendReady(true)
    connectionState.clearError()
    connectionState.resetRetry()
    console.log(`[API] 响应成功: ${response.config.url}`)
    return response
  },
  error => {
    connectionState.setConnecting(false)

    let errorInfo = {
      type: 'unknown',
      message: '未知错误',
      detail: null,
      retryable: false
    }

    if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
      errorInfo = {
        type: 'timeout',
        message: '请求超时，后端服务可能正在启动中',
        detail: 'Render 免费版服务在空闲后会休眠，首次请求可能需要等待 30-60 秒',
        retryable: true
      }
    } else if (error.code === 'ERR_NETWORK' || !error.response) {
      errorInfo = {
        type: 'network',
        message: '网络连接失败',
        detail: '无法连接到后端服务，请检查网络连接或稍后重试',
        retryable: true
      }
    } else if (error.response) {
      const status = error.response.status
      const detail = error.response.data?.detail

      if (status === 502 || status === 503 || status === 504) {
        errorInfo = {
          type: 'backend_unavailable',
          message: '后端服务暂时不可用',
          detail: 'Render 免费版服务正在启动，请等待 30-60 秒后重试',
          retryable: true
        }
      } else if (status === 404) {
        errorInfo = {
          type: 'not_found',
          message: detail || '请求的资源不存在',
          detail: null,
          retryable: false
        }
      } else if (status >= 400 && status < 500) {
        errorInfo = {
          type: 'client_error',
          message: detail || '请求参数错误',
          detail: `HTTP ${status}`,
          retryable: false
        }
      } else if (status >= 500) {
        errorInfo = {
          type: 'server_error',
          message: detail || '服务器内部错误',
          detail: `HTTP ${status}`,
          retryable: true
        }
      }
    }

    connectionState.setError(errorInfo)
    console.error(`[API] 请求失败:`, errorInfo)

    // 创建增强的错误对象
    const enhancedError = new Error(errorInfo.message)
    enhancedError.errorInfo = errorInfo
    enhancedError.originalError = error

    return Promise.reject(enhancedError)
  }
)

export default {
  // 任务管理
  createTask(data) {
    return api.post('/tasks', data)
  },

  getTasks(limit = 100) {
    return api.get('/tasks', { params: { limit } })
  },

  getTask(taskId) {
    return api.get(`/tasks/${taskId}`)
  },

  deleteTask(taskId) {
    return api.delete(`/tasks/${taskId}`)
  },

  getTaskStatus(taskId) {
    return api.get(`/tasks/${taskId}/status`)
  },

  // 文件上传
  uploadDocument(taskId, file) {
    const formData = new FormData()
    formData.append('file', file)
    return api.post(`/tasks/${taskId}/document`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  uploadStandard(taskId, file) {
    const formData = new FormData()
    formData.append('file', file)
    return api.post(`/tasks/${taskId}/standard`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  useTemplate(taskId, templateName) {
    return api.post(`/tasks/${taskId}/standard/template`, null, {
      params: { template_name: templateName }
    })
  },

  // 审阅
  startReview(taskId) {
    return api.post(`/tasks/${taskId}/review`)
  },

  // 结果
  getResult(taskId) {
    return api.get(`/tasks/${taskId}/result`)
  },

  updateModification(taskId, modificationId, data) {
    return api.patch(`/tasks/${taskId}/result/modifications/${modificationId}`, data)
  },

  updateAction(taskId, actionId, updates) {
    // 如果只是boolean，保持向后兼容
    if (typeof updates === 'boolean') {
      return api.patch(`/tasks/${taskId}/result/actions/${actionId}`, null, {
        params: { user_confirmed: updates }
      })
    }
    // 否则发送完整的更新对象
    return api.patch(`/tasks/${taskId}/result/actions/${actionId}`, updates)
  },

  // 导出
  exportJson(taskId) {
    return `https://contract-review-z9te.onrender.com/api/tasks/${taskId}/export/json`
  },

  exportExcel(taskId) {
    return `https://contract-review-z9te.onrender.com/api/tasks/${taskId}/export/excel`
  },

  exportCsv(taskId) {
    return `https://contract-review-z9te.onrender.com/api/tasks/${taskId}/export/csv`
  },

  exportReport(taskId) {
    return `https://contract-review-z9te.onrender.com/api/tasks/${taskId}/export/report`
  },

  // Redline 导出
  exportRedline(taskId, modificationIds = null, includeComments = false) {
    return api.post(`/tasks/${taskId}/export/redline`, {
      modification_ids: modificationIds,
      include_comments: includeComments
    }, {
      responseType: 'blob'
    })
  },

  getRedlinePreview(taskId) {
    return api.get(`/tasks/${taskId}/export/redline/preview`)
  },

  // 模板
  getTemplates() {
    return api.get('/templates')
  },

  downloadTemplate(templateName) {
    return `https://contract-review-z9te.onrender.com/api/templates/${templateName}`
  },

  // 健康检查
  health() {
    return api.get('/health')
  },

  // 预热后端服务 - 带重试逻辑
  async warmupBackend(onProgress) {
    const maxAttempts = 5
    const retryDelay = 3000 // 3秒

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        if (onProgress) {
          onProgress({
            attempt,
            maxAttempts,
            message: attempt === 1
              ? '正在连接后端服务...'
              : `后端服务正在启动，正在重试 (${attempt}/${maxAttempts})...`
          })
        }

        const response = await api.get('/health', { timeout: 30000 })
        connectionState.setBackendReady(true)
        return { success: true, data: response.data }
      } catch (error) {
        console.log(`[API] 预热尝试 ${attempt}/${maxAttempts} 失败:`, error.message)

        if (attempt < maxAttempts) {
          if (onProgress) {
            onProgress({
              attempt,
              maxAttempts,
              message: `连接失败，${retryDelay/1000}秒后重试...`
            })
          }
          await new Promise(resolve => setTimeout(resolve, retryDelay))
        }
      }
    }

    return {
      success: false,
      error: '无法连接到后端服务，请稍后再试或刷新页面'
    }
  },

  // ==================== 标准库管理 ====================

  // 获取标准库统计信息
  getLibraryStats() {
    return api.get('/standard-library')
  },

  // 获取标准列表
  getLibraryStandards(params = {}) {
    return api.get('/standard-library/standards', { params })
  },

  // 创建标准
  createLibraryStandard(data) {
    return api.post('/standard-library/standards', data)
  },

  // 批量创建标准
  batchCreateLibraryStandards(standards) {
    return api.post('/standard-library/standards/batch', { standards })
  },

  // 获取单条标准
  getLibraryStandard(standardId) {
    return api.get(`/standard-library/standards/${standardId}`)
  },

  // 更新标准
  updateLibraryStandard(standardId, data) {
    return api.put(`/standard-library/standards/${standardId}`, data)
  },

  // 删除标准
  deleteLibraryStandard(standardId) {
    return api.delete(`/standard-library/standards/${standardId}`)
  },

  // 获取所有分类
  getLibraryCategories() {
    return api.get('/standard-library/categories')
  },

  // 导出标准库
  exportLibrary(format = 'csv') {
    return `https://contract-review-z9te.onrender.com/api/standard-library/export?format=${format}`
  },

  // 导入标准到标准库
  importToLibrary(file, replace = false) {
    const formData = new FormData()
    formData.append('file', file)
    return api.post(`/standard-library/import?replace=${replace}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  // 预览标准文件
  previewStandards(file) {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/standards/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  // 保存标准到库
  saveToLibrary(data) {
    return api.post('/standards/save-to-library', data)
  },

  // 生成适用说明
  generateUsageInstruction(data) {
    return api.post('/standards/generate-usage-instruction', data)
  },

  // 推荐标准
  recommendStandards(data) {
    return api.post('/standards/recommend', data)
  },

  // AI 辅助修改标准
  aiModifyStandard(standardId, instruction) {
    return api.post(`/standards/${standardId}/ai-modify`, {
      instruction: instruction
    })
  },

  // ==================== 预设模板 ====================

  // 获取预设模板列表（包含完整标准内容）
  getPresetTemplates() {
    return api.get('/preset-templates')
  },

  // 获取单个预设模板详情
  getPresetTemplate(templateId) {
    return api.get(`/preset-templates/${templateId}`)
  },

  // ==================== 特殊要求整合 ====================

  // 整合特殊要求到审核标准
  mergeSpecialRequirements(data) {
    return api.post('/standards/merge-special-requirements', data)
  }
}
