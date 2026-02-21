# SPEC-21: Orchestrator 编排层（LLM 自主编排工作流）

> 优先级：中（架构改造三步走的第三步，可独立于 SPEC-19/20 延后实施）
> 前置依赖：SPEC-19（工具自描述层）+ SPEC-20（ReAct Agent 节点）
> 预计新建文件：2 个 | 修改文件：3 个
> 范围：图级别改造，影响整体审查流程的编排逻辑

---

## 0. 架构演进上下文

### 0.1 回顾：三步走计划的完成

```
SPEC-19（已完成）          SPEC-20（已完成）           SPEC-21（本文档）
工具自描述层          →    ReAct Agent 节点      →    Orchestrator 编排层
让工具能被 LLM 理解        让 LLM 自主选择工具         让 LLM 自主编排流程
```

经过 SPEC-19 和 SPEC-20 的改造：
- 每个 Skill 能生成 OpenAI Function Calling 格式的 tool definition（SPEC-19）
- `node_clause_analyze` 内部可以运行 ReAct Agent 循环，LLM 自主选择工具（SPEC-20）

但有一个关键问题仍未解决：**审查流程本身仍然是硬编码的。**

### 0.2 当前问题：硬编码的审查流程

当前 `build_review_graph`（builder.py 第 840-891 行）构建了一个固定的 8 节点 LangGraph：

```
init → parse_document → clause_analyze → clause_generate_diffs
                              ↑                    ↓
                         save_clause ← human_approval ← clause_validate
                              ↓
                          summarize → END
```

这个流程的问题：

1. **每个条款走完全相同的流水线**：不管条款是"承包商的一般义务"（需要深度分析）还是"定义条款"（只需快速扫描），都走 `analyze → diffs → validate → approval` 全流程
2. **无法跳过不必要的步骤**：如果 `clause_analyze` 发现条款无风险（`risks=[]`），仍然会进入 `clause_generate_diffs`（虽然会快速返回空 diffs），再进入 `clause_validate`
3. **无法根据全局情况调整策略**：比如审查到第 10 个条款时发现前 9 个都有严重的风险分配问题，理想情况下应该提高后续条款的审查深度——但当前架构做不到
4. **条款审查顺序固定**：按 checklist 顺序逐个审查，无法根据优先级或依赖关系动态调整

### 0.3 目标架构：Orchestrator-Workers

改造后的架构遵循 Anthropic 的 "Orchestrator-Workers" 模式：

```
┌─────────────────────────────────────────────────────────┐
│  Orchestrator（LLM 驱动）                                │
│                                                          │
│  "我看到 20 个条款需要审查。让我先规划一下：              │
│   - 4.1（critical）→ 深度分析，使用全部工具               │
│   - 1.1（定义条款）→ 快速扫描，只用 get_clause_context    │
│   - 14.1（付款条款）→ 中度分析，重点用财务工具            │
│   ..."                                                   │
│                                                          │
│  每个条款分析完成后，Orchestrator 检查结果：               │
│  "4.1 发现重大风险，我需要对 17.6（责任限制）提高关注度"   │
│                                                          │
└──────────┬──────────┬──────────┬────────────────────────┘
           │          │          │
     ┌─────▼──┐ ┌─────▼──┐ ┌────▼───┐
     │Worker 1│ │Worker 2│ │Worker 3│    ← 每个 Worker 是一个
     │(ReAct) │ │(ReAct) │ │(ReAct) │       SPEC-20 的 ReAct Agent
     └────────┘ └────────┘ └────────┘
```

关键变化：
- **Orchestrator LLM 决定审查策略**：哪些条款需要深度分析、哪些快速扫描、审查顺序如何
- **Worker 是 SPEC-20 的 ReAct Agent**：每个 Worker 负责一个条款的分析
- **Orchestrator 可以根据中间结果调整策略**：前面条款的发现影响后续条款的审查深度
- **条款可以并行审查**（未来优化）：独立的条款可以同时分析

### 0.4 为什么需要 Orchestrator

| 场景 | 当前行为 | Orchestrator 行为 |
|------|---------|------------------|
| 定义条款（1.1） | 走完整 analyze→diffs→validate 流程 | 快速扫描，跳过 diffs 和 validate |
| 发现前 5 个条款都有风险分配问题 | 后续条款审查深度不变 | 提高后续条款的审查深度，增加工具调用 |
| 20 个条款中 15 个是低优先级 | 全部按相同深度审查 | 低优先级条款快速扫描，节省 70% token |
| 条款 17.6 依赖 4.1 的分析结果 | 按固定顺序审查，可能 17.6 先于 4.1 | 动态调整顺序，确保依赖关系 |

### 0.5 设计原则

1. **Orchestrator 是增量添加，不替代现有图**：现有的 8 节点 LangGraph 保持不变，Orchestrator 是在其上层的新增能力
2. **Plan-then-Execute 模式**：Orchestrator 先生成审查计划，再逐步执行。与 SPEC-20 的 ReAct（边推理边行动）互补
3. **计划可调整**：执行过程中 Orchestrator 可以根据中间结果修改剩余计划
4. **配置控制**：`use_orchestrator: bool` 配置项，默认 `False`，可随时回退

---

## 1. 设计方案

### 1.1 Orchestrator 的两个职责

Orchestrator 承担两个核心职责：

**职责 1：审查规划（Planning）**
- 输入：checklist（所有待审查条款）+ 文档元信息
- 输出：审查计划（每个条款的审查深度、工具集、优先级排序）
- 时机：在 `parse_document` 之后、`clause_analyze` 之前

**职责 2：中间调度（Dispatching）**
- 输入：当前条款的分析结果 + 剩余计划
- 输出：是否需要调整后续计划、是否需要追加分析
- 时机：每个条款分析完成后

### 1.2 审查计划的数据结构

```python
class ClauseAnalysisPlan(BaseModel):
    """单个条款的审查计划。"""
    clause_id: str
    clause_name: str = ""
    analysis_depth: str = "standard"    # "quick" | "standard" | "deep"
    suggested_tools: list[str] = Field(default_factory=list)
    max_iterations: int = 3             # ReAct 循环上限
    priority_order: int = 0             # 执行顺序（0 = 最先）
    rationale: str = ""                 # Orchestrator 的决策理由
    skip_diffs: bool = False            # 是否跳过修改建议生成
    skip_validate: bool = False         # 是否跳过质量校验

class ReviewPlan(BaseModel):
    """完整的审查计划。"""
    clause_plans: list[ClauseAnalysisPlan] = Field(default_factory=list)
    global_strategy: str = ""           # 全局审查策略说明
    estimated_depth_distribution: dict = Field(default_factory=dict)
    # 例如 {"quick": 8, "standard": 7, "deep": 5}
    plan_version: int = 1               # 计划版本号（每次调整 +1）
```

### 1.3 审查深度的含义

| 深度 | max_iterations | 工具策略 | 后续步骤 |
|------|---------------|---------|---------|
| `quick` | 1 | 仅 `get_clause_context` | 跳过 diffs 和 validate |
| `standard` | 3 | checklist 建议的工具 | 正常流程 |
| `deep` | 5 | 全部可用工具 | 正常流程 + 可能追加分析 |

### 1.4 Orchestrator 的 LLM 调用

Orchestrator 本身也是 LLM 驱动的。它有两个 LLM 调用点：

**调用点 1：生成初始计划**
```
输入：checklist 列表 + 文档类型 + domain 信息
输出：ReviewPlan（JSON）
```

**调用点 2：中间调度（可选）**
```
输入：当前条款分析结果摘要 + 剩余计划
输出：是否调整计划（JSON）
```

调用点 2 不是每个条款都触发——只在以下情况触发：
- 当前条款发现了 `risk_level=high` 的风险
- 当前条款的分析结果与预期不符（如预期无风险但发现了风险）
- 已完成条款数达到总数的 50%（中期复盘）

---

## 2. 文件清单

### 新增文件（2 个）

| 文件路径 | 用途 |
|---------|------|
| `backend/src/contract_review/graph/orchestrator.py` | Orchestrator 编排逻辑 |
| `tests/test_orchestrator.py` | 单元测试 |

### 修改文件（3 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/graph/builder.py` | `node_clause_analyze` 和 `node_save_clause` 集成 Orchestrator；`build_review_graph` 新增 Orchestrator 节点 |
| `backend/src/contract_review/graph/state.py` | `ReviewGraphState` 新增 `review_plan`、`plan_version` 字段 |
| `backend/src/contract_review/config.py` | 新增 `use_orchestrator: bool` 配置项 |

### 不需要修改的文件

- `react_agent.py` — SPEC-20 已实现，Orchestrator 通过参数控制其行为
- `prompts.py` — Orchestrator 有自己的 prompt，不修改现有 prompt
- `llm_client.py` — 无需改动
- `dispatcher.py` — 无需改动
- `tool_adapter.py` — 无需改动

---

## 3. `orchestrator.py`（新增）

### 3.1 职责

实现 Orchestrator 的两个核心能力：生成审查计划 + 中间调度。

### 3.2 审查规划实现

```python
"""Orchestrator: LLM-driven review planning and dispatching."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..llm_client import LLMClient
from .llm_utils import parse_json_response

logger = logging.getLogger(__name__)


# --- 数据模型 ---

class ClauseAnalysisPlan(BaseModel):
    """单个条款的审查计划。"""
    clause_id: str
    clause_name: str = ""
    analysis_depth: str = "standard"    # "quick" | "standard" | "deep"
    suggested_tools: list[str] = Field(default_factory=list)
    max_iterations: int = 3
    priority_order: int = 0
    rationale: str = ""
    skip_diffs: bool = False
    skip_validate: bool = False


class ReviewPlan(BaseModel):
    """完整的审查计划。"""
    clause_plans: list[ClauseAnalysisPlan] = Field(default_factory=list)
    global_strategy: str = ""
    estimated_depth_distribution: dict = Field(default_factory=dict)
    plan_version: int = 1


class PlanAdjustment(BaseModel):
    """中间调度的计划调整。"""
    adjusted_clauses: list[ClauseAnalysisPlan] = Field(default_factory=list)
    reason: str = ""
    should_adjust: bool = False


# --- Prompt 模板 ---

PLANNING_SYSTEM = """你是一位资深法务审查项目经理。你的任务是为合同审查制定审查计划。

你需要根据条款列表和文档信息，为每个条款决定：
1. analysis_depth（审查深度）：
   - "quick"：快速扫描，仅提取条款文本，适用于定义条款、标准条款等低风险条款
   - "standard"：标准审查，使用建议的工具集，适用于大多数条款
   - "deep"：深度分析，使用全部可用工具，适用于 critical 条款和高风险条款

2. suggested_tools：建议使用的工具列表（从可用工具中选择）
3. max_iterations：ReAct 循环上限（quick=1, standard=3, deep=5）
4. priority_order：执行顺序（数字越小越先执行，critical 条款优先）
5. skip_diffs：是否跳过修改建议生成（quick 深度通常跳过）
6. skip_validate：是否跳过质量校验（quick 深度通常跳过）
7. rationale：决策理由（简短说明）

【决策原则】
- critical 优先级的条款 → deep 深度
- 定义条款、通则条款 → quick 深度
- 涉及金额、时效、责任限制的条款 → standard 或 deep
- 如果条款之间有依赖关系（如 4.1 的义务范围影响 17.6 的责任限制），被依赖的条款应先审查
- 目标：在保证审查质量的前提下，尽量减少不必要的深度分析

请以 JSON 格式输出审查计划：
{
    "global_strategy": "全局策略说明",
    "estimated_depth_distribution": {"quick": N, "standard": N, "deep": N},
    "clause_plans": [
        {
            "clause_id": "4.1",
            "clause_name": "承包商义务",
            "analysis_depth": "deep",
            "suggested_tools": ["get_clause_context", "fidic_merge_gc_pc", "compare_with_baseline"],
            "max_iterations": 5,
            "priority_order": 0,
            "skip_diffs": false,
            "skip_validate": false,
            "rationale": "critical 条款，义务范围是核心风险点"
        }
    ]
}

只输出 JSON，不要输出其他内容。"""


DISPATCH_SYSTEM = """你是一位法务审查项目经理。你刚完成了一个条款的审查，需要决定是否调整后续审查计划。

当前审查进度和发现如下。请判断：
1. 是否需要调整后续条款的审查深度
2. 是否需要调整审查顺序

只在以下情况建议调整：
- 发现了预期之外的重大风险
- 发现了条款之间的关联性（如风险联动）
- 当前条款的实际复杂度与计划不符

如果不需要调整，返回 {"should_adjust": false, "reason": "无需调整"}。

如果需要调整，返回：
{
    "should_adjust": true,
    "reason": "调整原因",
    "adjusted_clauses": [
        {"clause_id": "17.6", "analysis_depth": "deep", "max_iterations": 5, "rationale": "..."}
    ]
}

只输出 JSON，不要输出其他内容。"""


# --- 核心函数 ---

async def generate_review_plan(
    llm_client: LLMClient,
    checklist: list[dict],
    *,
    domain_id: str = "",
    material_type: str = "",
    available_tools: list[str] | None = None,
) -> ReviewPlan:
    """生成审查计划。

    Args:
        llm_client: LLM 客户端
        checklist: 条款 checklist 列表
        domain_id: 领域 ID（fidic / sha_spa / generic）
        material_type: 文档类型
        available_tools: 可用工具 ID 列表

    Returns:
        ReviewPlan
    """
    # 构造 checklist 摘要
    checklist_summary = []
    for item in checklist:
        if isinstance(item, dict):
            checklist_summary.append({
                "clause_id": item.get("clause_id", ""),
                "clause_name": item.get("clause_name", ""),
                "priority": item.get("priority", "medium"),
                "required_skills": item.get("required_skills", []),
                "description": item.get("description", ""),
            })

    user_content = (
        f"【文档信息】\n"
        f"- 领域：{domain_id or '通用'}\n"
        f"- 文档类型：{material_type or '合同'}\n"
        f"- 条款总数：{len(checklist_summary)}\n\n"
        f"【可用工具】\n{json.dumps(available_tools or [], ensure_ascii=False)}\n\n"
        f"【条款列表】\n{json.dumps(checklist_summary, ensure_ascii=False, indent=2)}"
    )

    messages = [
        {"role": "system", "content": PLANNING_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    try:
        response = await llm_client.chat(messages, temperature=0.1)
        plan_data = parse_json_response(response, expect_list=False)

        if not isinstance(plan_data, dict):
            logger.warning("Orchestrator 规划响应格式异常，使用默认计划")
            return _build_default_plan(checklist)

        clause_plans = []
        for cp in plan_data.get("clause_plans", []):
            if not isinstance(cp, dict):
                continue
            depth = cp.get("analysis_depth", "standard")
            if depth not in ("quick", "standard", "deep"):
                depth = "standard"
            clause_plans.append(ClauseAnalysisPlan(
                clause_id=cp.get("clause_id", ""),
                clause_name=cp.get("clause_name", ""),
                analysis_depth=depth,
                suggested_tools=cp.get("suggested_tools", []),
                max_iterations=cp.get("max_iterations", 3),
                priority_order=cp.get("priority_order", 0),
                rationale=cp.get("rationale", ""),
                skip_diffs=cp.get("skip_diffs", depth == "quick"),
                skip_validate=cp.get("skip_validate", depth == "quick"),
            ))

        # 确保所有 checklist 条款都有计划
        planned_ids = {cp.clause_id for cp in clause_plans}
        for item in checklist:
            cid = item.get("clause_id", "") if isinstance(item, dict) else ""
            if cid and cid not in planned_ids:
                clause_plans.append(ClauseAnalysisPlan(
                    clause_id=cid,
                    clause_name=item.get("clause_name", "") if isinstance(item, dict) else "",
                    analysis_depth="standard",
                    rationale="LLM 未规划，使用默认深度",
                ))

        # 按 priority_order 排序
        clause_plans.sort(key=lambda x: x.priority_order)

        return ReviewPlan(
            clause_plans=clause_plans,
            global_strategy=plan_data.get("global_strategy", ""),
            estimated_depth_distribution=plan_data.get("estimated_depth_distribution", {}),
        )

    except Exception as exc:
        logger.warning("Orchestrator 规划失败，使用默认计划: %s", exc)
        return _build_default_plan(checklist)


async def maybe_adjust_plan(
    llm_client: LLMClient,
    current_clause_id: str,
    current_risks: list[dict],
    remaining_plan: list[ClauseAnalysisPlan],
    completed_count: int,
    total_count: int,
) -> PlanAdjustment:
    """根据当前条款分析结果，决定是否调整后续计划。

    只在以下情况触发 LLM 调用：
    - 当前条款发现了 high 风险
    - 已完成 50% 条款（中期复盘）
    """
    has_high_risk = any(
        r.get("risk_level") == "high" for r in current_risks if isinstance(r, dict)
    )
    is_midpoint = total_count > 4 and completed_count == total_count // 2

    if not has_high_risk and not is_midpoint:
        return PlanAdjustment(should_adjust=False, reason="无触发条件")

    # 构造摘要
    risk_summary = []
    for r in current_risks[:5]:  # 最多 5 个风险
        if isinstance(r, dict):
            risk_summary.append({
                "risk_level": r.get("risk_level", ""),
                "description": r.get("description", "")[:100],
            })

    remaining_summary = [
        {"clause_id": cp.clause_id, "analysis_depth": cp.analysis_depth}
        for cp in remaining_plan[:10]  # 最多 10 个
    ]

    user_content = (
        f"【当前条款】{current_clause_id}\n"
        f"【发现风险】\n{json.dumps(risk_summary, ensure_ascii=False)}\n\n"
        f"【审查进度】{completed_count}/{total_count}\n\n"
        f"【剩余计划】\n{json.dumps(remaining_summary, ensure_ascii=False)}"
    )

    messages = [
        {"role": "system", "content": DISPATCH_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    try:
        response = await llm_client.chat(messages, temperature=0.1)
        data = parse_json_response(response, expect_list=False)

        if not isinstance(data, dict) or not data.get("should_adjust"):
            return PlanAdjustment(should_adjust=False, reason=data.get("reason", ""))

        adjusted = []
        for cp in data.get("adjusted_clauses", []):
            if isinstance(cp, dict) and cp.get("clause_id"):
                depth = cp.get("analysis_depth", "standard")
                if depth not in ("quick", "standard", "deep"):
                    depth = "standard"
                adjusted.append(ClauseAnalysisPlan(
                    clause_id=cp["clause_id"],
                    analysis_depth=depth,
                    max_iterations=cp.get("max_iterations", 3),
                    rationale=cp.get("rationale", ""),
                ))

        return PlanAdjustment(
            should_adjust=True,
            reason=data.get("reason", ""),
            adjusted_clauses=adjusted,
        )

    except Exception as exc:
        logger.warning("Orchestrator 调度失败: %s", exc)
        return PlanAdjustment(should_adjust=False, reason=f"调度异常: {exc}")


def _build_default_plan(checklist: list[dict]) -> ReviewPlan:
    """构建默认审查计划（LLM 不可用时的 fallback）。"""
    clause_plans = []
    for i, item in enumerate(checklist):
        if not isinstance(item, dict):
            continue
        priority = item.get("priority", "medium")
        depth = "deep" if priority == "critical" else "standard"
        clause_plans.append(ClauseAnalysisPlan(
            clause_id=item.get("clause_id", ""),
            clause_name=item.get("clause_name", ""),
            analysis_depth=depth,
            suggested_tools=item.get("required_skills", []),
            max_iterations=5 if depth == "deep" else 3,
            priority_order=i,
            rationale=f"默认计划：priority={priority}",
            skip_diffs=False,
            skip_validate=False,
        ))
    return ReviewPlan(
        clause_plans=clause_plans,
        global_strategy="默认计划：按 checklist 顺序，critical 条款深度分析",
    )


def apply_adjustment(plan: ReviewPlan, adjustment: PlanAdjustment) -> ReviewPlan:
    """将调整应用到现有计划。"""
    if not adjustment.should_adjust or not adjustment.adjusted_clauses:
        return plan

    adjusted_map = {cp.clause_id: cp for cp in adjustment.adjusted_clauses}
    new_plans = []
    for cp in plan.clause_plans:
        if cp.clause_id in adjusted_map:
            adj = adjusted_map[cp.clause_id]
            new_plans.append(ClauseAnalysisPlan(
                clause_id=cp.clause_id,
                clause_name=cp.clause_name,
                analysis_depth=adj.analysis_depth,
                suggested_tools=adj.suggested_tools or cp.suggested_tools,
                max_iterations=adj.max_iterations,
                priority_order=cp.priority_order,
                rationale=adj.rationale or cp.rationale,
                skip_diffs=adj.analysis_depth == "quick",
                skip_validate=adj.analysis_depth == "quick",
            ))
        else:
            new_plans.append(cp)

    return ReviewPlan(
        clause_plans=new_plans,
        global_strategy=plan.global_strategy,
        estimated_depth_distribution=plan.estimated_depth_distribution,
        plan_version=plan.plan_version + 1,
    )
```

### 3.3 设计说明

- **`generate_review_plan` 是一次性调用**：在审查开始前调用一次，生成完整计划。失败时回退到默认计划
- **`maybe_adjust_plan` 是条件触发**：不是每个条款都调用，只在发现高风险或中期复盘时触发，控制 LLM 调用成本
- **`_build_default_plan` 保证兜底**：即使 LLM 完全不可用，系统仍然能按默认策略运行
- **`apply_adjustment` 是纯函数**：不修改原计划，返回新计划，方便追踪计划变更历史

---

## 4. `builder.py` 改动

### 4.1 新增 `node_plan_review` 节点

```python
async def node_plan_review(
    state: ReviewGraphState,
    dispatcher: SkillDispatcher | None = None,
) -> Dict[str, Any]:
    """Orchestrator 规划节点：生成审查计划。

    在 parse_document 之后、clause_analyze 之前执行。
    """
    settings = get_settings()
    use_orchestrator = getattr(settings, "use_orchestrator", False)

    if not use_orchestrator:
        return {}  # 不启用 Orchestrator，跳过规划

    llm_client = _get_llm_client()
    if not llm_client:
        return {}

    checklist = state.get("review_checklist", [])
    if not checklist:
        return {}

    from .orchestrator import generate_review_plan

    available_tools = dispatcher.skill_ids if dispatcher else []

    plan = await generate_review_plan(
        llm_client,
        [_as_dict(item) for item in checklist],
        domain_id=state.get("domain_id", ""),
        material_type=state.get("material_type", ""),
        available_tools=available_tools,
    )

    # 按 Orchestrator 的排序重新排列 checklist
    plan_order = {cp.clause_id: cp.priority_order for cp in plan.clause_plans}
    sorted_checklist = sorted(
        checklist,
        key=lambda item: plan_order.get(
            _as_dict(item).get("clause_id", ""), 999
        ),
    )

    return {
        "review_plan": plan.model_dump(),
        "review_checklist": sorted_checklist,
    }
```

### 4.2 `node_clause_analyze` 集成 Orchestrator 计划

```python
async def node_clause_analyze(
    state: ReviewGraphState, dispatcher: SkillDispatcher | None = None
) -> Dict[str, Any]:
    # ... 现有代码：提取 checklist item 信息 ...

    # --- 新增：从 Orchestrator 计划中获取当前条款的审查参数 ---
    clause_plan = _get_clause_plan(state, clause_id)

    if clause_plan:
        # Orchestrator 模式：使用计划中的参数
        analysis_depth = clause_plan.get("analysis_depth", "standard")
        max_iterations = clause_plan.get("max_iterations", 3)
        suggested_tools = clause_plan.get("suggested_tools", required_skills)
    else:
        # 非 Orchestrator 模式：使用默认参数
        analysis_depth = "standard"
        max_iterations = 5
        suggested_tools = required_skills

    # --- ReAct 分支（SPEC-20）使用 Orchestrator 的参数 ---
    settings = get_settings()
    use_react = getattr(settings, "use_react_agent", False)
    llm_client = _get_llm_client()

    if use_react and llm_client and dispatcher and primary_structure:
        try:
            return await _run_react_branch(
                llm_client=llm_client,
                dispatcher=dispatcher,
                clause_id=clause_id,
                clause_name=clause_name,
                description=description,
                priority=priority,
                our_party=our_party,
                language=language,
                primary_structure=primary_structure,
                state=state,
                suggested_skills=suggested_tools,  # 使用 Orchestrator 的建议
                max_iterations=max_iterations,     # 使用 Orchestrator 的上限
            )
        except Exception as exc:
            logger.warning("ReAct Agent 失败，回退: %s", exc)

    # --- 原有硬编码分支 ---
    # ... 保持不变 ...


def _get_clause_plan(state: ReviewGraphState, clause_id: str) -> dict | None:
    """从 state 中获取当前条款的 Orchestrator 计划。"""
    review_plan = state.get("review_plan")
    if not isinstance(review_plan, dict):
        return None
    for cp in review_plan.get("clause_plans", []):
        if isinstance(cp, dict) and cp.get("clause_id") == clause_id:
            return cp
    return None
```

### 4.3 `node_save_clause` 集成中间调度

```python
async def node_save_clause(state: ReviewGraphState) -> Dict[str, Any]:
    # ... 现有保存逻辑不变 ...

    # --- 新增：Orchestrator 中间调度 ---
    updates = _orchestrator_dispatch(state, clause_id, risks)
    result = {
        "findings": findings,
        "all_risks": all_risks,
        "all_diffs": all_diffs,
        "current_clause_index": state.get("current_clause_index", 0) + 1,
    }
    result.update(updates)
    return result


def _orchestrator_dispatch(
    state: ReviewGraphState,
    clause_id: str,
    risks: list,
) -> dict:
    """Orchestrator 中间调度（同步包装）。"""
    settings = get_settings()
    if not getattr(settings, "use_orchestrator", False):
        return {}

    review_plan = state.get("review_plan")
    if not isinstance(review_plan, dict):
        return {}

    # 中间调度是异步的，但 node_save_clause 需要同步返回
    # 这里只做标记，实际调度在下一轮 clause_analyze 开始前执行
    has_high_risk = any(
        isinstance(r, dict) and r.get("risk_level") == "high"
        for r in risks
    )

    if has_high_risk:
        return {"_needs_plan_adjustment": True}

    return {}
```

### 4.4 `build_review_graph` 新增 Orchestrator 节点

```python
def build_review_graph(
    checkpointer=None,
    interrupt_before: List[str] | None = None,
    domain_id: str | None = None,
):
    # ... 现有代码 ...

    dispatcher = _create_dispatcher(domain_id=domain_id)

    # 包装 node 函数
    async def _node_clause_analyze(state: ReviewGraphState):
        return await node_clause_analyze(state, dispatcher=dispatcher)

    async def _node_plan_review(state: ReviewGraphState):
        return await node_plan_review(state, dispatcher=dispatcher)

    graph = StateGraph(ReviewGraphState)

    graph.add_node("init", node_init)
    graph.add_node("parse_document", node_parse_document)
    graph.add_node("plan_review", _node_plan_review)       # 新增
    graph.add_node("clause_analyze", _node_clause_analyze)
    graph.add_node("clause_generate_diffs", node_clause_generate_diffs)
    graph.add_node("clause_validate", node_clause_validate)
    graph.add_node("human_approval", node_human_approval)
    graph.add_node("save_clause", node_save_clause)
    graph.add_node("summarize", node_summarize)

    graph.set_entry_point("init")
    graph.add_edge("init", "parse_document")
    graph.add_edge("parse_document", "plan_review")         # 改动：插入 plan_review
    graph.add_conditional_edges(
        "plan_review",                                       # 改动：从 plan_review 出发
        route_next_clause_or_end,
        {"clause_analyze": "clause_analyze", "summarize": "summarize"},
    )
    # ... 其余边保持不变 ...
```

### 4.5 条件跳过 diffs 和 validate

```python
def route_after_analyze(state: ReviewGraphState) -> str:
    """根据 Orchestrator 计划决定是否跳过 diffs 生成。"""
    clause_id = state.get("current_clause_id", "")
    clause_plan = _get_clause_plan(state, clause_id)

    if clause_plan and clause_plan.get("skip_diffs"):
        return "save_clause"  # 跳过 diffs 和 validate，直接保存

    return "clause_generate_diffs"  # 正常流程
```

在 `build_review_graph` 中替换原有的固定边：

```python
# 改前
graph.add_edge("clause_analyze", "clause_generate_diffs")

# 改后
graph.add_conditional_edges(
    "clause_analyze",
    route_after_analyze,
    {"clause_generate_diffs": "clause_generate_diffs", "save_clause": "save_clause"},
)
```

---

## 5. `state.py` 和 `config.py` 改动

### 5.1 `state.py` 新增字段

```python
class ReviewGraphState(TypedDict, total=False):
    # ... 现有字段不变 ...

    # --- 新增：Orchestrator 相关 ---
    review_plan: Optional[Dict[str, Any]]
    # Orchestrator 生成的审查计划（ReviewPlan.model_dump()）
    # 仅在 use_orchestrator=True 时填充

    plan_version: int
    # 计划版本号，每次调整 +1
```

### 5.2 `config.py` 新增配置

```python
class AppSettings(BaseModel):
    # ... 现有字段不变 ...

    # --- 新增：Orchestrator 配置 ---
    use_orchestrator: bool = False
    # 是否启用 Orchestrator 编排模式
    # False: 使用原有的固定流程
    # True: 由 LLM 规划审查策略

    orchestrator_adjust_threshold: int = 1
    # 触发中间调度的高风险条款数阈值
```

### 5.3 环境变量映射

```
USE_ORCHESTRATOR=true                    → use_orchestrator=True
ORCHESTRATOR_ADJUST_THRESHOLD=1          → orchestrator_adjust_threshold=1
```

---

## 6. 测试要求

### 6.1 测试文件：`tests/test_orchestrator.py`

#### 6.1.1 审查规划测试

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from contract_review.graph.orchestrator import (
    generate_review_plan,
    maybe_adjust_plan,
    apply_adjustment,
    _build_default_plan,
    ClauseAnalysisPlan,
    ReviewPlan,
    PlanAdjustment,
)


def _make_fake_llm(response_text: str):
    client = AsyncMock()
    client.chat = AsyncMock(return_value=response_text)
    return client


def _sample_checklist():
    return [
        {"clause_id": "1.1", "clause_name": "定义", "priority": "low", "required_skills": ["get_clause_context"], "description": "定义条款"},
        {"clause_id": "4.1", "clause_name": "承包商义务", "priority": "critical", "required_skills": ["get_clause_context", "fidic_merge_gc_pc", "compare_with_baseline"], "description": "检查义务范围"},
        {"clause_id": "14.1", "clause_name": "合同价格", "priority": "critical", "required_skills": ["get_clause_context", "extract_financial_terms"], "description": "检查价格条款"},
        {"clause_id": "8.1", "clause_name": "开工日期", "priority": "medium", "required_skills": ["get_clause_context"], "description": "检查开工日期"},
    ]


class TestGenerateReviewPlan:
    @pytest.mark.asyncio
    async def test_basic_plan_generation(self):
        """LLM 返回合法 JSON 时，正确解析为 ReviewPlan。"""
        plan_json = json.dumps({
            "global_strategy": "critical 条款深度分析，定义条款快速扫描",
            "estimated_depth_distribution": {"quick": 1, "standard": 1, "deep": 2},
            "clause_plans": [
                {"clause_id": "4.1", "clause_name": "承包商义务", "analysis_depth": "deep", "max_iterations": 5, "priority_order": 0, "rationale": "critical"},
                {"clause_id": "14.1", "clause_name": "合同价格", "analysis_depth": "deep", "max_iterations": 5, "priority_order": 1, "rationale": "critical"},
                {"clause_id": "8.1", "clause_name": "开工日期", "analysis_depth": "standard", "max_iterations": 3, "priority_order": 2, "rationale": "medium"},
                {"clause_id": "1.1", "clause_name": "定义", "analysis_depth": "quick", "max_iterations": 1, "priority_order": 3, "skip_diffs": True, "skip_validate": True, "rationale": "定义条款"},
            ],
        })
        llm = _make_fake_llm(plan_json)

        plan = await generate_review_plan(llm, _sample_checklist(), domain_id="fidic")

        assert isinstance(plan, ReviewPlan)
        assert len(plan.clause_plans) == 4
        assert plan.clause_plans[0].clause_id == "4.1"  # priority_order=0 排第一
        assert plan.clause_plans[0].analysis_depth == "deep"
        assert plan.clause_plans[3].analysis_depth == "quick"
        assert plan.clause_plans[3].skip_diffs is True

    @pytest.mark.asyncio
    async def test_missing_clauses_get_default(self):
        """LLM 遗漏了某些条款时，自动补充默认计划。"""
        plan_json = json.dumps({
            "global_strategy": "test",
            "clause_plans": [
                {"clause_id": "4.1", "analysis_depth": "deep", "priority_order": 0},
            ],
        })
        llm = _make_fake_llm(plan_json)

        plan = await generate_review_plan(llm, _sample_checklist())

        planned_ids = {cp.clause_id for cp in plan.clause_plans}
        assert "1.1" in planned_ids   # 被自动补充
        assert "8.1" in planned_ids   # 被自动补充
        assert "14.1" in planned_ids  # 被自动补充

    @pytest.mark.asyncio
    async def test_llm_failure_returns_default_plan(self):
        """LLM 调用失败时，返回默认计划。"""
        llm = _make_fake_llm("")
        llm.chat = AsyncMock(side_effect=RuntimeError("API error"))

        plan = await generate_review_plan(llm, _sample_checklist())

        assert isinstance(plan, ReviewPlan)
        assert len(plan.clause_plans) == 4
        # 默认计划：critical → deep，其他 → standard
        critical_plans = [cp for cp in plan.clause_plans if cp.analysis_depth == "deep"]
        assert len(critical_plans) == 2  # 4.1 和 14.1

    @pytest.mark.asyncio
    async def test_invalid_depth_normalized(self):
        """analysis_depth 不在枚举中时，被修正为 standard。"""
        plan_json = json.dumps({
            "clause_plans": [
                {"clause_id": "4.1", "analysis_depth": "ultra_deep", "priority_order": 0},
            ],
        })
        llm = _make_fake_llm(plan_json)

        plan = await generate_review_plan(llm, _sample_checklist())

        cp_41 = next(cp for cp in plan.clause_plans if cp.clause_id == "4.1")
        assert cp_41.analysis_depth == "standard"  # 被修正


class TestDefaultPlan:
    def test_critical_gets_deep(self):
        plan = _build_default_plan(_sample_checklist())
        cp_41 = next(cp for cp in plan.clause_plans if cp.clause_id == "4.1")
        assert cp_41.analysis_depth == "deep"

    def test_non_critical_gets_standard(self):
        plan = _build_default_plan(_sample_checklist())
        cp_81 = next(cp for cp in plan.clause_plans if cp.clause_id == "8.1")
        assert cp_81.analysis_depth == "standard"

    def test_preserves_all_clauses(self):
        plan = _build_default_plan(_sample_checklist())
        assert len(plan.clause_plans) == 4
```

#### 6.1.2 中间调度测试

```python
class TestMaybeAdjustPlan:
    @pytest.mark.asyncio
    async def test_no_high_risk_no_adjustment(self):
        """没有高风险时，不触发调度。"""
        llm = _make_fake_llm("")
        risks = [{"risk_level": "low", "description": "test"}]
        remaining = [ClauseAnalysisPlan(clause_id="8.1")]

        result = await maybe_adjust_plan(llm, "4.1", risks, remaining, 1, 10)

        assert result.should_adjust is False
        llm.chat.assert_not_called()  # 不应调用 LLM

    @pytest.mark.asyncio
    async def test_high_risk_triggers_adjustment(self):
        """发现高风险时，触发 LLM 调度。"""
        adjustment_json = json.dumps({
            "should_adjust": True,
            "reason": "4.1 发现重大风险，需要提高 17.6 的审查深度",
            "adjusted_clauses": [
                {"clause_id": "17.6", "analysis_depth": "deep", "max_iterations": 5, "rationale": "关联风险"},
            ],
        })
        llm = _make_fake_llm(adjustment_json)
        risks = [{"risk_level": "high", "description": "义务范围被扩大"}]
        remaining = [ClauseAnalysisPlan(clause_id="17.6", analysis_depth="standard")]

        result = await maybe_adjust_plan(llm, "4.1", risks, remaining, 1, 10)

        assert result.should_adjust is True
        assert len(result.adjusted_clauses) == 1
        assert result.adjusted_clauses[0].clause_id == "17.6"

    @pytest.mark.asyncio
    async def test_midpoint_triggers_review(self):
        """达到 50% 进度时，触发中期复盘。"""
        llm = _make_fake_llm('{"should_adjust": false, "reason": "进展正常"}')
        risks = [{"risk_level": "low"}]
        remaining = [ClauseAnalysisPlan(clause_id="8.1")]

        result = await maybe_adjust_plan(llm, "4.1", risks, remaining, 5, 10)

        assert result.should_adjust is False
        llm.chat.assert_called_once()  # 应该调用了 LLM（中期复盘）


class TestApplyAdjustment:
    def test_no_adjustment(self):
        plan = ReviewPlan(clause_plans=[
            ClauseAnalysisPlan(clause_id="4.1", analysis_depth="standard"),
        ])
        adj = PlanAdjustment(should_adjust=False)

        result = apply_adjustment(plan, adj)
        assert result.clause_plans[0].analysis_depth == "standard"  # 不变

    def test_depth_upgraded(self):
        plan = ReviewPlan(clause_plans=[
            ClauseAnalysisPlan(clause_id="17.6", analysis_depth="standard"),
            ClauseAnalysisPlan(clause_id="8.1", analysis_depth="standard"),
        ])
        adj = PlanAdjustment(
            should_adjust=True,
            adjusted_clauses=[ClauseAnalysisPlan(clause_id="17.6", analysis_depth="deep", max_iterations=5)],
        )

        result = apply_adjustment(plan, adj)
        assert result.clause_plans[0].analysis_depth == "deep"   # 被调整
        assert result.clause_plans[1].analysis_depth == "standard"  # 不变
        assert result.plan_version == 2

    def test_unmatched_clause_ignored(self):
        plan = ReviewPlan(clause_plans=[
            ClauseAnalysisPlan(clause_id="4.1", analysis_depth="standard"),
        ])
        adj = PlanAdjustment(
            should_adjust=True,
            adjusted_clauses=[ClauseAnalysisPlan(clause_id="99.9", analysis_depth="deep")],
        )

        result = apply_adjustment(plan, adj)
        assert result.clause_plans[0].analysis_depth == "standard"  # 不变
```

#### 6.1.3 Builder 集成测试

```python
class TestOrchestratorIntegration:
    @pytest.mark.asyncio
    async def test_orchestrator_disabled_skips_planning(self, monkeypatch):
        """use_orchestrator=False 时，node_plan_review 返回空。"""
        pytest.importorskip("langgraph")
        from contract_review.graph.builder import node_plan_review

        fake_settings = MagicMock()
        fake_settings.use_orchestrator = False
        monkeypatch.setattr("contract_review.graph.builder.get_settings", lambda: fake_settings)

        state = {"review_checklist": [{"clause_id": "4.1"}]}
        result = await node_plan_review(state)
        assert result == {}

    def test_route_after_analyze_skip_diffs(self):
        """skip_diffs=True 时，跳过 diffs 生成。"""
        pytest.importorskip("langgraph")
        from contract_review.graph.builder import route_after_analyze

        state = {
            "current_clause_id": "1.1",
            "review_plan": {
                "clause_plans": [
                    {"clause_id": "1.1", "skip_diffs": True, "analysis_depth": "quick"},
                ],
            },
        }
        assert route_after_analyze(state) == "save_clause"

    def test_route_after_analyze_normal_flow(self):
        """skip_diffs=False 时，正常进入 diffs 生成。"""
        pytest.importorskip("langgraph")
        from contract_review.graph.builder import route_after_analyze

        state = {
            "current_clause_id": "4.1",
            "review_plan": {
                "clause_plans": [
                    {"clause_id": "4.1", "skip_diffs": False, "analysis_depth": "deep"},
                ],
            },
        }
        assert route_after_analyze(state) == "clause_generate_diffs"

    def test_route_after_analyze_no_plan(self):
        """没有 Orchestrator 计划时，走正常流程。"""
        pytest.importorskip("langgraph")
        from contract_review.graph.builder import route_after_analyze

        state = {"current_clause_id": "4.1"}
        assert route_after_analyze(state) == "clause_generate_diffs"
```

---

## 7. 运行命令

### 7.1 单元测试

```bash
# 运行 Orchestrator 测试
PYTHONPATH=backend/src python -m pytest tests/test_orchestrator.py -x -q
```

### 7.2 全量回归测试

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

---

## 8. 验收标准

### 8.1 功能验收

1. **审查规划**
   - `generate_review_plan` 能根据 checklist 生成结构化的审查计划
   - 计划包含每个条款的审查深度、工具集、执行顺序
   - LLM 遗漏的条款被自动补充默认计划
   - LLM 失败时回退到默认计划

2. **中间调度**
   - `maybe_adjust_plan` 在发现高风险时触发 LLM 调度
   - 在 50% 进度时触发中期复盘
   - 无触发条件时不调用 LLM（节省成本）
   - `apply_adjustment` 正确将调整应用到现有计划

3. **图集成**
   - `node_plan_review` 正确插入到 `parse_document` 和 `clause_analyze` 之间
   - `route_after_analyze` 根据 `skip_diffs` 决定是否跳过 diffs 生成
   - `node_clause_analyze` 从 Orchestrator 计划中读取审查参数

4. **配置控制**
   - `use_orchestrator=False`（默认）时，行为与改造前完全一致
   - `use_orchestrator=True` 时，启用 Orchestrator 编排

### 8.2 向后兼容验收

5. **零回归**
   - 全量测试通过，无新增失败
   - `use_orchestrator=False` 时，图结构和行为与改造前一致
   - `node_plan_review` 在非 Orchestrator 模式下返回空 dict，不影响后续节点

6. **与 SPEC-20 的兼容**
   - Orchestrator 的 `suggested_tools` 和 `max_iterations` 正确传递给 ReAct Agent
   - ReAct Agent 不感知 Orchestrator 的存在——它只看到参数变化

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM 规划质量不稳定 | 审查深度分配不合理 | `_build_default_plan` 兜底；可人工审核计划后再执行 |
| 规划 LLM 调用增加成本 | 每次审查多一次 LLM 调用 | 规划只调用一次；中间调度有条件触发 |
| 中间调度频繁调整计划 | 审查策略不稳定 | `orchestrator_adjust_threshold` 控制触发频率；只在高风险时触发 |
| `skip_diffs` 导致遗漏修改建议 | 低优先级条款的风险未被处理 | quick 深度仍然做风险识别，只跳过 diffs 生成；用户可手动要求补充 |
| 图结构变更导致回归 | 现有测试失败 | `node_plan_review` 在非 Orchestrator 模式下是 no-op；`route_after_analyze` 无计划时走默认路径 |

---

## 10. 三步走改造总结

### 10.1 完整架构图

```
改造前（硬编码流水线）：
═══════════════════════
init → parse → [for clause in checklist]:
                  analyze(hardcoded skills) → diffs → validate → save
               → summarize

改造后（AI 自主编排）：
═══════════════════════
init → parse → Orchestrator 规划（SPEC-21）
               ↓
               [for clause in sorted_plan]:
                  ReAct Agent（SPEC-20）
                  ├─ LLM 自主选择工具（SPEC-19 提供 tool definitions）
                  ├─ 执行工具 → 反馈结果 → 继续选择
                  └─ 输出风险分析
                  ↓
                  route_after_analyze
                  ├─ quick → save（跳过 diffs/validate）
                  └─ standard/deep → diffs → validate → save
                  ↓
                  Orchestrator 中间调度（条件触发）
               → summarize
```

### 10.2 三个 SPEC 的依赖关系

```
SPEC-19（工具自描述层）
  ├─ SkillRegistration.to_tool_definition()
  ├─ SkillRegistration.prepare_input_fn
  ├─ tool_adapter.skills_to_tool_definitions()
  ├─ tool_adapter.parse_tool_calls()
  ├─ SkillDispatcher.get_tool_definitions()
  └─ SkillDispatcher.prepare_and_call()
       │
       ▼
SPEC-20（ReAct Agent 节点）
  ├─ react_agent_loop()          ← 使用 SPEC-19 的 tool definitions + prepare_and_call
  ├─ build_react_agent_messages() ← 使用 SPEC-19 的 dispatcher.get_registration
  └─ _run_react_branch()         ← 集成到 node_clause_analyze
       │
       ▼
SPEC-21（Orchestrator 编排层）
  ├─ generate_review_plan()      ← 独立的 LLM 调用，不依赖 SPEC-19/20 的接口
  ├─ maybe_adjust_plan()         ← 独立的 LLM 调用
  ├─ node_plan_review()          ← 新增图节点
  ├─ route_after_analyze()       ← 新增路由函数
  └─ 参数传递                    ← 将 Orchestrator 的决策传给 SPEC-20 的 ReAct Agent
```

### 10.3 配置矩阵

| 配置组合 | 行为 |
|---------|------|
| `react=False, orchestrator=False` | 原有硬编码模式（默认，零改动） |
| `react=True, orchestrator=False` | ReAct Agent 自主选择工具，但流程固定 |
| `react=False, orchestrator=True` | Orchestrator 规划深度和顺序，但工具选择仍硬编码 |
| `react=True, orchestrator=True` | 完整的 AI 自主编排模式（目标状态） |

每种组合都是有效的，可以逐步开启，随时回退。

### 10.4 实施建议

1. **先实施 SPEC-19**：纯增量改造，风险最低，独立价值最高（消除 240 行 if/elif）
2. **再实施 SPEC-20**：在 SPEC-19 基础上，`use_react_agent=False` 默认关闭，可以充分测试后再开启
3. **最后实施 SPEC-21**：在 SPEC-19+20 基础上，`use_orchestrator=False` 默认关闭
4. **每步都可独立验证和回滚**：三个 SPEC 之间是单向依赖，回滚不影响前序 SPEC
