# SPEC-9: 前端 Gen 3.0 适配

## 1. 概述

本规格将前端对接后端 Gen 3.0 Agentic API (`/api/v3/*`)。核心目标是新增一个独立的 Gen 3.0 审阅页面，实现：上传合同 → SSE 实时接收审阅进度与 diff → 逐条审批/拒绝 → 查看最终结果。

**关键原则：**
- 不修改任何现有 Gen 2.x 代码（`api/index.js`、`api/interactive.js`、`store/index.js`、`store/document.js`、现有 views 和 components）
- 所有新代码放在独立文件中，通过路由和导航入口接入
- 复用现有技术栈：Vue 3 + Pinia + Element Plus + Fetch SSE
- 复用现有模式：`_startOperation/_endOperation` 操作状态追踪、SSE 手动解析、Clerk token 注入

## 2. 文件清单

### 新增文件（共 7 个）

| 文件路径 | 用途 |
|---------|------|
| `frontend/src/api/gen3.js` | Gen 3.0 API 客户端（REST + SSE） |
| `frontend/src/store/gen3Review.js` | Gen 3.0 审阅状态管理 |
| `frontend/src/views/Gen3ReviewView.vue` | Gen 3.0 审阅主页面 |
| `frontend/src/components/gen3/DiffCard.vue` | 单个 diff 审批卡片 |
| `frontend/src/components/gen3/ClauseProgress.vue` | 条款审阅进度条 |
| `frontend/src/components/gen3/UploadPanel.vue` | 文档上传面板 |
| `frontend/src/components/gen3/ReviewSummary.vue` | 审阅完成摘要 |

### 修改文件（共 2 个，最小改动）

| 文件路径 | 改动内容 |
|---------|---------|
| `frontend/src/router/index.js` | 新增 1 条路由 `/gen3/:taskId?` |
| `frontend/src/views/HomeView.vue` | 在"开始审阅"按钮旁新增"Gen 3.0 审阅"入口按钮 |

## 3. 详细规格

### 3.1 API 客户端 — `api/gen3.js`

创建独立的 axios 实例，baseURL 指向 `/api/v3`（生产环境使用完整 Render URL + `/api/v3`）。

**必须实现的方法：**

```javascript
// === REST 方法（使用 axios） ===

// 获取可用领域列表
listDomains()
// GET /api/v3/domains → { domains: [...] }

// 获取领域详情
getDomainDetail(domainId)
// GET /api/v3/domains/{domainId} → { domain_id, review_checklist, ... }

// 启动审阅
startReview(taskId, { domainId, domainSubtype, ourParty, language })
// POST /api/v3/review/start → { task_id, status, graph_run_id }

// 上传文档
uploadDocument(taskId, file, { role, ourParty, language })
// POST /api/v3/review/{taskId}/upload (multipart/form-data)
// → { task_id, document_id, filename, role, total_clauses, structure_type, message }

// 获取文档列表
getDocuments(taskId)
// GET /api/v3/review/{taskId}/documents → { task_id, documents: [...] }

// 获取审阅状态
getStatus(taskId)
// GET /api/v3/review/{taskId}/status → { task_id, is_interrupted, is_complete, ... }

// 获取待审批 diffs
getPendingDiffs(taskId)
// GET /api/v3/review/{taskId}/pending-diffs → { task_id, pending_diffs: [...] }

// 单个审批
approveDiff(taskId, { diffId, decision, feedback, userModifiedText })
// POST /api/v3/review/{taskId}/approve → { diff_id, new_status, message }

// 批量审批
approveBatch(taskId, approvals)
// POST /api/v3/review/{taskId}/approve-batch → { task_id, results: [...] }

// 恢复审阅
resumeReview(taskId)
// POST /api/v3/review/{taskId}/resume → { task_id, status }

// === SSE 方法（使用 fetch + ReadableStream） ===

// 连接事件流
connectEventStream(taskId, callbacks)
// GET /api/v3/review/{taskId}/events (text/event-stream)
// callbacks: { onProgress, onDiffProposed, onComplete, onError }
// 返回: { close() } 用于断开连接
```

**实现要求：**
- 复用现有 Clerk token 注入模式：导出 `setGen3AuthTokenGetter(fn)` 函数
- axios 实例配置 timeout: 120000（与现有一致）
- SSE 使用 fetch + ReadableStream 手动解析（与 `interactive.js` 相同模式）
- SSE 事件类型映射：`review_progress` → `onProgress`，`diff_proposed` → `onDiffProposed`，`review_complete` → `onComplete`，`review_error` → `onError`
- `connectEventStream` 返回一个对象 `{ close() }`，调用 `close()` 时 abort fetch 请求
- 生产环境 BASE_URL: `https://contract-review-z9te.onrender.com/api/v3`

### 3.2 状态管理 — `store/gen3Review.js`

使用 Pinia defineStore，store id 为 `'gen3Review'`。

**State：**

```javascript
state: () => ({
  // 任务元数据
  taskId: null,
  graphRunId: null,
  domainId: 'fidic',
  ourParty: '',
  language: 'zh-CN',

  // 文档
  documents: [],          // [{ document_id, filename, role, total_clauses, uploaded_at }]

  // 审阅进度
  currentClauseIndex: 0,
  totalClauses: 0,
  currentClauseId: null,
  progressMessage: '',

  // Diffs
  pendingDiffs: [],       // 待审批的 DocumentDiff[]
  approvedDiffs: [],      // 已批准
  rejectedDiffs: [],      // 已拒绝

  // 状态
  phase: 'idle',          // 'idle' | 'uploading' | 'reviewing' | 'interrupted' | 'complete' | 'error'
  isComplete: false,
  summary: '',
  error: null,

  // SSE 连接引用
  _sseConnection: null,   // { close() }

  // 操作状态（复用现有模式）
  operationState: {
    currentOperation: null,
    operationMessage: '',
    isLoading: false,
    lastError: null,
  }
})
```

**Getters：**

```javascript
getters: {
  hasDocuments: (state) => state.documents.length > 0,
  canStartReview: (state) => state.documents.some(d => d.role === 'primary'),
  totalDiffs: (state) => state.pendingDiffs.length + state.approvedDiffs.length + state.rejectedDiffs.length,
  reviewProgress: (state) => state.totalClauses > 0 ? Math.round((state.currentClauseIndex / state.totalClauses) * 100) : 0,
  isOperationInProgress: (state) => state.operationState.isLoading,
  currentOperationMessage: (state) => state.operationState.operationMessage,
}
```

**Actions：**

```javascript
actions: {
  // 辅助方法（与现有 store/index.js 模式一致）
  _startOperation(operation, message) { ... },
  _endOperation(error = null) { ... },

  // 生成唯一 taskId
  generateTaskId() {
    return `gen3_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
  },

  // 初始化审阅会话
  async initReview({ domainId, ourParty, language }) {
    // 1. 生成 taskId
    // 2. 调用 gen3Api.startReview(taskId, { domainId, ourParty, language })
    // 3. 保存 graphRunId
    // 4. 设置 phase = 'uploading'（等待用户上传文档）
  },

  // 上传文档
  async uploadDocument(file, role = 'primary') {
    // 1. 调用 gen3Api.uploadDocument(taskId, file, { role, ourParty, language })
    // 2. 将返回的文档信息 push 到 documents[]
    // 3. 如果 role === 'primary'，设置 totalClauses
  },

  // 开始审阅（上传完成后调用）
  async startListening() {
    // 1. 设置 phase = 'reviewing'
    // 2. 调用 gen3Api.connectEventStream(taskId, callbacks)
    // 3. 保存 _sseConnection 引用
    // callbacks:
    //   onProgress: 更新 currentClauseIndex, totalClauses, progressMessage
    //   onDiffProposed: 将 diff push 到 pendingDiffs[]
    //   onComplete: 设置 phase='complete', isComplete=true, summary
    //   onError: 设置 phase='error', error
  },

  // 审批单个 diff
  async approveDiff(diffId, decision, feedback = '') {
    // 1. 调用 gen3Api.approveDiff(taskId, { diffId, decision, feedback })
    // 2. 从 pendingDiffs 移到 approvedDiffs 或 rejectedDiffs
  },

  // 批量审批所有 pending diffs
  async approveAllPending(decision = 'approve') {
    // 1. 构建 approvals 数组
    // 2. 调用 gen3Api.approveBatch(taskId, approvals)
    // 3. 批量移动 diffs
    // 4. 调用 gen3Api.resumeReview(taskId) 恢复图执行
  },

  // 恢复审阅（审批完当前条款后）
  async resumeAfterApproval() {
    // 调用 gen3Api.resumeReview(taskId)
  },

  // 断开 SSE 并重置
  disconnect() {
    if (this._sseConnection) {
      this._sseConnection.close()
      this._sseConnection = null
    }
  },

  // 完全重置
  resetState() {
    this.disconnect()
    // 重置所有 state 到初始值
  }
}
```

### 3.3 路由修改 — `router/index.js`

在现有 routes 数组中，`InteractiveReview` 路由之后新增：

```javascript
{
  path: '/gen3/:taskId?',
  name: 'Gen3Review',
  component: lazyLoadView(() => import('@/views/Gen3ReviewView.vue'), 'Gen3ReviewView'),
  meta: { title: 'Gen 3.0 智能审阅' }
}
```

### 3.4 首页入口 — `HomeView.vue`

在现有"开始审阅"按钮的 `hero-actions` div 中，追加一个按钮：

```html
<el-button
  type="success"
  size="large"
  @click="$router.push('/gen3')"
  class="action-btn"
>
  <el-icon><Opportunity /></el-icon>
  Gen 3.0 审阅
</el-button>
```

需要在 `<script>` 的 import 中添加 `Opportunity` 图标。如果 `Opportunity` 不可用，使用 `MagicStick` 代替。

### 3.5 主页面 — `Gen3ReviewView.vue`

**布局结构（三阶段渐进式）：**

页面根据 `store.phase` 显示不同内容：

**阶段 1：`idle` / `uploading` — 配置与上传**
```
┌─────────────────────────────────────────┐
│ ← 返回    Gen 3.0 智能审阅              │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐    │
│  │  领域选择 (el-select)           │    │
│  │  我方身份 (el-input)            │    │
│  │  语言 (el-radio-group)          │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │  <UploadPanel />                │    │
│  │  拖拽上传 / 已上传文件列表       │    │
│  └─────────────────────────────────┘    │
│                                         │
│  [ 开始审阅 ]                           │
│                                         │
└─────────────────────────────────────────┘
```

**阶段 2：`reviewing` / `interrupted` — 审阅进行中**
```
┌─────────────────────────────────────────┐
│ ← 返回    合同审阅中    3/15 条款       │
├────────────────────┬────────────────────┤
│                    │                    │
│  <ClauseProgress/> │  <DiffCard />      │
│  条款进度列表       │  <DiffCard />      │
│  ● 1.1 已完成      │  <DiffCard />      │
│  ● 1.2 已完成      │                    │
│  ◉ 4.1 审阅中      │  [ 全部批准 ]      │
│  ○ 4.2 待审阅      │  [ 全部拒绝 ]      │
│  ...               │  [ 继续审阅 ]      │
│                    │                    │
└────────────────────┴────────────────────┘
```

**阶段 3：`complete` — 审阅完成**
```
┌─────────────────────────────────────────┐
│ ← 返回    审阅完成 ✓                    │
├─────────────────────────────────────────┤
│                                         │
│  <ReviewSummary />                      │
│  总结、统计、已批准/拒绝的 diff 列表     │
│                                         │
└─────────────────────────────────────────┘
```

**实现要求：**
- 使用 `<script setup>` 语法
- 从 `store/gen3Review.js` 获取状态
- `onMounted` 时：如果 URL 有 `taskId` 参数，尝试恢复会话（调用 `getStatus`）
- `onUnmounted` 时：调用 `store.disconnect()` 断开 SSE
- 在 `main.js` 中注册 `setGen3AuthTokenGetter`（与现有 `setAuthTokenGetter` 和 `setInteractiveAuthTokenGetter` 同位置）

### 3.6 组件 — `UploadPanel.vue`

**Props：**
```javascript
props: {
  documents: { type: Array, default: () => [] },  // 已上传文档列表
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
}
```

**Emits：**
```javascript
emits: ['upload']  // (file: File, role: string) => void
```

**功能：**
- el-upload 拖拽上传区域，accept=".txt,.docx,.pdf,.md"
- 文件大小校验 ≤ 20MB（前端预校验）
- 角色选择：el-radio-group，选项 primary / baseline / supplement / reference，默认 primary
- 已上传文档列表：显示 filename、role、total_clauses
- 同角色重复上传时显示替换提示

### 3.7 组件 — `DiffCard.vue`

**Props：**
```javascript
props: {
  diff: { type: Object, required: true },
  // diff 结构: { diff_id, clause_id, action_type, original_text, proposed_text, reason, risk_level, status }
}
```

**Emits：**
```javascript
emits: ['approve', 'reject']
// approve: (diffId: string, feedback?: string) => void
// reject: (diffId: string, feedback?: string) => void
```

**功能：**
- 卡片布局，顶部显示 clause_id + risk_level 徽章（high=红色, medium=橙色, low=蓝色）
- action_type 标签：replace=修改, delete=删除, insert=新增
- 原文区域（红色背景高亮）和建议文本区域（绿色背景高亮）
- reason 说明文字
- 底部操作栏：批准按钮（绿色）、拒绝按钮（红色）、可选反馈输入框
- 已审批状态：显示 approved/rejected 标签，按钮禁用

### 3.8 组件 — `ClauseProgress.vue`

**Props：**
```javascript
props: {
  currentIndex: { type: Number, default: 0 },
  totalClauses: { type: Number, default: 0 },
  currentClauseId: { type: String, default: '' },
  approvedDiffs: { type: Array, default: () => [] },
  rejectedDiffs: { type: Array, default: () => [] },
}
```

**功能：**
- 顶部进度条（el-progress，百分比 = currentIndex / totalClauses * 100）
- 条款列表：每个条款显示状态图标（已完成 ✓ / 审阅中 ◉ / 待审阅 ○）
- 当前条款高亮
- 底部统计：已审阅 X / 共 Y 条款

### 3.9 组件 — `ReviewSummary.vue`

**Props：**
```javascript
props: {
  summary: { type: String, default: '' },
  approvedDiffs: { type: Array, default: () => [] },
  rejectedDiffs: { type: Array, default: () => [] },
  totalClauses: { type: Number, default: 0 },
}
```

**功能：**
- 统计卡片：总条款数、已批准修改数、已拒绝修改数
- 摘要文本显示
- 已批准 diffs 折叠列表（每项显示 clause_id + 修改摘要）
- 已拒绝 diffs 折叠列表

## 4. SSE 事件处理流程

```
connectEventStream(taskId)
  │
  ├─ event: review_progress
  │   → store.currentClauseIndex = data.current_clause_index
  │   → store.totalClauses = data.total_clauses
  │   → store.currentClauseId = data.current_clause_id
  │   → store.progressMessage = data.message
  │
  ├─ event: diff_proposed
  │   → store.pendingDiffs.push(data)
  │   → 如果 store.phase !== 'interrupted'，设置 phase = 'interrupted'
  │   → UI 自动显示 DiffCard 列表
  │
  ├─ event: approval_required
  │   → store.phase = 'interrupted'
  │   → （可选：播放提示音或显示通知）
  │
  ├─ event: review_complete
  │   → store.phase = 'complete'
  │   → store.isComplete = true
  │   → store.summary = data.summary
  │   → store.disconnect()
  │
  └─ event: review_error
      → store.phase = 'error'
      → store.error = data.message
      → store.disconnect()
```

## 5. 用户操作流程

```
1. 用户从首页点击 "Gen 3.0 审阅" → 进入 /gen3
2. 填写领域(fidic)、我方身份、语言 → 点击"初始化"
   → store.initReview() → 后端创建 graph
   → phase 变为 'uploading'
3. 拖拽上传合同文件 → store.uploadDocument()
   → 后端解析文档，返回条款数
4. 点击"开始审阅" → store.startListening()
   → 建立 SSE 连接
   → phase 变为 'reviewing'
5. SSE 推送 review_progress → 进度条更新
6. SSE 推送 diff_proposed → DiffCard 出现
   → phase 变为 'interrupted'
7. 用户逐个或批量审批 → store.approveDiff() / store.approveAllPending()
8. 审批完成后点击"继续审阅" → store.resumeAfterApproval()
   → phase 回到 'reviewing'
9. 重复 5-8 直到所有条款审阅完成
10. SSE 推送 review_complete → phase 变为 'complete'
    → 显示 ReviewSummary
```

## 6. Clerk Token 注册

在 `frontend/src/main.js` 中，找到现有的 `setAuthTokenGetter` 和 `setInteractiveAuthTokenGetter` 调用位置，追加：

```javascript
import { setGen3AuthTokenGetter } from '@/api/gen3'

// 在 Clerk onAuth 回调中追加：
setGen3AuthTokenGetter(() => clerk.session?.getToken())
```

## 7. 样式规范

- 所有新组件使用 `<style scoped>`
- 颜色变量复用 Element Plus 主题变量（`--el-color-primary`、`--el-color-success`、`--el-color-danger` 等）
- 风险等级颜色：high → `--el-color-danger`，medium → `--el-color-warning`，low → `--el-color-primary`
- 布局使用 CSS Grid 或 Flexbox，不引入额外 CSS 框架
- 响应式：最小宽度 1024px（与现有页面一致）

## 8. 验证标准

| # | 验证项 | 预期结果 |
|---|--------|---------|
| V1 | 路由 `/gen3` 可访问 | 页面正常渲染，无 console 错误 |
| V2 | 初始化审阅 | 调用 `POST /api/v3/review/start` 成功，phase 变为 uploading |
| V3 | 上传文档 | 调用 `POST /api/v3/review/{taskId}/upload` 成功，显示条款数 |
| V4 | SSE 连接 | `GET /api/v3/review/{taskId}/events` 建立连接，收到 review_progress 事件 |
| V5 | Diff 展示 | 收到 diff_proposed 事件后，DiffCard 正确渲染 |
| V6 | 单个审批 | 点击批准/拒绝，调用 approve API，diff 从 pending 移到对应列表 |
| V7 | 批量审批 | "全部批准"按钮调用 approve-batch API |
| V8 | 恢复审阅 | 审批完成后点击"继续审阅"，调用 resume API，SSE 继续推送 |
| V9 | 审阅完成 | 收到 review_complete 事件，显示 ReviewSummary |
| V10 | 现有功能不受影响 | Gen 2.x 的 `/review`、`/interactive` 路由正常工作 |
| V11 | 页面离开清理 | 离开页面时 SSE 连接正确关闭 |

## 9. 不在本 SPEC 范围内

- 导出功能（Word/JSON/Excel）— 后续 SPEC
- 与现有 Gen 2.x 任务系统的数据互通
- 移动端适配
- 国际化（i18n）框架集成
- 用户认证/权限校验（复用现有 Clerk 即可）
