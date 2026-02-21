# SPEC-7: LangGraph 节点 LLM 集成

> 版本：1.0
> 日期：2026-02-20
> 前置依赖：SPEC-1 ~ SPEC-6（已完成并部署）
> 目标：将 `graph/builder.py` 中 4 个 stub 节点替换为真正的 DeepSeek LLM 调用

---

## 1. 背景与目标

Gen 3.0 架构骨架已完成部署。当前 `builder.py` 中的 8 个节点里，有 4 个是 stub（返回硬编码/空数据）：

| 节点 | 当前行为 | 目标行为 |
|------|---------|---------|
| `node_clause_analyze` | 只提取 clause_id，返回空 risks | 调用 LLM 分析条款，输出 `List[RiskPoint]` |
| `node_clause_generate_diffs` | 返回空 diffs | 调用 LLM 根据 risks 生成修改建议 `List[DocumentDiff]` |
| `node_clause_validate` | 硬编码 `"pass"` | 调用 LLM 校验分析质量，输出 `"pass"` 或 `"fail"` |
| `node_summarize` | 拼接计数字符串 | 调用 LLM 生成结构化审查总结 |

另外，`SkillDispatcher` 尚未接入图节点，需要在本阶段完成接线。

### 1.1 不在本 Spec 范围内

- 前端 UI 改动
- 新增 API 端点
- 文档上传/解析流程（`node_parse_document` 保持现状）
- Refly 远程 Skill 的真实实现

---

## 2. 架构设计

### 2.1 LLM 调用层

不新建 LLM 封装。直接复用现有 `LLMClient`：

```
graph/builder.py 节点函数
    ↓
graph/prompts.py (新文件，Gen 3.0 专用 prompt 模板)
    ↓
LLMClient.chat() (现有，backend/src/contract_review/llm_client.py)
    ↓
DeepSeek API
```

### 2.2 LLMClient 实例化策略

在 `builder.py` 模块级别创建懒加载的 LLMClient 单例：

```python
# graph/builder.py 顶部新增
from ..config import get_settings
from ..llm_client import LLMClient

_llm_client: LLMClient | None = None

def _get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(get_settings().llm)
    return _llm_client
```

### 2.3 SkillDispatcher 接入

在 `build_review_graph()` 中初始化 dispatcher 并通过闭包传入节点：

```python
def build_review_graph(...):
    dispatcher = _create_dispatcher()

    # 节点函数通过闭包捕获 dispatcher
    async def _node_clause_analyze(state):
        return await node_clause_analyze(state, dispatcher)

    graph.add_node("clause_analyze", _node_clause_analyze)
    ...
```

---

## 3. Prompt 设计

### 3.1 新文件：`graph/prompts.py`

所有 Gen 3.0 图节点专用的 prompt 模板集中在此文件。复用现有 `prompts.py` 中的安全防护指令（`ANTI_INJECTION_INSTRUCTION`）和法域指令（`JURISDICTION_INSTRUCTIONS`）。

### 3.2 条款分析 Prompt（node_clause_analyze）

```python
CLAUSE_ANALYZE_SYSTEM = """你是一位资深法务审阅专家，正在逐条审查合同条款。

{anti_injection}

{jurisdiction_instruction}

【任务】
分析以下条款，从我方（{our_party}）的角度识别风险点。

【条款信息】
- 条款编号：{clause_id}
- 条款名称：{clause_name}
- 审查重点：{description}
- 优先级：{priority}

【条款原文】
<<<CLAUSE_START>>>
{clause_text}
<<<CLAUSE_END>>>

【输出要求】
以 JSON 数组格式输出风险点列表。每个风险点包含：
```json
[
  {
    "risk_level": "high|medium|low",
    "risk_type": "风险分类（如：责任条款、付款条件、违约责任等）",
    "description": "风险描述（一句话概括）",
    "reason": "判定理由（详细说明为什么这是风险）",
    "analysis": "深度分析（法律依据、潜在后果、应对建议）",
    "original_text": "相关原文摘录"
  }
]
```

如果该条款无风险，返回空数组 `[]`。
只输出 JSON，不要输出其他内容。"""
```

### 3.3 修改建议生成 Prompt（node_clause_generate_diffs）

```python
CLAUSE_GENERATE_DIFFS_SYSTEM = """你是一位资深法务审阅专家，需要根据已识别的风险点生成具体的合同修改建议。

【条款信息】
- 条款编号：{clause_id}
- 条款原文：
<<<CLAUSE_START>>>
{clause_text}
<<<CLAUSE_END>>>

【已识别的风险点】
{risks_json}

【输出要求】
针对每个风险点，生成具体的文本修改指令。以 JSON 数组格式输出：
```json
[
  {
    "risk_id": "对应的风险点序号（从0开始）",
    "action_type": "replace|delete|insert",
    "original_text": "需要修改的原文（必须是条款原文中的精确子串）",
    "proposed_text": "建议替换为的文本（delete 时为空字符串）",
    "reason": "修改理由",
    "risk_level": "high|medium|low"
  }
]
```

【重要规则】
1. `original_text` 必须是条款原文中可精确匹配的子串
2. `action_type` 为 `insert` 时，`original_text` 填写插入点前的文本
3. 修改建议应当具体、可操作，不要泛泛而谈
4. 如果某个风险点无需文本修改（需要通过谈判或补充协议解决），可以不生成 diff

只输出 JSON，不要输出其他内容。"""
```

### 3.4 校验 Prompt（node_clause_validate）

```python
CLAUSE_VALIDATE_SYSTEM = """你是一位法务审阅质量检查员。请检查以下条款分析和修改建议的质量。

【条款编号】{clause_id}
【条款原文】
<<<CLAUSE_START>>>
{clause_text}
<<<CLAUSE_END>>>

【风险分析结果】
{risks_json}

【修改建议】
{diffs_json}

【检查标准】
1. 风险分析是否准确、有依据？
2. 修改建议的 original_text 是否能在原文中精确匹配？
3. 修改建议是否合理、可操作？
4. 是否有遗漏的重要风险？

【输出要求】
只输出一个 JSON 对象：
```json
{
  "result": "pass|fail",
  "issues": ["问题描述1", "问题描述2"]
}
```

如果质量合格，`result` 为 `"pass"`，`issues` 为空数组。
如果有问题，`result` 为 `"fail"`，`issues` 列出具体问题。
只输出 JSON，不要输出其他内容。"""
```

### 3.5 总结 Prompt（node_summarize）

```python
SUMMARIZE_SYSTEM = """你是一位法务审阅专家，请根据以下审查结果生成结构化总结。

【审查概况】
- 共审查 {total_clauses} 个条款
- 发现 {total_risks} 个风险点（高：{high_risks}，中：{medium_risks}，低：{low_risks}）
- 生成 {total_diffs} 条修改建议

【各条款审查发现】
{findings_detail}

【输出要求】
生成一段结构化的审查总结（纯文本，不要 JSON），包含：
1. 总体风险评估（一句话）
2. 关键风险提示（列出最重要的 3-5 个风险）
3. 优先修改建议（列出最紧急需要修改的条款）
4. 后续建议（需要进一步关注或谈判的事项）

总结应当简洁专业，适合发送给业务负责人阅读。"""
```

---

## 4. 节点实现详细规格

### 4.1 node_clause_analyze

**输入（从 state 读取）：**
- `review_checklist[current_clause_index]` → 当前条款的 checklist item
- `primary_structure` → 文档结构（用于获取条款原文）
- `our_party` → 我方身份
- `language` → 语言

**处理流程：**
1. 从 checklist 获取当前条款的 `clause_id`, `clause_name`, `description`, `priority`
2. 通过 `SkillDispatcher.call("get_clause_context", ...)` 获取条款原文
   - 如果 dispatcher 不可用或 skill 调用失败，使用 `clause_name + description` 作为 fallback
3. 组装 prompt，调用 `LLMClient.chat()`
4. 解析 JSON 响应为 `List[RiskPoint]`
5. 为每个 RiskPoint 填充 `id`（generate_id）和 `location`（TextLocation）

**输出（写入 state）：**
```python
{
    "current_clause_id": clause_id,
    "current_clause_text": clause_text,  # 新增：保存条款原文供后续节点使用
    "current_risks": [RiskPoint dict, ...],
    "current_diffs": [],
    "clause_retry_count": 0,
}
```

**错误处理：**
- LLM 返回非 JSON → 尝试从响应中提取 JSON 块（正则 `\[.*\]`），失败则返回空 risks
- LLM 超时 → 记录 warning，返回空 risks
- JSON 字段缺失 → 使用默认值填充

### 4.2 node_clause_generate_diffs

**输入（从 state 读取）：**
- `current_clause_id`
- `current_clause_text`
- `current_risks`

**处理流程：**
1. 如果 `current_risks` 为空，直接返回空 diffs
2. 将 risks 序列化为 JSON 字符串
3. 组装 prompt，调用 `LLMClient.chat()`
4. 解析 JSON 响应为 `List[DocumentDiff]`
5. 为每个 diff 填充：
   - `diff_id`（generate_id）
   - `clause_id`（当前条款 ID）
   - `risk_id`（关联到对应 risk 的 id）
   - `status`（"pending"）

**输出（写入 state）：**
```python
{
    "current_diffs": [DocumentDiff dict, ...],
}
```

**错误处理：**
- 同 4.1 的 JSON 解析策略
- `original_text` 无法在条款原文中匹配 → 仍然保留 diff，但在 metadata 中标记 `{"text_match": false}`

### 4.3 node_clause_validate

**输入（从 state 读取）：**
- `current_clause_id`
- `current_clause_text`
- `current_risks`
- `current_diffs`
- `clause_retry_count`

**处理流程：**
1. 如果 `current_risks` 为空且 `current_diffs` 为空，直接返回 `"pass"`
2. 组装 prompt，调用 `LLMClient.chat()`
3. 解析 JSON 响应
4. 返回 validation result

**输出（写入 state）：**
```python
{
    "validation_result": "pass" | "fail",
    "clause_retry_count": retry_count + 1 if "fail" else retry_count,
}
```

**错误处理：**
- LLM 返回无法解析 → 默认 `"pass"`（宁可放行，不要卡住流程）

### 4.4 node_summarize

**输入（从 state 读取）：**
- `findings`
- `all_risks`
- `all_diffs`
- `review_checklist`

**处理流程：**
1. 统计风险数量（按级别分类）
2. 将 findings 格式化为可读文本
3. 组装 prompt，调用 `LLMClient.chat()`
4. 返回 LLM 生成的总结文本

**输出（写入 state）：**
```python
{
    "summary_notes": "LLM 生成的结构化总结文本",
    "is_complete": True,
}
```

**错误处理：**
- LLM 失败 → 回退到当前的计数字符串拼接逻辑

---

## 5. SkillDispatcher 接入规格

### 5.1 Dispatcher 初始化

在 `graph/builder.py` 中新增：

```python
from ..skills.dispatcher import SkillDispatcher
from ..skills.schema import SkillBackend, SkillRegistration

def _create_dispatcher() -> SkillDispatcher:
    dispatcher = SkillDispatcher()
    dispatcher.register(SkillRegistration(
        skill_id="get_clause_context",
        name="获取条款上下文",
        backend=SkillBackend.LOCAL,
        handler_path="contract_review.skills.local.clause_context:get_clause_context",
    ))
    return dispatcher
```

### 5.2 在 node_clause_analyze 中使用

```python
async def node_clause_analyze(state, dispatcher: SkillDispatcher | None = None):
    ...
    clause_text = ""
    if dispatcher and state.get("primary_structure"):
        try:
            result = await dispatcher.call("get_clause_context", {
                "clause_id": clause_id,
                "document_structure": state["primary_structure"],
            })
            if result.success:
                clause_text = result.output.get("clause_text", "")
        except Exception as e:
            logger.warning("Skill get_clause_context 调用失败: %s", e)
    ...
```

---

## 6. JSON 解析工具函数

新增 `graph/llm_utils.py`：

```python
"""LLM 响应解析工具。"""

import json
import logging
import re
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def parse_json_response(text: str, expect_list: bool = True) -> Any:
    """从 LLM 响应中解析 JSON。

    策略：
    1. 直接尝试 json.loads
    2. 尝试提取 ```json ... ``` 代码块
    3. 尝试正则提取 [...] 或 {...}
    """
    text = text.strip()

    # 策略 1：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略 2：提取 markdown 代码块
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 策略 3：正则提取
    pattern = r"\[.*\]" if expect_list else r"\{.*\}"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("无法从 LLM 响应中解析 JSON: %s...", text[:200])
    return [] if expect_list else {}
```

---

## 7. 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `graph/builder.py` | 修改 | 替换 4 个 stub 节点，接入 LLMClient 和 SkillDispatcher |
| `graph/prompts.py` | 新建 | Gen 3.0 图节点专用 prompt 模板 |
| `graph/llm_utils.py` | 新建 | JSON 解析工具函数 |
| `graph/__init__.py` | 可能修改 | 确保新模块可导入 |
| `tests/test_review_graph.py` | 修改 | 更新测试以 mock LLM 调用 |
| `tests/test_llm_utils.py` | 新建 | JSON 解析工具的单元测试 |
| `tests/test_graph_prompts.py` | 新建 | Prompt 模板格式化测试 |

**不修改的文件：**
- `llm_client.py` — 直接复用
- `models.py` — 所有需要的类型已存在
- `config.py` — 配置已足够
- `api_gen3.py` — API 层无需改动
- `prompts.py` / `prompts_interactive.py` — 现有 prompt 不动，只复用其中的安全指令

---

## 8. 测试策略

### 8.1 核心原则：Mock LLM，不依赖真实 API

所有测试通过 mock `LLMClient.chat()` 来运行，不需要真实的 DeepSeek API key。

### 8.2 test_llm_utils.py（新建）

```python
class TestParseJsonResponse:
    def test_direct_json_array(self):
        assert parse_json_response('[{"a": 1}]') == [{"a": 1}]

    def test_markdown_code_block(self):
        text = '```json\n[{"a": 1}]\n```'
        assert parse_json_response(text) == [{"a": 1}]

    def test_json_with_surrounding_text(self):
        text = '以下是分析结果：\n[{"a": 1}]\n以上。'
        assert parse_json_response(text) == [{"a": 1}]

    def test_invalid_json_returns_empty(self):
        assert parse_json_response('not json') == []

    def test_object_mode(self):
        text = '{"result": "pass"}'
        assert parse_json_response(text, expect_list=False) == {"result": "pass"}
```

### 8.3 test_graph_prompts.py（新建）

```python
class TestPromptFormatting:
    def test_clause_analyze_prompt_has_placeholders(self):
        from contract_review.graph.prompts import CLAUSE_ANALYZE_SYSTEM
        assert "{clause_id}" in CLAUSE_ANALYZE_SYSTEM
        assert "{our_party}" in CLAUSE_ANALYZE_SYSTEM

    def test_all_prompts_have_anti_injection(self):
        # 确保分析 prompt 包含安全防护
        from contract_review.graph.prompts import CLAUSE_ANALYZE_SYSTEM
        assert "{anti_injection}" in CLAUSE_ANALYZE_SYSTEM
```

### 8.4 test_review_graph.py（修改现有）

关键改动：mock LLMClient 使节点返回预设的 JSON 响应。

```python
@pytest.fixture
def mock_llm_client(monkeypatch):
    """Mock LLMClient.chat() 返回预设响应。"""
    async def fake_chat(messages, **kwargs):
        # 根据 prompt 内容判断是哪个节点在调用
        content = messages[-1]["content"] if messages else ""
        if "识别风险点" in content or "risk" in content.lower():
            return json.dumps([{
                "risk_level": "high",
                "risk_type": "付款条件",
                "description": "预付款比例过高",
                "reason": "预付款达到合同总价的30%，超出行业惯例",
                "analysis": "建议降低至10-15%",
                "original_text": "预付款为合同总价的30%"
            }])
        elif "修改建议" in content or "diff" in content.lower():
            return json.dumps([{
                "risk_id": "0",
                "action_type": "replace",
                "original_text": "预付款为合同总价的30%",
                "proposed_text": "预付款为合同总价的10%",
                "reason": "降低预付款风险",
                "risk_level": "high"
            }])
        elif "质量检查" in content or "validate" in content.lower():
            return json.dumps({"result": "pass", "issues": []})
        else:
            return "审查完成。共审查 1 个条款，发现 1 个风险点。"

    monkeypatch.setattr(
        "contract_review.graph.builder._get_llm_client",
        lambda: type("MockClient", (), {"chat": fake_chat})()
    )
```

测试用例：

```python
class TestLLMIntegration:
    @pytest.mark.asyncio
    async def test_single_clause_with_llm(self, mock_llm_client):
        """验证单条款审查能产出 risks 和 diffs。"""
        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_llm_001",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "review_checklist": [{
                "clause_id": "14.2",
                "clause_name": "预付款",
                "priority": "high",
                "required_skills": [],
                "description": "核查预付款条款",
            }],
        }
        config = {"configurable": {"thread_id": "test_llm"}}
        result = await graph.ainvoke(initial_state, config)

        assert result["is_complete"] is True
        assert len(result["all_risks"]) >= 1
        assert result["all_risks"][0]["risk_level"] == "high"

    @pytest.mark.asyncio
    async def test_llm_failure_graceful(self, monkeypatch):
        """验证 LLM 调用失败时节点不崩溃。"""
        async def failing_chat(messages, **kwargs):
            raise Exception("API timeout")

        monkeypatch.setattr(
            "contract_review.graph.builder._get_llm_client",
            lambda: type("MockClient", (), {"chat": failing_chat})()
        )

        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_fail_001",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "review_checklist": [{
                "clause_id": "1.1",
                "clause_name": "定义",
                "priority": "medium",
                "required_skills": [],
                "description": "检查定义条款",
            }],
        }
        config = {"configurable": {"thread_id": "test_fail"}}
        result = await graph.ainvoke(initial_state, config)

        # 即使 LLM 失败，图也应该正常完成
        assert result["is_complete"] is True
```

### 8.5 现有测试兼容性

现有的 `test_review_graph.py` 中的测试（`test_empty_checklist`, `test_single_clause_no_interrupt`, `test_interrupt_and_resume`）必须继续通过。由于这些测试不提供 mock，节点在无法获取 LLMClient 时应 graceful fallback 到空结果。

实现方式：`_get_llm_client()` 在配置文件不存在时返回 `None`，节点检查 client 是否为 None 后决定是否调用 LLM。

```python
def _get_llm_client() -> LLMClient | None:
    global _llm_client
    if _llm_client is None:
        try:
            _llm_client = LLMClient(get_settings().llm)
        except Exception:
            logger.warning("无法初始化 LLMClient，节点将使用 fallback 模式")
            return None
    return _llm_client
```

---

## 9. 执行顺序

```
步骤 1: 创建 graph/llm_utils.py + tests/test_llm_utils.py → 运行测试
步骤 2: 创建 graph/prompts.py + tests/test_graph_prompts.py → 运行测试
步骤 3: 修改 graph/builder.py（接入 LLMClient + SkillDispatcher + 替换 4 个 stub）
步骤 4: 修改 tests/test_review_graph.py（添加 mock LLM 测试）
步骤 5: 运行全部测试，确保 50 个现有测试 + 新测试全部通过
```

---

## 10. 验收标准

1. `graph/builder.py` 中 4 个节点不再返回硬编码数据
2. 使用 mock LLM 运行图时，`all_risks` 和 `all_diffs` 包含有意义的数据
3. LLM 调用失败时，图仍能正常完成（graceful degradation）
4. 现有 50 个测试全部通过（零回归）
5. 新增测试覆盖：JSON 解析、prompt 格式化、mock LLM 集成、LLM 失败降级
6. `SkillDispatcher` 在 `node_clause_analyze` 中被正确调用（当 primary_structure 存在时）
