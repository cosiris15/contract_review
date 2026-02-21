# 专业 Skills 开发设计文档

## 1. 总览

本文档为 FIDIC 和 SHA/SPA 两个合同审查场景设计专业 Skills 的完整开发逻辑，包括：
- 每个 Skill 的功能定义、输入输出、实现方式
- 本地 vs Refly 的划分依据
- 与现有框架的集成方式
- 实施路线图

### 1.1 划分原则

| 维度 | 本地 Skill | Refly Skill |
|------|-----------|-------------|
| 逻辑类型 | 确定性（正则、规则、diff） | 需要 LLM 推理或语义理解 |
| 数据范围 | 单文档/单条款 | 跨文档、大文档向量检索 |
| 输入输出 | 结构明确、可预测 | 需要多步骤 workflow |
| 延迟要求 | 低延迟（<1s） | 可接受较高延迟（5-30s） |

### 1.2 现有框架集成点

每个新 Skill 需要：
1. **Input/Output Model** — 在对应的 skill 模块中定义 Pydantic 模型
2. **Handler 函数** — `async def skill_name(input_data: XxxInput) -> XxxOutput`
3. **SkillRegistration** — 在域插件（如 `fidic.py`）中声明
4. **_build_skill_input 分支** — 在 `builder.py` 中添加输入构造逻辑
5. **Checklist 引用** — 在 `required_skills` 中添加 skill_id

对于 Refly Skill，额外需要：
- Refly 平台上创建对应 workflow
- `ReflyClient` 从 stub 升级为真实 HTTP 调用
- 环境变量配置 `REFLY_API_KEY`

---

## 2. FIDIC 场景

### 2.1 场景特征

FIDIC 合同（Silver/Yellow/Red Book）的核心结构：
- **GC（General Conditions）**：FIDIC 标准通用条件，条款编号固定（1.1-20.x）
- **PC（Particular Conditions）**：项目专用条件，对 GC 进行修改/补充/删除
- **ER（Employer's Requirements）**：业主方要求，通常是独立的大文档
- **标准版本**：FIDIC 2017 版有公开的标准条款文本，可作为基线对比

审查核心关注点：PC 对 GC 做了哪些修改？这些修改是否对承包商不利？

### 2.2 FIDIC 本地 Skills

---

#### 2.2.1 `fidic_merge_gc_pc` — GC+PC 条款合并

**功能：** 将 GC 标准文本与 PC 修改按条款号合并，输出每个条款的最终生效文本，并标注 PC 对 GC 的修改类型。

**为什么本地：** 纯结构化文本操作，按条款号做 diff，不需要 LLM。

**输入模型：**

```python
class MergeGcPcInput(BaseModel):
    clause_id: str
    document_structure: Any  # primary document (PC) 的解析结构
    gc_baseline: str = ""    # GC 标准条款原文（从 baseline_texts 获取）
```

**输出模型：**

```python
class MergeGcPcOutput(BaseModel):
    clause_id: str
    gc_text: str              # GC 原文
    pc_text: str              # PC 对应条款文本（如有）
    merged_text: str          # 最终生效文本
    modification_type: str    # "unchanged" | "modified" | "deleted" | "added" | "no_gc_baseline"
    changes_summary: str      # 变更摘要（如"PC 删除了第3段关于索赔时效的规定"）
```

**实现逻辑：**

```python
async def merge(input_data: MergeGcPcInput) -> MergeGcPcOutput:
    # 1. 从 document_structure 中提取当前条款文本（PC 文本）
    pc_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    gc_text = input_data.gc_baseline or ""

    # 2. 判断修改类型
    if not gc_text:
        modification_type = "no_gc_baseline"
        merged_text = pc_text
        changes_summary = "无 GC 基线文本可供对比"
    elif not pc_text:
        modification_type = "deleted"
        merged_text = ""
        changes_summary = "PC 删除了该条款"
    elif _normalize(pc_text) == _normalize(gc_text):
        modification_type = "unchanged"
        merged_text = gc_text
        changes_summary = "PC 未修改该条款"
    else:
        modification_type = "modified"
        merged_text = pc_text  # PC 覆盖 GC
        changes_summary = _compute_changes(gc_text, pc_text)

    return MergeGcPcOutput(
        clause_id=input_data.clause_id,
        gc_text=gc_text,
        pc_text=pc_text,
        merged_text=merged_text,
        modification_type=modification_type,
        changes_summary=changes_summary,
    )
```

**_compute_changes 逻辑：** 复用 `compare_with_baseline` 中的 `_compute_diff_summary`，输出"删除内容：xxx；新增内容：yyy"格式。

**builder.py 集成：**

```python
if skill_id == "fidic_merge_gc_pc":
    from ..skills.fidic.merge_gc_pc import MergeGcPcInput
    gc_baseline = get_baseline_text(state.get("domain_id", ""), clause_id) or ""
    return MergeGcPcInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        gc_baseline=gc_baseline,
    )
```

**文件路径：** `backend/src/contract_review/skills/fidic/merge_gc_pc.py`

---

#### 2.2.2 `fidic_calculate_time_bar` — 索赔时效计算

**功能：** 从条款文本中提取所有时效/通知期限要求，汇总为结构化清单。

**为什么本地：** FIDIC 的时效表述格式相对固定（"within X days"、"not later than X days after"、"X天内"），基于正则 + 规则即可提取。

**输入模型：**

```python
class CalculateTimeBarInput(BaseModel):
    clause_id: str
    document_structure: Any
```

**输出模型：**

```python
class TimeBarItem(BaseModel):
    trigger_event: str     # 触发事件描述（如"承包商知悉或应当知悉该事件"）
    deadline_days: int     # 期限天数
    deadline_text: str     # 原文表述（如"28 days"）
    action_required: str   # 需要采取的行动（如"提交索赔通知"）
    consequence: str       # 逾期后果（如"丧失索赔权利"）
    context: str           # 上下文片段

class CalculateTimeBarOutput(BaseModel):
    clause_id: str
    time_bars: List[TimeBarItem] = Field(default_factory=list)
    total_time_bars: int = 0
    has_strict_time_bar: bool = False  # 是否存在"逾期即丧权"的严格时效
```

**实现逻辑：**

```python
# 时效模式匹配
_TIME_BAR_PATTERNS = [
    # 英文模式
    (r"within\s+(\d+)\s*(?:calendar\s+)?days?\b", "en"),
    (r"not\s+later\s+than\s+(\d+)\s*days?\b", "en"),
    (r"(\d+)\s*days?\s*(?:after|from|of)\b", "en"),
    # 中文模式
    (r"(\d+)\s*(?:个工作日|天|日)内", "zh"),
    (r"不迟于.*?(\d+)\s*(?:天|日)", "zh"),
]

# 严格时效关键词（逾期丧权）
_STRICT_KEYWORDS = [
    "shall not be entitled", "deemed to have waived",
    "time-barred", "forfeited", "丧失权利", "视为放弃",
]

async def calculate(input_data: CalculateTimeBarInput) -> CalculateTimeBarOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    time_bars = []

    for pattern, lang in _TIME_BAR_PATTERNS:
        for match in re.finditer(pattern, clause_text, re.IGNORECASE):
            days = int(match.group(1))
            start = max(0, match.start() - 80)
            end = min(len(clause_text), match.end() + 80)
            context = clause_text[start:end].strip()

            time_bars.append(TimeBarItem(
                trigger_event=_extract_trigger(context),
                deadline_days=days,
                deadline_text=match.group(0),
                action_required=_extract_action(context),
                consequence=_extract_consequence(context),
                context=context,
            ))

    has_strict = any(
        kw.lower() in clause_text.lower() for kw in _STRICT_KEYWORDS
    )

    return CalculateTimeBarOutput(
        clause_id=input_data.clause_id,
        time_bars=time_bars,
        total_time_bars=len(time_bars),
        has_strict_time_bar=has_strict,
    )
```

**辅助函数 `_extract_trigger` / `_extract_action` / `_extract_consequence`：**
- 基于上下文窗口中的关键词定位
- trigger: 查找 "after"/"from"/"upon" 后面的短语
- action: 查找 "shall"/"must"/"应当" 后面的动作
- consequence: 查找 "otherwise"/"failing which"/"否则" 后面的内容
- 如果无法提取，返回空字符串（LLM 分析时会补充）

**文件路径：** `backend/src/contract_review/skills/fidic/time_bar.py`

---

### 2.3 FIDIC 基线数据

当前 `fidic.py` 中 `baseline_texts={}` 为空。`compare_with_baseline` 和 `fidic_merge_gc_pc` 都依赖基线数据才能发挥作用。

#### 2.3.1 数据结构

```python
# backend/src/contract_review/skills/fidic/baseline_silver_book.py

FIDIC_SILVER_BOOK_2017_BASELINE: dict[str, str] = {
    "1.1": """1.1 Definitions
In the Conditions of Contract ("these Conditions"), which include Particular Conditions
and these General Conditions, the following words and expressions shall have the
meanings stated. Words indicating persons or parties include corporations and other
legal entities, except where the context requires otherwise.
...""",

    "1.5": """1.5 Priority of Documents
The documents forming the Contract are to be taken as mutually explanatory of one
another. For the purposes of interpretation, the priority of the documents shall be
in accordance with the following listing:
(a) the Contract Agreement,
(b) the Particular Conditions – Part A,
(c) the Particular Conditions – Part B,
(d) these General Conditions,
(e) the Employer's Requirements, and
(f) the Schedules and any other documents forming part of the Contract.
...""",

    "4.1": """4.1 Contractor's General Obligations
The Contractor shall design (to the extent specified in the Contract), execute and
complete the Works in accordance with the Contract, and shall remedy any defects
in the Works. The Contractor shall provide the Plant, Contractor's Documents,
Contractor's Personnel, Contractor's Equipment, Temporary Works and all other
things (whether of a temporary or permanent nature) required for the design,
execution, completion and remedying of defects.
...""",

    "8.2": """8.2 Time for Completion
The Contractor shall complete the whole of the Works, and each Section (if any),
within the Time for Completion for the Works or Section (as the case may be),
including achieving the requirements specified in the Contract for the purposes of
taking-over under Sub-Clause 10.1 [Taking Over of the Works and Sections].
...""",

    "14.1": """14.1 The Contract Price
Unless otherwise stated in the Particular Conditions:
(a) the Contract Price shall be the lump sum Accepted Contract Amount and be
subject to adjustments in accordance with the Contract;
(b) the Contractor shall pay all taxes, duties and fees required to be paid by the
Contractor under the Contract, and the Contract Price shall not be adjusted for
any of these costs except as stated in Sub-Clause 13.7 [Adjustments for Changes
in Legislation].
...""",

    "20.1": """20.1 Claims
If the Contractor considers himself to be entitled to any extension of the Time for
Completion and/or any additional payment, under any Clause of these Conditions or
otherwise in connection with the Contract, the Contractor shall give a notice to the
Engineer, describing the event or circumstance giving rise to the claim. The notice
shall be given as soon as practicable, and not later than 28 days after the Contractor
became aware, or should have become aware, of the event or circumstance.
...""",
}
```

#### 2.3.2 集成方式

在 `fidic.py` 中引用：

```python
from ..skills.fidic.baseline_silver_book import FIDIC_SILVER_BOOK_2017_BASELINE

FIDIC_PLUGIN = DomainPlugin(
    domain_id="fidic",
    ...
    baseline_texts=FIDIC_SILVER_BOOK_2017_BASELINE,
)
```

**注意：** 基线文本应尽量完整录入 FIDIC 2017 Silver Book 的 GC 条款原文。上面仅为示例片段，实际实施时需要补充 checklist 中涉及的所有条款（1.1, 1.5, 4.1, 4.12, 8.2, 14.1, 14.2, 14.7, 17.6, 18.1, 20.1, 20.2）的完整文本。

---

### 2.4 FIDIC Refly Skills

---

#### 2.4.1 `fidic_search_er` — ER 语义检索

**功能：** 在业主方要求（Employer's Requirements）大文档中，根据当前审查条款的关键词做语义检索，找出 ER 中与该条款相关的段落。

**为什么 Refly：**
- ER 文档通常很大（100-500 页），需要向量化索引
- 需要语义匹配而非关键词匹配（如"工期延误"应匹配"delay in completion"）
- Refly 平台提供 RAG workflow 能力

**Refly Workflow 设计：**

```
输入: { "query": "条款关键词+描述", "document_id": "ER文档ID", "top_k": 5 }
步骤:
  1. 将 query 向量化
  2. 在 ER 文档的向量索引中检索 top_k 相关段落
  3. 用 LLM 对检索结果做相关性过滤和摘要
输出: { "relevant_sections": [{ "section_id": "...", "text": "...", "relevance_score": 0.85 }] }
```

**本地侧输入构造（builder.py）：**

```python
if skill_id == "fidic_search_er":
    query = f"{clause_name} {description}"
    er_doc_id = _find_er_document_id(state)
    return GenericSkillInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        state_snapshot={
            "query": query,
            "er_document_id": er_doc_id,
            "top_k": 5,
        },
    )
```

**SkillRegistration（已在 fidic.py 中声明）：**

```python
SkillRegistration(
    skill_id="fidic_search_er",
    name="ER 语义检索",
    description="在业主方要求中做语义检索",
    backend=SkillBackend.REFLY,
    refly_workflow_id="refly_wf_fidic_search_er",  # Refly 平台上的 workflow ID
)
```

**Refly 平台开发要点：**
- 需要支持文档上传和向量化（ER 文档在创建审查任务时上传）
- Workflow 接收 query + document_id，返回相关段落
- 建议使用 Refly 的 Knowledge Base + RAG 模板

---

#### 2.4.2 `fidic_check_pc_consistency` — PC 一致性检查（新增）

**功能：** 检查 PC 各条款之间的内在一致性，识别矛盾或冲突。例如：PC 第 4 条扩大了承包商义务，但 PC 第 17 条的责任限制没有相应调整。

**为什么 Refly：**
- 需要跨条款的全局语义理解
- 需要 LLM 推理能力判断条款间的逻辑关系
- 单条款本地 Skill 无法完成跨条款分析

**Refly Workflow 设计：**

```
输入: {
  "pc_clauses": [
    { "clause_id": "4.1", "text": "...", "modification_type": "modified" },
    { "clause_id": "17.6", "text": "...", "modification_type": "modified" },
    ...
  ],
  "focus_clause_id": "4.1"
}
步骤:
  1. 将所有 modified/added 的 PC 条款作为上下文
  2. 聚焦当前条款，让 LLM 分析与其他修改条款的一致性
  3. 输出潜在冲突列表
输出: {
  "consistency_issues": [
    {
      "clause_a": "4.1",
      "clause_b": "17.6",
      "issue": "4.1 扩大了承包商设计责任，但 17.6 的责任上限未相应调整",
      "severity": "high"
    }
  ]
}
```

**SkillRegistration：**

```python
SkillRegistration(
    skill_id="fidic_check_pc_consistency",
    name="PC 一致性检查",
    description="检查 PC 各条款之间的内在一致性",
    backend=SkillBackend.REFLY,
    refly_workflow_id="refly_wf_fidic_pc_consistency",
)
```

**builder.py 集成：**

```python
if skill_id == "fidic_check_pc_consistency":
    # 收集所有已分析的 PC 修改条款
    findings = state.get("findings", {})
    pc_clauses = []
    for cid, finding in findings.items():
        skill_data = finding.get("skill_context", {}).get("fidic_merge_gc_pc", {})
        if skill_data.get("modification_type") in ("modified", "added"):
            pc_clauses.append({
                "clause_id": cid,
                "text": skill_data.get("pc_text", ""),
                "modification_type": skill_data.get("modification_type"),
            })
    return GenericSkillInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        state_snapshot={
            "pc_clauses": pc_clauses,
            "focus_clause_id": clause_id,
        },
    )
```

---

### 2.5 FIDIC 领域提示词增强

当前 `prompts.py` 中的提示词是通用的。FIDIC 场景需要在 `build_clause_analyze_messages` 中注入领域专业知识。

**方案：** 在 `_format_skill_context` 输出的基础上，增加 FIDIC 专用的分析指引。

```python
# prompts.py 中新增

FIDIC_DOMAIN_INSTRUCTION = """
【FIDIC 专项审查指引】
你正在审查一份 FIDIC {book_type} 合同。请特别关注以下方面：

1. **PC 对 GC 的修改**：PC 是否删除了对承包商有利的条款？是否增加了额外义务？
2. **时效条款（Time Bar）**：所有通知期限是否合理？是否存在"逾期即丧权"的严格时效？
3. **风险分配**：不可预见条件、不可抗力、法律变更等风险是否公平分配？
4. **付款机制**：付款条件是否清晰？是否存在不合理的扣款或延迟付款条款？
5. **索赔与争议**：索赔程序是否完整？争议解决机制是否对我方不利？
6. **责任限制**：赔偿上限是否合理？是否存在无限责任条款？

{merge_context}
{time_bar_context}
{er_context}
"""

def _build_fidic_instruction(state, skill_context, book_type="Silver Book"):
    merge_data = skill_context.get("fidic_merge_gc_pc", {})
    time_bar_data = skill_context.get("fidic_calculate_time_bar", {})
    er_data = skill_context.get("fidic_search_er", {})

    merge_context = ""
    if merge_data:
        mod_type = merge_data.get("modification_type", "")
        if mod_type == "modified":
            merge_context = f"【GC/PC 对比结果】该条款已被 PC 修改。变更摘要：{merge_data.get('changes_summary', '')}"
        elif mod_type == "deleted":
            merge_context = "【GC/PC 对比结果】该条款已被 PC 删除，需重点关注删除原因和影响。"

    time_bar_context = ""
    if time_bar_data and time_bar_data.get("total_time_bars", 0) > 0:
        bars = time_bar_data.get("time_bars", [])
        bar_summary = "; ".join(f"{b.get('deadline_text','')}: {b.get('action_required','')}" for b in bars[:3])
        strict = "⚠️ 存在严格时效条款（逾期丧权）" if time_bar_data.get("has_strict_time_bar") else ""
        time_bar_context = f"【时效分析】发现 {len(bars)} 个时效要求：{bar_summary}。{strict}"

    er_context = ""
    if er_data and er_data.get("relevant_sections"):
        sections = er_data["relevant_sections"]
        er_context = f"【ER 相关内容】在业主方要求中找到 {len(sections)} 个相关段落，请结合分析。"

    return FIDIC_DOMAIN_INSTRUCTION.format(
        book_type=book_type,
        merge_context=merge_context,
        time_bar_context=time_bar_context,
        er_context=er_context,
    )
```

**集成点：** 在 `build_clause_analyze_messages` 中，当 `domain_id == "fidic"` 时，将 FIDIC 指引追加到 system prompt。

---

### 2.6 FIDIC Skills 总览

| Skill ID | 类型 | 后端 | 功能 | 依赖 |
|----------|------|------|------|------|
| `fidic_merge_gc_pc` | 本地 | LOCAL | GC+PC 条款合并对比 | baseline_texts |
| `fidic_calculate_time_bar` | 本地 | LOCAL | 索赔时效提取 | 无 |
| `fidic_search_er` | 远程 | REFLY | ER 语义检索 | Refly workflow + ER 文档 |
| `fidic_check_pc_consistency` | 远程 | REFLY | PC 跨条款一致性检查 | Refly workflow + merge 结果 |

---

## 3. SHA/SPA 场景

### 3.1 场景特征

SHA（Shareholders' Agreement，股东协议）和 SPA（Share Purchase Agreement，股权转让协议）是并购/投资交易中的核心文件。

**文档结构特点：**
- 条款编号通常为 Article/Section 格式（如 Article 3, Section 3.1）
- 核心条款相对固定：先决条件、陈述与保证、赔偿、治理、竞业限制等
- 通常包含多个附件（Schedules/Exhibits）：披露函、财务报表等
- 中英文双语版本常见，以英文版为准

**审查核心关注点：**
- 先决条件（Conditions Precedent）是否完整、可控？
- 陈述与保证（Representations & Warranties）的范围和限制？
- 赔偿条款（Indemnification）的触发条件、上限、时效？
- 治理结构（Governance）中的保护性条款是否充分？
- 竞业限制和保密条款是否合理？

### 3.2 SHA/SPA 本地 Skills

---

#### 3.2.1 `spa_extract_conditions` — 先决条件提取

**功能：** 从交易文件中提取所有先决条件（Conditions Precedent / Conditions to Closing），结构化为清单，标注每个条件的责任方和状态。

**为什么本地：** 先决条件通常以编号列表形式出现，格式规律（"(a)...(b)...(c)..."），基于正则 + 规则即可提取。

**输入模型：**

```python
class ExtractConditionsInput(BaseModel):
    clause_id: str
    document_structure: Any
```

**输出模型：**

```python
class ConditionItem(BaseModel):
    condition_id: str          # 如 "CP-1", "CP-2"
    text: str                  # 条件原文
    responsible_party: str     # "buyer" | "seller" | "both" | "third_party"
    condition_type: str        # "regulatory" | "corporate" | "financial" | "legal" | "other"
    is_waivable: bool = False  # 是否可豁免
    context: str = ""          # 上下文片段

class ExtractConditionsOutput(BaseModel):
    clause_id: str
    conditions: List[ConditionItem] = Field(default_factory=list)
    total_conditions: int = 0
    buyer_conditions: int = 0   # 买方需满足的条件数
    seller_conditions: int = 0  # 卖方需满足的条件数
    has_material_adverse_change: bool = False  # 是否包含 MAC 条件
```

**实现逻辑：**

```python
# 先决条件模式匹配
_CP_SECTION_PATTERNS = [
    r"(?i)conditions?\s+(?:precedent|to\s+closing|to\s+completion)",
    r"(?i)closing\s+conditions?",
    r"先决条件",
    r"交割条件",
]

_CP_ITEM_PATTERNS = [
    r"\(([a-z])\)\s*(.+?)(?=\([a-z]\)|$)",          # (a) ... (b) ...
    r"(\d+\.\d+)\s*(.+?)(?=\d+\.\d+|$)",             # 3.1 ... 3.2 ...
    r"(?:^|\n)\s*(?:(?:i{1,3}|iv|vi{0,3})\))\s*(.+)",  # i) ii) iii)
]

_RESPONSIBLE_PARTY_KEYWORDS = {
    "buyer": ["purchaser", "buyer", "investor", "买方", "收购方"],
    "seller": ["seller", "vendor", "卖方", "转让方"],
    "both": ["each party", "both parties", "各方", "双方"],
}

_MAC_KEYWORDS = [
    "material adverse change", "material adverse effect",
    "重大不利变化", "重大不利影响", "MAC",
]

async def extract_conditions(input_data: ExtractConditionsInput) -> ExtractConditionsOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    conditions = []

    # 1. 提取编号列表项
    for pattern in _CP_ITEM_PATTERNS:
        for match in re.finditer(pattern, clause_text, re.MULTILINE | re.DOTALL):
            item_text = match.group(0).strip()
            if len(item_text) < 10:
                continue
            conditions.append(ConditionItem(
                condition_id=f"CP-{len(conditions)+1}",
                text=item_text[:500],
                responsible_party=_detect_responsible_party(item_text),
                condition_type=_detect_condition_type(item_text),
                is_waivable=_detect_waivable(item_text),
                context=item_text[:200],
            ))

    has_mac = any(kw.lower() in clause_text.lower() for kw in _MAC_KEYWORDS)
    buyer_count = sum(1 for c in conditions if c.responsible_party == "buyer")
    seller_count = sum(1 for c in conditions if c.responsible_party == "seller")

    return ExtractConditionsOutput(
        clause_id=input_data.clause_id,
        conditions=conditions,
        total_conditions=len(conditions),
        buyer_conditions=buyer_count,
        seller_conditions=seller_count,
        has_material_adverse_change=has_mac,
    )
```

**辅助函数：**
- `_detect_responsible_party`: 基于关键词匹配判断责任方
- `_detect_condition_type`: 基于关键词分类（regulatory: "approval"/"permit"; corporate: "board"/"resolution"; financial: "payment"/"financing"）
- `_detect_waivable`: 查找 "may be waived"/"可豁免" 等表述

**文件路径：** `backend/src/contract_review/skills/sha_spa/extract_conditions.py`

---

#### 3.2.2 `spa_extract_reps_warranties` — 陈述与保证提取

**功能：** 从条款中提取陈述与保证（Representations & Warranties）的结构化清单，标注每项陈述的主体、范围限定词和例外情况。

**为什么本地：** R&W 条款格式高度结构化，通常以 "The Seller represents and warrants that..." 开头，后跟编号列表。

**输入模型：**

```python
class ExtractRepsWarrantiesInput(BaseModel):
    clause_id: str
    document_structure: Any
```

**输出模型：**

```python
class RepWarrantyItem(BaseModel):
    rw_id: str                  # 如 "RW-1"
    text: str                   # 陈述原文
    representing_party: str     # "seller" | "buyer" | "both"
    has_knowledge_qualifier: bool = False   # 是否有"据其所知"限定
    has_materiality_qualifier: bool = False # 是否有"重大性"限定
    has_disclosure_exception: bool = False  # 是否有"除披露函所列"例外
    subject_matter: str = ""    # 主题分类（如 "financial", "legal", "tax", "employment"）

class ExtractRepsWarrantiesOutput(BaseModel):
    clause_id: str
    reps_warranties: List[RepWarrantyItem] = Field(default_factory=list)
    total_items: int = 0
    seller_reps: int = 0
    buyer_reps: int = 0
    knowledge_qualified_count: int = 0   # 有"据其所知"限定的数量
    materiality_qualified_count: int = 0 # 有"重大性"限定的数量
```

**实现逻辑：**

```python
_KNOWLEDGE_QUALIFIERS = [
    "to the best of", "to the knowledge of", "so far as .* aware",
    "据其所知", "就其所知",
]

_MATERIALITY_QUALIFIERS = [
    "material", "in all material respects", "materially",
    "重大", "实质性",
]

_DISCLOSURE_EXCEPTIONS = [
    "except as disclosed", "other than as set forth in the disclosure",
    "除披露函", "除附件所列",
]

_SUBJECT_KEYWORDS = {
    "financial": ["financial statements", "accounts", "balance sheet", "财务报表"],
    "tax": ["tax", "taxation", "税务", "税收"],
    "legal": ["litigation", "proceedings", "disputes", "诉讼", "争议"],
    "employment": ["employee", "labor", "employment", "员工", "劳动"],
    "ip": ["intellectual property", "patent", "trademark", "知识产权"],
    "compliance": ["compliance", "regulatory", "合规", "监管"],
    "title": ["title", "ownership", "encumbrance", "权属", "产权"],
}

async def extract_reps_warranties(input_data: ExtractRepsWarrantiesInput) -> ExtractRepsWarrantiesOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    items = []

    # 提取每个编号项
    for match in re.finditer(r"\(([a-z]|\d+)\)\s*(.+?)(?=\([a-z]|\(\d+\)|$)", clause_text, re.DOTALL):
        text = match.group(0).strip()
        if len(text) < 15:
            continue
        items.append(RepWarrantyItem(
            rw_id=f"RW-{len(items)+1}",
            text=text[:500],
            representing_party=_detect_rep_party(clause_text),
            has_knowledge_qualifier=_has_pattern(text, _KNOWLEDGE_QUALIFIERS),
            has_materiality_qualifier=_has_pattern(text, _MATERIALITY_QUALIFIERS),
            has_disclosure_exception=_has_pattern(text, _DISCLOSURE_EXCEPTIONS),
            subject_matter=_classify_subject(text),
        ))

    return ExtractRepsWarrantiesOutput(
        clause_id=input_data.clause_id,
        reps_warranties=items,
        total_items=len(items),
        seller_reps=sum(1 for i in items if i.representing_party == "seller"),
        buyer_reps=sum(1 for i in items if i.representing_party == "buyer"),
        knowledge_qualified_count=sum(1 for i in items if i.has_knowledge_qualifier),
        materiality_qualified_count=sum(1 for i in items if i.has_materiality_qualifier),
    )
```

**文件路径：** `backend/src/contract_review/skills/sha_spa/extract_reps_warranties.py`

---

#### 3.2.3 `spa_indemnity_analysis` — 赔偿条款分析

**功能：** 从赔偿条款中提取赔偿上限（Cap）、免赔额（Basket/De Minimis）、时效（Survival Period）等关键参数。

**为什么本地：** 赔偿条款的数值参数（金额、百分比、期限）可通过正则提取，结构相对固定。

**输入模型：**

```python
class IndemnityAnalysisInput(BaseModel):
    clause_id: str
    document_structure: Any
```

**输出模型：**

```python
class IndemnityAnalysisOutput(BaseModel):
    clause_id: str
    # 赔偿上限
    has_cap: bool = False
    cap_amount: str = ""           # 如 "USD 10,000,000" 或 "100% of Purchase Price"
    cap_percentage: str = ""       # 如 "15% of the Purchase Price"
    # 免赔额
    has_basket: bool = False
    basket_type: str = ""          # "deductible" (起赔点) | "tipping" (门槛) | "none"
    basket_amount: str = ""        # 如 "USD 500,000"
    # 单项最低金额
    has_de_minimis: bool = False
    de_minimis_amount: str = ""    # 如 "USD 50,000"
    # 时效
    survival_period: str = ""      # 如 "18 months from Closing"
    survival_exceptions: List[str] = Field(default_factory=list)  # 不受时效限制的事项
    # 特殊赔偿
    has_special_indemnity: bool = False  # 是否有特别赔偿条款（如税务赔偿）
    special_indemnity_items: List[str] = Field(default_factory=list)
    # 原文片段
    key_excerpts: Dict[str, str] = Field(default_factory=dict)
```

**实现逻辑：**

```python
_CAP_PATTERNS = [
    r"(?i)(?:aggregate|total|maximum)\s+(?:liability|amount).*?(?:shall\s+not\s+exceed|limited\s+to|capped\s+at)\s+(.+?)(?:\.|;)",
    r"(?i)(?:cap|上限|赔偿限额).*?(\$[\d,]+(?:\.\d+)?|\d+%)",
]

_BASKET_PATTERNS = [
    r"(?i)(?:basket|threshold|deductible|de\s+minimis|免赔额|起赔点).*?(\$[\d,]+(?:\.\d+)?|\d+%)",
]

_SURVIVAL_PATTERNS = [
    r"(?i)(?:surviv\w+|有效期|时效).*?(\d+)\s*(?:months?|years?|个月|年)",
]

_SPECIAL_INDEMNITY_KEYWORDS = [
    "tax indemnity", "environmental indemnity", "specific indemnity",
    "税务赔偿", "环境赔偿", "特别赔偿",
]

async def analyze_indemnity(input_data: IndemnityAnalysisInput) -> IndemnityAnalysisOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    result = IndemnityAnalysisOutput(clause_id=input_data.clause_id)

    # 提取 Cap
    for pattern in _CAP_PATTERNS:
        match = re.search(pattern, clause_text)
        if match:
            result.has_cap = True
            cap_text = match.group(1).strip()
            if "%" in cap_text:
                result.cap_percentage = cap_text
            else:
                result.cap_amount = cap_text
            result.key_excerpts["cap"] = match.group(0)[:200]
            break

    # 提取 Basket
    for pattern in _BASKET_PATTERNS:
        match = re.search(pattern, clause_text)
        if match:
            result.has_basket = True
            result.basket_amount = match.group(1).strip()
            result.basket_type = "deductible" if "deductible" in match.group(0).lower() else "tipping"
            result.key_excerpts["basket"] = match.group(0)[:200]
            break

    # 提取 Survival
    for pattern in _SURVIVAL_PATTERNS:
        match = re.search(pattern, clause_text)
        if match:
            result.survival_period = match.group(0).strip()[:100]
            result.key_excerpts["survival"] = match.group(0)[:200]
            break

    # 特殊赔偿
    for kw in _SPECIAL_INDEMNITY_KEYWORDS:
        if kw.lower() in clause_text.lower():
            result.has_special_indemnity = True
            result.special_indemnity_items.append(kw)

    return result
```

**文件路径：** `backend/src/contract_review/skills/sha_spa/indemnity_analysis.py`

---

### 3.3 SHA/SPA Refly Skills

---

#### 3.3.1 `sha_governance_check` — 治理条款完整性检查

**功能：** 分析 SHA 中的治理结构条款，检查董事会组成、表决机制、保护性条款（如一票否决权、反稀释）是否完整，是否存在对我方不利的安排。

**为什么 Refly：**
- 需要 LLM 理解复杂的治理逻辑（如"重大事项需经持有 2/3 以上表决权的股东同意"）
- 需要跨条款关联分析（治理条款可能分散在多个 Section 中）
- 需要结合行业惯例做合理性判断

**Refly Workflow 设计：**

```
输入: {
  "governance_clauses": [
    { "clause_id": "5.1", "title": "Board Composition", "text": "..." },
    { "clause_id": "5.2", "title": "Board Meetings", "text": "..." },
    { "clause_id": "5.3", "title": "Reserved Matters", "text": "..." },
    ...
  ],
  "our_party_role": "investor",  // "investor" | "founder" | "majority" | "minority"
  "our_shareholding": "30%"
}
步骤:
  1. 分析董事会组成是否与持股比例匹配
  2. 检查重大事项清单是否完整（对标行业标准清单）
  3. 分析表决机制是否对我方有足够保护
  4. 检查信息权、检查权等附属权利
输出: {
  "governance_assessment": {
    "board_composition": { "analysis": "...", "risk_level": "medium" },
    "reserved_matters": { "analysis": "...", "missing_items": [...], "risk_level": "high" },
    "voting_mechanism": { "analysis": "...", "risk_level": "low" },
    "information_rights": { "analysis": "...", "risk_level": "medium" }
  },
  "overall_risk": "medium",
  "recommendations": [...]
}
```

**SkillRegistration：**

```python
SkillRegistration(
    skill_id="sha_governance_check",
    name="治理条款完整性检查",
    description="分析 SHA 治理结构的完整性和公平性",
    backend=SkillBackend.REFLY,
    refly_workflow_id="refly_wf_sha_governance",
)
```

---

#### 3.3.2 `transaction_doc_cross_check` — 交易文件交叉检查

**功能：** 在 SPA/SHA 及其附件（披露函、附表）之间做交叉一致性检查。例如：SPA 中的陈述与保证是否与披露函中的例外事项一致？SHA 中的股权比例是否与 SPA 中的交易对价匹配？

**为什么 Refly：**
- 需要跨文档的语义理解和关联
- 文档量大（SPA + SHA + 多个附件），需要向量检索
- 需要 LLM 推理判断不一致之处

**Refly Workflow 设计：**

```
输入: {
  "primary_clause": { "clause_id": "4.1", "text": "...", "document_type": "SPA" },
  "related_documents": [
    { "document_id": "disclosure_letter", "type": "disclosure" },
    { "document_id": "sha_draft", "type": "SHA" }
  ],
  "check_type": "rw_vs_disclosure"  // 检查类型
}
步骤:
  1. 从 primary_clause 提取关键断言/数据点
  2. 在 related_documents 中检索对应内容
  3. 用 LLM 比对一致性，标注差异
输出: {
  "cross_check_results": [
    {
      "source": "SPA 4.1(a)",
      "target": "Disclosure Letter Item 3",
      "issue": "SPA 声明无未决诉讼，但披露函列出了 2 项进行中的仲裁",
      "severity": "high"
    }
  ],
  "total_issues": 1
}
```

**SkillRegistration：**

```python
SkillRegistration(
    skill_id="transaction_doc_cross_check",
    name="交易文件交叉检查",
    description="跨文档一致性检查（SPA/SHA/披露函）",
    backend=SkillBackend.REFLY,
    refly_workflow_id="refly_wf_transaction_cross_check",
)
```

---

### 3.4 SHA/SPA 领域提示词

```python
SHA_SPA_DOMAIN_INSTRUCTION = """
【SHA/SPA 专项审查指引】
你正在审查一份{doc_type}。请特别关注以下方面：

1. **先决条件**：交割条件是否完整？是否存在难以满足的条件？MAC 条款是否合理？
2. **陈述与保证**：R&W 的范围是否充分？知悉限定（knowledge qualifier）是否过多？
   披露例外是否过宽？
3. **赔偿机制**：赔偿上限（Cap）是否合理？免赔额（Basket）类型和金额？
   时效（Survival）是否足够？是否有特别赔偿条款？
4. **价格调整**：是否有 Completion Accounts / Locked Box 机制？调整公式是否清晰？
5. **竞业限制**：范围（地域、时间、业务）是否合理？
6. **治理结构**（SHA）：董事会组成、重大事项清单、信息权是否充分？
7. **退出机制**（SHA）：Tag-along / Drag-along / Put Option / Call Option 是否公平？

{conditions_context}
{rw_context}
{indemnity_context}
"""

def _build_sha_spa_instruction(state, skill_context, doc_type="SPA"):
    conditions_data = skill_context.get("spa_extract_conditions", {})
    rw_data = skill_context.get("spa_extract_reps_warranties", {})
    indemnity_data = skill_context.get("spa_indemnity_analysis", {})

    conditions_context = ""
    if conditions_data and conditions_data.get("total_conditions", 0) > 0:
        total = conditions_data["total_conditions"]
        mac = "⚠️ 包含 MAC 条件" if conditions_data.get("has_material_adverse_change") else ""
        conditions_context = f"【先决条件分析】共提取 {total} 项先决条件（买方 {conditions_data.get('buyer_conditions',0)} 项，卖方 {conditions_data.get('seller_conditions',0)} 项）。{mac}"

    rw_context = ""
    if rw_data and rw_data.get("total_items", 0) > 0:
        total = rw_data["total_items"]
        kq = rw_data.get("knowledge_qualified_count", 0)
        mq = rw_data.get("materiality_qualified_count", 0)
        rw_context = f"【R&W 分析】共 {total} 项陈述与保证，其中 {kq} 项有知悉限定，{mq} 项有重大性限定。"

    indemnity_context = ""
    if indemnity_data:
        parts = []
        if indemnity_data.get("has_cap"):
            cap = indemnity_data.get("cap_amount") or indemnity_data.get("cap_percentage", "")
            parts.append(f"赔偿上限: {cap}")
        if indemnity_data.get("has_basket"):
            parts.append(f"免赔额: {indemnity_data.get('basket_amount','')} ({indemnity_data.get('basket_type','')})")
        if indemnity_data.get("survival_period"):
            parts.append(f"时效: {indemnity_data['survival_period']}")
        if parts:
            indemnity_context = f"【赔偿条款分析】{'；'.join(parts)}"

    return SHA_SPA_DOMAIN_INSTRUCTION.format(
        doc_type=doc_type,
        conditions_context=conditions_context,
        rw_context=rw_context,
        indemnity_context=indemnity_context,
    )
```

---

### 3.5 SHA/SPA 插件定义

```python
# backend/src/contract_review/plugins/sha_spa.py

SHA_SPA_PARSER_CONFIG = DocumentParserConfig(
    clause_pattern=r"^(?:Article|Section|Clause)\s+\d+",
    chapter_pattern=r"^(?:ARTICLE|PART)\s+[IVXLCDM\d]+",
    definitions_section_id="1",
    max_depth=3,
    structure_type="sha_spa",
)

SHA_SPA_DOMAIN_SKILLS: list[SkillRegistration] = [
    SkillRegistration(
        skill_id="spa_extract_conditions",
        name="先决条件提取",
        description="提取交割先决条件清单",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.sha_spa.extract_conditions.extract_conditions",
    ),
    SkillRegistration(
        skill_id="spa_extract_reps_warranties",
        name="陈述与保证提取",
        description="提取 R&W 结构化清单",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.sha_spa.extract_reps_warranties.extract_reps_warranties",
    ),
    SkillRegistration(
        skill_id="spa_indemnity_analysis",
        name="赔偿条款分析",
        description="提取赔偿上限、免赔额、时效等参数",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.sha_spa.indemnity_analysis.analyze_indemnity",
    ),
    SkillRegistration(
        skill_id="sha_governance_check",
        name="治理条款完整性检查",
        description="分析 SHA 治理结构的完整性和公平性",
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_sha_governance",
    ),
    SkillRegistration(
        skill_id="transaction_doc_cross_check",
        name="交易文件交叉检查",
        description="跨文档一致性检查",
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_transaction_cross_check",
    ),
]

SHA_SPA_CHECKLIST: list[ReviewChecklistItem] = [
    ReviewChecklistItem(
        clause_id="1", clause_name="定义与解释",
        priority="high",
        required_skills=["get_clause_context", "resolve_definition"],
        description="核实关键定义（如 Material Adverse Change、Knowledge 等）",
    ),
    ReviewChecklistItem(
        clause_id="2", clause_name="交易结构与对价",
        priority="critical",
        required_skills=["get_clause_context", "extract_financial_terms"],
        description="核查交易对价、支付方式、价格调整机制",
    ),
    ReviewChecklistItem(
        clause_id="3", clause_name="先决条件",
        priority="critical",
        required_skills=["get_clause_context", "spa_extract_conditions"],
        description="审查交割先决条件的完整性和可控性",
    ),
    ReviewChecklistItem(
        clause_id="4", clause_name="陈述与保证",
        priority="critical",
        required_skills=["get_clause_context", "spa_extract_reps_warranties", "transaction_doc_cross_check"],
        description="审查 R&W 范围、限定词、与披露函的一致性",
    ),
    ReviewChecklistItem(
        clause_id="5", clause_name="交割前承诺",
        priority="high",
        required_skills=["get_clause_context", "cross_reference_check"],
        description="审查签约到交割期间的经营限制",
    ),
    ReviewChecklistItem(
        clause_id="6", clause_name="交割机制",
        priority="high",
        required_skills=["get_clause_context", "extract_financial_terms"],
        description="核查交割流程、交割文件清单",
    ),
    ReviewChecklistItem(
        clause_id="7", clause_name="赔偿条款",
        priority="critical",
        required_skills=["get_clause_context", "spa_indemnity_analysis", "extract_financial_terms"],
        description="审查赔偿上限、免赔额、时效、特别赔偿",
    ),
    ReviewChecklistItem(
        clause_id="8", clause_name="竞业限制与保密",
        priority="high",
        required_skills=["get_clause_context"],
        description="审查竞业限制的范围（地域、时间、业务）和保密义务",
    ),
    ReviewChecklistItem(
        clause_id="9", clause_name="治理结构（SHA）",
        priority="critical",
        required_skills=["get_clause_context", "sha_governance_check"],
        description="审查董事会组成、重大事项、表决机制",
    ),
    ReviewChecklistItem(
        clause_id="10", clause_name="退出机制（SHA）",
        priority="high",
        required_skills=["get_clause_context", "extract_financial_terms"],
        description="审查 Tag/Drag-along、Put/Call Option、IPO 条款",
    ),
    ReviewChecklistItem(
        clause_id="11", clause_name="争议解决",
        priority="high",
        required_skills=["get_clause_context", "compare_with_baseline"],
        description="审查仲裁/诉讼条款、适用法律",
    ),
]

SHA_SPA_PLUGIN = DomainPlugin(
    domain_id="sha_spa",
    name="股权交易文件",
    description="SHA（股东协议）和 SPA（股权转让协议）审查",
    supported_subtypes=["sha", "spa", "share_purchase", "investment"],
    domain_skills=SHA_SPA_DOMAIN_SKILLS,
    review_checklist=SHA_SPA_CHECKLIST,
    document_parser_config=SHA_SPA_PARSER_CONFIG,
    baseline_texts={},  # SHA/SPA 无标准基线文本，依赖行业惯例
)


def register_sha_spa_plugin() -> None:
    from .registry import register_domain_plugin
    register_domain_plugin(SHA_SPA_PLUGIN)
```

**builder.py 集成（新增 SHA/SPA Skills 的输入构造）：**

```python
if skill_id == "spa_extract_conditions":
    from ..skills.sha_spa.extract_conditions import ExtractConditionsInput
    return ExtractConditionsInput(
        clause_id=clause_id,
        document_structure=primary_structure,
    )

if skill_id == "spa_extract_reps_warranties":
    from ..skills.sha_spa.extract_reps_warranties import ExtractRepsWarrantiesInput
    return ExtractRepsWarrantiesInput(
        clause_id=clause_id,
        document_structure=primary_structure,
    )

if skill_id == "spa_indemnity_analysis":
    from ..skills.sha_spa.indemnity_analysis import IndemnityAnalysisInput
    return IndemnityAnalysisInput(
        clause_id=clause_id,
        document_structure=primary_structure,
    )
```

---

### 3.6 SHA/SPA Skills 总览

| Skill ID | 类型 | 后端 | 功能 | 依赖 |
|----------|------|------|------|------|
| `spa_extract_conditions` | 本地 | LOCAL | 先决条件提取 | 无 |
| `spa_extract_reps_warranties` | 本地 | LOCAL | 陈述与保证提取 | 无 |
| `spa_indemnity_analysis` | 本地 | LOCAL | 赔偿条款参数提取 | 无 |
| `sha_governance_check` | 远程 | REFLY | 治理条款完整性检查 | Refly workflow |
| `transaction_doc_cross_check` | 远程 | REFLY | 交易文件交叉检查 | Refly workflow + 多文档 |

---

## 4. Refly Client 升级设计

当前 `refly_client.py` 是 stub，需要升级为真实 HTTP 调用。

### 4.1 升级后的 ReflyClient

```python
# backend/src/contract_review/skills/refly_client.py

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ReflyClientConfig(BaseModel):
    base_url: str = "https://api.refly.ai"
    api_key: str = ""
    timeout: int = 120
    poll_interval: int = 2
    max_poll_attempts: int = 60


class ReflyClientError(Exception):
    """Refly API 调用异常。"""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ReflyClient:
    """Real Refly client with workflow execution and polling."""

    def __init__(self, config: ReflyClientConfig):
        self.config = config
        self._session: httpx.AsyncClient | None = None

    def _get_session(self) -> httpx.AsyncClient:
        if self._session is None or self._session.is_closed:
            self._session = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.config.timeout),
            )
        return self._session

    async def call_workflow(self, workflow_id: str, input_data: Dict[str, Any]) -> str:
        """触发 Refly workflow，返回 task_id。"""
        session = self._get_session()
        try:
            resp = await session.post(
                f"/v1/workflows/{workflow_id}/run",
                json={"input": input_data},
            )
            resp.raise_for_status()
            data = resp.json()
            task_id = data.get("task_id") or data.get("id", "")
            if not task_id:
                raise ReflyClientError("Refly 返回中缺少 task_id")
            logger.info("Refly workflow %s 已触发，task_id=%s", workflow_id, task_id)
            return task_id
        except httpx.HTTPStatusError as exc:
            raise ReflyClientError(
                f"Refly API 错误: {exc.response.status_code} {exc.response.text[:200]}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise ReflyClientError(f"Refly 网络错误: {exc}") from exc

    async def poll_result(
        self, task_id: str, timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """轮询 workflow 执行结果，直到完成或超时。"""
        session = self._get_session()
        max_attempts = (timeout or self.config.timeout) // self.config.poll_interval
        max_attempts = min(max_attempts, self.config.max_poll_attempts)

        for attempt in range(max_attempts):
            try:
                resp = await session.get(f"/v1/tasks/{task_id}")
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "").lower()

                if status == "completed":
                    logger.info("Refly task %s 完成", task_id)
                    return data.get("result", {})
                elif status in ("failed", "error", "cancelled"):
                    error_msg = data.get("error", "未知错误")
                    raise ReflyClientError(f"Refly task 失败: {error_msg}")
                else:
                    # running / pending — 继续等待
                    await asyncio.sleep(self.config.poll_interval)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise ReflyClientError(f"Task {task_id} 不存在", status_code=404) from exc
                raise ReflyClientError(
                    f"轮询错误: {exc.response.status_code}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.RequestError as exc:
                logger.warning("轮询网络错误（第 %d 次）: %s", attempt + 1, exc)
                await asyncio.sleep(self.config.poll_interval)

        raise ReflyClientError(f"Refly task {task_id} 轮询超时（{max_attempts} 次）")

    async def close(self):
        if self._session and not self._session.is_closed:
            await self._session.aclose()
            self._session = None
```

### 4.2 环境变量配置

```python
# config.py 中新增
class ReflySettings(BaseModel):
    enabled: bool = False
    base_url: str = "https://api.refly.ai"
    api_key: str = ""
    timeout: int = 120

# .env 示例
REFLY_ENABLED=true
REFLY_BASE_URL=https://api.refly.ai
REFLY_API_KEY=your_api_key_here
```

### 4.3 Dispatcher 集成

当前 `ReflySkillExecutor` 已经调用 `refly_client.call_workflow()` 和 `poll_result()`，升级 client 后无需修改 dispatcher 代码。只需确保：

1. `_create_dispatcher` 中在有 Refly Skills 时创建 `ReflyClient` 实例
2. 将 `ReflyClient` 传入 `SkillDispatcher` 构造函数
3. 当 `REFLY_ENABLED=false` 时，Refly Skills 注册时跳过（已有此逻辑）

```python
# builder.py 中修改 _create_dispatcher
def _create_dispatcher(domain_id: str | None = None) -> SkillDispatcher | None:
    try:
        settings = get_settings()
        refly_client = None
        if settings.refly.enabled and settings.refly.api_key:
            from ..skills.refly_client import ReflyClient, ReflyClientConfig
            refly_client = ReflyClient(ReflyClientConfig(
                base_url=settings.refly.base_url,
                api_key=settings.refly.api_key,
                timeout=settings.refly.timeout,
            ))

        dispatcher = SkillDispatcher(refly_client=refly_client)
        # ... 注册逻辑不变
```

---

## 5. 实施路线图

### Phase 1：本地 Skills 实现（可立即开始，交给 Codex）

**目标：** 实现所有本地 Skills，不依赖 Refly。

| 任务 | 文件 | 预计工作量 |
|------|------|-----------|
| 创建 `skills/fidic/__init__.py` | 新建 | 极小 |
| 实现 `fidic_merge_gc_pc` | `skills/fidic/merge_gc_pc.py` | 中 |
| 实现 `fidic_calculate_time_bar` | `skills/fidic/time_bar.py` | 中 |
| 填充 FIDIC Silver Book 基线数据 | `skills/fidic/baseline_silver_book.py` | 大（数据录入） |
| 更新 `fidic.py` 引用基线数据 | `plugins/fidic.py` | 小 |
| 创建 `skills/sha_spa/__init__.py` | 新建 | 极小 |
| 实现 `spa_extract_conditions` | `skills/sha_spa/extract_conditions.py` | 中 |
| 实现 `spa_extract_reps_warranties` | `skills/sha_spa/extract_reps_warranties.py` | 中 |
| 实现 `spa_indemnity_analysis` | `skills/sha_spa/indemnity_analysis.py` | 中 |
| 创建 SHA/SPA 插件 | `plugins/sha_spa.py` | 中 |
| 更新 `builder.py` 添加输入构造 | `graph/builder.py` | 小 |
| 添加领域提示词 | `graph/prompts.py` | 中 |
| 单元测试 | `tests/test_fidic_skills.py`, `tests/test_sha_spa_skills.py` | 中 |

**Codex 指令要点：**
- 所有 handler 函数签名必须为 `async def xxx(input_data: XxxInput) -> XxxOutput`
- 使用 `get_clause_text()` 辅助函数从 document_structure 提取文本
- 正则模式需同时支持中英文
- 每个 Skill 模块需包含完整的 Input/Output Pydantic 模型
- 测试用例需覆盖：正常提取、空文本、无匹配、中英文混合

### Phase 2：Refly Client 升级（可与 Phase 1 并行）

**目标：** 将 stub client 升级为真实 HTTP 调用。

| 任务 | 文件 | 说明 |
|------|------|------|
| 升级 ReflyClient | `skills/refly_client.py` | 按 4.1 设计实现 |
| 添加 ReflySettings | `config.py` | 新增配置项 |
| 更新 _create_dispatcher | `graph/builder.py` | 按 4.3 设计修改 |
| 添加测试 | `tests/test_refly_client.py` | mock httpx 测试 |

### Phase 3：Refly Workflows 开发（在 Refly 平台上）

**目标：** 在 Refly 平台上创建 4 个 workflow。

| Workflow | Refly ID | 核心能力 |
|----------|----------|---------|
| FIDIC ER 语义检索 | `refly_wf_fidic_search_er` | RAG（Knowledge Base + 向量检索） |
| FIDIC PC 一致性检查 | `refly_wf_fidic_pc_consistency` | LLM 推理（多条款上下文） |
| SHA 治理条款检查 | `refly_wf_sha_governance` | LLM 推理（行业标准对标） |
| 交易文件交叉检查 | `refly_wf_transaction_cross_check` | RAG + LLM（跨文档检索+比对） |

**开发顺序建议：**
1. 先做 `fidic_search_er`（最简单的 RAG 场景，验证 Refly 集成链路）
2. 再做 `sha_governance_check`（纯 LLM 推理，不需要 RAG）
3. 然后做 `fidic_check_pc_consistency`（需要结构化输入）
4. 最后做 `transaction_doc_cross_check`（最复杂，RAG + 多文档）

### Phase 4：集成测试与前端适配

| 任务 | 说明 |
|------|------|
| E2E 测试 FIDIC 场景 | 上传 FIDIC PC 文档，验证完整审查流程 |
| E2E 测试 SHA/SPA 场景 | 上传 SPA 文档，验证完整审查流程 |
| 前端域选择 | Gen3 审查页面增加域选择（FIDIC / SHA/SPA / 通用） |
| Skills 管理页面 | 已有（SPEC-14），确认新 Skills 正确显示 |

### 依赖关系图

```
Phase 1 (本地 Skills) ──────────────────────┐
    ├── FIDIC 本地 Skills                    │
    ├── SHA/SPA 本地 Skills                  ├──→ Phase 4 (集成测试)
    └── 领域提示词                            │
                                              │
Phase 2 (Refly Client) ──→ Phase 3 (Workflows) ┘
```

Phase 1 和 Phase 2 可以完全并行。Phase 3 依赖 Phase 2 完成。Phase 4 在 Phase 1 + Phase 3 都完成后进行。

---

## 附录：文件清单

### 新建文件

```
backend/src/contract_review/skills/fidic/__init__.py
backend/src/contract_review/skills/fidic/merge_gc_pc.py
backend/src/contract_review/skills/fidic/time_bar.py
backend/src/contract_review/skills/fidic/baseline_silver_book.py
backend/src/contract_review/skills/sha_spa/__init__.py
backend/src/contract_review/skills/sha_spa/extract_conditions.py
backend/src/contract_review/skills/sha_spa/extract_reps_warranties.py
backend/src/contract_review/skills/sha_spa/indemnity_analysis.py
backend/src/contract_review/plugins/sha_spa.py
tests/test_fidic_skills.py
tests/test_sha_spa_skills.py
tests/test_refly_client.py
```

### 修改文件

```
backend/src/contract_review/plugins/fidic.py        — 引用 baseline_texts, 新增 pc_consistency skill
backend/src/contract_review/graph/builder.py         — 新增 _build_skill_input 分支
backend/src/contract_review/graph/prompts.py         — 新增领域提示词
backend/src/contract_review/skills/refly_client.py   — stub → 真实实现
backend/src/contract_review/config.py                — 新增 ReflySettings
```
