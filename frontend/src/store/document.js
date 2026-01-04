import { defineStore } from 'pinia'
import api from '@/api'

/**
 * 文档状态管理 Store
 *
 * 用途：管理交互式审阅过程中的文档变更
 * - 维护 original 和 draft 两个版本
 * - 跟踪待处理的变更（来自AI工具调用）
 * - 提供 apply/revert 变更的接口
 */
export const useDocumentStore = defineStore('document', {
  state: () => ({
    // 任务ID
    taskId: null,

    // 文档的原始版本（只读）
    original: null,

    // 文档的草稿版本（包含已应用的变更）
    draft: null,

    // 待处理的变更列表
    // 格式: [{ change_id, tool_name, status, data, created_at }]
    pendingChanges: [],

    // 已应用的变更列表
    appliedChanges: [],

    // 已回滚的变更列表
    revertedChanges: [],

    // 加载状态
    loading: false,
  }),

  getters: {
    /**
     * 是否有待处理的变更
     */
    hasPendingChanges: (state) => state.pendingChanges.length > 0,

    /**
     * 获取所有变更（按时间倒序）
     */
    allChanges: (state) => {
      return [...state.pendingChanges, ...state.appliedChanges, ...state.revertedChanges]
        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    },

    /**
     * 按变更ID查找变更
     */
    getChangeById: (state) => (changeId) => {
      return state.allChanges.find(c => c.change_id === changeId)
    },

    /**
     * 文档是否已修改
     */
    hasModifications: (state) => {
      return state.appliedChanges.length > 0
    },
  },

  actions: {
    /**
     * 初始化文档（加载任务的文档内容）
     */
    async initDocument(taskId, documentText) {
      this.taskId = taskId
      this.original = documentText
      this.draft = documentText
      this.pendingChanges = []
      this.appliedChanges = []
      this.revertedChanges = []

      // 从后端加载变更历史
      await this.loadChanges()
    },

    /**
     * 从后端加载变更列表
     */
    async loadChanges() {
      if (!this.taskId) return

      try {
        this.loading = true
        const response = await api.getDocumentChanges(this.taskId)

        // 按状态分类
        this.pendingChanges = response.data.changes.filter(c => c.status === 'pending')
        this.appliedChanges = response.data.changes.filter(c => c.status === 'applied')
        this.revertedChanges = response.data.changes.filter(c => c.status === 'reverted')

        // 重建draft版本（应用所有已应用的变更）
        this._rebuildDraft()
      } catch (error) {
        console.error('加载变更列表失败:', error)
      } finally {
        this.loading = false
      }
    },

    /**
     * 添加一个新的待处理变更（来自SSE doc_update事件）
     */
    addPendingChange(changeId, toolName, data) {
      const change = {
        change_id: changeId,
        tool_name: toolName,
        status: 'pending',
        data,
        created_at: new Date().toISOString(),
      }

      // 避免重复添加
      if (!this.pendingChanges.find(c => c.change_id === changeId)) {
        this.pendingChanges.unshift(change)
      }
    },

    /**
     * 应用一个变更
     */
    async applyChange(changeId) {
      try {
        const response = await api.applyDocumentChange(this.taskId, changeId)

        if (response.data.status === 'applied') {
          // 从pending移到applied
          const change = this.pendingChanges.find(c => c.change_id === changeId)
          if (change) {
            change.status = 'applied'
            this.pendingChanges = this.pendingChanges.filter(c => c.change_id !== changeId)
            this.appliedChanges.unshift(change)
          }

          // 重建draft
          this._rebuildDraft()

          return { success: true, message: '变更已应用' }
        }
      } catch (error) {
        console.error('应用变更失败:', error)
        return { success: false, message: error.message || '应用变更失败' }
      }
    },

    /**
     * 回滚一个已应用的变更
     */
    async revertChange(changeId) {
      try {
        const response = await api.revertDocumentChange(this.taskId, changeId)

        if (response.data.status === 'reverted') {
          // 从applied移到reverted
          const change = this.appliedChanges.find(c => c.change_id === changeId)
          if (change) {
            change.status = 'reverted'
            this.appliedChanges = this.appliedChanges.filter(c => c.change_id !== changeId)
            this.revertedChanges.unshift(change)
          }

          // 重建draft
          this._rebuildDraft()

          return { success: true, message: '变更已回滚' }
        }
      } catch (error) {
        console.error('回滚变更失败:', error)
        return { success: false, message: error.message || '回滚变更失败' }
      }
    },

    /**
     * 批量应用所有待处理的变更
     */
    async applyAllPendingChanges() {
      const results = []
      for (const change of this.pendingChanges) {
        const result = await this.applyChange(change.change_id)
        results.push({ changeId: change.change_id, ...result })
      }
      return results
    },

    /**
     * 清空文档状态
     */
    clearDocument() {
      this.taskId = null
      this.original = null
      this.draft = null
      this.pendingChanges = []
      this.appliedChanges = []
      this.revertedChanges = []
    },

    /**
     * 重建draft版本（私有方法）
     *
     * 通过应用所有已应用的变更到original来生成draft
     */
    _rebuildDraft() {
      if (!this.original) {
        this.draft = null
        return
      }

      // 从original开始
      let draft = this.original

      // 按时间顺序应用所有已应用的变更
      const sortedChanges = [...this.appliedChanges].sort(
        (a, b) => new Date(a.created_at) - new Date(b.created_at)
      )

      for (const change of sortedChanges) {
        draft = this._applyChangeToText(draft, change)
      }

      this.draft = draft
    },

    /**
     * 应用单个变更到文本（私有方法）
     *
     * 根据tool_name执行对应的变更操作
     */
    _applyChangeToText(text, change) {
      const { tool_name, data } = change

      try {
        switch (tool_name) {
          case 'modify_paragraph':
            return this._applyModifyParagraph(text, data)
          case 'batch_replace_text':
            return this._applyBatchReplace(text, data)
          case 'insert_clause':
            return this._applyInsertClause(text, data)
          default:
            console.warn(`未知的工具类型: ${tool_name}`)
            return text
        }
      } catch (error) {
        console.error(`应用变更失败 (${tool_name}):`, error)
        return text
      }
    },

    /**
     * 应用modify_paragraph变更
     */
    _applyModifyParagraph(text, data) {
      const { paragraph_id, new_content } = data
      const paragraphs = text.split('\n\n')

      if (paragraph_id > 0 && paragraph_id <= paragraphs.length) {
        paragraphs[paragraph_id - 1] = new_content
      }

      return paragraphs.join('\n\n')
    },

    /**
     * 应用batch_replace_text变更
     */
    _applyBatchReplace(text, data) {
      const { old_text, new_text } = data
      return text.replaceAll(old_text, new_text)
    },

    /**
     * 应用insert_clause变更
     */
    _applyInsertClause(text, data) {
      const { position, new_clause } = data
      const paragraphs = text.split('\n\n')

      if (position === 'before' && data.before_paragraph_id) {
        const idx = data.before_paragraph_id - 1
        paragraphs.splice(idx, 0, new_clause)
      } else if (position === 'after' && data.after_paragraph_id) {
        const idx = data.after_paragraph_id
        paragraphs.splice(idx, 0, new_clause)
      } else if (position === 'end') {
        paragraphs.push(new_clause)
      }

      return paragraphs.join('\n\n')
    },
  }
})
