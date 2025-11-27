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
  }
}
