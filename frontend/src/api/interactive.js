/**
 * 深度交互审阅模式 API
 */
import axios from 'axios'

const API_BASE_URL = 'https://contract-review-z9te.onrender.com/api'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 180000, // 3 分钟超时，适应对话场景
  headers: {
    'Content-Type': 'application/json'
  }
})

// 用于获取 token 的辅助函数
let getTokenFn = null

export function setInteractiveAuthTokenGetter(fn) {
  getTokenFn = fn
}

// 请求拦截器 - 添加认证 token
api.interceptors.request.use(
  async (config) => {
    if (getTokenFn) {
      try {
        const token = await getTokenFn()
        if (token) {
          config.headers.Authorization = `Bearer ${token}`
        }
      } catch (error) {
        console.error('获取 token 失败:', error)
      }
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器 - 处理错误
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      const { status, data } = error.response
      if (status === 401) {
        console.error('认证失败，请重新登录')
      } else if (status === 402) {
        console.error('配额不足')
      } else if (status === 404) {
        console.error('资源不存在')
      }
      error.message = data?.detail || error.message
    }
    return Promise.reject(error)
  }
)

export default {
  /**
   * 启动统一审阅（支持可选标准）
   * @param {string} taskId - 任务 ID
   * @param {Object} options - 审阅选项
   * @param {string} options.llmProvider - LLM 提供者（'deepseek' | 'gemini'）
   * @param {boolean} options.useStandards - 是否使用审核标准（默认 false）
   * @param {string} options.businessLineId - 业务条线 ID（可选）
   * @param {string} options.specialRequirements - 本次特殊要求（可选）
   */
  startUnifiedReview(taskId, options = {}) {
    const {
      llmProvider = 'deepseek',
      useStandards = false,
      businessLineId = null,
      specialRequirements = null
    } = options

    return api.post(`/tasks/${taskId}/unified-review`, {
      llm_provider: llmProvider,
      use_standards: useStandards,
      business_line_id: businessLineId,
      special_requirements: specialRequirements
    })
  },

  /**
   * 启动快速初审（无标准审阅）- 保留向后兼容
   * @deprecated 请使用 startUnifiedReview 方法
   * @param {string} taskId - 任务 ID
   * @param {string} llmProvider - LLM 提供者（'deepseek' | 'gemini'）
   */
  startQuickReview(taskId, llmProvider = 'deepseek') {
    return api.post(`/tasks/${taskId}/quick-review`, {
      llm_provider: llmProvider
    })
  },

  /**
   * 获取任务的所有交互条目
   * @param {string} taskId - 任务 ID
   */
  getInteractiveItems(taskId) {
    return api.get(`/interactive/${taskId}/items`)
  },

  /**
   * 获取单个条目的详细信息（含对话历史）
   * @param {string} taskId - 任务 ID
   * @param {string} itemId - 条目 ID
   */
  getItemDetail(taskId, itemId) {
    return api.get(`/interactive/${taskId}/items/${itemId}`)
  },

  /**
   * 发送对话消息
   * @param {string} taskId - 任务 ID
   * @param {string} itemId - 条目 ID
   * @param {string} message - 用户消息
   * @param {string} llmProvider - LLM 提供者
   */
  sendChatMessage(taskId, itemId, message, llmProvider = 'deepseek') {
    return api.post(`/interactive/${taskId}/items/${itemId}/chat`, {
      message,
      llm_provider: llmProvider
    })
  },

  /**
   * 标记条目为已完成
   * @param {string} taskId - 任务 ID
   * @param {string} itemId - 条目 ID
   * @param {string|null} finalSuggestion - 最终建议（可选）
   */
  completeItem(taskId, itemId, finalSuggestion = null) {
    return api.post(`/interactive/${taskId}/items/${itemId}/complete`, {
      final_suggestion: finalSuggestion
    })
  },

  /**
   * 获取文档全文内容
   * @param {string} taskId - 任务 ID
   * @returns {Promise<{task_id, document_name, text, paragraphs}>}
   */
  getDocumentText(taskId) {
    return api.get(`/tasks/${taskId}/document/text`)
  }
}
