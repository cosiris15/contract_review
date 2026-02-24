# SPEC-31a：extract_financial_terms LLM 增强

> 优先级：P0 | 独立交付 | 预估改动 ~120 行

---

## 1. 背景与问题

当前 `extract_financial_terms` 使用 5 组正则（`_FINANCIAL_PATTERNS`）提取财务条款：

```python
_FINANCIAL_PATTERNS = [
    (r"(\d+(?:\.\d+)?)\s*[%％]", "percentage"),
    (r"(?:USD|EUR|CNY|RMB|GBP|\$|€|£|¥)\s*[\d,]+(?:\.\d+)?", "amount"),
    (r"[\d,]+(?:\.\d+)?\s*(?:万元|亿元|元|美元|欧元|英镑)", "amount"),
    (r"\d+\s*(?:天|日|个月|月|年|days?|months?|years?|weeks?|周)", "duration"),
    (r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?", "date"),
]
```

能抓到的：`USD 1,000,000`、`30 days`、`5%`、`2024年6月30日`

抓不到的：
- `不超过合同总价的百分之五` — 文字表述的比例
- `the aggregate liability shall not exceed twice the Contract Price` — 倍数关系
- `合同价格的 200%` — 能抓到 `200%` 但丢失"合同价格"的关联
- `a reasonable period` — 非数字时限
- 隐含的 cap/basket/de minimis 关系

## 2. 设计原则

1. 正则先行保底，LLM 补充增强（对齐 SPEC-30 混合模式）
2. LLM 失败静默降级，不阻塞流程
3. 输出向后兼容：只增字段，不改已有字段语义
4. regex 结果优先：同一 value 两个来源都有时保留 regex

## 3. 数据模型变更

### FinancialTerm 增强

```python
class FinancialTerm(BaseModel):
    term_type: str              # 不变：percentage / amount / duration / date
    value: str                  # 不变：提取的原始值
    context: str                # 不变：前后 30 字符上下文
    source: str = "regex"       # 新增："regex" | "llm"
    semantic_meaning: str = ""  # 新增：LLM 提供的语义解释（如"责任上限为合同总价的200%"）
```

### ExtractFinancialTermsOutput 增强

```python
class ExtractFinancialTermsOutput(BaseModel):
    clause_id: str              # 不变
    terms: List[FinancialTerm]  # 不变
    total_terms: int = 0        # 不变
    llm_used: bool = False      # 新增
```

## 4. 实现方案

### 4.1 主函数流程

```
extract_financial_terms(input_data)
  ├─ Phase A: _regex_extract(clause_text)          → List[FinancialTerm], source="regex"
  ├─ Phase B: _llm_extract(clause_text, regex_terms) → List[FinancialTerm], source="llm"
  │   ├─ get_llm_client() → None? 跳过
  │   ├─ _build_prompt(clause_text, regex_terms)
  │   ├─ llm_client.chat(messages, max_output_tokens=800)
  │   └─ _parse_llm_response(response) → List[FinancialTerm]
  └─ Phase C: _merge_results(regex_terms, llm_terms) → 去重合并
```

### 4.2 Phase A — 正则提取

保持现有 `_FINANCIAL_PATTERNS` 逻辑完全不变，仅为每个结果设置 `source="regex"`。

### 4.3 Phase B — LLM 补充提取

#### LLM Prompt

```python
SYSTEM_PROMPT = (
    "你是合同财务条款分析专家。请从条款文本中提取所有财务相关条款。"
    "已由规则引擎提取的条款会提供给你，请勿重复这些条款。"
    "请重点关注：\n"
    "1. 用文字表述的金额或比例（如'合同总价的百分之五'、'twice the Contract Price'）\n"
    "2. 隐含的财务上限/下限/计算公式\n"
    "3. 非数字时限表述（如'a reasonable period'、'合理期限'）\n"
    "4. 金额与条件的关联关系\n"
    "只返回 JSON 数组，不得输出额外文本。"
    "每项字段：term_type（percentage/amount/duration/date/formula）, value, context, semantic_meaning"
)
```

#### 输入构造

```python
def _build_prompt(clause_text: str, regex_terms: List[FinancialTerm]) -> List[dict]:
    existing = "\n".join(f"- [{t.term_type}] {t.value}" for t in regex_terms) or "（无）"
    user_msg = (
        f"条款文本：\n{clause_text[:3000]}\n\n"
        f"已提取的财务条款（请勿重复）：\n{existing}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
```

#### 响应解析

复用 `assess_deviation.py` 中的 `_extract_json` 模式：
- 尝试直接 JSON parse
- 尝试提取 ```json``` 代码块
- 尝试提取 `[...]` 括号内容
- 全部失败返回空列表

### 4.4 Phase C — 合并去重

```python
def _merge_results(
    regex_terms: List[FinancialTerm],
    llm_terms: List[FinancialTerm],
) -> List[FinancialTerm]:
    # 用 regex 已提取的 value 集合做去重
    seen_values = {t.value.strip() for t in regex_terms}
    merged = list(regex_terms)
    for lt in llm_terms:
        if lt.value.strip() not in seen_values:
            merged.append(lt)
            seen_values.add(lt.value.strip())
    return merged
```

## 5. 文件改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/src/contract_review/skills/local/extract_financial_terms.py` | 修改 | 主逻辑：拆分 regex → LLM → merge |
| `tests/test_extract_financial_terms_llm.py` | 新增 | LLM mock 测试 |

## 6. 测试用例

### 6.1 test_regex_only_when_llm_unavailable
- mock `get_llm_client` 返回 None
- 输入含 `USD 1,000,000` 的条款
- 验证输出与当前行为一致，`llm_used=False`

### 6.2 test_llm_supplements_regex
- mock LLM 返回 `[{"term_type":"percentage","value":"合同总价的百分之五","context":"...","semantic_meaning":"责任上限为合同总价的5%"}]`
- 输入含 `5%` 和 `不超过合同总价的百分之五` 的条款
- 验证 regex 抓到 `5%`（source=regex），LLM 补充 `合同总价的百分之五`（source=llm）

### 6.3 test_llm_dedup_with_regex
- mock LLM 返回包含 regex 已提取的 `USD 1,000,000`
- 验证不会重复出现

### 6.4 test_llm_failure_fallback
- mock LLM 抛出异常
- 验证输出与纯 regex 一致，`llm_used=False`

### 6.5 test_llm_returns_semantic_meaning
- mock LLM 返回含 `semantic_meaning` 的结果
- 验证 `semantic_meaning` 字段正确传递

### 6.6 test_empty_clause_text
- 输入空文本
- 验证返回空列表，不调用 LLM

## 7. 验收条件

1. ✅ `"不超过合同总价的百分之五"` 能被提取，`term_type="percentage"`，`source="llm"`
2. ✅ `"twice the Contract Price"` 能被提取，带 `semantic_meaning`
3. ✅ LLM 不可用时，输出与当前完全一致（纯 regex），`llm_used=False`
4. ✅ regex 已抓到的 term 不会被 LLM 重复输出
5. ✅ 所有现有测试继续通过
6. ✅ 新增测试全部通过
