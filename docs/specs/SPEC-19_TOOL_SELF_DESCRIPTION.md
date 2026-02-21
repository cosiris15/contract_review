# SPEC-19: 工具自描述层（Tool Self-Description）

> 优先级：高（架构改造三步走的第一步，后续 SPEC-20/21 的前置基础）
> 前置依赖：无（纯增量改造，不破坏现有流程）
> 预计新建文件：2 个 | 修改文件：4 个
> 范围：框架层改造，影响所有 Skill

---

## 0. 架构演进上下文

### 0.1 为什么需要这次改造

本项目（十行合同 / Paralaw Gen 3.0）的核心架构正在从 **"硬编码工作流"** 向 **"AI 自主编排工作流"** 演进。这是一个分三步走的改造计划：

```
SPEC-19（本文档）        SPEC-20                    SPEC-21
工具自描述层        →    ReAct Agent 节点      →    Orchestrator 编排层
让工具能被 LLM 理解      让 LLM 自主选择工具         让 LLM 自主编排流程
```

**最终目标**：实现类似 Anthropic "Orchestrator-Workers" 模式的架构——由一个 Orchestrator LLM 根据任务性质，自主决定调用哪些工具、按什么顺序执行、是否需要深度分析或快速扫描。工作流不再是写死的 `analyze → diffs → validate` 流水线，而是由 AI 根据每个条款的具体情况动态组织。

**为什么分三步**：
- 一步到位风险太大，已有 16+ 个 Skill 和完整的测试体系需要保护
- 每一步都可以独立验证、独立回滚
- SPEC-19 本身就有独立价值——即使不做后续步骤，它也消除了 `_build_skill_input` 的 240 行硬编码

### 0.2 当前架构的问题

当前 `builder.py` 中存在一个 240 行的 `_build_skill_input` 函数（第 240-484 行），它是一个巨大的 `if/elif` 链：

```python
# 当前：每加一个 Skill 就要手动加一个分支
def _build_skill_input(skill_id, clause_id, primary_structure, state):
    if skill_id == "get_clause_context":
        return ClauseContextInput(clause_id=clause_id, ...)
    if skill_id == "resolve_definition":
        return ResolveDefinitionInput(clause_id=clause_id, ...)
    if skill_id == "compare_with_baseline":
        return CompareWithBaselineInput(clause_id=clause_id, baseline_text=..., ...)
    # ... 16 个分支，每个都手动构造输入
```

这个设计有三个严重问题：

1. **不可扩展**：每新增一个 Skill，必须在 `builder.py` 中手写一个 if 分支，知道如何从 state 中提取该 Skill 需要的参数
2. **知识集中**：所有 Skill 的参数构造逻辑集中在一个文件里，违反了"谁定义谁负责"的原则
3. **无法被 LLM 理解**：LLM 看不到 Skill 的参数定义，无法自主决定调用哪些 Skill、传什么参数

### 0.3 本 SPEC 要解决什么

让每个 Skill **自己描述自己**：
- 自己声明需要哪些参数（JSON Schema）
- 自己知道如何从 state 中提取参数（`prepare_input` 方法）
- 自己能生成 OpenAI Function Calling 格式的 tool 定义（供 LLM 阅读）

改造后：
- `_build_skill_input` 的 240 行 if/elif 被消除
- 新增 Skill 时只需在 Skill 自己的文件里定义好 schema 和 prepare_input，无需改 builder.py
- `SkillDispatcher` 能一键导出所有 Skill 的 tool 定义，供 SPEC-20 的 ReAct Agent 使用

---

## 1. 设计方案

### 1.1 核心概念：`prepare_input` 方法

每个 Skill 新增一个可选的 `prepare_input` 静态方法，负责从 state 中提取自己需要的参数：

```python
# 示例：compare_with_baseline.py
class CompareWithBaselineInput(BaseModel):
    clause_id: str
    document_structure: Any
    baseline_text: str = ""
    state_snapshot: dict = Field(default_factory=dict)

def prepare_input(clause_id: str, primary_structure: Any, state: dict) -> CompareWithBaselineInput:
    """从 state 中提取本 Skill 需要的参数。"""
    from ...plugins.registry import get_baseline_text
    baseline_text = get_baseline_text(state.get("domain_id", ""), clause_id) or ""
    return CompareWithBaselineInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        baseline_text=baseline_text,
        state_snapshot={
            "our_party": state.get("our_party", ""),
            "language": state.get("language", "en"),
            "domain_id": state.get("domain_id", ""),
        },
    )
```

### 1.2 核心概念：`to_tool_definition` 方法

`SkillRegistration` 新增一个方法，将 Skill 的元信息转为 OpenAI Function Calling 格式：

```python
# SkillRegistration.to_tool_definition() 输出示例
{
    "type": "function",
    "function": {
        "name": "compare_with_baseline",
        "description": "将条款文本与标准模板进行对比，识别差异和偏离",
        "parameters": {
            "type": "object",
            "properties": {
                "clause_id": {"type": "string", "description": "条款编号"},
                "baseline_text": {"type": "string", "description": "基线文本"}
            },
            "required": ["clause_id"]
        }
    }
}
```

### 1.3 向后兼容策略

**关键原则：现有流程完全不变，新能力是增量添加。**

- `prepare_input` 是可选的。没有 `prepare_input` 的 Skill 仍然走 `_build_skill_input` 的 fallback 分支
- `to_tool_definition` 是新增方法，不影响现有调用
- `_build_skill_input` 改为：先尝试调用 Skill 自带的 `prepare_input`，如果没有再走原来的 if/elif
- 可以逐个 Skill 迁移，不需要一次性全改

---

## 2. 文件清单

### 新增文件（2 个）

| 文件路径 | 用途 |
|---------|------|
| `backend/src/contract_review/skills/tool_adapter.py` | Skill → OpenAI Tool 定义的转换器 |
| `tests/test_tool_adapter.py` | 单元测试 |

### 修改文件（4 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/skills/schema.py` | `SkillRegistration` 新增 `prepare_input_fn`、`to_tool_definition()` |
| `backend/src/contract_review/skills/dispatcher.py` | `SkillDispatcher` 新增 `get_tool_definitions()`、`prepare_and_call()` |
| `backend/src/contract_review/graph/builder.py` | `_build_skill_input` 改为优先使用 `prepare_input`；为已有 Skill 迁移 `prepare_input` |
| 各 Skill 文件（逐步迁移） | 新增 `prepare_input` 函数 |

### 不需要修改的文件

- `llm_client.py` — 无需改动
- `prompts.py` — 无需改动
- `api_gen3.py` — 无需改动
- `state.py` — 无需改动

---

## 3. schema.py 改动

### 3.1 `SkillRegistration` 扩展

```python
class SkillRegistration(BaseModel):
    """Skill registration payload."""

    skill_id: str
    name: str
    description: str = ""
    input_schema: Optional[Type[BaseModel]] = None
    output_schema: Optional[Type[BaseModel]] = None
    backend: SkillBackend
    refly_workflow_id: Optional[str] = None
    local_handler: Optional[str] = None
    domain: str = "*"
    category: str = "general"
    status: str = "active"

    # --- 新增字段 ---
    prepare_input_fn: Optional[str] = None
    # 格式同 local_handler：模块路径.函数名
    # 例如 "contract_review.skills.local.compare_with_baseline.prepare_input"
    # 如果为 None，则走 builder.py 中的 _build_skill_input fallback

    class Config:
        arbitrary_types_allowed = True

    def to_tool_definition(self) -> dict:
        """将 Skill 转为 OpenAI Function Calling 格式的 tool 定义。

        返回格式：
        {
            "type": "function",
            "function": {
                "name": "skill_id",
                "description": "...",
                "parameters": { JSON Schema }
            }
        }
        """
        parameters = {"type": "object", "properties": {}, "required": []}

        if self.input_schema is not None:
            try:
                schema = self.input_schema.model_json_schema()
                parameters = {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                }
                # 移除 LLM 不需要关心的内部字段
                for field_name in ("document_structure", "state_snapshot"):
                    parameters["properties"].pop(field_name, None)
                    if field_name in parameters["required"]:
                        parameters["required"].remove(field_name)
            except Exception:
                pass

        return {
            "type": "function",
            "function": {
                "name": self.skill_id,
                "description": self.description,
                "parameters": parameters,
            },
        }
```

### 3.2 关于 `to_tool_definition` 的设计说明

- `document_structure` 和 `state_snapshot` 从 parameters 中移除，因为这些是系统自动注入的，LLM 不需要也不应该填写
- `clause_id` 保留，因为 LLM 需要指定要分析哪个条款
- 其他业务参数（如 `baseline_text`、`query`、`top_k`）保留，LLM 可以选择性填写
- 如果 `input_schema` 为 None，返回空 parameters（仅 clause_id 作为必填）

---

## 4. tool_adapter.py（新增）

### 4.1 职责

提供两个核心能力：
1. 将 `SkillRegistration` 列表批量转为 OpenAI tool 定义列表
2. 将 LLM 返回的 `tool_calls` 解析为可执行的 Skill 调用

这个文件是 SPEC-20 ReAct Agent 的前置基础，但在 SPEC-19 中就要实现并测试。

### 4.2 函数设计

```python
"""Adapter: convert registered Skills to OpenAI Function Calling tool definitions."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .dispatcher import SkillDispatcher
from .schema import SkillRegistration, SkillResult

logger = logging.getLogger(__name__)

# LLM 不需要感知的内部字段，在生成 tool definition 时自动剔除
INTERNAL_FIELDS = frozenset({
    "document_structure",
    "state_snapshot",
    "criteria_data",
    "criteria_file_path",
})


def skills_to_tool_definitions(
    skills: List[SkillRegistration],
    *,
    domain_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    exclude_internal_fields: frozenset[str] = INTERNAL_FIELDS,
) -> List[dict]:
    """将 Skill 列表转为 OpenAI Function Calling 格式的 tools 数组。

    Args:
        skills: 已注册的 Skill 列表
        domain_filter: 可选，只包含指定 domain 的 Skill（"*" 表示通用）
        category_filter: 可选，只包含指定 category 的 Skill
        exclude_internal_fields: 从 parameters 中剔除的内部字段名集合

    Returns:
        OpenAI tools 数组，可直接传给 LLMClient.chat_with_tools()
    """
    tools: List[dict] = []
    for skill in skills:
        if skill.status != "active":
            continue
        if domain_filter and skill.domain not in ("*", domain_filter):
            continue
        if category_filter and skill.category != category_filter:
            continue

        tool_def = skill.to_tool_definition()

        # 额外清理内部字段
        params = tool_def.get("function", {}).get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])
        for field_name in exclude_internal_fields:
            props.pop(field_name, None)
            if field_name in required:
                required.remove(field_name)

        tools.append(tool_def)
    return tools


def parse_tool_calls(
    tool_calls: List[dict],
) -> List[Dict[str, Any]]:
    """将 LLM 返回的 tool_calls 解析为结构化的调用请求。

    Args:
        tool_calls: LLM 返回的 tool_calls 列表，格式为 OpenAI 标准格式

    Returns:
        解析后的调用请求列表：
        [{"id": "call_xxx", "skill_id": "compare_with_baseline", "arguments": {...}}, ...]
    """
    parsed: List[Dict[str, Any]] = []
    for tc in tool_calls:
        func = tc.get("function", {})
        skill_id = func.get("name", "")
        raw_args = func.get("arguments", "{}")

        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except (json.JSONDecodeError, TypeError):
            logger.warning("tool_call 参数解析失败: skill=%s, raw=%s", skill_id, raw_args)
            arguments = {}

        parsed.append({
            "id": tc.get("id", ""),
            "skill_id": skill_id,
            "arguments": arguments,
        })
    return parsed
```

### 4.3 设计说明

- `skills_to_tool_definitions` 支持按 domain 和 category 过滤，这样 SPEC-20 中可以只给 LLM 展示当前场景相关的工具
- `parse_tool_calls` 负责将 LLM 的 JSON 字符串参数解析为 Python dict，处理解析失败的情况
- `INTERNAL_FIELDS` 集中定义了所有不应暴露给 LLM 的字段名，避免在多处重复

---

## 5. dispatcher.py 改动

### 5.1 新增方法：`get_tool_definitions`

```python
def get_tool_definitions(
    self,
    *,
    domain_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
) -> List[dict]:
    """获取所有已注册 Skill 的 OpenAI tool 定义。

    供 ReAct Agent 使用，将 Skill 作为 tools 传给 LLM。
    """
    from .tool_adapter import skills_to_tool_definitions

    return skills_to_tool_definitions(
        self.list_skills(),
        domain_filter=domain_filter,
        category_filter=category_filter,
    )
```

### 5.2 新增方法：`prepare_and_call`

```python
async def prepare_and_call(
    self,
    skill_id: str,
    clause_id: str,
    primary_structure: Any,
    state: dict,
    *,
    llm_arguments: Optional[dict] = None,
) -> SkillResult:
    """智能调用 Skill：优先使用 prepare_input，支持 LLM 提供的参数覆盖。

    调用优先级：
    1. 如果 Skill 注册了 prepare_input_fn → 调用它从 state 中构造输入
    2. 否则 → 使用 llm_arguments 构造 GenericSkillInput
    3. 如果 llm_arguments 中有额外参数 → 合并到 prepare_input 的结果中

    Args:
        skill_id: Skill ID
        clause_id: 当前条款 ID
        primary_structure: 主文档结构
        state: 完整的 ReviewGraphState（dict 形式）
        llm_arguments: LLM 通过 tool_call 提供的参数（可选）

    Returns:
        SkillResult
    """
    registration = self.get_registration(skill_id)
    if not registration:
        return SkillResult(skill_id=skill_id, success=False, error=f"Skill '{skill_id}' 未注册")

    input_data = None

    # 优先使用 prepare_input_fn
    if registration.prepare_input_fn:
        try:
            from .dispatcher import _import_handler
            prepare_fn = _import_handler(registration.prepare_input_fn)
            input_data = prepare_fn(clause_id, primary_structure, state)
        except Exception as exc:
            logger.warning("prepare_input 调用失败 (skill=%s): %s", skill_id, exc)

    # 如果 prepare_input 失败或不存在，用 GenericSkillInput
    if input_data is None:
        from .schema import GenericSkillInput
        input_data = GenericSkillInput(
            clause_id=clause_id,
            document_structure=primary_structure,
            state_snapshot=llm_arguments or {},
        )

    return await self.call(skill_id, input_data)
```

### 5.3 设计说明

- `prepare_and_call` 是 `_build_skill_input` + `dispatcher.call` 的合并替代品
- 它不替代现有的 `call` 方法——`call` 仍然是底层执行接口，`prepare_and_call` 是上层便捷接口
- `llm_arguments` 参数为 SPEC-20 预留：当 LLM 通过 tool_call 指定了参数时，可以传入这里

---

## 6. builder.py 改动

### 6.1 `_build_skill_input` 改造

将现有的 `_build_skill_input` 改为优先使用 `prepare_input`：

```python
def _build_skill_input(
    skill_id: str,
    clause_id: str,
    primary_structure: Any,
    state: ReviewGraphState,
    dispatcher: SkillDispatcher | None = None,
) -> BaseModel | None:
    """Build per-skill input payload.

    优先级：
    1. 如果 Skill 注册了 prepare_input_fn → 动态导入并调用
    2. 否则 → 走原有的 if/elif fallback（向后兼容）
    """
    # --- 新增：尝试 prepare_input ---
    if dispatcher:
        registration = dispatcher.get_registration(skill_id)
        if registration and registration.prepare_input_fn:
            try:
                prepare_fn = _import_handler(registration.prepare_input_fn)
                return prepare_fn(clause_id, primary_structure, dict(state))
            except Exception as exc:
                logger.warning(
                    "prepare_input 调用失败 (skill=%s)，回退到硬编码分支: %s",
                    skill_id, exc,
                )

    # --- 原有 if/elif 分支保持不变（作为 fallback）---
    if skill_id == "get_clause_context":
        # ... 原有代码不变
```

**关键点**：
- `dispatcher` 参数是新增的，但有默认值 `None`，不影响现有调用
- 如果 `prepare_input` 调用失败，自动回退到原有的 if/elif 分支
- 原有的所有 if/elif 分支保持不变，确保零回归风险

### 6.2 `node_clause_analyze` 中传入 dispatcher

当前 `_build_skill_input` 的调用处（第 548 行）需要传入 dispatcher：

```python
# 改前
skill_input = _build_skill_input(skill_id, clause_id, primary_structure, state)

# 改后
skill_input = _build_skill_input(skill_id, clause_id, primary_structure, state, dispatcher)
```

### 6.3 Skill 注册时添加 `prepare_input_fn`

本 SPEC 要求为所有 16 个已有 Skill 添加 `prepare_input` 函数并注册。以下是完整的迁移清单：

#### 通用 Skills（8 个）

| skill_id | prepare_input_fn | 复杂度 |
|----------|-----------------|--------|
| `get_clause_context` | `contract_review.skills.local.clause_context.prepare_input` | 低 |
| `resolve_definition` | `contract_review.skills.local.resolve_definition.prepare_input` | 低 |
| `compare_with_baseline` | `contract_review.skills.local.compare_with_baseline.prepare_input` | 中 |
| `cross_reference_check` | `contract_review.skills.local.cross_reference_check.prepare_input` | 低 |
| `extract_financial_terms` | `contract_review.skills.local.extract_financial_terms.prepare_input` | 低 |
| `search_reference_doc` | `contract_review.skills.local.semantic_search.prepare_input` | 中 |
| `load_review_criteria` | `contract_review.skills.local.load_review_criteria.prepare_input` | 低 |
| `assess_deviation` | `contract_review.skills.local.assess_deviation.prepare_input` | 中 |

#### FIDIC Skills（4 个）

| skill_id | prepare_input_fn | 复杂度 |
|----------|-----------------|--------|
| `fidic_merge_gc_pc` | `contract_review.skills.fidic.merge_gc_pc.prepare_input` | 中 |
| `fidic_calculate_time_bar` | `contract_review.skills.fidic.time_bar.prepare_input` | 低 |
| `fidic_check_pc_consistency` | `contract_review.skills.fidic.check_pc_consistency.prepare_input` | 高 |
| `fidic_search_er` | `contract_review.skills.fidic.search_er.prepare_input` | 中 |

#### SHA/SPA Skills（4 个）

| skill_id | prepare_input_fn | 复杂度 |
|----------|-----------------|--------|
| `spa_extract_conditions` | `contract_review.skills.sha_spa.extract_conditions.prepare_input` | 低 |
| `spa_extract_reps_warranties` | `contract_review.skills.sha_spa.extract_reps_warranties.prepare_input` | 低 |
| `spa_indemnity_analysis` | `contract_review.skills.sha_spa.indemnity_analysis.prepare_input` | 低 |
| `sha_governance_check` | `contract_review.skills.sha_spa.governance_check.prepare_input` | 低 |

### 6.4 `prepare_input` 函数的统一签名

所有 `prepare_input` 函数必须遵循统一签名：

```python
def prepare_input(
    clause_id: str,
    primary_structure: Any,
    state: dict,
) -> BaseModel:
    """从 state 中提取本 Skill 需要的参数。

    Args:
        clause_id: 当前审查的条款 ID
        primary_structure: 主文档结构（已解析的 DocumentStructure）
        state: 完整的 ReviewGraphState（dict 形式）

    Returns:
        该 Skill 的 Input BaseModel 实例
    """
```

### 6.5 迁移示例：从 if/elif 到 prepare_input

以 `fidic_search_er` 为例，展示迁移过程：

**迁移前**（builder.py 第 338-361 行）：
```python
if skill_id == "fidic_search_er":
    from ..skills.fidic.search_er import SearchErInput
    clause_text = _extract_clause_text(primary_structure, clause_id)
    query = " ".join(
        part for part in [clause_text[:500], state.get("material_type", ""), state.get("domain_subtype", "")]
        if part
    )
    er_structure = None
    for doc in state.get("documents", []):
        doc_dict = _as_dict(doc)
        role = str(doc_dict.get("role", "") or "").lower()
        filename = str(doc_dict.get("filename", "") or "")
        if role == "reference" and "er" in filename.lower():
            er_structure = doc_dict.get("structure")
            break
    return SearchErInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        er_structure=er_structure,
        query=query or clause_id,
        top_k=5,
    )
```

**迁移后**（search_er.py 中新增）：
```python
def prepare_input(clause_id: str, primary_structure: Any, state: dict) -> SearchErInput:
    """从 state 中提取 ER 检索所需的参数。"""
    from ..local._utils import get_clause_text

    clause_text = get_clause_text(primary_structure, clause_id) or ""
    query = " ".join(
        part for part in [clause_text[:500], state.get("material_type", ""), state.get("domain_subtype", "")]
        if part
    )

    er_structure = None
    for doc in state.get("documents", []):
        doc_dict = doc if isinstance(doc, dict) else (doc.model_dump() if hasattr(doc, "model_dump") else {})
        role = str(doc_dict.get("role", "") or "").lower()
        filename = str(doc_dict.get("filename", "") or "")
        if role == "reference" and "er" in filename.lower():
            er_structure = doc_dict.get("structure")
            break

    return SearchErInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        er_structure=er_structure,
        query=query or clause_id,
        top_k=5,
    )
```

builder.py 中对应的 if 分支在所有 Skill 迁移完成后可以删除，但本 SPEC 阶段保留作为 fallback。

---

## 7. 测试要求

### 7.1 测试文件：`tests/test_tool_adapter.py`

本 SPEC 的测试覆盖三个层面：
1. `to_tool_definition()` 方法（schema.py 改动）
2. `tool_adapter.py` 的两个核心函数
3. `prepare_input` 机制与 `_build_skill_input` 的 fallback 行为

#### 7.1.1 `to_tool_definition` 测试

```python
import pytest
from pydantic import BaseModel, Field
from typing import Any

from contract_review.skills.schema import SkillRegistration, SkillBackend


class DummyInput(BaseModel):
    """测试用 Input Schema。"""
    clause_id: str
    query: str = ""
    top_k: int = 5
    document_structure: Any = None      # 内部字段，应被剔除
    state_snapshot: dict = Field(default_factory=dict)  # 内部字段，应被剔除


class TestToToolDefinition:
    def test_basic_structure(self):
        """to_tool_definition 返回 OpenAI Function Calling 标准格式。"""
        reg = SkillRegistration(
            skill_id="test_skill",
            name="测试技能",
            description="这是一个测试技能",
            backend=SkillBackend.LOCAL,
            local_handler="some.module.handler",
            input_schema=DummyInput,
        )
        tool_def = reg.to_tool_definition()

        assert tool_def["type"] == "function"
        assert tool_def["function"]["name"] == "test_skill"
        assert tool_def["function"]["description"] == "这是一个测试技能"
        assert "parameters" in tool_def["function"]
        assert tool_def["function"]["parameters"]["type"] == "object"

    def test_internal_fields_excluded(self):
        """document_structure 和 state_snapshot 不出现在 parameters 中。"""
        reg = SkillRegistration(
            skill_id="test_skill",
            name="测试",
            backend=SkillBackend.LOCAL,
            local_handler="some.module.handler",
            input_schema=DummyInput,
        )
        tool_def = reg.to_tool_definition()
        props = tool_def["function"]["parameters"]["properties"]

        assert "clause_id" in props
        assert "query" in props
        assert "top_k" in props
        assert "document_structure" not in props
        assert "state_snapshot" not in props

    def test_required_fields_correct(self):
        """required 列表只包含必填的业务字段，不包含内部字段。"""
        reg = SkillRegistration(
            skill_id="test_skill",
            name="测试",
            backend=SkillBackend.LOCAL,
            local_handler="some.module.handler",
            input_schema=DummyInput,
        )
        tool_def = reg.to_tool_definition()
        required = tool_def["function"]["parameters"]["required"]

        assert "clause_id" in required
        assert "document_structure" not in required
        assert "state_snapshot" not in required

    def test_no_input_schema(self):
        """input_schema 为 None 时，返回空 parameters。"""
        reg = SkillRegistration(
            skill_id="test_skill",
            name="测试",
            backend=SkillBackend.LOCAL,
            local_handler="some.module.handler",
            input_schema=None,
        )
        tool_def = reg.to_tool_definition()
        params = tool_def["function"]["parameters"]

        assert params["properties"] == {}
        assert params["required"] == []
```

#### 7.1.2 `skills_to_tool_definitions` 测试

```python
from contract_review.skills.tool_adapter import (
    skills_to_tool_definitions,
    parse_tool_calls,
    INTERNAL_FIELDS,
)


class TestSkillsToToolDefinitions:
    def _make_skill(self, skill_id, domain="*", category="general", status="active"):
        return SkillRegistration(
            skill_id=skill_id,
            name=skill_id,
            description=f"Skill {skill_id}",
            backend=SkillBackend.LOCAL,
            local_handler="some.module.handler",
            input_schema=DummyInput,
            domain=domain,
            category=category,
            status=status,
        )

    def test_basic_conversion(self):
        """多个 Skill 批量转为 tool definitions。"""
        skills = [self._make_skill("a"), self._make_skill("b")]
        tools = skills_to_tool_definitions(skills)

        assert len(tools) == 2
        assert tools[0]["function"]["name"] == "a"
        assert tools[1]["function"]["name"] == "b"

    def test_inactive_skill_excluded(self):
        """status != 'active' 的 Skill 被过滤。"""
        skills = [
            self._make_skill("active_one"),
            self._make_skill("disabled_one", status="disabled"),
        ]
        tools = skills_to_tool_definitions(skills)

        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "active_one"

    def test_domain_filter(self):
        """domain_filter 只保留匹配 domain 和通用 domain='*' 的 Skill。"""
        skills = [
            self._make_skill("generic", domain="*"),
            self._make_skill("fidic_only", domain="fidic"),
            self._make_skill("sha_only", domain="sha_spa"),
        ]
        tools = skills_to_tool_definitions(skills, domain_filter="fidic")

        names = [t["function"]["name"] for t in tools]
        assert "generic" in names       # domain="*" 通过
        assert "fidic_only" in names    # domain="fidic" 通过
        assert "sha_only" not in names  # domain="sha_spa" 被过滤

    def test_category_filter(self):
        """category_filter 只保留匹配 category 的 Skill。"""
        skills = [
            self._make_skill("a", category="analysis"),
            self._make_skill("b", category="validation"),
        ]
        tools = skills_to_tool_definitions(skills, category_filter="validation")

        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "b"

    def test_internal_fields_stripped(self):
        """INTERNAL_FIELDS 中的字段在最终输出中被剔除。"""
        skills = [self._make_skill("a")]
        tools = skills_to_tool_definitions(skills)

        props = tools[0]["function"]["parameters"]["properties"]
        for field_name in INTERNAL_FIELDS:
            assert field_name not in props

    def test_empty_input(self):
        """空 Skill 列表返回空 tools 列表。"""
        assert skills_to_tool_definitions([]) == []
```

#### 7.1.3 `parse_tool_calls` 测试

```python
class TestParseToolCalls:
    def test_basic_parsing(self):
        """标准 OpenAI tool_calls 格式解析。"""
        tool_calls = [
            {
                "id": "call_001",
                "function": {
                    "name": "compare_with_baseline",
                    "arguments": '{"clause_id": "4.1", "baseline_text": "原文"}',
                },
            }
        ]
        parsed = parse_tool_calls(tool_calls)

        assert len(parsed) == 1
        assert parsed[0]["id"] == "call_001"
        assert parsed[0]["skill_id"] == "compare_with_baseline"
        assert parsed[0]["arguments"]["clause_id"] == "4.1"

    def test_multiple_tool_calls(self):
        """多个 tool_calls 同时解析。"""
        tool_calls = [
            {"id": "call_001", "function": {"name": "skill_a", "arguments": "{}"}},
            {"id": "call_002", "function": {"name": "skill_b", "arguments": '{"x": 1}'}},
        ]
        parsed = parse_tool_calls(tool_calls)

        assert len(parsed) == 2
        assert parsed[0]["skill_id"] == "skill_a"
        assert parsed[1]["arguments"]["x"] == 1

    def test_invalid_json_arguments(self):
        """arguments 不是合法 JSON 时，降级为空 dict。"""
        tool_calls = [
            {"id": "call_001", "function": {"name": "skill_a", "arguments": "not json"}},
        ]
        parsed = parse_tool_calls(tool_calls)

        assert parsed[0]["arguments"] == {}

    def test_dict_arguments(self):
        """arguments 已经是 dict（非字符串）时，直接使用。"""
        tool_calls = [
            {"id": "call_001", "function": {"name": "skill_a", "arguments": {"key": "val"}}},
        ]
        parsed = parse_tool_calls(tool_calls)

        assert parsed[0]["arguments"]["key"] == "val"

    def test_empty_tool_calls(self):
        """空列表返回空结果。"""
        assert parse_tool_calls([]) == []

    def test_missing_fields_graceful(self):
        """缺少 id 或 function 字段时不崩溃。"""
        tool_calls = [{"function": {"name": "skill_a", "arguments": "{}"}}]
        parsed = parse_tool_calls(tool_calls)

        assert parsed[0]["id"] == ""
        assert parsed[0]["skill_id"] == "skill_a"
```

### 7.2 `prepare_input` 机制测试

在现有的 `tests/test_skill_dispatch.py` 中新增测试类：

```python
class TestPrepareInputFallback:
    """测试 _build_skill_input 的 prepare_input 优先 + fallback 机制。"""

    def test_prepare_input_fn_takes_priority(self):
        """当 Skill 注册了 prepare_input_fn 时，优先使用它。"""
        # 1. 创建一个带 prepare_input_fn 的 dispatcher
        dispatcher = _create_dispatcher()
        reg = dispatcher.get_registration("get_clause_context")

        # 如果 reg 有 prepare_input_fn，验证 _build_skill_input 使用它
        # 如果没有，验证走 fallback
        result = _build_skill_input(
            "get_clause_context",
            "4.1",
            {"clauses": [{"clause_id": "4.1", "text": "test", "children": []}]},
            {"our_party": "承包商", "language": "zh-CN"},
            dispatcher=dispatcher,
        )
        assert result is not None
        assert result.clause_id == "4.1"

    def test_fallback_when_no_prepare_input(self):
        """没有 prepare_input_fn 时，走原有 if/elif 分支。"""
        # 不传 dispatcher，强制走 fallback
        result = _build_skill_input(
            "get_clause_context",
            "4.1",
            {"clauses": [{"clause_id": "4.1", "text": "test", "children": []}]},
            {"our_party": "承包商", "language": "zh-CN"},
        )
        assert result is not None
        assert result.clause_id == "4.1"

    def test_fallback_when_prepare_input_fails(self, monkeypatch):
        """prepare_input_fn 调用失败时，回退到 if/elif 分支。"""
        dispatcher = _create_dispatcher()
        reg = dispatcher.get_registration("get_clause_context")

        # 如果有 prepare_input_fn，mock 它抛异常
        if reg and reg.prepare_input_fn:
            import contract_review.skills.dispatcher as disp_mod
            original_import = disp_mod._import_handler

            def failing_import(path):
                if "prepare_input" in path:
                    raise ImportError("模拟导入失败")
                return original_import(path)

            monkeypatch.setattr(disp_mod, "_import_handler", failing_import)

        result = _build_skill_input(
            "get_clause_context",
            "4.1",
            {"clauses": [{"clause_id": "4.1", "text": "test", "children": []}]},
            {"our_party": "承包商", "language": "zh-CN"},
            dispatcher=dispatcher,
        )
        # 即使 prepare_input 失败，fallback 仍然能构造输入
        assert result is not None
```

### 7.3 `dispatcher.get_tool_definitions` 集成测试

```python
class TestDispatcherToolDefinitions:
    """测试 SkillDispatcher.get_tool_definitions() 集成。"""

    def test_get_all_tool_definitions(self):
        """获取所有已注册 Skill 的 tool 定义。"""
        dispatcher = _create_dispatcher()
        tools = dispatcher.get_tool_definitions()

        assert isinstance(tools, list)
        assert len(tools) > 0

        # 每个 tool 都有标准结构
        for tool in tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

    def test_tool_definitions_with_domain_filter(self):
        """domain_filter 正确过滤。"""
        from contract_review.plugins.fidic import register_fidic_plugin
        from contract_review.plugins.registry import clear_plugins

        clear_plugins()
        register_fidic_plugin()
        dispatcher = _create_dispatcher(domain_id="fidic")

        # 只获取 fidic 相关的 tools
        tools = dispatcher.get_tool_definitions(domain_filter="fidic")
        names = [t["function"]["name"] for t in tools]

        # 通用 Skill（domain="*"）应该包含
        assert "get_clause_context" in names

    def test_tool_definitions_names_match_skill_ids(self):
        """tool definition 的 name 与 skill_id 一一对应。"""
        dispatcher = _create_dispatcher()
        tools = dispatcher.get_tool_definitions()
        tool_names = {t["function"]["name"] for t in tools}

        for skill_id in dispatcher.skill_ids:
            reg = dispatcher.get_registration(skill_id)
            if reg and reg.status == "active":
                assert skill_id in tool_names, f"Skill '{skill_id}' 未出现在 tool definitions 中"

    def test_tool_definitions_passable_to_llm_client(self):
        """生成的 tools 数组格式可直接传给 LLMClient.chat_with_tools()。"""
        dispatcher = _create_dispatcher()
        tools = dispatcher.get_tool_definitions()

        # 验证格式兼容性：每个 tool 的 parameters 都是合法的 JSON Schema
        for tool in tools:
            params = tool["function"]["parameters"]
            assert params["type"] == "object"
            assert isinstance(params.get("properties", {}), dict)
            assert isinstance(params.get("required", []), list)
```

---

## 8. 运行命令

### 8.1 单元测试

```bash
# 运行 SPEC-19 新增的测试
PYTHONPATH=backend/src python -m pytest tests/test_tool_adapter.py -x -q

# 运行 dispatcher 相关测试（含新增的 prepare_input 测试）
PYTHONPATH=backend/src python -m pytest tests/test_skill_dispatch.py -x -q
```

### 8.2 全量回归测试

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

### 8.3 快速验证命令

```bash
# 验证 to_tool_definition 输出格式
PYTHONPATH=backend/src python -c "
from contract_review.graph.builder import _create_dispatcher
d = _create_dispatcher()
tools = d.get_tool_definitions()
print(f'共 {len(tools)} 个 tool definitions')
for t in tools:
    print(f'  - {t[\"function\"][\"name\"]}: {t[\"function\"][\"description\"][:40]}...')
"
```

---

## 9. 验收标准

### 9.1 功能验收

1. **`SkillRegistration` 扩展**
   - 新增 `prepare_input_fn: Optional[str]` 字段，默认 `None`
   - 新增 `to_tool_definition()` 方法，返回 OpenAI Function Calling 标准格式
   - `to_tool_definition()` 自动剔除 `document_structure`、`state_snapshot` 等内部字段
   - `input_schema=None` 时返回空 parameters

2. **`tool_adapter.py` 新增文件**
   - `skills_to_tool_definitions()` 支持 `domain_filter` 和 `category_filter`
   - `skills_to_tool_definitions()` 自动过滤 `status != "active"` 的 Skill
   - `parse_tool_calls()` 正确解析 OpenAI 标准格式的 tool_calls
   - `parse_tool_calls()` 对非法 JSON 参数 graceful 降级

3. **`SkillDispatcher` 扩展**
   - 新增 `get_tool_definitions()` 方法，一键导出所有 Skill 的 tool 定义
   - 新增 `prepare_and_call()` 方法，优先使用 `prepare_input_fn`
   - `prepare_and_call()` 在 `prepare_input_fn` 失败时回退到 `GenericSkillInput`

4. **`_build_skill_input` 改造**
   - 新增可选参数 `dispatcher`，默认 `None`
   - 当 `dispatcher` 提供且 Skill 有 `prepare_input_fn` 时，优先调用 `prepare_input`
   - `prepare_input` 调用失败时，自动回退到原有 if/elif 分支
   - 原有所有 if/elif 分支保持不变（零回归风险）

### 9.2 向后兼容验收

5. **零回归**
   - 全量测试 `tests/` 通过，无新增失败
   - 现有 `test_skill_dispatch.py` 中的所有测试不受影响
   - 不传 `dispatcher` 参数时，`_build_skill_input` 行为与改造前完全一致

6. **增量迁移**
   - 没有 `prepare_input_fn` 的 Skill 仍然正常工作
   - 可以逐个 Skill 添加 `prepare_input`，不需要一次性全改
   - 已迁移和未迁移的 Skill 可以共存

### 9.3 SPEC-20 前置验收

7. **tool 定义可用性**
   - `dispatcher.get_tool_definitions()` 输出的格式可直接传给 `LLMClient.chat_with_tools()`
   - 每个 tool definition 的 `name` 与 `skill_id` 一致
   - `description` 非空，能让 LLM 理解该工具的用途
   - `parameters` 只包含 LLM 需要填写的业务参数

8. **`parse_tool_calls` 可用性**
   - 能正确解析 `LLMClient.chat_with_tools()` 返回的 `tool_calls` 格式
   - 解析结果中的 `skill_id` 可直接用于 `dispatcher.call()` 或 `dispatcher.prepare_and_call()`

### 9.4 迁移进度验收

9. **Skill 迁移**
   - 所有 16 个已有 Skill 均添加了 `prepare_input` 函数
   - 所有 `prepare_input` 函数遵循统一签名：`(clause_id, primary_structure, state) -> BaseModel`
   - 所有 Skill 注册时设置了 `prepare_input_fn` 字段
   - 迁移后的 `prepare_input` 逻辑与原 `_build_skill_input` 中的对应分支等价

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| `prepare_input` 逻辑与原 if/elif 不一致 | 某些 Skill 输入构造错误 | 保留 if/elif 作为 fallback；逐个 Skill 迁移并对比测试 |
| `to_tool_definition` 生成的 schema 不被 LLM 理解 | SPEC-20 中 LLM 无法正确调用工具 | 在 SPEC-19 阶段就用快速验证命令检查输出格式 |
| `model_json_schema()` 对复杂类型（如 `Any`）生成不理想的 schema | tool definition 中出现无意义的参数 | `INTERNAL_FIELDS` 集中管理需要剔除的字段 |
| 16 个 Skill 同时迁移工作量大 | 开发周期拉长 | 可分批迁移：先迁移 8 个通用 Skill，再迁移 domain Skill |

---

## 11. 与后续 SPEC 的接口约定

### 11.1 SPEC-20（ReAct Agent 节点）将使用

- `dispatcher.get_tool_definitions()` → 获取 tools 数组传给 LLM
- `parse_tool_calls()` → 解析 LLM 返回的 tool_calls
- `dispatcher.prepare_and_call()` → 执行 LLM 选择的工具

### 11.2 SPEC-21（Orchestrator 编排层）将使用

- `dispatcher.get_tool_definitions(category_filter=...)` → 按类别获取不同阶段的工具集
- `SkillRegistration.to_tool_definition()` → 单个 Skill 的 tool 定义（用于动态组合）

### 11.3 接口稳定性承诺

以下接口在 SPEC-19 中定义后，SPEC-20/21 不应修改其签名：

```python
# schema.py
SkillRegistration.to_tool_definition() -> dict
SkillRegistration.prepare_input_fn: Optional[str]

# tool_adapter.py
skills_to_tool_definitions(skills, *, domain_filter, category_filter, exclude_internal_fields) -> List[dict]
parse_tool_calls(tool_calls) -> List[Dict[str, Any]]

# dispatcher.py
SkillDispatcher.get_tool_definitions(*, domain_filter, category_filter) -> List[dict]
SkillDispatcher.prepare_and_call(skill_id, clause_id, primary_structure, state, *, llm_arguments) -> SkillResult
```
