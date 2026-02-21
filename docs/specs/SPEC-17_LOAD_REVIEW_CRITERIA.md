# SPEC-17: 审核标准加载与条款匹配（`load_review_criteria`）

> 优先级：高（标准审核流程的基础设施）
> 前置依赖：SPEC-16（通用语义检索，提供 embedding 匹配能力）
> 预计新建文件：3 个 | 修改文件：4 个
> 范围：通用 Skill，`domain="*"`，FIDIC 和 SHA/SPA 均可使用

---

## 1. 背景与目标

### 1.1 业务场景

合作律所会提供 Excel 格式的审核标准表，每行一条审核要点，典型列结构如下：

| 条款编号 | 条款名称 | 审核要点 | 风险等级 | 标准条件/基准 | 建议措施 |
|---------|---------|---------|---------|-------------|---------|
| 4.1 | 承包商的一般义务 | 义务范围不应超出 Silver Book 原文 | 高 | GC 原文范围 | 如有扩大，建议限缩至... |
| 20.1 | 承包商索赔 | 索赔通知期限不应短于 28 天 | 高 | 28 天 | 如缩短，建议恢复至... |

初审工作的实质是：按这些标准逐条核对合同条款，判断偏离情况，给出建议。

### 1.2 现状

- Excel 解析代码已存在（`document_loader.py` 中的 `_read_xlsx`），但仅转为 Markdown 文本，未做结构化提取
- Excel 上传未在 API 中开放（`.xlsx` 不在 `ALLOWED_EXTENSIONS` 中）
- 没有 Skill 能将审核标准与合同条款进行匹配

### 1.3 目标

1. 开放 Excel 上传，新增文档角色 `criteria`（审核标准）
2. 实现 `load_review_criteria` 通用 Skill：解析 Excel 审核标准 → 结构化数据 → 按条款匹配
3. 匹配策略：条款编号精确匹配优先，无精确匹配时用语义检索兜底

### 1.4 设计原则

- **不改变现有上传流程** — 复用 `document_loader.py` + `api_gen3.py` 的上传管线，仅扩展支持的格式和角色
- **Excel 列名自适应** — 不硬编码列名，通过关键词模糊匹配识别列的语义角色
- **精确匹配优先** — 条款编号能匹配就不走 embedding，降低 API 调用和延迟
- **语义兜底** — 审核标准的条款编号可能和合同条款编号不完全一致（如标准写 "4.1"，合同写 "Sub-Clause 4.1"），用 `search_reference_doc` 的 embedding 能力兜底

---

## 2. 文件清单

### 新增文件（3 个）

| 文件路径 | 用途 |
|---------|------|
| `backend/src/contract_review/skills/local/load_review_criteria.py` | 审核标准加载与匹配 Skill |
| `backend/src/contract_review/criteria_parser.py` | Excel 审核标准结构化解析器 |
| `tests/test_load_review_criteria.py` | 单元测试 |

### 修改文件（4 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/api_gen3.py` | `ALLOWED_EXTENSIONS` 加入 `.xlsx`；`ALLOWED_ROLES` 加入 `criteria` |
| `backend/src/contract_review/graph/builder.py` | `_GENERIC_SKILLS` 注册 `load_review_criteria`；`_build_skill_input` 新增分支 |
| `backend/src/contract_review/graph/prompts.py` | `_format_skill_context` 中为 `load_review_criteria` 添加格式化逻辑 |
| `backend/src/contract_review/models.py` | 新增 `ReviewCriterion` 数据模型 |

### 不需要修改的文件

- `document_loader.py` — `_read_xlsx` 已存在，但本 Skill 不走 `_read_xlsx`（它只转 Markdown），而是直接用 openpyxl 做结构化解析
- `dispatcher.py` — 无需改动
- `schema.py` — 无需改动

---

## 3. 数据模型

### 3.1 `ReviewCriterion`（新增，`models.py`）

```python
class ReviewCriterion(BaseModel):
    """单条审核标准。"""
    criterion_id: str              # 自动生成：RC-1, RC-2, ...
    clause_ref: str = ""           # Excel 中的条款编号（原始值）
    clause_name: str = ""          # 条款名称
    review_point: str              # 审核要点（核心内容）
    risk_level: str = ""           # 风险等级：高/中/低 或 high/medium/low
    baseline_text: str = ""        # 标准条件/基准描述
    suggested_action: str = ""     # 建议措施
    raw_row: dict = Field(default_factory=dict)  # 原始行数据（保留所有列）
```

---

## 4. Excel 解析器设计

### 4.1 文件：`criteria_parser.py`

#### 职责

将 Excel 文件解析为 `list[ReviewCriterion]`。不依赖固定列名，通过关键词匹配识别列的语义角色。

#### 列识别策略

```python
# 列名 → 语义角色的关键词映射
COLUMN_ROLE_KEYWORDS = {
    "clause_ref": ["条款编号", "条款号", "clause", "sub-clause", "编号", "ref"],
    "clause_name": ["条款名称", "名称", "clause name", "title", "标题"],
    "review_point": ["审核要点", "审查要点", "要点", "review point", "check point", "审核内容", "检查内容", "issue"],
    "risk_level": ["风险等级", "风险", "等级", "risk", "level", "severity", "优先级", "priority"],
    "baseline_text": ["标准条件", "基准", "baseline", "standard", "benchmark", "参考标准", "原文"],
    "suggested_action": ["建议措施", "建议", "措施", "suggestion", "action", "recommendation", "应对", "对策"],
}
```

#### 解析流程

```
1. 用 openpyxl 打开 Excel 文件
2. 读取第一个 sheet（或指定 sheet）
3. 取第一行作为表头
4. 对每个表头单元格，用 COLUMN_ROLE_KEYWORDS 做模糊匹配，确定语义角色
   - 匹配规则：表头文本（去空格、转小写）包含任一关键词即匹配
   - 如果 review_point 列未识别到，尝试用最长文本列作为 fallback
5. 逐行读取数据，跳过空行
6. 构造 ReviewCriterion 列表，自动编号 RC-1, RC-2, ...
7. 返回解析结果
```

#### 函数签名

```python
def parse_criteria_excel(
    file_path: str | Path,
    sheet_name: str | None = None,
) -> list[ReviewCriterion]:
    """解析 Excel 审核标准文件为结构化列表。"""
```

#### 容错处理

- 表头行为空 → 返回空列表
- 某列未识别 → 对应字段为空字符串，不报错
- `review_point` 列未识别 → 日志警告，尝试用内容最长的列作为 fallback
- 行数据全空 → 跳过
- 文件格式错误 → 捕获异常，返回空列表 + 日志警告

---

## 5. Skill 设计

### 5.1 文件：`skills/local/load_review_criteria.py`

#### 输入/输出 Schema

```python
class LoadReviewCriteriaInput(BaseModel):
    clause_id: str                          # 当前审查的条款 ID
    document_structure: Any                 # 主文档结构
    criteria_file_path: str = ""            # Excel 文件路径（从 state 中获取）
    criteria_data: list[dict] = Field(default_factory=list)  # 已解析的标准数据（缓存）

class MatchedCriterion(BaseModel):
    criterion_id: str
    clause_ref: str
    review_point: str
    risk_level: str
    baseline_text: str
    suggested_action: str
    match_type: str                         # "exact" | "semantic" | "none"
    match_score: float = 1.0               # 精确匹配为 1.0，语义匹配为相似度分数

class LoadReviewCriteriaOutput(BaseModel):
    clause_id: str
    matched_criteria: list[MatchedCriterion] = Field(default_factory=list)
    total_matched: int = 0
    has_criteria: bool = False              # 是否有审核标准文件
```

#### 匹配算法

```
1. 获取审核标准数据
   - 优先使用 criteria_data（已解析缓存）
   - 如果为空，从 criteria_file_path 解析 Excel
   - 如果都没有，返回 has_criteria=False

2. 精确匹配
   - 将当前 clause_id 标准化（去空格、去前缀 "Sub-Clause"/"条款" 等）
   - 遍历所有 ReviewCriterion，将 clause_ref 同样标准化
   - 完全匹配或前缀匹配（如 clause_id="4.1" 匹配 clause_ref="4.1"）
   - 收集所有精确匹配的标准

3. 语义兜底（仅在精确匹配为空时触发）
   - 从主文档中提取当前条款文本（前 300 字）
   - 将所有未匹配的 review_point 作为候选段落
   - 调用 _embed_texts + _cosine_similarity（复用 semantic_search 模块）
   - 取相似度 >= 0.5 的 top 3 结果
   - match_type 标记为 "semantic"

4. 返回 LoadReviewCriteriaOutput
```

#### 条款编号标准化函数

```python
def _normalize_clause_ref(ref: str) -> str:
    """标准化条款编号，用于匹配。

    '条款 4.1' → '4.1'
    'Sub-Clause 4.1' → '4.1'
    'Clause 4.1' → '4.1'
    '4.1 ' → '4.1'
    """
    ref = ref.strip()
    ref = re.sub(
        r"^(?:sub-clause|clause|条款|第)\s*",
        "",
        ref,
        flags=re.IGNORECASE,
    )
    return ref.strip().rstrip(".")
```

#### Handler 函数签名

```python
async def load_review_criteria(
    input_data: LoadReviewCriteriaInput,
) -> LoadReviewCriteriaOutput:
    """加载审核标准并匹配到当前条款。"""
```

---

## 6. 上传管线改动

### 6.1 `api_gen3.py` 改动

```python
# 改动 1：扩展允许的文件类型
ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md", ".xlsx"}

# 改动 2：扩展允许的角色
ALLOWED_ROLES = {"primary", "baseline", "supplement", "reference", "criteria"}
```

### 6.2 上传后的处理

当 `role="criteria"` 时，上传流程需要特殊处理：

```python
# 在上传处理逻辑中，role=="criteria" 时：
# 1. 不走 StructureParser（审核标准不是合同文档，不需要条款树解析）
# 2. 用 criteria_parser.parse_criteria_excel() 解析为 list[ReviewCriterion]
# 3. 将解析结果存入 state["criteria_data"]（序列化为 list[dict]）
# 4. 同时保存文件路径到 state["criteria_file_path"]
```

具体改动位置在上传 endpoint 中，`load_document` + `StructureParser` 之前加一个分支：

```python
if role == "criteria":
    from .criteria_parser import parse_criteria_excel
    criteria = parse_criteria_excel(saved_path)
    # 存入 state
    await _update_state(task_id, {
        "criteria_data": [c.model_dump() for c in criteria],
        "criteria_file_path": str(saved_path),
    })
    # 同时存入 documents 列表（保持一致性）
    doc_entry = {
        "id": _gen_doc_id(),
        "task_id": task_id,
        "role": "criteria",
        "filename": file.filename,
        "storage_name": saved_path.name,
        "structure": None,  # 审核标准没有 DocumentStructure
        "metadata": {"total_criteria": len(criteria), "source": "gen3_upload"},
        "uploaded_at": datetime.utcnow().isoformat(),
    }
    # ... 更新 state["documents"]
    return {"document_id": doc_entry["id"], "filename": file.filename, "role": "criteria", "total_criteria": len(criteria)}
```

---

## 7. builder.py 改动

### 7.1 注册通用 Skill

在 `_GENERIC_SKILLS` 中新增：

```python
SkillRegistration(
    skill_id="load_review_criteria",
    name="审核标准加载",
    description="加载审核标准并匹配到当前条款",
    backend=SkillBackend.LOCAL,
    local_handler="contract_review.skills.local.load_review_criteria.load_review_criteria",
    domain="*",
    category="validation",
),
```

### 7.2 `_build_skill_input` 新增分支

```python
if skill_id == "load_review_criteria":
    from ..skills.local.load_review_criteria import LoadReviewCriteriaInput

    return LoadReviewCriteriaInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        criteria_data=state.get("criteria_data", []),
        criteria_file_path=state.get("criteria_file_path", ""),
    )
```

---

## 8. prompts.py 改动

在 `_format_skill_context` 中为 `load_review_criteria` 添加专门的格式化：

```python
if skill_id == "load_review_criteria":
    data = ensure_dict(skill_data)
    if not data.get("has_criteria"):
        continue  # 没有审核标准，不注入
    criteria = data.get("matched_criteria", [])
    if not criteria:
        parts.append("[审核标准] 未找到与本条款匹配的审核要点。")
        continue
    lines = ["[审核标准] 以下是与本条款匹配的审核要点："]
    for c in criteria:
        lines.append(f"- 【{c.get('risk_level', '')}】{c.get('review_point', '')}")
        if c.get("baseline_text"):
            lines.append(f"  基准：{c['baseline_text']}")
        if c.get("suggested_action"):
            lines.append(f"  建议：{c['suggested_action']}")
        lines.append(f"  匹配方式：{c.get('match_type', '')}（{c.get('match_score', '')}）")
    parts.append("\n".join(lines))
    continue
```

这样 LLM 在 `node_clause_analyze` 中会看到类似：

```
【辅助分析信息】
[审核标准] 以下是与本条款匹配的审核要点：
- 【高】义务范围不应超出 Silver Book 原文
  基准：GC 原文范围
  建议：如有扩大，建议限缩至原文范围
  匹配方式：exact（1.0）
```

---

## 9. 测试要求

### 9.1 `tests/test_load_review_criteria.py`

```python
# --- criteria_parser 测试 ---

def test_parse_criteria_excel_normal():
    """正常 Excel 文件解析为 ReviewCriterion 列表。"""

def test_parse_criteria_excel_column_recognition():
    """不同列名风格（中文/英文/混合）都能正确识别。"""

def test_parse_criteria_excel_empty_rows():
    """空行被跳过，不生成空 criterion。"""

def test_parse_criteria_excel_missing_columns():
    """缺少某些列时，对应字段为空字符串，不报错。"""

def test_parse_criteria_excel_file_not_found():
    """文件不存在时返回空列表。"""

# --- load_review_criteria Skill 测试 ---

def test_load_criteria_exact_match():
    """clause_id 与 clause_ref 精确匹配。"""

def test_load_criteria_no_criteria():
    """没有审核标准数据时，has_criteria=False。"""

def test_load_criteria_no_match():
    """没有匹配的标准时，matched_criteria 为空。"""

def test_load_criteria_semantic_fallback():
    """精确匹配失败时，语义检索兜底。"""

def test_load_criteria_normalize_clause_ref():
    """'Sub-Clause 4.1' 和 '4.1' 能匹配。"""
```

### 9.2 测试数据

测试需要一个小型 Excel 文件。建议在测试中用 openpyxl 动态创建临时 Excel 文件，不提交二进制文件到仓库。

```python
@pytest.fixture
def sample_criteria_xlsx(tmp_path):
    """创建临时审核标准 Excel 文件。"""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["条款编号", "条款名称", "审核要点", "风险等级", "标准条件", "建议措施"])
    ws.append(["4.1", "承包商义务", "义务范围不应超出原文", "高", "GC 原文", "建议限缩"])
    ws.append(["20.1", "承包商索赔", "通知期限不应短于28天", "高", "28天", "建议恢复"])
    ws.append(["14.7", "期中付款", "付款周期应合理", "中", "56天", "建议缩短"])
    path = tmp_path / "criteria.xlsx"
    wb.save(path)
    return path
```

### 9.3 运行命令

```bash
PYTHONPATH=backend/src python -m pytest tests/test_load_review_criteria.py -x -q
```

全量测试：

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

---

## 10. 验收标准

1. `.xlsx` 文件可通过 `POST /api/v3/review/{task_id}/upload` 上传，`role="criteria"`
2. `criteria_parser.parse_criteria_excel()` 能正确解析不同列名风格的 Excel 文件
3. `load_review_criteria` Skill 在 `_GENERIC_SKILLS` 中注册，`domain="*"`
4. 精确匹配：`clause_id="4.1"` 能匹配 `clause_ref="4.1"` / `"Sub-Clause 4.1"` / `"条款 4.1"`
5. 语义兜底：精确匹配失败时，通过 embedding 相似度找到相关标准
6. `prompts.py` 中审核标准被格式化注入 LLM prompt
7. 所有新增测试通过，全量测试无回归
