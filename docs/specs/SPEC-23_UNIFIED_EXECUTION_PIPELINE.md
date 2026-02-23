# SPEC-23: 统一执行管线与模式切换（Unified Execution Pipeline）

> 优先级：高（架构整合两步走的第二步，完成架构转型的最后一环）
> 前置依赖：SPEC-22（移除硬编码 Skill 构建器）
> 预计新建文件：1 个 | 修改文件：4 个
> 范围：图级别改造，统一执行路径，消除配置歧义

---

## 0. 背景与动机

### 0.1 当前状态（SPEC-22 完成后）

经过 SPEC-19/20/21 的组件开发和 SPEC-22 的冗余清理，系统中仍然存在以下架构问题：

**问题 1：双开关产生无意义组合**

当前有两个独立的 bool 开关：`use_react_agent` 和 `use_orchestrator`，产生 4 种组合：

| 组合 | 行为 | 是否有意义 |
|------|------|-----------|
| `react=False, orchestrator=False` | 纯 LLM 分析（无工具调用） | ✓ 遗留模式 |
| `react=True, orchestrator=False` | ReAct 自主选工具，但流程固定 | △ 半成品 |
| `react=False, orchestrator=True` | Orchestrator 规划了 suggested_tools，但没有 ReAct 来执行 | ✗ 无意义 |
| `react=True, orchestrator=True` | 完整的 AI 编排模式 | ✓ 目标状态 |

组合 3 是一个**逻辑矛盾**：Orchestrator 花费一次 LLM 调用生成了包含 `suggested_tools` 和 `max_iterations` 的计划，但因为 ReAct 未启用，这些参数被完全忽略，Skill 调用走的是 `dispatcher.prepare_and_call()` 的固定循环。

**问题 2：`node_clause_analyze` 内部仍有多条执行路径**

SPEC-22 删除了 `_build_skill_input`，但 `node_clause_analyze` 内部仍然有三条分支：

```python
# 分支 1：ReAct Agent（use_react_agent=True）
if use_react and llm_client and dispatcher and primary_structure:
    return await _run_react_branch(...)

# 分支 2：dispatcher 固定循环（SPEC-22 后的默认路径）
if dispatcher and primary_structure:
    for skill_id in required_skills:
        result = await dispatcher.prepare_and_call(...)

# 分支 3：纯 LLM 分析（无 dispatcher）
if llm_client:
    response = await llm_client.chat(analyze_messages)
```

这三条分支的选择逻辑分散在函数内部，难以理解和维护。

**问题 3：缺少端到端集成测试**

当前测试都是分层 mock 的：
- `test_orchestrator.py` mock 了 LLM，测试 orchestrator 逻辑
- `test_review_graph.py` mock 了 LLM 和 dispatcher，测试图流转
- `test_react_agent.py` mock 了 LLM 和 dispatcher，测试 ReAct 循环

没有一个测试验证 **orchestrator → ReAct → dispatcher → skill** 的完整链路。

### 0.2 目标

1. 合并双开关为单一 `execution_mode` 枚举，消除无意义组合
2. 重构 `node_clause_analyze` 为清晰的模式分发
3. 补充端到端集成测试
4. 保留 `legacy` 模式作为过渡期兜底

### 0.3 设计原则

1. **一个开关，两种模式**：`legacy`（遗留）和 `gen3`（AI 编排），不存在中间状态
2. **gen3 模式 = orchestrator + ReAct**：两者绑定，不可单独开启
3. **legacy 模式完全不变**：不触碰遗留路径的任何逻辑
4. **gen3 模式不保留 fallback 到 legacy**：ReAct 失败时记录错误，不回退到硬编码循环（硬编码循环已在 SPEC-22 中删除）

---

## 1. 设计方案

### 1.1 `execution_mode` 枚举

```python
# config.py 新增
from enum import Enum

class ExecutionMode(str, Enum):
    LEGACY = "legacy"    # 遗留模式：dispatcher 固定循环 + LLM 分析
    GEN3 = "gen3"        # AI 编排模式：orchestrator + ReAct + dispatcher
```

### 1.2 配置映射

```python
class Settings(BaseModel):
    # --- 废弃（保留但标记 deprecated）---
    use_react_agent: bool = False       # deprecated, 由 execution_mode 控制
    use_orchestrator: bool = False      # deprecated, 由 execution_mode 控制

    # --- 新增 ---
    execution_mode: str = "legacy"      # "legacy" | "gen3"
    react_max_iterations: int = 5       # 保留，gen3 模式下的默认值
    react_temperature: float = 0.1      # 保留
```

**向后兼容逻辑**：

```python
def get_execution_mode(settings: Settings) -> ExecutionMode:
    """解析执行模式，兼容旧配置。

    优先级：
    1. 如果显式设置了 execution_mode → 使用它
    2. 否则，从旧开关推断：
       - use_orchestrator=True OR use_react_agent=True → gen3
       - 都为 False → legacy
    """
    mode_str = getattr(settings, "execution_mode", "legacy")

    # 如果显式设置了 execution_mode，直接使用
    if mode_str != "legacy":
        return ExecutionMode(mode_str)

    # 兼容旧配置：任一旧开关为 True → gen3
    if getattr(settings, "use_orchestrator", False) or getattr(settings, "use_react_agent", False):
        return ExecutionMode.GEN3

    return ExecutionMode.LEGACY
```

### 1.3 环境变量

```
EXECUTION_MODE=gen3              → execution_mode="gen3"
EXECUTION_MODE=legacy            → execution_mode="legacy"

# 旧环境变量仍然生效（向后兼容）
USE_REACT_AGENT=true             → 推断为 gen3
USE_ORCHESTRATOR=true            → 推断为 gen3
```

### 1.4 `node_clause_analyze` 重构

```python
async def node_clause_analyze(
    state: ReviewGraphState, dispatcher: SkillDispatcher | None = None
) -> Dict[str, Any]:
    # ... 提取 checklist item 信息（不变）...

    settings = get_settings()
    mode = get_execution_mode(settings)

    if mode == ExecutionMode.GEN3:
        return await _analyze_gen3(
            state=state,
            dispatcher=dispatcher,
            clause_id=clause_id,
            clause_name=clause_name,
            description=description,
            priority=priority,
            our_party=our_party,
            language=language,
            primary_structure=primary_structure,
            required_skills=required_skills,
        )
    else:
        return await _analyze_legacy(
            state=state,
            dispatcher=dispatcher,
            clause_id=clause_id,
            clause_name=clause_name,
            description=description,
            priority=priority,
            our_party=our_party,
            language=language,
            primary_structure=primary_structure,
            required_skills=required_skills,
        )
```

### 1.5 `_analyze_gen3` 实现

```python
async def _analyze_gen3(
    *,
    state: ReviewGraphState,
    dispatcher: SkillDispatcher | None,
    clause_id: str,
    clause_name: str,
    description: str,
    priority: str,
    our_party: str,
    language: str,
    primary_structure: Any,
    required_skills: list[str],
) -> Dict[str, Any]:
    """Gen3 模式：Orchestrator 计划 + ReAct Agent 执行。

    执行流程：
    1. 从 state 中读取 Orchestrator 的 clause plan（由 node_plan_review 生成）
    2. 使用 plan 中的 suggested_tools 和 max_iterations
    3. 调用 ReAct Agent 执行分析
    4. ReAct 失败时记录错误，返回空结果（不回退到 legacy）
    """
    llm_client = _get_llm_client()
    if not llm_client or not dispatcher or not primary_structure:
        logger.warning(
            "gen3 模式缺少必要组件 (llm=%s, dispatcher=%s, structure=%s)，"
            "返回空结果",
            bool(llm_client), bool(dispatcher), bool(primary_structure),
        )
        return {
            "current_clause_id": clause_id,
            "current_clause_text": "",
            "current_risks": [],
            "current_skill_context": {},
            "current_diffs": [],
        }

    # 从 Orchestrator 计划中获取参数
    clause_plan = _get_clause_plan(state, clause_id)
    settings = get_settings()

    if clause_plan:
        suggested_tools = clause_plan.get("suggested_tools", required_skills)
        max_iterations = clause_plan.get("max_iterations", settings.react_max_iterations)
        temperature = settings.react_temperature
    else:
        # 没有 Orchestrator 计划（可能 node_plan_review 失败了）
        # 使用默认参数，仍然走 ReAct
        suggested_tools = required_skills
        max_iterations = settings.react_max_iterations
        temperature = settings.react_temperature

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
            suggested_skills=suggested_tools,
            max_iterations=max_iterations,
            temperature=temperature,
        )
    except Exception as exc:
        logger.error("gen3 ReAct Agent 执行失败 (clause=%s): %s", clause_id, exc)
        return {
            "current_clause_id": clause_id,
            "current_clause_text": "",
            "current_risks": [],
            "current_skill_context": {},
            "current_diffs": [],
            "error": f"ReAct Agent 失败: {exc}",
        }
```

### 1.6 `_analyze_legacy` 实现

将当前 `node_clause_analyze` 中的非 ReAct 路径（dispatcher 固定循环 + LLM 分析）原样提取为独立函数，不做任何逻辑修改：

```python
async def _analyze_legacy(
    *,
    state: ReviewGraphState,
    dispatcher: SkillDispatcher | None,
    clause_id: str,
    clause_name: str,
    description: str,
    priority: str,
    our_party: str,
    language: str,
    primary_structure: Any,
    required_skills: list[str],
) -> Dict[str, Any]:
    """Legacy 模式：dispatcher 固定循环 + LLM 分析。

    此函数是当前 node_clause_analyze 非 ReAct 路径的原样提取，
    不做任何逻辑修改，确保遗留模式行为完全不变。
    """
    skill_context: Dict[str, Any] = {}

    # --- 阶段 1：dispatcher 固定循环调用 Skill ---
    if dispatcher and primary_structure:
        for skill_id in required_skills:
            if skill_id not in dispatcher.skill_ids:
                logger.debug("Skill '%s' 未注册，跳过", skill_id)
                continue
            try:
                result = await dispatcher.prepare_and_call(
                    skill_id, clause_id, primary_structure, dict(state),
                )
                if result.success and result.data:
                    skill_context[skill_id] = result.data
            except Exception as exc:
                logger.warning("Skill '%s' 调用失败: %s", skill_id, exc)

    # --- 阶段 2：提取条款文本 ---
    clause_text = ""
    context = skill_context.get("get_clause_context")
    if isinstance(context, dict):
        clause_text = str(context.get("context_text", "") or "")

    if not clause_text and primary_structure:
        clause_text = _extract_clause_text(primary_structure, clause_id)

    if not clause_text:
        clause_text = f"{clause_name}\n{description}".strip() or clause_id

    # --- 阶段 3：LLM 分析生成风险 ---
    risks: List[Dict[str, Any]] = []
    llm_client = _get_llm_client()
    if llm_client:
        try:
            messages = build_clause_analyze_messages(
                language=language,
                our_party=our_party,
                clause_id=clause_id,
                clause_name=clause_name,
                description=description,
                priority=priority,
                clause_text=clause_text,
                skill_context=skill_context,
                domain_id=state.get("domain_id"),
            )
            response = await llm_client.chat(messages)
            raw_risks = parse_json_response(response, expect_list=True)

            for raw in raw_risks:
                row = _as_dict(raw)
                original_text = row.get("original_text", "")
                risks.append(
                    {
                        "id": generate_id(),
                        "risk_level": _normalize_risk_level(row.get("risk_level")),
                        "risk_type": row.get("risk_type", "未分类风险"),
                        "description": row.get("description", ""),
                        "reason": row.get("reason", ""),
                        "analysis": row.get("analysis", ""),
                        "location": (
                            {"original_text": original_text} if original_text else None
                        ),
                    }
                )
        except Exception as exc:
            logger.warning("条款分析 LLM 调用失败，使用空风险回退: %s", exc)

    return {
        "current_clause_id": clause_id,
        "current_clause_text": clause_text,
        "current_risks": risks,
        "current_skill_context": skill_context,
        "current_diffs": [],
    }
```

**关键说明**：

- `_analyze_legacy` 是当前 `node_clause_analyze` 第 779-855 行的**原样提取**
- 唯一的变化是 SPEC-22 已将 `_build_skill_input` + `dispatcher.call` 替换为 `dispatcher.prepare_and_call`
- 不新增任何逻辑，不修改任何行为

### 1.7 `build_review_graph` 统一图拓扑

当前 `build_review_graph` 根据 `use_orchestrator` 开关决定是否添加 `plan_review` 节点和条件边。重构为基于 `execution_mode` 的统一拓扑：

```python
def build_review_graph(
    domain_id: str = "fidic",
    domain_subtype: str | None = None,
) -> StateGraph:
    settings = get_settings()
    mode = get_execution_mode(settings)

    dispatcher = _create_dispatcher(domain_id, domain_subtype)

    # --- 节点注册（两种模式共用） ---
    graph = StateGraph(ReviewGraphState)
    graph.add_node("parse_document", node_parse_document)
    graph.add_node("clause_analyze", _wrap_with_dispatcher(node_clause_analyze, dispatcher))
    graph.add_node("clause_generate_diffs", node_clause_generate_diffs)
    graph.add_node("save_clause", node_save_clause)
    graph.add_node("merge_report", node_merge_report)

    if mode == ExecutionMode.GEN3:
        # --- Gen3 模式：添加 plan_review 节点 ---
        graph.add_node("plan_review", _wrap_with_dispatcher(node_plan_review, dispatcher))

        graph.set_entry_point("parse_document")
        graph.add_edge("parse_document", "plan_review")
        graph.add_edge("plan_review", "clause_analyze")

        # clause_analyze 后根据 Orchestrator 计划决定是否跳过 diffs
        graph.add_conditional_edges(
            "clause_analyze",
            route_after_analyze,
            {
                "clause_generate_diffs": "clause_generate_diffs",
                "save_clause": "save_clause",
            },
        )
    else:
        # --- Legacy 模式：原有拓扑不变 ---
        graph.set_entry_point("parse_document")
        graph.add_edge("parse_document", "clause_analyze")
        graph.add_edge("clause_analyze", "clause_generate_diffs")

    # --- 共用的后续边 ---
    graph.add_edge("clause_generate_diffs", "save_clause")
    graph.add_edge("save_clause", "merge_report")
    graph.set_finish_point("merge_report")

    return graph
```

**变化总结**：

| 改动点 | 改动前 | 改动后 |
|--------|--------|--------|
| 模式判断 | `if use_orchestrator:` | `if mode == ExecutionMode.GEN3:` |
| plan_review 节点 | 仅 `use_orchestrator=True` 时添加 | 仅 `gen3` 模式添加 |
| 条件边 | 仅 `use_orchestrator=True` 时使用 `route_after_analyze` | 仅 `gen3` 模式使用 |
| ReAct 判断 | `node_clause_analyze` 内部 `if use_react:` | `_analyze_gen3` 内部，无需额外判断 |

---

## 2. 文件清单

### 新建文件（1 个）

| 文件路径 | 内容 |
|---------|------|
| `tests/test_e2e_gen3_pipeline.py` | 端到端集成测试：验证 orchestrator → ReAct → dispatcher → skill 完整链路 |

### 修改文件（4 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/config.py` | 新增 `ExecutionMode` 枚举、`execution_mode` 字段、`get_execution_mode()` 函数、`EXECUTION_MODE` 环境变量映射 |
| `backend/src/contract_review/graph/builder.py` | 重构 `node_clause_analyze` 为模式分发；提取 `_analyze_gen3` 和 `_analyze_legacy`；重构 `build_review_graph` 基于 `execution_mode` 构建图拓扑 |
| `tests/test_review_graph.py` | 更新现有测试以适配 `execution_mode` 配置；新增 `TestExecutionModeSwitch` 测试类 |
| `tests/test_orchestrator.py` | 更新 orchestrator 测试中的配置 mock，使用 `execution_mode="gen3"` 替代 `use_orchestrator=True` |

### 不需要修改的文件

- `backend/src/contract_review/graph/orchestrator.py` — 无需改动，`generate_review_plan` 和 `ClauseAnalysisPlan` 不变
- `backend/src/contract_review/graph/react_agent.py` — 无需改动，`_run_react_branch` 接口不变
- `backend/src/contract_review/skills/dispatcher.py` — 无需改动
- `backend/src/contract_review/graph/state.py` — 无需改动
- 各 Skill 文件 — 无需改动

---

## 3. config.py 改动

### 3.1 新增 `ExecutionMode` 枚举

在 `Settings` 类定义之前添加：

```python
from enum import Enum

class ExecutionMode(str, Enum):
    """执行模式枚举。

    LEGACY: 遗留模式 — dispatcher 固定循环 + LLM 分析
    GEN3:   AI 编排模式 — orchestrator 规划 + ReAct Agent 执行
    """
    LEGACY = "legacy"
    GEN3 = "gen3"
```

### 3.2 `Settings` 类新增字段

```python
class Settings(BaseModel):
    """全局配置"""
    llm: LLMSettings
    review: ReviewSettings = Field(default_factory=ReviewSettings)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    refly: ReflySettings = Field(default_factory=ReflySettings)

    # --- 执行模式（新增）---
    execution_mode: str = "legacy"          # "legacy" | "gen3"

    # --- 废弃（保留向后兼容）---
    use_react_agent: bool = False           # deprecated, 由 execution_mode 控制
    use_orchestrator: bool = False          # deprecated, 由 execution_mode 控制

    # --- ReAct 参数（保留）---
    react_max_iterations: int = 5
    react_temperature: float = 0.1
```

### 3.3 新增 `get_execution_mode()` 函数

在 `get_settings()` 函数附近添加（见 1.2 节的完整实现）。

### 3.4 环境变量映射

在现有环境变量处理逻辑中新增：

```python
# EXECUTION_MODE 环境变量
env_mode = os.getenv("EXECUTION_MODE", "").strip().lower()
if env_mode in ("legacy", "gen3"):
    overrides["execution_mode"] = env_mode
```

**向后兼容**：旧的 `USE_REACT_AGENT` 和 `USE_ORCHESTRATOR` 环境变量继续生效，通过 `get_execution_mode()` 的推断逻辑映射到 `gen3`。

---

## 4. builder.py 改动

### 4.1 导入新增

```python
from ..config import ExecutionMode, get_execution_mode
```

### 4.2 `node_clause_analyze` 重构

将当前函数体（约 120 行，包含 3 条分支）替换为模式分发（见 1.4 节）。

**提取前后对比**：

```
改动前（node_clause_analyze 内部）：
  ├─ if use_react and llm_client and dispatcher and primary_structure:
  │     → _run_react_branch(...)                    # 分支 1
  ├─ skill_context = {}
  │  if dispatcher and primary_structure:
  │     for skill_id in required_skills:
  │         → _build_skill_input + dispatcher.call   # 分支 2（SPEC-22 后已改为 prepare_and_call）
  ├─ if llm_client:
  │     → llm_client.chat(analyze_messages)          # 分支 3
  └─ return {...}

改动后（node_clause_analyze 内部）：
  ├─ mode = get_execution_mode(settings)
  ├─ if mode == ExecutionMode.GEN3:
  │     → _analyze_gen3(...)                         # 新函数
  └─ else:
        → _analyze_legacy(...)                       # 新函数（原分支 2+3 的原样提取）
```

### 4.3 新增 `_analyze_gen3` 函数

见 1.5 节的完整实现。

### 4.4 新增 `_analyze_legacy` 函数

见 1.6 节的完整实现。

### 4.5 `build_review_graph` 重构

见 1.7 节的完整实现。将 `if use_orchestrator:` 替换为 `if mode == ExecutionMode.GEN3:`。

### 4.6 清理旧开关引用

删除 builder.py 中所有直接读取 `use_react_agent` 和 `use_orchestrator` 的代码。这些开关的读取统一收敛到 `get_execution_mode()` 中。

```python
# 删除这些代码：
settings = get_settings()
use_react = settings.use_react_agent          # ← 删除
use_orchestrator = settings.use_orchestrator   # ← 删除

# 替换为：
settings = get_settings()
mode = get_execution_mode(settings)            # ← 统一入口
```

---

## 5. 测试改动

### 5.1 `tests/test_review_graph.py` 改动

#### 更新现有测试的配置 mock

所有涉及 `use_orchestrator` 或 `use_react_agent` 的 mock 需要同步更新：

```python
# 改动前：
mock_settings.use_orchestrator = True
mock_settings.use_react_agent = True

# 改动后：
mock_settings.execution_mode = "gen3"
# use_orchestrator 和 use_react_agent 保留默认值即可
```

#### 新增 `TestExecutionModeSwitch` 测试类

```python
class TestExecutionModeSwitch:
    """验证 execution_mode 正确切换执行路径。"""

    @pytest.mark.asyncio
    async def test_legacy_mode_uses_dispatcher_loop(self, mock_settings):
        """legacy 模式走 dispatcher 固定循环 + LLM 分析。"""
        mock_settings.execution_mode = "legacy"
        # 验证 _analyze_legacy 被调用
        with patch(
            "contract_review.graph.builder._analyze_legacy",
            new_callable=AsyncMock,
        ) as mock_legacy:
            mock_legacy.return_value = {
                "current_clause_id": "4.1",
                "current_clause_text": "test",
                "current_risks": [],
                "current_skill_context": {},
                "current_diffs": [],
            }
            result = await node_clause_analyze(state, dispatcher)
            mock_legacy.assert_called_once()

    @pytest.mark.asyncio
    async def test_gen3_mode_uses_react_agent(self, mock_settings):
        """gen3 模式走 Orchestrator + ReAct Agent。"""
        mock_settings.execution_mode = "gen3"
        with patch(
            "contract_review.graph.builder._analyze_gen3",
            new_callable=AsyncMock,
        ) as mock_gen3:
            mock_gen3.return_value = {
                "current_clause_id": "4.1",
                "current_clause_text": "test",
                "current_risks": [],
                "current_skill_context": {},
                "current_diffs": [],
            }
            result = await node_clause_analyze(state, dispatcher)
            mock_gen3.assert_called_once()

    @pytest.mark.asyncio
    async def test_legacy_bool_inferred_as_gen3(self, mock_settings):
        """旧开关 use_orchestrator=True 推断为 gen3 模式。"""
        mock_settings.execution_mode = "legacy"  # 未显式设置
        mock_settings.use_orchestrator = True
        mode = get_execution_mode(mock_settings)
        assert mode == ExecutionMode.GEN3

    @pytest.mark.asyncio
    async def test_explicit_mode_overrides_bool(self, mock_settings):
        """显式 execution_mode 优先于旧开关。"""
        mock_settings.execution_mode = "gen3"
        mock_settings.use_orchestrator = False
        mock_settings.use_react_agent = False
        mode = get_execution_mode(mock_settings)
        assert mode == ExecutionMode.GEN3
```

### 5.2 `tests/test_orchestrator.py` 改动

更新配置 mock，将 `use_orchestrator=True` 替换为 `execution_mode="gen3"`。逻辑不变，仅配置方式变化。

### 5.3 新建 `tests/test_e2e_gen3_pipeline.py`

这是本 SPEC 最重要的新增测试，验证 **orchestrator → ReAct → dispatcher → skill** 的完整链路。

```python
"""端到端集成测试：Gen3 完整管线。

测试目标：验证 orchestrator 生成的 plan 能被 ReAct Agent 正确消费，
ReAct Agent 能通过 dispatcher 调用真实的 Skill，最终产出有效的审查结果。

Mock 策略：
- LLM 调用：mock（避免真实 API 调用和费用）
- dispatcher + Skill：真实调用（验证完整链路）
- 文档结构：使用最小化的测试 fixture
"""

import pytest
from unittest.mock import AsyncMock, patch

from contract_review.config import ExecutionMode, get_execution_mode
from contract_review.graph.builder import (
    build_review_graph,
    _analyze_gen3,
    _get_clause_plan,
)
from contract_review.skills.dispatcher import SkillDispatcher


class TestGen3EndToEnd:
    """Gen3 模式端到端集成测试。"""

    @pytest.fixture
    def dispatcher(self):
        """创建包含所有 Skill 的真实 dispatcher。"""
        from contract_review.graph.builder import _create_dispatcher
        return _create_dispatcher(domain_id="fidic")

    @pytest.fixture
    def primary_structure(self):
        return {
            "clauses": [
                {
                    "clause_id": "4.1",
                    "title": "承包商的一般义务",
                    "text": "承包商应按照合同规定设计、施工并完成工程。",
                    "children": [],
                }
            ]
        }

    @pytest.fixture
    def base_state(self, primary_structure):
        return {
            "task_id": "e2e_test_001",
            "our_party": "承包商",
            "language": "zh-CN",
            "domain_id": "fidic",
            "domain_subtype": "yellow_book",
            "material_type": "contract",
            "documents": [],
            "findings": {},
            "primary_structure": primary_structure,
            "review_plan": {
                "plan_version": 1,
                "clause_plans": [
                    {
                        "clause_id": "4.1",
                        "suggested_tools": [
                            "get_clause_context",
                            "compare_with_baseline",
                        ],
                        "max_iterations": 3,
                        "skip_diffs": False,
                    }
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_orchestrator_plan_feeds_react_agent(
        self, dispatcher, primary_structure, base_state
    ):
        """Orchestrator 的 clause plan 正确传递给 ReAct Agent。

        验证链路：
        1. _get_clause_plan 从 state 中提取 plan
        2. plan 中的 suggested_tools 和 max_iterations 传递给 _run_react_branch
        3. ReAct Agent 使用这些参数调用 dispatcher
        """
        # 验证 plan 提取
        plan = _get_clause_plan(base_state, "4.1")
        assert plan is not None
        assert plan.suggested_tools == ["get_clause_context", "compare_with_baseline"]
        assert plan.max_iterations == 3

        # Mock LLM，但使用真实 dispatcher
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = '{"action": "finish", "result": []}'

        with patch(
            "contract_review.graph.builder._get_llm_client",
            return_value=mock_llm,
        ):
            result = await _analyze_gen3(
                state=base_state,
                dispatcher=dispatcher,
                clause_id="4.1",
                clause_name="承包商的一般义务",
                description="承包商应按照合同规定完成工程",
                priority="high",
                our_party="承包商",
                language="zh-CN",
                primary_structure=primary_structure,
                required_skills=["get_clause_context", "compare_with_baseline"],
            )

        assert result["current_clause_id"] == "4.1"
        # ReAct Agent 应该被调用（即使 mock LLM 返回 finish）
        assert mock_llm.chat.called

    @pytest.mark.asyncio
    async def test_gen3_graph_includes_plan_review_node(self):
        """gen3 模式的图拓扑包含 plan_review 节点。"""
        with patch(
            "contract_review.graph.builder.get_execution_mode",
            return_value=ExecutionMode.GEN3,
        ):
            graph = build_review_graph(domain_id="fidic")
            node_names = set(graph.nodes.keys())
            assert "plan_review" in node_names
            assert "clause_analyze" in node_names

    @pytest.mark.asyncio
    async def test_legacy_graph_excludes_plan_review_node(self):
        """legacy 模式的图拓扑不包含 plan_review 节点。"""
        with patch(
            "contract_review.graph.builder.get_execution_mode",
            return_value=ExecutionMode.LEGACY,
        ):
            graph = build_review_graph(domain_id="fidic")
            node_names = set(graph.nodes.keys())
            assert "plan_review" not in node_names
            assert "clause_analyze" in node_names

    @pytest.mark.asyncio
    async def test_gen3_without_plan_still_works(
        self, dispatcher, primary_structure
    ):
        """gen3 模式下即使没有 Orchestrator plan，ReAct 仍能执行。

        场景：node_plan_review 失败或被跳过，state 中没有 review_plan。
        预期：_analyze_gen3 使用默认参数调用 ReAct，不回退到 legacy。
        """
        state_no_plan = {
            "task_id": "e2e_test_002",
            "our_party": "承包商",
            "language": "zh-CN",
            "domain_id": "fidic",
            "primary_structure": primary_structure,
            # 注意：没有 review_plan
        }

        mock_llm = AsyncMock()
        mock_llm.chat.return_value = '{"action": "finish", "result": []}'

        with patch(
            "contract_review.graph.builder._get_llm_client",
            return_value=mock_llm,
        ):
            result = await _analyze_gen3(
                state=state_no_plan,
                dispatcher=dispatcher,
                clause_id="4.1",
                clause_name="承包商的一般义务",
                description="测试",
                priority="high",
                our_party="承包商",
                language="zh-CN",
                primary_structure=primary_structure,
                required_skills=["get_clause_context"],
            )

        # 应该正常返回，不崩溃
        assert result["current_clause_id"] == "4.1"

    @pytest.mark.asyncio
    async def test_gen3_react_failure_returns_error(
        self, dispatcher, primary_structure, base_state
    ):
        """gen3 模式下 ReAct Agent 失败时返回错误，不回退到 legacy。"""
        mock_llm = AsyncMock()
        mock_llm.chat.side_effect = RuntimeError("LLM 服务不可用")

        with patch(
            "contract_review.graph.builder._get_llm_client",
            return_value=mock_llm,
        ):
            result = await _analyze_gen3(
                state=base_state,
                dispatcher=dispatcher,
                clause_id="4.1",
                clause_name="承包商的一般义务",
                description="测试",
                priority="high",
                our_party="承包商",
                language="zh-CN",
                primary_structure=primary_structure,
                required_skills=["get_clause_context"],
            )

        assert "error" in result
        assert "ReAct Agent 失败" in result["error"]
        # 不应该有 skill_context（因为没走 legacy 的 dispatcher 循环）
        assert result["current_skill_context"] == {}


class TestGetExecutionMode:
    """get_execution_mode 函数的单元测试。"""

    def test_default_is_legacy(self):
        from contract_review.config import Settings
        settings = Settings(llm={"provider": "openai", "model": "gpt-4"})
        assert get_execution_mode(settings) == ExecutionMode.LEGACY

    def test_explicit_gen3(self):
        from contract_review.config import Settings
        settings = Settings(
            llm={"provider": "openai", "model": "gpt-4"},
            execution_mode="gen3",
        )
        assert get_execution_mode(settings) == ExecutionMode.GEN3

    def test_use_orchestrator_infers_gen3(self):
        from contract_review.config import Settings
        settings = Settings(
            llm={"provider": "openai", "model": "gpt-4"},
            use_orchestrator=True,
        )
        assert get_execution_mode(settings) == ExecutionMode.GEN3

    def test_use_react_agent_infers_gen3(self):
        from contract_review.config import Settings
        settings = Settings(
            llm={"provider": "openai", "model": "gpt-4"},
            use_react_agent=True,
        )
        assert get_execution_mode(settings) == ExecutionMode.GEN3

    def test_explicit_legacy_overrides_bool(self):
        """显式设置 legacy 时，即使旧开关为 True 也走 legacy。

        注意：这是一个边界情况。get_execution_mode 的优先级是：
        1. 显式 execution_mode（非 legacy）→ 使用它
        2. 旧开关推断
        3. 默认 legacy

        当 execution_mode="legacy" 且 use_orchestrator=True 时，
        走步骤 2 推断为 gen3。这是向后兼容的正确行为。
        """
        from contract_review.config import Settings
        settings = Settings(
            llm={"provider": "openai", "model": "gpt-4"},
            execution_mode="legacy",
            use_orchestrator=True,
        )
        # 旧开关优先（向后兼容）
        assert get_execution_mode(settings) == ExecutionMode.GEN3
```

---

## 6. 运行命令

### 6.1 单元测试

```bash
# config.py 相关测试
PYTHONPATH=backend/src python -m pytest tests/test_e2e_gen3_pipeline.py::TestGetExecutionMode -x -q

# 执行模式切换测试
PYTHONPATH=backend/src python -m pytest tests/test_review_graph.py::TestExecutionModeSwitch -x -q

# 端到端集成测试
PYTHONPATH=backend/src python -m pytest tests/test_e2e_gen3_pipeline.py::TestGen3EndToEnd -x -q
```

### 6.2 全量回归测试

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

### 6.3 验证模式切换

```bash
# 验证 legacy 模式（默认）
EXECUTION_MODE=legacy PYTHONPATH=backend/src python -c "
from contract_review.config import get_settings, get_execution_mode
s = get_settings()
print(f'execution_mode = {get_execution_mode(s)}')
"

# 验证 gen3 模式
EXECUTION_MODE=gen3 PYTHONPATH=backend/src python -c "
from contract_review.config import get_settings, get_execution_mode
s = get_settings()
print(f'execution_mode = {get_execution_mode(s)}')
"

# 验证旧开关向后兼容
USE_ORCHESTRATOR=true PYTHONPATH=backend/src python -c "
from contract_review.config import get_settings, get_execution_mode
s = get_settings()
print(f'execution_mode = {get_execution_mode(s)}')
"
```

### 6.4 验证图拓扑

```bash
PYTHONPATH=backend/src python -c "
from unittest.mock import patch
from contract_review.config import ExecutionMode
from contract_review.graph.builder import build_review_graph

# Legacy 模式
with patch('contract_review.graph.builder.get_execution_mode', return_value=ExecutionMode.LEGACY):
    g = build_review_graph('fidic')
    print('Legacy 节点:', sorted(g.nodes.keys()))

# Gen3 模式
with patch('contract_review.graph.builder.get_execution_mode', return_value=ExecutionMode.GEN3):
    g = build_review_graph('fidic')
    print('Gen3 节点:', sorted(g.nodes.keys()))
"
```

---

## 7. 验收标准

### 7.1 配置验收

1. `ExecutionMode` 枚举定义在 `config.py` 中，包含 `LEGACY` 和 `GEN3` 两个值
2. `Settings` 类新增 `execution_mode: str = "legacy"` 字段
3. `get_execution_mode()` 函数正确实现优先级逻辑（显式 mode > 旧开关推断 > 默认 legacy）
4. `EXECUTION_MODE` 环境变量正确映射
5. 旧环境变量 `USE_REACT_AGENT` 和 `USE_ORCHESTRATOR` 仍然生效

### 7.2 执行路径验收

6. `node_clause_analyze` 内部不再有 `if use_react:` 或 `if use_orchestrator:` 的直接判断
7. `node_clause_analyze` 通过 `get_execution_mode()` 分发到 `_analyze_gen3` 或 `_analyze_legacy`
8. `_analyze_gen3` 正确读取 Orchestrator 的 clause plan 并传递给 ReAct Agent
9. `_analyze_legacy` 行为与重构前完全一致
10. gen3 模式下 ReAct 失败时返回错误，不回退到 legacy

### 7.3 图拓扑验收

11. `build_review_graph` 基于 `execution_mode` 构建图拓扑
12. gen3 模式包含 `plan_review` 节点和 `route_after_analyze` 条件边
13. legacy 模式不包含 `plan_review` 节点，`clause_analyze` 直连 `clause_generate_diffs`

### 7.4 测试验收

14. 全量测试通过，无新增失败
15. `TestExecutionModeSwitch` 验证模式切换正确分发
16. `TestGetExecutionMode` 覆盖所有优先级组合
17. `TestGen3EndToEnd` 验证 orchestrator → ReAct → dispatcher → skill 完整链路
18. 端到端测试使用真实 dispatcher 和 Skill，仅 mock LLM

### 7.5 向后兼容验收

19. `EXECUTION_MODE` 未设置时，默认行为与改动前完全一致（legacy 模式）
20. `USE_ORCHESTRATOR=true` 自动推断为 gen3 模式
21. `USE_REACT_AGENT=true` 自动推断为 gen3 模式
22. 不存在任何代码直接读取 `settings.use_orchestrator` 或 `settings.use_react_agent`（除了 `get_execution_mode` 内部）

---

## 8. 实施步骤

按以下顺序执行，每步完成后运行全量测试确认无回归：

### 步骤 1：config.py 改动

1. 新增 `ExecutionMode` 枚举
2. `Settings` 类新增 `execution_mode` 字段
3. 新增 `get_execution_mode()` 函数
4. 新增 `EXECUTION_MODE` 环境变量映射

运行测试确认现有测试不受影响（新增字段有默认值）。

### 步骤 2：builder.py 提取 `_analyze_legacy`

将 `node_clause_analyze` 中的非 ReAct 路径原样提取为 `_analyze_legacy` 函数。此步骤是纯重构，不改变任何行为。

### 步骤 3：builder.py 新增 `_analyze_gen3`

新增 `_analyze_gen3` 函数，封装 Orchestrator plan 读取 + ReAct Agent 调用。

### 步骤 4：重构 `node_clause_analyze`

将函数体替换为 `get_execution_mode` + 模式分发。删除旧的 `use_react_agent` / `use_orchestrator` 直接读取。

### 步骤 5：重构 `build_review_graph`

将 `if use_orchestrator:` 替换为 `if mode == ExecutionMode.GEN3:`。

### 步骤 6：更新现有测试

更新 `test_review_graph.py` 和 `test_orchestrator.py` 中的配置 mock。

### 步骤 7：新增测试

1. 新增 `TestExecutionModeSwitch`
2. 新增 `TestGetExecutionMode`
3. 新建 `test_e2e_gen3_pipeline.py`

### 步骤 8：全量回归测试

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| `_analyze_legacy` 提取时遗漏逻辑 | legacy 模式行为改变 | 纯机械提取，不修改任何逻辑；提取前后运行全量测试对比 |
| `get_execution_mode` 优先级逻辑错误 | 旧配置用户被意外切换到 gen3 | 默认值为 `legacy`；旧开关推断逻辑有完整的单元测试覆盖 |
| gen3 模式缺少组件时静默失败 | 用户设置 gen3 但未配置 LLM，得到空结果 | `_analyze_gen3` 在缺少组件时记录 warning 并返回空结果，不崩溃 |
| 端到端测试 mock LLM 不够真实 | 测试通过但生产环境失败 | mock 返回符合 ReAct 协议的 JSON；后续可补充真实 LLM 的冒烟测试 |
| `build_review_graph` 重构影响图编译 | 图无法构建 | 新增图拓扑验证测试，确认两种模式的节点和边都正确 |

---

## 10. 架构转型总结（SPEC-19 → SPEC-23）

本 SPEC 是架构转型五步走的最后一步。完成后，系统从"硬编码工作流"完全转型为"AI 驱动的动态编排"：

```
SPEC-19: 工具自描述层
  └─ 每个 Skill 注册 prepare_input_fn，实现自描述
  └─ dispatcher.prepare_and_call() 成为统一调用入口

SPEC-20: ReAct Agent
  └─ LLM 自主选择工具、观察结果、决定下一步
  └─ 替代硬编码的 for skill_id in required_skills 循环

SPEC-21: Orchestrator 编排层
  └─ 审查前生成全局计划（ReviewPlan）
  └─ 为每个条款规划 suggested_tools 和 max_iterations

SPEC-22: 移除硬编码 Skill 构建器
  └─ 删除 _build_skill_input() 的 230 行 if/elif
  └─ dispatcher.prepare_and_call() 成为唯一 Skill 调用入口

SPEC-23: 统一执行管线（本文档）
  └─ 合并双开关为 execution_mode 枚举
  └─ 统一图拓扑和执行路径
  └─ 补充端到端集成测试
```

**最终架构**：

```
用户请求
  → parse_document（文档解析）
  → plan_review（Orchestrator 生成全局计划）     ← gen3 模式独有
  → clause_analyze
      → _analyze_gen3                            ← gen3 模式
          → 读取 Orchestrator 的 clause plan
          → ReAct Agent 自主选工具执行分析
          → dispatcher.prepare_and_call() 调用 Skill
      → _analyze_legacy                          ← legacy 模式
          → dispatcher 固定循环调用 Skill
          → LLM 分析生成风险
  → clause_generate_diffs（或 skip_diffs）
  → save_clause
  → merge_report
```

**切换方式**：

```bash
# 遗留模式（默认，行为不变）
EXECUTION_MODE=legacy

# AI 编排模式（完整的 Gen3 管线）
EXECUTION_MODE=gen3
```
