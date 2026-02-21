# SPEC-10: Gen 3.0 导出桥接

## 1. 概述

Gen 3.0 审阅流程（SPEC-1~9）已全部实现。当前缺少最后一环：审阅完成后，将用户批准的修改建议导出为 Word 红线文档。

后端已有完整的红线生成器 `redline_generator.py`（`generate_redline_document` 函数），但它接受的是 Gen 2.x 的 `ModificationSuggestion` 模型。Gen 3.0 产出的是 `DocumentDiff` 模型。本 SPEC 的核心任务是在 API 层做桥接转换，并在前端完成页面增加导出按钮。

**关键原则：**
- 不修改 `redline_generator.py`，它是已有的稳定代码
- 不修改图节点代码，只在 API 层做桥接
- 复用现有导出基础设施（`python-docx`、`lxml` 已安装）

## 2. 文件清单

### 修改文件（共 5 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/api_gen3.py` | 新增 2 个端点：`/export` 和 `/result` |
| `frontend/src/api/gen3.js` | 新增 2 个方法：`exportRedline`、`getResult` |
| `frontend/src/store/gen3Review.js` | 新增 2 个 action：`exportRedline`、`fetchResult` |
| `frontend/src/components/gen3/ReviewSummary.vue` | 新增导出按钮区域 |
| `frontend/src/views/Gen3ReviewView.vue` | 向 ReviewSummary 传递 `taskId` prop |

### 新增文件（共 0 个）

不新建任何文件。

## 3. 数据模型桥接

Gen 3.0 的 `DocumentDiff` 需要转换为 Gen 2.x 的 `ModificationSuggestion` 才能调用 `generate_redline_document`。

### 字段映射

| DocumentDiff 字段 | ModificationSuggestion 字段 | 转换逻辑 |
|---|---|---|
| `diff_id` | `id` | 直接赋值 |
| `risk_id` | `risk_id` | 直接赋值，若为 None 则用 `diff_id` |
| `original_text` | `original_text` | 直接赋值 |
| `proposed_text` | `suggested_text` | 直接赋值 |
| `reason` | `modification_reason` | 直接赋值 |
| `risk_level` | `priority` | `"high"/"critical"` → `"must"`，`"medium"` → `"should"`，`"low"` → `"may"` |
| （固定值） | `user_confirmed` | 固定为 `True`（只导出已批准的） |
| `action_type == "insert"` | `is_addition` | `True` 当 action_type 为 `"insert"` |
| `action_type == "insert"` 时 | `insertion_point` | 使用 `clause_id` 生成，如 `"插入到条款 {clause_id} 之后"` |

### 转换函数签名

在 `api_gen3.py` 中新增一个模块级私有函数：

```python
def _diff_to_modification(diff: dict) -> ModificationSuggestion:
    """将 Gen 3.0 DocumentDiff 转换为 Gen 2.x ModificationSuggestion"""
```

## 4. 详细规格

### 4.1 后端 — `api_gen3.py` 新增端点

#### 4.1.1 `GET /api/v3/review/{task_id}/result`

返回审阅结果的 JSON 摘要。

**逻辑：**
1. 从 `_active_graphs[task_id]` 获取 entry
2. 获取图状态快照 `snapshot.values`
3. 组装返回数据

**响应体：**
```json
{
  "task_id": "...",
  "is_complete": true,
  "summary_notes": "...",
  "total_risks": 12,
  "approved_count": 6,
  "rejected_count": 2,
  "findings": { "clause_id": { ... } },
  "all_risks": [ ... ]
}
```

**错误处理：**
- 任务不存在 → 404
- 任务未完成（`is_complete != True`）→ 正常返回，`is_complete` 为 `false`

#### 4.1.2 `POST /api/v3/review/{task_id}/export`

生成并下载 Word 红线文档。

**逻辑：**
1. 从 `_active_graphs[task_id]` 获取 entry
2. 检查 `snapshot.values.get("is_complete")` 为 `True`，否则返回 HTTP 400（`"审阅尚未完成，无法导出"`）
3. 从 `snapshot.values` 提取 `all_diffs`，过滤出 `status == "approved"` 的
4. 如果没有已批准的 diff，返回 HTTP 400（`"没有已批准的修改建议"`）
5. 找到 primary 文档的文件路径：
   - 从 `entry["documents"]` 中找 `role == "primary"` 的文档
   - 文件在 `entry["tmp_dir"]` 目录下，文件名为文档的 `storage_name` 或 `filename`
   - 检查文件扩展名必须是 `.docx`，否则返回 HTTP 400（`"仅支持 .docx 格式的红线导出"`）
6. 用 `_diff_to_modification()` 将每个 approved diff 转换为 `ModificationSuggestion`
7. 调用 `generate_redline_document(file_path, modifications, filter_confirmed=False)`
   - 注意 `filter_confirmed=False`，因为我们已经手动过滤了 approved 的
8. 检查 `result.success` 和 `result.document_bytes`
9. 返回 `StreamingResponse`：
   - `content` = `BytesIO(result.document_bytes)`
   - `media_type` = `"application/vnd.openxmlformats-officedocument.wordprocessingml.document"`
   - `headers` = `{"Content-Disposition": f"attachment; filename=redline_{task_id}.docx"}`

**需要新增的 import：**
```python
from io import BytesIO
from .redline_generator import generate_redline_document
from .models import ModificationSuggestion
```

### 4.2 前端 API 层 — `api/gen3.js`

在 `gen3Api` 对象中新增两个方法：

```javascript
exportRedline(taskId) {
  return api.post(`/review/${taskId}/export`, null, {
    responseType: 'blob',
    timeout: 60000
  })
},

getResult(taskId) {
  return api.get(`/review/${taskId}/result`)
}
```

### 4.3 前端 Store 层 — `store/gen3Review.js`

新增两个 action：

```javascript
async exportRedline() {
  if (!this.taskId) throw new Error('任务不存在')
  this._startOperation('export_redline', '正在生成红线文档...')
  try {
    const response = await gen3Api.exportRedline(this.taskId)
    this._endOperation()
    return response.data  // Blob
  } catch (error) {
    this._endOperation(error, { setErrorPhase: false })
    throw error
  }
},

async fetchResult() {
  if (!this.taskId) throw new Error('任务不存在')
  const response = await gen3Api.getResult(this.taskId)
  return response.data
}
```

### 4.4 前端组件 — `ReviewSummary.vue`

**新增 props：**
- `taskId: { type: String, default: '' }`

**新增导出按钮区域：** 在 `el-collapse` 之后添加：

```html
<div class="export-actions">
  <el-button type="primary" :loading="exporting" @click="handleExportRedline">
    导出红线文档
  </el-button>
  <el-button @click="handleExportJson">
    导出 JSON 报告
  </el-button>
</div>
```

**新增逻辑：**
- `exporting` ref 控制 loading 状态
- `handleExportRedline`：调用 store 的 `exportRedline()`，拿到 Blob 后用 `URL.createObjectURL` + 临时 `<a>` 标签触发下载，下载后 `URL.revokeObjectURL`
- `handleExportJson`：调用 store 的 `fetchResult()`，将 JSON 转为 Blob（`new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })`），同样触发下载

**新增样式：**
```css
.export-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
```

### 4.5 父组件 — `Gen3ReviewView.vue`

当前 ReviewSummary 的调用：
```html
<ReviewSummary
  :summary="store.summary"
  :approved-diffs="store.approvedDiffs"
  :rejected-diffs="store.rejectedDiffs"
  :total-clauses="store.totalClauses"
/>
```

需要补传 `taskId`：
```html
<ReviewSummary
  :task-id="store.taskId"
  :summary="store.summary"
  :approved-diffs="store.approvedDiffs"
  :rejected-diffs="store.rejectedDiffs"
  :total-clauses="store.totalClauses"
/>
```

## 5. 测试

在 `tests/test_api_gen3.py` 中新增：

### 5.1 `test_export_requires_complete_review`
- 创建一个未完成的任务（`is_complete = False`）
- 调用 `POST /api/v3/review/{task_id}/export`
- 断言返回 HTTP 400

### 5.2 `test_get_result_returns_summary`
- 创建一个已完成的任务，注入 mock 状态（`is_complete=True`, `all_risks=[...]`, `summary_notes="test"`）
- 调用 `GET /api/v3/review/{task_id}/result`
- 断言返回包含 `is_complete`、`summary_notes`、`total_risks` 等字段

### 5.3 `test_diff_to_modification_conversion`
- 直接测试 `_diff_to_modification` 函数
- 验证 `replace` 类型 diff 转换正确
- 验证 `insert` 类型 diff 的 `is_addition=True` 和 `insertion_point` 非空
- 验证 `risk_level` → `priority` 映射正确

## 6. 验收标准

1. `cd backend && python -m pytest tests/ -x -q` 全部通过
2. `cd frontend && npm run build` 构建成功
3. 审阅完成页面显示「导出红线文档」和「导出 JSON 报告」两个按钮
4. 点击「导出 JSON 报告」能下载包含审阅结果的 JSON 文件
5. 未完成的任务调用导出端点返回 400 错误
