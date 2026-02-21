# SPEC-16: 语义检索通用化重构

> 优先级：高（为 SHA/SPA 场景复用铺路）
> 前置依赖：SPEC-15（FIDIC Local Skills，已完成）
> 预计新建文件：2 个 | 修改文件：5 个 | 删除文件：0 个
> 范围：将 `fidic_search_er` 中的语义检索能力提取为通用 Skill，FIDIC 和 SHA/SPA 共用

---

## 1. 背景与目标

### 1.1 现状

SPEC-15 实现了 `fidic_search_er`，其核心逻辑是：

1. 从文档结构中递归提取段落（`_collect_er_sections`）
2. 调用 Dashscope Embedding API 生成向量（`_embed_texts`）
3. 用 numpy 计算余弦相似度（`_cosine_similarity`）
4. 按相似度排序、过滤、返回 top_k

这四步完全不含 FIDIC 专有逻辑。唯一的 FIDIC 耦合点是：

- 文件位于 `skills/fidic/search_er.py`
- 输入字段叫 `er_structure`（ER 是 FIDIC 特有概念）
- `builder.py` 中按文件名包含 "er" 来查找参考文档

SHA/SPA 场景同样需要语义检索能力——例如审查 SPA 时，需要在披露函（Disclosure Letter）中检索与某条 R&W 相关的段落，或在交易文件间做交叉检索。逻辑完全一样，只是"参考文档"的角色不同。

### 1.2 目标

1. 将语义检索的核心能力（embedding + 相似度 + 段落提取）提取到 `skills/local/` 作为通用工具
2. 注册一个通用 Skill `search_reference_doc`，放在 `_GENERIC_SKILLS` 中，所有领域可用
3. `fidic_search_er` 变为薄包装，调用通用检索 + FIDIC 特定的 query 构造
4. SHA/SPA 的两个 Refly Skill（`sha_governance_check`、`transaction_doc_cross_check`）中，`transaction_doc_cross_check` 可部分复用通用检索能力

### 1.3 设计原则

- **不改变外部行为** — `fidic_search_er` 的输入输出 Schema 不变，下游 prompts 无需修改
- **通用 Skill 输入通用化** — 用 `reference_structure` 替代 `er_structure`，用 `doc_role` 替代硬编码的 "er"
- **零新增依赖** — 复用已有的 `dashscope` 和 `numpy`
- **现有测试不回归** — `test_fidic_search_er.py` 全部保持通过

---

## 2. 文件清单

### 新增文件（2 个）

| 文件路径 | 用途 |
|---------|------|
| `backend/src/contract_review/skills/local/semantic_search.py` | 通用语义检索 Skill 实现 |
| `tests/test_semantic_search.py` | 通用语义检索单元测试 |

### 修改文件（5 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/skills/fidic/search_er.py` | 改为薄包装，核心逻辑委托给通用模块 |
| `backend/src/contract_review/graph/builder.py` | 在 `_GENERIC_SKILLS` 中注册 `search_reference_doc`；更新 `_build_skill_input` |
| `backend/src/contract_review/plugins/sha_spa.py` | `transaction_doc_cross_check` 改为 LOCAL，使用通用检索 |
| `backend/src/contract_review/skills/local/_utils.py` | 无改动（确认 `ensure_dict` 已可复用） |
| `tests/test_fidic_search_er.py` | 更新 monkeypatch 路径（如果内部调用路径变化） |

### 不需要修改的文件

- `schema.py` — 不需要新增字段
- `dispatcher.py` — `LocalSkillExecutor` 已支持，无需改动
- `prompts.py` — skill_context 的格式化逻辑是通用的，无需改动
- `check_pc_consistency.py` — 不涉及语义检索
- `fidic.py`（插件）— `fidic_search_er` 的注册信息不变

---

## 3. 通用语义检索 Skill 设计

### 3.1 文件：`skills/local/semantic_search.py`

#### 输入/输出 Schema

```python
class SearchReferenceDocInput(BaseModel):
    clause_id: str
    document_structure: Any           # 主文档结构（用于提取查询文本）
    reference_structure: Any = None   # 参考文档结构（被检索的目标）
    query: str = ""                   # 检索查询文本
    top_k: int = 5
    min_score: float = 0.3            # 相似度阈值，允许调用方覆盖

class MatchedSection(BaseModel):
    section_id: str
    text: str
    relevance_score: float            # 0-1

class SearchReferenceDocOutput(BaseModel):
    clause_id: str
    matched_sections: list[MatchedSection] = Field(default_factory=list)
    total_found: int = 0
    search_method: str = "dashscope_embedding"
```

#### 核心函数迁移

从 `fidic/search_er.py` 迁移以下函数到 `local/semantic_search.py`，保持逻辑不变：

| 函数 | 说明 |
|------|------|
| `_collect_sections(structure)` | 原 `_collect_er_sections`，改名去掉 "er" |
| `_embed_texts(texts)` | 不变，Dashscope Embedding 调用 |
| `_cosine_similarity(query_vec, doc_vecs)` | 不变，numpy 余弦相似度 |
| `async search_reference_doc(input_data)` | 通用 handler，原 `search_er` 的核心逻辑 |

#### Handler 实现

```python
async def search_reference_doc(
    input_data: SearchReferenceDocInput,
) -> SearchReferenceDocOutput:
    """在参考文档中检索与查询文本语义相关的段落。"""

    query = (input_data.query or "").strip()
    if not query:
        query = input_data.clause_id

    sections = _collect_sections(input_data.reference_structure)
    if not sections:
        return SearchReferenceDocOutput(clause_id=input_data.clause_id)

    texts = [query] + [row["text"] for row in sections]
    vectors = _embed_texts(texts)
    if vectors.size == 0 or len(vectors) != len(texts):
        return SearchReferenceDocOutput(clause_id=input_data.clause_id)

    scores = _cosine_similarity(vectors[0], vectors[1:])
    if scores.size == 0:
        return SearchReferenceDocOutput(clause_id=input_data.clause_id)

    ranked = [
        (float(score), section)
        for score, section in zip(scores.tolist(), sections)
    ]
    ranked.sort(key=lambda x: x[0], reverse=True)

    top_k = max(1, int(input_data.top_k or 5))
    min_score = input_data.min_score
    results: list[MatchedSection] = []
    for score, section in ranked:
        if score < min_score:
            continue
        results.append(
            MatchedSection(
                section_id=section["section_id"],
                text=section["text"],
                relevance_score=round(score, 4),
            )
        )
        if len(results) >= top_k:
            break

    return SearchReferenceDocOutput(
        clause_id=input_data.clause_id,
        matched_sections=results,
        total_found=len(results),
    )
```

与原 `search_er` 的区别：
- `er_structure` → `reference_structure`（通用命名）
- `ErSection` → `MatchedSection`（通用命名）
- `relevant_sections` → `matched_sections`（通用命名）
- `_MIN_SCORE` 硬编码 → `min_score` 参数化，默认 0.3
- 其余逻辑完全一致

---

### 3.2 `fidic/search_er.py` 改为薄包装

重构后的 `search_er.py` 只做两件事：
1. 保持原有的 `SearchErInput` / `SearchErOutput` / `ErSection` Schema 不变（保证下游兼容）
2. 内部调用通用 `search_reference_doc`，做输入输出转换

```python
"""FIDIC ER 语义检索 — 薄包装，委托给通用语义检索。"""

from __future__ import annotations
from typing import Any, List
from pydantic import BaseModel, Field
from ..local.semantic_search import (
    SearchReferenceDocInput,
    search_reference_doc,
)


class SearchErInput(BaseModel):
    clause_id: str
    document_structure: Any
    er_structure: Any = None
    query: str = ""
    top_k: int = 5


class ErSection(BaseModel):
    section_id: str
    text: str
    relevance_score: float


class SearchErOutput(BaseModel):
    clause_id: str
    relevant_sections: List[ErSection] = Field(default_factory=list)
    total_found: int = 0
    search_method: str = "dashscope_embedding"


async def search_er(input_data: SearchErInput) -> SearchErOutput:
    """在 ER 文档中检索与当前条款相关的段落。"""
    generic_input = SearchReferenceDocInput(
        clause_id=input_data.clause_id,
        document_structure=input_data.document_structure,
        reference_structure=input_data.er_structure,
        query=input_data.query,
        top_k=input_data.top_k,
    )
    generic_output = await search_reference_doc(generic_input)

    return SearchErOutput(
        clause_id=generic_output.clause_id,
        relevant_sections=[
            ErSection(
                section_id=s.section_id,
                text=s.text,
                relevance_score=s.relevance_score,
            )
            for s in generic_output.matched_sections
        ],
        total_found=generic_output.total_found,
    )
```

关键点：
- `SearchErInput` / `ErSection` / `SearchErOutput` 保持不变，下游零改动
- `fidic.py` 插件注册不变（`local_handler` 仍指向 `search_er.search_er`）
- `builder.py` 中 `fidic_search_er` 的输入构造不变

---

## 4. SHA/SPA 集成

### 4.1 `transaction_doc_cross_check` 改为 LOCAL

当前 `sha_spa.py` 中 `transaction_doc_cross_check` 是 Refly Skill（`status="preview"`）。改为 LOCAL，复用通用语义检索：

```python
# 修改前
SkillRegistration(
    skill_id="transaction_doc_cross_check",
    name="交易文件交叉检查",
    description="跨文档一致性检查",
    backend=SkillBackend.REFLY,
    refly_workflow_id="refly_wf_transaction_cross_check",
    domain="sha_spa",
    category="validation",
    status="preview",
),

# 修改后
SkillRegistration(
    skill_id="transaction_doc_cross_check",
    name="交易文件交叉检查",
    description="在关联交易文件中检索与当前条款相关的段落",
    backend=SkillBackend.LOCAL,
    local_handler="contract_review.skills.local.semantic_search.search_reference_doc",
    domain="sha_spa",
    category="validation",
),
```

注意：`transaction_doc_cross_check` 直接使用通用 `search_reference_doc` 作为 handler，不需要薄包装。因为它本身就是"在参考文档中做语义检索"，没有额外的领域逻辑。

### 4.2 `sha_governance_check` 暂不改动

`sha_governance_check`（治理条款完整性检查）的核心是规则推理，不是语义检索，和 `search_reference_doc` 能力不匹配。保持 `status="preview"` 不变，后续单独设计。

### 4.3 `builder.py` 新增 `_build_skill_input` 分支

```python
if skill_id == "transaction_doc_cross_check":
    from ..skills.local.semantic_search import SearchReferenceDocInput

    clause_text = _extract_clause_text(primary_structure, clause_id)
    query = " ".join(
        part for part in [
            clause_text[:500],
            state.get("material_type", ""),
        ] if part
    )
    # 从 documents 中查找关联交易文件（非主文档的 reference 文档）
    ref_structure = None
    for doc in state.get("documents", []):
        doc_dict = _as_dict(doc)
        role = str(doc_dict.get("role", "") or "").lower()
        if role == "reference":
            ref_structure = doc_dict.get("structure")
            break

    return SearchReferenceDocInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        reference_structure=ref_structure,
        query=query or clause_id,
        top_k=5,
    )
```

### 4.4 通用 Skill 注册

在 `builder.py` 的 `_GENERIC_SKILLS` 列表中新增：

```python
SkillRegistration(
    skill_id="search_reference_doc",
    name="参考文档语义检索",
    description="在参考文档中检索与当前条款语义相关的段落",
    backend=SkillBackend.LOCAL,
    local_handler="contract_review.skills.local.semantic_search.search_reference_doc",
    domain="*",
    category="validation",
),
```

这样任何领域的 checklist 都可以引用 `search_reference_doc`，无需每个领域单独注册。

---

## 5. 测试要求

### 5.1 `tests/test_semantic_search.py`（新增）

```python
# 测试用例清单

def test_search_reference_doc_basic_match():
    """参考文档中有相关段落时，返回按相似度排序的结果。"""

def test_search_reference_doc_no_reference():
    """reference_structure 为 None 时，返回空 matched_sections。"""

def test_search_reference_doc_no_match():
    """所有段落相似度低于阈值时，返回空列表。"""

def test_search_reference_doc_top_k_limit():
    """结果数量不超过 top_k。"""

def test_search_reference_doc_custom_min_score():
    """自定义 min_score 阈值生效。"""

def test_search_reference_doc_chinese_text():
    """中文文本的检索。"""

def test_collect_sections_nested():
    """递归展平嵌套 children 结构。"""
```

测试策略：通过 monkeypatch mock `_embed_texts`，与现有 `test_fidic_search_er.py` 一致。

### 5.2 `tests/test_fidic_search_er.py`（更新）

monkeypatch 路径可能需要从 `contract_review.skills.fidic.search_er._embed_texts` 改为 `contract_review.skills.local.semantic_search._embed_texts`，因为实际的 `_embed_texts` 函数已迁移到通用模块。

需要确认：如果 `search_er.py` 薄包装内部调用 `search_reference_doc`，而 `search_reference_doc` 调用 `_embed_texts`，那么 monkeypatch 的目标路径应该是 `contract_review.skills.local.semantic_search._embed_texts`。

### 5.3 运行命令

```bash
PYTHONPATH=backend/src python -m pytest tests/test_semantic_search.py tests/test_fidic_search_er.py tests/test_fidic_check_pc_consistency.py -x -q
```

全量测试：

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

---

## 6. 验收标准

1. `skills/local/semantic_search.py` 包含完整的通用语义检索实现（`_embed_texts`、`_cosine_similarity`、`_collect_sections`、`search_reference_doc`）
2. `fidic/search_er.py` 改为薄包装，内部委托给 `search_reference_doc`，输入输出 Schema 不变
3. `search_reference_doc` 在 `_GENERIC_SKILLS` 中注册，`domain="*"`
4. `transaction_doc_cross_check` 改为 `SkillBackend.LOCAL`，handler 指向 `search_reference_doc`，移除 `status="preview"`
5. `sha_governance_check` 保持 `status="preview"` 不变
6. 所有新增测试通过，全量测试无回归（现有 136 个测试 + 新增约 7 个）
7. `test_fidic_search_er.py` 的 monkeypatch 路径正确更新，6 个用例全部通过
