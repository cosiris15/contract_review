# SPEC-33: GEN3 编排层 Deterministic Fallback

## 优先级: P1（LLM 不可用时关键技能无输出）

## 问题描述

GEN3 模式下，`_analyze_gen3` 在入口处检查 `llm_client`，若为 None 则直接返回空结果。
ReAct agent 循环也完全依赖 LLM 做工具调度决策。当 LLM 不可用（API key 无效、服务宕机等），
所有 Skill 都不会被执行，`skill_context` 为空，导致 T2~T6 全部失败。

而系统中已有 `_analyze_legacy` 确定性管线，会直接遍历 `required_skills` 逐个调用，
不依赖 LLM 做调度。但 GEN3 模式没有在 LLM 失败时回退到这条路径。

## 根因定位

| 位置 | 问题 |
|------|------|
| `builder.py:617-633` | `_analyze_gen3` 入口 `if not llm_client` 直接返回空，不尝试 fallback |
| `builder.py:659-670` | `_run_react_branch` 异常时也返回空，不尝试 fallback |
| `react_agent.py:67-69` | LLM 调用失败直接 `break`，skill_context 为空 |
| `builder.py:692-716` | `node_clause_analyze` 按 mode 二选一，无降级逻辑 |

## 修复方案

### 核心思路

在 `_analyze_gen3` 中，当 LLM 不可用或 ReAct 执行失败时，回退到确定性 Skill 执行
（复用 `_analyze_legacy` 的 Skill 遍历逻辑），确保规则保底的 Skill 仍能产出结果。

### 变更 1: `builder.py` — `_analyze_gen3` 增加 deterministic fallback

将当前的"LLM 不可用 → 返回空"改为"LLM 不可用 → 走确定性 Skill 管线"：

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
    llm_client = _get_llm_client()

    # --- 尝试 ReAct 路径 ---
    if llm_client and dispatcher and primary_structure:
        settings = get_settings()
        clause_plan = _get_clause_plan(state, clause_id)
        suggested_tools = required_skills
        max_iterations = int(getattr(settings, "react_max_iterations", 5) or 5)
        if clause_plan:
            suggested_tools = clause_plan.suggested_tools or required_skills
            max_iterations = int(clause_plan.max_iterations or max_iterations)

        try:
            result = await _run_react_branch(
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
                temperature=float(getattr(settings, "react_temperature", 0.1) or 0.1),
            )
            # ReAct 成功且有 skill_context → 正常返回
            if result.get("current_skill_context"):
                return result
            # ReAct 返回但 skill_context 为空 → 继续走 fallback
            logger.info("gen3 ReAct 返回空 skill_context (clause=%s)，尝试 deterministic fallback", clause_id)
        except Exception as exc:
            logger.warning("gen3 ReAct 执行失败 (clause=%s): %s，尝试 deterministic fallback", clause_id, exc)
    else:
        logger.info(
            "gen3 缺少 LLM 或必要组件 (llm=%s, dispatcher=%s, structure=%s)，走 deterministic fallback",
            bool(llm_client), bool(dispatcher), bool(primary_structure),
        )

    # --- Deterministic fallback: 直接遍历 required_skills ---
    return await _deterministic_skill_fallback(
        state=state,
        dispatcher=dispatcher,
        clause_id=clause_id,
        clause_name=clause_name,
        description=description,
        primary_structure=primary_structure,
        required_skills=required_skills,
    )
```

### 变更 2: `builder.py` — 新增 `_deterministic_skill_fallback` 函数

从 `_analyze_legacy` 的 Skill 遍历逻辑中提取，专注于确定性 Skill 执行：

```python
async def _deterministic_skill_fallback(
    *,
    state: ReviewGraphState,
    dispatcher: SkillDispatcher | None,
    clause_id: str,
    clause_name: str,
    description: str,
    primary_structure: Any,
    required_skills: list[str],
) -> Dict[str, Any]:
    """LLM 不可用时的确定性 Skill 执行管线。"""
    skill_context: Dict[str, Any] = {}

    if dispatcher and primary_structure:
        for skill_id in required_skills:
            if skill_id not in dispatcher.skill_ids:
                continue
            try:
                skill_result = await dispatcher.prepare_and_call(
                    skill_id,
                    clause_id,
                    primary_structure,
                    dict(state),
                )
                if skill_result.success and skill_result.data:
                    skill_context[skill_id] = skill_result.data
            except Exception as exc:
                logger.warning("Deterministic fallback: Skill '%s' 调用失败: %s", skill_id, exc)

    # 提取条款文本
    clause_text = ""
    context = skill_context.get("get_clause_context")
    if isinstance(context, dict):
        clause_text = str(context.get("context_text", "") or "")
    if not clause_text and primary_structure:
        clause_text = _extract_clause_text(primary_structure, clause_id)
    if not clause_text:
        clause_text = f"{clause_name}\n{description}".strip() or clause_id

    return {
        "current_clause_id": clause_id,
        "current_clause_text": clause_text,
        "current_risks": [],  # 无 LLM 时不生成风险评估
        "current_skill_context": skill_context,
        "current_diffs": [],
        "agent_messages": None,
        "clause_retry_count": 0,
    }
```

### 变更 3（可选）: `react_agent.py` — LLM 失败后返回已收集的 skill_context

当前 `break` 后返回 `[], skill_context, current_messages`，如果 LLM 在第 2+ 轮失败，
已经收集到部分 skill_context。这个行为已经是正确的（line 115），无需修改。
但建议在 break 前增加一行 info 日志：

```python
except Exception as exc:
    logger.warning("ReAct LLM 调用失败: %s", exc)
    logger.info("ReAct 中断，已收集 %d 个 skill 结果", len(skill_context))
    break
```

## 验收标准 (AC)

1. AC-1: LLM 不可用时（无效 API key），GEN3 模式下 `skill_context` 不为空 — 至少包含规则保底 Skill 的输出
2. AC-2: LLM 可用时，GEN3 模式行为不变（仍走 ReAct 路径）
3. AC-3: ReAct 执行成功但 skill_context 为空时，触发 deterministic fallback
4. AC-4: ReAct 执行抛异常时，触发 deterministic fallback 而非返回空结果
5. AC-5: `_deterministic_skill_fallback` 遍历 `required_skills` 并调用每个已注册 Skill
6. AC-6: 新增单元测试覆盖上述场景

## 测试要求

在 `tests/test_gen3_fallback.py`（新建）中：

```python
def test_gen3_fallback_when_llm_unavailable():
    """LLM client 为 None 时，走 deterministic fallback，skill_context 非空"""

def test_gen3_fallback_when_react_fails():
    """ReAct 抛异常时，走 deterministic fallback"""

def test_gen3_fallback_when_react_returns_empty_context():
    """ReAct 返回空 skill_context 时，走 deterministic fallback"""

def test_gen3_normal_path_when_llm_available():
    """LLM 可用且 ReAct 正常时，不走 fallback"""

def test_deterministic_fallback_calls_all_required_skills():
    """fallback 管线遍历 required_skills 并调用每个已注册 Skill"""

def test_deterministic_fallback_skips_unregistered_skills():
    """未注册的 skill_id 被跳过，不报错"""
```

## 涉及文件

| 文件 | 变更类型 |
|------|---------|
| `backend/src/contract_review/graph/builder.py` | 修改（_analyze_gen3 增加 fallback + 新增 _deterministic_skill_fallback） |
| `backend/src/contract_review/graph/react_agent.py` | 修改（可选：增加 info 日志） |
| `tests/test_gen3_fallback.py` | 新建测试 |

## 回归风险

中低。核心变更在 `_analyze_gen3` 的控制流：
- LLM 可用 + ReAct 成功 + skill_context 非空 → 行为完全不变
- 仅在 LLM 不可用或 ReAct 失败/空结果时触发新路径
- `_deterministic_skill_fallback` 逻辑复用自已验证的 `_analyze_legacy` 模式
