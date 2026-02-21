# SPEC-9 代码评审报告

## 总体评价

Codex 的实现质量整体良好，SPEC-9 的核心功能已全部落地：API 客户端、Pinia 状态管理、SSE 事件流、三阶段页面、四个子组件、路由接入、Clerk token 注册。后端 `auto_start` 竞态修复方案合理。14 项后端测试通过，前端构建成功。

以下按优先级分为三类：**必须修复（P0）**、**建议修复（P1）**、**可选优化（P2）**。

---

## P0 — 必须修复（影响功能正确性）

### P0-1: `UploadPanel` 的 `beforeUpload` 不会被触发

**文件**: `frontend/src/components/gen3/UploadPanel.vue:22-36`

`el-upload` 设置了 `:auto-upload="false"`，此时 Element Plus 不会调用 `before-upload` 钩子。文件选择后什么都不会发生。

**修复方案**: 改用 `on-change` 事件：

```html
<el-upload
  drag
  action="#"
  :auto-upload="false"
  :show-file-list="false"
  :disabled="disabled || loading"
  accept=".txt,.docx,.pdf,.md"
  :on-change="handleFileChange"
>
```

```javascript
function handleFileChange(uploadFile) {
  const file = uploadFile.raw
  if (file.size > MAX_SIZE) {
    ElMessage.error('文件大小不能超过 20MB')
    return
  }
  emit('upload', file, selectedRole.value)
}
```

### P0-2: `startListening` 调用 `resumeReview` 但图尚未运行

**文件**: `frontend/src/store/gen3Review.js:143-150`

`_connectEventStream({ resumeFirst: true })` 会先调用 `gen3Api.resumeReview()`，而 `resumeReview` 后端实现是 `graph.ainvoke(None, config)` — 这是恢复一个已中断的图。但在首次启动时，图从未运行过（`auto_start=false`），此时 `ainvoke(None, config)` 的行为取决于 LangGraph 实现，可能直接报错或跳过。

**修复方案**: 区分"首次启动"和"恢复"两种场景。

方案 A — 后端新增 `/api/v3/review/{taskId}/run` 端点（推荐，与之前讨论一致）：

```python
@router.post("/review/{task_id}/run")
async def run_review(task_id: str):
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")
    if entry.get("run_task"):
        return {"task_id": task_id, "status": "already_running"}
    graph = entry["graph"]
    config = entry["config"]
    snapshot = graph.get_state(config)
    entry["run_task"] = asyncio.create_task(
        _run_graph(task_id, graph, snapshot.values, config)
    )
    return {"task_id": task_id, "status": "started"}
```

前端 `startListening` 改为：
```javascript
async startListening() {
  this._startOperation('start_listening', '正在启动审阅...')
  try {
    await gen3Api.runReview(this.taskId)  // 新端点，首次启动图
    await this._connectEventStream({ resumeFirst: false })
    this._endOperation()
  } catch (error) {
    this._endOperation(error)
    throw error
  }
}
```

方案 B — 如果不想改后端，前端可以在 `startListening` 中直接用 `resumeReview`，但需要后端 `resume` 端点能处理"图从未运行"的情况（当前实现不能）。

### P0-3: SSE 连接与图执行的时序问题

**文件**: `frontend/src/store/gen3Review.js:143-184`

当前流程：`startListening()` → `resumeReview()` → `connectEventStream()`。问题是 `resumeReview` 是异步的（后端 `create_task`），图可能在 SSE 连接建立之前就已经推送了事件。SSE 端点是轮询式的（每 2 秒检查状态），所以实际上不会丢事件，但如果图执行非常快（比如只有 1-2 个条款），可能在 SSE 连接建立前就已经 `is_complete=true`。

**修复方案**: 调换顺序 — 先建立 SSE 连接，再触发图执行：

```javascript
async startListening() {
  this._startOperation('start_listening', '正在启动审阅...')
  try {
    this.disconnect()
    this.phase = 'reviewing'
    // 先建立 SSE 连接
    this._sseConnection = await gen3Api.connectEventStream(this.taskId, { ... })
    // 再触发图执行
    await gen3Api.runReview(this.taskId)  // 或 resumeReview
    this._endOperation()
  } catch (error) {
    this._endOperation(error)
    throw error
  }
}
```

---

## P1 — 建议修复（影响健壮性/用户体验）

### P1-1: `_endOperation` 在非错误场景下不应设置 `phase = 'error'`

**文件**: `frontend/src/store/gen3Review.js:51-60`

当前 `_endOperation(error)` 只要 `error` 非空就会设置 `this.phase = 'error'`。但某些操作失败（如单个 diff 审批失败）不应该把整个页面切到 error 状态。

**修复方案**: 只在关键操作失败时设置 phase，或者让调用方自行决定：

```javascript
_endOperation(error = null, { setErrorPhase = true } = {}) {
  this.operationState.currentOperation = null
  this.operationState.operationMessage = ''
  this.operationState.isLoading = false
  this.operationState.lastError = error
  if (error && setErrorPhase) {
    this.error = error.message || String(error)
    this.phase = 'error'
  }
}
```

然后在 `approveDiff` 等非关键操作中：
```javascript
this._endOperation(error, { setErrorPhase: false })
```

### P1-2: `approveAllPending` 中 `_moveDiff` 在循环中修改数组

**文件**: `frontend/src/store/gen3Review.js:218-224`

```javascript
const pendingIds = this.pendingDiffs.map((diff) => diff.diff_id)
pendingIds.forEach((id) => this._moveDiff(id, decision))
```

`_moveDiff` 内部使用 `splice` 修改 `pendingDiffs` 数组。虽然这里先提取了 id 列表所以不会死循环，但每次 `findIndex` + `splice` 的复杂度是 O(n²)。更重要的是，如果 pending 数量较多，频繁的响应式触发会导致性能问题。

**修复方案**: 批量移动，一次性操作：

```javascript
async approveAllPending(decision = 'approve') {
  // ... API 调用 ...
  const moved = [...this.pendingDiffs]
  moved.forEach(d => d.status = decision === 'approve' ? 'approved' : 'rejected')
  if (decision === 'approve') {
    this.approvedDiffs.push(...moved)
  } else {
    this.rejectedDiffs.push(...moved)
  }
  this.pendingDiffs = []
  // ...
}
```

### P1-3: SSE `connectEventStream` 中 token 只获取一次

**文件**: `frontend/src/api/gen3.js:155`

```javascript
const token = await getBearerToken()
```

SSE 连接可能持续数十分钟。如果 Clerk token 在此期间过期，连接断开后重连时仍使用旧 token。虽然当前后端 SSE 端点没有做认证校验（直接返回 StreamingResponse），但这是一个潜在问题。

**修复方案**: 暂时可以不改（后端 SSE 端点目前不校验 token），但建议在代码中加注释标记为 TODO：

```javascript
// TODO: SSE 长连接场景下 token 可能过期，后续需要实现重连机制
const token = await getBearerToken()
```

### P1-4: `recoverSession` 中 `_connectEventStream` 可能覆盖 phase

**文件**: `frontend/src/store/gen3Review.js:270-277`

```javascript
this.phase = 'interrupted'
await this._connectEventStream({ resumeFirst: false })
this.phase = 'interrupted'  // 重复设置
```

`_connectEventStream` 内部会设置 `this.phase = 'reviewing'`（第 151 行），然后这里又立即覆盖为 `interrupted`。这个逻辑虽然最终结果正确，但中间会有一次不必要的 phase 闪烁（reviewing → interrupted），可能导致 UI 闪烁。

**修复方案**: 让 `_connectEventStream` 接受一个可选的 `initialPhase` 参数，或者在 `_connectEventStream` 中不强制设置 phase：

```javascript
async _connectEventStream({ resumeFirst = true, phase = 'reviewing' } = {}) {
  // ...
  this.phase = phase
  // ...
}
```

### P1-5: 后端 `auto_start=false` 时 `graph.update_state` 可能不生效

**文件**: `backend/src/contract_review/api_gen3.py:130`

```python
graph.update_state(config, initial_state)
```

当 `auto_start=false` 时，图从未被 `ainvoke` 过，此时 `graph.update_state()` 的行为取决于 LangGraph 的 checkpointer 实现。如果使用的是 `MemorySaver`（当前代码中 `build_review_graph()` 的实现），`update_state` 在图未运行过时可能不会正确初始化状态。

**修复方案**: 需要验证 `build_review_graph()` 中 checkpointer 的行为。如果 `update_state` 在无历史状态时不工作，则需要改为：

```python
# 方案：先用 ainvoke 初始化到第一个中断点，而不是 update_state
# 或者确保 build_review_graph 使用的 MemorySaver 支持空状态 update
```

建议添加一个集成测试验证此路径。

### P1-6: `gen3Api` 缺少本地开发环境支持

**文件**: `frontend/src/api/gen3.js:3`

```javascript
const API_BASE_URL = 'https://contract-review-z9te.onrender.com/api/v3'
```

硬编码了生产环境 URL。本地开发时 Vite proxy 会将 `/api` 代理到 `localhost:8000`，但 SSE 的 `fetch` 调用使用的是完整 URL（绕过了 proxy）。

**修复方案**: 与 `api/index.js` 保持一致的模式，或者使用环境变量：

```javascript
const isProd = import.meta.env.PROD
const API_BASE_URL = isProd
  ? 'https://contract-review-z9te.onrender.com/api/v3'
  : '/api/v3'
```

这样本地开发时 axios 请求走 Vite proxy，SSE fetch 也走 proxy。

---

## P2 — 可选优化（代码质量/未来维护）

### P2-1: DiffCard 硬编码颜色值

**文件**: `frontend/src/components/gen3/DiffCard.vue:125-133`

```css
.original { background: #fef2f2; border: 1px solid #fecaca; }
.proposed { background: #ecfdf5; border: 1px solid #86efac; }
```

SPEC-9 要求使用 Element Plus 主题变量。建议改为：

```css
.original { background: var(--el-color-danger-light-9); border: 1px solid var(--el-color-danger-light-5); }
.proposed { background: var(--el-color-success-light-9); border: 1px solid var(--el-color-success-light-5); }
```

### P2-2: `ClauseProgress` 条款列表可能很长

**文件**: `frontend/src/components/gen3/ClauseProgress.vue:41-56`

FIDIC 合同可能有 50+ 条款，当前实现会渲染所有条款的 `<li>`。建议使用虚拟滚动或限制显示数量（如只显示当前条款前后各 5 个）。

### P2-3: `ReviewSummary` 缺少空列表处理

**文件**: `frontend/src/components/gen3/ReviewSummary.vue:14-29`

当 `approvedDiffs` 或 `rejectedDiffs` 为空时，折叠面板展开后显示空的 `<ul>`。建议加 `v-if` 或 `el-empty`。

### P2-4: 后端 SSE 轮询间隔固定 2 秒

**文件**: `backend/src/contract_review/api_gen3.py:458`

```python
await asyncio.sleep(2)
```

对于长时间运行的审阅，2 秒轮询可能过于频繁。建议在无变化时逐步增加间隔（指数退避），有变化时重置为 2 秒。

### P2-5: `Gen3ReviewView` 初始化后配置表单仍可见

**文件**: `frontend/src/views/Gen3ReviewView.vue:20-61`

`isSetupPhase` 在 `phase === 'uploading'` 时为 true，此时配置卡片和上传卡片同时显示。但配置卡片中的表单（领域、我方身份、语言）在初始化后不应再可编辑（因为已经发送给后端了）。

**修复方案**: 在 `phase === 'uploading'` 时禁用配置表单，或者隐藏配置卡片只显示上传卡片。

---

## 验证清单对照

| # | 验证项 | 状态 | 备注 |
|---|--------|------|------|
| V1 | 路由 `/gen3` 可访问 | ✅ | 路由正确注册，lazyLoadView 包装 |
| V2 | 初始化审阅 | ⚠️ | API 调用正确，但 `auto_start=false` 的 `update_state` 需验证（P1-5） |
| V3 | 上传文档 | ❌ | `beforeUpload` 不会触发（P0-1） |
| V4 | SSE 连接 | ⚠️ | 连接逻辑正确，但首次启动时序有问题（P0-2, P0-3） |
| V5 | Diff 展示 | ✅ | DiffCard 渲染正确 |
| V6 | 单个审批 | ✅ | API 调用和状态移动正确 |
| V7 | 批量审批 | ⚠️ | 功能正确但性能可优化（P1-2） |
| V8 | 恢复审阅 | ⚠️ | 时序问题（P1-4） |
| V9 | 审阅完成 | ✅ | ReviewSummary 正确渲染 |
| V10 | 现有功能不受影响 | ✅ | 零侵入，所有新代码在独立文件中 |
| V11 | 页面离开清理 | ✅ | `onUnmounted` 调用 `disconnect()` |

---

## 修复优先级建议

1. 先修 P0-1（UploadPanel 上传不触发）— 这是阻断性 bug，用户无法上传文件
2. 再修 P0-2 + P0-3（图启动时序）— 需要后端配合新增 `/run` 端点
3. 然后处理 P1 项（健壮性改进）
4. P2 项可以留到后续迭代
