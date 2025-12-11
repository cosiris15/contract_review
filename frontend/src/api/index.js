import axios from 'axios'

const API_BASE_URL = 'https://contract-review-z9te.onrender.com/api'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // 增加到 120 秒，适应 Render 免费版冷启动
  headers: {
    'Content-Type': 'application/json'
  }
})

// 用于获取 token 的辅助函数
let getTokenFn = null

export function setAuthTokenGetter(fn) {
  getTokenFn = fn
}

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

// 请求拦截器 - 添加请求追踪和认证
api.interceptors.request.use(
  async config => {
    console.log(`[API] 请求: ${config.method?.toUpperCase()} ${config.url}`)
    connectionState.setConnecting(true)

    // 添加 Clerk 认证 token
    if (getTokenFn) {
      try {
        const token = await getTokenFn()
        if (token) {
          config.headers.Authorization = `Bearer ${token}`
        }
      } catch (error) {
        console.warn('[API] 获取认证 token 失败:', error)
      }
    }

    return config
  },
  error => {
    connectionState.setConnecting(false)
    return Promise.reject(error)
  }
)

// 辅助函数：从 Blob 中提取错误详情
async function extractErrorFromBlob(blob) {
  try {
    const text = await blob.text()
    const json = JSON.parse(text)
    return json.detail || null
  } catch {
    return null
  }
}

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
  async error => {
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
      // 当 responseType 为 blob 时，错误响应的 data 也是 Blob，需要特殊处理
      let detail = error.response.data?.detail
      if (!detail && error.response.data instanceof Blob) {
        detail = await extractErrorFromBlob(error.response.data)
      }

      // 识别配额不足错误 (403 + 特定消息)
      if (status === 403 && detail && (detail.includes('配额') || detail.includes('quota') || detail.includes('Quota'))) {
        errorInfo = {
          type: 'quota_exceeded',
          message: '免费额度已用完',
          detail: detail,
          retryable: false
        }
      } else if (status === 502 || status === 503 || status === 504) {
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
    // data 应包含 name, our_party, material_type, language
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

  updateTask(taskId, data) {
    return api.patch(`/tasks/${taskId}`, data)
  },

  getTaskStatus(taskId) {
    return api.get(`/tasks/${taskId}/status`)
  },

  // 语言检测
  detectLanguage(text) {
    return api.post('/detect-language', { text })
  },

  // 文档预处理（识别合同各方、生成任务名称）
  preprocessDocument(taskId) {
    return api.post(`/tasks/${taskId}/preprocess`)
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
  // llmProvider: 'deepseek' | 'gemini'
  // businessLineId: 业务条线ID（可选）
  // specialRequirements: 本次特殊要求（可选，直接传递给LLM）
  startReview(taskId, llmProvider = 'deepseek', businessLineId = null, specialRequirements = null) {
    const params = { llm_provider: llmProvider }
    if (businessLineId) {
      params.business_line_id = businessLineId
    }
    if (specialRequirements) {
      params.special_requirements = specialRequirements
    }
    return api.post(`/tasks/${taskId}/review`, null, { params })
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

  // Redline 导出（异步模式）
  startRedlineExport(taskId, modificationIds = null, includeComments = false) {
    return api.post(`/tasks/${taskId}/export/redline/start`, {
      modification_ids: modificationIds,
      include_comments: includeComments
    })
  },

  getRedlineExportStatus(taskId) {
    return api.get(`/tasks/${taskId}/export/redline/status`)
  },

  downloadRedlineExport(taskId) {
    return api.get(`/tasks/${taskId}/export/redline/download`, {
      responseType: 'blob'
    })
  },

  // 获取已持久化的 Redline 文件信息
  getRedlineInfo(taskId) {
    return api.get(`/tasks/${taskId}/redline/info`)
  },

  // 下载已持久化的 Redline 文件
  downloadPersistedRedline(taskId) {
    return api.get(`/tasks/${taskId}/redline/download-persisted`, {
      responseType: 'blob'
    })
  },

  // Redline 导出（同步模式，保留兼容性）
  exportRedline(taskId, modificationIds = null, includeComments = false) {
    return api.post(`/tasks/${taskId}/export/redline`, {
      modification_ids: modificationIds,
      include_comments: includeComments
    }, {
      responseType: 'blob',
      timeout: 300000  // Redline 生成可能耗时较长，设置 5 分钟超时
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

  // 从业务信息生成标准
  createStandardsFromBusiness(data) {
    return api.post('/standards/create-from-business', data)
  },

  // ==================== 标准集合 ====================

  // 获取所有标准集合
  // params: { material_type?, language? }
  getCollections(params = {}) {
    return api.get('/standard-library/collections', { params })
  },

  // 推荐标准集合（根据文档内容智能推荐）
  recommendCollections(data) {
    return api.post('/standard-library/collections/recommend', data)
  },

  // 获取单个集合（包含标准列表）
  getCollection(collectionId) {
    return api.get(`/standard-library/collections/${collectionId}`)
  },

  // 创建标准集合
  createCollection(data) {
    return api.post('/standard-library/collections', data)
  },

  // 更新集合信息
  updateCollection(collectionId, data) {
    return api.put(`/standard-library/collections/${collectionId}`, data)
  },

  // 为集合生成适用说明
  generateCollectionUsageInstruction(collectionId) {
    return api.post(`/standard-library/collections/${collectionId}/generate-usage-instruction`)
  },

  // 删除集合（连同删除所有风险点）
  deleteCollection(collectionId, force = false) {
    return api.delete(`/standard-library/collections/${collectionId}`, {
      params: { force }
    })
  },

  // 获取集合内的标准列表（支持筛选）
  getCollectionStandards(collectionId, params = {}) {
    return api.get(`/standard-library/collections/${collectionId}/standards`, { params })
  },

  // 向集合中添加单条标准
  addStandardToCollection(collectionId, data) {
    return api.post(`/standard-library/collections/${collectionId}/standards`, data)
  },

  // 获取集合内的分类列表
  getCollectionCategories(collectionId) {
    return api.get(`/standard-library/collections/${collectionId}/categories`)
  },

  // ==================== 预设模板（兼容旧接口） ====================

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
  },

  // ==================== 业务条线管理 ====================

  // 获取业务条线列表
  // params: { language?, include_preset? }
  getBusinessLines(params = {}) {
    return api.get('/business-lines', { params })
  },

  // 获取业务条线详情（含背景信息）
  getBusinessLine(lineId) {
    return api.get(`/business-lines/${lineId}`)
  },

  // 创建业务条线
  createBusinessLine(data) {
    return api.post('/business-lines', data)
  },

  // 更新业务条线
  updateBusinessLine(lineId, data) {
    return api.put(`/business-lines/${lineId}`, data)
  },

  // 删除业务条线
  deleteBusinessLine(lineId) {
    return api.delete(`/business-lines/${lineId}`)
  },

  // 获取业务条线的背景信息列表
  getBusinessContexts(lineId, params = {}) {
    return api.get(`/business-lines/${lineId}/contexts`, { params })
  },

  // 添加业务背景信息
  addBusinessContext(lineId, data) {
    return api.post(`/business-lines/${lineId}/contexts`, data)
  },

  // 批量添加业务背景信息
  addBusinessContextsBatch(lineId, contexts) {
    return api.post(`/business-lines/${lineId}/contexts/batch`, { contexts })
  },

  // 更新业务背景信息
  updateBusinessContext(contextId, data) {
    return api.put(`/business-contexts/${contextId}`, data)
  },

  // 删除业务背景信息
  deleteBusinessContext(contextId) {
    return api.delete(`/business-contexts/${contextId}`)
  },

  // 获取业务背景分类列表
  getBusinessCategories(language = 'zh-CN') {
    return api.get('/business-categories', { params: { language } })
  },

  // ==================== 配额管理 ====================

  // 获取当前用户配额信息
  getQuota() {
    return api.get('/quota')
  },

  // ==================== 修改建议生成 ====================

  /**
   * 批量为指定风险点生成修改建议
   *
   * 用于"先分析讨论、后统一改动"的工作流程
   *
   * @param {string} taskId - 任务 ID
   * @param {string[]} riskIds - 需要生成修改建议的风险点 ID 列表
   * @param {Object} userNotes - 用户备注，key 为 risk_id，value 为备注内容（可选）
   * @returns {Promise} 包含生成的修改建议列表
   */
  generateModifications(taskId, riskIds, userNotes = null) {
    return api.post(`/tasks/${taskId}/generate-modifications`, {
      risk_ids: riskIds,
      user_notes: userNotes
    })
  },

  /**
   * 为单个风险点生成修改建议（基于讨论结果）
   *
   * 用于用户与 AI 讨论完某个风险点后生成精准的修改建议
   *
   * @param {string} taskId - 任务 ID
   * @param {string} riskId - 风险点 ID
   * @param {string} discussionSummary - 与用户的讨论摘要
   * @param {string} userDecision - 用户的最终决定
   * @returns {Promise} 生成的修改建议
   */
  generateSingleModification(taskId, riskId, discussionSummary, userDecision) {
    return api.post(`/tasks/${taskId}/risks/${riskId}/generate-modification`, {
      discussion_summary: discussionSummary,
      user_decision: userDecision
    })
  }
}
