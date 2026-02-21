# SPEC-4: LangGraph 状态机骨架

> 优先级：核心（Gen 3.0 架构的中枢）
> 前置依赖：Spec-1（SkillDispatcher）、Spec-2（数据模型）、Spec-3（StructureParser）
> 预计新建文件：2 个 | 修改文件：1 个
> 参考：GEN3_GAP_ANALYSIS.md 第 3 章、第 9.4-9.5 章

---

## 1. 目标

引入 LangGraph 构建合同审查状态机，实现：
- 文档解析 → 条款级循环审查 → 修改建议生成 → 人工审批 → 汇总的完整流程
- Human-in-the-loop：Agent 生成修改建议后挂起（interrupt），等待用户 Approve/Reject
- 条款级循环：按 ReviewChecklist 逐条审查，每个条款调用所需 Skills
- 跨条款发现共享（Scratchpad）：前序条款的发现可供后续条款参考
- 循环推理：验证失败时可回到修改建议重新生成（带最大重试限制）

本 Spec 实现最小可运行骨架，节点内的 LLM 调用用 stub 替代。

## 2. 新增依赖

```
# backend/requirements.txt 或 pyproject.toml 追加
langgraph>=0.2.0
```

## 3. 需要创建的文件

### 3.1 `backend/src/contract_review/graph/__init__.py`

空文件，标记 graph 为 Python 包。

### 3.2 `backend/src/contract_review/graph/state.py`

LangGraph 状态定义。

```python
"""
LangGraph 状态定义

ReviewGraphState 是状态机的核心数据结构，
在节点间流转并累积审查结果。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict

from ..models import (
    RiskPoint,
    ModificationSuggestion,
    ActionRecommendation,
    ReviewChecklistItem,
    ClauseFindings,
    DocumentDiff,
    DocumentStructure,
    TaskDocument,
    DiffBatch,
)


class ReviewGraphState(TypedDict, total=False):
    """
    合同审查状态机的状态

    所有节点共享此状态，通过 LangGraph 的 reducer 机制累积数据。
    """

    # === 任务基本信息（初始化时设置，后续只读）===
    task_id: str
    our_party: str
    material_type: str
    language: str
    domain_id: Optional[str]                # 领域插件 ID
    domain_subtype: Optional[str]           # 如 "silver_book"

    # === 文档数据 ===
    documents: List[TaskDocument]           # 关联的所有文档
    primary_structure: Optional[DocumentStructure]  # 主文档的结构化解析结果

    # === 审查清单（由领域插件或通用流程提供）===
    review_checklist: List[ReviewChecklistItem]
    current_clause_index: int               # 当前审查到第几个条款

    # === 条款级审查结果（Scratchpad）===
    findings: Dict[str, ClauseFindings]     # clause_id → 该条款的发现
    global_issues: List[str]                # 全局性问题

    # === 当前条款的工作区 ===
    current_clause_id: Optional[str]
    current_clause_text: Optional[str]
    current_risks: List[RiskPoint]
    current_diffs: List[DocumentDiff]

    # === 循环控制 ===
    validation_result: Optional[str]        # "pass" / "fail"
    clause_retry_count: int                 # 当前条款的重试次数
    max_retries: int                        # 最大重试次数（默认 2）

    # === 人机协同 ===
    pending_diffs: List[DocumentDiff]       # 等待用户审批的 Diff 列表
    user_decisions: Dict[str, str]          # diff_id → "approve"/"reject"
    user_feedback: Dict[str, str]           # diff_id → 用户反馈文本

    # === 最终汇总 ===
    all_risks: List[RiskPoint]
    all_diffs: List[DocumentDiff]
    all_actions: List[ActionRecommendation]
    summary_notes: str

    # === 流程控制 ===
    error: Optional[str]
    is_complete: bool
```

### 3.3 `backend/src/contract_review/graph/builder.py`

LangGraph 图构建器 — 定义节点和边。

```python
"""
LangGraph 合同审查图构建器

定义审查流程的所有节点和转换边。
核心流程：
  START → init → parse_document → next_clause_or_end
    → [循环] clause_analyze → clause_generate_diffs → clause_validate
        → (pass) human_approval → (approve) save_clause → next_clause_or_end
        → (fail) clause_generate_diffs (重试)
    → summarize → END
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import ReviewGraphState
from ..skills.dispatcher import SkillDispatcher
from ..structure_parser import StructureParser

logger = logging.getLogger(__name__)


# ============================================================
# 节点函数（每个函数接收 state，返回 state 的部分更新）
# ============================================================

async def node_init(state: ReviewGraphState) -> Dict[str, Any]:
    """
    初始化节点

    设置默认值，准备审查环境。
    """
    return {
        "current_clause_index": 0,
        "findings": {},
        "global_issues": [],
        "all_risks": [],
        "all_diffs": [],
        "all_actions": [],
        "clause_retry_count": 0,
        "max_retries": state.get("max_retries", 2),
        "is_complete": False,
        "error": None,
    }


async def node_parse_document(state: ReviewGraphState) -> Dict[str, Any]:
    """
    文档解析节点

    使用 StructureParser 解析主文档的条款结构。
    如果没有领域插件提供 checklist，则生成通用 checklist。
    """
    documents = state.get("documents", [])
    primary_docs = [d for d in documents if d.get("role") == "primary"]

    if not primary_docs:
        return {"error": "未找到主文档", "is_complete": True}

    # 解析主文档结构
    # 注意：实际实现中需要从 storage 加载文档文本
    # 此处骨架假设 primary_structure 已在外部设置
    primary_structure = state.get("primary_structure")

    # 如果没有预设的 checklist，从文档结构生成通用 checklist
    checklist = state.get("review_checklist", [])
    if not checklist and primary_structure:
        checklist = _generate_generic_checklist(primary_structure)

    return {
        "primary_structure": primary_structure,
        "review_checklist": checklist,
    }


async def node_clause_analyze(state: ReviewGraphState) -> Dict[str, Any]:
    """
    条款分析节点

    获取当前条款的上下文，调用 Skills 进行风险识别。
    """
    checklist = state.get("review_checklist", [])
    index = state.get("current_clause_index", 0)

    if index >= len(checklist):
        return {}  # 不应到达此处，由路由控制

    item = checklist[index]
    clause_id = item["clause_id"] if isinstance(item, dict) else item.clause_id

    logger.info(f"开始分析条款: {clause_id}")

    # TODO: 实际实现中通过 SkillDispatcher 调用:
    # 1. get_clause_context → 获取条款文本
    # 2. compare_with_baseline → 偏离分析（如有基线）
    # 3. extract_financial_terms → 财务条款提取（如需要）
    # 当前骨架返回空风险列表

    # 获取前序条款的发现（Scratchpad），供分析参考
    prior_findings = state.get("findings", {})

    return {
        "current_clause_id": clause_id,
        "current_risks": [],       # TODO: 替换为 Skill 调用结果
        "current_diffs": [],
        "clause_retry_count": 0,   # 新条款重置重试计数
    }


async def node_clause_generate_diffs(state: ReviewGraphState) -> Dict[str, Any]:
    """
    修改建议生成节点

    基于风险分析结果，生成 DocumentDiff 列表。
    """
    clause_id = state.get("current_clause_id", "")
    risks = state.get("current_risks", [])

    logger.info(f"为条款 {clause_id} 生成修改建议 (风险数: {len(risks)})")

    # TODO: 实际实现中通过 SkillDispatcher 调用:
    # draft_redline_comment → 生成结构化 Diff
    # 当前骨架返回空 Diff 列表

    return {
        "current_diffs": [],  # TODO: 替换为 Skill 调用结果
    }


async def node_clause_validate(state: ReviewGraphState) -> Dict[str, Any]:
    """
    策略验证节点

    验证生成的修改建议是否合理。
    返回 validation_result: "pass" 或 "fail"。
    """
    diffs = state.get("current_diffs", [])
    retry_count = state.get("clause_retry_count", 0)

    # TODO: 实际实现中通过 Skill 验证修改策略
    # 当前骨架直接通过
    validation = "pass"

    return {
        "validation_result": validation,
        "clause_retry_count": retry_count + 1 if validation == "fail" else retry_count,
    }


async def node_human_approval(state: ReviewGraphState) -> Dict[str, Any]:
    """
    人工审批节点（INTERRUPT 挂起点）

    将当前条款的 Diffs 设为 pending，等待用户操作。
    LangGraph 的 interrupt 机制会在此暂停图执行。

    用户通过 API 提交 approve/reject 后，
    外部代码调用 graph.update_state() 注入 user_decisions，
    然后 resume 图执行。
    """
    diffs = state.get("current_diffs", [])

    # 如果没有 Diff 需要审批，直接跳过
    if not diffs:
        return {"pending_diffs": [], "user_decisions": {}}

    return {
        "pending_diffs": diffs,
        # user_decisions 和 user_feedback 将由外部注入
    }


async def node_save_clause(state: ReviewGraphState) -> Dict[str, Any]:
    """
    保存条款审查结果

    将当前条款的发现写入 Scratchpad (findings)，
    将已批准的 Diffs 累积到 all_diffs。
    """
    clause_id = state.get("current_clause_id", "")
    risks = state.get("current_risks", [])
    diffs = state.get("current_diffs", [])
    user_decisions = state.get("user_decisions", {})

    # 根据用户决策过滤 Diffs
    approved_diffs = []
    for diff in diffs:
        diff_id = diff.get("diff_id") if isinstance(diff, dict) else diff.diff_id
        decision = user_decisions.get(diff_id, "approve")
        if decision == "approve":
            approved_diffs.append(diff)

    # 更新 Scratchpad
    findings = dict(state.get("findings", {}))
    findings[clause_id] = {
        "clause_id": clause_id,
        "risks": risks,
        "diffs": approved_diffs,
        "completed": True,
    }

    # 累积到全局结果
    all_risks = list(state.get("all_risks", []))
    all_risks.extend(risks)
    all_diffs = list(state.get("all_diffs", []))
    all_diffs.extend(approved_diffs)

    return {
        "findings": findings,
        "all_risks": all_risks,
        "all_diffs": all_diffs,
        "current_clause_index": state.get("current_clause_index", 0) + 1,
    }


async def node_summarize(state: ReviewGraphState) -> Dict[str, Any]:
    """
    汇总节点

    所有条款审查完成后，生成最终汇总。
    """
    all_risks = state.get("all_risks", [])
    all_diffs = state.get("all_diffs", [])
    findings = state.get("findings", {})

    summary = (
        f"审查完成。共审查 {len(findings)} 个条款，"
        f"发现 {len(all_risks)} 个风险点，"
        f"生成 {len(all_diffs)} 条修改建议。"
    )

    logger.info(summary)

    return {
        "summary_notes": summary,
        "is_complete": True,
    }


# ============================================================
# 路由函数（条件边）
# ============================================================

def route_next_clause_or_end(state: ReviewGraphState) -> str:
    """
    判断是否还有条款需要审查

    Returns:
        "clause_analyze" — 继续审查下一个条款
        "summarize" — 所有条款已完成，进入汇总
    """
    checklist = state.get("review_checklist", [])
    index = state.get("current_clause_index", 0)

    if state.get("error"):
        return "summarize"

    if index < len(checklist):
        return "clause_analyze"
    else:
        return "summarize"


def route_validation(state: ReviewGraphState) -> str:
    """
    验证结果路由

    Returns:
        "human_approval" — 验证通过，进入人工审批
        "clause_generate_diffs" — 验证失败，重新生成（有重试上限）
        "save_clause" — 超过重试上限，跳过该条款
    """
    validation = state.get("validation_result", "pass")
    retry_count = state.get("clause_retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if validation == "pass":
        return "human_approval"
    elif retry_count < max_retries:
        return "clause_generate_diffs"
    else:
        logger.warning(
            f"条款 {state.get('current_clause_id')} "
            f"超过最大重试次数 ({max_retries})，跳过"
        )
        return "save_clause"


def route_after_approval(state: ReviewGraphState) -> str:
    """
    审批后路由

    当前简化实现：审批后直接保存。
    后续可扩展：reject 时回到 generate_diffs 重新生成。
    """
    return "save_clause"


# ============================================================
# 辅助函数
# ============================================================

def _generate_generic_checklist(structure) -> List[Dict[str, Any]]:
    """
    从文档结构生成通用审查清单

    对于没有领域插件的合同，将顶级条款作为审查清单。
    """
    checklist = []
    clauses = structure.get("clauses", []) if isinstance(structure, dict) else structure.clauses
    for clause in clauses:
        clause_id = clause.get("clause_id") if isinstance(clause, dict) else clause.clause_id
        title = clause.get("title", "") if isinstance(clause, dict) else clause.title
        checklist.append({
            "clause_id": clause_id,
            "clause_name": title,
            "priority": "medium",
            "required_skills": ["get_clause_context"],
            "description": f"审查条款 {clause_id}",
        })
    return checklist


# ============================================================
# 图构建
# ============================================================

def build_review_graph(
    checkpointer=None,
    interrupt_before: List[str] = None,
) -> StateGraph:
    """
    构建合同审查 LangGraph 图

    Args:
        checkpointer: 状态持久化后端（默认 MemorySaver）
        interrupt_before: 在哪些节点前中断（默认在 human_approval 前）

    Returns:
        编译后的 StateGraph，可直接 invoke/stream
    """
    if interrupt_before is None:
        interrupt_before = ["human_approval"]

    graph = StateGraph(ReviewGraphState)

    # 添加节点
    graph.add_node("init", node_init)
    graph.add_node("parse_document", node_parse_document)
    graph.add_node("clause_analyze", node_clause_analyze)
    graph.add_node("clause_generate_diffs", node_clause_generate_diffs)
    graph.add_node("clause_validate", node_clause_validate)
    graph.add_node("human_approval", node_human_approval)
    graph.add_node("save_clause", node_save_clause)
    graph.add_node("summarize", node_summarize)

    # 设置入口
    graph.set_entry_point("init")

    # 添加边
    graph.add_edge("init", "parse_document")
    graph.add_conditional_edges(
        "parse_document",
        route_next_clause_or_end,
        {"clause_analyze": "clause_analyze", "summarize": "summarize"},
    )
    graph.add_edge("clause_analyze", "clause_generate_diffs")
    graph.add_edge("clause_generate_diffs", "clause_validate")
    graph.add_conditional_edges(
        "clause_validate",
        route_validation,
        {
            "human_approval": "human_approval",
            "clause_generate_diffs": "clause_generate_diffs",
            "save_clause": "save_clause",
        },
    )
    graph.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {"save_clause": "save_clause"},
    )
    graph.add_conditional_edges(
        "save_clause",
        route_next_clause_or_end,
        {"clause_analyze": "clause_analyze", "summarize": "summarize"},
    )
    graph.add_edge("summarize", END)

    # 编译
    memory = checkpointer or MemorySaver()
    compiled = graph.compile(
        checkpointer=memory,
        interrupt_before=interrupt_before,
    )

    return compiled
```

## 4. 需要修改的文件

### 4.1 `backend/requirements.txt` 或 `pyproject.toml`

追加 LangGraph 依赖：

```
langgraph>=0.2.0
```

## 5. 目录结构（完成后）

```
backend/src/contract_review/
├── graph/
│   ├── __init__.py              # 新建：包标记
│   ├── state.py                 # 新建：状态定义
│   └── builder.py               # 新建：图构建器 + 节点函数
└── ... (其他文件不动)
```

## 6. 流程图

```
                    ┌─────────┐
                    │  START  │
                    └────┬────┘
                         │
                    ┌────▼────┐
                    │  init   │
                    └────┬────┘
                         │
                ┌────────▼────────┐
                │ parse_document  │
                └────────┬────────┘
                         │
              ┌──────────▼──────────┐
              │ route: next_clause  │
              │   or_end?           │
              └──┬──────────────┬───┘
                 │              │
          有条款待审       全部完成
                 │              │
          ┌──────▼──────┐  ┌───▼──────┐
          │clause_analyze│  │summarize │
          └──────┬──────┘  └───┬──────┘
                 │              │
     ┌───────────▼───────────┐  │
     │clause_generate_diffs  │  END
     └───────────┬───────────┘
                 │
       ┌─────────▼─────────┐
       │ clause_validate    │
       └──┬─────────┬──┬───┘
          │         │  │
       pass      fail  超过重试
          │         │  │
  ┌───────▼──┐      │  │
  │ human_   │      │  │
  │ approval │◄─────┘  │
  │(INTERRUPT│  重试    │
  │ 挂起)    │         │
  └────┬─────┘         │
       │               │
  ┌────▼─────┐    ┌────▼─────┐
  │save_clause│◄──┤ (跳过)   │
  └────┬─────┘    └──────────┘
       │
       └──→ route: next_clause_or_end (循环)
```

## 7. Human-in-the-loop 交互流程

```
1. 图执行到 human_approval 节点前，LangGraph 自动中断（interrupt_before）
2. API 层检测到中断，向前端推送 SSE 事件：pending_diffs 列表
3. 前端渲染红线标注，用户逐条 Approve/Reject
4. 用户提交审批结果，API 层调用:
     graph.update_state(config, {
         "user_decisions": {"diff_id_1": "approve", "diff_id_2": "reject"},
         "user_feedback": {"diff_id_2": "赔偿上限应改为合同总额的100%"},
     })
5. API 层调用 graph.invoke(None, config) 恢复执行
6. human_approval 节点读取 user_decisions，路由到 save_clause
7. save_clause 根据 user_decisions 过滤 Diffs，保存结果
8. 继续下一个条款或进入汇总
```

## 8. 验收标准

1. `build_review_graph()` 返回可执行的编译图
2. 空 checklist 时，图能正常走完 init → parse_document → summarize → END
3. 有 checklist 时，图能按条款循环：clause_analyze → generate_diffs → validate → human_approval（中断）
4. 中断后，通过 `update_state` 注入 user_decisions，`invoke` 恢复执行能继续到 save_clause
5. `route_validation` 在 fail 时路由回 generate_diffs，超过 max_retries 时路由到 save_clause
6. `save_clause` 正确累积 findings 和 all_diffs
7. 所有新代码通过 `python -m py_compile` 语法检查

## 9. 验证用测试代码

```python
# tests/test_review_graph.py
import pytest
from contract_review.graph.builder import build_review_graph
from contract_review.graph.state import ReviewGraphState


class TestReviewGraph:
    def test_build_graph(self):
        """测试图构建"""
        graph = build_review_graph()
        assert graph is not None

    @pytest.mark.asyncio
    async def test_empty_checklist(self):
        """测试空 checklist — 直接走到汇总"""
        graph = build_review_graph(interrupt_before=[])  # 不中断，方便测试

        initial_state = {
            "task_id": "test_001",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "en",
            "documents": [],
            "review_checklist": [],
        }

        config = {"configurable": {"thread_id": "test_empty"}}
        result = await graph.ainvoke(initial_state, config)

        assert result["is_complete"] is True
        assert "审查完成" in result.get("summary_notes", "")

    @pytest.mark.asyncio
    async def test_single_clause_no_interrupt(self):
        """测试单条款审查（不中断）"""
        graph = build_review_graph(interrupt_before=[])

        initial_state = {
            "task_id": "test_002",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "en",
            "documents": [],
            "review_checklist": [
                {
                    "clause_id": "14.2",
                    "clause_name": "预付款",
                    "priority": "high",
                    "required_skills": ["get_clause_context"],
                    "description": "核查预付款条款",
                }
            ],
        }

        config = {"configurable": {"thread_id": "test_single"}}
        result = await graph.ainvoke(initial_state, config)

        assert result["is_complete"] is True
        assert result["current_clause_index"] == 1
        assert "14.2" in result.get("findings", {})

    @pytest.mark.asyncio
    async def test_interrupt_and_resume(self):
        """测试 Human-in-the-loop 中断与恢复"""
        graph = build_review_graph(interrupt_before=["human_approval"])

        initial_state = {
            "task_id": "test_003",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "en",
            "documents": [],
            "review_checklist": [
                {
                    "clause_id": "17.6",
                    "clause_name": "责任限制",
                    "priority": "critical",
                    "required_skills": [],
                    "description": "核查赔偿上限",
                }
            ],
        }

        config = {"configurable": {"thread_id": "test_interrupt"}}

        # 第一次执行 — 应在 human_approval 前中断
        result = await graph.ainvoke(initial_state, config)

        # 获取当前状态快照
        snapshot = graph.get_state(config)
        assert snapshot.next  # 应有待执行的下一个节点

        # 注入用户审批决策
        graph.update_state(config, {
            "user_decisions": {},
            "user_feedback": {},
        })

        # 恢复执行
        result = await graph.ainvoke(None, config)
        assert result["is_complete"] is True

    @pytest.mark.asyncio
    async def test_multiple_clauses(self):
        """测试多条款循环"""
        graph = build_review_graph(interrupt_before=[])

        initial_state = {
            "task_id": "test_004",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "en",
            "documents": [],
            "review_checklist": [
                {"clause_id": "4.1", "clause_name": "一般义务",
                 "priority": "critical", "required_skills": [], "description": ""},
                {"clause_id": "14.2", "clause_name": "预付款",
                 "priority": "high", "required_skills": [], "description": ""},
                {"clause_id": "20.1", "clause_name": "索赔",
                 "priority": "critical", "required_skills": [], "description": ""},
            ],
        }

        config = {"configurable": {"thread_id": "test_multi"}}
        result = await graph.ainvoke(initial_state, config)

        assert result["is_complete"] is True
        assert result["current_clause_index"] == 3
        assert len(result.get("findings", {})) == 3
```

## 10. 注意事项

- `interrupt_before=["human_approval"]` 是 LangGraph 的内置机制，图执行到该节点前自动暂停
- 恢复执行时调用 `graph.ainvoke(None, config)`，`None` 表示不提供新输入，从中断点继续
- `MemorySaver` 是内存中的 checkpointer，生产环境应替换为持久化方案（如 PostgreSQL）
- 节点函数返回的 dict 是对 state 的**部分更新**（patch），不是完整替换
- `route_validation` 的重试上限（max_retries=2）防止死循环
- 当前所有节点内的 Skill 调用都是 stub（返回空列表），后续 Spec 完成后逐步替换
- 不要修改任何现有的 `review_engine.py` 或 `interactive_engine.py`
