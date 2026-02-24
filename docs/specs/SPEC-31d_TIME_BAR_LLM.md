# SPEC-31d：fidic_calculate_time_bar LLM 增强

> 优先级：P1 | 独立交付 | 预估改动 ~130 行

---

## 1. 背景与问题

当前 `calculate` (time_bar.py) 使用 5 组正则提取时限 + 3 组正则分别提取触发条件/行动要求/后果：

```python
_TIME_BAR_PATTERNS = [
    (r"within\s+(\d+)\s*(?:calendar\s+)?days?\b", "en"),
    (r"not\s+later\s+than\s+(\d+)\s*days?\b", "en"),
    (r"(\d+)\s*days?\s*(?:after|from|of)\b", "en"),
    (r"(\d+)\s*(?:个工作日|天|日)内", "zh"),
    (r"不迟于.{0,20}?(\d+)\s*(?:天|日)", "zh"),
]
```

能做到的：提取 `within 28 days`、`30天内` 等数字时限

做不到的：
- 触发条件截断：`_extract_trigger` 用 `(?:after|from|upon)\s+([^,.;]{5,80})` 只取 80 字符，复杂表述如 "after the Contractor became aware or should have become aware of the event or circumstance giving rise to the claim" 被截断
- 后果提取遗漏：`_extract_consequence` 只匹配 "otherwise"/"failing which"/"否则"/"逾期"，遗漏 "the Contractor shall have no entitlement"、"such failure shall constitute a waiver" 等变体
- 无法识别文字时限：`a reasonable period`、`一个月内`、`promptly` 等非数字表述
- 无法判断严格程度：是硬性 time bar（逾期丧失权利）还是建议性期限（should endeavour）
- `has_strict_time_bar` 只用 6 个关键词判断，覆盖面有限

## 2. 设计原则

1. 正则提取保留作为基础层
2. LLM 对 regex 已提取的 item 做精细化补充（enrich），同时发现 regex 遗漏的 item
3. 每个 TimeBarItem 标记来源
4. LLM 失败静默降级

## 3. 数据模型变更

### TimeBarItem 增强

```python
class TimeBarItem(BaseModel):
    trigger_event: str = ""      # 不变，LLM 可覆盖空值
    deadline_days: int           # 不变（LLM 新发现的 item 也需提供）
    deadline_text: str           # 不变
    action_required: str = ""    # 不变，LLM 可覆盖空值
    consequence: str = ""        # 不变，LLM 可覆盖空值
    context: str = ""            # 不变
    source: str = "regex"        # 新增："regex" | "llm"
    strictness_level: str = ""   # 新增："hard_bar" | "soft_bar" | "advisory" | ""
    risk_assessment: str = ""    # 新增：LLM 一句话风险评估
```

### CalculateTimeBarOutput 增强

```python
class CalculateTimeBarOutput(BaseModel):
    clause_id: str                      # 不变
    time_bars: List[TimeBarItem]        # 不变
    total_time_bars: int = 0            # 不变
    has_strict_time_bar: bool = False   # 不变（规则判断保留，LLM 可补充）
    llm_used: bool = False              # 新增
```

## 4. 实现方案

### 4.1 主函数流程

```
calculate(input_data)
  ├─ Phase A: 现有正则提取逻辑（完全不变）
  │   └─ 结果标记 source="regex"
  ├─ Phase B: _llm_enrich_and_discover(clause_text, regex_items)
  │   ├─ get_llm_client() → None? 跳过
  │   ├─ _build_time_bar_prompt(clause_text, regex_items)
  │   ├─ llm_client.chat(messages, max_output_tokens=1000)
  │   └─ _parse_time_bar_response(response)
  │       ├─ enrichments: 对已有 item 的补充（trigger/consequence/strictness）
  │       └─ discoveries: 新发现的 time bar item
  ├─ Phase C: _apply_enrichments(regex_items, enrichments)
  │   └─ 仅覆盖空值字段，不覆盖 regex 已提取的内容
  ├─ Phase D: _merge_discoveries(regex_items, discoveries)
  │   └─ 按 deadline_days 去重
  └─ 更新 has_strict_time_bar（规则判断 OR 任一 item 的 strictness_level=="hard_bar"）
```

### 4.2 Phase A — 正则提取

保持现有逻辑完全不变。为每个 `TimeBarItem` 设置 `source="regex"`。

### 4.3 Phase B — LLM 增强

#### LLM Prompt

```python
TIME_BAR_SYSTEM_PROMPT = (
    "你是 FIDIC 合同时限条款分析专家。请分析以下条款中的所有时限要求。\n"
    "已由规则引擎提取的时限会提供给你。请：\n"
    "1. 对已提取的时限补充缺失信息（触发条件、行动要求、后果）\n"
    "2. 发现规则遗漏的时限要求（包括文字表述的时限如'a reasonable period'）\n"
    "3. 对每个时限判断严格程度\n\n"
    "只返回 JSON 对象，不得输出额外文本。格式：\n"
    "{\n"
    '  "enrichments": [\n'
    '    {"deadline_days": 28, "trigger_event": "...", "action_required": "...", '
    '"consequence": "...", "strictness_level": "hard_bar|soft_bar|advisory", '
    '"risk_assessment": "..."}\n'
    "  ],\n"
    '  "discoveries": [\n'
    '    {"deadline_days": 0, "deadline_text": "a reasonable period", '
    '"trigger_event": "...", "action_required": "...", "consequence": "...", '
    '"strictness_level": "...", "risk_assessment": "..."}\n'
    "  ]\n"
    "}\n"
    "enrichments 按 deadline_days 与已提取项对应。\n"
    "discoveries 中 deadline_days 为 0 表示非数字时限。"
)
```

#### 输入构造

```python
def _build_time_bar_prompt(
    clause_text: str, regex_items: List[TimeBarItem]
) -> List[dict]:
    existing = "\n".join(
        f"- {item.deadline_text} (days={item.deadline_days}), "
        f"trigger={item.trigger_event or '未知'}, "
        f"consequence={item.consequence or '未知'}"
        for item in regex_items
    ) or "（无）"
    user_msg = (
        f"条款文本：\n{clause_text[:3000]}\n\n"
        f"已提取的时限：\n{existing}"
    )
    return [
        {"role": "system", "content": TIME_BAR_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
```

#### 响应解析

- 期望 JSON 对象（非数组），包含 `enrichments` 和 `discoveries` 两个数组
- `enrichments` 按 `deadline_days` 与 regex_items 匹配
- `discoveries` 每项构造新的 `TimeBarItem`，`source="llm"`
- `strictness_level` 校验为 hard_bar/soft_bar/advisory，无效值设为空

### 4.4 Phase C — 应用补充

```python
def _apply_enrichments(
    regex_items: List[TimeBarItem],
    enrichments: List[dict],
) -> None:
    enrich_by_days = {}
    for e in enrichments:
        days = e.get("deadline_days")
        if days is not None:
            enrich_by_days[int(days)] = e

    for item in regex_items:
        e = enrich_by_days.get(item.deadline_days)
        if not e:
            continue
        # 仅覆盖空值
        if not item.trigger_event:
            item.trigger_event = str(e.get("trigger_event", "") or "")
        if not item.action_required:
            item.action_required = str(e.get("action_required", "") or "")
        if not item.consequence:
            item.consequence = str(e.get("consequence", "") or "")
        # 新字段直接赋值
        item.strictness_level = str(e.get("strictness_level", "") or "")
        item.risk_assessment = str(e.get("risk_assessment", "") or "")
```

### 4.5 Phase D — 合并新发现

```python
def _merge_discoveries(
    regex_items: List[TimeBarItem],
    discoveries: List[dict],
) -> List[TimeBarItem]:
    existing_days = {item.deadline_days for item in regex_items}
    new_items = []
    for d in discoveries:
        days = int(d.get("deadline_days", 0))
        if days in existing_days and days != 0:
            continue  # 去重（days=0 的非数字时限不去重）
        new_items.append(TimeBarItem(
            trigger_event=str(d.get("trigger_event", "") or ""),
            deadline_days=days,
            deadline_text=str(d.get("deadline_text", "") or ""),
            action_required=str(d.get("action_required", "") or ""),
            consequence=str(d.get("consequence", "") or ""),
            context="",
            source="llm",
            strictness_level=str(d.get("strictness_level", "") or ""),
            risk_assessment=str(d.get("risk_assessment", "") or ""),
        ))
    return regex_items + new_items
```

## 5. 文件改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/src/contract_review/skills/fidic/time_bar.py` | 修改 | 主逻辑：regex → LLM enrich/discover → merge |
| `tests/test_time_bar_llm.py` | 新增 | LLM mock 测试 |

## 6. 测试用例

### 6.1 test_regex_only_when_llm_unavailable
- mock `get_llm_client` 返回 None
- 输入含 `within 28 days` 的条款
- 验证输出与当前行为一致，`llm_used=False`

### 6.2 test_llm_enriches_trigger
- regex 提取到 28 days，但 `trigger_event` 为空（正则没匹配到）
- mock LLM enrichments 返回完整 trigger_event
- 验证 trigger_event 被补充，source 仍为 "regex"

### 6.3 test_llm_does_not_overwrite_regex
- regex 提取到 trigger_event = "after completion"
- mock LLM enrichments 返回不同的 trigger_event
- 验证 regex 的值保留不变

### 6.4 test_llm_discovers_text_deadline
- 条款含 "a reasonable period" 但无数字时限
- mock LLM discoveries 返回 deadline_days=0, deadline_text="a reasonable period"
- 验证新 item 出现在结果中，source="llm"

### 6.5 test_strictness_level_classification
- mock LLM 返回 strictness_level="hard_bar" 对应 "deemed to have waived"
- 验证 strictness_level 正确填充
- 验证 has_strict_time_bar 为 True

### 6.6 test_llm_failure_fallback
- mock LLM 抛出异常
- 验证输出与纯 regex 一致，`llm_used=False`

### 6.7 test_dedup_discoveries
- regex 已提取 28 days
- mock LLM discoveries 也返回 28 days
- 验证不重复

## 7. 验收条件

1. ✅ 现有正则提取行为完全不变
2. ✅ 复杂触发条件能被 LLM 完整提取
3. ✅ 每个 time bar 有 strictness_level 分类
4. ✅ 非数字时限（如 "a reasonable period"）能被发现
5. ✅ LLM 不覆盖 regex 已提取的非空字段
6. ✅ LLM 不可用时输出与当前完全一致
7. ✅ 所有现有测试继续通过
8. ✅ 新增测试全部通过
