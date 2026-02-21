# SPEC-13: 通用 Skills 实现

## 1. 概述

SPEC-12 建立了 Skills 动态执行机制。本 SPEC 实现 4 个通用 Skills，它们适用于所有合同审核场景，不依赖特定领域知识。

FIDIC checklist 中已引用但未实现的通用 Skills：
- `resolve_definition` — 被 clause 1.1 引用
- `compare_with_baseline` — 被 clause 4.1, 4.12, 14.1, 17.6, 20.2 引用
- `cross_reference_check` — 被 clause 4.1, 20.1 引用
- `extract_financial_terms` — 被 clause 8.2, 14.1, 14.2, 14.7, 17.6, 18.1 引用

这 4 个 Skills 都基于 `StructureParser` 已有的解析能力构建，不需要调用 LLM。

**前置依赖：** SPEC-12 必须先完成。

## 2. 文件清单

### 新增文件（共 5 个）

| 文件路径 | 用途 |
|---------|------|
| `backend/src/contract_review/skills/local/resolve_definition.py` | 定义解析 Skill |
| `backend/src/contract_review/skills/local/compare_with_baseline.py` | 基线文本对比 Skill |
| `backend/src/contract_review/skills/local/cross_reference_check.py` | 交叉引用检查 Skill |
| `backend/src/contract_review/skills/local/extract_financial_terms.py` | 财务条款提取 Skill |
| `tests/test_generic_skills.py` | 通用 Skills 单元测试 |

### 修改文件（共 2 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/graph/builder.py` | `_GENERIC_SKILLS` 列表中注册 4 个新 Skill；`_build_skill_input` 增加对应分支 |
| `backend/src/contract_review/skills/schema.py` | 如果 SPEC-12 未添加 `GenericSkillInput`，在此添加 |

## 3. Skill 详细设计

### 3.1 `resolve_definition`

**功能：** 从文档结构的 `definitions` 字典中查找当前条款引用的术语定义，返回相关定义列表。

**输入/输出：**

```python
class ResolveDefinitionInput(BaseModel):
    clause_id: str
    document_structure: Any  # dict 或 DocumentStructure
    terms: List[str] = Field(default_factory=list)  # 可选：指定要查找的术语

class ResolveDefinitionOutput(BaseModel):
    clause_id: str
    definitions_found: Dict[str, str] = Field(default_factory=dict)
    terms_not_found: List[str] = Field(default_factory=list)
```

**实现逻辑：**

```python
async def resolve_definition(input_data: ResolveDefinitionInput) -> ResolveDefinitionOutput:
    structure = _ensure_dict(input_data.document_structure)
    definitions = structure.get("definitions", {})

    if input_data.terms:
        # 查找指定术语
        found = {}
        not_found = []
        for term in input_data.terms:
            if term in definitions:
                found[term] = definitions[term]
            else:
                # 模糊匹配：忽略大小写和引号
                matched = _fuzzy_match_term(term, definitions)
                if matched:
                    found[term] = matched
                else:
                    not_found.append(term)
        return ResolveDefinitionOutput(
            clause_id=input_data.clause_id,
            definitions_found=found,
            terms_not_found=not_found,
        )

    # 未指定术语时：从条款文本中自动提取被引号包裹的术语
    clause_text = _get_clause_text(structure, input_data.clause_id)
    referenced_terms = _extract_quoted_terms(clause_text)
    found = {}
    not_found = []
    for term in referenced_terms:
        if term in definitions:
            found[term] = definitions[term]
        else:
            matched = _fuzzy_match_term(term, definitions)
            if matched:
                found[term] = matched
            else:
                not_found.append(term)
    return ResolveDefinitionOutput(
        clause_id=input_data.clause_id,
        definitions_found=found,
        terms_not_found=not_found,
    )
```

**辅助函数：**

```python
def _ensure_dict(structure: Any) -> dict:
    if isinstance(structure, dict):
        return structure
    if hasattr(structure, "model_dump"):
        return structure.model_dump()
    return {}

def _get_clause_text(structure: dict, clause_id: str) -> str:
    """复用 builder.py 中 _search_clauses 的逻辑。"""
    from contract_review.graph.builder import _extract_clause_text
    return _extract_clause_text(structure, clause_id)

def _extract_quoted_terms(text: str) -> List[str]:
    """提取文本中被引号包裹的术语。"""
    import re
    patterns = [r'"([^"]+)"', r'"([^"]+)"', r'"([^"]+)"']
    terms = []
    for pattern in patterns:
        terms.extend(re.findall(pattern, text))
    return list(set(terms))

def _fuzzy_match_term(term: str, definitions: Dict[str, str]) -> str | None:
    term_lower = term.lower().strip()
    for key, value in definitions.items():
        if key.lower().strip() == term_lower:
            return value
    return None
```

### 3.2 `compare_with_baseline`

**功能：** 将当前条款文本与 Plugin 提供的基线文本（`baseline_texts`）进行对比，返回差异摘要。

**输入/输出：**

```python
class CompareWithBaselineInput(BaseModel):
    clause_id: str
    document_structure: Any
    baseline_text: str = ""  # 由 _build_skill_input 从 Plugin 注入
    state_snapshot: Dict[str, Any] = Field(default_factory=dict)

class CompareWithBaselineOutput(BaseModel):
    clause_id: str
    has_baseline: bool = False
    current_text: str = ""
    baseline_text: str = ""
    is_identical: bool = False
    differences_summary: str = ""
```

**实现逻辑：**

```python
async def compare_with_baseline(input_data: CompareWithBaselineInput) -> CompareWithBaselineOutput:
    structure = _ensure_dict(input_data.document_structure)
    current_text = _get_clause_text(structure, input_data.clause_id)
    baseline = input_data.baseline_text

    if not baseline:
        return CompareWithBaselineOutput(
            clause_id=input_data.clause_id,
            has_baseline=False,
            current_text=current_text,
        )

    is_identical = _normalize_text(current_text) == _normalize_text(baseline)

    differences = ""
    if not is_identical:
        differences = _compute_diff_summary(baseline, current_text)

    return CompareWithBaselineOutput(
        clause_id=input_data.clause_id,
        has_baseline=True,
        current_text=current_text,
        baseline_text=baseline,
        is_identical=is_identical,
        differences_summary=differences,
    )
```

**辅助函数：**

```python
import difflib

def _normalize_text(text: str) -> str:
    """标准化文本用于比较：去除多余空白。"""
    return " ".join(text.split())

def _compute_diff_summary(baseline: str, current: str) -> str:
    """生成简洁的差异摘要。"""
    baseline_lines = baseline.splitlines()
    current_lines = current.splitlines()
    diff = difflib.unified_diff(baseline_lines, current_lines, lineterm="", n=1)
    added = []
    removed = []
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:].strip())
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:].strip())

    parts = []
    if removed:
        parts.append(f"删除内容：{'; '.join(removed[:5])}")
    if added:
        parts.append(f"新增内容：{'; '.join(added[:5])}")
    if not parts:
        parts.append("文本存在细微差异")
    return "\n".join(parts)
```

### 3.3 `cross_reference_check`

**功能：** 检查当前条款中的交叉引用是否有效（引用的目标条款是否存在于文档中）。

**输入/输出：**

```python
class CrossReferenceCheckInput(BaseModel):
    clause_id: str
    document_structure: Any

class CrossReferenceCheckOutput(BaseModel):
    clause_id: str
    references: List[Dict[str, Any]] = Field(default_factory=list)
    invalid_references: List[Dict[str, Any]] = Field(default_factory=list)
    total_references: int = 0
    total_invalid: int = 0
```

**实现逻辑：**

```python
async def cross_reference_check(input_data: CrossReferenceCheckInput) -> CrossReferenceCheckOutput:
    structure = _ensure_dict(input_data.document_structure)
    cross_refs = structure.get("cross_references", [])

    # 筛选当前条款的引用
    clause_refs = [
        ref for ref in cross_refs
        if _as_ref_dict(ref).get("source_clause_id") == input_data.clause_id
    ]

    references = []
    invalid = []
    for ref in clause_refs:
        ref_dict = _as_ref_dict(ref)
        entry = {
            "target_clause_id": ref_dict.get("target_clause_id", ""),
            "reference_text": ref_dict.get("reference_text", ""),
            "is_valid": ref_dict.get("is_valid", False),
        }
        references.append(entry)
        if not entry["is_valid"]:
            invalid.append(entry)

    return CrossReferenceCheckOutput(
        clause_id=input_data.clause_id,
        references=references,
        invalid_references=invalid,
        total_references=len(references),
        total_invalid=len(invalid),
    )

def _as_ref_dict(ref: Any) -> dict:
    if isinstance(ref, dict):
        return ref
    if hasattr(ref, "model_dump"):
        return ref.model_dump()
    return {}
```

### 3.4 `extract_financial_terms`

**功能：** 从条款文本中提取金额、百分比、期限等财务相关数值。

**输入/输出：**

```python
class ExtractFinancialTermsInput(BaseModel):
    clause_id: str
    document_structure: Any

class FinancialTerm(BaseModel):
    term_type: str  # "percentage" | "amount" | "duration" | "date"
    value: str
    context: str  # 包含该数值的原文片段

class ExtractFinancialTermsOutput(BaseModel):
    clause_id: str
    terms: List[FinancialTerm] = Field(default_factory=list)
    total_terms: int = 0
```

**实现逻辑：**

```python
import re

_FINANCIAL_PATTERNS = [
    # 百分比
    (r"(\d+(?:\.\d+)?)\s*[%％]", "percentage"),
    # 金额（带货币符号）
    (r"(?:USD|EUR|CNY|RMB|GBP|\$|€|£|¥)\s*[\d,]+(?:\.\d+)?", "amount"),
    # 金额（中文）
    (r"[\d,]+(?:\.\d+)?\s*(?:万元|亿元|元|美元|欧元|英镑)", "amount"),
    # 期限（天/月/年）
    (r"\d+\s*(?:天|日|个月|月|年|days?|months?|years?|weeks?|周)", "duration"),
    # 日期
    (r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?", "date"),
]

async def extract_financial_terms(input_data: ExtractFinancialTermsInput) -> ExtractFinancialTermsOutput:
    structure = _ensure_dict(input_data.document_structure)
    clause_text = _get_clause_text(structure, input_data.clause_id)

    terms = []
    for pattern, term_type in _FINANCIAL_PATTERNS:
        for match in re.finditer(pattern, clause_text):
            # 提取匹配值周围的上下文（前后各 30 字符）
            start = max(0, match.start() - 30)
            end = min(len(clause_text), match.end() + 30)
            context = clause_text[start:end].strip()
            terms.append(FinancialTerm(
                term_type=term_type,
                value=match.group(0).strip(),
                context=context,
            ))

    return ExtractFinancialTermsOutput(
        clause_id=input_data.clause_id,
        terms=terms,
        total_terms=len(terms),
    )
```

## 4. builder.py 集成

### 4.1 `_GENERIC_SKILLS` 扩展

在 SPEC-12 建立的 `_GENERIC_SKILLS` 列表中追加 4 个新 Skill：

```python
_GENERIC_SKILLS: list[SkillRegistration] = [
    # get_clause_context（SPEC-12 已有）
    SkillRegistration(
        skill_id="get_clause_context",
        ...
    ),
    # --- 以下为 SPEC-13 新增 ---
    SkillRegistration(
        skill_id="resolve_definition",
        name="定义解析",
        description="查找条款中引用的术语定义",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.resolve_definition.resolve_definition",
        domain="*",
        category="extraction",
    ),
    SkillRegistration(
        skill_id="compare_with_baseline",
        name="基线文本对比",
        description="将条款文本与标准模板进行对比",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.compare_with_baseline.compare_with_baseline",
        domain="*",
        category="comparison",
    ),
    SkillRegistration(
        skill_id="cross_reference_check",
        name="交叉引用检查",
        description="检查条款中的交叉引用是否有效",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.cross_reference_check.cross_reference_check",
        domain="*",
        category="validation",
    ),
    SkillRegistration(
        skill_id="extract_financial_terms",
        name="财务条款提取",
        description="从条款中提取金额、百分比、期限等数值",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.extract_financial_terms.extract_financial_terms",
        domain="*",
        category="extraction",
    ),
]
```

### 4.2 `_build_skill_input` 扩展

为每个新 Skill 添加输入构造分支：

```python
def _build_skill_input(
    skill_id: str,
    clause_id: str,
    primary_structure: Any,
    state: ReviewGraphState,
) -> BaseModel | None:
    if skill_id == "get_clause_context":
        try:
            return ClauseContextInput(
                clause_id=clause_id,
                document_structure=primary_structure,
            )
        except Exception:
            return None

    if skill_id == "resolve_definition":
        from ..skills.local.resolve_definition import ResolveDefinitionInput
        return ResolveDefinitionInput(
            clause_id=clause_id,
            document_structure=primary_structure,
        )

    if skill_id == "compare_with_baseline":
        from ..skills.local.compare_with_baseline import CompareWithBaselineInput
        from ..plugins.registry import get_baseline_text
        domain_id = state.get("domain_id", "")
        baseline = get_baseline_text(domain_id, clause_id) or ""
        return CompareWithBaselineInput(
            clause_id=clause_id,
            document_structure=primary_structure,
            baseline_text=baseline,
        )

    if skill_id == "cross_reference_check":
        from ..skills.local.cross_reference_check import CrossReferenceCheckInput
        return CrossReferenceCheckInput(
            clause_id=clause_id,
            document_structure=primary_structure,
        )

    if skill_id == "extract_financial_terms":
        from ..skills.local.extract_financial_terms import ExtractFinancialTermsInput
        return ExtractFinancialTermsInput(
            clause_id=clause_id,
            document_structure=primary_structure,
        )

    # 未识别的 Skill 使用通用输入
    return GenericSkillInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        state_snapshot={
            "our_party": state.get("our_party", ""),
            "language": state.get("language", "en"),
            "domain_id": state.get("domain_id", ""),
        },
    )
```

## 5. 测试

### 5.1 测试文件：`tests/test_generic_skills.py`

```python
import pytest

pytest.importorskip("langgraph")


class TestResolveDefinition:
    @pytest.mark.asyncio
    async def test_finds_definitions_from_structure(self):
        from contract_review.skills.local.resolve_definition import (
            ResolveDefinitionInput,
            resolve_definition,
        )

        structure = {
            "definitions": {
                "Employer": "The party named as employer in the Contract Data.",
                "Contractor": "The party named as contractor in the Contract Data.",
            },
            "clauses": [
                {"clause_id": "1.1", "text": 'The "Employer" shall provide access.', "children": []},
            ],
        }
        result = await resolve_definition(
            ResolveDefinitionInput(clause_id="1.1", document_structure=structure)
        )
        assert result.definitions_found
        assert "Employer" in result.definitions_found

    @pytest.mark.asyncio
    async def test_specific_terms_lookup(self):
        from contract_review.skills.local.resolve_definition import (
            ResolveDefinitionInput,
            resolve_definition,
        )

        structure = {
            "definitions": {"Force Majeure": "An exceptional event."},
            "clauses": [],
        }
        result = await resolve_definition(
            ResolveDefinitionInput(
                clause_id="19.1",
                document_structure=structure,
                terms=["Force Majeure", "Unknown Term"],
            )
        )
        assert "Force Majeure" in result.definitions_found
        assert "Unknown Term" in result.terms_not_found

    @pytest.mark.asyncio
    async def test_empty_definitions(self):
        from contract_review.skills.local.resolve_definition import (
            ResolveDefinitionInput,
            resolve_definition,
        )

        result = await resolve_definition(
            ResolveDefinitionInput(clause_id="1.1", document_structure={"definitions": {}, "clauses": []})
        )
        assert result.definitions_found == {}


class TestCompareWithBaseline:
    @pytest.mark.asyncio
    async def test_identical_text(self):
        from contract_review.skills.local.compare_with_baseline import (
            CompareWithBaselineInput,
            compare_with_baseline,
        )

        structure = {
            "clauses": [{"clause_id": "14.1", "text": "The Contract Price is fixed.", "children": []}],
        }
        result = await compare_with_baseline(
            CompareWithBaselineInput(
                clause_id="14.1",
                document_structure=structure,
                baseline_text="The Contract Price is fixed.",
            )
        )
        assert result.has_baseline is True
        assert result.is_identical is True

    @pytest.mark.asyncio
    async def test_different_text(self):
        from contract_review.skills.local.compare_with_baseline import (
            CompareWithBaselineInput,
            compare_with_baseline,
        )

        structure = {
            "clauses": [{"clause_id": "14.1", "text": "The Contract Price is adjustable.", "children": []}],
        }
        result = await compare_with_baseline(
            CompareWithBaselineInput(
                clause_id="14.1",
                document_structure=structure,
                baseline_text="The Contract Price is fixed.",
            )
        )
        assert result.has_baseline is True
        assert result.is_identical is False
        assert result.differences_summary

    @pytest.mark.asyncio
    async def test_no_baseline(self):
        from contract_review.skills.local.compare_with_baseline import (
            CompareWithBaselineInput,
            compare_with_baseline,
        )

        result = await compare_with_baseline(
            CompareWithBaselineInput(clause_id="14.1", document_structure={"clauses": []})
        )
        assert result.has_baseline is False


class TestCrossReferenceCheck:
    @pytest.mark.asyncio
    async def test_finds_valid_and_invalid_refs(self):
        from contract_review.skills.local.cross_reference_check import (
            CrossReferenceCheckInput,
            cross_reference_check,
        )

        structure = {
            "clauses": [],
            "cross_references": [
                {"source_clause_id": "4.1", "target_clause_id": "1.1", "reference_text": "Clause 1.1", "is_valid": True},
                {"source_clause_id": "4.1", "target_clause_id": "99.9", "reference_text": "Clause 99.9", "is_valid": False},
                {"source_clause_id": "8.2", "target_clause_id": "14.1", "reference_text": "Clause 14.1", "is_valid": True},
            ],
        }
        result = await cross_reference_check(
            CrossReferenceCheckInput(clause_id="4.1", document_structure=structure)
        )
        assert result.total_references == 2  # 只包含 source=4.1 的
        assert result.total_invalid == 1
        assert result.invalid_references[0]["target_clause_id"] == "99.9"

    @pytest.mark.asyncio
    async def test_no_references(self):
        from contract_review.skills.local.cross_reference_check import (
            CrossReferenceCheckInput,
            cross_reference_check,
        )

        result = await cross_reference_check(
            CrossReferenceCheckInput(clause_id="1.1", document_structure={"clauses": [], "cross_references": []})
        )
        assert result.total_references == 0


class TestExtractFinancialTerms:
    @pytest.mark.asyncio
    async def test_extracts_percentage_and_amount(self):
        from contract_review.skills.local.extract_financial_terms import (
            ExtractFinancialTermsInput,
            extract_financial_terms,
        )

        structure = {
            "clauses": [
                {
                    "clause_id": "14.2",
                    "text": "预付款为合同总价的30%，金额为USD 1,000,000，应在开工后14天内支付。",
                    "children": [],
                }
            ],
        }
        result = await extract_financial_terms(
            ExtractFinancialTermsInput(clause_id="14.2", document_structure=structure)
        )
        assert result.total_terms >= 2
        types = {t.term_type for t in result.terms}
        assert "percentage" in types
        # amount 或 duration 至少有一个
        assert types & {"amount", "duration"}

    @pytest.mark.asyncio
    async def test_no_financial_terms(self):
        from contract_review.skills.local.extract_financial_terms import (
            ExtractFinancialTermsInput,
            extract_financial_terms,
        )

        structure = {
            "clauses": [{"clause_id": "1.1", "text": "Definitions and Interpretation.", "children": []}],
        }
        result = await extract_financial_terms(
            ExtractFinancialTermsInput(clause_id="1.1", document_structure=structure)
        )
        assert result.total_terms == 0
```

## 6. 约束

1. 所有 Skill 必须是纯函数（async），不依赖外部状态或 LLM
2. 所有 Skill 的 `_ensure_dict` 和 `_get_clause_text` 辅助函数可以提取为共享模块 `skills/local/_utils.py`，避免重复代码
3. 不修改已有测试用例
4. 不修改前端代码
5. 不修改 `redline_generator.py`
6. 运行 `PYTHONPATH=backend/src python -m pytest tests/ -x -q` 确认全部通过

## 7. 验收标准

1. 4 个 Skill 文件均可独立导入和执行
2. 每个 Skill 的单元测试通过
3. `_GENERIC_SKILLS` 中包含 5 个 Skill（含 `get_clause_context`）
4. `_build_skill_input` 能为每个 Skill 构造正确的输入
5. 所有测试通过（包括 SPEC-12 的测试）
