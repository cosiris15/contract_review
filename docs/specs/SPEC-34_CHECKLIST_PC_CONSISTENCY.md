# SPEC-34: FIDIC Checklist 补全 fidic_check_pc_consistency

## 优先级: P1

## 问题描述

`fidic_check_pc_consistency` 已注册为 FIDIC 域 Skill，但未被放入任何 checklist 条款的
`required_skills`，导致模式 A（ReAct）和模式 B（deterministic fallback）都不会调用它。

## 根因

`backend/src/contract_review/plugins/fidic.py` 的 `FIDIC_SILVER_BOOK_CHECKLIST` 中
12 个条款的 `required_skills` 均不包含 `fidic_check_pc_consistency`。

## 修复方案

在以下 7 个条款的 `required_skills` 中追加 `"fidic_check_pc_consistency"`：

| 条款 | 覆盖的一致性规则 |
|------|-----------------|
| 4.1 | obligation_vs_liability_cap, risk_transfer_vs_insurance, rights_vs_obligations |
| 8.2 | payment_vs_schedule |
| 14.1 | payment_vs_schedule |
| 14.7 | payment_vs_schedule |
| 17.6 | obligation_vs_liability_cap |
| 20.1 | time_bar_vs_procedure, rights_vs_obligations |
| 20.2 | time_bar_vs_procedure |

### 变更文件

`backend/src/contract_review/plugins/fidic.py` — 修改 `FIDIC_SILVER_BOOK_CHECKLIST` 中
上述 7 个条款的 `required_skills` 列表，在末尾追加 `"fidic_check_pc_consistency"`。

## 验收标准 (AC)

1. AC-1: 上述 7 个条款的 `required_skills` 包含 `fidic_check_pc_consistency`
2. AC-2: 其余 5 个条款（1.1, 1.5, 4.12, 14.2, 18.1）不受影响
3. AC-3: 新增单元测试验证 checklist 配置正确性
4. AC-4: 全量测试零回归

## 测试要求

在 `tests/test_fidic_checklist.py`（新建或追加）中：

```python
def test_pc_consistency_in_required_skills():
    """fidic_check_pc_consistency 出现在预期条款的 required_skills 中"""

def test_pc_consistency_not_in_unrelated_clauses():
    """不相关条款不包含 fidic_check_pc_consistency"""
```

## 回归风险

极低。仅修改 checklist 配置数据，不涉及任何逻辑代码。
