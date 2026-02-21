# Codex Gen 3.0 代码审查报告

> 审查范围：Codex 按 SPEC 1-6 实施的全部代码
> 审查人：Claude Opus 4.6
> 日期：2026-02-20

---

## 总体评价

实现质量良好，6 个 Spec 全部落地，架构骨架完整，测试覆盖合理。代码风格简洁，与 Spec 文档高度一致。以下按严重程度分级列出发现的问题。

---

## 🔴 严重问题（必须修复）

### S1. `api_gen3.py:262` — SSE 格式化函数使用了转义换行符

```python
def _format_gen3_sse(event_type: str, data: Any) -> str:
    return f"event: {event_type}\\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\\n\\n"
```

**问题**：`\\n` 是字面量字符串 `\n`，不是真正的换行符。SSE 协议要求用真正的换行符 `\n` 分隔 `event:` 和 `data:` 行。当前写法会导致浏览器/前端无法正确解析 SSE 事件。

**修复**：将 `\\n` 改为 `\n`：
```python
def _format_gen3_sse(event_type: str, data: Any) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
```

### S2. `api_gen3.py:56` — `asyncio.create_task` 的 fire-and-forget 问题

```python
asyncio.create_task(_run_graph(task_id, graph, initial_state, config))
```

**问题**：创建的 task 没有被保存引用。如果 task 抛出异常，Python 会打印 "Task exception was never retrieved" 警告。更严重的是，如果 task 被垃圾回收，它可能被静默取消。

**修复**：将 task 引用保存到 `_active_graphs` 中：
```python
task = asyncio.create_task(_run_graph(task_id, graph, initial_state, config))
_active_graphs[task_id] = {"graph": graph, "config": config, "graph_run_id": graph_run_id, "task": task}
```
同样修复 `resume_review` 端点（第 146 行）。

### S3. `api_gen3.py:194-234` — SSE 事件流会重复推送相同的 pending_diffs

```python
pending = state.get("pending_diffs", [])
if pending and snapshot.next:
    for diff in pending:
        ...
        yield _format_gen3_sse("diff_proposed", payload)
```

**问题**：每次 2 秒轮询循环都会重新推送所有 pending_diffs，导致前端收到大量重复事件。

**修复**：添加已推送 diff 的追踪集合：
```python
async def event_generator():
    last_clause_index = -1
    pushed_diff_ids: set = set()  # 新增
    while True:
        ...
        pending = state.get("pending_diffs", [])
        if pending and snapshot.next:
            for diff in pending:
                diff_id = diff.get("diff_id") if isinstance(diff, dict) else diff.diff_id
                if diff_id not in pushed_diff_ids:  # 新增
                    pushed_diff_ids.add(diff_id)    # 新增
                    ...
                    yield _format_gen3_sse("diff_proposed", payload)
```

---

## 🟡 中等问题（建议修复）

### M1. `api_gen3.py` — 缺少 `_active_graphs` 的清理机制

**问题**：图执行完成后，`_active_graphs[task_id]` 永远不会被清理。长时间运行会导致内存泄漏。

**建议**：在 `_run_graph` 完成后清理，或添加 TTL 过期机制：
```python
async def _run_graph(task_id, graph, initial_state, config):
    try:
        await graph.ainvoke(initial_state, config)
    except Exception as exc:
        logger.error("审查图执行异常: %s — %s", task_id, exc)
    # 注意：不要在这里立即清理，因为用户可能还需要查询最终状态
    # 可以标记为已完成，由定期清理任务处理
```

### M2. `api_gen3.py:69` — `graph.get_state()` 应使用 async 版本

```python
snapshot = graph.get_state(config)
```

**问题**：在 async 端点中调用同步方法 `get_state()`。LangGraph 的 `get_state` 在使用某些 checkpointer 时可能阻塞事件循环。当前使用 `MemorySaver` 不会有问题，但切换到持久化 checkpointer 后会成为瓶颈。

**建议**：改用 `await graph.aget_state(config)`（如果 LangGraph 版本支持）。

### M3. `graph/state.py:9` — 导入了 `ActionRecommendation` 但该类型可能不存在于 models.py

```python
from ..models import (
    ActionRecommendation,
    ...
)
```

**问题**：需要确认 `ActionRecommendation` 是否在现有 `models.py` 中定义。如果不存在，这个 import 会在运行时报错。Codex 的测试可能因为 `pytest.importorskip("langgraph")` 跳过了这个检查。

**建议**：确认 `ActionRecommendation` 存在于 models.py 中。如果不存在，需要添加或移除该引用。

### M4. `graph/builder.py` — 节点函数中大量使用 `isinstance(x, dict)` 双模式处理

```python
clause_id = item["clause_id"] if isinstance(item, dict) else item.clause_id
```

**问题**：这种 dict/model 双模式处理散布在多个节点函数中（`node_parse_document`, `node_clause_analyze`, `node_save_clause`, `_generate_generic_checklist`）。LangGraph 的 TypedDict state 在运行时确实是 dict，所以 Pydantic model 分支可能永远不会执行。

**建议**：这不是 bug，但增加了代码复杂度。可以统一为只处理 dict 模式，因为 LangGraph state 始终是 dict。不过作为骨架代码，保留双模式也可以接受，后续填充真实逻辑时再统一。

### M5. `api_gen3.py:113` — `graph.update_state` 应使用 async 版本

```python
graph.update_state(config, {"user_decisions": decisions, "user_feedback": feedback})
```

**建议**：与 M2 同理，改用 `await graph.aupdate_state(config, ...)` 以避免阻塞。

---

## 🟢 轻微问题（可选修复）

### L1. `structure_parser.py:14` — DEFAULT_PARSER_CONFIG 的 clause_pattern 与 Spec 不一致

Spec-3 定义的默认模式：`r"^(\d+\.)+\d*\s+"`
Codex 实现的默认模式：`r"^\d+(?:\.\d+)*\s+"`

**影响**：两个正则在大多数情况下行为相同，但对边缘情况（如纯数字 "1 " 开头的行）匹配结果不同。Codex 的版本实际上更精确（不会匹配 "1. " 这种末尾带点的格式），但与 Spec 不一致。

**建议**：保持 Codex 的版本即可，它更合理。但需要确保 FIDIC 插件的 `clause_pattern` 仍然使用 Spec 中定义的 `r"^(\d+\.)+\d*\s+"`（已确认是这样）。

### L2. `refly_client.py:40` — `_session.aclose()` 调用了未初始化的 httpx session

```python
async def close(self):
    if self._session:
        await self._session.aclose()
```

**影响**：当前 `_session` 始终为 None（stub 阶段不创建 session），所以这段代码不会执行。但后续替换为真实实现时，需要确保 `_session` 被正确初始化为 `httpx.AsyncClient`。

### L3. `config.py:110-112` — Refly 环境变量覆盖逻辑的空字符串处理

```python
refly_base_url = os.getenv("REFLY_BASE_URL", refly_cfg.get("base_url", ""))
if refly_base_url:
    refly_cfg["base_url"] = refly_base_url
```

**影响**：如果 `REFLY_BASE_URL` 环境变量设置为空字符串，`if refly_base_url` 为 False，不会覆盖配置文件中的值。这其实是正确行为，但与 `REFLY_API_KEY` 的处理逻辑不完全对称。不影响功能。

### L4. 测试文件 `test_skill_framework.py` — 绕过了 `register()` 方法直接操作内部字典

```python
dispatcher._executors["echo"] = executor
dispatcher._registrations["echo"] = SkillRegistration(...)
```

**影响**：测试没有覆盖 `register()` 方法的正常路径（动态 import handler）。这是因为测试中的 handler 是内存中的函数，无法通过 `importlib.import_module` 加载。可以理解，但意味着 `_import_handler` 的正常路径没有被测试覆盖。

**建议**：可以添加一个测试，将 echo_handler 放在一个可 import 的模块路径下，测试完整的 `register()` 流程。优先级低。

### L5. `api_gen3.py:52` — `review_checklist` 传入的是 Pydantic model 列表

```python
checklist = get_review_checklist(request.domain_id, request.domain_subtype)
...
initial_state = {
    ...
    "review_checklist": checklist,  # List[ReviewChecklistItem]
}
```

**影响**：`checklist` 是 `List[ReviewChecklistItem]`（Pydantic model），但 `ReviewGraphState` 是 TypedDict，LangGraph 内部会将其序列化。`builder.py` 中的节点函数已经用 `isinstance(item, dict)` 做了双模式处理，所以不会报错。但数据流不够清晰。

**建议**：在传入 initial_state 前将 checklist 转为 dict 列表：
```python
"review_checklist": [item.model_dump() for item in checklist] if checklist else [],
```

---

## 测试质量评估

| 测试文件 | 覆盖度 | 评价 |
|---------|--------|------|
| test_skill_framework.py | 中等 | 覆盖了注册、调用、错误路径，但绕过了 register() 的动态 import |
| test_gen3_models.py | 良好 | 覆盖了递归嵌套、序列化、与现有模型兼容性 |
| test_structure_parser.py | 良好 | 覆盖了解析、层级、嵌套、交叉引用、定义提取 |
| test_domain_plugins.py | 良好 | 覆盖了注册、查询、清空、FIDIC 结构验证 |
| test_review_graph.py | 良好 | 覆盖了构建、空 checklist、单条款、中断恢复 |
| test_api_gen3.py | 良好 | 覆盖了域端点、启动、重复启动、404、SSE 事件类型 |

---

## 修复优先级建议

| 优先级 | 编号 | 描述 | 工作量 |
|--------|------|------|--------|
| 立即修复 | S1 | SSE 换行符转义错误 | 1 行 |
| 立即修复 | S2 | asyncio.create_task 引用丢失 | 2 行 |
| 立即修复 | S3 | SSE 事件流重复推送 | 5 行 |
| 尽快修复 | M1 | _active_graphs 内存泄漏 | 10 行 |
| 尽快修复 | M3 | ActionRecommendation import 确认 | 1 行 |
| 可选 | M2/M5 | get_state/update_state async 版本 | 各 1 行 |
| 可选 | M4 | dict/model 双模式统一 | 重构 |
| 低优先级 | L1-L5 | 轻微问题 | 各 1-3 行 |

---

## 结论

Codex 的实现忠实于 Spec 文档，架构骨架完整可用。3 个严重问题（S1-S3）都集中在 `api_gen3.py` 的 SSE 和异步处理部分，修复工作量很小（总共约 8 行代码）。建议优先修复 S1-S3 和 M1/M3，其余可在后续迭代中处理。
