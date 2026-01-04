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
      useStandards,
      businessLineId = null,
      specialRequirements = null
    } = options

    // 确保 useStandards 是布尔值（防止 null/undefined 传递给后端）
    const safeUseStandards = Boolean(useStandards)

    return api.post(`/tasks/${taskId}/unified-review`, {
      llm_provider: llmProvider,
      use_standards: safeUseStandards,
      business_line_id: businessLineId,
      special_requirements: specialRequirements
    })
  },

  /**
   * 启动流式统一审阅（SSE）- 边审边返回风险点
   * @param {string} taskId - 任务 ID
   * @param {Object} options - 审阅选项
   * @param {string} options.llmProvider - LLM 提供者（'deepseek' | 'gemini'）
   * @param {boolean} options.useStandards - 是否使用审核标准（默认 false）
   * @param {string} options.businessLineId - 业务条线 ID（可选）
   * @param {string} options.specialRequirements - 本次特殊要求（可选）
   * @param {Object} callbacks - 回调函数
   * @param {Function} callbacks.onStart - 审阅开始 {task_id}
   * @param {Function} callbacks.onProgress - 进度更新 {percentage, message}
   * @param {Function} callbacks.onRisk - 收到新风险点 {data, index}
   * @param {Function} callbacks.onComplete - 审阅完成 {summary, actions, total_risks}
   * @param {Function} callbacks.onError - 错误 {message}
   * @returns {Promise<void>}
   */
  async startUnifiedReviewStream(taskId, options = {}, callbacks = {}) {
    const {
      llmProvider = 'deepseek',
      useStandards,
      businessLineId = null,
      specialRequirements = null
    } = options
    const { onStart, onProgress, onRisk, onComplete, onError } = callbacks

    // 确保 useStandards 是布尔值（防止 null/undefined 传递给后端）
    const safeUseStandards = Boolean(useStandards)

    // 获取 token
    let token = ''
    if (getTokenFn) {
      try {
        token = await getTokenFn()
      } catch (error) {
        console.error('获取 token 失败:', error)
      }
    }

    // 使用 fetch API 进行 SSE 请求
    try {
      const response = await fetch(`${API_BASE_URL}/tasks/${taskId}/unified-review-stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': token ? `Bearer ${token}` : '',
        },
        body: JSON.stringify({
          llm_provider: llmProvider,
          use_standards: safeUseStandards,
          business_line_id: businessLineId,
          special_requirements: specialRequirements
        })
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: '请求失败' }))
        // 处理 detail 可能是对象或数组的情况（FastAPI 422 错误格式）
        let errorMessage = `HTTP ${response.status}`
        if (error.detail) {
          if (typeof error.detail === 'string') {
            errorMessage = error.detail
          } else if (Array.isArray(error.detail)) {
            // FastAPI 默认的 422 格式: [{loc: [...], msg: "...", type: "..."}]
            const firstError = error.detail[0]
            if (firstError && firstError.msg) {
              const loc = (firstError.loc || []).join(' -> ')
              errorMessage = `参数验证失败 (${loc}): ${firstError.msg}`
            }
          } else if (typeof error.detail === 'object') {
            errorMessage = JSON.stringify(error.detail)
          }
        }
        throw new Error(errorMessage)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 解析 SSE 事件
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // 保留未完成的行

        let currentEvent = null
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ') && currentEvent) {
            try {
              const data = JSON.parse(line.slice(6))

              switch (currentEvent) {
                case 'start':
                  if (onStart) onStart(data)
                  break
                case 'progress':
                  if (onProgress) onProgress(data)
                  break
                case 'risk':
                  if (onRisk) onRisk(data)
                  break
                case 'complete':
                  if (onComplete) onComplete(data)
                  break
                case 'error':
                  if (onError) onError(new Error(data.message))
                  break
              }
            } catch (e) {
              // 忽略无法解析的行
              console.warn('SSE 解析失败:', line, e)
            }
            currentEvent = null
          }
        }
      }
    } catch (error) {
      if (onError) onError(error)
      throw error
    }
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
   * 发送流式对话消息（SSE）
   * @param {string} taskId - 任务 ID
   * @param {string} itemId - 条目 ID
   * @param {string} message - 用户消息
   * @param {string} llmProvider - LLM 提供者
   * @param {Object} callbacks - 回调函数
   * @param {Function} callbacks.onChunk - 收到文本片段时的回调
   * @param {Function} callbacks.onSuggestion - 收到更新建议时的回调
   * @param {Function} callbacks.onDone - 完成时的回调
   * @param {Function} callbacks.onError - 错误时的回调
   * @returns {Promise<void>}
   */
  async sendChatMessageStream(taskId, itemId, message, llmProvider = 'deepseek', callbacks = {}) {
    const {
      onChunk,
      onSuggestion,
      onDone,
      onError,
      // 新增：工具调用相关回调
      onToolThinking,
      onToolCall,
      onToolResult,
      onToolError,
      onDocUpdate,
      onMessageDelta
    } = callbacks

    // 获取 token
    let token = ''
    if (getTokenFn) {
      try {
        token = await getTokenFn()
      } catch (error) {
        console.error('获取 token 失败:', error)
      }
    }

    // 使用 fetch API 进行 SSE 请求（POST 方法）
    try {
      const response = await fetch(`${API_BASE_URL}/interactive/${taskId}/items/${itemId}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': token ? `Bearer ${token}` : '',
        },
        body: JSON.stringify({
          message,
          llm_provider: llmProvider
        })
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: '请求失败' }))
        // 处理 detail 可能是对象或数组的情况（FastAPI 422 错误格式）
        let errorMessage = `HTTP ${response.status}`
        if (error.detail) {
          if (typeof error.detail === 'string') {
            errorMessage = error.detail
          } else if (Array.isArray(error.detail)) {
            const firstError = error.detail[0]
            if (firstError && firstError.msg) {
              const loc = (firstError.loc || []).join(' -> ')
              errorMessage = `参数验证失败 (${loc}): ${firstError.msg}`
            }
          } else if (typeof error.detail === 'object') {
            errorMessage = JSON.stringify(error.detail)
          }
        }
        throw new Error(errorMessage)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 解析 SSE 事件
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // 保留未完成的行

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              const { type, content, data: eventData } = data

              switch (type) {
                case 'chunk':
                  if (onChunk) onChunk(content)
                  break
                case 'suggestion':
                  if (onSuggestion) onSuggestion(content)
                  break
                case 'done':
                  if (onDone) onDone(content)
                  break
                case 'error':
                  if (onError) onError(new Error(content))
                  break

                // 新增：工具调用相关事件
                case 'tool_thinking':
                  if (onToolThinking) onToolThinking(content)
                  break
                case 'tool_call':
                  if (onToolCall) onToolCall(eventData)
                  break
                case 'tool_result':
                  if (onToolResult) onToolResult(eventData)
                  break
                case 'tool_error':
                  if (onToolError) onToolError(eventData)
                  break
                case 'doc_update':
                  if (onDocUpdate) onDocUpdate(eventData)
                  break
                case 'message_delta':
                  if (onMessageDelta) onMessageDelta(content)
                  break
              }
            } catch (e) {
              console.error('解析 SSE 事件失败:', e)
              // 忽略无法解析的行
            }
          }
        }
      }
    } catch (error) {
      if (onError) onError(error)
      throw error
    }
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
   * 跳过条目
   * @param {string} taskId - 任务 ID
   * @param {string} itemId - 条目 ID (risk_id)
   */
  skipItem(taskId, itemId) {
    return api.post(`/interactive/${taskId}/items/${itemId}/skip`)
  },

  /**
   * 为单个风险点生成修改建议
   * @param {string} taskId - 任务 ID
   * @param {string} riskId - 风险点 ID
   * @param {string} discussionSummary - 讨论摘要
   * @param {string} userDecision - 用户决策
   * @returns {Promise<{id, suggested_text, modification_reason}>}
   */
  generateSingleModification(taskId, riskId, discussionSummary = '', userDecision = '') {
    return api.post(`/tasks/${taskId}/risks/${riskId}/generate-modification`, {
      discussion_summary: discussionSummary,
      user_decision: userDecision
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
