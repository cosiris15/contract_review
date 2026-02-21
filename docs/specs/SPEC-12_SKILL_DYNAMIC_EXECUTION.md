# SPEC-12: Skills 动态执行机制

## 1. 概述

当前 `node_clause_analyze` 中只硬编码调用了 `get_clause_context` 一个 Skill。但 FIDIC checklist 中每个条款已声明了 `required_skills` 列表（如 `["get_clause_context", "resolve_definition", "compare_with_baseline"]`），这些声明完全没有被使用。

同时，Plugin 注册时声明的 `domain_skills` 也没有被自动注册到 SkillDispatcher，导致即使实现了新 Skill，图引擎也无法调用。

本 SPEC 的目标：
1. 让 `_create_dispatcher` 自动注册 Plugin 的 `domain_skills` + 通用 Skills
2. 改造 `node_clause_analyze`，根据 checklist 的 `required_skills` 动态调用多个 Skills
3. 将 Skills 输出结构化传递给 LLM Prompt
4. 对未注册的 Skill 优雅跳过（不阻塞流程）

## 2. 文件清单

### 修改文件（共 3 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/graph/builder.py` | 改造 `_create_dispatcher` 和 `node_clause_analyze` |
| `backend/src/contract_review/graph/prompts.py` | `build_clause_analyze_messages` 增加 `skill_context` 参数 |
| `backend/src/contract_review/skills/schema.py` | `SkillRegistration` 增加 `domain` 和 `category` 元数据字段 |

### 新增文件（共 1 个）

| 文件路径 | 用途 |
|---------|------|
| `tests/test_skill_dispatch.py` | Skills 动态执行机制的单元测试 |

## 3. 详细设计

### 3.1 扩展 SkillRegistration 元数据

**文件：** `schema.py`

在 `SkillRegistration` 中新增两个可选字段：

```python
class SkillRegistration(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    input_schema: Optional[Type[BaseModel]] = None
    output_schema: Optional[Type[BaseModel]] = None
    backend: SkillBackend
    refly_workflow_id: Optional[str] = None
    local_handler: Optional[str] = None
    # --- 新增字段 ---
    domain: str = "*"          # "*" 表示通用，"fidic" 表示 FIDIC 专用
    category: str = "general"  # 技能类别：extraction / comparison / validation / general

    class Config:
        arbitrary_types_allowed = True
```

### 3.2 改造 `_create_dispatcher`

**文件：** `builder.py`

当前 `_create_dispatcher` 只硬编码注册了 `get_clause_context`。改造后：

```python
from ..plugins.registry import get_domain_plugin

# 通用 Skills 列表（模块级常量）
_GENERIC_SKILLS: list[SkillRegistration] = [
    SkillRegistration(
        skill_id="get_clause_context",
        name="获取条款上下文",
        description="从文档结构中提取指定条款文本",
        input_schema=ClauseContextInput,
        output_schema=ClauseContextOutput,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.clause_context.get_clause_context",
        domain="*",
        category="extraction",
    ),
]


def _create_dispatcher(domain_id: str | None = None) -> SkillDispatcher | None:
    """创建 SkillDispatcher 并注册通用 Skills + 领域 Skills。"""
    try:
        dispatcher = SkillDispatcher()

        # 1. 注册通用 Skills
        for skill in _GENERIC_SKILLS:
            try:
                dispatcher.register(skill)
            except Exception as exc:
                logger.warning("注册通用 Skill '%s' 失败: %s", skill.skill_id, exc)

        # 2. 注册领域 Skills（来自 Plugin）
        if domain_id:
            plugin = get_domain_plugin(domain_id)
            if plugin and plugin.domain_skills:
                for skill in plugin.domain_skills:
                    try:
                        dispatcher.register(skill)
                    except Exception as exc:
                        logger.warning("注册领域 Skill '%s' 失败（已跳过）: %s", skill.skill_id, exc)

        return dispatcher
    except Exception as exc:
        logger.warning("创建 SkillDispatcher 失败: %s", exc)
        return None
```

**关键点：**
- `_create_dispatcher` 新增 `domain_id` 参数
- 领域 Skill 注册失败不阻塞（try/except 逐个注册）
- `build_review_graph` 需要传入 `domain_id`

### 3.3 `build_review_graph` 签名变更

```python
def build_review_graph(
    checkpointer=None,
    interrupt_before: List[str] | None = None,
    domain_id: str | None = None,
):
    if interrupt_before is None:
        interrupt_before = ["human_approval"]

    dispatcher = _create_dispatcher(domain_id=domain_id)
    # ... 其余不变
```

**影响范围：** `api_gen3.py` 中调用 `build_review_graph()` 的地方需要传入 `domain_id`。搜索 `build_review_graph` 的调用点，补充参数。

### 3.4 改造 `node_clause_analyze` 的 Skills 动态调用

**文件：** `builder.py`

当前逻辑只调用 `get_clause_context`。改造后根据 `required_skills` 动态调用：

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

    # --- Skills 动态调用 ---
    primary_structure = state.get("primary_structure")
    skill_context: Dict[str, Any] = {}

    if dispatcher and primary_structure:
        for skill_id in required_skills:
            if skill_id not in dispatcher.skill_ids:
                logger.debug("Skill '%s' 未注册，跳过", skill_id)
                continue
            try:
                skill_input = _build_skill_input(skill_id, clause_id, primary_structure, state)
                if skill_input is None:
                    continue
                result = await dispatcher.call(skill_id, skill_input)
                if result.success and result.data:
                    skill_context[skill_id] = result.data
            except Exception as exc:
                logger.warning("Skill '%s' 调用失败: %s", skill_id, exc)

    # --- 条款文本提取（保持三层 fallback） ---
    clause_text = ""
    ctx = skill_context.get("get_clause_context")
    if isinstance(ctx, dict):
        clause_text = ctx.get("context_text", "")

    if not clause_text and primary_structure:
        clause_text = _extract_clause_text(primary_structure, clause_id)

    if not clause_text:
        clause_text = f"{clause_name}\n{description}".strip() or clause_id

    # --- LLM 调用（传入 skill_context） ---
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
                skill_context=skill_context,  # 新增参数
            )
            response = await llm_client.chat(messages)
            raw_risks = parse_json_response(response, expect_list=True)
            # ... 风险解析逻辑不变
```

### 3.5 新增 `_build_skill_input` 辅助函数

**文件：** `builder.py`

根据 skill_id 构造对应的输入对象。当前只有 `get_clause_context` 有明确的 Input schema，其他 Skill 暂时使用通用 dict 输入：

```python
def _build_skill_input(
    skill_id: str,
    clause_id: str,
    primary_structure: Any,
    state: ReviewGraphState,
) -> BaseModel | None:
    """根据 skill_id 构造输入对象。未识别的 skill 返回 None。"""
    if skill_id == "get_clause_context":
        try:
            return ClauseContextInput(
                clause_id=clause_id,
                document_structure=primary_structure,
            )
        except Exception:
            return None

    # 通用 Skills 使用 GenericSkillInput
    return GenericSkillInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        state_snapshot={
            "our_party": state.get("our_party", ""),
            "language": state.get("language", "en"),
            "domain_id": state.get("domain_id", ""),
        },
    )
```

### 3.6 新增 `GenericSkillInput` 模型

**文件：** `schema.py`

```python
class GenericSkillInput(BaseModel):
    """通用 Skill 输入，适用于尚未定义专用 Input schema 的 Skills。"""
    clause_id: str
    document_structure: Any = None
    state_snapshot: Dict[str, Any] = Field(default_factory=dict)
```

### 3.7 改造 Prompt 传入 skill_context

**文件：** `prompts.py`

`build_clause_analyze_messages` 新增 `skill_context` 参数：

```python
def build_clause_analyze_messages(
    *,
    language: str,
    our_party: str,
    clause_id: str,
    clause_name: str,
    description: str,
    priority: str,
    clause_text: str,
    skill_context: Dict[str, Any] | None = None,  # 新增
) -> List[Dict[str, str]]:
    system = CLAUSE_ANALYZE_SYSTEM.format(
        anti_injection=_anti_injection_instruction(language, our_party),
        jurisdiction_instruction=_jurisdiction_instruction(language),
        our_party=our_party,
    )
    user = (
        f"【条款信息】\n"
        f"- 条款编号：{clause_id}\n"
        f"- 条款名称：{clause_name}\n"
        f"- 审查重点：{description}\n"
        f"- 优先级：{priority}\n\n"
        f"【条款原文】\n<<<CLAUSE_START>>>\n{clause_text}\n<<<CLAUSE_END>>>"
    )

    # 追加 Skills 提供的额外上下文
    if skill_context:
        extra = _format_skill_context(skill_context)
        if extra:
            user += f"\n\n【辅助分析信息】\n{extra}"

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

**新增 `_format_skill_context` 函数：**

```python
def _format_skill_context(skill_context: Dict[str, Any]) -> str:
    """将 Skills 输出格式化为 LLM 可读的文本。"""
    parts = []
    for skill_id, data in skill_context.items():
        if skill_id == "get_clause_context":
            continue  # 条款原文已单独传递
        if isinstance(data, dict):
            parts.append(f"[{skill_id}]\n{json.dumps(data, ensure_ascii=False, indent=2)}")
        elif isinstance(data, str):
            parts.append(f"[{skill_id}]\n{data}")
    return "\n\n".join(parts)
```

### 3.8 `api_gen3.py` 调用点适配

搜索 `build_review_graph()` 的调用位置，传入 `domain_id`：

```python
# 在 start_review 端点中，构建图时传入 domain_id
graph = build_review_graph(domain_id=domain_id)
```

同时需要将 `domain_id` 存入图状态，以便 `node_clause_analyze` 可以访问。在 `ReviewGraphState` 中确认 `domain_id` 字段存在（如果不存在需要添加）。

## 4. 测试

### 4.1 测试文件：`tests/test_skill_dispatch.py`

```python
import pytest

pytest.importorskip("langgraph")

from contract_review.graph.builder import _build_skill_input, _create_dispatcher
from contract_review.skills.schema import GenericSkillInput


class TestCreateDispatcher:
    def test_creates_with_generic_skills(self):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None
        assert "get_clause_context" in dispatcher.skill_ids

    def test_creates_with_domain_skills(self):
        """领域 Skills 如果 handler 不存在，应跳过而非崩溃。"""
        from contract_review.plugins.fidic import register_fidic_plugin
        from contract_review.plugins.registry import clear_plugins

        clear_plugins()
        register_fidic_plugin()
        dispatcher = _create_dispatcher(domain_id="fidic")
        assert dispatcher is not None
        # get_clause_context 应该始终存在
        assert "get_clause_context" in dispatcher.skill_ids
        # fidic 领域 Skills 因 handler 模块不存在会注册失败，但不应崩溃

    def test_unknown_domain_returns_dispatcher(self):
        dispatcher = _create_dispatcher(domain_id="nonexistent")
        assert dispatcher is not None
        assert "get_clause_context" in dispatcher.skill_ids


class TestBuildSkillInput:
    def test_get_clause_context_input(self):
        result = _build_skill_input(
            "get_clause_context",
            "14.2",
            {"clauses": [], "document_id": "test", "structure_type": "generic", "definitions": {}, "cross_references": [], "total_clauses": 0},
            {"our_party": "承包商", "language": "zh-CN"},
        )
        assert result is not None
        assert result.clause_id == "14.2"

    def test_unknown_skill_returns_generic_input(self):
        result = _build_skill_input(
            "some_future_skill",
            "1.1",
            {"clauses": []},
            {"our_party": "承包商"},
        )
        assert isinstance(result, GenericSkillInput)
        assert result.clause_id == "1.1"

    def test_invalid_structure_returns_none(self):
        """get_clause_context 需要 DocumentStructure，传入不兼容数据应返回 None。"""
        result = _build_skill_input(
            "get_clause_context",
            "1.1",
            "not_a_dict",
            {},
        )
        assert result is None
```

### 4.2 已有测试兼容性

由于 `build_clause_analyze_messages` 新增了 `skill_context` 参数（默认值 `None`），已有测试不需要修改。

`build_review_graph` 新增了 `domain_id` 参数（默认值 `None`），已有测试也不需要修改。

## 5. 约束

1. 不修改 `redline_generator.py`
2. 不修改前端代码
3. 不修改已有测试用例，只新增
4. `_build_skill_input` 必须是纯函数
5. 未注册的 Skill 必须优雅跳过，不能阻塞审阅流程
6. `skill_context` 参数默认值为 `None`，确保向后兼容
7. 运行 `PYTHONPATH=backend/src python -m pytest tests/ -x -q` 确认全部通过

## 6. 验收标准

1. `_create_dispatcher(domain_id="fidic")` 能注册通用 Skills + FIDIC 领域 Skills（handler 不存在的跳过）
2. `node_clause_analyze` 根据 `required_skills` 动态调用已注册的 Skills
3. Skills 输出通过 `skill_context` 传递给 LLM Prompt
4. 未注册的 Skill 被跳过，不影响流程
5. 所有测试通过
