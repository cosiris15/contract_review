# SPEC-31e：load_review_criteria LLM 适用性过滤

> 优先级：P2 | 独立交付 | 预估改动 ~90 行

---

## 1. 背景与问题

当前 `load_review_criteria` 采用两级匹配：
1. 精确匹配：按 clause_ref 归一化后比对（如 "4.1" == "Clause 4.1"）
2. 语义回退：用 Dashscope embedding 计算条款文本与 review_point 的 cosine 相似度，取 top-3（阈值 0.5）

问题在语义回退阶段：
- embedding 只看文本相似度，不判断"这条标准是否真的适用于当前条款"
- 例：条款讲"付款期限 30 天"，标准讲"付款方式应支持电汇"，embedding 相似度可能 >0.5（都含"付款"），但实际不适用
- 例：条款讲"保险责任"，标准讲"保险费用承担"，语义相关但审查角度不同
- 误匹配的标准会传给下游 `assess_deviation`，导致 LLM 做无意义的偏离评估，浪费 token 且产生噪音

## 2. 设计原则

1. 精确匹配结果不经过 LLM 过滤（已确定适用）
2. LLM 过滤仅作用于 semantic match 的候选
3. 扩大 semantic 候选范围（top-5），LLM 过滤后再截取 top-3
4. LLM 失败时行为与当前完全一致（保留所有 semantic 候选）

## 3. 数据模型变更

### MatchedCriterion 增强

```python
class MatchedCriterion(BaseModel):
    criterion_id: str       # 不变
    clause_ref: str         # 不变
    review_point: str       # 不变
    risk_level: str         # 不变
    baseline_text: str      # 不变
    suggested_action: str   # 不变
    match_type: str         # 不变："exact" | "semantic"
    match_score: float = 1.0    # 不变
    applicable: bool = True     # 新增：LLM 适用性判断（exact 始终 True）
    applicability_reason: str = ""  # 新增：LLM 判断理由
```

### LoadReviewCriteriaOutput 增强

```python
class LoadReviewCriteriaOutput(BaseModel):
    clause_id: str                          # 不变
    matched_criteria: List[MatchedCriterion] # 不变
    total_matched: int = 0                  # 不变
    has_criteria: bool = False              # 不变
    llm_filtered: bool = False              # 新增
```

## 4. 实现方案

### 4.1 主函数流程变更

```
load_review_criteria(input_data)
  ├─ 现有逻辑：精确匹配 → 有结果直接返回（不变）
  ├─ 现有逻辑：embedding 语义回退
  │   └─ 变更：取 top-5（原 top-3），阈值仍为 0.5
  ├─ Phase B: _llm_filter_applicability(clause_text, semantic_candidates)
  │   ├─ get_llm_client() → None? 跳过，保留全部候选
  │   ├─ _build_filter_prompt(clause_text, candidates)
  │   ├─ llm_client.chat(messages, max_output_tokens=600)
  │   └─ _parse_filter_response(response) → dict[criterion_id, (applicable, reason)]
  ├─ 标记每个候选的 applicable / applicability_reason
  └─ 过滤：只保留 applicable=True 的，最多 3 条
```

### 4.2 语义回退变更

仅修改一处：将 `if len(semantic_matches) >= 3: break` 改为 `>= 5`，扩大候选池供 LLM 过滤。

### 4.3 LLM Prompt

```python
FILTER_SYSTEM_PROMPT = (
    "你是合同审查标准匹配专家。请判断以下审查标准是否适用于当前条款。\n"
    "适用 = 该标准的审查角度与条款内容直接相关，可以用来评估条款的合规性或风险。\n"
    "不适用 = 虽然文字相似，但审查角度与条款内容无关。\n"
    "只返回 JSON 数组，不得输出额外文本。\n"
    "每项：{\"criterion_id\": \"...\", \"applicable\": true/false, \"reason\": \"一句话理由\"}"
)
```

### 4.4 输入构造

```python
def _build_filter_prompt(
    clause_text: str,
    candidates: List[MatchedCriterion],
) -> List[dict]:
    criteria_text = "\n".join(
        f"- criterion_id={c.criterion_id}, review_point={c.review_point}"
        for c in candidates
    )
    user_msg = (
        f"条款文本：\n{clause_text[:2000]}\n\n"
        f"候选审查标准：\n{criteria_text}"
    )
    return [
        {"role": "system", "content": FILTER_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
```

### 4.5 响应解析

- 复用 `_extract_json` 模式解析 JSON 数组
- 按 `criterion_id` 建立映射
- 对每个候选标记 `applicable` 和 `applicability_reason`
- 无效/缺失的 criterion_id 默认 `applicable=True`（保守策略）

### 4.6 过滤与截取

```python
# 标记后过滤
filtered = [c for c in semantic_candidates if c.applicable]
# 截取 top-3（按 match_score 降序）
final = sorted(filtered, key=lambda c: c.match_score, reverse=True)[:3]
```

## 5. 文件改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/src/contract_review/skills/local/load_review_criteria.py` | 修改 | semantic 候选扩到 5，增加 LLM 过滤层 |
| `tests/test_load_review_criteria_llm.py` | 新增 | LLM mock 测试 |

## 6. 测试用例

### 6.1 test_exact_match_bypasses_llm
- 输入 clause_id 精确匹配到标准
- 验证不调用 LLM，`applicable=True`，`llm_filtered=False`

### 6.2 test_llm_filters_inapplicable
- 5 条 semantic 候选，mock LLM 标记其中 2 条 `applicable=false`
- 验证最终结果只含 3 条 applicable=True 的标准

### 6.3 test_llm_reason_populated
- mock LLM 返回 `reason="该标准针对付款方式，与本条款的付款期限无关"`
- 验证 `applicability_reason` 正确填充

### 6.4 test_llm_unavailable_keeps_all
- mock `get_llm_client` 返回 None
- 验证行为与当前一致（保留 top-3 semantic），`llm_filtered=False`

### 6.5 test_llm_failure_keeps_all
- mock LLM 抛出异常
- 验证与 test_llm_unavailable_keeps_all 相同

### 6.6 test_all_filtered_out
- mock LLM 标记全部 5 条为 `applicable=false`
- 验证返回空列表，`total_matched=0`

### 6.7 test_missing_criterion_id_defaults_true
- mock LLM 返回的 JSON 中缺少某个 criterion_id
- 验证该候选默认 `applicable=True`（保守策略）

## 7. 验收条件

1. ✅ 精确匹配结果不经过 LLM 过滤
2. ✅ 语义匹配的误匹配率降低（LLM 过滤掉不适用的标准）
3. ✅ LLM 不可用时行为与当前完全一致
4. ✅ `applicability_reason` 可被人工审查参考
5. ✅ 所有现有测试继续通过
6. ✅ 新增测试全部通过
