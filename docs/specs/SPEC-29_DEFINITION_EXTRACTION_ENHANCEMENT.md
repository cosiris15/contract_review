# SPEC-29：Gen3 定义术语识别与提取增强（LLM + 规则混合方案）

| 字段 | 值 |
|------|-----|
| 状态 | Draft |
| 优先级 | P1 |
| 前置依赖 | SPEC-28（smart_parser 基础设施） |
| 影响范围 | structure_parser.py, models.py, resolve_definition skill, api_gen3.py |

---

## 0. 背景与动机

### 0.1 现状分析

当前定义术语提取完全依赖正则匹配，存在以下局限：

**`structure_parser.py:117-136` — `_extract_definitions()` 现有实现：**

```python
def _extract_definitions(self, clause_tree, section_id):
    definitions = {}
    target_node = self._find_clause(clause_tree, section_id)
    if not target_node:
        return definitions
    full_text = self._collect_text(target_node)
    patterns = [
        r'"([^"]+)"\s+means?\s+(.+?)(?=\n\s*"|$)',
        r'"([^"]+)"\s+shall\s+mean\s+(.+?)(?=\n\s*"|$)',
        r'"([^"]+)"\s*(?:指|是指|系指)\s*(.+?)(?=\n\s*"|$)',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, full_text, re.DOTALL):
            term = match.group(1).strip()
            definition = match.group(2).strip()
            if term and definition:
                definitions[term] = definition
    return definitions
```

**问题清单：**

| # | 问题 | 影响 |
|---|------|------|
| 1 | 仅 3 条正则，覆盖 `"term" means`、`"term" shall mean`、`"term" 指/是指/系指` | 大量中文合同使用 `：`、`，即`、`（以下简称"X"）` 等格式，完全漏提 |
| 2 | 仅扫描 `definitions_section_id` 指定的单一条款 | 散落在正文中的行内定义（如"甲方（以下简称'出租方'）"）无法捕获 |
| 3 | 存储为 `Dict[str, str]`，无元数据 | 无法区分提取来源（regex vs LLM）、无置信度、无法做质量回溯 |
| 4 | `resolve_definition` skill 做简单 dict lookup | 无法处理同义词、缩写、模糊匹配 |
| 5 | 无 LLM 参与 | 对非标准格式的定义条款束手无策 |

### 0.2 目标

构建 **"规则保底 + LLM 增强 + 可验证回退"** 的混合定义提取管线：

1. **扩展正则库**：覆盖中英文常见定义格式（目标：从 3 条 → 12+ 条）
2. **LLM 结构化提取**：对正则未覆盖的文本，调用 LLM 以 JSON 格式提取定义
3. **置信度与来源追踪**：每条定义记录 `source`（regex/llm）和 `confidence`
4. **行内定义扫描**：不限于 definitions section，扫描全文捕获散落定义
5. **向后兼容**：`resolve_definition` skill 和 `DocumentStructure.definitions` 接口不破坏

---

## 1. 数据模型设计

### 1.1 新增 `DefinitionEntry` 模型

**文件**: `backend/src/contract_review/models.py`

```python
class DefinitionSource(str, Enum):
    """定义提取来源。"""
    REGEX = "regex"
    LLM = "llm"
    MANUAL = "manual"


class DefinitionEntry(BaseModel):
    """单条定义术语的结构化表示。"""
    term: str                                    # 术语名称
    definition_text: str                         # 定义内容
    source: DefinitionSource = DefinitionSource.REGEX  # 提取来源
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)  # 置信度
    source_clause_id: Optional[str] = None       # 来源条款 ID
    aliases: List[str] = Field(default_factory=list)  # 同义词/缩写
    category: Optional[str] = None               # 分类：party / date / amount / general
```

### 1.2 `DocumentStructure` 扩展

```python
class DocumentStructure(BaseModel):
    """文档结构化解析结果。"""
    document_id: str
    structure_type: str = "generic_numbered"
    clauses: List[ClauseNode] = Field(default_factory=list)
    definitions: Dict[str, str] = Field(default_factory=dict)          # 保留，向后兼容
    definitions_v2: List[DefinitionEntry] = Field(default_factory=list) # 新增，富元数据
    cross_references: List[CrossReference] = Field(default_factory=list)
    total_clauses: int = 0
    parsed_at: datetime = Field(default_factory=datetime.now)
```

**兼容策略**：
- `definitions`（Dict[str, str]）继续由 `_extract_definitions()` 写入，保持现有 `resolve_definition` skill 不变
- `definitions_v2`（List[DefinitionEntry]）由新管线写入，包含完整元数据
- `resolve_definition` skill 优先查 `definitions_v2`，fallback 到 `definitions`

---

## 2. 正则库扩展

### 2.1 新增模块 `definition_patterns.py`

**文件**: `backend/src/contract_review/definition_patterns.py`

将正则从硬编码 3 条扩展为分类管理的模式库：

```python
"""Definition extraction regex patterns — categorized and extensible."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class DefinitionPattern:
    """A single definition extraction pattern."""
    name: str                    # 模式名称，用于日志
    regex: str                   # 正则表达式（MULTILINE + DOTALL）
    term_group: int = 1          # 术语在哪个捕获组
    definition_group: int = 2    # 定义文本在哪个捕获组
    language: str = "any"        # zh / en / any
    category: Optional[str] = None  # party / general / ...


# ==================== 英文模式 ====================

EN_PATTERNS: List[DefinitionPattern] = [
    DefinitionPattern(
        name="en_means",
        regex=r'"([^"]+)"\s+means?\s+(.+?)(?=\n\s*"|$)',
        language="en",
    ),
    DefinitionPattern(
        name="en_shall_mean",
        regex=r'"([^"]+)"\s+shall\s+mean\s+(.+?)(?=\n\s*"|$)',
        language="en",
    ),
    DefinitionPattern(
        name="en_refers_to",
        regex=r'"([^"]+)"\s+refers?\s+to\s+(.+?)(?=\n\s*"|$)',
        language="en",
    ),
    DefinitionPattern(
        name="en_is_defined_as",
        regex=r'"([^"]+)"\s+is\s+defined\s+as\s+(.+?)(?=\n\s*"|$)',
        language="en",
    ),
    DefinitionPattern(
        name="en_hereinafter",
        regex=r'"([^"]+)"\s*\(hereinafter\s+(?:referred\s+to\s+as\s+)?"([^"]+)"\)',
        term_group=1,
        definition_group=2,
        language="en",
    ),
]

# ==================== 中文模式 ====================

ZH_PATTERNS: List[DefinitionPattern] = [
    DefinitionPattern(
        name="zh_zhi",
        regex=r'["\u201c]([^\u201d"]+)["\u201d]\s*(?:指|是指|系指)\s*(.+?)(?=\n\s*["\u201c]|$)',
        language="zh",
    ),
    DefinitionPattern(
        name="zh_colon",
        regex=r'["\u201c]([^\u201d"]+)["\u201d]\s*[：:]\s*(.+?)(?=\n\s*["\u201c]|$)',
        language="zh",
    ),
    DefinitionPattern(
        name="zh_ji",
        regex=r'["\u201c]([^\u201d"]+)["\u201d]\s*[，,]\s*即\s*(.+?)(?=\n\s*["\u201c]|$)',
        language="zh",
    ),
    DefinitionPattern(
        name="zh_inline_party",
        regex=r'(.{2,20})\s*[（(]\s*以下简称\s*["\u201c]([^\u201d"]+)["\u201d]\s*[)）]',
        term_group=2,
        definition_group=1,
        language="zh",
        category="party",
    ),
    DefinitionPattern(
        name="zh_inline_abbreviation",
        regex=r'(.{2,40})\s*[（(]\s*(?:以下称|下称|简称)\s*["\u201c]?([^\u201d"）)]+)["\u201d]?\s*[)）]',
        term_group=2,
        definition_group=1,
        language="zh",
    ),
    DefinitionPattern(
        name="zh_di_tiao",
        regex=r'第[一二三四五六七八九十百零\d]+[条章节]\s+["\u201c]([^\u201d"]+)["\u201d]\s*(?:指|是指|系指|：)\s*(.+?)(?=\n|$)',
        language="zh",
    ),
]

ALL_PATTERNS: List[DefinitionPattern] = EN_PATTERNS + ZH_PATTERNS


def extract_by_patterns(
    text: str,
    patterns: List[DefinitionPattern] | None = None,
) -> List[Tuple[str, str, str]]:
    """Extract (term, definition_text, pattern_name) tuples from text.

    Returns deduplicated results; first match wins for duplicate terms.
    """
    if patterns is None:
        patterns = ALL_PATTERNS

    seen_terms: set[str] = set()
    results: List[Tuple[str, str, str]] = []

    for pat in patterns:
        try:
            compiled = re.compile(pat.regex, re.MULTILINE | re.DOTALL)
        except re.error:
            continue
        for match in compiled.finditer(text):
            term = match.group(pat.term_group).strip()
            definition = match.group(pat.definition_group).strip()
            if not term or not definition:
                continue
            norm_key = term.lower().strip('""\u201c\u201d\'')
            if norm_key in seen_terms:
                continue
            seen_terms.add(norm_key)
            results.append((term, definition, pat.name))

    return results
```

### 2.2 模式数量对比

| 维度 | 现有 | SPEC-29 |
|------|------|---------|
| 英文模式 | 2（means, shall mean） | 5（+ refers to, defined as, hereinafter） |
| 中文模式 | 1（指/是指/系指） | 6（+ 冒号、即、以下简称、下称、第X条） |
| 行内定义 | 0 | 2（zh_inline_party, zh_inline_abbreviation） |
| 总计 | 3 | 11 |

---

## 3. LLM 结构化提取

### 3.1 新增模块 `definition_extractor.py`

**文件**: `backend/src/contract_review/definition_extractor.py`

```python
"""LLM-assisted definition extraction with regex fallback."""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from .definition_patterns import ALL_PATTERNS, extract_by_patterns
from .models import DefinitionEntry, DefinitionSource, DocumentParserConfig
from .smart_parser import _parse_llm_response, _validate_regex

logger = logging.getLogger(__name__)

# LLM 单次提取的文本上限（字符）
EXTRACT_CHAR_LIMIT = 8000

# 最大 LLM 提取条目数（防止幻觉膨胀）
MAX_LLM_ENTRIES = 60

DEFINITION_EXTRACT_SYSTEM = """你是一个合同文档定义术语提取专家。你的任务是从合同文本中识别并提取所有定义术语及其释义。

要求：
1. 识别所有被明确定义的术语，包括但不限于：
   - 引号包裹的术语定义（如 "甲方" 指...、"Employer" means...）
   - 括号内的简称定义（如 XX公司（以下简称"甲方"））
   - 冒号后的定义（如 "合同价格"：指...）
   - 条款标题中的定义
2. 对每个术语提取：
   - term: 术语名称（不含引号）
   - definition_text: 完整的定义文本
   - aliases: 同义词或缩写列表（如有）
   - category: 分类（party=当事方 / date=日期 / amount=金额 / general=一般术语）
3. 不要编造不存在的定义
4. 如果文本中没有定义术语，返回空数组

你必须严格按以下 JSON 格式返回，不要包含任何其他文字：
{
  "definitions": [
    {
      "term": "术语名称",
      "definition_text": "定义内容",
      "aliases": ["别名1"],
      "category": "general"
    }
  ],
  "total_found": 数量,
  "confidence": 0.0-1.0
}"""

DEFINITION_EXTRACT_USER = """请从以下合同文本中提取所有定义术语：

<<<TEXT_START>>>
{text}
<<<TEXT_END>>>"""
```

### 3.2 核心提取函数

```python
async def extract_definitions_hybrid(
    llm_client,
    document_text: str,
    definitions_section_text: str = "",
    parser_config: Optional[DocumentParserConfig] = None,
) -> List[DefinitionEntry]:
    """混合提取管线：regex 先行 → LLM 补充 → 合并去重。

    Phase A: 对 definitions_section_text 执行扩展正则提取
    Phase B: 对全文执行行内定义正则扫描
    Phase C: 对 definitions_section_text 调用 LLM 结构化提取
    Phase D: 合并去重，regex 结果 confidence=1.0，LLM 结果保留原始 confidence
    Phase E: 验证与过滤（去除过短术语、过长定义等噪声）
    """
    entries: List[DefinitionEntry] = []
    seen_terms: set[str] = set()

    def _norm(t: str) -> str:
        return t.lower().strip('""\u201c\u201d\'')

    # ── Phase A: 定义条款正则提取 ──
    if definitions_section_text:
        regex_results = extract_by_patterns(definitions_section_text)
        for term, defn, pat_name in regex_results:
            nk = _norm(term)
            if nk in seen_terms:
                continue
            seen_terms.add(nk)
            entries.append(DefinitionEntry(
                term=term,
                definition_text=defn,
                source=DefinitionSource.REGEX,
                confidence=1.0,
                source_clause_id=_get_def_section_id(parser_config),
            ))

    # ── Phase B: 全文行内定义扫描 ──
    inline_patterns = [p for p in ALL_PATTERNS if p.category == "party" or "inline" in p.name]
    if document_text:
        inline_results = extract_by_patterns(document_text, inline_patterns)
        for term, defn, pat_name in inline_results:
            nk = _norm(term)
            if nk in seen_terms:
                continue
            seen_terms.add(nk)
            entries.append(DefinitionEntry(
                term=term,
                definition_text=defn,
                source=DefinitionSource.REGEX,
                confidence=0.9,
                category="party" if "party" in pat_name else None,
            ))

    # ── Phase C: LLM 结构化提取 ──
    llm_entries = await _llm_extract(llm_client, definitions_section_text or document_text[:EXTRACT_CHAR_LIMIT])
    for entry in llm_entries:
        nk = _norm(entry.term)
        if nk in seen_terms:
            # LLM 发现的术语已被 regex 捕获 → 跳过（regex 优先）
            continue
        seen_terms.add(nk)
        entries.append(entry)

    # ── Phase D+E: 验证与过滤 ──
    entries = _validate_entries(entries)

    logger.info(
        "定义提取完成: regex=%d, llm=%d, total=%d",
        sum(1 for e in entries if e.source == DefinitionSource.REGEX),
        sum(1 for e in entries if e.source == DefinitionSource.LLM),
        len(entries),
    )
    return entries


async def _llm_extract(llm_client, text: str) -> List[DefinitionEntry]:
    """调用 LLM 提取定义，返回 DefinitionEntry 列表。失败时返回空列表。"""
    if not llm_client or not text or not text.strip():
        return []

    try:
        response = await llm_client.chat(
            messages=[
                {"role": "system", "content": DEFINITION_EXTRACT_SYSTEM},
                {"role": "user", "content": DEFINITION_EXTRACT_USER.format(text=text[:EXTRACT_CHAR_LIMIT])},
            ],
            temperature=0.0,
            max_output_tokens=2000,
        )

        payload = _parse_llm_response(response)
        if payload is None:
            logger.warning("LLM 定义提取结果无法解析")
            return []

        raw_defs = payload.get("definitions", [])
        if not isinstance(raw_defs, list):
            return []

        confidence = float(payload.get("confidence", 0.7) or 0.7)
        entries: List[DefinitionEntry] = []

        for item in raw_defs[:MAX_LLM_ENTRIES]:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term", "") or "").strip()
            defn = str(item.get("definition_text", "") or "").strip()
            if not term or not defn:
                continue
            entries.append(DefinitionEntry(
                term=term,
                definition_text=defn,
                source=DefinitionSource.LLM,
                confidence=confidence,
                aliases=item.get("aliases", []) if isinstance(item.get("aliases"), list) else [],
                category=item.get("category") if item.get("category") in ("party", "date", "amount", "general") else None,
            ))

        return entries

    except Exception:
        logger.exception("LLM 定义提取异常")
        return []


def _get_def_section_id(config: Optional[DocumentParserConfig]) -> Optional[str]:
    if config and hasattr(config, "definitions_section_id"):
        return config.definitions_section_id
    return None


def _validate_entries(entries: List[DefinitionEntry]) -> List[DefinitionEntry]:
    """过滤噪声条目。"""
    valid: List[DefinitionEntry] = []
    for entry in entries:
        # 术语过短（单字符）或过长（超过 50 字符）→ 可疑
        if len(entry.term) < 2 or len(entry.term) > 50:
            continue
        # 定义文本过短（少于 4 字符）→ 可疑
        if len(entry.definition_text) < 4:
            continue
        # 定义文本过长 → 截断到 2000 字符
        if len(entry.definition_text) > 2000:
            entry.definition_text = entry.definition_text[:2000] + "..."
        valid.append(entry)
    return valid


def build_definitions_dict(entries: List[DefinitionEntry]) -> Dict[str, str]:
    """从 DefinitionEntry 列表构建向后兼容的 Dict[str, str]。

    用于填充 DocumentStructure.definitions 字段。
    """
    result: Dict[str, str] = {}
    for entry in entries:
        if entry.term not in result:
            result[entry.term] = entry.definition_text
    return result
```

---

## 4. 集成点改动

### 4.1 `structure_parser.py` — 替换 `_extract_definitions()`

**文件**: `backend/src/contract_review/structure_parser.py`

现有 `_extract_definitions()` 方法（第 117-136 行）保留为 `_extract_definitions_legacy()` 作为纯同步 fallback。新增异步入口：

```python
from .definition_patterns import extract_by_patterns
from .definition_extractor import build_definitions_dict

def _extract_definitions_legacy(self, clause_tree, section_id):
    """原有正则提取（保留为同步 fallback）。"""
    # ... 原有代码不变 ...

def _extract_definitions_v2(self, clause_tree, section_id):
    """使用扩展正则库的同步提取（不调用 LLM）。

    在 parse() 同步路径中使用，替代原有 3 条正则。
    """
    definitions = {}
    target_node = self._find_clause(clause_tree, section_id)
    if not target_node:
        return definitions
    full_text = self._collect_text(target_node)
    results = extract_by_patterns(full_text)
    for term, defn, _pat_name in results:
        if term not in definitions:
            definitions[term] = defn
    return definitions
```

**改动说明**：
- `parse()` 方法中将 `self._extract_definitions(clause_tree, section_id)` 替换为 `self._extract_definitions_v2(clause_tree, section_id)`
- 这是纯同步改动，不涉及 LLM 调用，仅扩展正则覆盖面
- LLM 增强在 `api_gen3.py` 的异步上传管线中执行（见 4.2）

### 4.2 `api_gen3.py` — 上传管线集成 LLM 定义提取

**文件**: `backend/src/contract_review/api_gen3.py`

在现有 SPEC-28 的 smart_parser 调用之后（约第 364 行），追加定义提取增强：

```python
# ── SPEC-28: LLM 模式检测（已有） ──
# parser_config = await detect_clause_pattern(...)

# ── SPEC-29: LLM 定义提取增强 ──
try:
    from .definition_extractor import extract_definitions_hybrid, build_definitions_dict

    # 获取定义条款文本
    def_section_id = None
    if parser_config and hasattr(parser_config, "definitions_section_id"):
        def_section_id = parser_config.definitions_section_id

    def_section_text = ""
    if def_section_id and structure:
        # 从已解析的 structure 中提取定义条款全文
        def_node = _find_clause_in_structure(structure, def_section_id)
        if def_node:
            def_section_text = _collect_node_text(def_node)

    definitions_v2 = await extract_definitions_hybrid(
        llm_client=llm_client,
        document_text=loaded.text,
        definitions_section_text=def_section_text,
        parser_config=parser_config,
    )

    # 回写到 structure
    if structure and definitions_v2:
        structure.definitions_v2 = definitions_v2
        # 同时更新向后兼容的 definitions dict
        enhanced_dict = build_definitions_dict(definitions_v2)
        structure.definitions.update(enhanced_dict)

except Exception:
    logger.warning("SPEC-29 定义提取增强跳过", exc_info=True)
```

### 4.3 `resolve_definition` skill — 优先查 `definitions_v2`

**文件**: `backend/src/contract_review/skills/local/resolve_definition.py`

修改 `resolve_definition()` 函数，优先从 `definitions_v2` 查找：

```python
async def resolve_definition(input_data: ResolveDefinitionInput) -> ResolveDefinitionOutput:
    structure = ensure_dict(input_data.document_structure)

    # 优先使用 definitions_v2（SPEC-29 富元数据）
    v2_entries = structure.get("definitions_v2", [])
    definitions_v2_map: Dict[str, str] = {}
    if isinstance(v2_entries, list):
        for entry in v2_entries:
            if isinstance(entry, dict):
                term = str(entry.get("term", "") or "")
                defn = str(entry.get("definition_text", "") or "")
                if term and defn:
                    definitions_v2_map[term] = defn
                # 也索引 aliases
                for alias in (entry.get("aliases") or []):
                    if alias and defn:
                        definitions_v2_map[str(alias)] = defn

    # fallback 到 definitions（向后兼容）
    raw_definitions = structure.get("definitions", {})
    definitions = raw_definitions if isinstance(raw_definitions, dict) else {}

    # 合并：v2 优先
    merged = {**definitions, **definitions_v2_map}

    terms = input_data.terms
    if not terms:
        terms = _extract_quoted_terms(get_clause_text(structure, input_data.clause_id))

    found: Dict[str, str] = {}
    not_found: List[str] = []
    for term in terms:
        matched = _find_term(term, merged)
        if matched is not None:
            found[term] = matched
        else:
            not_found.append(term)

    return ResolveDefinitionOutput(
        clause_id=input_data.clause_id,
        definitions_found=found,
        terms_not_found=not_found,
    )
```

---

## 5. 回退与容错策略

### 5.1 分层回退

```
extract_definitions_hybrid()
├── Phase A: 扩展正则（definitions section）  ← 始终执行，0 成本
├── Phase B: 行内正则（全文）                  ← 始终执行，0 成本
├── Phase C: LLM 提取                         ← 可能失败
│   ├── 成功 → 合并去重
│   ├── JSON 解析失败 → 仅保留 regex 结果
│   ├── API 超时/异常 → 仅保留 regex 结果
│   └── 返回空 → 仅保留 regex 结果
└── Phase D+E: 验证过滤                        ← 始终执行
```

### 5.2 关键保证

| 场景 | 行为 | 结果 |
|------|------|------|
| LLM 不可用 | Phase C 返回空列表 | 仅 regex 结果，不低于现有水平 |
| LLM 返回垃圾 JSON | `_parse_llm_response` 返回 None | 同上 |
| LLM 幻觉（编造定义） | `_validate_entries` 过滤 + regex 优先策略 | 幻觉条目可能混入，但 confidence < 1.0 |
| 无 definitions section | Phase A 跳过，Phase B+C 仍执行 | 行内定义 + LLM 全文提取 |
| 空文档 | 所有 Phase 跳过 | 返回空列表 |
| `definitions_v2` 字段缺失 | `resolve_definition` fallback 到 `definitions` | 完全向后兼容 |

### 5.3 LLM 幻觉防护

1. **MAX_LLM_ENTRIES = 60**：限制单次 LLM 返回的最大条目数
2. **术语长度过滤**：`len(term) < 2` 或 `> 50` 的条目被丢弃
3. **定义文本过滤**：`len(definition_text) < 4` 的条目被丢弃
4. **Regex 优先**：同一术语如果 regex 已捕获，LLM 结果被跳过
5. **Confidence 标记**：LLM 结果的 `source=DefinitionSource.LLM`，下游可按需过滤

---

## 6. 性能与成本控制

### 6.1 LLM 调用预算

| 参数 | 值 | 说明 |
|------|-----|------|
| `EXTRACT_CHAR_LIMIT` | 8000 | 发送给 LLM 的最大文本长度 |
| `max_output_tokens` | 2000 | LLM 输出上限 |
| `temperature` | 0.0 | 确定性输出 |
| 调用次数 | 1 次/文档 | 仅在上传时调用一次 |

### 6.2 成本估算

以 DeepSeek API 为例：
- 输入：~8000 字符 ≈ 4000 tokens
- 输出：~2000 tokens（60 条定义的 JSON）
- 单次成本：约 ¥0.01-0.02
- 与 SPEC-28 的 smart_parser 调用叠加，总上传管线 LLM 成本 ≈ ¥0.03/文档

### 6.3 延迟影响

- 正则提取：< 50ms（纯 CPU）
- LLM 提取：1-3s（网络 I/O）
- 总增量：~2s（在上传管线中，用户可接受）

---

## 7. `resolve_definition` skill 增强

### 7.1 别名匹配

当前 `_find_term()` 仅做精确匹配 + 大小写归一化。SPEC-29 后，`definitions_v2` 中的 `aliases` 字段已在 4.3 节中被展开到查找 map，无需修改 `_find_term()` 逻辑。

### 7.2 输出增强（可选，Phase 2）

未来可扩展 `ResolveDefinitionOutput` 添加：

```python
class ResolveDefinitionOutput(BaseModel):
    clause_id: str
    definitions_found: Dict[str, str] = Field(default_factory=dict)
    terms_not_found: List[str] = Field(default_factory=list)
    # Phase 2 扩展
    definitions_detail: List[DefinitionEntry] = Field(default_factory=list)  # 富元数据
```

MVP 阶段不改动 `ResolveDefinitionOutput` 的 schema，仅改动内部查找逻辑。

---

## 8. 测试计划

### 8.1 新增测试文件 `tests/test_definition_extraction.py`

```python
"""Tests for SPEC-29 definition extraction enhancement."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from contract_review.definition_patterns import (
    ALL_PATTERNS,
    EN_PATTERNS,
    ZH_PATTERNS,
    extract_by_patterns,
)
from contract_review.definition_extractor import (
    EXTRACT_CHAR_LIMIT,
    MAX_LLM_ENTRIES,
    _validate_entries,
    build_definitions_dict,
    extract_definitions_hybrid,
)
from contract_review.models import DefinitionEntry, DefinitionSource


# ==================== definition_patterns 测试 ====================

class TestEnPatterns:
    def test_means(self):
        text = '"Employer" means the party named in the Contract.\n"Engineer" means the person appointed.'
        results = extract_by_patterns(text, EN_PATTERNS)
        assert len(results) == 2
        assert results[0][0] == "Employer"

    def test_shall_mean(self):
        text = '"Contract Price" shall mean the total amount payable.'
        results = extract_by_patterns(text, EN_PATTERNS)
        assert len(results) == 1
        assert results[0][0] == "Contract Price"

    def test_refers_to(self):
        text = '"Completion Date" refers to the date specified in the Appendix.'
        results = extract_by_patterns(text, EN_PATTERNS)
        assert len(results) == 1
        assert results[0][0] == "Completion Date"

    def test_defined_as(self):
        text = '"Force Majeure" is defined as any event beyond reasonable control.'
        results = extract_by_patterns(text, EN_PATTERNS)
        assert len(results) == 1
        assert results[0][0] == "Force Majeure"

    def test_dedup(self):
        text = '"Term" means X.\n"Term" shall mean Y.'
        results = extract_by_patterns(text, EN_PATTERNS)
        assert len(results) == 1  # first match wins


class TestZhPatterns:
    def test_zhi(self):
        text = '"甲方"指本合同中的委托方。\n"乙方"是指本合同中的受托方。'
        results = extract_by_patterns(text, ZH_PATTERNS)
        assert len(results) == 2

    def test_colon(self):
        text = '\u201c合同价格\u201d：指双方约定的总价款。'
        results = extract_by_patterns(text, ZH_PATTERNS)
        assert len(results) >= 1
        assert any(r[0] == "合同价格" for r in results)

    def test_ji(self):
        text = '\u201c竣工日期\u201d，即工程实际完工的日期。'
        results = extract_by_patterns(text, ZH_PATTERNS)
        assert len(results) >= 1

    def test_inline_party(self):
        text = '北京某某科技有限公司（以下简称"甲方"）与上海某某有限公司（以下简称"乙方"）'
        results = extract_by_patterns(text, ZH_PATTERNS)
        terms = [r[0] for r in results]
        assert "甲方" in terms
        assert "乙方" in terms

    def test_inline_abbreviation(self):
        text = '中华人民共和国住房和城乡建设部（以下称"住建部"）'
        results = extract_by_patterns(text, ZH_PATTERNS)
        terms = [r[0] for r in results]
        assert "住建部" in terms


class TestExtractByPatterns:
    def test_empty_text(self):
        assert extract_by_patterns("") == []

    def test_no_matches(self):
        assert extract_by_patterns("这是一段普通文本，没有定义。") == []

    def test_mixed_languages(self):
        text = '"Employer" means the owner.\n"甲方"指委托方。'
        results = extract_by_patterns(text)
        assert len(results) == 2


# ==================== definition_extractor 测试 ====================

class TestValidateEntries:
    def test_filters_short_term(self):
        entries = [DefinitionEntry(term="X", definition_text="something valid")]
        assert _validate_entries(entries) == []

    def test_filters_long_term(self):
        entries = [DefinitionEntry(term="A" * 51, definition_text="something valid")]
        assert _validate_entries(entries) == []

    def test_filters_short_definition(self):
        entries = [DefinitionEntry(term="ValidTerm", definition_text="abc")]
        assert _validate_entries(entries) == []

    def test_truncates_long_definition(self):
        entries = [DefinitionEntry(term="ValidTerm", definition_text="X" * 2500)]
        result = _validate_entries(entries)
        assert len(result) == 1
        assert result[0].definition_text.endswith("...")
        assert len(result[0].definition_text) == 2003  # 2000 + "..."

    def test_passes_valid_entry(self):
        entries = [DefinitionEntry(term="甲方", definition_text="本合同中的委托方")]
        result = _validate_entries(entries)
        assert len(result) == 1


class TestBuildDefinitionsDict:
    def test_basic(self):
        entries = [
            DefinitionEntry(term="甲方", definition_text="委托方"),
            DefinitionEntry(term="乙方", definition_text="受托方"),
        ]
        result = build_definitions_dict(entries)
        assert result == {"甲方": "委托方", "乙方": "受托方"}

    def test_dedup_first_wins(self):
        entries = [
            DefinitionEntry(term="甲方", definition_text="第一个定义"),
            DefinitionEntry(term="甲方", definition_text="第二个定义"),
        ]
        result = build_definitions_dict(entries)
        assert result["甲方"] == "第一个定义"


class TestExtractDefinitionsHybrid:
    @pytest.mark.asyncio
    async def test_regex_only_no_llm(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({"definitions": [], "confidence": 0.9})
        text = '"Employer" means the owner.\n"Engineer" means the consultant.'
        entries = await extract_definitions_hybrid(mock_llm, text, definitions_section_text=text)
        assert len(entries) >= 2
        assert all(e.source == DefinitionSource.REGEX for e in entries)

    @pytest.mark.asyncio
    async def test_llm_supplements_regex(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({
            "definitions": [
                {"term": "LLM专属术语", "definition_text": "仅LLM能识别的定义", "aliases": [], "category": "general"}
            ],
            "confidence": 0.8,
        })
        text = '"甲方"指委托方。'
        entries = await extract_definitions_hybrid(mock_llm, text, definitions_section_text=text)
        sources = {e.source for e in entries}
        assert DefinitionSource.REGEX in sources
        assert DefinitionSource.LLM in sources

    @pytest.mark.asyncio
    async def test_llm_dedup_regex_wins(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({
            "definitions": [
                {"term": "甲方", "definition_text": "LLM版本的定义", "aliases": [], "category": "party"}
            ],
            "confidence": 0.9,
        })
        text = '"甲方"指委托方。'
        entries = await extract_definitions_hybrid(mock_llm, text, definitions_section_text=text)
        jf = [e for e in entries if e.term == "甲方"]
        assert len(jf) == 1
        assert jf[0].source == DefinitionSource.REGEX  # regex wins

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self):
        mock_llm = AsyncMock()
        mock_llm.chat.side_effect = Exception("API timeout")
        text = '"Employer" means the owner.'
        entries = await extract_definitions_hybrid(mock_llm, text, definitions_section_text=text)
        assert len(entries) >= 1
        assert all(e.source == DefinitionSource.REGEX for e in entries)

    @pytest.mark.asyncio
    async def test_empty_text(self):
        mock_llm = AsyncMock()
        entries = await extract_definitions_hybrid(mock_llm, "")
        assert entries == []

    @pytest.mark.asyncio
    async def test_inline_definitions_from_fulltext(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({"definitions": [], "confidence": 0.9})
        text = '北京某某公司（以下简称"甲方"）与上海某某公司（以下简称"乙方"）签订本合同。'
        entries = await extract_definitions_hybrid(mock_llm, text, definitions_section_text="")
        terms = [e.term for e in entries]
        assert "甲方" in terms or "乙方" in terms

    @pytest.mark.asyncio
    async def test_llm_unparseable_response(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = "这不是JSON"
        text = '"Employer" means the owner.'
        entries = await extract_definitions_hybrid(mock_llm, text, definitions_section_text=text)
        assert len(entries) >= 1
        assert all(e.source == DefinitionSource.REGEX for e in entries)
```

### 8.2 现有测试兼容性

| 测试文件 | 影响 | 说明 |
|----------|------|------|
| `tests/test_smart_parser.py` | 无影响 | SPEC-28 测试，不涉及定义提取 |
| `tests/test_structure_parser.py`（如存在） | 需验证 | `_extract_definitions` 改名后需确认调用点 |
| `tests/test_resolve_definition.py`（如存在） | 需验证 | `resolve_definition` 内部逻辑变更 |
| 全量 `pytest` | 必须通过 | 回归验证 |

---

## 9. 文件清单

| 文件 | 类型 | 预估行数 | 说明 |
|------|------|---------|------|
| `backend/src/contract_review/definition_patterns.py` | 新增 | ~130 | 分类正则模式库 + `extract_by_patterns()` |
| `backend/src/contract_review/definition_extractor.py` | 新增 | ~180 | 混合提取管线 + LLM prompt + 验证过滤 |
| `backend/src/contract_review/models.py` | 修改 | ~15 | 新增 `DefinitionSource`、`DefinitionEntry`、`DocumentStructure.definitions_v2` |
| `backend/src/contract_review/structure_parser.py` | 修改 | ~20 | `_extract_definitions` → `_extract_definitions_v2` 使用扩展正则 |
| `backend/src/contract_review/api_gen3.py` | 修改 | ~25 | 上传管线集成 `extract_definitions_hybrid` |
| `backend/src/contract_review/skills/local/resolve_definition.py` | 修改 | ~20 | 优先查 `definitions_v2` + aliases 展开 |
| `tests/test_definition_extraction.py` | 新增 | ~200 | 全量测试覆盖 |

总计：~590 行，4 个修改文件 + 3 个新增文件

---

## 10. 验收条件

### 10.1 MVP（Phase 1）验收标准

| # | 条件 | 验证方式 |
|---|------|---------|
| AC-1 | `definition_patterns.py` 包含 ≥ 11 条正则模式（5 英文 + 6 中文） | 代码审查 |
| AC-2 | `extract_by_patterns()` 对英文 FIDIC 样本提取 ≥ 10 条定义 | 单元测试 |
| AC-3 | `extract_by_patterns()` 对中文合同样本提取行内当事方定义 | 单元测试 |
| AC-4 | `extract_definitions_hybrid()` 在 LLM 可用时返回 regex + LLM 混合结果 | 单元测试 |
| AC-5 | `extract_definitions_hybrid()` 在 LLM 不可用时仅返回 regex 结果，不抛异常 | 单元测试 |
| AC-6 | 同一术语 regex 和 LLM 都捕获时，regex 结果优先 | 单元测试 |
| AC-7 | `DefinitionEntry` 包含 `term`、`definition_text`、`source`、`confidence`、`aliases`、`category` 字段 | 代码审查 |
| AC-8 | `DocumentStructure.definitions_v2` 字段存在且类型为 `List[DefinitionEntry]` | 代码审查 |
| AC-9 | `DocumentStructure.definitions`（Dict[str, str]）继续正常工作 | 回归测试 |
| AC-10 | `resolve_definition` skill 优先查 `definitions_v2`，fallback 到 `definitions` | 单元测试 |
| AC-11 | `resolve_definition` skill 能通过 aliases 匹配术语 | 单元测试 |
| AC-12 | `_validate_entries` 过滤术语长度 < 2 或 > 50 的条目 | 单元测试 |
| AC-13 | `_validate_entries` 过滤定义文本长度 < 4 的条目 | 单元测试 |
| AC-14 | `_validate_entries` 截断定义文本 > 2000 字符 | 单元测试 |
| AC-15 | `api_gen3.py` 上传管线调用 `extract_definitions_hybrid` 并回写 structure | 代码审查 |
| AC-16 | LLM 调用使用 `EXTRACT_CHAR_LIMIT=8000` 限制输入长度 | 代码审查 |
| AC-17 | `MAX_LLM_ENTRIES=60` 限制 LLM 返回条目数 | 代码审查 |
| AC-18 | `build_definitions_dict()` 正确构建向后兼容 dict | 单元测试 |
| AC-19 | 全量 `pytest` 通过，无回归 | CI |

### 10.2 Phase 2（未来增强，不在本 SPEC 范围）

| 特性 | 说明 |
|------|------|
| `ResolveDefinitionOutput.definitions_detail` | 返回富元数据给前端 |
| 定义术语高亮 | 前端在条款文本中高亮已识别的定义术语 |
| 定义一致性检查 | 检测同一术语在不同位置的定义是否一致 |
| 多文档定义对比 | 对比主合同与补充协议中的定义差异 |
| 定义缺失检测 | 识别合同中使用但未定义的术语 |
| 自定义正则模式 | 允许用户通过 UI 添加自定义定义提取模式 |

---

## 11. 实施步骤

### 11.1 推荐实施顺序

```
Step 1: models.py — 添加 DefinitionSource、DefinitionEntry、definitions_v2 字段
Step 2: definition_patterns.py — 创建正则模式库 + extract_by_patterns()
Step 3: definition_extractor.py — 创建混合提取管线
Step 4: structure_parser.py — _extract_definitions → _extract_definitions_v2
Step 5: api_gen3.py — 上传管线集成
Step 6: resolve_definition.py — 优先查 definitions_v2
Step 7: test_definition_extraction.py — 全量测试
Step 8: 全量 pytest 回归验证
```

### 11.2 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 扩展正则误匹配（false positive） | 中 | 低 | `_validate_entries` 过滤 + 测试覆盖 |
| LLM 幻觉生成不存在的定义 | 中 | 中 | regex 优先 + confidence 标记 + MAX_LLM_ENTRIES 限制 |
| `definitions_v2` 序列化体积过大 | 低 | 低 | 60 条上限 + 定义文本 2000 字符截断 |
| 现有 `resolve_definition` 测试失败 | 低 | 高 | 向后兼容设计：`definitions` dict 不变，v2 为增量 |
| 中文引号变体（`""` vs `""` vs `「」`） | 中 | 低 | 正则已覆盖 `\u201c\u201d`，可按需扩展 |

---

## 12. 数据流图

```
文档上传
    │
    ▼
┌─────────────────────────────────────────────────┐
│  api_gen3.py 上传管线                            │
│                                                  │
│  1. 文档解析 → StructureParser.parse()           │
│     └── _extract_definitions_v2() ← 扩展正则     │
│         → structure.definitions (Dict[str,str])  │
│                                                  │
│  2. SPEC-28: detect_clause_pattern() ← LLM      │
│                                                  │
│  3. SPEC-29: extract_definitions_hybrid() ← LLM │
│     ├── Phase A: 定义条款扩展正则                 │
│     ├── Phase B: 全文行内定义扫描                 │
│     ├── Phase C: LLM 结构化提取                  │
│     ├── Phase D: 合并去重                        │
│     └── Phase E: 验证过滤                        │
│         → structure.definitions_v2               │
│         → structure.definitions.update()         │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│  审阅阶段 — resolve_definition skill             │
│                                                  │
│  查找优先级：                                     │
│  1. definitions_v2 (含 aliases 展开)             │
│  2. definitions (向后兼容 fallback)              │
└─────────────────────────────────────────────────┘
```
