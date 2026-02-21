# SPEC-20: ReAct Agent 节点（LLM 自主选择工具）

> 优先级：高（架构改造三步走的第二步）
> 前置依赖：SPEC-19（工具自描述层，提供 tool definitions 和 prepare_input 机制）
> 预计新建文件：2 个 | 修改文件：4 个
> 范围：`node_clause_analyze` 核心改造，影响条款审查的工具选择逻辑

---

## 0. 架构演进上下文

### 0.1 回顾：三步走计划

```
SPEC-19（已完成）          SPEC-20（本文档）           SPEC-21
工具自描述层          →    ReAct Agent 节点      →    Orchestrator 编排层
让工具能被 LLM 理解        让 LLM 自主选择工具         让 LLM 自主编排流程
```

SPEC-19 解决了"工具如何被 LLM 理解"的问题——每个 Skill 现在能生成 OpenAI Function Calling 格式的 tool definition，`SkillDispatcher` 能一键导出所有工具定义。

SPEC-20 要解决的是：**让 LLM 自主决定调用哪些工具，而不是由 checklist 中的 `required_skills` 硬编码决定。**

### 0.2 当前问题：硬编码的工具选择

当前 `node_clause_analyze`（builder.py 第 522-610 行）的工具调用逻辑是：

```python
# 当前：工具选择完全由 checklist 硬编码
required_skills = item.get("required_skills", [])  # 从 checklist 读取
for skill_id in required_skills:
    skill_input = _build_skill_input(skill_id, clause_id, primary_structure, state)
    skill_result = await dispatcher.call(skill_id, skill_input)
    skill_context[skill_id] = skill_result.data
```

这个设计的问题：

1. **工具选择不智能**：每个条款调用哪些工具是在 checklist 中写死的。条款 4.1 永远调用 `[get_clause_context, fidic_merge_gc_pc, compare_with_baseline, ...]`，不管条款内容是什么
2. **无法根据中间结果调整**：如果 `compare_with_baseline` 发现了重大偏离，当前流程不会自动追加 `assess_deviation`——除非 checklist 里预先写了
3. **新增工具需要改 checklist**：每新增一个 Skill，必须手动修改所有相关条款的 `required_skills` 列表
4. **LLM 的判断力被浪费**：LLM 完全有能力根据条款内容判断"这个条款需要做时效分析"还是"这个条款需要做财务条款提取"，但当前架构不给它这个机会

### 0.3 目标架构：ReAct Agent

改造后，`node_clause_analyze` 内部将运行一个 ReAct（Reasoning + Acting）循环：

```
┌─────────────────────────────────────────────────┐
│  node_clause_analyze（ReAct Agent）               │
│                                                   │
│  1. LLM 看到条款文本 + 所有可用工具的描述          │
│  2. LLM 决定："我需要先调用 get_clause_context"    │
│  3. 执行工具，将结果反馈给 LLM                     │
│  4. LLM 决定："基于上下文，我还需要 compare_with_  │
│     baseline 和 extract_financial_terms"           │
│  5. 执行工具，将结果反馈给 LLM                     │
│  6. LLM 决定："信息足够了，输出风险分析结果"        │
│  7. 输出结构化的 risks                             │
│                                                   │
│  循环次数由 LLM 自主决定（上限 max_iterations）     │
└─────────────────────────────────────────────────┘
```

关键变化：
- **工具选择权从 checklist 转移到 LLM**
- **LLM 可以根据中间结果动态追加工具调用**
- **checklist 中的 `required_skills` 变为"建议工具"而非"必须工具"**
- **`LLMClient.chat_with_tools()` 终于被启用**

### 0.4 为什么选择 ReAct 而非 Plan-and-Execute

两种主流 Agent 模式的对比：

| 维度 | ReAct | Plan-and-Execute |
|------|-------|-----------------|
| 工作方式 | 每步推理+行动，逐步推进 | 先生成完整计划，再逐步执行 |
| 适合场景 | 信息逐步揭示，需要根据中间结果调整 | 任务结构清晰，步骤可预知 |
| LLM 调用次数 | 较多（每步一次） | 较少（计划一次 + 执行多次） |
| 容错性 | 高（每步可调整） | 低（计划错误需要重新规划） |

选择 ReAct 的原因：
- 合同条款审查天然是"信息逐步揭示"的场景——先看条款文本，再决定需要什么分析
- 不同条款需要的工具组合差异很大，难以预先规划
- ReAct 的实现更简单，与现有 `chat_with_tools` 接口天然匹配
- 后续 SPEC-21 可以在 Orchestrator 层引入 Plan-and-Execute，两者不冲突

### 0.5 向后兼容策略

**关键原则：ReAct 模式是可选的，可以随时回退到硬编码模式。**

- 新增 `use_react_agent: bool` 配置项，默认 `False`
- `False` 时：行为与当前完全一致（遍历 `required_skills`）
- `True` 时：启用 ReAct Agent 循环
- checklist 中的 `required_skills` 在 ReAct 模式下变为"建议工具"（suggested_skills），LLM 可以参考但不必全部调用
- 如果 ReAct 循环失败（LLM 不返回 tool_calls 也不返回分析结果），自动回退到硬编码模式

---

## 1. 设计方案

### 1.1 ReAct 循环核心逻辑

```python
async def _react_agent_loop(
    llm_client: LLMClient,
    dispatcher: SkillDispatcher,
    clause_id: str,
    clause_text: str,
    primary_structure: Any,
    state: dict,
    *,
    suggested_skills: list[str] | None = None,
    max_iterations: int = 5,
    domain_id: str | None = None,
    language: str = "zh-CN",
    our_party: str = "",
) -> tuple[list[dict], dict[str, Any]]:
    """运行 ReAct Agent 循环，返回 (risks, skill_context)。

    流程：
    1. 构造初始 messages（system + user），包含条款信息和建议工具
    2. 获取所有可用工具的 tool definitions
    3. 循环：
       a. 调用 LLM（chat_with_tools）
       b. 如果 LLM 返回 tool_calls → 执行工具 → 将结果追加到 messages → 继续循环
       c. 如果 LLM 返回文本（无 tool_calls）→ 解析为 risks → 结束循环
    4. 返回 risks 和 skill_context
    """
```

### 1.2 消息流示例

一个典型的 ReAct 循环消息流：

```
messages = [
    {"role": "system", "content": "你是合同审查专家...以下是你可以使用的工具..."},
    {"role": "user", "content": "请审查条款 4.1：[条款文本]..."},

    # --- 第 1 轮 ---
    {"role": "assistant", "content": null, "tool_calls": [
        {"id": "call_1", "function": {"name": "get_clause_context", "arguments": "{\"clause_id\": \"4.1\"}"}}
    ]},
    {"role": "tool", "tool_call_id": "call_1", "content": "{\"context_text\": \"...\"}"},

    # --- 第 2 轮 ---
    {"role": "assistant", "content": null, "tool_calls": [
        {"id": "call_2", "function": {"name": "compare_with_baseline", "arguments": "{\"clause_id\": \"4.1\"}"}},
        {"id": "call_3", "function": {"name": "extract_financial_terms", "arguments": "{\"clause_id\": \"4.1\"}"}}
    ]},
    {"role": "tool", "tool_call_id": "call_2", "content": "{\"modification_type\": \"modified\", ...}"},
    {"role": "tool", "tool_call_id": "call_3", "content": "{\"terms\": [...]}"},

    # --- 第 3 轮（最终输出）---
    {"role": "assistant", "content": "[{\"risk_level\": \"high\", \"description\": \"...\"}]"}
]
```

### 1.3 工具执行桥接

LLM 通过 tool_calls 只提供 `skill_id` 和简单参数（如 `clause_id`）。但实际执行 Skill 需要 `primary_structure`、`state` 等系统参数。这个桥接由 SPEC-19 的 `dispatcher.prepare_and_call()` 完成：

```python
# LLM 返回: {"name": "compare_with_baseline", "arguments": {"clause_id": "4.1"}}
# 实际执行:
result = await dispatcher.prepare_and_call(
    skill_id="compare_with_baseline",
    clause_id="4.1",
    primary_structure=primary_structure,
    state=state,
    llm_arguments={"clause_id": "4.1"},  # LLM 提供的参数
)
```

`prepare_and_call` 内部会调用 Skill 的 `prepare_input` 从 state 中提取完整参数，LLM 不需要知道 `document_structure` 或 `state_snapshot` 这些内部细节。

---

## 2. 文件清单

### 新增文件（2 个）

| 文件路径 | 用途 |
|---------|------|
| `backend/src/contract_review/graph/react_agent.py` | ReAct Agent 循环实现 |
| `tests/test_react_agent.py` | 单元测试 |

### 修改文件（4 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/graph/builder.py` | `node_clause_analyze` 新增 ReAct 分支；新增 `use_react_agent` 判断 |
| `backend/src/contract_review/graph/prompts.py` | 新增 `build_react_agent_messages()` 构造 ReAct 专用 prompt |
| `backend/src/contract_review/graph/state.py` | `ReviewGraphState` 新增 `agent_messages` 字段（可选） |
| `backend/src/contract_review/config.py` | 新增 `use_react_agent: bool` 配置项 |

### 不需要修改的文件

- `llm_client.py` — `chat_with_tools()` 已存在，无需改动
- `dispatcher.py` — SPEC-19 已添加 `prepare_and_call()` 和 `get_tool_definitions()`
- `tool_adapter.py` — SPEC-19 已实现 `parse_tool_calls()`
- `schema.py` — SPEC-19 已添加 `to_tool_definition()`
- 各 Skill 文件 — 无需改动

---

## 3. `react_agent.py`（新增）

### 3.1 职责

实现 ReAct Agent 循环的核心逻辑。这是一个独立模块，不依赖 LangGraph，可以被任何 node 调用。

### 3.2 完整实现

```python
"""ReAct Agent: LLM-driven tool selection loop for clause analysis."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from ..llm_client import LLMClient
from ..skills.dispatcher import SkillDispatcher
from ..skills.tool_adapter import parse_tool_calls
from .llm_utils import parse_json_response

logger = logging.getLogger(__name__)

# 工具执行结果的最大字符数，超过则截断（防止 context 爆炸）
MAX_TOOL_RESULT_CHARS = 3000


def _truncate(text: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """截断过长的工具执行结果。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... (截断，原文 {len(text)} 字符)"


def _serialize_tool_result(result_data: Any) -> str:
    """将工具执行结果序列化为 LLM 可读的字符串。"""
    if result_data is None:
        return "{}"
    if isinstance(result_data, str):
        return _truncate(result_data)
    try:
        return _truncate(json.dumps(result_data, ensure_ascii=False, indent=2))
    except (TypeError, ValueError):
        return _truncate(str(result_data))


async def react_agent_loop(
    llm_client: LLMClient,
    dispatcher: SkillDispatcher,
    messages: List[Dict[str, Any]],
    clause_id: str,
    primary_structure: Any,
    state: dict,
    *,
    max_iterations: int = 5,
    temperature: float = 0.1,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    """运行 ReAct Agent 循环。

    Args:
        llm_client: LLM 客户端
        dispatcher: Skill 调度器（已注册所有可用工具）
        messages: 初始消息列表（system + user）
        clause_id: 当前条款 ID
        primary_structure: 主文档结构
        state: 完整的 ReviewGraphState（dict 形式）
        max_iterations: 最大循环次数（防止无限循环）
        temperature: LLM 温度参数

    Returns:
        (risks, skill_context, final_messages)
        - risks: 解析后的风险点列表
        - skill_context: 所有工具执行结果的汇总
        - final_messages: 完整的消息历史（用于调试和 state 存储）
    """
    # 获取所有可用工具的 tool definitions
    tools = dispatcher.get_tool_definitions(
        domain_filter=state.get("domain_id"),
    )

    if not tools:
        logger.warning("没有可用的 tool definitions，跳过 ReAct 循环")
        return [], {}, messages

    skill_context: Dict[str, Any] = {}
    current_messages = list(messages)  # 复制，不修改原始列表

    for iteration in range(max_iterations):
        logger.info(
            "ReAct 循环 #%d/%d (clause=%s, tools=%d, messages=%d)",
            iteration + 1, max_iterations, clause_id, len(tools), len(current_messages),
        )

        try:
            response_text, tool_calls = await llm_client.chat_with_tools(
                current_messages,
                tools=tools,
                temperature=temperature,
            )
        except Exception as exc:
            logger.error("ReAct LLM 调用失败 (iteration=%d): %s", iteration + 1, exc)
            break

        # 情况 1：LLM 返回文本，无 tool_calls → 解析为最终结果
        if not tool_calls:
            logger.info("ReAct 循环结束：LLM 返回最终文本 (iteration=%d)", iteration + 1)
            risks = _parse_final_response(response_text)
            current_messages.append({"role": "assistant", "content": response_text})
            return risks, skill_context, current_messages

        # 情况 2：LLM 返回 tool_calls → 执行工具
        # 将 assistant 消息（含 tool_calls）追加到历史
        current_messages.append({
            "role": "assistant",
            "content": response_text or None,
            "tool_calls": tool_calls,
        })

        # 解析并执行每个 tool_call
        parsed_calls = parse_tool_calls(tool_calls)
        for call in parsed_calls:
            skill_id = call["skill_id"]
            call_id = call["id"]
            llm_arguments = call["arguments"]

            logger.info("执行工具: %s (call_id=%s, args=%s)", skill_id, call_id, llm_arguments)

            tool_result_content = ""
            try:
                result = await dispatcher.prepare_and_call(
                    skill_id=skill_id,
                    clause_id=llm_arguments.get("clause_id", clause_id),
                    primary_structure=primary_structure,
                    state=state,
                    llm_arguments=llm_arguments,
                )
                if result.success:
                    skill_context[skill_id] = result.data
                    tool_result_content = _serialize_tool_result(result.data)
                else:
                    tool_result_content = json.dumps(
                        {"error": result.error or "执行失败"}, ensure_ascii=False
                    )
            except Exception as exc:
                logger.warning("工具 '%s' 执行异常: %s", skill_id, exc)
                tool_result_content = json.dumps(
                    {"error": str(exc)}, ensure_ascii=False
                )

            # 将工具结果追加到消息历史
            current_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_result_content,
            })

    # 达到最大循环次数，尝试从最后一次响应中提取结果
    logger.warning(
        "ReAct 循环达到最大次数 %d (clause=%s)，尝试提取已有结果",
        max_iterations, clause_id,
    )
    return [], skill_context, current_messages


def _parse_final_response(response_text: str) -> List[Dict[str, Any]]:
    """解析 LLM 的最终文本响应为风险点列表。"""
    if not response_text or not response_text.strip():
        return []
    try:
        risks = parse_json_response(response_text, expect_list=True)
        return [r for r in risks if isinstance(r, dict)]
    except Exception as exc:
        logger.warning("ReAct 最终响应解析失败: %s", exc)
        return []
```

### 3.3 设计说明

- **`react_agent_loop` 是纯函数式设计**：接收所有依赖作为参数，不依赖全局状态，方便测试
- **消息历史完整保留**：`final_messages` 包含完整的 ReAct 对话历史，可存入 state 用于调试
- **工具结果截断**：`MAX_TOOL_RESULT_CHARS` 防止单个工具输出过大导致 context window 溢出
- **graceful 降级**：LLM 调用失败或达到最大循环次数时，返回空 risks + 已收集的 skill_context
- **并行工具调用**：LLM 可以在一次响应中返回多个 tool_calls（如同时调用 `compare_with_baseline` 和 `extract_financial_terms`），代码会顺序执行它们并将所有结果一起反馈

---

## 4. `prompts.py` 改动

### 4.1 新增 `build_react_agent_messages()`

```python
REACT_AGENT_SYSTEM = """你是一位资深法务审阅专家，正在逐条审查合同条款。

{anti_injection}

{jurisdiction_instruction}

{domain_instruction}

【你的任务】
分析以下条款，从我方（{our_party}）的角度识别风险点。

【工作方式】
你可以使用以下工具来辅助分析。请根据条款内容自主判断需要调用哪些工具：
- 先调用 get_clause_context 获取条款完整上下文
- 根据条款类型，选择性调用其他分析工具
- 收集到足够信息后，输出最终的风险分析结果

{suggested_skills_hint}

【工具使用规则】
1. 每次可以调用一个或多个工具
2. 工具的 clause_id 参数使用当前条款编号：{clause_id}
3. 不需要填写 document_structure 和 state_snapshot 等内部参数，系统会自动注入
4. 当你认为信息足够时，直接输出最终结果，不要再调用工具

【最终输出要求】
当你完成分析后，以 JSON 数组格式输出风险点列表，字段必须包含：
- risk_level: high|medium|low
- risk_type: 风险类型
- description: 风险描述
- reason: 风险原因
- analysis: 详细分析
- original_text: 相关原文

如果该条款无风险，返回 []。
最终输出只包含 JSON，不要输出其他内容。"""


def _build_suggested_skills_hint(suggested_skills: list[str] | None, dispatcher: SkillDispatcher) -> str:
    """根据 checklist 中的 suggested_skills 生成提示。"""
    if not suggested_skills:
        return ""

    lines = ["【建议工具】以下工具可能对本条款的分析有帮助（仅供参考，你可以自主决定是否使用）："]
    for skill_id in suggested_skills:
        reg = dispatcher.get_registration(skill_id)
        if reg:
            lines.append(f"- {skill_id}: {reg.description}")
    return "\n".join(lines)


def build_react_agent_messages(
    *,
    language: str,
    our_party: str,
    clause_id: str,
    clause_name: str,
    description: str,
    priority: str,
    clause_text: str,
    domain_id: str | None = None,
    suggested_skills: list[str] | None = None,
    dispatcher: SkillDispatcher | None = None,
) -> list[dict[str, str]]:
    """构造 ReAct Agent 的初始消息。

    与 build_clause_analyze_messages 的区别：
    1. system prompt 包含工具使用指引
    2. 不包含 skill_context（由 Agent 自己收集）
    3. 包含 suggested_skills 提示
    """
    domain_instruction = ""
    if domain_id == "fidic":
        domain_instruction = FIDIC_DOMAIN_INSTRUCTION.format(
            merge_context="（请使用 fidic_merge_gc_pc 工具获取）",
            time_bar_context="（请使用 fidic_calculate_time_bar 工具获取）",
            er_context="（请使用 fidic_search_er 工具获取）",
        )
    elif domain_id == "sha_spa":
        domain_instruction = SHA_SPA_DOMAIN_INSTRUCTION.format(
            conditions_context="（请使用 spa_extract_conditions 工具获取）",
            rw_context="（请使用 spa_extract_reps_warranties 工具获取）",
            indemnity_context="（请使用 spa_indemnity_analysis 工具获取）",
        )

    suggested_hint = ""
    if suggested_skills and dispatcher:
        suggested_hint = _build_suggested_skills_hint(suggested_skills, dispatcher)

    system = REACT_AGENT_SYSTEM.format(
        anti_injection=_anti_injection_instruction(language, our_party),
        jurisdiction_instruction=_jurisdiction_instruction(language),
        domain_instruction=domain_instruction,
        our_party=our_party,
        suggested_skills_hint=suggested_hint,
        clause_id=clause_id,
    )

    user = (
        f"【条款信息】\n"
        f"- 条款编号：{clause_id}\n"
        f"- 条款名称：{clause_name}\n"
        f"- 审查重点：{description}\n"
        f"- 优先级：{priority}\n\n"
        f"【条款原文】\n<<<CLAUSE_START>>>\n{clause_text}\n<<<CLAUSE_END>>>"
    )

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

### 4.2 设计说明

- **`suggested_skills_hint`**：将 checklist 中的 `required_skills` 转为"建议"而非"命令"，LLM 可以参考但不必全部调用
- **domain_instruction 中的占位符**：在 ReAct 模式下，domain 指引中的上下文信息改为提示 LLM 使用对应工具获取，而非预先注入
- **与原有 prompt 的关系**：`build_react_agent_messages` 是新增函数，不修改 `build_clause_analyze_messages`。两者共存，由 `use_react_agent` 配置决定使用哪个

---

## 5. `builder.py` 改动

### 5.1 `node_clause_analyze` 新增 ReAct 分支

```python
async def node_clause_analyze(
    state: ReviewGraphState, dispatcher: SkillDispatcher | None = None
) -> Dict[str, Any]:
    checklist = state.get("review_checklist", [])
    index = state.get("current_clause_index", 0)
    if index >= len(checklist):
        return {}

    item = _as_dict(checklist[index])
    clause_id = item.get("clause_id", "")
    clause_name = item.get("clause_name", "")
    description = item.get("description", "")
    priority = item.get("priority", "medium")
    our_party = state.get("our_party", "")
    language = state.get("language", "en")
    required_skills = item.get("required_skills", [])

    primary_structure = state.get("primary_structure")

    # --- 新增：ReAct Agent 分支 ---
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
                suggested_skills=required_skills,
            )
        except Exception as exc:
            logger.warning(
                "ReAct Agent 失败 (clause=%s)，回退到硬编码模式: %s",
                clause_id, exc,
            )
            # 回退到下面的硬编码分支

    # --- 原有硬编码分支（保持不变）---
    skill_context: Dict[str, Any] = {}
    if dispatcher and primary_structure:
        for skill_id in required_skills:
            # ... 原有代码完全不变 ...
```

### 5.2 `_run_react_branch` 辅助函数

```python
async def _run_react_branch(
    *,
    llm_client: LLMClient,
    dispatcher: SkillDispatcher,
    clause_id: str,
    clause_name: str,
    description: str,
    priority: str,
    our_party: str,
    language: str,
    primary_structure: Any,
    state: ReviewGraphState,
    suggested_skills: list[str] | None = None,
) -> Dict[str, Any]:
    """ReAct Agent 分支：LLM 自主选择工具并分析条款。"""
    from .react_agent import react_agent_loop
    from .prompts import build_react_agent_messages

    # 先获取条款文本（get_clause_context 是基础工具，预先执行以提供给 prompt）
    clause_text = _extract_clause_text(primary_structure, clause_id)
    if not clause_text:
        clause_text = f"{clause_name}\n{description}".strip() or clause_id

    # 构造初始消息
    messages = build_react_agent_messages(
        language=language,
        our_party=our_party,
        clause_id=clause_id,
        clause_name=clause_name,
        description=description,
        priority=priority,
        clause_text=clause_text,
        domain_id=state.get("domain_id"),
        suggested_skills=suggested_skills,
        dispatcher=dispatcher,
    )

    # 运行 ReAct 循环
    risks_raw, skill_context, final_messages = await react_agent_loop(
        llm_client=llm_client,
        dispatcher=dispatcher,
        messages=messages,
        clause_id=clause_id,
        primary_structure=primary_structure,
        state=dict(state),
        max_iterations=5,
    )

    # 标准化 risks 格式（与原有逻辑一致）
    risks = []
    for raw in risks_raw:
        row = _as_dict(raw)
        original_text = row.get("original_text", "")
        risks.append({
            "id": generate_id(),
            "risk_level": _normalize_risk_level(row.get("risk_level")),
            "risk_type": row.get("risk_type", "未分类风险"),
            "description": row.get("description", ""),
            "reason": row.get("reason", ""),
            "analysis": row.get("analysis", ""),
            "location": {"original_text": original_text} if original_text else None,
        })

    return {
        "current_clause_id": clause_id,
        "current_clause_text": clause_text,
        "current_risks": risks,
        "current_diffs": [],
        "current_skill_context": skill_context,
        "clause_retry_count": 0,
    }
```

### 5.3 关键设计决策

1. **`_run_react_branch` 的输出格式与原有分支完全一致**：返回相同的 dict 结构，下游 node（`node_clause_generate_diffs`、`node_clause_validate`）无需任何改动

2. **ReAct 失败时自动回退**：如果 `_run_react_branch` 抛异常，`node_clause_analyze` 会 catch 并继续执行原有的硬编码分支。这保证了即使 ReAct 有 bug，系统仍然可用

3. **`suggested_skills` 传递**：checklist 中的 `required_skills` 在 ReAct 模式下变为 `suggested_skills`，通过 prompt 告诉 LLM"这些工具可能有用"，但 LLM 可以自主决定

---

## 6. `state.py` 和 `config.py` 改动

### 6.1 `state.py` 新增字段

```python
class ReviewGraphState(TypedDict, total=False):
    # ... 现有字段不变 ...

    # --- 新增：ReAct Agent 相关 ---
    agent_messages: Optional[List[Dict[str, Any]]]
    # ReAct 循环的完整消息历史，用于调试和审计
    # 仅在 use_react_agent=True 时填充
```

### 6.2 `config.py` 新增配置

```python
class AppSettings(BaseModel):
    # ... 现有字段不变 ...

    # --- 新增：ReAct Agent 配置 ---
    use_react_agent: bool = False
    # 是否启用 ReAct Agent 模式
    # False: 使用原有的硬编码 required_skills 模式
    # True: 使用 LLM 自主选择工具的 ReAct 模式

    react_max_iterations: int = 5
    # ReAct 循环的最大迭代次数

    react_temperature: float = 0.1
    # ReAct Agent 的 LLM 温度参数（低温度 = 更确定性的工具选择）
```

### 6.3 环境变量映射

```
USE_REACT_AGENT=true          → use_react_agent=True
REACT_MAX_ITERATIONS=5        → react_max_iterations=5
REACT_TEMPERATURE=0.1         → react_temperature=0.1
```

---

## 7. 测试要求

### 7.1 测试文件：`tests/test_react_agent.py`

#### 7.1.1 核心循环测试

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from contract_review.graph.react_agent import (
    react_agent_loop,
    _parse_final_response,
    _truncate,
    _serialize_tool_result,
    MAX_TOOL_RESULT_CHARS,
)
from contract_review.skills.schema import SkillResult


# --- 辅助工具 ---

def _make_fake_llm(responses: list):
    """创建一个按顺序返回预设响应的 fake LLM client。

    responses 中每个元素是 (text, tool_calls) 元组。
    """
    client = AsyncMock()
    client.chat_with_tools = AsyncMock(side_effect=responses)
    return client


def _make_fake_dispatcher(skill_ids: list[str], results: dict[str, dict] | None = None):
    """创建一个 fake dispatcher。

    results: {skill_id: data_dict} 映射，prepare_and_call 返回对应的 SkillResult。
    """
    dispatcher = MagicMock()
    dispatcher.skill_ids = skill_ids
    dispatcher.get_tool_definitions.return_value = [
        {
            "type": "function",
            "function": {
                "name": sid,
                "description": f"Tool {sid}",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
        for sid in skill_ids
    ]

    results = results or {}

    async def fake_prepare_and_call(skill_id, clause_id, primary_structure, state, **kwargs):
        data = results.get(skill_id, {"status": "ok"})
        return SkillResult(skill_id=skill_id, success=True, data=data)

    dispatcher.prepare_and_call = AsyncMock(side_effect=fake_prepare_and_call)
    return dispatcher


# --- 核心循环测试 ---

class TestReactAgentLoop:
    @pytest.mark.asyncio
    async def test_single_iteration_no_tools(self):
        """LLM 第一轮就返回文本（不调用工具），循环立即结束。"""
        llm = _make_fake_llm([
            ('[{"risk_level": "low", "description": "无重大风险"}]', None),
        ])
        dispatcher = _make_fake_dispatcher(["get_clause_context"])
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]

        risks, skill_ctx, final_msgs = await react_agent_loop(
            llm, dispatcher, messages, "4.1", {}, {},
        )

        assert len(risks) == 1
        assert risks[0]["risk_level"] == "low"
        assert skill_ctx == {}  # 没有调用工具
        assert len(final_msgs) == 3  # system + user + assistant

    @pytest.mark.asyncio
    async def test_tool_call_then_final_response(self):
        """LLM 先调用一个工具，再返回最终结果。典型的 2 轮循环。"""
        tool_calls = [
            {"id": "call_1", "function": {"name": "get_clause_context", "arguments": '{"clause_id": "4.1"}'}},
        ]
        llm = _make_fake_llm([
            ("", tool_calls),  # 第 1 轮：调用工具
            ('[{"risk_level": "high", "description": "义务范围被扩大"}]', None),  # 第 2 轮：最终结果
        ])
        dispatcher = _make_fake_dispatcher(
            ["get_clause_context"],
            {"get_clause_context": {"context_text": "条款 4.1 全文..."}},
        )
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]

        risks, skill_ctx, final_msgs = await react_agent_loop(
            llm, dispatcher, messages, "4.1", {}, {},
        )

        assert len(risks) == 1
        assert risks[0]["risk_level"] == "high"
        assert "get_clause_context" in skill_ctx
        # messages: system + user + assistant(tool_calls) + tool + assistant(final)
        assert len(final_msgs) == 5

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_one_round(self):
        """LLM 在一轮中同时调用多个工具。"""
        tool_calls = [
            {"id": "call_1", "function": {"name": "compare_with_baseline", "arguments": '{"clause_id": "4.1"}'}},
            {"id": "call_2", "function": {"name": "extract_financial_terms", "arguments": '{"clause_id": "4.1"}'}},
        ]
        llm = _make_fake_llm([
            ("", tool_calls),
            ("[]", None),  # 无风险
        ])
        dispatcher = _make_fake_dispatcher(
            ["compare_with_baseline", "extract_financial_terms"],
            {
                "compare_with_baseline": {"modification_type": "unmodified"},
                "extract_financial_terms": {"terms": []},
            },
        )
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]

        risks, skill_ctx, final_msgs = await react_agent_loop(
            llm, dispatcher, messages, "4.1", {}, {},
        )

        assert risks == []
        assert "compare_with_baseline" in skill_ctx
        assert "extract_financial_terms" in skill_ctx
        # messages: system + user + assistant(2 tool_calls) + tool + tool + assistant(final)
        assert len(final_msgs) == 6

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self):
        """达到最大循环次数时，返回空 risks + 已收集的 skill_context。"""
        tool_calls = [
            {"id": "call_1", "function": {"name": "get_clause_context", "arguments": "{}"}},
        ]
        # LLM 永远返回 tool_calls，不返回最终结果
        llm = _make_fake_llm([("", tool_calls)] * 3)
        dispatcher = _make_fake_dispatcher(["get_clause_context"])
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]

        risks, skill_ctx, _ = await react_agent_loop(
            llm, dispatcher, messages, "4.1", {}, {},
            max_iterations=3,
        )

        assert risks == []
        assert "get_clause_context" in skill_ctx

    @pytest.mark.asyncio
    async def test_llm_failure_breaks_loop(self):
        """LLM 调用失败时，循环中断，返回已收集的结果。"""
        llm = _make_fake_llm([Exception("API timeout")])
        dispatcher = _make_fake_dispatcher(["get_clause_context"])
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]

        risks, skill_ctx, _ = await react_agent_loop(
            llm, dispatcher, messages, "4.1", {}, {},
        )

        assert risks == []
        assert skill_ctx == {}

    @pytest.mark.asyncio
    async def test_tool_execution_failure_continues(self):
        """单个工具执行失败时，循环继续（不中断）。"""
        tool_calls = [
            {"id": "call_1", "function": {"name": "broken_tool", "arguments": "{}"}},
        ]
        llm = _make_fake_llm([
            ("", tool_calls),
            ('[{"risk_level": "medium", "description": "test"}]', None),
        ])
        dispatcher = _make_fake_dispatcher(["broken_tool"])
        # 让 prepare_and_call 抛异常
        dispatcher.prepare_and_call = AsyncMock(side_effect=RuntimeError("工具崩溃"))
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]

        risks, skill_ctx, final_msgs = await react_agent_loop(
            llm, dispatcher, messages, "4.1", {}, {},
        )

        assert len(risks) == 1
        # 工具失败的错误信息被传回给 LLM
        tool_msg = [m for m in final_msgs if m.get("role") == "tool"][0]
        assert "工具崩溃" in tool_msg["content"]

    @pytest.mark.asyncio
    async def test_no_tools_available(self):
        """没有可用工具时，直接返回空结果。"""
        llm = _make_fake_llm([])
        dispatcher = MagicMock()
        dispatcher.get_tool_definitions.return_value = []
        messages = [{"role": "system", "content": "test"}]

        risks, skill_ctx, _ = await react_agent_loop(
            llm, dispatcher, messages, "4.1", {}, {},
        )

        assert risks == []
        assert skill_ctx == {}


# --- 辅助函数测试 ---

class TestParseResponse:
    def test_valid_json_array(self):
        text = '[{"risk_level": "high", "description": "test"}]'
        result = _parse_final_response(text)
        assert len(result) == 1

    def test_empty_array(self):
        assert _parse_final_response("[]") == []

    def test_empty_string(self):
        assert _parse_final_response("") == []

    def test_invalid_json(self):
        assert _parse_final_response("not json") == []

    def test_filters_non_dict(self):
        text = '[{"a": 1}, "string", 42]'
        result = _parse_final_response(text)
        assert len(result) == 1


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_long_text_truncated(self):
        text = "x" * 5000
        result = _truncate(text, 100)
        assert len(result) < 200
        assert "截断" in result


class TestSerializeToolResult:
    def test_none(self):
        assert _serialize_tool_result(None) == "{}"

    def test_dict(self):
        result = _serialize_tool_result({"key": "value"})
        assert "key" in result

    def test_string(self):
        assert _serialize_tool_result("hello") == "hello"
```

#### 7.1.2 Prompt 构造测试

在 `tests/test_graph_prompts.py` 中新增：

```python
class TestBuildReactAgentMessages:
    def test_basic_structure(self):
        """返回 [system, user] 两条消息。"""
        from contract_review.graph.prompts import build_react_agent_messages

        msgs = build_react_agent_messages(
            language="zh-CN",
            our_party="承包商",
            clause_id="4.1",
            clause_name="承包商义务",
            description="检查义务范围",
            priority="critical",
            clause_text="The Contractor shall...",
        )
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_system_contains_tool_instructions(self):
        """system prompt 包含工具使用指引。"""
        from contract_review.graph.prompts import build_react_agent_messages

        msgs = build_react_agent_messages(
            language="zh-CN",
            our_party="承包商",
            clause_id="4.1",
            clause_name="test",
            description="test",
            priority="medium",
            clause_text="test",
        )
        system = msgs[0]["content"]
        assert "工具" in system
        assert "clause_id" in system

    def test_suggested_skills_included(self):
        """传入 suggested_skills 和 dispatcher 时，prompt 包含建议工具。"""
        from contract_review.graph.prompts import build_react_agent_messages
        from unittest.mock import MagicMock
        from contract_review.skills.schema import SkillRegistration, SkillBackend

        dispatcher = MagicMock()
        dispatcher.get_registration.return_value = SkillRegistration(
            skill_id="compare_with_baseline",
            name="基线对比",
            description="将条款与标准模板对比",
            backend=SkillBackend.LOCAL,
            local_handler="some.module.handler",
        )

        msgs = build_react_agent_messages(
            language="zh-CN",
            our_party="承包商",
            clause_id="4.1",
            clause_name="test",
            description="test",
            priority="medium",
            clause_text="test",
            suggested_skills=["compare_with_baseline"],
            dispatcher=dispatcher,
        )
        system = msgs[0]["content"]
        assert "compare_with_baseline" in system
        assert "建议工具" in system

    def test_fidic_domain_instruction(self):
        """domain_id='fidic' 时，包含 FIDIC 专项指引。"""
        from contract_review.graph.prompts import build_react_agent_messages

        msgs = build_react_agent_messages(
            language="zh-CN",
            our_party="承包商",
            clause_id="4.1",
            clause_name="test",
            description="test",
            priority="medium",
            clause_text="test",
            domain_id="fidic",
        )
        system = msgs[0]["content"]
        assert "FIDIC" in system
        assert "fidic_merge_gc_pc" in system
```

#### 7.1.3 Builder 集成测试

在 `tests/test_review_graph.py` 中新增：

```python
class TestReactBranchFallback:
    """测试 node_clause_analyze 的 ReAct 分支和回退机制。"""

    @pytest.mark.asyncio
    async def test_react_disabled_uses_hardcoded(self, monkeypatch):
        """use_react_agent=False 时，走原有硬编码分支。"""
        from contract_review.graph.builder import node_clause_analyze

        # mock settings.use_react_agent = False
        fake_settings = MagicMock()
        fake_settings.use_react_agent = False
        monkeypatch.setattr("contract_review.graph.builder.get_settings", lambda: fake_settings)

        state = {
            "review_checklist": [{"clause_id": "1.1", "clause_name": "test", "required_skills": []}],
            "current_clause_index": 0,
            "our_party": "承包商",
            "language": "zh-CN",
        }
        result = await node_clause_analyze(state)
        assert result.get("current_clause_id") == "1.1"

    @pytest.mark.asyncio
    async def test_react_failure_falls_back(self, monkeypatch):
        """ReAct 分支抛异常时，自动回退到硬编码分支。"""
        from contract_review.graph.builder import node_clause_analyze

        fake_settings = MagicMock()
        fake_settings.use_react_agent = True
        monkeypatch.setattr("contract_review.graph.builder.get_settings", lambda: fake_settings)

        # mock _run_react_branch 抛异常
        async def failing_react(**kwargs):
            raise RuntimeError("ReAct 模拟失败")

        monkeypatch.setattr("contract_review.graph.builder._run_react_branch", failing_react)

        state = {
            "review_checklist": [{"clause_id": "1.1", "clause_name": "test", "required_skills": []}],
            "current_clause_index": 0,
            "our_party": "承包商",
            "language": "zh-CN",
        }
        # 不应抛异常，应该回退到硬编码分支
        result = await node_clause_analyze(state)
        assert result.get("current_clause_id") == "1.1"
```

---

## 8. 运行命令

### 8.1 单元测试

```bash
# 运行 ReAct Agent 核心测试
PYTHONPATH=backend/src python -m pytest tests/test_react_agent.py -x -q

# 运行 prompt 相关测试
PYTHONPATH=backend/src python -m pytest tests/test_graph_prompts.py -x -q

# 运行 builder 集成测试
PYTHONPATH=backend/src python -m pytest tests/test_review_graph.py -x -q
```

### 8.2 全量回归测试

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

### 8.3 手动验证（需要 LLM API key）

```bash
# 启用 ReAct 模式运行完整审查
USE_REACT_AGENT=true PYTHONPATH=backend/src python -c "
import asyncio
from contract_review.graph.builder import build_review_graph

async def main():
    graph = build_review_graph(domain_id='fidic')
    state = {
        'task_id': 'test',
        'our_party': '承包商',
        'language': 'zh-CN',
        'domain_id': 'fidic',
        'primary_structure': {
            'clauses': [{'clause_id': '4.1', 'text': 'The Contractor shall...', 'children': []}],
            'document_id': 'test',
            'structure_type': 'fidic',
            'definitions': {},
            'cross_references': [],
            'total_clauses': 1,
        },
        'review_checklist': [{
            'clause_id': '4.1',
            'clause_name': '承包商义务',
            'priority': 'critical',
            'required_skills': ['get_clause_context', 'fidic_merge_gc_pc', 'compare_with_baseline'],
            'description': '检查义务范围',
        }],
    }
    result = await graph.ainvoke(state, config={'configurable': {'thread_id': 'test'}})
    print(f'Risks: {len(result.get(\"all_risks\", []))}')
    print(f'Complete: {result.get(\"is_complete\")}')

asyncio.run(main())
"
```

---

## 9. 验收标准

### 9.1 功能验收

1. **ReAct 循环正确运行**
   - `react_agent_loop` 能正确执行 LLM → tool_calls → 执行工具 → 反馈结果 → LLM 的循环
   - LLM 返回文本（无 tool_calls）时，循环正确终止并解析为 risks
   - LLM 在一轮中返回多个 tool_calls 时，所有工具都被执行

2. **工具执行桥接**
   - LLM 只需提供 `skill_id` 和简单参数（如 `clause_id`）
   - `dispatcher.prepare_and_call()` 正确从 state 中补充完整参数
   - 工具执行结果被序列化为 LLM 可读的字符串

3. **Prompt 构造**
   - `build_react_agent_messages` 生成的 system prompt 包含工具使用指引
   - `suggested_skills` 被正确格式化为建议（非命令）
   - domain 指引中的上下文占位符引导 LLM 使用对应工具

4. **配置控制**
   - `use_react_agent=False`（默认）时，行为与改造前完全一致
   - `use_react_agent=True` 时，启用 ReAct Agent 循环
   - `react_max_iterations` 和 `react_temperature` 可通过环境变量配置

### 9.2 向后兼容验收

5. **零回归**
   - 全量测试 `tests/` 通过，无新增失败
   - `use_react_agent=False` 时，`node_clause_analyze` 行为与改造前完全一致
   - 下游 node（`node_clause_generate_diffs`、`node_clause_validate`、`node_save_clause`）无需任何改动

6. **自动回退**
   - ReAct 分支抛异常时，自动回退到硬编码分支，不影响审查流程
   - LLM 调用失败时，循环中断但不崩溃
   - 单个工具执行失败时，错误信息反馈给 LLM，循环继续

### 9.3 质量验收

7. **消息历史完整**
   - `final_messages` 包含完整的 ReAct 对话历史
   - 每个 tool_call 和 tool 结果都有正确的 `tool_call_id` 关联

8. **工具结果截断**
   - 超过 `MAX_TOOL_RESULT_CHARS` 的工具输出被截断
   - 截断信息包含原始长度提示

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM 不调用工具直接输出 | 分析质量下降（缺少工具辅助信息） | `suggested_skills_hint` 引导 LLM 使用工具；可在 prompt 中强化"必须先调用 get_clause_context" |
| LLM 无限循环调用工具 | token 消耗过大，延迟增加 | `max_iterations` 硬限制（默认 5）；达到上限后强制终止 |
| LLM 调用不存在的工具 | `prepare_and_call` 返回错误 | 错误信息反馈给 LLM，LLM 可以自行修正；`parse_tool_calls` 对非法输入 graceful 降级 |
| ReAct 模式下 LLM 调用次数增多 | API 成本增加 | 默认关闭（`use_react_agent=False`）；`temperature=0.1` 减少不确定性；`max_iterations=5` 限制上限 |
| DeepSeek API 的 tool calling 质量不稳定 | 工具选择不准确 | 保留硬编码模式作为 fallback；`suggested_skills` 提供引导；后续可切换到更强的模型 |
| 工具结果过大导致 context 溢出 | LLM 截断或报错 | `MAX_TOOL_RESULT_CHARS=3000` 截断；`_serialize_tool_result` 统一处理 |

---

## 11. 与后续 SPEC 的接口约定

### 11.1 SPEC-21（Orchestrator 编排层）将复用

- `react_agent_loop` → 作为 Orchestrator 中"Worker Agent"的执行引擎
- `build_react_agent_messages` → 作为 Worker Agent 的 prompt 模板基础
- `_serialize_tool_result` / `_truncate` → 工具结果序列化的通用工具

### 11.2 SPEC-21 将扩展

- 在 `react_agent_loop` 之上增加 Orchestrator 层，决定"哪些条款需要深度分析、哪些快速扫描"
- Orchestrator 可以为不同条款配置不同的 `max_iterations` 和工具集
- 可能引入 Plan-and-Execute 模式作为 Orchestrator 的决策机制

### 11.3 接口稳定性承诺

以下接口在 SPEC-20 中定义后，SPEC-21 不应修改其签名：

```python
# react_agent.py
react_agent_loop(
    llm_client, dispatcher, messages, clause_id, primary_structure, state,
    *, max_iterations, temperature,
) -> Tuple[List[dict], Dict[str, Any], List[dict]]

# prompts.py
build_react_agent_messages(
    *, language, our_party, clause_id, clause_name, description, priority,
    clause_text, domain_id, suggested_skills, dispatcher,
) -> list[dict]
```

### 11.4 从 SPEC-19 到 SPEC-20 的依赖链

```
SPEC-19 提供                          SPEC-20 使用
─────────────────────────────────────────────────────
SkillRegistration.to_tool_definition()  → dispatcher.get_tool_definitions()
skills_to_tool_definitions()            → react_agent_loop 获取 tools 数组
parse_tool_calls()                      → react_agent_loop 解析 LLM 返回的 tool_calls
dispatcher.prepare_and_call()           → react_agent_loop 执行工具
SkillRegistration.prepare_input_fn      → prepare_and_call 内部使用
```

这条依赖链是单向的：SPEC-20 依赖 SPEC-19，但不修改 SPEC-19 的任何接口。
