import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import gen3Api from '@/api/gen3'

export const useGen3ReviewStore = defineStore('gen3Review', {
  state: () => ({
    taskId: null,
    graphRunId: null,
    domainId: 'fidic',
    ourParty: '',
    language: 'zh-CN',
    documents: [],
    uploadJobs: [],
    currentClauseIndex: 0,
    totalClauses: 0,
    currentClauseId: null,
    progressMessage: '',
    pendingDiffs: [],
    approvedDiffs: [],
    rejectedDiffs: [],
    phase: 'idle',
    isComplete: false,
    summary: '',
    error: null,
    _sseConnection: null,
    operationState: {
      currentOperation: null,
      operationMessage: '',
      isLoading: false,
      lastError: null
    }
  }),

  getters: {
    hasDocuments: (state) => state.documents.length > 0,
    allUploadsComplete: (state) => state.uploadJobs.length > 0 && state.uploadJobs.every((j) => j.status === 'succeeded'),
    hasFailedUploads: (state) => state.uploadJobs.some((j) => j.status === 'failed'),
    uploadProgress: (state) => {
      if (!state.uploadJobs.length) return 0
      const total = state.uploadJobs.reduce((sum, j) => sum + Number(j.progress || 0), 0)
      return Math.round(total / state.uploadJobs.length)
    },
    canStartReview: (state) => {
      const hasPrimary = state.documents.some((d) => d.role === 'primary')
      const hasUploading = state.uploadJobs.some((j) => ['queued', 'running'].includes(j.status))
      const allSucceeded = state.uploadJobs.length === 0 || state.uploadJobs.every((j) => j.status === 'succeeded')
      return hasPrimary && !hasUploading && allSucceeded
    },
    totalDiffs: (state) => state.pendingDiffs.length + state.approvedDiffs.length + state.rejectedDiffs.length,
    reviewProgress: (state) => (state.totalClauses > 0
      ? Math.round((state.currentClauseIndex / state.totalClauses) * 100)
      : 0),
    isOperationInProgress: (state) => state.operationState.isLoading,
    currentOperationMessage: (state) => state.operationState.operationMessage,
    groupedPendingDiffs: (state) => {
      const groups = {}
      for (const diff of state.pendingDiffs) {
        const key = diff.clause_id || '未知条款'
        if (!groups[key]) groups[key] = []
        groups[key].push(diff)
      }
      return Object.entries(groups).map(([clauseId, diffs]) => ({ clauseId, diffs }))
    },
    handledDiffs: (state) => {
      return [...state.approvedDiffs, ...state.rejectedDiffs]
        .sort((a, b) => (b._handledAt || 0) - (a._handledAt || 0))
    }
  },

  actions: {
    _startOperation(operation, message) {
      this.operationState.currentOperation = operation
      this.operationState.operationMessage = message
      this.operationState.isLoading = true
      this.operationState.lastError = null
    },

    _endOperation(error = null, options = {}) {
      const { setErrorPhase = true } = options
      this.operationState.currentOperation = null
      this.operationState.operationMessage = ''
      this.operationState.isLoading = false
      this.operationState.lastError = error
      if (error && setErrorPhase) {
        this.error = error.message || String(error)
        this.phase = 'error'
      }
    },

    generateTaskId() {
      return `gen3_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    },

    _mergeDocument(doc) {
      const role = doc.role || 'primary'
      this.documents = this.documents.filter((item) => item.role !== role)
      this.documents.push(doc)
    },

    _upsertUploadJob(job) {
      const index = this.uploadJobs.findIndex((item) => item.job_id === job.job_id)
      if (index >= 0) {
        this.uploadJobs[index] = { ...this.uploadJobs[index], ...job }
      } else {
        this.uploadJobs.push(job)
      }
      this.uploadJobs.sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')))
    },

    _moveDiff(diffId, decision) {
      const index = this.pendingDiffs.findIndex((item) => item.diff_id === diffId)
      if (index < 0) {
        return
      }
      const diff = this.pendingDiffs[index]
      this.pendingDiffs.splice(index, 1)
      diff._handledAt = Date.now()
      if (decision === 'approve') {
        diff.status = 'approved'
        this.approvedDiffs.push(diff)
      } else {
        diff.status = 'rejected'
        this.rejectedDiffs.push(diff)
      }
    },

    async initReview({ domainId = 'fidic', ourParty = '', language = 'zh-CN' } = {}) {
      this._startOperation('init_review', '正在初始化 Gen3 审阅...')
      try {
        const taskId = this.generateTaskId()
        const response = await gen3Api.startReview(taskId, {
          domainId,
          ourParty,
          language,
          autoStart: false
        })
        this.taskId = taskId
        this.graphRunId = response.data.graph_run_id
        this.domainId = domainId
        this.ourParty = ourParty
        this.language = language
        this.phase = 'uploading'
        this.error = null
        this.uploadJobs = []
        this._endOperation()
        return response.data
      } catch (error) {
        this._endOperation(error)
        throw error
      }
    },

    async fetchUploadJobs() {
      if (!this.taskId) return []
      const resp = await gen3Api.getUploadJobs(this.taskId)
      this.uploadJobs = resp.data?.jobs || []
      return this.uploadJobs
    },

    async uploadDocument(file, role = 'primary') {
      if (!this.taskId) {
        throw new Error('请先创建审阅任务')
      }
      this._startOperation('upload_document', `正在上传 ${file.name}...`)
      try {
        await this._connectEventStream({ phase: 'uploading' })
        const response = await gen3Api.uploadDocument(this.taskId, file, {
          role,
          ourParty: this.ourParty,
          language: this.language
        })
        this._upsertUploadJob({
          job_id: response.data.job_id,
          task_id: this.taskId,
          role: response.data.role,
          filename: response.data.filename,
          status: response.data.status,
          stage: 'uploaded',
          progress: 0,
          error_message: null,
          result_meta: null,
          created_at: new Date().toISOString()
        })
        this.phase = 'uploading'
        this._endOperation()
        return response.data
      } catch (error) {
        this._endOperation(error)
        throw error
      }
    },

    async retryUploadJob(jobId) {
      if (!this.taskId) throw new Error('任务不存在')
      this._startOperation('retry_upload_job', '正在重试上传任务...')
      try {
        await gen3Api.retryUploadJob(this.taskId, jobId)
        this._upsertUploadJob({ job_id: jobId, status: 'queued', stage: 'uploaded', progress: 0, error_message: null })
        await this._connectEventStream({ phase: 'uploading' })
        this._endOperation()
      } catch (error) {
        this._endOperation(error, { setErrorPhase: false })
        throw error
      }
    },

    async _connectEventStream({ phase = 'reviewing' } = {}) {
      if (!this.taskId) {
        throw new Error('任务不存在')
      }
      this.disconnect()
      this.phase = phase
      this._sseConnection = await gen3Api.connectEventStream(this.taskId, {
        onProgress: (data) => {
          this.currentClauseIndex = data.current_clause_index || 0
          this.totalClauses = data.total_clauses || this.totalClauses
          this.currentClauseId = data.current_clause_id || ''
          this.progressMessage = data.message || ''
        },
        onUploadProgress: (data) => {
          this._upsertUploadJob({
            job_id: data.job_id,
            role: data.role,
            filename: data.filename,
            stage: data.stage,
            progress: data.progress,
            status: data.status,
            error_message: null
          })
          this.phase = 'uploading'
        },
        onUploadComplete: (data) => {
          this._upsertUploadJob({
            job_id: data.job_id,
            role: data.role,
            filename: data.filename,
            stage: data.stage,
            progress: data.progress,
            status: data.status,
            result_meta: data.result_meta,
            error_message: null
          })
          const meta = data.result_meta || {}
          if (meta.document_id && meta.role) {
            this._mergeDocument({
              document_id: meta.document_id,
              filename: meta.filename,
              role: meta.role,
              total_clauses: meta.total_clauses || 0,
              uploaded_at: new Date().toISOString()
            })
            if (meta.role === 'primary') {
              this.totalClauses = meta.total_clauses || this.totalClauses
            }
          }
        },
        onUploadFailed: (data) => {
          this._upsertUploadJob({
            job_id: data.job_id,
            role: data.role,
            filename: data.filename,
            stage: data.stage,
            progress: data.progress,
            status: data.status,
            error_message: data.error || '上传解析失败'
          })
        },
        onDiffProposed: (data) => {
          if (!data?.diff_id) {
            return
          }
          const exists = this.pendingDiffs.some((item) => item.diff_id === data.diff_id)
          if (!exists) {
            this.pendingDiffs.push({ ...data, status: data.status || 'pending' })
          }
          this.phase = 'interrupted'
        },
        onApprovalRequired: () => {
          this.phase = 'interrupted'
        },
        onComplete: (data) => {
          this.summary = data.summary || ''
          this.isComplete = true
          this.phase = 'complete'
          this.disconnect()
        },
        onError: (error) => {
          this.error = error.message || '审阅失败'
          this.phase = 'error'
          this.disconnect()
        }
      })
    },

    async startListening() {
      this._startOperation('start_listening', '正在启动审阅...')
      try {
        await this.fetchUploadJobs()
        await this._connectEventStream({ phase: 'reviewing' })
        await gen3Api.runReview(this.taskId)
        this._endOperation()
      } catch (error) {
        this.disconnect()
        this._endOperation(error)
        throw error
      }
    },

    async approveDiff(diffId, decision, feedback = '', userModifiedText = undefined) {
      if (!this.taskId) {
        throw new Error('任务不存在')
      }
      this._startOperation('approve_diff', '正在提交审批...')
      try {
        await gen3Api.approveDiff(this.taskId, { diffId, decision, feedback, userModifiedText })
        this._moveDiff(diffId, decision)
        this._endOperation()
      } catch (error) {
        this._endOperation(error, { setErrorPhase: false })
        throw error
      }
    },

    async approveAllPending(decision = 'approve') {
      if (!this.taskId || this.pendingDiffs.length === 0) {
        return
      }
      this._startOperation('approve_batch', '正在批量审批...')
      try {
        const approvals = this.pendingDiffs.map((diff) => ({
          diffId: diff.diff_id,
          decision
        }))
        await gen3Api.approveBatch(this.taskId, approvals)
        const moved = [...this.pendingDiffs]
        moved.forEach((diff) => {
          diff.status = decision === 'approve' ? 'approved' : 'rejected'
        })
        if (decision === 'approve') {
          this.approvedDiffs.push(...moved)
        } else {
          this.rejectedDiffs.push(...moved)
        }
        this.pendingDiffs = []
        await gen3Api.resumeReview(this.taskId)
        this.phase = 'reviewing'
        this._endOperation()
      } catch (error) {
        this._endOperation(error, { setErrorPhase: false })
        throw error
      }
    },

    async resumeAfterApproval() {
      if (!this.taskId) {
        return
      }
      this._startOperation('resume_review', '正在恢复审阅...')
      try {
        await gen3Api.resumeReview(this.taskId)
        this.phase = 'reviewing'
        this._endOperation()
      } catch (error) {
        if (error.response?.status === 400) {
          ElMessage.warning(error.response?.data?.detail || '请先完成所有审批再恢复')
          this._endOperation(error, { setErrorPhase: false })
          return
        }
        this._endOperation(error, { setErrorPhase: false })
        throw error
      }
    },

    async recoverSession(taskId) {
      this._startOperation('recover_session', '正在恢复会话...')
      try {
        this.taskId = taskId
        let statusResp
        try {
          statusResp = await gen3Api.getStatus(taskId)
        } catch (error) {
          if (error?.response?.status === 404) {
            await gen3Api.rehydrateSession(taskId)
            statusResp = await gen3Api.getStatus(taskId)
          } else {
            throw error
          }
        }

        const [docsResp, pendingResp, uploadResp] = await Promise.all([
          gen3Api.getDocuments(taskId),
          gen3Api.getPendingDiffs(taskId),
          gen3Api.getUploadJobs(taskId)
        ])

        const status = statusResp.data || {}
        this.graphRunId = status.graph_run_id || null
        this.currentClauseIndex = status.current_clause_index || 0
        this.currentClauseId = status.current_clause_id || ''
        this.totalClauses = status.total_clauses || 0
        this.documents = docsResp.data?.documents || []
        this.pendingDiffs = pendingResp.data?.pending_diffs || []
        this.uploadJobs = uploadResp.data?.jobs || []

        const hasActiveUploads = this.uploadJobs.some((job) => ['queued', 'running'].includes(job.status))
        if (status.is_complete) {
          this.phase = 'complete'
          this.isComplete = true
        } else if (hasActiveUploads) {
          await this._connectEventStream({ phase: 'uploading' })
        } else if (this.pendingDiffs.length > 0 || status.is_interrupted) {
          await this._connectEventStream({ phase: 'interrupted' })
        } else {
          this.phase = this.documents.length > 0 ? 'uploading' : 'uploading'
        }
        this._endOperation()
      } catch (error) {
        this._endOperation(error)
        throw error
      }
    },

    async exportRedline() {
      if (!this.taskId) {
        throw new Error('任务不存在')
      }
      this._startOperation('export_redline', '正在生成红线文档...')
      try {
        const response = await gen3Api.exportRedline(this.taskId)
        this._endOperation()
        return response.data
      } catch (error) {
        this._endOperation(error, { setErrorPhase: false })
        throw error
      }
    },

    async fetchResult() {
      if (!this.taskId) {
        throw new Error('任务不存在')
      }
      const response = await gen3Api.getResult(this.taskId)
      return response.data
    },

    disconnect() {
      if (this._sseConnection) {
        this._sseConnection.close()
        this._sseConnection = null
      }
    },

    resetState() {
      this.disconnect()
      this.taskId = null
      this.graphRunId = null
      this.domainId = 'fidic'
      this.ourParty = ''
      this.language = 'zh-CN'
      this.documents = []
      this.uploadJobs = []
      this.currentClauseIndex = 0
      this.totalClauses = 0
      this.currentClauseId = null
      this.progressMessage = ''
      this.pendingDiffs = []
      this.approvedDiffs = []
      this.rejectedDiffs = []
      this.phase = 'idle'
      this.isComplete = false
      this.summary = ''
      this.error = null
      this.operationState = {
        currentOperation: null,
        operationMessage: '',
        isLoading: false,
        lastError: null
      }
    }
  }
})
