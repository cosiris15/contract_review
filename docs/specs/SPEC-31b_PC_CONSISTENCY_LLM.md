# SPEC-31b：fidic_check_pc_consistency LLM 增强

> 优先级：P0 | 独立交付 | 预估改动 ~150 行

---

## 1. 背景与问题

当前 `check_pc_consistency` 使用 6 条硬编码规则（`CONSISTENCY_RULES`）做交叉条款一致性检查：

| rule_id | clause_pairs | 检查方式 |
|---------|-------------|---------|
| obligation_vs_liability_cap | (4.1,17.6) (4.12,17.6) | 关键词："shall be responsible for" vs "shall not exceed" |
| time_bar_vs_procedure | (20.1,20.2) | 天数≤28 + "supporting documents"等关键词 |
| payment_vs_schedule | (8.2,14.7) (8.2,14.1) | "accelerate"类关键词 vs "monthly"/"56 days"类关键词 |
| risk_transfer_vs_insurance | (4.1,18.1) (4.12,18.1) | "contractor bears all risks" vs 无"insurance"关键词 |
| rights_vs_obligations | (20.1,4.1) | "not entitled"/"waived" vs "shall"/"must" |
| cross_reference_stale | 无固定对 | 引用条款号但无"amended"/"revised"标记 |

核心问题：
- `clause_pairs` 硬编码为 FIDIC Silver Book 条款号，非标合同完全失效
- 关键词匹配只能覆盖最表面的冲突，换个说法就漏
- 无法发现语义层面的矛盾（如条款 A 说"承包商自行承担一切费用"，条款 B 说"业主应补偿合理费用"）
- 6 条规则只覆盖 6 种冲突模式，实际合同中的不一致远不止这些

## 2. 设计原则

1. 保留现有 6 条规则作为快速检查层（零延迟、零成本）
2. LLM 仅对规则未覆盖的条款对做补充检查
3. LLM 输入限制：最多 8 条 modified clauses，避免 token 爆炸
4. 非 FIDIC 合同：规则层 clause_pairs 不匹配全部跳过，但 LLM 层不受条款号限制
5. LLM 失败静默降级

## 3. 数据模型变更

### ConsistencyIssue 增强

```python
class ConsistencyIssue(BaseModel):
    clause_a: str           # 不变
    clause_b: str           # 不变
    issue: str              # 不变
    severity: str           # 不变
    rule_id: str            # 不变（LLM 结果统一用 "llm_semantic"）
    source: str = "rule"    # 新增："rule" | "llm"
    reasoning: str = ""     # 新增：LLM 推理过程
    confidence: float = 1.0 # 新增：规则=1.0，LLM=模型返回值
```

### CheckPcConsistencyOutput 增强

```python
class CheckPcConsistencyOutput(BaseModel):
    clause_id: str                          # 不变
    consistency_issues: List[ConsistencyIssue]  # 不变
    total_issues: int = 0                   # 不变
    clauses_checked: int = 0                # 不变
    llm_used: bool = False                  # 新增
```

## 4. 实现方案

### 4.1 主函数流程

```
check_pc_consistency(input_data)
  ├─ Phase A: 现有 CONSISTENCY_RULES 逻辑（完全不变）
  │   └─ 结果标记 source="rule", confidence=1.0
  ├─ Phase B: _llm_consistency_check(focus, other_clauses, rule_issues)
  │   ├─ get_llm_client() → None? 跳过
  │   ├─ 筛选：最多 8 条 modified clauses
  │   ├─ _build_consistency_prompt(focus, others, rule_issues)
  │   ├─ llm_client.chat(messages, max_output_tokens=1200)
  │   └─ _parse_llm_issues(response) → List[ConsistencyIssue]
  └─ Phase C: _merge_issues(rule_issues, llm_issues)
      └─ 去重：(clause_a, clause_b) 对已被规则覆盖的跳过
```

### 4.2 Phase A — 规则检查

保持现有 `CONSISTENCY_RULES` + 遍历逻辑完全不变。仅为每个 `ConsistencyIssue` 设置：
- `source="rule"`
- `confidence=1.0`
- `reasoning=""` （规则检查不需要推理过程）

### 4.3 Phase B — LLM 语义一致性检查

#### 触发条件

- `get_llm_client()` 返回非 None
- `len(clauses) >= 2`（至少有 focus + 1 个 other）

#### 输入限制

- 最多传入 8 条 modified clauses（除 focus 外）
- 每条 clause text 截断到 2000 字符
- 将 Phase A 已发现的 issues 传入 prompt，避免重复

#### LLM Prompt

```python
CONSISTENCY_SYSTEM_PROMPT = (
    "你是 FIDIC 合同一致性审查专家。"
    "请分析焦点条款与其他已修改条款之间是否存在一致性问题。\n"
    "请重点关注：\n"
    "1. 权责不对等：一方义务扩大但对应权利/保障未联动\n"
    "2. 时间/程序矛盾：时限与程序要求不匹配\n"
    "3. 定义不一致：同一术语在不同条款中含义不同\n"
    "4. 隐含冲突：条款间逻辑上互相矛盾\n"
    "已由规则引擎发现的问题会提供给你，请勿重复。\n"
    "只返回 JSON 数组，不得输出额外文本。\n"
    "每项字段：clause_a, clause_b, issue, severity(high|medium|low), reasoning, confidence(0-1)"
)
```

#### 输入构造

```python
def _build_consistency_prompt(
    focus: PcClause,
    others: List[PcClause],
    rule_issues: List[ConsistencyIssue],
) -> List[dict]:
    others_text = "\n\n".join(
        f"[{c.clause_id}]:\n{c.text[:2000]}" for c in others[:8]
    )
    existing = "\n".join(
        f"- {i.clause_a} vs {i.clause_b}: {i.issue}" for i in rule_issues
    ) or "（无）"
    user_msg = (
        f"焦点条款 [{focus.clause_id}]:\n{focus.text[:2000]}\n\n"
        f"其他已修改条款:\n{others_text}\n\n"
        f"已发现的问题（请勿重复）:\n{existing}"
    )
    return [
        {"role": "system", "content": CONSISTENCY_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
```

#### 响应解析

复用 `_extract_json` 模式（同 assess_deviation.py）。对每条 LLM 结果：
- `rule_id` 统一设为 `"llm_semantic"`
- `source` 设为 `"llm"`
- `confidence` 从 LLM 输出中取，clamp 到 [0, 1]
- `severity` 校验为 high/medium/low，无效值默认 medium

### 4.4 Phase C — 合并去重

```python
def _merge_issues(
    rule_issues: List[ConsistencyIssue],
    llm_issues: List[ConsistencyIssue],
) -> List[ConsistencyIssue]:
    # 规则已覆盖的条款对
    covered_pairs = {
        (i.clause_a, i.clause_b) for i in rule_issues
    } | {
        (i.clause_b, i.clause_a) for i in rule_issues
    }
    merged = list(rule_issues)
    for li in llm_issues:
        pair = (li.clause_a, li.clause_b)
        reverse_pair = (li.clause_b, li.clause_a)
        if pair not in covered_pairs and reverse_pair not in covered_pairs:
            merged.append(li)
            covered_pairs.add(pair)
    return merged
```

注意：去重粒度是条款对级别。同一对条款如果规则已报了问题，LLM 的补充就跳过。这是保守策略，避免同一对条款出现重复/矛盾的 issue。

## 5. 文件改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/src/contract_review/skills/fidic/check_pc_consistency.py` | 修改 | 主逻辑：rule → LLM → merge |
| `tests/test_check_pc_consistency_llm.py` | 新增 | LLM mock 测试 |

## 6. 测试用例

### 6.1 test_rule_only_when_llm_unavailable
- mock `get_llm_client` 返回 None
- 输入 FIDIC 标准条款对 (4.1, 17.6)，触发 obligation_vs_liability 规则
- 验证输出与当前行为一致，`llm_used=False`，所有 issue 的 `source="rule"`

### 6.2 test_llm_supplements_rules
- mock LLM 返回一条新 issue：clause 8.2 vs 14.2 的语义矛盾
- 验证规则 issue + LLM issue 都出现在结果中
- LLM issue 的 `source="llm"`，`rule_id="llm_semantic"`

### 6.3 test_llm_dedup_with_rules
- mock LLM 返回的 issue 涉及 (4.1, 17.6) — 已被规则覆盖
- 验证 LLM issue 被去重，不重复出现

### 6.4 test_llm_failure_fallback
- mock LLM 抛出异常
- 验证输出与纯规则一致，`llm_used=False`

### 6.5 test_non_fidic_clauses
- 输入非标条款号（如 "3.1", "7.2"），不匹配任何 clause_pairs
- 规则层无结果，LLM 层仍能发现语义矛盾
- 验证 LLM issue 正常输出

### 6.6 test_max_clauses_limit
- 输入 12 条 modified clauses
- 验证 LLM prompt 中最多包含 8 条（除 focus 外）

### 6.7 test_single_clause_no_check
- 输入仅 1 条 clause
- 验证直接返回空结果，不调用 LLM

## 7. 验收条件

1. ✅ 现有 6 条规则行为完全不变
2. ✅ LLM 能发现规则遗漏的语义矛盾
3. ✅ 非 FIDIC 合同（无标准条款号）时 LLM 仍能工作
4. ✅ LLM 不可用时输出与当前完全一致
5. ✅ 同一条款对不会出现重复 issue
6. ✅ LLM 输入最多 8 条 clauses
7. ✅ 所有现有测试继续通过
8. ✅ 新增测试全部通过
