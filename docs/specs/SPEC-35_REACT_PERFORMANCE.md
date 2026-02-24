# SPEC-35: GEN3 ReAct 性能治理

## 优先级: P0（模式 A 真实文档跑不完）

## 问题描述

模式 A（LLM 可用）在真实 FIDIC 文档上 120s 内仅处理 4/12 个条款，`is_complete=false`。
根因是 ReAct 编排存在多层性能瓶颈：

1. 条款串行处理，无并发
2. 同一条款内工具调用串行，无并发
3. 无单条款超时机制，挂起的 LLM/工具调用阻塞整条链路
4. 提示词未约束工具调用上限，LLM 可能空转

## 根因定位

| 位置 | 问题 |
|------|------|
| `builder.py` 条款循环 | `current_clause_index` 逐一递增，纯串行 |
| `react_agent.py:60-70` | `for _ in range(max_iterations)` 无超时保护 |
| `react_agent.py:84-112` | 工具调用 `for call in parsed_calls` 串行 await |
| `prompts.py:280-330` | 提示词无"必须调用 suggested_skills"和"最多 N 轮"约束 |
| `config.py:74-75` | 仅有 `react_max_iterations=5`，无超时配置 |

## 修复方案

### 变更 1: 单条款超时 + fallback（`builder.py`）

在 `_analyze_gen3` 中用 `asyncio.wait_for` 包裹 `_run_react_branch`，超时后走 fallback：

```python
import asyncio

REACT_CLAUSE_TIMEOUT = 30  # 秒，可通过 settings 配置

try:
    result = await asyncio.wait_for(
        _run_react_branch(...),
        timeout=float(getattr(settings, "react_clause_timeout", REACT_CLAUSE_TIMEOUT) or REACT_CLAUSE_TIMEOUT),
    )
    if result.get("current_skill_context"):
        return result
    logger.info("gen3 ReAct 返回空 skill_context (clause=%s)，尝试 deterministic fallback", clause_id)
except asyncio.TimeoutError:
    logger.warning("gen3 ReAct 超时 (clause=%s, timeout=%ss)，走 deterministic fallback", clause_id, REACT_CLAUSE_TIMEOUT)
except Exception as exc:
    logger.warning("gen3 ReAct 执行失败 (clause=%s): %s，走 deterministic fallback", clause_id, exc)
```

在 `config.py` 中新增配置项：
```python
react_clause_timeout: int = 30  # 单条款 ReAct 超时秒数
```

### 变更 2: 同条款内工具并发执行（`react_agent.py`）

将工具调用从串行改为并发（同一轮 LLM 返回的多个 tool_calls 可以并行执行）：

```python
# 替换原有的 for call in parsed_calls 串行循环
async def _execute_tool(call, dispatcher, clause_id, primary_structure, state, skill_context):
    skill_id = call.get("skill_id", "")
    llm_arguments = call.get("arguments", {}) or {}
    target_clause_id = str(llm_arguments.get("clause_id", "") or clause_id)
    try:
        result = await dispatcher.prepare_and_call(
            skill_id=skill_id,
            clause_id=target_clause_id,
            primary_structure=primary_structure,
            state=state,
            llm_arguments=llm_arguments,
        )
        if result.success:
            return call, skill_id, result.data, _serialize_tool_result(result.data)
        return call, skill_id, None, json.dumps({"error": result.error or "执行失败"}, ensure_ascii=False)
    except Exception as exc:
        logger.warning("工具 '%s' 执行异常: %s", skill_id, exc)
        return call, skill_id, None, json.dumps({"error": str(exc)}, ensure_ascii=False)

# 在 react_agent_loop 中：
tasks = [
    _execute_tool(call, dispatcher, clause_id, primary_structure, state, skill_context)
    for call in parsed_calls
]
results = await asyncio.gather(*tasks, return_exceptions=True)

for res in results:
    if isinstance(res, Exception):
        continue
    call, skill_id, data, tool_content = res
    if data is not None:
        skill_context[skill_id] = data
    current_messages.append({
        "role": "tool",
        "tool_call_id": call.get("id", ""),
        "content": tool_content,
    })
```

### 变更 3: 提示词约束（`prompts.py`）

在 `build_react_agent_messages` 的工具使用规则中增加约束：

```
【工具使用规则】
1. 你必须优先调用以下建议工具：{suggested_skills_list}
2. 每次可以调用一个或多个工具，但总轮次不超过 {max_iterations} 轮
3. 工具的 clause_id 参数使用当前条款编号：{clause_id}
4. 不需要填写 document_structure 和 state_snapshot 等内部参数，系统会自动注入
5. 当你认为信息足够时，立即输出最终结果，不要再调用工具
6. 如果某个工具返回空结果或错误，不要重复调用同一工具
```

关键改动：
- 规则 1：将 `suggested_skills` 从"建议"升级为"必须优先调用"
- 规则 2：明确告知 LLM 总轮次上限
- 规则 6：禁止重复调用失败工具，防止空转

### 变更 4: ReAct 观测日志（`react_agent.py`）

在每轮迭代结束时记录结构化日志：

```python
logger.info(
    "ReAct iter=%d clause=%s tools_called=%s skill_count=%d",
    iteration + 1,
    clause_id,
    [c.get("skill_id") for c in parsed_calls],
    len(skill_context),
)
```

在循环结束后记录总耗时：

```python
import time
start = time.monotonic()
# ... loop ...
elapsed = time.monotonic() - start
logger.info("ReAct 完成 clause=%s iters=%d skills=%d elapsed=%.1fs", clause_id, iteration + 1, len(skill_context), elapsed)
```

## 验收标准 (AC)

1. AC-1: 单条款 ReAct 超过 `react_clause_timeout` 秒后自动中断并走 deterministic fallback
2. AC-2: 同一轮 LLM 返回的多个 tool_calls 并发执行（`asyncio.gather`）
3. AC-3: 提示词包含 suggested_skills 强约束和轮次上限提示
4. AC-4: 每轮 ReAct 迭代有结构化日志（iteration、tools_called、elapsed）
5. AC-5: `config.py` 新增 `react_clause_timeout` 配置项
6. AC-6: LLM 可用时，12 条款在合理时间内完成（不要求具体秒数，但不应无限挂起）
7. AC-7: 新增单元测试覆盖超时 fallback 和工具并发场景
8. AC-8: 全量测试零回归

## 测试要求

在 `tests/test_react_performance.py`（新建）中：

```python
def test_react_clause_timeout_triggers_fallback():
    """单条款 ReAct 超时后走 deterministic fallback"""

def test_react_tool_calls_concurrent():
    """同一轮多个 tool_calls 并发执行"""

def test_react_prompt_includes_suggested_skills():
    """提示词包含 suggested_skills 约束"""

def test_react_iteration_logging():
    """每轮迭代产生结构化日志"""
```

## 涉及文件

| 文件 | 变更类型 |
|------|---------|
| `backend/src/contract_review/graph/builder.py` | 修改（asyncio.wait_for 超时） |
| `backend/src/contract_review/graph/react_agent.py` | 修改（工具并发 + 观测日志） |
| `backend/src/contract_review/graph/prompts.py` | 修改（提示词约束） |
| `backend/src/contract_review/config.py` | 修改（新增 react_clause_timeout） |
| `tests/test_react_performance.py` | 新建测试 |

## 回归风险

中。涉及 ReAct 核心执行路径的改动：
- 超时机制：可能导致原本能完成的条款被提前中断（但有 fallback 兜底）
- 工具并发：需确保 skill_context 写入无竞态（dict 赋值在 gather 后统一处理）
- 提示词变更：可能影响 LLM 的工具选择行为（但方向是更可控）

建议实施后立即重跑真实文档双模式测试验证。
