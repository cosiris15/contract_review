# SPEC-22: 移除硬编码 Skill 构建器（Remove Hardcoded Skill Builders）

> 优先级：高（架构整合两步走的第一步，SPEC-23 的前置条件）
> 前置依赖：SPEC-19（工具自描述层）— 所有 17 个 Skill 的 `prepare_input_fn` 已实现并注册
> 预计新建文件：0 个 | 修改文件：3 个 | 删除代码：~230 行
> 范围：builder.py 瘦身 + 测试迁移

---

## 0. 背景与动机

### 0.1 当前状态

经过 SPEC-19/20/21 的实施，项目中存在**两套完全重复的 Skill 输入构建逻辑**：

1. **新路径**（SPEC-19）：每个 Skill 文件中的 `prepare_input()` 函数，通过 `SkillRegistration.prepare_input_fn` 注册到 dispatcher
2. **旧路径**（遗留）：`builder.py` 中 `_build_skill_input()` 的 17 个 `if/elif` 分支（第 319-546 行，约 230 行）

经过逐一比对确认：**17 个 Skill 的 `prepare_input()` 逻辑与 `_build_skill_input()` 中的对应分支完全等价**。旧路径已经是纯冗余代码。

### 0.2 为什么现在必须删除

1. **双路径维护成本**：修改任何 Skill 的输入构造逻辑，需要同时改两个地方
2. **SPEC-23 的前置条件**：SPEC-23 要统一执行管线，必须确保 dispatcher 是唯一的 Skill 调用入口。如果 `_build_skill_input()` 还在，`node_clause_analyze` 就无法干净地切换到纯 dispatcher 路径
3. **代码信号混乱**：新开发者看到 `_build_skill_input()` 会以为这是主路径，实际上它只是 fallback

### 0.3 风险评估

这是一个**低风险**的删除操作：
- 所有 17 个 `prepare_input_fn` 已经在 SPEC-19 中实现并通过测试
- `_build_skill_input()` 当前只在 `dispatcher` 参数为 `None` 时才被使用（即 `prepare_input_fn` 不可用时的 fallback）
- 删除后，`dispatcher.prepare_and_call()` 成为唯一入口，其内部已有 `GenericSkillInput` 兜底

---

## 1. 设计方案

### 1.1 核心改动

```
改动前：
  node_clause_analyze
    → _build_skill_input(skill_id, ..., dispatcher)
        → 先尝试 dispatcher.prepare_input_fn
        → 失败则走 17 个 if/elif 分支（fallback）
    → dispatcher.call(skill_id, input_data)

改动后：
  node_clause_analyze
    → dispatcher.prepare_and_call(skill_id, clause_id, primary_structure, state)
        → 内部调用 prepare_input_fn（所有 17 个 Skill 都已注册）
        → 失败则用 GenericSkillInput 兜底
```

### 1.2 删除清单

| 目标 | 位置 | 行数 |
|------|------|------|
| `_build_skill_input()` 函数 | builder.py 第 319-546 行 | ~230 行 |
| `_build_skill_input` 的所有调用点 | builder.py `node_clause_analyze` 内 | ~15 行 |
| `_build_skill_input` 相关的 import | builder.py 顶部 | ~10 行 |
| `_extract_clause_text()` 辅助函数 | builder.py（如果仅被 `_build_skill_input` 使用） | ~15 行 |

### 1.3 保留什么

- `dispatcher.prepare_and_call()` — 已在 SPEC-19 中实现，成为唯一入口
- `dispatcher.call()` — 底层执行接口，不变
- 各 Skill 文件中的 `prepare_input()` — 不变
- `_as_dict()` 辅助函数 — 其他节点也在使用，保留

---

## 2. 文件清单

### 修改文件（3 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/graph/builder.py` | 删除 `_build_skill_input()`；重构 `node_clause_analyze` 中的硬编码 Skill 调用循环，改用 `dispatcher.prepare_and_call()` |
| `tests/test_skill_dispatch.py` | 删除测试 `_build_skill_input()` 的用例；新增测试 `dispatcher.prepare_and_call()` 全覆盖 |
| `tests/test_review_graph.py` | 更新依赖硬编码路径的集成测试 |

### 不需要修改的文件

- `dispatcher.py` — `prepare_and_call()` 已在 SPEC-19 中实现
- `schema.py` — 无需改动
- `tool_adapter.py` — 无需改动
- `orchestrator.py` — 无需改动
- `react_agent.py` — 无需改动
- 各 Skill 文件 — `prepare_input()` 已就绪，无需改动

---

## 3. builder.py 改动

### 3.1 删除 `_build_skill_input()` 函数

**完整删除** `_build_skill_input()` 函数（约 230 行），包括其内部的 17 个 `if skill_id == "..."` 分支。

同时检查并清理以下内容：
- 仅被 `_build_skill_input()` 使用的 import 语句
- `_extract_clause_text()` 辅助函数（如果仅被 `_build_skill_input` 调用则删除；如果其他地方也用到则保留）

### 3.2 重构 `node_clause_analyze` 中的硬编码 Skill 调用

当前 `node_clause_analyze` 中有一段硬编码的 Skill 调用循环（非 ReAct 路径）：

```python
# 当前代码（需要重构的部分）：
if dispatcher and primary_structure:
    for skill_id in required_skills:
        skill_input = _build_skill_input(
            skill_id, clause_id, primary_structure, state, dispatcher
        )
        if skill_input:
            result = await dispatcher.call(skill_id, skill_input)
            if result.success:
                skill_context[skill_id] = result.data
```

重构为：

```python
# 重构后：
if dispatcher and primary_structure:
    for skill_id in required_skills:
        result = await dispatcher.prepare_and_call(
            skill_id,
            clause_id,
            primary_structure,
            dict(state),
        )
        if result.success:
            skill_context[skill_id] = result.data
```

**关键变化**：
- 两步操作（`_build_skill_input` + `dispatcher.call`）合并为一步（`dispatcher.prepare_and_call`）
- `prepare_and_call` 内部已处理 `prepare_input_fn` 调用和 `GenericSkillInput` 兜底
- 不再需要 `_build_skill_input` 函数

### 3.3 清理不再需要的 import

删除 `_build_skill_input` 引入的各 Skill Input 类型 import。这些 import 分散在函数内部（lazy import），删除函数时一并清理即可。

检查 builder.py 顶部是否有以下不再需要的 import（仅删除确认无其他引用的）：

```python
# 可能需要清理的 import（需逐一确认）
from ..skills.local.clause_context import ClauseContextInput
from ..skills.local.resolve_definition import ResolveDefinitionInput
from ..skills.local.compare_with_baseline import CompareWithBaselineInput
# ... 等等
```

**注意**：由于 `_build_skill_input` 内部使用的是 lazy import（在 if 分支内 import），大部分 import 会随函数删除自动清理。只需检查顶部是否有残留。

### 3.4 `_extract_clause_text()` 处理

检查 `_extract_clause_text()` 是否仅被 `_build_skill_input()` 使用：
- 如果是 → 删除
- 如果其他地方也用到（如 `node_clause_analyze` 的 LLM 分支）→ 保留

各 Skill 的 `prepare_input()` 中已有等价的文本提取逻辑，不依赖 builder.py 的 `_extract_clause_text()`。

---

## 4. 测试改动

### 4.1 `tests/test_skill_dispatch.py` 改动

#### 删除的测试

删除所有直接测试 `_build_skill_input()` 的用例。这些测试验证的是"给定 skill_id 和 state，能否正确构造 Input 对象"——这个职责已经转移到各 Skill 的 `prepare_input()` 中。

具体删除的测试类/方法：
- `TestBuildSkillInput` 类（如果存在）
- 所有 `test_build_skill_input_*` 方法
- `TestPrepareInputFallback` 类（SPEC-19 新增的 fallback 测试，fallback 机制已不存在）

#### 新增的测试

新增 `TestPrepareAndCallAllSkills` 类，验证 `dispatcher.prepare_and_call()` 对所有 17 个 Skill 都能正确工作：

```python
class TestPrepareAndCallAllSkills:
    """验证 dispatcher.prepare_and_call() 覆盖所有已注册 Skill。"""

    @pytest.fixture
    def dispatcher(self):
        """创建包含所有 Skill 的 dispatcher。"""
        return _create_dispatcher(domain_id="fidic")

    @pytest.fixture
    def base_state(self):
        """基础 state，包含所有 Skill 可能需要的字段。"""
        return {
            "task_id": "test_001",
            "our_party": "承包商",
            "language": "zh-CN",
            "domain_id": "fidic",
            "domain_subtype": "yellow_book",
            "material_type": "contract",
            "documents": [],
            "findings": {},
            "primary_structure": {
                "clauses": [
                    {
                        "clause_id": "4.1",
                        "title": "承包商义务",
                        "text": "承包商应按照合同要求完成工程。",
                        "children": [],
                    }
                ]
            },
        }

    @pytest.fixture
    def primary_structure(self, base_state):
        return base_state["primary_structure"]

    @pytest.mark.asyncio
    async def test_all_generic_skills_have_prepare_input(self, dispatcher):
        """所有通用 Skill 都注册了 prepare_input_fn。"""
        generic_skills = [
            "get_clause_context",
            "resolve_definition",
            "compare_with_baseline",
            "cross_reference_check",
            "extract_financial_terms",
            "search_reference_doc",
            "load_review_criteria",
            "assess_deviation",
        ]
        for skill_id in generic_skills:
            reg = dispatcher.get_registration(skill_id)
            assert reg is not None, f"Skill '{skill_id}' 未注册"
            assert reg.prepare_input_fn is not None, (
                f"Skill '{skill_id}' 缺少 prepare_input_fn"
            )

    @pytest.mark.asyncio
    async def test_all_domain_skills_have_prepare_input(self, dispatcher):
        """所有领域 Skill 都注册了 prepare_input_fn。"""
        domain_skills = [
            "fidic_merge_gc_pc",
            "fidic_calculate_time_bar",
            "fidic_check_pc_consistency",
            "fidic_search_er",
        ]
        for skill_id in domain_skills:
            reg = dispatcher.get_registration(skill_id)
            if reg is None:
                continue  # 领域 Skill 可能未注册（取决于 domain_id）
            assert reg.prepare_input_fn is not None, (
                f"Skill '{skill_id}' 缺少 prepare_input_fn"
            )

    @pytest.mark.asyncio
    async def test_prepare_and_call_constructs_valid_input(
        self, dispatcher, base_state, primary_structure
    ):
        """prepare_and_call 能为每个已注册 Skill 构造有效输入。"""
        for skill_id in dispatcher.skill_ids:
            reg = dispatcher.get_registration(skill_id)
            if not reg or not reg.prepare_input_fn:
                continue

            # 只验证 prepare_input 不抛异常，不实际执行 Skill
            from contract_review.skills.dispatcher import _import_handler

            prepare_fn = _import_handler(reg.prepare_input_fn)
            input_data = prepare_fn("4.1", primary_structure, base_state)
            assert input_data is not None, (
                f"Skill '{skill_id}' 的 prepare_input 返回 None"
            )
            assert hasattr(input_data, "clause_id"), (
                f"Skill '{skill_id}' 的 input 缺少 clause_id"
            )

    @pytest.mark.asyncio
    async def test_prepare_and_call_generic_skill_input_fallback(self, dispatcher):
        """prepare_input_fn 失败时，回退到 GenericSkillInput。"""
        # 注册一个没有 prepare_input_fn 的假 Skill
        from contract_review.skills.schema import (
            SkillBackend,
            SkillRegistration,
        )

        fake_reg = SkillRegistration(
            skill_id="fake_skill",
            name="Fake",
            description="测试用",
            backend=SkillBackend.LOCAL,
            local_handler="contract_review.skills.local.clause_context.get_clause_context",
            prepare_input_fn=None,
        )
        dispatcher._skills["fake_skill"] = fake_reg

        result = await dispatcher.prepare_and_call(
            "fake_skill", "4.1", {"clauses": []}, {}
        )
        # 应该用 GenericSkillInput 兜底，不应抛异常
        # result 可能 success=False（因为 handler 期望特定 Input 类型），但不应崩溃
        assert result is not None
```

### 4.2 `tests/test_review_graph.py` 改动

更新依赖硬编码 Skill 调用路径的集成测试。主要影响：

- `TestReviewGraph.test_single_clause_no_interrupt` — 如果它依赖 `_build_skill_input` 的行为，需要确保 dispatcher mock 覆盖 `prepare_and_call`
- `TestLLMIntegration` 中的测试 — 确保 mock 的 dispatcher 正确响应 `prepare_and_call` 调用

**原则**：不改变测试的验证目标，只更新 mock 方式以匹配新的调用路径。

### 4.3 SHA/SPA 领域测试补充

为 SHA/SPA 领域的 5 个 Skill 补充 `prepare_input` 验证（当前测试主要覆盖 FIDIC 和通用 Skill）：

```python
@pytest.mark.asyncio
async def test_sha_spa_skills_prepare_input():
    """SHA/SPA 领域 Skill 的 prepare_input 正确构造输入。"""
    dispatcher = _create_dispatcher(domain_id="sha_spa")
    sha_spa_skills = [
        "spa_extract_conditions",
        "spa_extract_reps_warranties",
        "spa_indemnity_analysis",
        "sha_governance_check",
        "transaction_doc_cross_check",
    ]
    state = {
        "our_party": "买方",
        "domain_id": "sha_spa",
        "material_type": "sha",
        "documents": [],
    }
    structure = {
        "clauses": [
            {"clause_id": "5.1", "title": "先决条件", "text": "交割先决条件如下", "children": []}
        ]
    }
    for skill_id in sha_spa_skills:
        reg = dispatcher.get_registration(skill_id)
        if not reg or not reg.prepare_input_fn:
            continue
        from contract_review.skills.dispatcher import _import_handler

        prepare_fn = _import_handler(reg.prepare_input_fn)
        input_data = prepare_fn("5.1", structure, state)
        assert input_data is not None
```

---

## 5. 实施步骤

按以下顺序执行，每步完成后运行全量测试确认无回归：

### 步骤 1：确认 `_extract_clause_text` 的引用范围

```bash
PYTHONPATH=backend/src grep -rn "_extract_clause_text" backend/src/
```

如果仅在 `_build_skill_input` 中使用，标记为待删除。

### 步骤 2：重构 `node_clause_analyze` 的硬编码 Skill 调用

将 `_build_skill_input` + `dispatcher.call` 替换为 `dispatcher.prepare_and_call`。

### 步骤 3：删除 `_build_skill_input()` 函数

连同其内部的 17 个 if/elif 分支、lazy import、以及 `_extract_clause_text()`（如果确认无其他引用）。

### 步骤 4：清理 import

删除 builder.py 中不再需要的 import 语句。

### 步骤 5：更新测试

- 删除 `test_skill_dispatch.py` 中测试 `_build_skill_input` 的用例
- 新增 `TestPrepareAndCallAllSkills` 测试类
- 更新 `test_review_graph.py` 中受影响的集成测试
- 新增 SHA/SPA 领域测试

### 步骤 6：全量回归测试

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

---

## 6. 运行命令

### 6.1 单元测试

```bash
# 运行 Skill dispatch 相关测试
PYTHONPATH=backend/src python -m pytest tests/test_skill_dispatch.py -x -q

# 运行图集成测试
PYTHONPATH=backend/src python -m pytest tests/test_review_graph.py -x -q
```

### 6.2 全量回归测试

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

### 6.3 验证删除完整性

```bash
# 确认 _build_skill_input 已完全移除
grep -rn "_build_skill_input" backend/src/
# 预期输出：无结果

# 确认所有 Skill 都有 prepare_input_fn
PYTHONPATH=backend/src python -c "
from contract_review.graph.builder import _create_dispatcher
d = _create_dispatcher(domain_id='fidic')
for sid in d.skill_ids:
    reg = d.get_registration(sid)
    has_fn = '✓' if reg.prepare_input_fn else '✗'
    print(f'  {has_fn} {sid}: {reg.prepare_input_fn or \"MISSING\"}')
"
```

---

## 7. 验收标准

### 7.1 删除验收

1. `_build_skill_input()` 函数已从 builder.py 中完全删除
2. `grep -rn "_build_skill_input" backend/src/` 无结果
3. builder.py 减少约 230 行代码
4. 不再有任何 Skill Input 类型的 lazy import 残留在 builder.py 中

### 7.2 功能验收

5. `node_clause_analyze` 的非 ReAct 路径使用 `dispatcher.prepare_and_call()` 调用 Skill
6. 所有 17 个 Skill 通过 `prepare_and_call()` 正确构造输入并执行
7. `prepare_input_fn` 失败时，`prepare_and_call` 回退到 `GenericSkillInput`（不崩溃）

### 7.3 测试验收

8. 全量测试通过，无新增失败
9. `TestPrepareAndCallAllSkills` 覆盖所有 17 个 Skill 的 `prepare_input_fn` 注册检查
10. SHA/SPA 领域 Skill 有专门的 `prepare_input` 验证测试
11. 不存在任何测试引用 `_build_skill_input`

### 7.4 向后兼容验收

12. `use_react_agent=False, use_orchestrator=False`（默认模式）下，审查流程行为不变
13. `use_react_agent=True` 时，ReAct 路径不受影响（它已经使用 dispatcher）
14. `use_orchestrator=True` 时，Orchestrator 路径不受影响

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 某个 Skill 的 `prepare_input` 与旧 `_build_skill_input` 行为不完全一致 | 该 Skill 输入构造错误 | 步骤 2 先重构调用方式，步骤 3 再删除旧代码；中间运行全量测试确认 |
| `_extract_clause_text` 被其他地方引用 | 删除后编译错误 | 步骤 1 先确认引用范围，有引用则保留 |
| 测试 mock 不完整导致假通过 | 删除后生产环境出错 | 新增的 `TestPrepareAndCallAllSkills` 直接调用真实的 `prepare_input`，不 mock |
| `GenericSkillInput` 兜底不够 | 未注册 `prepare_input_fn` 的 Skill 执行失败 | 当前所有 17 个 Skill 都已注册，兜底只是防御性代码 |

---

## 9. 与 SPEC-23 的关系

本 SPEC 完成后，builder.py 中的 Skill 调用将统一通过 `dispatcher.prepare_and_call()`。这为 SPEC-23 的统一执行管线奠定基础：

- SPEC-22（本文档）：删除旧路径，确保 dispatcher 是唯一 Skill 调用入口
- SPEC-23：统一 `node_clause_analyze` 的执行模式，合并双开关为单一模式切换，补充端到端集成测试
