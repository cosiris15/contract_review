import axios from 'axios'

const api = axios.create({
  baseURL: 'https://contract-review-z9te.onrender.com/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 响应拦截器
api.interceptors.response.use(
  response => response,
  error => {
    const message = error.response?.data?.detail || error.message || '请求失败'
    console.error('API Error:', message)
    return Promise.reject(new Error(message))
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

  updateAction(taskId, actionId, confirmed) {
    return api.patch(`/tasks/${taskId}/result/actions/${actionId}`, null, {
      params: { user_confirmed: confirmed }
    })
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
  }
}
