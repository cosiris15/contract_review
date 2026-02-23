# SPEC-30：交叉引用混合引擎 + 定义章节自动识别 + 结构回退增强

> 状态：Draft
> 优先级：P0
> 前置依赖：SPEC-28（smart_parser LLM 模式检测）、SPEC-29（定义术语混合提取）
> 设计风格：对齐 SPEC-29 —— 规则保底 + LLM 补充 + 可验证回退

---

## 0. 背景与动机

SPEC-28 实现了 LLM 辅助的条款编号模式检测，SPEC-29 实现了定义术语的混合提取。但对于非插件合同（即非 FIDIC / SHA-SPA 等预设领域），仍存在三个关键缺口：

| 缺口 | 现状 | 影响 |
|------|------|------|
| 交叉引用检测 | `structure_parser.py:154-159` 仅 4 条硬编码正则，零 LLM 参与 | 无法识别 Article/Section/§/Appendix/附件/款/项 等常见格式 |
| 定义章节识别 | `definitions_section_id` 仅由插件硬编码（FIDIC="1.1"），`smart_parser.py` 始终返回 `None` | 非插件合同跳过 Phase A 精确定义提取 |
| 结构解析回退 | `FALLBACK_CONFIG` 仅 `^\d+(?:\.\d+)*\s+`（纯数字编号） | 中文"第X条"、Article/Section、罗马数字等格式完全失效 |

本 SPEC 将三个缺口打包为一个统一方案，避免割裂修补。

---

## 1. 设计原则

1. **规则保底**：扩展正则模式库覆盖常见格式，确保零 LLM 调用时仍有基本能力
2. **LLM 增强**：对规则无法覆盖的非标格式，用 LLM 补充提取
3. **可验证回退**：LLM 结果必须通过验证（目标条款存在性校验），失败时静默降级到规则结果
4. **向后兼容**：`CrossReference` 模型不变，新增字段均为 Optional；现有插件配置不受影响
5. **单次 LLM 调用合并**：将定义章节识别与交叉引用模式检测合并到 `smart_parser.py` 的同一次 LLM 调用中，避免额外延迟

---

## 2. 数据模型变更

### 2.1 CrossReference 增强（models.py）

现有模型保持不变，新增 `source` 和 `confidence` 字段：

```python
class CrossReferenceSource(str, Enum):
    """交叉引用检测来源。"""
    REGEX = "regex"
    LLM = "llm"

class CrossReference(BaseModel):
    """条款间交叉引用。"""
    source_clause_id: str
    target_clause_id: str
    reference_text: str = ""
    is_valid: Optional[bool] = None
    # --- SPEC-30 新增 ---
    source: CrossReferenceSource = CrossReferenceSource.REGEX
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reference_type: Optional[str] = None  # "clause" | "article" | "section" | "appendix" | "schedule" | "annex" | "paragraph"
```

### 2.2 DocumentParserConfig 扩展（models.py）

新增可选字段，由 LLM 检测填充：

```python
class DocumentParserConfig(BaseModel):
    """文档解析器配置。"""
    clause_pattern: str = r"^\d+(?:\.\d+)*\s+"
    chapter_pattern: Optional[str] = None
    definitions_section_id: Optional[str] = None
    max_depth: int = 4
    structure_type: str = "generic_numbered"
    # --- SPEC-30 新增 ---
    cross_reference_patterns: List[str] = Field(default_factory=list)  # LLM 生成的额外交叉引用正则
```

---

## 3. 交叉引用正则模式库（cross_reference_patterns.py — 新文件）

### 3.1 设计

对齐 `definition_patterns.py` 的 `DefinitionPattern` 风格，创建 `CrossRefPattern` 数据类：

```python
@dataclass
class CrossRefPattern:
    name: str
    regex: str
    target_group: int = 1          # 捕获目标条款 ID 的分组号
    reference_type: str = "clause"  # clause/article/section/appendix/schedule/annex/paragraph
    language: str = "any"           # en/zh/any
```

### 3.2 内置模式清单

#### 英文模式（EN_XREF_PATTERNS）

| 名称 | 正则 | 匹配示例 | reference_type |
|------|------|---------|----------------|
| `en_clause` | `[Cc]lause\s+(\d+(?:\.\d+)*)` | Clause 4.1 | clause |
| `en_sub_clause` | `[Ss]ub-[Cc]lause\s+(\d+(?:\.\d+)*)` | Sub-Clause 4.1.2 | clause |
| `en_article` | `[Aa]rticle\s+(\d+(?:\.\d+)*)` | Article 5 | article |
| `en_section` | `[Ss]ection\s+(\d+(?:\.\d+)*)` | Section 3.2 | section |
| `en_paragraph` | `[Pp]aragraph\s+(\d+(?:\.\d+)*)` | Paragraph 2.1 | paragraph |
| `en_section_symbol` | `§\s*(\d+(?:\.\d+)*)` | § 12.3 | section |
| `en_appendix` | `[Aa]ppendix\s+([A-Z\d]+)` | Appendix A | appendix |
| `en_schedule` | `[Ss]chedule\s+(\d+\|[A-Z])` | Schedule 1 | schedule |
| `en_annex` | `[Aa]nnex\s+([A-Z\d]+)` | Annex B | annex |

#### 中文模式（ZH_XREF_PATTERNS）

| 名称 | 正则 | 匹配示例 | reference_type |
|------|------|---------|----------------|
| `zh_di_tiao` | `第\s*(\d+(?:\.\d+)*)\s*条` | 第 5 条 | clause |
| `zh_di_tiao_cn` | `第[一二三四五六七八九十百零]+条` | 第五条 | clause |
| `zh_kuan` | `第\s*(\d+)\s*款` | 第 2 款 | paragraph |
| `zh_xiang` | `第\s*(\d+)\s*项` | 第 3 项 | paragraph |
| `zh_see_ref` | `(?:见\|参见\|依据\|根据\|按照\|依照)\s*第?\s*(\d+(?:\.\d+)*)\s*条` | 见第 5.1 条 | clause |
| `zh_fujian` | `(?:附件\|附录\|附表)\s*([一二三四五六七八九十\d]+)` | 附件一 | appendix |

#### 合并列表

```python
ALL_XREF_PATTERNS: List[CrossRefPattern] = EN_XREF_PATTERNS + ZH_XREF_PATTERNS
```

### 3.3 提取函数

```python
def extract_cross_refs_by_patterns(
    text: str,
    source_clause_id: str,
    all_clause_ids: Set[str],
    patterns: List[CrossRefPattern] | None = None,
) -> List[CrossReference]:
    """从文本中提取交叉引用，返回 CrossReference 列表。"""
```

逻辑：
1. 遍历 patterns（默认 ALL_XREF_PATTERNS），对每个 pattern 执行 `re.finditer`
2. 提取 `target_id = match.group(pat.target_group)`
3. 跳过 `target_id == source_clause_id`（自引用）
4. 去重：同一 `(source, target, reference_text)` 只保留首次
5. 设置 `is_valid = target_id in all_clause_ids`
6. 设置 `source=CrossReferenceSource.REGEX, confidence=1.0`
7. 对中文数字条款（如"第五条"），尝试转换为阿拉伯数字后再校验 `is_valid`

### 3.4 中文数字转换辅助函数

```python
def _cn_num_to_arabic(cn: str) -> Optional[int]:
    """将中文数字（一~九十九）转换为阿拉伯数字。超出范围返回 None。"""
```

映射表：一=1, 二=2, ..., 十=10, 十一=11, ..., 九十九=99。用于将"第五条"转换为 target_id="5" 以便校验 `is_valid`。

---

## 4. 交叉引用 LLM 补充提取（cross_reference_extractor.py — 新文件）

### 4.1 设计思路

对齐 SPEC-29 的 `definition_extractor.py`，创建独立的交叉引用混合提取模块。

### 4.2 LLM Prompt

```python
XREF_EXTRACT_SYSTEM = """你是一个合同交叉引用分析专家。
请从给定条款文本中提取所有对其他条款、附件、附录的引用。
只返回 JSON，不要附加解释。
格式:
{
  "cross_references": [
    {
      "target_id": "引用目标的编号（如 5.1、Article 3、附件一）",
      "reference_text": "包含引用的原文片段（不超过 80 字）",
      "reference_type": "clause|article|section|appendix|schedule|annex|paragraph"
    }
  ],
  "confidence": 0.0
}"""

XREF_EXTRACT_USER = """请提取以下条款中的交叉引用：

条款编号：{clause_id}
条款文本：
<<<TEXT_START>>>
{text}
<<<TEXT_END>>>"""
```

### 4.3 LLM 提取函数

```python
XREF_CHAR_LIMIT = 4000
MAX_LLM_XREFS = 30

async def _llm_extract_cross_refs(
    llm_client,
    clause_id: str,
    clause_text: str,
) -> List[CrossReference]:
    """调用 LLM 提取单个条款的交叉引用。"""
```

逻辑：
1. 如果 `clause_text` 为空或 `llm_client` 为 None，返回空列表
2. 截断文本到 `XREF_CHAR_LIMIT`
3. 调用 LLM，使用 `_parse_llm_response` 解析 JSON
4. 遍历 `cross_references` 数组，构建 `CrossReference` 对象
5. 设置 `source=CrossReferenceSource.LLM`，`confidence` 取 LLM 返回值
6. 异常时 `logger.exception` 并返回空列表（静默降级）

### 4.4 混合提取主函数

```python
async def extract_cross_refs_hybrid(
    llm_client,
    clause_id: str,
    clause_text: str,
    all_clause_ids: Set[str],
    extra_patterns: List[str] | None = None,
) -> List[CrossReference]:
    """规则保底 + LLM 补充的交叉引用混合提取。"""
```

三阶段流程：

**Phase A：规则提取**
1. 调用 `extract_cross_refs_by_patterns(clause_text, clause_id, all_clause_ids)`
2. 如果 `extra_patterns` 非空，将其编译为 `CrossRefPattern` 并追加提取
3. 记录已发现的 `(target_id, reference_text)` 到 `seen` 集合

**Phase B：LLM 补充**
1. 调用 `_llm_extract_cross_refs(llm_client, clause_id, clause_text)`
2. 对每个 LLM 结果，检查 `(target_id, reference_text)` 是否已在 `seen` 中
3. 如果是新发现，校验 `is_valid = target_id in all_clause_ids`
4. 追加到结果列表

**Phase C：去重与排序**
1. 按 `(source_clause_id, target_clause_id)` 去重，规则优先
2. 返回最终列表

### 4.5 批量提取入口

```python
async def extract_all_cross_refs_hybrid(
    llm_client,
    clause_tree: List[ClauseNode],
    all_clause_ids: Set[str],
    extra_patterns: List[str] | None = None,
    max_llm_clauses: int = 50,
) -> List[CrossReference]:
    """遍历所有条款，执行混合交叉引用提取。"""
```

逻辑：
1. 遍历 `clause_tree`（递归展开所有节点）
2. 对每个节点调用 `extract_cross_refs_hybrid`
3. 为控制 LLM 调用量，仅对前 `max_llm_clauses` 个条款调用 LLM，其余仅用规则
4. 合并所有结果并返回

> 注意：`max_llm_clauses=50` 是默认值。对于大型合同（>100 条款），LLM 仅处理前 50 个条款，其余用规则覆盖。这是性能与质量的平衡点。

---

## 5. smart_parser.py 增强 — 定义章节识别 + 结构回退

### 5.1 LLM Prompt 扩展

当前 `PATTERN_DETECTION_SYSTEM` prompt 仅要求 LLM 返回 `clause_pattern`、`chapter_pattern`、`structure_type`、`max_depth`、`confidence`。

SPEC-30 扩展 JSON 输出格式，新增两个字段：

```json
{
  "clause_pattern": "...",
  "chapter_pattern": "...",
  "structure_type": "...",
  "max_depth": 4,
  "confidence": 0.9,
  "reasoning": "...",
  "definitions_section_id": "1.1 或 null",
  "cross_reference_patterns": ["额外的交叉引用正则（如有非标格式）"]
}
```

在 `PATTERN_DETECTION_SYSTEM` prompt 末尾追加：

```
6. 识别定义/解释条款的位置：
   - 查找标题包含"定义"、"释义"、"Definitions"、"Interpretation"等关键词的条款
   - 返回该条款的编号（如 "1.1"、"1"、"第一条"）
   - 如果没有明确的定义章节，返回 null
7. 如果文档使用了非标准的交叉引用格式（不在常见的 Clause/Article/Section/第X条 之列），
   请提供额外的正则表达式用于匹配这些引用
```

JSON 格式说明追加：

```
  "definitions_section_id": "定义章节的条款编号（如 1.1），如果没有则为 null",
  "cross_reference_patterns": ["额外的交叉引用正则数组，如果没有则为空数组"]
```

### 5.2 detect_clause_pattern 函数修改

在 `smart_parser.py` 的 `detect_clause_pattern` 函数中：

1. 解析 LLM 返回的 `definitions_section_id` 字段
2. 如果非空且为字符串，设置到 `DocumentParserConfig.definitions_section_id`
3. 如果 `existing_config` 已有 `definitions_section_id`（来自插件），保留插件值（插件优先）
4. 解析 `cross_reference_patterns` 数组，逐个验证正则合法性
5. 合法的正则存入 `DocumentParserConfig.cross_reference_patterns`

关键代码变更（伪代码）：

```python
# 在构建 config 之前
raw_def_section = payload.get("definitions_section_id")
definitions_section_id = None
if raw_def_section and isinstance(raw_def_section, str) and raw_def_section.strip():
    definitions_section_id = raw_def_section.strip()

# 插件优先：如果 existing_config 已有值，保留
if existing_config and existing_config.definitions_section_id:
    definitions_section_id = existing_config.definitions_section_id

# 交叉引用额外模式
raw_xref_patterns = payload.get("cross_reference_patterns", [])
valid_xref_patterns = []
if isinstance(raw_xref_patterns, list):
    for p in raw_xref_patterns:
        if isinstance(p, str) and _validate_regex(p):
            valid_xref_patterns.append(p)

config = DocumentParserConfig(
    clause_pattern=clause_pattern,
    chapter_pattern=chapter_pattern,
    definitions_section_id=definitions_section_id,  # 现在可能非 None
    max_depth=min(max(max_depth_int, 1), 6),
    structure_type=...,
    cross_reference_patterns=valid_xref_patterns,
)
```

### 5.3 结构回退增强 — FALLBACK_PATTERNS

当前 `FALLBACK_CONFIG` 仅有一个正则 `^\d+(?:\.\d+)*\s+`。当 LLM 失败且无插件配置时，对中文合同或 Article/Section 格式完全无效。

新增多模式回退尝试机制：

```python
FALLBACK_PATTERNS = [
    (r"^\d+(?:\.\d+)*\s+", "generic_numbered"),           # 1 / 1.1 / 1.1.1
    (r"^第[一二三四五六七八九十百零]+条", "chinese_numbered"),  # 第一条 / 第二条
    (r"^第\s*\d+\s*条", "chinese_arabic_numbered"),         # 第1条 / 第 2 条
    (r"^(?:Article|ARTICLE)\s+\d+", "article_numbered"),    # Article 1
    (r"^(?:Section|SECTION)\s+\d+", "section_numbered"),    # Section 1
]

def _select_best_fallback(text: str) -> DocumentParserConfig:
    """尝试多个回退模式，选择匹配数最多的。"""
    best_pattern = FALLBACK_PATTERNS[0][0]
    best_type = FALLBACK_PATTERNS[0][1]
    best_count = _count_matches(best_pattern, text)

    for pattern, structure_type in FALLBACK_PATTERNS[1:]:
        count = _count_matches(pattern, text)
        if count > best_count:
            best_count = count
            best_pattern = pattern
            best_type = structure_type

    if best_count < 3:
        # 所有模式都匹配不到足够条款，使用默认
        return FALLBACK_CONFIG

    return DocumentParserConfig(
        clause_pattern=best_pattern,
        chapter_pattern=None,
        definitions_section_id=None,
        max_depth=4,
        structure_type=best_type,
    )
```

在 `detect_clause_pattern` 中，将所有 `return existing_config or FALLBACK_CONFIG` 替换为：

```python
return existing_config or _select_best_fallback(document_text)
```

这样即使 LLM 完全失败，系统也能自动选择最匹配的回退模式。

---

## 6. structure_parser.py 改造 — 使用新模式库

### 6.1 _extract_cross_references 重构

将硬编码的 4 个正则替换为调用 `cross_reference_patterns.extract_cross_refs_by_patterns`：

```python
def _extract_cross_references(self, clause_tree: List[ClauseNode]) -> List[CrossReference]:
    """使用扩展模式库提取交叉引用（同步路径，仅规则）。"""
    all_clause_ids = set(self._collect_all_ids(clause_tree))
    refs: List[CrossReference] = []
    seen: set[tuple] = set()

    # 构建额外模式（来自 LLM 检测）
    extra = []
    if self.config.cross_reference_patterns:
        for i, p in enumerate(self.config.cross_reference_patterns):
            extra.append(CrossRefPattern(
                name=f"llm_extra_{i}",
                regex=p,
                reference_type="clause",
            ))

    all_patterns = ALL_XREF_PATTERNS + extra

    def scan_node(node: ClauseNode):
        node_refs = extract_cross_refs_by_patterns(
            text=node.text,
            source_clause_id=node.clause_id,
            all_clause_ids=all_clause_ids,
            patterns=all_patterns,
        )
        for ref in node_refs:
            key = (ref.source_clause_id, ref.target_clause_id, ref.reference_text)
            if key not in seen:
                seen.add(key)
                refs.append(ref)
        for child in node.children:
            scan_node(child)

    for node in clause_tree:
        scan_node(node)
    return refs
```

### 6.2 向后兼容

- `StructureParser.parse()` 的同步路径仍然只用规则（不调用 LLM）
- LLM 增强在 `api_gen3.py` 的异步路径中执行（见 Section 7）
- 现有测试中的 `test_cross_references` 不受影响，因为 `Clause` 和 `Sub-Clause` 模式仍在 `ALL_XREF_PATTERNS` 中

---

## 7. api_gen3.py 集成 — 异步 LLM 交叉引用增强

### 7.1 集成位置

在 `api_gen3.py` 的上传管道中，SPEC-29 定义提取之后、存储到 graph state 之前，插入交叉引用 LLM 增强：

```
detect_clause_pattern()          ← SPEC-28（现在也返回 definitions_section_id）
    ↓
StructureParser.parse()          ← 同步规则提取（使用扩展模式库）
    ↓
extract_definitions_hybrid()     ← SPEC-29
    ↓
extract_all_cross_refs_hybrid()  ← SPEC-30 新增（LLM 补充交叉引用）
    ↓
store in graph state
```

### 7.2 集成代码（伪代码）

在 SPEC-29 定义提取代码块之后追加：

```python
# --- SPEC-30: 交叉引用 LLM 增强 ---
try:
    from .cross_reference_extractor import extract_all_cross_refs_hybrid

    all_clause_ids = set()
    def _collect_ids(nodes):
        for n in nodes:
            all_clause_ids.add(n.clause_id)
            _collect_ids(n.children)
    if structure and structure.clauses:
        _collect_ids(structure.clauses)

    enhanced_refs = await extract_all_cross_refs_hybrid(
        llm_client=llm_client,
        clause_tree=structure.clauses,
        all_clause_ids=all_clause_ids,
        extra_patterns=getattr(parser_config, "cross_reference_patterns", None),
    )
    if enhanced_refs:
        structure.cross_references = enhanced_refs
except Exception:
    logger.warning("SPEC-30 交叉引用增强跳过", exc_info=True)
```

### 7.3 definitions_section_id 自动生效

由于 `detect_clause_pattern` 现在会返回 `definitions_section_id`（Section 5.2），后续的 SPEC-29 定义提取代码无需修改——它已经在检查 `parser_config.definitions_section_id`：

```python
# 已有代码（api_gen3.py:384-388），无需改动
def_section_id = getattr(parser_config, "definitions_section_id", None) if parser_config else None
if def_section_id and structure:
    def_node = _find_clause_in_structure(structure, str(def_section_id))
    if def_node:
        def_section_text = _collect_node_text(def_node)
```

现在 `def_section_id` 对非插件合同也可能非 None（由 LLM 检测填充），Phase A 精确定义提取将自动激活。

---

## 8. cross_reference_check skill 增强

### 8.1 现状

`cross_reference_check.py` 仅消费 `structure.cross_references`，不做任何提取。SPEC-30 的改动对它是透明的——它会自动获得更多、更准确的交叉引用数据。

### 8.2 增强：输出 reference_type

在 `CrossReferenceCheckOutput` 的 `references` 和 `invalid_references` 字典中，新增 `reference_type` 和 `source` 字段：

```python
entry = {
    "target_clause_id": str(ref.get("target_clause_id", "") or ""),
    "reference_text": str(ref.get("reference_text", "") or ""),
    "is_valid": bool(ref.get("is_valid", False)),
    # SPEC-30 新增
    "reference_type": str(ref.get("reference_type", "") or ""),
    "source": str(ref.get("source", "regex") or "regex"),
}
```

这是纯透传，不影响现有逻辑。

---

## 9. 测试计划

### 9.1 新增测试文件：tests/test_cross_reference_patterns.py

```python
class TestCrossRefPatternsEN:
    def test_clause_and_sub_clause(self): ...
    def test_article_and_section(self): ...
    def test_section_symbol(self): ...
    def test_appendix_schedule_annex(self): ...
    def test_paragraph(self): ...
    def test_dedup_same_target(self): ...

class TestCrossRefPatternsZH:
    def test_di_tiao_arabic(self): ...
    def test_di_tiao_chinese(self): ...
    def test_kuan_and_xiang(self): ...
    def test_see_ref_variants(self): ...
    def test_fujian(self): ...
    def test_cn_num_conversion(self): ...

class TestCrossRefExtractor:
    @pytest.mark.asyncio
    async def test_regex_only_when_llm_empty(self): ...
    @pytest.mark.asyncio
    async def test_llm_supplement(self): ...
    @pytest.mark.asyncio
    async def test_regex_wins_on_same_ref(self): ...
    @pytest.mark.asyncio
    async def test_llm_failure_degrades(self): ...
    @pytest.mark.asyncio
    async def test_unparseable_llm_degrades(self): ...
    @pytest.mark.asyncio
    async def test_extra_patterns_from_config(self): ...

class TestCnNumToArabic:
    def test_basic_numbers(self): ...
    def test_teens(self): ...
    def test_tens(self): ...
    def test_out_of_range(self): ...
```

### 9.2 新增测试文件：tests/test_smart_parser_enhanced.py

```python
class TestDefinitionsSectionDetection:
    @pytest.mark.asyncio
    async def test_llm_detects_definitions_section(self): ...
    @pytest.mark.asyncio
    async def test_plugin_overrides_llm(self): ...
    @pytest.mark.asyncio
    async def test_llm_returns_null_section(self): ...

class TestFallbackPatterns:
    def test_chinese_numbered_fallback(self): ...
    def test_article_numbered_fallback(self): ...
    def test_section_numbered_fallback(self): ...
    def test_best_match_wins(self): ...
    def test_all_fail_returns_default(self): ...

class TestCrossReferencePatternDetection:
    @pytest.mark.asyncio
    async def test_extra_patterns_validated(self): ...
    @pytest.mark.asyncio
    async def test_invalid_patterns_filtered(self): ...
```

### 9.3 现有测试回归

以下现有测试必须继续通过（零修改）：

- `tests/test_structure_parser.py` — 所有 7 个测试
- `tests/test_definition_extraction.py` — 所有测试
- `tests/test_generic_skills.py` — 所有测试（含 alias lookup）
- `tests/test_smart_parser.py` — 所有测试

---

## 10. 文件清单

| 文件 | 类型 | 预估行数 | 说明 |
|------|------|---------|------|
| `backend/src/contract_review/models.py` | 修改 | ~15 | 新增 `CrossReferenceSource` 枚举，`CrossReference` 增加 3 字段，`DocumentParserConfig` 增加 1 字段 |
| `backend/src/contract_review/cross_reference_patterns.py` | 新建 | ~150 | 交叉引用正则模式库 + `extract_cross_refs_by_patterns` + `_cn_num_to_arabic` |
| `backend/src/contract_review/cross_reference_extractor.py` | 新建 | ~180 | LLM 交叉引用提取 + 混合引擎 + 批量入口 |
| `backend/src/contract_review/smart_parser.py` | 修改 | ~50 | prompt 扩展 + `definitions_section_id` 解析 + `FALLBACK_PATTERNS` + `_select_best_fallback` |
| `backend/src/contract_review/structure_parser.py` | 修改 | ~20 | `_extract_cross_references` 重构为调用模式库 |
| `backend/src/contract_review/api_gen3.py` | 修改 | ~20 | 集成 `extract_all_cross_refs_hybrid` |
| `backend/src/contract_review/skills/local/cross_reference_check.py` | 修改 | ~5 | 输出增加 `reference_type` 和 `source` 字段 |
| `tests/test_cross_reference_patterns.py` | 新建 | ~200 | 正则模式 + 混合引擎 + 中文数字转换测试 |
| `tests/test_smart_parser_enhanced.py` | 新建 | ~120 | 定义章节检测 + 回退模式 + 额外模式验证测试 |

总计：~760 行，5 个修改文件 + 4 个新建文件

---

## 11. 验收条件（AC）

### 交叉引用正则模式库（AC 1-5）

1. `EN_XREF_PATTERNS` 包含 9 个英文模式，覆盖 Clause/Sub-Clause/Article/Section/Paragraph/§/Appendix/Schedule/Annex
2. `ZH_XREF_PATTERNS` 包含 6 个中文模式，覆盖 第X条（阿拉伯+中文数字）/款/项/见X条/附件
3. `extract_cross_refs_by_patterns` 正确提取、去重、校验 `is_valid`
4. `_cn_num_to_arabic` 正确转换一~九十九
5. 自引用（source == target）被过滤

### 交叉引用 LLM 混合引擎（AC 6-10）

6. LLM 返回空时，仅使用规则结果
7. LLM 补充新引用时，正确追加且标记 `source=LLM`
8. 规则与 LLM 发现相同引用时，规则优先（`source=REGEX`）
9. LLM 异常时静默降级到规则结果
10. `max_llm_clauses` 限制生效，超出的条款仅用规则

### smart_parser 增强（AC 11-15）

11. LLM 返回 `definitions_section_id` 时，正确设置到 `DocumentParserConfig`
12. 插件已有 `definitions_section_id` 时，插件值优先
13. LLM 返回 `cross_reference_patterns` 时，逐个验证并存入配置
14. `_select_best_fallback` 对中文合同选择 `chinese_numbered` 模式
15. `_select_best_fallback` 对 Article 格式合同选择 `article_numbered` 模式

### 集成与兼容（AC 16-20）

16. `api_gen3.py` 上传管道中，交叉引用 LLM 增强在定义提取之后执行
17. 非插件合同的 `definitions_section_id` 由 LLM 自动检测填充
18. `cross_reference_check` skill 输出包含 `reference_type` 和 `source`
19. 所有现有测试（292+）零回归
20. `PYTHONPATH=backend/src python -m pytest tests/ -x -q` 全量通过

---

## 12. 实施步骤

建议按以下顺序实施，每步可独立验证：

1. **models.py** — 新增 `CrossReferenceSource`，扩展 `CrossReference` 和 `DocumentParserConfig`
2. **cross_reference_patterns.py** — 新建模式库 + 提取函数 + 中文数字转换
3. **tests/test_cross_reference_patterns.py** — 正则模式单元测试（先写测试）
4. **cross_reference_extractor.py** — LLM 混合引擎
5. **tests/test_cross_reference_patterns.py** — 补充混合引擎测试
6. **smart_parser.py** — prompt 扩展 + 定义章节解析 + 回退增强
7. **tests/test_smart_parser_enhanced.py** — 回退模式 + 定义章节检测测试
8. **structure_parser.py** — 重构 `_extract_cross_references`
9. **api_gen3.py** — 集成交叉引用 LLM 增强
10. **cross_reference_check.py** — 输出字段增强
11. **全量回归测试** — 确认 292+ 测试全部通过

---

## 13. 数据流全景图

```
文档上传
    ↓
detect_clause_pattern() [LLM — SPEC-28 + SPEC-30 扩展]
    ├─ clause_pattern（条款编号正则）
    ├─ definitions_section_id（定义章节 ID）← SPEC-30 新增
    └─ cross_reference_patterns（额外交叉引用正则）← SPEC-30 新增
    ↓
    ↓ [LLM 失败时]
    ↓ _select_best_fallback() ← SPEC-30 新增
    ↓   尝试 5 种回退模式，选最佳匹配
    ↓
StructureParser.parse() [同步]
    ├─ _split_clauses()（条款切分）
    ├─ _build_tree()（层级树构建）
    ├─ _extract_definitions_v2()（定义提取 — 现在 definitions_section_id 可能非 None）
    └─ _extract_cross_references()（交叉引用 — 使用扩展模式库）← SPEC-30 重构
         └─ ALL_XREF_PATTERNS（15 个内置模式）+ extra_patterns（LLM 生成）
    ↓
extract_definitions_hybrid() [异步 — SPEC-29]
    ├─ Phase A: 定义章节正则（现在对非插件合同也可能激活）
    ├─ Phase B: 内联正则扫描
    └─ Phase C: LLM 补充
    ↓
extract_all_cross_refs_hybrid() [异步 — SPEC-30 新增]
    ├─ 对每个条款：规则提取（15+ 模式）
    ├─ 对前 50 个条款：LLM 补充提取
    └─ 去重合并（规则优先）
    ↓
存入 graph state
    ↓
Skills 消费：
    ├─ cross_reference_check: 校验引用有效性（现在有 reference_type + source）
    └─ resolve_definition: 解析术语定义（受益于 definitions_section_id 自动检测）
```
