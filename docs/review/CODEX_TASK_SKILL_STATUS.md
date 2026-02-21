# 任务：为 Refly Skills 添加状态标签

## 背景

项目中有 4 个 Refly 类型的 Skills（2 个 FIDIC + 2 个 SHA/SPA），它们依赖 Refly 平台的 Knowledge Base API 才能完整运行。但 Refly 目前未开放 Knowledge Base 管理 API，导致这些 Skills 无法在生产环境中被用户自动触发使用。

当前问题：
- 后端已有保护机制（`builder.py` 第 180-182 行会跳过未注册的 Refly Skill），不会报错
- 但前端 Skills 管理页面没有区分 skill 的可用状态，用户无法知道哪些 skill 是可用的、哪些还在开发中
- 需要在数据模型和前端展示中体现 skill 的开发状态

## 需要修改的文件

### 1. `backend/src/contract_review/skills/schema.py`

在 `SkillRegistration` 模型（第 21-36 行）中添加 `status` 字段：

```python
class SkillRegistration(BaseModel):
    """Skill registration payload."""

    skill_id: str
    name: str
    description: str = ""
    input_schema: Optional[Type[BaseModel]] = None
    output_schema: Optional[Type[BaseModel]] = None
    backend: SkillBackend
    refly_workflow_id: Optional[str] = None
    local_handler: Optional[str] = None
    domain: str = "*"
    category: str = "general"
    status: str = "active"  # "active" | "preview" | "deprecated"

    class Config:
        arbitrary_types_allowed = True
```

默认值为 `"active"`，这样所有现有的 Local Skills 不需要改动。

### 2. `backend/src/contract_review/plugins/fidic.py`

为两个 Refly Skill 添加 `status="preview"`：

第 41-51 行的 `fidic_search_er`：
```python
    SkillRegistration(
        skill_id="fidic_search_er",
        ...
        backend=SkillBackend.REFLY,
        refly_workflow_id="c-cxcin1htmspl8xq419kzseii",
        domain="fidic",
        category="validation",
        status="preview",  # 添加这一行
    ),
```

第 52-62 行的 `fidic_check_pc_consistency`：
```python
    SkillRegistration(
        skill_id="fidic_check_pc_consistency",
        ...
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_fidic_pc_consistency",
        domain="fidic",
        category="validation",
        status="preview",  # 添加这一行
    ),
```

### 3. `backend/src/contract_review/plugins/sha_spa.py`

同样为两个 Refly Skill 添加 `status="preview"`：

第 45-53 行的 `sha_governance_check`：
```python
    SkillRegistration(
        skill_id="sha_governance_check",
        ...
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_sha_governance",
        domain="sha_spa",
        category="validation",
        status="preview",  # 添加这一行
    ),
```

第 54-62 行的 `transaction_doc_cross_check`：
```python
    SkillRegistration(
        skill_id="transaction_doc_cross_check",
        ...
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_transaction_cross_check",
        domain="sha_spa",
        category="validation",
        status="preview",  # 添加这一行
    ),
```

### 4. 后端 API：确认 `status` 字段会被返回

检查 `api_server.py` 中 `/api/v3/skills` 相关端点。`SkillRegistration` 继承自 `BaseModel`，新增的 `status` 字段会自动出现在 `.model_dump()` 的输出中。如果 API 端点使用了字段白名单过滤，需要把 `status` 加入白名单。

### 5. `frontend/src/views/SkillsView.vue`

#### 5a. 在 skill-tags 区域添加状态标签

在第 56-60 行的 `<div class="skill-tags">` 中，在现有三个 tag 之后添加状态标签：

```html
<div class="skill-tags">
  <span class="tag domain">{{ domainLabel(skill.domain) }}</span>
  <span class="tag backend">{{ backendLabel(skill.backend) }}</span>
  <span class="tag category">{{ categoryLabel(skill.category) }}</span>
  <span
    v-if="skill.status && skill.status !== 'active'"
    class="tag status"
    :class="'status-' + skill.status"
  >
    {{ statusLabel(skill.status) }}
  </span>
</div>
```

注意：`status === "active"` 时不显示标签（可用是默认状态，不需要额外标注）。

#### 5b. 在 `<script setup>` 中添加 `statusLabel` 函数

在 `categoryLabel` 函数（第 122-130 行）之后添加：

```javascript
function statusLabel(status) {
  const labels = {
    preview: '开发中',
    deprecated: '已废弃'
  }
  return labels[status] || status
}
```

#### 5c. 在 `<style scoped>` 中添加状态标签样式

在 `.tag.category` 样式（第 335-339 行）之后添加：

```css
.tag.status.status-preview {
  background: #fef3c7;
  color: #92400e;
  border-color: #fcd34d;
}

.tag.status.status-deprecated {
  background: #f3f4f6;
  color: #6b7280;
  border-color: #d1d5db;
}
```

#### 5d. 在筛选栏添加状态筛选（可选但建议）

在 `filterBackend` 的 `<select>` 之后添加第三个筛选器：

```html
<select v-model="filterStatus" class="filter-select">
  <option value="">全部状态</option>
  <option value="active">可用</option>
  <option value="preview">开发中</option>
</select>
```

在 `<script setup>` 中添加：
```javascript
const filterStatus = ref('')
```

在 `filteredSkills` 的 computed 中添加状态过滤条件：
```javascript
if (filterStatus.value && (skill.status || 'active') !== filterStatus.value) return false
```

## 不需要修改的文件

- `dispatcher.py` — 不需要改，`status` 字段不影响执行逻辑
- `builder.py` — 不需要改，现有的 Refly 跳过逻辑已经足够
- 测试文件 — `status` 有默认值 `"active"`，现有测试不受影响

## 验证

1. 运行 `PYTHONPATH=backend/src python -m pytest tests/ -x -q`，确保所有测试通过
2. 本地启动前端，访问 `/skills` 页面，确认：
   - Local Skills 没有额外标签（status 默认 active，不显示）
   - 4 个 Refly Skills 显示橙色「开发中」标签
   - 筛选器能正确过滤
