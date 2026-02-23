# SPEC-27：Gen3 审查体验增强 — 处理进度、中断说明、条款分组、决策历史

> 状态：待实施
> 优先级：P0（Phase 2）
> 前置依赖：SPEC-26（DiffCard 增强）已完成
> 预估改动量：~115 行前端代码，仅 2 个文件，零后端变更，零新依赖

---

## 0. 背景与动机

SPEC-26 完成了 DiffCard 的内联 diff 高亮、条款上下文和可编辑建议文本。但 Gen3ReviewView 的整体审查体验仍有 4 个 UX 缺口：

1. **无处理进度反馈**：`progressMessage` 和 `currentClauseId` 已由 SSE 写入 store（`gen3Review.js` 第 155-156 行），但 `Gen3ReviewView` 从未渲染它们。用户在 `reviewing` 阶段只看到空白的 diff 区域，不知道后端正在做什么。
2. **中断状态突兀**：当 `phase === 'interrupted'` 且 `pendingDiffs.length === 0`（所有 diff 已处理但尚未点"继续审阅"），用户看到的是 `<el-empty description="当前无待审批 diff" />`，缺乏上下文说明。
3. **Diff 平铺无分组**：所有 pendingDiffs 按到达顺序平铺，用户无法按条款快速定位。
4. **无决策历史**：已批准/拒绝的 diff 从列表中消失，用户无法回顾自己的决策。

关键发现：
- `progressMessage`（第 16 行）和 `currentClauseId`（第 15 行）已在 store state 中定义
- SSE `onProgress` 回调（第 152-157 行）已正确写入这两个字段
- `approvedDiffs` 和 `rejectedDiffs` 数组已在 store 中维护，但前端仅用于 `ClauseProgress` 计数
- `el-collapse` 组件已由 element-plus 提供，无需额外依赖

---

## 1. 设计原则

1. **零后端变更**：所有改动限于前端，不改动 API、SSE 协议或图状态机
2. **零新依赖**：使用已有的 element-plus 组件（`el-alert`、`el-collapse`、`el-tag`、`el-icon`）
3. **渐进增强**：所有新 UI 元素在数据不可用时优雅降级（空数组 = 不显示）
4. **向后兼容**：所有现有审批功能不受影响

---

## 2. 改动清单

### 2.1 gen3Review.js — 添加 2 个 getter + _moveDiff 时间戳

**文件**: `frontend/src/store/gen3Review.js`

**改动 1：在 getters 块（第 33-42 行）中添加两个 getter**

```javascript
// 按 clause_id 分组 pendingDiffs
groupedPendingDiffs: (state) => {
  const groups = {}
  for (const diff of state.pendingDiffs) {
    const key = diff.clause_id || '未知条款'
    if (!groups[key]) groups[key] = []
    groups[key].push(diff)
  }
  return Object.entries(groups).map(([clauseId, diffs]) => ({ clauseId, diffs }))
},

// 合并已处理 diffs（按时间倒序，最新在前）
handledDiffs: (state) => {
  return [...state.approvedDiffs, ...state.rejectedDiffs]
    .sort((a, b) => (b._handledAt || 0) - (a._handledAt || 0))
}
```

**改动 2：在 _moveDiff action（第 74-88 行）中添加时间戳**

```javascript
// 改前：
_moveDiff(diffId, decision) {
  const index = this.pendingDiffs.findIndex((item) => item.diff_id === diffId)
  if (index < 0) {
    return
  }
  const diff = this.pendingDiffs[index]
  this.pendingDiffs.splice(index, 1)
  if (decision === 'approve') {
    diff.status = 'approved'
    this.approvedDiffs.push(diff)
  } else {
    diff.status = 'rejected'
    this.rejectedDiffs.push(diff)
  }
}

// 改后：
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
}
```

### 2.2 Gen3ReviewView.vue — 4 项 UI 增强

**文件**: `frontend/src/views/Gen3ReviewView.vue`

**改动 1：导入 Loading 图标**

```javascript
// 改前（第 136 行）：
import { ArrowLeft } from '@element-plus/icons-vue'

// 改后：
import { ArrowLeft, Loading } from '@element-plus/icons-vue'
```

**改动 2：处理进度 banner**

在 diff-header 之后（第 106 行之后）插入：

```html
<div v-if="store.phase === 'reviewing'" class="processing-banner">
  <el-icon class="is-loading"><Loading /></el-icon>
  <span>{{ store.progressMessage || '正在分析合同条款...' }}</span>
  <el-tag v-if="store.currentClauseId" size="small" effect="plain">
    {{ store.currentClauseId }}
  </el-tag>
</div>
```

**改动 3：中断说明 banner**

替换第 108 行的 el-empty：

```html
<!-- 改前：-->
<el-empty v-if="store.pendingDiffs.length === 0" description="当前无待审批 diff" />

<!-- 改后：-->
<el-alert
  v-if="store.pendingDiffs.length === 0 && store.phase === 'interrupted'"
  type="info"
  :closable="false"
  show-icon
  title="所有修改建议已处理完毕"
  description="点击「继续审阅」让系统继续分析下一批条款。"
/>
<el-empty
  v-else-if="store.pendingDiffs.length === 0 && store.phase === 'reviewing'"
  description="等待系统生成修改建议..."
  :image-size="60"
/>
```

**改动 4：Diff 按条款分组渲染**

替换第 109-116 行的平铺 DiffCard 列表：

```html
<!-- 改前：-->
<DiffCard
  v-for="item in store.pendingDiffs"
  :key="item.diff_id"
  :diff="item"
  :task-id="store.taskId"
  @approve="(id, feedback, userModifiedText) => approveSingle(id, 'approve', feedback, userModifiedText)"
  @reject="(id, feedback) => approveSingle(id, 'reject', feedback)"
/>

<!-- 改后：-->
<div v-for="group in store.groupedPendingDiffs" :key="group.clauseId" class="clause-group">
  <div class="clause-group-header">
    <span class="clause-group-id">{{ group.clauseId }}</span>
    <el-tag size="small" effect="plain">{{ group.diffs.length }} 项修改</el-tag>
  </div>
  <DiffCard
    v-for="item in group.diffs"
    :key="item.diff_id"
    :diff="item"
    :task-id="store.taskId"
    @approve="(id, feedback, userModifiedText) => approveSingle(id, 'approve', feedback, userModifiedText)"
    @reject="(id, feedback) => approveSingle(id, 'reject', feedback)"
  />
</div>
```

**改动 5：决策历史面板**

在 DiffCard 列表之后、diff-area 关闭 div 之前插入：

```html
<el-collapse v-if="store.handledDiffs.length > 0" class="history-collapse">
  <el-collapse-item>
    <template #title>
      <span>决策历史</span>
      <el-tag size="small" type="success" effect="plain" style="margin-left: 8px;">
        {{ store.approvedDiffs.length }} 批准
      </el-tag>
      <el-tag size="small" type="danger" effect="plain" style="margin-left: 4px;">
        {{ store.rejectedDiffs.length }} 拒绝
      </el-tag>
    </template>
    <div v-for="item in store.handledDiffs" :key="item.diff_id" class="history-item">
      <el-tag :type="item.status === 'approved' ? 'success' : 'danger'" size="small">
        {{ item.status === 'approved' ? '批准' : '拒绝' }}
      </el-tag>
      <span class="history-clause">{{ item.clause_id || '未知' }}</span>
      <span class="history-reason">{{ item.reason || '' }}</span>
    </div>
  </el-collapse-item>
</el-collapse>
```

**改动 6：CSS 新增**

```css
.processing-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: var(--el-color-primary-light-9);
  border-radius: 8px;
  margin-bottom: 12px;
  color: var(--el-color-primary);
  font-size: 14px;
}

.clause-group {
  margin-bottom: 16px;
}

.clause-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.clause-group-id {
  font-weight: 600;
  font-size: 14px;
}

.history-collapse {
  margin-top: 16px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
}

.history-clause {
  font-weight: 500;
  min-width: 60px;
}

.history-reason {
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

---

## 3. 不改动的部分

- 不改动后端（零 Python 变更）
- 不改动 SSE 协议或图状态机
- 不引入新 npm 依赖
- 不改动 `DiffCard.vue`（SPEC-26 已完善）
- 不改动 `ClauseProgress.vue`（已有条款进度侧边栏）
- 不改动 `gen3.js` API 层
- 不改动 `ClauseContext.vue`

---

## 4. 文件清单

| 文件 | 改动类型 | 预估行数 | 改动点 |
|------|----------|---------|--------|
| `frontend/src/store/gen3Review.js` | 修改 | ~15 | groupedPendingDiffs getter、handledDiffs getter、_moveDiff 时间戳 |
| `frontend/src/views/Gen3ReviewView.vue` | 修改 | ~100 | Loading 导入、处理进度 banner、中断说明、条款分组、决策历史面板、CSS |

总计：~115 行，仅 2 个文件

---

## 5. 验收条件

1. `reviewing` 阶段显示处理进度 banner（Loading 旋转图标 + progressMessage + currentClauseId tag）
2. `interrupted` 阶段且无 pending diff 时，显示 `el-alert` 说明而非空白 el-empty
3. `reviewing` 阶段且无 pending diff 时，显示"等待系统生成修改建议..."
4. pending diffs 按 clause_id 分组显示，每组有条款标题和修改数量
5. diff-area 底部有可折叠的决策历史面板，显示已批准/拒绝的 diff 摘要
6. 所有现有功能（批准/拒绝/批量/恢复/上下文/内联 diff）不受影响
7. `npm run build` 无编译错误
8. 后端 pytest 全量无回归（虽然无后端改动，仍需确认）

---

## 6. 实施步骤

1. `gen3Review.js`：添加 `groupedPendingDiffs` 和 `handledDiffs` getter
2. `gen3Review.js`：在 `_moveDiff` 中添加 `_handledAt` 时间戳
3. `Gen3ReviewView.vue`：导入 `Loading` 图标
4. `Gen3ReviewView.vue`：添加处理进度 banner
5. `Gen3ReviewView.vue`：替换 el-empty 为条件化的中断说明 / 等待提示
6. `Gen3ReviewView.vue`：将平铺 DiffCard 改为按条款分组渲染
7. `Gen3ReviewView.vue`：添加决策历史面板
8. `Gen3ReviewView.vue`：添加 CSS
9. 运行 `cd frontend && npm run build`，确认无编译错误
10. 运行 `PYTHONPATH=backend/src python -m pytest tests/ -x -q`，确认无回归

---

## 7. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| `groupedPendingDiffs` 在 diff 数量极大时性能 | 合同审查通常每批 1-5 个 diff，getter 计算量极小 |
| `el-collapse` 首次使用可能有样式冲突 | element-plus 内置组件，样式隔离良好 |
| `_handledAt` 字段在会话恢复时丢失 | 仅影响排序，降级为按数组顺序显示，不影响功能 |
| 分组后批量操作仍作用于全部 pending | 符合预期，批量操作不区分条款 |
