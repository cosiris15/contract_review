# SPEC-25：Human-in-the-Loop 审批工作流完善

> 状态：待实施
> 优先级：P0（Phase 1 第二项）
> 前置依赖：SPEC-24（Gen3 默认化）已完成
> 预估改动量：~80 行后端代码 + ~30 行前端代码 + ~150 行测试

---

## 0. 背景与动机

当前系统已具备 Human-in-the-Loop 的基础设施：
- LangGraph `interrupt_before=["human_approval"]` 正确暂停图执行
- `node_human_approval()` 将 diffs 移入 `pending_diffs`
- 三个审批端点（`/approve`、`/approve-batch`、`/resume`）已实现
- 前端 Pinia store 有 `phase: 'interrupted'` 状态和 `DiffCard.vue` 审批按钮
- SSE 协议定义了 `APPROVAL_REQUIRED` 事件类型和 `approval_required()` 辅助函数

但存在以下关键缺口：

1. **后端不发送 `approval_required` SSE 事件**：事件流只发送 `diff_proposed`，前端靠 `onDiffProposed` 间接设置 `phase='interrupted'`，没有明确的"等待审批"信号
2. **`/resume` 端点不验证决策完整性**：可以在未对所有 diff 做出决策的情况下恢复执行
3. **`route_after_approval` 不处理拒绝**：始终返回 `"save_clause"`，被拒绝的 diff 没有重新生成的机会

---

## 1. 设计原则

1. **最小改动**：利用已有的 SSE 事件类型和辅助函数，不引入新的事件类型
2. **信号完整**：`diff_proposed`（逐条）+ `approval_required`（汇总）形成完整信号链
3. **安全恢复**：`/resume` 必须验证所有 pending diff 都有决策
4. **拒绝可重生成**：被拒绝的 diff 可选路由回 `clause_generate_diffs` 重新生成（可配置）

---

## 2. 改动清单

### 2.1 api_gen3.py — 事件流发送 `approval_required`

**改动 1：在 `review_events` 的事件生成器中，发送完所有 `diff_proposed` 后，发送一次 `approval_required`**

当前代码（第 744-757 行）在检测到 `pending` 且 `snapshot.next` 时，逐条发送 `diff_proposed`。需要在这个循环之后，如果本轮有新 diff 被推送，额外发送一次 `approval_required` 事件。

```python
# 在第 757 行之后，添加：
# 如果本轮推送了新的 diff，发送 approval_required 汇总信号
new_diffs_pushed = False
for diff in pending:
    # ... 现有逻辑 ...
    if diff_id and diff_id not in pushed_diff_ids:
        new_diffs_pushed = True
    # ... 现有逻辑 ...

if new_diffs_pushed and snapshot.next:
    yield _format_gen3_sse("approval_required", {
        "task_id": task_id,
        "pending_count": len(pending),
        "type": "approval_required",
    })
```

具体实现：重构事件流循环，在 diff 推送循环中追踪 `new_diffs_pushed` 标志，循环结束后条件发送。

### 2.2 api_gen3.py — `/resume` 端点验证决策完整性

**改动 2：在 `resume_review` 中，验证所有 `pending_diffs` 都有对应的 `user_decisions`**

```python
@router.post("/review/{task_id}/resume")
async def resume_review(task_id: str):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    # 新增：验证决策完整性
    graph = entry["graph"]
    config = entry["config"]
    snapshot = graph.get_state(config)
    state = snapshot.values
    pending = state.get("pending_diffs", [])
    decisions = state.get("user_decisions", {})

    if pending:
        pending_ids = set()
        for diff in pending:
            if hasattr(diff, "diff_id"):
                pending_ids.add(diff.diff_id)
            elif isinstance(diff, dict):
                did = diff.get("diff_id")
                if did:
                    pending_ids.add(did)
        missing = pending_ids - set(decisions.keys())
        if missing:
            raise HTTPException(
                400,
                f"以下 diff 尚未做出决策: {', '.join(sorted(missing))}。请先完成所有审批再恢复。"
            )

    resume_task = entry.get("resume_task")
    if resume_task and not resume_task.done():
        return {"task_id": task_id, "status": "resuming"}

    _touch_entry(entry)
    entry["resume_task"] = asyncio.create_task(
        _resume_graph(task_id, entry["graph"], entry["config"])
    )
    return {"task_id": task_id, "status": "resumed"}
```

### 2.3 builder.py — `route_after_approval` 处理拒绝

**改动 3：`route_after_approval` 检查是否有被拒绝的 diff，如果全部拒绝则路由回 `clause_generate_diffs`**

```python
# 第 904-906 行，改前：
def route_after_approval(state: ReviewGraphState) -> str:
    _ = state
    return "save_clause"

# 改后：
def route_after_approval(state: ReviewGraphState) -> str:
    """审批后路由：如果所有 diff 都被拒绝，重新生成；否则保存。"""
    user_decisions = state.get("user_decisions", {})
    pending_diffs = state.get("pending_diffs", [])

    if not pending_diffs or not user_decisions:
        return "save_clause"

    # 收集本轮 pending diff 的决策
    pending_ids = set()
    for diff in pending_diffs:
        if hasattr(diff, "diff_id"):
            pending_ids.add(diff.diff_id)
        elif isinstance(diff, dict):
            did = diff.get("diff_id")
            if did:
                pending_ids.add(did)

    # 检查是否全部拒绝
    all_rejected = all(
        user_decisions.get(did) == "reject" for did in pending_ids if did in user_decisions
    )

    if all_rejected and pending_ids:
        return "clause_generate_diffs"

    return "save_clause"
```

同时需要更新 `build_review_graph` 中 `route_after_approval` 的条件边映射，添加 `"clause_generate_diffs"` 目标：

```python
# 第 992 行，改前：
graph.add_conditional_edges("human_approval", route_after_approval, {"save_clause": "save_clause"})

# 改后：
graph.add_conditional_edges(
    "human_approval",
    route_after_approval,
    {"save_clause": "save_clause", "clause_generate_diffs": "clause_generate_diffs"},
)
```

### 2.4 builder.py — `node_human_approval` 清理上一轮决策

**改动 4：`node_human_approval` 在设置 `pending_diffs` 时，清空上一轮的 `user_decisions` 和 `user_feedback`**

```python
# 第 750-754 行，改前：
async def node_human_approval(state: ReviewGraphState) -> Dict[str, Any]:
    diffs = state.get("current_diffs", [])
    if not diffs:
        return {"pending_diffs": [], "user_decisions": {}}
    return {"pending_diffs": diffs}

# 改后：
async def node_human_approval(state: ReviewGraphState) -> Dict[str, Any]:
    """准备审批：将当前 diffs 移入 pending，清空上一轮决策。"""
    diffs = state.get("current_diffs", [])
    if not diffs:
        return {"pending_diffs": [], "user_decisions": {}, "user_feedback": {}}
    return {"pending_diffs": diffs, "user_decisions": {}, "user_feedback": {}}
```

---

## 3. 前端改动（最小）

前端已有完整的审批 UI 和事件处理逻辑。唯一需要确认的是 `onApprovalRequired` 回调已正确连接。

根据调研，`gen3Review.js` 第 167 行已有：
```javascript
onApprovalRequired: () => {
    this.phase = 'interrupted'
}
```

`gen3.js` API 客户端已能解析 `approval_required` 事件。

**无需前端代码改动**。后端开始发送 `approval_required` 事件后，前端自动生效。

但需要验证：前端 `resumeAfterApproval()` 方法应能处理 400 错误（决策不完整时 `/resume` 返回 400）。检查 `gen3Review.js` 第 242-258 行的错误处理是否充分。如果 `resumeAfterApproval` 没有 catch 400 并显示提示，需要添加。

**建议改动**（如果当前没有 400 错误处理）：

```javascript
async resumeAfterApproval() {
    try {
        await gen3Api.resumeReview(this.taskId)
        this.phase = 'reviewing'
    } catch (err) {
        if (err.response?.status === 400) {
            // 决策不完整，提示用户
            ElMessage.warning(err.response.data?.detail || '请先完成所有审批再恢复')
        } else {
            this.phase = 'error'
        }
    }
}
```

---

## 4. 测试要求

### 4.1 后端测试

**新增 `tests/test_approval_workflow.py`**：

```python
class TestApprovalRequired:
    """测试 approval_required SSE 事件发送"""

    def test_event_stream_sends_approval_required_after_diffs(self):
        """事件流在发送 diff_proposed 后应发送 approval_required"""
        # Mock graph state with pending_diffs and snapshot.next
        # Verify event stream yields diff_proposed + approval_required

    def test_event_stream_no_approval_required_when_no_pending(self):
        """无 pending diffs 时不发送 approval_required"""


class TestResumeValidation:
    """测试 /resume 端点决策完整性验证"""

    def test_resume_rejects_incomplete_decisions(self):
        """未完成所有决策时 /resume 返回 400"""

    def test_resume_accepts_complete_decisions(self):
        """所有决策完成后 /resume 正常恢复"""

    def test_resume_accepts_empty_pending(self):
        """无 pending diffs 时 /resume 正常恢复"""


class TestRouteAfterApproval:
    """测试审批后路由逻辑"""

    def test_all_rejected_routes_to_regenerate(self):
        """全部拒绝时路由到 clause_generate_diffs"""

    def test_mixed_decisions_routes_to_save(self):
        """混合决策时路由到 save_clause"""

    def test_all_approved_routes_to_save(self):
        """全部批准时路由到 save_clause"""

    def test_empty_decisions_routes_to_save(self):
        """无决策时路由到 save_clause"""


class TestNodeHumanApproval:
    """测试 node_human_approval 清理逻辑"""

    def test_clears_previous_decisions(self):
        """进入审批节点时清空上一轮 user_decisions 和 user_feedback"""

    def test_empty_diffs_returns_empty(self):
        """无 diffs 时返回空 pending_diffs"""
```

### 4.2 现有测试更新

- `test_review_graph.py` 中涉及 `route_after_approval` 的测试需要更新条件边映射
- `test_e2e_gen3.py` 中如果有审批相关的 e2e 测试，需要适配新的验证逻辑

---

## 5. 文件清单

| 文件 | 改动类型 | 改动点 |
|------|----------|--------|
| `backend/src/contract_review/api_gen3.py` | 修改 | 事件流发送 `approval_required`；`/resume` 验证决策完整性 |
| `backend/src/contract_review/graph/builder.py` | 修改 | `route_after_approval` 处理拒绝；`node_human_approval` 清理决策；条件边映射更新 |
| `frontend/src/store/gen3Review.js` | 修改（可选） | `resumeAfterApproval` 添加 400 错误处理 |
| `tests/test_approval_workflow.py` | 新增 | 审批工作流专项测试 |
| `tests/test_review_graph.py` | 修改 | 更新 `route_after_approval` 条件边映射 |

---

## 6. 验收条件

1. 事件流在发送 `diff_proposed` 后发送 `approval_required` 事件（含 `pending_count`）
2. 无 pending diffs 时不发送 `approval_required`
3. 已推送过的 diff 不重复发送 `approval_required`
4. `/resume` 端点在决策不完整时返回 400 + 明确错误信息
5. `/resume` 端点在决策完整时正常恢复
6. `route_after_approval` 在全部拒绝时路由到 `clause_generate_diffs`
7. `route_after_approval` 在混合/全部批准时路由到 `save_clause`
8. `node_human_approval` 进入时清空 `user_decisions` 和 `user_feedback`
9. `build_review_graph` 中 `human_approval` 的条件边包含 `clause_generate_diffs` 目标
10. 前端 `resumeAfterApproval` 能处理 400 错误并提示用户
11. 新增测试全部通过
12. `pytest` 全量通过，无回归

---

## 7. 实施步骤

1. `builder.py`：修改 `node_human_approval`（清理决策）、`route_after_approval`（处理拒绝）、条件边映射
2. `api_gen3.py`：事件流添加 `approval_required` 发送逻辑；`/resume` 添加验证
3. `frontend/src/store/gen3Review.js`：`resumeAfterApproval` 添加 400 错误处理（如果当前没有）
4. 新增 `tests/test_approval_workflow.py`
5. 更新 `tests/test_review_graph.py` 中的条件边映射
6. 运行 `cd backend && PYTHONPATH=backend/src python -m pytest tests/ -x -q`，确保全量通过

---

## 8. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 全部拒绝后重新生成可能导致无限循环 | `clause_retry_count` 已有上限（`route_validation` 中检查），重新生成后仍需通过验证 |
| `/resume` 400 错误可能影响前端体验 | 前端添加明确的错误提示，引导用户完成审批 |
| `approval_required` 事件可能重复发送 | 使用 `new_diffs_pushed` 标志，仅在有新 diff 推送时发送 |
| 清空 `user_decisions` 可能丢失跨条款决策 | `user_decisions` 是按 diff_id 索引的，每个条款的 diff_id 不同，清空不影响已保存的条款 |
