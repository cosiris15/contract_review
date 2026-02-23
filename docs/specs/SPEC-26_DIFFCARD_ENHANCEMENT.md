# SPEC-26：Gen3 DiffCard 增强 — 内联 Diff 高亮、条款上下文、可编辑建议文本

> 状态：待实施
> 优先级：P0（Phase 2 首项）
> 前置依赖：SPEC-25（审批工作流完善）已完成
> 预估改动量：~180 行前端代码 + ~25 行后端代码 + ~50 行测试

---

## 0. 背景与动机

SPEC-24（模式切换）和 SPEC-25（审批工作流）完成后，Gen3 后端链路已成熟。但前端 `DiffCard.vue` 仍是纯文本展示，用户体验存在三个关键缺口：

1. **无字符级差异高亮**：原文与建议文本并排显示为纯文本，用户需要逐字对比才能发现变更
2. **无条款上下文**：用户看不到 diff 在条款中的位置，缺乏语境理解
3. **无法编辑建议文本**：用户只能批准或拒绝，无法在审批前微调建议文本

关键发现：
- `diff@8.0.2` 已安装但仅在 Interactive 流的 `DiffView.vue` 中使用，Gen3 流未使用
- 后端 `ApprovalRequest` 已有 `user_modified_text: Optional[str]` 字段（`models.py` 第 614 行）
- 前端 `gen3.js` API 客户端已发送 `user_modified_text`（第 129 行），但 store 层未传递
- 后端 `_active_graphs` 已存储 `primary_structure`（条款树），但未通过 API 暴露给前端

本 SPEC 利用已有依赖和后端数据，以最小改动量显著提升审查体验。

---

## 1. 设计原则

1. **零新依赖**：使用已安装的 `diff@8.0.2` 和 `element-plus`，不引入 TipTap 或任何富文本编辑器
2. **复用已有模式**：参考 Interactive 流 `DiffView.vue` 的 `diffChars` + `escapeHtml` 实现
3. **后端最小改动**：仅添加一个只读 GET 端点，不改动图状态机或 SSE 协议
4. **向后兼容**：所有现有审批功能（批准/拒绝/批量/恢复）不受影响

---

## 2. 改动清单

### 2.1 DiffCard.vue — 内联 Diff 高亮 + 可编辑建议文本 + 上下文按钮

**文件**: `frontend/src/components/gen3/DiffCard.vue`（当前 152 行）

**改动 1：导入 diffChars 并添加内联 diff 计算**

```javascript
// 在 script setup 中添加：
import { diffChars } from 'diff'
import ClauseContext from './ClauseContext.vue'

const viewMode = ref('unified')
const showContext = ref(false)

const htmlEscapeMap = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
function escapeHtml(text) {
  return text.replace(/[&<>"']/g, c => htmlEscapeMap[c]).replace(/\n/g, '<br>')
}

const inlineDiffHtml = computed(() => {
  const orig = props.diff.original_text || ''
  const proposed = editableProposed.value || ''
  if (!orig && !proposed) return '<span class="no-diff">（空）</span>'
  if (!orig) return `<span class="diff-added">${escapeHtml(proposed)}</span>`
  if (!proposed) return `<span class="diff-removed">${escapeHtml(orig)}</span>`
  return diffChars(orig, proposed).map(part => {
    const text = escapeHtml(part.value)
    if (part.added) return `<span class="diff-added">${text}</span>`
    if (part.removed) return `<span class="diff-removed">${text}</span>`
    return text
  }).join('')
})
```

**改动 2：添加可编辑建议文本**

```javascript
const editableProposed = ref(props.diff.proposed_text || '')
const isEdited = computed(() => editableProposed.value !== (props.diff.proposed_text || ''))

watch(() => props.diff.proposed_text, (val) => {
  if (!isEdited.value) editableProposed.value = val || ''
})
```

**改动 3：修改 emit 签名，传递 userModifiedText**

```javascript
// 改前：
function onApprove() {
  emit('approve', props.diff.diff_id, feedback.value.trim())
}

// 改后：
function onApprove() {
  const userModifiedText = isEdited.value ? editableProposed.value : undefined
  emit('approve', props.diff.diff_id, feedback.value.trim(), userModifiedText)
}
```

**改动 4：新增 taskId prop**

```javascript
// 改前：
const props = defineProps({
  diff: { type: Object, required: true }
})

// 改后：
const props = defineProps({
  diff: { type: Object, required: true },
  taskId: { type: String, default: '' }
})
```

**改动 5：模板重构**

将第 3-12 行的 card-header 区域添加上下文按钮：

```html
<div class="card-header">
  <div class="header-left">
    <span class="clause-id">{{ diff.clause_id || '未知条款' }}</span>
    <el-tag size="small" :type="riskTagType">{{ diff.risk_level || 'medium' }}</el-tag>
    <el-tag size="small" effect="plain">{{ actionLabel }}</el-tag>
    <!-- 新增：上下文按钮 -->
    <el-button text size="small" @click="showContext = !showContext">
      {{ showContext ? '隐藏上下文' : '查看上下文' }}
    </el-button>
  </div>
  <el-tag v-if="isHandled" :type="diff.status === 'approved' ? 'success' : 'danger'" size="small">
    {{ diff.status === 'approved' ? '已批准' : '已拒绝' }}
  </el-tag>
</div>
```

在 card-header 之后、原有 block 之前，插入条款上下文和视图切换：

```html
<!-- 条款上下文面板 -->
<ClauseContext
  :task-id="taskId"
  :clause-id="diff.clause_id"
  :original-text="diff.original_text"
  :visible="showContext"
  @close="showContext = false"
/>

<!-- 视图切换 -->
<div class="view-toggle">
  <el-radio-group v-model="viewMode" size="small">
    <el-radio-button value="unified">对比</el-radio-button>
    <el-radio-button value="split">分栏</el-radio-button>
  </el-radio-group>
  <el-tag v-if="isEdited" type="warning" size="small" effect="plain">已修改</el-tag>
</div>

<!-- Unified 内联 diff 视图 -->
<div v-if="viewMode === 'unified'" class="block">
  <div class="label">变更对比</div>
  <div class="text unified-diff" v-html="inlineDiffHtml"></div>
</div>

<!-- Split 分栏视图 -->
<template v-else>
  <div class="block">
    <div class="label">原文</div>
    <div class="text original">{{ diff.original_text || '（空）' }}</div>
  </div>
  <div class="block">
    <div class="label">建议文本</div>
    <el-input
      v-if="!isHandled"
      v-model="editableProposed"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 8 }"
      class="editable-proposed"
    />
    <div v-else class="text proposed">{{ editableProposed || '（空）' }}</div>
  </div>
</template>
```

**改动 6：CSS 添加**

```css
.view-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.unified-diff {
  background: #fff;
  border: 1px solid var(--el-border-color);
}

.unified-diff :deep(.diff-removed) {
  background: #fee2e2;
  color: #dc2626;
  text-decoration: line-through;
  padding: 1px 2px;
  border-radius: 2px;
}

.unified-diff :deep(.diff-added) {
  background: #d1fae5;
  color: #059669;
  padding: 1px 2px;
  border-radius: 2px;
}

.editable-proposed :deep(.el-textarea__inner) {
  line-height: 1.6;
}
```

### 2.2 ClauseContext.vue — 新组件

**文件**: `frontend/src/components/gen3/ClauseContext.vue`（新建）

```vue
<template>
  <el-card v-if="visible" class="clause-context" shadow="never">
    <template #header>
      <div class="ctx-header">
        <span>条款上下文: {{ clauseId }}</span>
        <el-button text size="small" @click="$emit('close')">收起</el-button>
      </div>
    </template>
    <div v-if="loading" class="loading">
      <el-icon class="is-loading"><Loading /></el-icon>
    </div>
    <div v-else-if="clauseText" class="clause-text" v-html="highlightedText"></div>
    <el-empty v-else description="无法加载条款上下文" :image-size="40" />
  </el-card>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import gen3Api from '@/api/gen3'

const props = defineProps({
  taskId: { type: String, required: true },
  clauseId: { type: String, default: '' },
  originalText: { type: String, default: '' },
  visible: { type: Boolean, default: false }
})
defineEmits(['close'])

const clauseText = ref('')
const loading = ref(false)

function escapeHtml(t) {
  return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

const highlightedText = computed(() => {
  if (!clauseText.value) return ''
  const escaped = escapeHtml(clauseText.value)
  if (!props.originalText) return escaped
  const needle = escapeHtml(props.originalText)
  const idx = escaped.indexOf(needle)
  if (idx === -1) return escaped
  return escaped.substring(0, idx) +
    '<mark class="diff-highlight">' + needle + '</mark>' +
    escaped.substring(idx + needle.length)
})

watch([() => props.clauseId, () => props.visible], async ([id, vis]) => {
  if (!id || !vis || !props.taskId) { clauseText.value = ''; return }
  loading.value = true
  try {
    const resp = await gen3Api.getClauseContext(props.taskId, id)
    clauseText.value = resp.data.text || ''
  } catch { clauseText.value = '' }
  finally { loading.value = false }
}, { immediate: true })
</script>

<style scoped>
.clause-context { margin-bottom: 12px; }
.ctx-header { display: flex; justify-content: space-between; align-items: center; }
.clause-text {
  white-space: pre-wrap;
  line-height: 1.7;
  font-size: 13px;
  max-height: 200px;
  overflow: auto;
}
.clause-text :deep(.diff-highlight) {
  background: #fef3c7;
  border-bottom: 2px solid #f59e0b;
  padding: 1px 0;
}
.loading { text-align: center; padding: 16px; }
</style>
```

### 2.3 Gen3ReviewView.vue — 传递 taskId 和 userModifiedText

**文件**: `frontend/src/views/Gen3ReviewView.vue`

**改动 1：DiffCard 添加 taskId prop**

```html
<!-- 改前（第 109-115 行）：-->
<DiffCard
  v-for="item in store.pendingDiffs"
  :key="item.diff_id"
  :diff="item"
  @approve="(id, feedback) => approveSingle(id, 'approve', feedback)"
  @reject="(id, feedback) => approveSingle(id, 'reject', feedback)"
/>

<!-- 改后：-->
<DiffCard
  v-for="item in store.pendingDiffs"
  :key="item.diff_id"
  :diff="item"
  :task-id="store.taskId"
  @approve="(id, feedback, userModifiedText) => approveSingle(id, 'approve', feedback, userModifiedText)"
  @reject="(id, feedback) => approveSingle(id, 'reject', feedback)"
/>
```

**改动 2：approveSingle 函数签名更新**

```javascript
// 改前：
async function approveSingle(diffId, decision, feedback = '') {
  try {
    await store.approveDiff(diffId, decision, feedback)
  } catch (error) { ... }
}

// 改后：
async function approveSingle(diffId, decision, feedback = '', userModifiedText) {
  try {
    await store.approveDiff(diffId, decision, feedback, userModifiedText)
  } catch (error) { ... }
}
```

### 2.4 gen3Review.js — approveDiff 传递 userModifiedText

**文件**: `frontend/src/store/gen3Review.js`

```javascript
// 改前（第 198 行）：
async approveDiff(diffId, decision, feedback = '') {
  // ...
  await gen3Api.approveDiff(this.taskId, { diffId, decision, feedback })
  // ...
}

// 改后：
async approveDiff(diffId, decision, feedback = '', userModifiedText) {
  // ...
  await gen3Api.approveDiff(this.taskId, { diffId, decision, feedback, userModifiedText })
  // ...
}
```

注意：`gen3.js` API 客户端第 129 行已发送 `user_modified_text: payload.userModifiedText || null`，无需改动。

### 2.5 gen3.js — 添加 getClauseContext API

**文件**: `frontend/src/api/gen3.js`

在 `gen3Api` 对象中添加：

```javascript
getClauseContext(taskId, clauseId) {
  return api.get(`/review/${taskId}/clause/${encodeURIComponent(clauseId)}/context`)
},
```

### 2.6 api_gen3.py — 添加条款上下文端点

**文件**: `backend/src/contract_review/api_gen3.py`

在 `/review/{task_id}/documents` 端点之后（第 384 行之后）添加：

```python
def _find_clause_in_dict(clauses: list, clause_id: str) -> dict | None:
    """递归遍历条款 dict 列表，查找匹配 clause_id 的节点。"""
    for node in clauses:
        if node.get("clause_id") == clause_id:
            return node
        children = node.get("children", [])
        if children:
            found = _find_clause_in_dict(children, clause_id)
            if found:
                return found
    return None


@router.get("/review/{task_id}/clause/{clause_id}/context")
async def get_clause_context(task_id: str, clause_id: str):
    """获取指定条款的上下文文本，用于前端展示 diff 所在位置。"""
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    _touch_entry(entry)
    primary_structure = entry.get("primary_structure")
    if not primary_structure:
        raise HTTPException(404, "未找到文档结构")

    clauses = primary_structure.get("clauses", [])
    node = _find_clause_in_dict(clauses, clause_id)
    if not node:
        raise HTTPException(404, f"条款 {clause_id} 不存在")

    return {
        "clause_id": node.get("clause_id", ""),
        "title": node.get("title", ""),
        "text": node.get("text", ""),
        "level": node.get("level", 0),
        "start_offset": node.get("start_offset", 0),
        "end_offset": node.get("end_offset", 0),
    }
```

注意：直接遍历 dict 而非重建 `DocumentStructure` 对象，避免不必要的开销。`primary_structure` 在上传时通过 `structure.model_dump(mode="json")` 存储为 dict（第 328 行）。

---

## 3. 测试要求

### 3.1 后端测试

**新增 `tests/test_clause_context.py`**：

```python
class TestClauseContext:
    """测试条款上下文端点"""

    @pytest.mark.asyncio
    async def test_returns_clause_text(self, client):
        """正常返回条款文本"""
        # 构造 _active_graphs entry，包含 primary_structure
        # GET /api/v3/review/{task_id}/clause/{clause_id}/context
        # 验证返回 clause_id, title, text, level

    @pytest.mark.asyncio
    async def test_404_when_clause_not_found(self, client):
        """条款不存在时返回 404"""

    @pytest.mark.asyncio
    async def test_404_when_no_structure(self, client):
        """无文档结构时返回 404"""

    @pytest.mark.asyncio
    async def test_404_when_task_not_found(self, client):
        """任务不存在时返回 404"""

    @pytest.mark.asyncio
    async def test_nested_clause_found(self, client):
        """能找到嵌套的子条款"""
```

### 3.2 单元测试

**`_find_clause_in_dict` 函数测试**：

```python
class TestFindClauseInDict:
    def test_find_top_level(self):
        clauses = [{"clause_id": "1", "text": "a", "children": []}]
        assert _find_clause_in_dict(clauses, "1")["text"] == "a"

    def test_find_nested(self):
        clauses = [{"clause_id": "1", "children": [{"clause_id": "1.1", "text": "b", "children": []}]}]
        assert _find_clause_in_dict(clauses, "1.1")["text"] == "b"

    def test_not_found(self):
        clauses = [{"clause_id": "1", "children": []}]
        assert _find_clause_in_dict(clauses, "99") is None
```

---

## 4. 不改动的部分

- 不引入新 npm 依赖（使用已有 `diff@8.0.2`）
- 不引入 TipTap 或任何富文本编辑器
- 不改动 SSE 协议或图状态机
- 不改动 `ApprovalRequest` 模型（已有 `user_modified_text`）
- 不改动 `gen3.js` 的 `approveDiff` 调用（已发送 `userModifiedText`）
- 不改动 `document.js` store（仅 Interactive 流使用）

---

## 5. 文件清单

| 文件 | 改动类型 | 预估行数 | 改动点 |
|------|----------|---------|--------|
| `frontend/src/components/gen3/DiffCard.vue` | 修改 | ~80 | diffChars 导入、inlineDiffHtml、viewMode 切换、editableProposed、showContext、taskId prop |
| `frontend/src/components/gen3/ClauseContext.vue` | 新建 | ~60 | 条款上下文面板组件 |
| `frontend/src/views/Gen3ReviewView.vue` | 修改 | ~10 | 传递 taskId prop、approveSingle 接收 userModifiedText |
| `frontend/src/store/gen3Review.js` | 修改 | ~5 | approveDiff 添加 userModifiedText 参数 |
| `frontend/src/api/gen3.js` | 修改 | ~5 | 添加 getClauseContext 方法 |
| `backend/src/contract_review/api_gen3.py` | 修改 | ~25 | _find_clause_in_dict 函数 + GET /clause/{clause_id}/context 端点 |
| `tests/test_clause_context.py` | 新建 | ~50 | 后端端点测试 |

---

## 6. 验收条件

1. DiffCard 默认显示字符级内联 diff 高亮（红色删除线 = 删除，绿色 = 新增）
2. 用户可切换 unified（内联对比）和 split（分栏）视图
3. split 视图中建议文本可编辑（textarea），编辑后显示"已修改"标记
4. 编辑后批准时，`user_modified_text` 正确发送到后端
5. DiffCard 有"查看上下文"按钮，点击加载条款全文
6. 条款上下文面板中，diff 原文位置用黄色高亮标记
7. `GET /api/v3/review/{task_id}/clause/{clause_id}/context` 返回条款信息
8. 所有现有审批功能（批准/拒绝/批量/恢复）不受影响
9. 不引入新 npm 依赖
10. 后端测试通过，pytest 全量无回归

---

## 7. 实施步骤

1. `api_gen3.py`：添加 `_find_clause_in_dict` 函数和 `GET /clause/{clause_id}/context` 端点
2. `gen3.js`：添加 `getClauseContext` API 方法
3. `ClauseContext.vue`：新建条款上下文面板组件
4. `DiffCard.vue`：添加 diffChars 内联高亮、viewMode 切换、editableProposed、showContext、taskId prop
5. `Gen3ReviewView.vue`：传递 taskId、更新 approveSingle 签名
6. `gen3Review.js`：approveDiff 添加 userModifiedText 参数
7. 新增 `tests/test_clause_context.py`
8. 运行 `cd backend && PYTHONPATH=backend/src python -m pytest tests/ -x -q`，确保全量通过
9. 运行 `cd frontend && npm run build`，确认无编译错误

---

## 8. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| `diffChars` 对长文本性能问题 | 合同条款通常不超过几千字，diffChars 性能足够；如有问题可加 `maxEditLength` 限制 |
| `v-html` XSS 风险 | `escapeHtml` 函数对所有用户文本进行转义，仅插入安全的 `<span>` 和 `<mark>` 标签 |
| `primary_structure` 可能为 None | 端点返回 404，前端 ClauseContext 优雅降级显示 el-empty |
| 编辑后切换到 unified 视图 | inlineDiffHtml 使用 editableProposed 而非原始 proposed_text，编辑内容实时反映在 diff 中 |
