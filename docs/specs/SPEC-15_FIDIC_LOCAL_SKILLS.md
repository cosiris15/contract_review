# SPEC-15: FIDIC 专项 Local Skills 实现

> 优先级：高（完成 FIDIC 审查能力闭环）
> 前置依赖：SPEC-5（领域插件）、SPEC-12（动态执行）、SPEC-13（通用 Skills）
> 预计新建文件：4 个 | 修改文件：3 个
> 范围：仅 FIDIC 领域，SHA/SPA 不在本期范围内

---

## 1. 背景与目标

### 1.1 现状

FIDIC 插件（`plugins/fidic.py`）注册了 4 个领域 Skills：

| Skill ID | 当前状态 | Backend | 说明 |
|----------|---------|---------|------|
| `fidic_merge_gc_pc` | 已实现 | LOCAL | GC+PC 合并对比 |
| `fidic_calculate_time_bar` | 已实现 | LOCAL | 索赔时效计算 |
| `fidic_search_er` | 未实现 | REFLY → **改为 LOCAL** | ER 语义检索 |
| `fidic_check_pc_consistency` | 未实现 | REFLY → **改为 LOCAL** | PC 一致性检查 |

后两个 Skill 原计划通过 Refly 平台 Workflow 实现，但因 Refly 未开放 Knowledge Base 管理 API，且数据本身就在本地后端，决定改为 Local Skills 实现。详见 [归档文档](../refly/REFLY_WORKFLOW_SPEC_FIDIC.md)。

### 1.2 目标

将 `fidic_search_er` 和 `fidic_check_pc_consistency` 实现为 Local Skills，使 FIDIC 审查清单中所有 `required_skills` 都有对应的可用实现。

实现后，FIDIC 审查清单 12 个条款的 skill 依赖将全部满足：
- 条款 4.1（承包商义务）引用 `fidic_check_pc_consistency` → 可用
- 条款 20.1（承包商索赔）引用 `fidic_search_er`（如果 checklist 中添加）→ 可用

### 1.3 设计原则

- **不调用 LLM 做推理** — `check_pc_consistency` 使用规则引擎，不调用 LLM；`search_er` 调用 Dashscope Embedding API 做向量化（不是 LLM 推理），API 失败时 graceful 降级返回空结果
- **新增依赖最小化** — 仅需 `dashscope`（已安装）和 `numpy`，不引入 RAG 框架
- **输入来自 `_build_skill_input`** — 复用 `builder.py` 中已有的输入构造逻辑
- **输出注入 `skill_context`** — LLM 在 `node_clause_analyze` 中通过 prompt 消费 skill 输出

## 2. 文件清单

### 新增文件（4 个）

| 文件路径 | 用途 |
|---------|------|
| `backend/src/contract_review/skills/fidic/search_er.py` | ER 语义检索 Local Skill |
| `backend/src/contract_review/skills/fidic/check_pc_consistency.py` | PC 一致性检查 Local Skill |
| `tests/test_fidic_search_er.py` | search_er 单元测试 |
| `tests/test_fidic_check_pc_consistency.py` | check_pc_consistency 单元测试 |

### 修改文件（3 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/plugins/fidic.py` | 将 2 个 Refly Skill 改为 LOCAL，指向新的 handler |
| `backend/src/contract_review/graph/builder.py` | 更新 `_build_skill_input` 中对应的输入构造逻辑 |
| `backend/src/contract_review/plugins/fidic.py` | 移除 `status="preview"`（改为 active） |

### 不需要修改的文件

- `schema.py` — 不需要新增字段
- `dispatcher.py` — `LocalSkillExecutor` 已支持，无需改动
- `prompts.py` — skill_context 的格式化逻辑是通用的，无需改动
- 现有测试文件 — 现有测试不受影响

---

## 3. Skill 详细设计

### 3.1 `fidic_search_er` — ER 文档相关段落检索

#### 功能

在用户上传的 ER（Employer's Requirements）文档中，根据当前审查条款的文本，找出语义相关的段落。使用 Dashscope Embedding API 生成向量，通过余弦相似度进行轻量级语义检索。

#### 设计思路

原 Refly 方案使用 Refly Knowledge Base 做 RAG 检索，但 KB API 未开放。Local 实现使用 Dashscope Embedding API（项目已有 `DASHSCOPE_API_KEY`）+ numpy 余弦相似度，实现轻量级语义检索：

1. 将查询文本和所有 ER 段落文本发送给 Dashscope `text-embedding-v3` 生成向量
2. 用 numpy 计算查询向量与每个段落向量的余弦相似度
3. 取 top_k 个相似度最高的段落，过滤掉相似度低于阈值的结果
4. 返回排序后的相关段落列表

相比 TF-IDF，Embedding 方案能处理同义词、跨语言（中英混合）和语义相近但用词不同的情况，对 FIDIC 合同审查场景至关重要。

**新增依赖：** `dashscope`（已安装，OCR 在用）、`numpy`

#### 输入/输出 Schema

```python
class SearchErInput(BaseModel):
    clause_id: str
    document_structure: Any  # 主文档（PC）结构
    er_structure: Any = None  # ER 文档结构（从 state.documents 中获取）
    query: str = ""  # 检索查询文本（由 builder 构造）
    top_k: int = 5

class ErSection(BaseModel):
    section_id: str
    text: str
    relevance_score: float  # 0-1

class SearchErOutput(BaseModel):
    clause_id: str
    relevant_sections: List[ErSection] = Field(default_factory=list)
    total_found: int = 0
    search_method: str = "dashscope_embedding"  # 标记使用的检索方法
```

#### 核心算法

```python
import logging
import numpy as np
from dashscope import TextEmbedding

logger = logging.getLogger(__name__)

# Dashscope embedding 模型
_EMBEDDING_MODEL = "text-embedding-v3"
# 单次 API 调用最大文本数（Dashscope 限制 25 条）
_BATCH_SIZE = 25
# 相似度阈值
_MIN_SCORE = 0.3


def _embed_texts(texts: list[str]) -> np.ndarray:
    """调用 Dashscope Embedding API 将文本列表转为向量矩阵。

    返回 shape=(len(texts), dim) 的 numpy 数组。
    如果 API 调用失败，返回空数组。
    """
    if not texts:
        return np.array([])

    all_embeddings = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        try:
            response = TextEmbedding.call(
                model=_EMBEDDING_MODEL,
                input=batch,
            )
            if response.status_code == 200:
                embeddings = [
                    item["embedding"]
                    for item in response.output["embeddings"]
                ]
                all_embeddings.extend(embeddings)
            else:
                logger.warning(
                    "Dashscope Embedding 调用失败: %s", response.message
                )
                return np.array([])
        except Exception as exc:
            logger.warning("Dashscope Embedding 异常: %s", exc)
            return np.array([])

    return np.array(all_embeddings)


def _cosine_similarity(query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
    """计算 query 向量与多个 doc 向量的余弦相似度。"""
    if query_vec.size == 0 or doc_vecs.size == 0:
        return np.array([])
    # query_vec: (dim,), doc_vecs: (n, dim)
    dot_products = np.dot(doc_vecs, query_vec)
    query_norm = np.linalg.norm(query_vec)
    doc_norms = np.linalg.norm(doc_vecs, axis=1)
    # 避免除零
    norms = query_norm * doc_norms
    norms[norms == 0] = 1.0
    return dot_products / norms
```

**Embedding API 调用说明：**
- 使用 `dashscope.TextEmbedding.call()`，API Key 从环境变量 `DASHSCOPE_API_KEY` 自动读取
- 模型 `text-embedding-v3` 支持中英文混合文本，输出 1024 维向量
- 每次最多 25 条文本，超过时分批调用
- API 失败时 graceful 降级，返回空结果（不阻塞审查流程）

#### Handler 函数签名

```python
async def search_er(input_data: SearchErInput) -> SearchErOutput:
    """在 ER 文档中检索与当前条款相关的段落。"""
```

#### 处理流程

```
1. 提取查询文本
   - 优先使用 input_data.query（由 builder 从条款文本前 500 字构造）
   - 如果为空，从 document_structure 中提取条款文本

2. 获取 ER 文档段落
   - 从 input_data.er_structure 中提取所有段落（clauses 列表，递归展平）
   - 如果 er_structure 为 None，返回空结果

3. 调用 Dashscope Embedding API
   - 将查询文本和所有 ER 段落文本合并为一个列表
   - 调用 _embed_texts() 批量生成向量（自动分批，每批 ≤ 25 条）
   - 如果 API 失败，返回空结果（graceful 降级）

4. 计算余弦相似度
   - 用 _cosine_similarity() 计算查询向量与每个段落向量的相似度

5. 排序和过滤
   - 按相似度降序排列
   - 过滤掉相似度 < 0.3 的段落（embedding 相似度阈值高于 TF-IDF）
   - 取 top_k 个结果

6. 返回 SearchErOutput
```

#### 下游消费

`builder.py` 中 `_build_skill_input` 已有 `fidic_search_er` 的输入构造逻辑（第 292-306 行），使用 `GenericSkillInput`。需要修改为使用新的 `SearchErInput`，并从 state 中获取 ER 文档结构。

`prompts.py` 中 `_build_fidic_instruction` 已有消费逻辑：

```python
er_data = skill_context.get("fidic_search_er", {})
if isinstance(er_data, dict) and er_data.get("relevant_sections"):
    er_context = f"【ER 检索】关联段落数量：{len(er_data.get('relevant_sections', []))}"
```

输出格式与原 Refly 方案的 `relevant_sections` 结构一致，下游无需修改。

---

### 3.2 `fidic_check_pc_consistency` — PC 条款一致性检查

#### 功能

检查 PC（Particular Conditions）中各修改条款之间的内在一致性，识别潜在矛盾或冲突。不使用 LLM，而是基于规则引擎做结构化检测。

#### 设计思路

原 Refly 方案使用 LLM 推理来分析条款间矛盾。Local 实现采用规则引擎，基于 FIDIC 合同审查的专业知识，预定义一组一致性检查规则：

1. 从 state 的 `findings` 中收集所有已分析条款的 `fidic_merge_gc_pc` 结果
2. 筛选出 `modification_type` 为 `modified` 或 `added` 的条款
3. 对聚焦条款与其他修改条款逐对运行规则检查
4. 每条规则检测一种特定类型的不一致

#### 输入/输出 Schema

```python
class PcClause(BaseModel):
    clause_id: str
    text: str
    modification_type: str  # "modified" | "added"

class CheckPcConsistencyInput(BaseModel):
    clause_id: str  # 当前聚焦条款
    document_structure: Any
    pc_clauses: List[PcClause] = Field(default_factory=list)
    focus_clause_id: str = ""

class ConsistencyIssue(BaseModel):
    clause_a: str  # 聚焦条款
    clause_b: str  # 冲突条款
    issue: str  # 问题描述（中文）
    severity: str  # "high" | "medium" | "low"
    rule_id: str  # 触发的规则 ID

class CheckPcConsistencyOutput(BaseModel):
    clause_id: str
    consistency_issues: List[ConsistencyIssue] = Field(default_factory=list)
    total_issues: int = 0
    clauses_checked: int = 0
```

#### 规则引擎设计

预定义 6 类一致性检查规则，每条规则是一个函数，接收两个条款文本，返回 `ConsistencyIssue | None`：

```python
# 规则注册表
CONSISTENCY_RULES: List[ConsistencyRule] = [
    ConsistencyRule(
        rule_id="obligation_vs_liability_cap",
        name="义务扩大 vs 责任上限",
        description="检查义务范围扩大但责任限制未相应调整",
        clause_pairs=[("4.1", "17.6"), ("4.12", "17.6")],
        severity="high",
        check_fn=check_obligation_vs_liability,
    ),
    ConsistencyRule(
        rule_id="time_bar_vs_procedure",
        name="时效缩短 vs 程序要求",
        description="检查索赔期限缩短但程序要求未简化",
        clause_pairs=[("20.1", "20.2")],
        severity="high",
        check_fn=check_time_bar_vs_procedure,
    ),
    ConsistencyRule(
        rule_id="payment_vs_schedule",
        name="付款条件 vs 工期要求",
        description="检查工期压缩但付款周期未缩短",
        clause_pairs=[("8.2", "14.7"), ("8.2", "14.1")],
        severity="medium",
        check_fn=check_payment_vs_schedule,
    ),
    ConsistencyRule(
        rule_id="risk_transfer_vs_insurance",
        name="风险转移 vs 保险要求",
        description="检查风险转移给承包商但保险条款未调整",
        clause_pairs=[("4.1", "18.1"), ("4.12", "18.1")],
        severity="medium",
        check_fn=check_risk_vs_insurance,
    ),
    ConsistencyRule(
        rule_id="rights_vs_obligations",
        name="权利削减 vs 义务对等",
        description="检查删除了某项权利但对应义务仍在",
        clause_pairs=[("20.1", "4.1")],
        severity="medium",
        check_fn=check_rights_vs_obligations,
    ),
    ConsistencyRule(
        rule_id="cross_reference_stale",
        name="交叉引用失效",
        description="检查修改了某条款但引用它的其他条款未同步更新",
        clause_pairs=[],  # 动态检测所有对
        severity="low",
        check_fn=check_cross_reference_stale,
    ),
]
```

#### 规则检查函数示例

```python
def check_obligation_vs_liability(
    clause_a_text: str,
    clause_b_text: str,
    clause_a_id: str,
    clause_b_id: str,
) -> ConsistencyIssue | None:
    """检查义务扩大但责任上限未调整。"""
    # 义务扩大关键词
    obligation_expansion = [
        "shall be responsible for",
        "including but not limited to",
        "承包商应负责",
        "包括但不限于",
        "全部责任",
        "entire",
    ]
    # 责任限制关键词
    liability_cap = [
        r"\d+%\s*of\s*the\s*Contract\s*Price",
        r"合同价格的\s*\d+%",
        r"shall not exceed",
        r"不超过",
    ]

    a_has_expansion = any(
        kw.lower() in clause_a_text.lower() for kw in obligation_expansion
    )
    b_has_cap = any(
        re.search(pattern, clause_b_text, re.IGNORECASE) for pattern in liability_cap
    )

    if a_has_expansion and b_has_cap:
        return ConsistencyIssue(
            clause_a=clause_a_id,
            clause_b=clause_b_id,
            issue=f"条款 {clause_a_id} 扩大了承包商义务范围，但条款 {clause_b_id} 的责任上限未相应调整，存在责任与风险不匹配",
            severity="high",
            rule_id="obligation_vs_liability_cap",
        )
    return None
```

#### Handler 函数签名

```python
async def check_pc_consistency(
    input_data: CheckPcConsistencyInput,
) -> CheckPcConsistencyOutput:
    """检查 PC 修改条款之间的一致性。"""
```

#### 处理流程

```
1. 获取 PC 修改条款列表
   - 从 input_data.pc_clauses 获取（由 builder 从 state.findings 中收集）
   - 如果列表为空或只有 1 个条款，返回空结果

2. 确定聚焦条款
   - focus_clause_id = input_data.focus_clause_id 或 input_data.clause_id

3. 遍历规则
   - 对每条规则，检查 clause_pairs 是否包含聚焦条款
   - 如果 clause_pairs 为空（如 cross_reference_stale），动态检测所有对
   - 调用 check_fn，收集非 None 的结果

4. 返回 CheckPcConsistencyOutput
```

#### 下游消费

`builder.py` 中 `_build_skill_input` 已有 `fidic_check_pc_consistency` 的输入构造逻辑（第 266-290 行），从 `state.findings` 中收集 PC 修改条款。需要修改为使用新的 `CheckPcConsistencyInput`，将 `GenericSkillInput` 替换。

输出的 `consistency_issues` 结构与原 Refly 方案一致（`clause_a`, `clause_b`, `issue`, `severity`），新增 `rule_id` 字段。下游 `prompts.py` 的 `_format_skill_context` 通用格式化逻辑无需修改。

---

## 4. 插件注册改动

### 4.1 `plugins/fidic.py` 修改

将两个 Refly Skill 改为 LOCAL：

```python
# 修改前
SkillRegistration(
    skill_id="fidic_search_er",
    ...
    backend=SkillBackend.REFLY,
    refly_workflow_id="c-cxcin1htmspl8xq419kzseii",
    ...
    status="preview",
),

# 修改后
SkillRegistration(
    skill_id="fidic_search_er",
    name="ER 文档检索",
    description="在业主方要求文档中检索与当前条款相关的段落",
    backend=SkillBackend.LOCAL,
    local_handler="contract_review.skills.fidic.search_er.search_er",
    domain="fidic",
    category="validation",
),
```

```python
# 修改前
SkillRegistration(
    skill_id="fidic_check_pc_consistency",
    ...
    backend=SkillBackend.REFLY,
    refly_workflow_id="refly_wf_fidic_pc_consistency",
    ...
    status="preview",
),

# 修改后
SkillRegistration(
    skill_id="fidic_check_pc_consistency",
    name="PC 一致性检查",
    description="检查 PC 各修改条款之间的内在一致性",
    backend=SkillBackend.LOCAL,
    local_handler="contract_review.skills.fidic.check_pc_consistency.check_pc_consistency",
    domain="fidic",
    category="validation",
),
```

注意：移除 `refly_workflow_id` 和 `status="preview"`，改为 `local_handler`。

### 4.2 `builder.py` 修改

#### `_build_skill_input` 中 `fidic_search_er` 分支（第 292-306 行）

```python
# 修改前：使用 GenericSkillInput
if skill_id == "fidic_search_er":
    clause_text = _extract_clause_text(primary_structure, clause_id)
    query = " ".join(...)
    return GenericSkillInput(...)

# 修改后：使用 SearchErInput，传入 ER 文档结构
if skill_id == "fidic_search_er":
    from ..skills.fidic.search_er import SearchErInput

    clause_text = _extract_clause_text(primary_structure, clause_id)
    query = " ".join(
        part for part in [
            clause_text[:500],
            state.get("material_type", ""),
            state.get("domain_subtype", ""),
        ] if part
    )
    # 从 documents 中查找 ER 文档
    er_structure = None
    for doc in state.get("documents", []):
        doc_dict = _as_dict(doc)
        if doc_dict.get("role") == "reference" and "er" in doc_dict.get("name", "").lower():
            er_structure = doc_dict.get("structure")
            break

    return SearchErInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        er_structure=er_structure,
        query=query or clause_id,
        top_k=5,
    )
```

#### `_build_skill_input` 中 `fidic_check_pc_consistency` 分支（第 266-290 行）

```python
# 修改前：使用 GenericSkillInput
if skill_id == "fidic_check_pc_consistency":
    ...
    return GenericSkillInput(...)

# 修改后：使用 CheckPcConsistencyInput
if skill_id == "fidic_check_pc_consistency":
    from ..skills.fidic.check_pc_consistency import CheckPcConsistencyInput, PcClause

    findings = state.get("findings", {})
    pc_clauses = []
    for cid, finding in findings.items():
        row = _as_dict(finding)
        skills_data = row.get("skill_context", {})
        merge_data = _as_dict(skills_data.get("fidic_merge_gc_pc"))
        mod_type = merge_data.get("modification_type", "")
        if mod_type in {"modified", "added"}:
            pc_clauses.append(PcClause(
                clause_id=cid,
                text=merge_data.get("pc_text", ""),
                modification_type=mod_type,
            ))

    return CheckPcConsistencyInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        pc_clauses=pc_clauses,
        focus_clause_id=clause_id,
    )
```

---

## 5. 测试要求

### 5.1 `tests/test_fidic_search_er.py`

```python
# 测试用例清单

def test_search_er_basic_match():
    """ER 文档中有相关段落时，返回按相似度排序的结果。"""

def test_search_er_no_er_document():
    """er_structure 为 None 时，返回空 relevant_sections。"""

def test_search_er_no_match():
    """ER 文档中没有相关段落时，返回空列表。"""

def test_search_er_top_k_limit():
    """结果数量不超过 top_k。"""

def test_search_er_relevance_threshold():
    """相似度低于阈值的段落被过滤。"""

def test_search_er_chinese_text():
    """中文条款和 ER 文档的检索。"""
```

### 5.2 `tests/test_fidic_check_pc_consistency.py`

```python
# 测试用例清单

def test_consistency_obligation_vs_liability():
    """条款 4.1 扩大义务 + 条款 17.6 有责任上限 → 检出 high issue。"""

def test_consistency_no_issues():
    """所有条款一致时，返回空 consistency_issues。"""

def test_consistency_single_clause():
    """只有 1 个 PC 修改条款时，返回空结果。"""

def test_consistency_empty_clauses():
    """pc_clauses 为空时，返回空结果。"""

def test_consistency_cross_reference_stale():
    """条款 A 引用条款 B，B 被修改但 A 未更新 → 检出 low issue。"""

def test_consistency_multiple_issues():
    """一个聚焦条款可能触发多条规则。"""
```

### 5.3 运行命令

```bash
PYTHONPATH=backend/src python -m pytest tests/test_fidic_search_er.py tests/test_fidic_check_pc_consistency.py -x -q
```

全量测试：

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

---

## 6. 验收标准

1. `fidic_search_er` 和 `fidic_check_pc_consistency` 在 `plugins/fidic.py` 中注册为 `SkillBackend.LOCAL`，无 `status="preview"`
2. 两个 Skill 的 handler 函数可被 `SkillDispatcher` 正常注册和调用
3. `_build_skill_input` 中使用新的 Input Schema（不再使用 `GenericSkillInput`）
4. 所有新增测试通过，全量测试无回归
5. `search_er` 在有 ER 文档时返回按相似度排序的段落，无 ER 文档时返回空结果
6. `check_pc_consistency` 在有多个 PC 修改条款时能检出预定义规则匹配的一致性问题
7. 输出格式与原 Refly 方案兼容（`relevant_sections` / `consistency_issues`），下游 prompts 无需修改
