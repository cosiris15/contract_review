# SPEC-31：Skills LLM 增强实施计划

> 排除 SHA/SPA 系列。按优先级排序，每个 Skill 独立可交付。

---

## 总体设计原则

1. **混合架构（Hybrid）**：正则先行保底，LLM 补充增强，对齐 SPEC-30 cross_reference_extractor 的成熟模式
2. **输出字段标记来源**：每条结果标注 `source: "regex" | "llm"`，方便下游区分置信度
3. **LLM 失败降级**：LLM 超时/异常时静默回退到纯正则结果，不阻塞流程
4. **输出结构向后兼容**：只增字段，不改已有字段语义，不破坏现有 graph node 消费方
5. **参考实现**：`assess_deviation.py`（LLM 调用 + JSON 解析 + fallback）和 `cross_reference_extractor.py`（regex + LLM 混合 + dedup）

---

## P0-1：extract_financial_terms — 财务条款提取增强

### 现状问题

当前 5 组正则（`_FINANCIAL_PATTERNS`）只能匹配字面量：
- `USD 1,000,000` / `30 days` / `5%` — 能抓到
- `不超过合同总价的百分之五` — 漏
- `the aggregate liability shall not exceed twice the Contract Price` — 漏
- `付款后 30 个工作日内` — 能抓到数字，但丢失"工作日"语义和"付款后"触发条件
- 无法识别隐含的财务关系（如 cap 与 basket 的关联）

### 增强方案

**Phase A — 正则提取（保留现有逻辑）**
- 保持 `_FINANCIAL_PATTERNS` 不变，结果标记 `source="regex"`

**Phase B — LLM 补充提取**
- Prompt 要求 LLM 从条款文本中提取正则遗漏的财务条款
- 将 Phase A 已提取的 terms 作为上下文传入 prompt，避免重复
- LLM 输出 JSON 数组，每项包含 `term_type / value / context / semantic_meaning`
- 新增 `semantic_meaning` 字段：LLM 用一句话解释该财务条款的法律含义（如"责任上限为合同总价的 200%"）

**Phase C — 合并去重**
- regex 结果优先（同一 value 出现在两个来源时保留 regex）
- LLM 补充项追加到结果列表

### 输出模型变更

```python
class FinancialTerm(BaseModel):
    term_type: str          # 不变
    value: str              # 不变
    context: str            # 不变
    source: str = "regex"   # 新增："regex" | "llm"
    semantic_meaning: str = ""  # 新增：LLM 提供的语义解释
```

### LLM Prompt 要点

```
你是合同财务条款分析专家。请从以下条款文本中提取所有财务相关条款。
已由规则引擎提取的条款如下（请勿重复）：{regex_terms}
请重点关注：
1. 用文字表述的金额/比例（如"合同总价的百分之五"、"twice the Contract Price"）
2. 隐含的财务上限/下限/计算公式
3. 付款条件中的时间要求及其触发事件
只返回 JSON 数组，每项：{"term_type", "value", "context", "semantic_meaning"}
```

### 文件改动

| 文件 | 改动 |
|------|------|
| `skills/local/extract_financial_terms.py` | 主逻辑：regex → LLM → merge |
| `tests/test_extract_financial_terms.py` | 新增 LLM mock 测试 |

### 验收条件

1. `"不超过合同总价的百分之五"` 能被提取，`term_type="percentage"`，`source="llm"`
2. `"twice the Contract Price"` 能被提取，带 `semantic_meaning`
3. LLM 不可用时，输出与当前完全一致（纯 regex）
4. 已有正则能抓到的 term 不会被 LLM 重复输出

---

## P0-2：fidic_check_pc_consistency — PC 条款一致性检查增强

### 现状问题

6 条硬编码规则（`CONSISTENCY_RULES`）用关键词匹配做交叉条款一致性判断：
- `check_obligation_vs_liability`：只检查 "shall be responsible for" + "shall not exceed" 这类固定搭配
- `check_time_bar_vs_procedure`：只检查天数 ≤28 + "supporting documents" 等关键词
- 无法发现语义层面的矛盾（如条款 A 说"承包商自行承担一切费用"，条款 B 说"业主应补偿合理费用"）
- `clause_pairs` 硬编码为 FIDIC Silver Book 条款号，非标合同完全失效

### 增强方案

**Phase A — 规则检查（保留现有 6 条规则）**
- 保持 `CONSISTENCY_RULES` 不变，结果标记 `source="rule"`

**Phase B — LLM 语义一致性检查**
- 仅对 Phase A 未发现问题的条款对调用 LLM
- 将 focus clause + 所有 modified clauses 文本打包发给 LLM
- Prompt 要求 LLM 识别：
  - 权责不对等
  - 时间/程序矛盾
  - 定义不一致
  - 隐含冲突
- LLM 输出 JSON 数组，每项包含 `clause_a / clause_b / issue / severity / reasoning`

**Phase C — 合并去重**
- 规则结果优先
- LLM 补充项中，如果 `(clause_a, clause_b, rule_id)` 已被规则覆盖则跳过

### 输出模型变更

```python
class ConsistencyIssue(BaseModel):
    clause_a: str       # 不变
    clause_b: str       # 不变
    issue: str          # 不变
    severity: str       # 不变
    rule_id: str        # 不变（LLM 结果用 "llm_semantic_check"）
    source: str = "rule"    # 新增："rule" | "llm"
    reasoning: str = ""     # 新增：LLM 提供的推理过程
    confidence: float = 1.0 # 新增：规则=1.0，LLM=模型返回值
```

### LLM Prompt 要点

```
你是 FIDIC 合同一致性审查专家。
以下是一组已修改的 PC 条款，请分析焦点条款与其他条款之间是否存在一致性问题。
焦点条款：{focus_clause_id}: {focus_text}
其他已修改条款：
{other_clauses}
已由规则引擎发现的问题（请勿重复）：{rule_issues}
请重点关注：权责不对等、时间/程序矛盾、定义不一致、隐含冲突。
只返回 JSON 数组，每项：{"clause_a", "clause_b", "issue", "severity", "reasoning", "confidence"}
severity 仅可取 high|medium|low。
```

### 关键设计决策

- LLM 输入限制：最多传入 8 条 modified clauses（按与 focus clause 的关联度排序），避免 token 爆炸
- 非 FIDIC 合同：规则层 `clause_pairs` 不匹配时全部跳过，但 LLM 层不受条款号限制，天然支持非标合同

### 文件改动

| 文件 | 改动 |
|------|------|
| `skills/fidic/check_pc_consistency.py` | 主逻辑：rule → LLM → merge |
| `tests/test_check_pc_consistency.py` | 新增 LLM mock 测试 |

### 验收条件

1. 现有 6 条规则行为不变
2. LLM 能发现规则遗漏的语义矛盾（如义务扩大但未提及保险调整）
3. LLM 不可用时输出与当前完全一致
4. 非 FIDIC 合同（无标准条款号）时 LLM 仍能工作

---

## P1-1：fidic_calculate_time_bar — 时限分析增强

### 现状问题

- 5 组正则能抓 `within 28 days`、`30天内`，但：
  - 触发条件提取（`_extract_trigger`）只用简单正则，复杂表述如 "after the Contractor became aware or should have become aware of the event" 会被截断或漏掉
  - 后果提取（`_extract_consequence`）只匹配 "otherwise" / "failing which"，遗漏 "the Contractor shall have no entitlement" 等变体
  - 无法识别文字表述的时限（如"一个月内"、"a reasonable period"）
  - 无法判断时限的严格程度（是硬性 time bar 还是建议性期限）

### 增强方案

**Phase A — 正则提取（保留现有逻辑）**
- 保持 `_TIME_BAR_PATTERNS` + `_STRICT_KEYWORDS` 不变

**Phase B — LLM 增强**
- 对每个 regex 提取到的 TimeBarItem，将其 context 发给 LLM 做精细化分析
- LLM 补充/修正：`trigger_event`、`action_required`、`consequence` 三个字段
- LLM 额外输出：`strictness_level`（hard_bar / soft_bar / advisory）和 `risk_assessment`
- 同时让 LLM 识别正则遗漏的时限要求

**Phase C — 合并**
- regex 提取的 item 保留，LLM 补充字段覆盖空值
- LLM 新发现的 item 追加，标记 `source="llm"`

### 输出模型变更

```python
class TimeBarItem(BaseModel):
    trigger_event: str = ""      # 不变，LLM 可补充
    deadline_days: int           # 不变
    deadline_text: str           # 不变
    action_required: str = ""    # 不变，LLM 可补充
    consequence: str = ""        # 不变，LLM 可补充
    context: str = ""            # 不变
    source: str = "regex"        # 新增
    strictness_level: str = ""   # 新增："hard_bar" | "soft_bar" | "advisory"
    risk_assessment: str = ""    # 新增：LLM 风险评估
```

### 文件改动

| 文件 | 改动 |
|------|------|
| `skills/fidic/time_bar.py` | 主逻辑：regex → LLM enrich → LLM discover → merge |
| `tests/test_time_bar.py` | 新增 LLM mock 测试 |

### 验收条件

1. 现有正则提取行为不变
2. "after the Contractor became aware or should have become aware" 能被完整提取为 trigger_event
3. 每个 time bar 有 strictness_level 分类
4. LLM 不可用时输出与当前完全一致

---

## P1-2：compare_with_baseline — 基线对比语义增强

### 现状问题

- `difflib.unified_diff` 只做文本 diff，输出"删除内容 / 新增内容"
- 无法判断改动的法律含义：
  - `shall` → `may`：义务变权利，实质性修改
  - `28 days` → `14 days`：时限缩短，风险升高
  - 段落重排但语义不变：误报为大量修改
- `differences_summary` 只是文本片段拼接，对下游 `assess_deviation` 的输入质量有限

### 增强方案

**Phase A — 文本 diff（保留现有逻辑）**
- 保持 `_compute_diff_summary` 不变

**Phase B — LLM 语义分析**
- 仅当 `is_identical == False` 时调用
- 将 baseline_text + current_text + diff_summary 发给 LLM
- LLM 输出结构化分析：

```json
{
  "change_significance": "material|minor|cosmetic",
  "key_changes": [
    {
      "change_type": "obligation_weakened|obligation_strengthened|time_changed|amount_changed|scope_changed|wording_only",
      "description": "将 shall 改为 may，承包商义务变为可选",
      "risk_impact": "high|medium|low|none"
    }
  ],
  "overall_risk_delta": "increased|decreased|neutral",
  "summary": "一句话总结"
}
```

### 输出模型变更

```python
class CompareWithBaselineOutput(BaseModel):
    clause_id: str                  # 不变
    has_baseline: bool = False      # 不变
    current_text: str = ""          # 不变
    baseline_text: str = ""         # 不变
    is_identical: bool = False      # 不变
    differences_summary: str = ""   # 不变（文本 diff）
    # 新增
    change_significance: str = ""   # "material" | "minor" | "cosmetic"
    key_changes: List[dict] = []    # LLM 结构化变更列表
    overall_risk_delta: str = ""    # "increased" | "decreased" | "neutral"
    semantic_summary: str = ""      # LLM 一句话总结
    llm_used: bool = False
```

### 文件改动

| 文件 | 改动 |
|------|------|
| `skills/local/compare_with_baseline.py` | 主逻辑：diff → LLM semantic → merge |
| `tests/test_compare_with_baseline.py` | 新增 LLM mock 测试 |

### 验收条件

1. `shall` → `may` 的修改被标记为 `change_significance="material"`，`change_type="obligation_weakened"`
2. 纯格式调整（空格/换行）被标记为 `cosmetic`
3. LLM 不可用时，新增字段全部为空/默认值，`differences_summary` 正常输出
4. `semantic_summary` 能被下游 `assess_deviation` 直接消费

---

## P2-1：load_review_criteria — 审查标准适用性判断

### 现状问题

- 精确匹配 → embedding 语义回退，已经是合理的两级方案
- 但语义匹配只看 review_point 文本相似度，不判断"这条标准是否真的适用于当前条款"
- 例：条款讲"付款期限"，标准讲"付款方式"，embedding 相似度可能 >0.5 但实际不适用

### 增强方案

**Phase A — 保留现有精确匹配 + embedding 回退**

**Phase B — LLM 适用性过滤（仅对 semantic match 结果）**
- 将 semantic match 的 top-5 候选 + 条款文本发给 LLM
- LLM 判断每条标准是否真正适用，输出 `applicable: true/false` + `reason`
- 过滤掉 `applicable=false` 的候选

### 输出模型变更

```python
class MatchedCriterion(BaseModel):
    # 所有现有字段不变
    applicable: bool = True         # 新增：LLM 适用性判断
    applicability_reason: str = ""  # 新增：LLM 判断理由
```

### 文件改动

| 文件 | 改动 |
|------|------|
| `skills/local/load_review_criteria.py` | semantic match 后增加 LLM 过滤 |
| `tests/test_load_review_criteria.py` | 新增 LLM mock 测试 |

### 验收条件

1. 精确匹配结果不经过 LLM 过滤（已确定适用）
2. 语义匹配的误匹配率降低（LLM 过滤掉不适用的标准）
3. LLM 不可用时行为与当前完全一致

---

## 实施顺序建议

```
Week 1:  P0-1 extract_financial_terms（独立，无依赖）
Week 1:  P0-2 fidic_check_pc_consistency（独立，无依赖）
Week 2:  P1-2 compare_with_baseline（优先于 P1-1，因为其输出直接喂给 assess_deviation）
Week 2:  P1-1 fidic_calculate_time_bar（独立）
Week 3:  P2-1 load_review_criteria（依赖 embedding 基础设施已稳定）
```

每个 Skill 独立可交付、独立可测试、独立可回滚。失败不影响其他 Skill。

---

## 通用实施模式（参考模板）

每个 Skill 的 LLM 增强遵循相同的代码结构：

```python
async def skill_handler(input_data: SkillInput) -> SkillOutput:
    # Phase A: 规则/正则提取
    regex_results = _regex_extract(input_data)

    # Phase B: LLM 补充
    llm_client = get_llm_client()
    llm_results = []
    if llm_client and input_data.text.strip():
        try:
            response = await llm_client.chat(
                _build_prompt(input_data, regex_results),
                max_output_tokens=1200,
            )
            llm_results = _parse_llm_response(response)
        except Exception:
            logger.warning("LLM 调用失败，降级规则", exc_info=True)

    # Phase C: 合并去重（regex 优先）
    return _merge_results(regex_results, llm_results)
```

---

## 文件总览

| 文件 | SPEC | 类型 | 预估行数 |
|------|------|------|---------|
| `skills/local/extract_financial_terms.py` | P0-1 | 修改 | +60 |
| `skills/fidic/check_pc_consistency.py` | P0-2 | 修改 | +80 |
| `skills/fidic/time_bar.py` | P1-1 | 修改 | +70 |
| `skills/local/compare_with_baseline.py` | P1-2 | 修改 | +60 |
| `skills/local/load_review_criteria.py` | P2-1 | 修改 | +40 |
| `tests/test_extract_financial_terms.py` | P0-1 | 新增 | ~60 |
| `tests/test_check_pc_consistency.py` | P0-2 | 新增 | ~70 |
| `tests/test_time_bar.py` | P1-1 | 新增 | ~60 |
| `tests/test_compare_with_baseline.py` | P1-2 | 新增 | ~60 |
| `tests/test_load_review_criteria.py` | P2-1 | 新增 | ~50 |

总计：~550 行改动/新增，10 个文件
