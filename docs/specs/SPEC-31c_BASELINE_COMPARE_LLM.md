# SPEC-31c：compare_with_baseline 语义分析增强

> 优先级：P1 | 独立交付 | 预估改动 ~120 行

---

## 1. 背景与问题

当前 `compare_with_baseline` 使用 `difflib.unified_diff` 做文本对比，输出 `differences_summary`：

```python
def _compute_diff_summary(baseline: str, current: str) -> str:
    # unified_diff → 提取 added/removed 行 → 拼接
    # 输出示例："删除内容：shall; 新增内容：may"
```

能做到的：逐行文本 diff，列出新增/删除的文本片段

做不到的：
- `shall` → `may`：difflib 只报"删了 shall、加了 may"，无法判断这是义务变权利的实质性修改
- `28 days` → `14 days`：只报数字变了，无法判断时限缩短的风险含义
- 段落重排但语义不变：误报为大量修改
- 无法区分 cosmetic（格式调整）、minor（措辞微调）、material（实质性修改）
- `differences_summary` 是纯文本拼接，下游 `assess_deviation` 无法结构化消费

## 2. 设计原则

1. difflib diff 保留作为基础层（零成本、确定性）
2. LLM 仅在 `is_identical == False` 时调用（相同文本不浪费 token）
3. LLM 输出结构化分析，直接可被下游 `assess_deviation` 消费
4. `differences_summary` 字段保持不变（文本 diff），新增字段承载语义分析
5. LLM 失败时新增字段全部为空/默认值

## 3. 数据模型变更

### KeyChange 新增模型

```python
class KeyChange(BaseModel):
    change_type: str = ""
    # 可选值：obligation_weakened / obligation_strengthened /
    #         time_changed / amount_changed / scope_changed /
    #         party_changed / condition_added / condition_removed /
    #         wording_only
    description: str = ""       # 一句话描述变更内容
    risk_impact: str = "none"   # high / medium / low / none
```

### CompareWithBaselineOutput 增强

```python
class CompareWithBaselineOutput(BaseModel):
    clause_id: str                  # 不变
    has_baseline: bool = False      # 不变
    current_text: str = ""          # 不变
    baseline_text: str = ""         # 不变
    is_identical: bool = False      # 不变
    differences_summary: str = ""   # 不变（文本 diff）
    # 新增
    change_significance: str = ""   # "material" | "minor" | "cosmetic" | ""
    key_changes: List[KeyChange] = Field(default_factory=list)
    overall_risk_delta: str = ""    # "increased" | "decreased" | "neutral" | ""
    semantic_summary: str = ""      # LLM 一句话总结
    llm_used: bool = False
```

## 4. 实现方案

### 4.1 主函数流程

```
compare_with_baseline(input_data)
  ├─ 现有逻辑：get_clause_text → normalize → diff → differences_summary
  ├─ 如果 is_identical == True → 直接返回（不调 LLM）
  ├─ Phase B: _llm_semantic_analysis(baseline, current, diff_summary)
  │   ├─ get_llm_client() → None? 跳过
  │   ├─ _build_compare_prompt(baseline, current, diff_summary)
  │   ├─ llm_client.chat(messages, max_output_tokens=1000)
  │   └─ _parse_compare_response(response) → dict
  └─ 将 LLM 结果填入输出模型的新增字段
```

### 4.2 LLM Prompt

```python
COMPARE_SYSTEM_PROMPT = (
    "你是合同条款变更分析专家。请对比基线文本和当前文本，分析修改的法律含义。\n"
    "你必须只输出 JSON 对象，不得输出额外文本。\n"
    "字段说明：\n"
    "- change_significance: material（实质性修改）| minor（措辞微调，不影响权责）| cosmetic（格式/标点调整）\n"
    "- key_changes: 数组，每项包含：\n"
    "  - change_type: obligation_weakened|obligation_strengthened|time_changed|amount_changed|"
    "scope_changed|party_changed|condition_added|condition_removed|wording_only\n"
    "  - description: 一句话描述\n"
    "  - risk_impact: high|medium|low|none\n"
    "- overall_risk_delta: increased|decreased|neutral\n"
    "- summary: 一句话总结所有变更的综合影响"
)
```

### 4.3 输入构造

```python
def _build_compare_prompt(
    baseline: str, current: str, diff_summary: str
) -> List[dict]:
    user_msg = (
        f"基线文本：\n{baseline[:2000]}\n\n"
        f"当前文本：\n{current[:2000]}\n\n"
        f"文本差异摘要：\n{diff_summary}"
    )
    return [
        {"role": "system", "content": COMPARE_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
```

### 4.4 响应解析

```python
def _parse_compare_response(raw: str) -> dict:
    # 复用 _extract_json 模式，但期望单个 JSON 对象（非数组）
    # 尝试：直接 parse → ```json``` 块 → {...} 提取
    # 校验 change_significance ∈ {material, minor, cosmetic}
    # 校验 overall_risk_delta ∈ {increased, decreased, neutral}
    # key_changes 中每项校验 change_type 和 risk_impact
    # 无效值用默认值替代
```

### 4.5 与下游 assess_deviation 的衔接

`assess_deviation` 的 `prepare_input` 当前从 state 中取 `baseline_text`，独立调用 LLM 做偏离评估。SPEC-31c 增强后：
- `compare_with_baseline` 的 `semantic_summary` 和 `key_changes` 可作为 `assess_deviation` 的额外上下文
- 但本 SPEC 不修改 `assess_deviation`，仅确保输出结构可被消费
- 后续可在 graph flow 中将 compare 结果注入 assess_deviation 的 state

## 5. 文件改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/src/contract_review/skills/local/compare_with_baseline.py` | 修改 | 新增 LLM 语义分析层 |
| `tests/test_compare_with_baseline_llm.py` | 新增 | LLM mock 测试 |

## 6. 测试用例

### 6.1 test_identical_text_no_llm
- baseline == current（归一化后相同）
- 验证 `is_identical=True`，不调用 LLM，新增字段全部为空

### 6.2 test_shall_to_may_material
- baseline: `"The Contractor shall complete the works within 28 days"`
- current: `"The Contractor may complete the works within 28 days"`
- mock LLM 返回 `change_significance="material"`，`change_type="obligation_weakened"`
- 验证 `change_significance="material"`，`overall_risk_delta="increased"`

### 6.3 test_cosmetic_change
- baseline 和 current 仅标点/空格不同
- mock LLM 返回 `change_significance="cosmetic"`
- 验证 `key_changes` 中 `risk_impact="none"`

### 6.4 test_time_reduction
- baseline: `"within 28 days"` → current: `"within 14 days"`
- mock LLM 返回 `change_type="time_changed"`，`risk_impact="high"`
- 验证结构化输出正确

### 6.5 test_llm_unavailable_fallback
- mock `get_llm_client` 返回 None
- 验证 `differences_summary` 正常输出，新增字段全部为空，`llm_used=False`

### 6.6 test_llm_failure_fallback
- mock LLM 抛出异常
- 验证与 test_llm_unavailable_fallback 相同行为

### 6.7 test_no_baseline
- `baseline_text` 为空
- 验证 `has_baseline=False`，不调用 LLM

### 6.8 test_semantic_summary_populated
- mock LLM 返回含 `summary` 的结果
- 验证 `semantic_summary` 字段正确填充

## 7. 验收条件

1. ✅ `shall` → `may` 被标记为 `change_significance="material"`，`change_type="obligation_weakened"`
2. ✅ 纯格式调整被标记为 `cosmetic`
3. ✅ `differences_summary`（文本 diff）行为完全不变
4. ✅ LLM 不可用时新增字段全部为空/默认值
5. ✅ `semantic_summary` 可被下游直接消费
6. ✅ 所有现有测试继续通过
7. ✅ 新增测试全部通过
