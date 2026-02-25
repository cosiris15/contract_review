import axios from 'axios'

const API_BASE_URL = import.meta.env.PROD
  ? 'https://contract-review-z9te.onrender.com/api/v3'
  : '/api/v3'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
  headers: {
    'Content-Type': 'application/json'
  }
})

let getTokenFn = null

export function setGen3AuthTokenGetter(fn) {
  getTokenFn = fn
}

api.interceptors.request.use(
  async (config) => {
    if (getTokenFn) {
      try {
        const token = await getTokenFn()
        if (token) {
          config.headers.Authorization = `Bearer ${token}`
        }
      } catch (error) {
        console.error('获取 Gen3 token 失败:', error)
      }
    }
    return config
  },
  (error) => Promise.reject(error)
)

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const rawDetail = error.response?.data?.detail
    const detailText = typeof rawDetail === 'string'
      ? rawDetail
      : (rawDetail?.message || rawDetail?.error || '')
    const isQuotaExceeded = status === 403 && (
      (typeof detailText === 'string' && /quota|配额/i.test(detailText)) ||
      rawDetail?.error === 'quota_exceeded'
    )

    error.errorInfo = {
      type: isQuotaExceeded ? 'quota_exceeded' : 'gen3_api_error',
      status: status || 0,
      detail: rawDetail || null
    }

    if (isQuotaExceeded) {
      error.message = '免费额度已用完，请先充值后重试'
    } else if (detailText) {
      error.message = detailText
    }

    return Promise.reject(error)
  }
)

async function getBearerToken() {
  if (!getTokenFn) {
    return ''
  }
  try {
    return (await getTokenFn()) || ''
  } catch (error) {
    console.error('获取 Gen3 token 失败:', error)
    return ''
  }
}

function parseSsePayload(raw) {
  try {
    return JSON.parse(raw)
  } catch (error) {
    console.warn('Gen3 SSE JSON 解析失败:', raw, error)
    return null
  }
}

const gen3Api = {
  listDomains() {
    return api.get('/domains')
  },

  getDomainDetail(domainId) {
    return api.get(`/domains/${domainId}`)
  },

  startReview(taskId, options = {}) {
    const {
      domainId = 'fidic',
      domainSubtype = null,
      ourParty = '',
      language = 'zh-CN',
      autoStart = false
    } = options
    return api.post('/review/start', {
      task_id: taskId,
      domain_id: domainId,
      domain_subtype: domainSubtype,
      our_party: ourParty,
      language,
      auto_start: autoStart
    })
  },

  uploadDocument(taskId, file, options = {}) {
    const {
      role = 'primary',
      ourParty = '',
      language = 'zh-CN'
    } = options
    const formData = new FormData()
    formData.append('file', file)
    formData.append('role', role)
    formData.append('our_party', ourParty)
    formData.append('language', language)
    return api.post(`/review/${taskId}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      // Large doc parsing/OCR/LLM may exceed default 120s on cloud environments.
      timeout: 600000
    })
  },

  getDocuments(taskId) {
    return api.get(`/review/${taskId}/documents`)
  },

  getStatus(taskId) {
    return api.get(`/review/${taskId}/status`)
  },

  getPendingDiffs(taskId) {
    return api.get(`/review/${taskId}/pending-diffs`)
  },

  getClauseContext(taskId, clauseId) {
    return api.get(`/review/${taskId}/clause/${clauseId}/context`)
  },

  approveDiff(taskId, payload) {
    return api.post(`/review/${taskId}/approve`, {
      diff_id: payload.diffId,
      decision: payload.decision,
      feedback: payload.feedback || null,
      user_modified_text: payload.userModifiedText || null
    })
  },

  approveBatch(taskId, approvals) {
    return api.post(`/review/${taskId}/approve-batch`, {
      approvals: approvals.map((item) => ({
        diff_id: item.diffId,
        decision: item.decision,
        feedback: item.feedback || null,
        user_modified_text: item.userModifiedText || null
      }))
    })
  },

  resumeReview(taskId) {
    return api.post(`/review/${taskId}/resume`)
  },

  runReview(taskId) {
    return api.post(`/review/${taskId}/run`)
  },

  exportRedline(taskId) {
    return api.post(`/review/${taskId}/export`, null, {
      responseType: 'blob',
      timeout: 60000
    })
  },

  getResult(taskId) {
    return api.get(`/review/${taskId}/result`)
  },

  async connectEventStream(taskId, callbacks = {}) {
    const {
      onProgress,
      onDiffProposed,
      onApprovalRequired,
      onComplete,
      onError
    } = callbacks

    const controller = new AbortController()
    const decoder = new TextDecoder()
    let reconnectAttempts = 0
    const maxReconnectAttempts = 5
    let reconnectTimer = null

    const clearReconnectTimer = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
    }

    const scheduleReconnect = () => {
      if (controller.signal.aborted) return false
      if (reconnectAttempts >= maxReconnectAttempts) return false
      reconnectAttempts += 1
      const delayMs = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 8000)
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        startStream()
      }, delayMs)
      return true
    }

    const startStream = async () => {
      try {
        // TODO: SSE 长连接场景下 token 可能过期，后续补充自动重连与 token 刷新。
        const token = await getBearerToken()
        const response = await fetch(`${API_BASE_URL}/review/${taskId}/events`, {
          method: 'GET',
          headers: {
            'Authorization': token ? `Bearer ${token}` : ''
          },
          signal: controller.signal
        })

        if (!response.ok) {
          const detail = await response.json().catch(() => ({}))
          throw new Error(detail?.detail || `HTTP ${response.status}`)
        }

        reconnectAttempts = 0
        const reader = response.body.getReader()
        let buffer = ''
        let currentEvent = null

        while (true) {
          const { done, value } = await reader.read()
          if (done) {
            if (!scheduleReconnect() && onError) {
              onError(new Error('审阅事件流连接已断开'))
            }
            break
          }

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            const cleaned = line.replace(/\r$/, '')
            if (cleaned.startsWith('event: ')) {
              currentEvent = cleaned.slice(7).trim()
            } else if (cleaned.startsWith('data: ')) {
              const data = parseSsePayload(cleaned.slice(6))
              if (!data) {
                currentEvent = null
                continue
              }

              switch (currentEvent) {
                case 'review_progress':
                  if (onProgress) onProgress(data)
                  break
                case 'diff_proposed':
                  if (onDiffProposed) onDiffProposed(data)
                  break
                case 'approval_required':
                  if (onApprovalRequired) onApprovalRequired(data)
                  break
                case 'review_complete':
                  if (onComplete) onComplete(data)
                  break
                case 'review_error':
                  if (onError) onError(new Error(data.message || '审阅失败'))
                  break
                case 'heartbeat':
                  break
              }
              currentEvent = null
            }
          }
        }
      } catch (error) {
        if (error?.name === 'AbortError') return
        if (!scheduleReconnect() && onError) {
          onError(error)
        }
      }
    }

    startStream()

    return {
      close() {
        clearReconnectTimer()
        controller.abort()
      }
    }
  }
}

export default gen3Api
