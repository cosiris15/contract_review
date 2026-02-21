# SPEC-6: API 层改造

> 优先级：中（前端对接的桥梁）
> 前置依赖：Spec-2（API 模型）、Spec-4（LangGraph 图）
> 预计新建文件：1 个 | 修改文件：2 个
> 参考：GEN3_GAP_ANALYSIS.md 第 4.3、5.3 章

---

## 1. 目标

改造 API 层以支持 Gen 3.0 的新交互模式：
- 新增审查启动端点（触发 LangGraph 图执行）
- 新增审批端点（接收用户 Approve/Reject，恢复图执行）
- 扩展 SSE 协议（新增 Diff 推送和审查进度事件类型）
- 新增领域插件查询端点（前端获取可用领域列表）

不修改任何现有端点，所有新功能通过新增端点实现。

## 2. 需要创建的文件

### 2.1 `backend/src/contract_review/api_gen3.py`

Gen 3.0 新增 API 端点，作为独立模块挂载到现有 FastAPI app。

```python
"""
Gen 3.0 API 端点

新增的审查、审批、领域插件相关端点。
通过 FastAPI Router 挂载到现有 app，不影响旧端点。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .models import (
    ApprovalRequest,
    ApprovalResponse,
    BatchApprovalRequest,
    DiffPushEvent,
    ReviewProgressEvent,
    StartReviewRequest,
    StartReviewResponse,
    DocumentDiff,
)
from .graph.builder import build_review_graph
from .plugins.registry import (
    get_domain_plugin,
    get_review_checklist,
    list_domain_plugins,
    get_parser_config,
)
from .sse_protocol import format_sse_event, SSEEventType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["Gen 3.0"])

# 存储活跃的图执行实例
# key: task_id, value: {"graph": compiled_graph, "config": config, "state": latest_state}
_active_graphs: Dict[str, Dict[str, Any]] = {}


# ============================================================
# 审查流程端点
# ============================================================

@router.post("/review/start", response_model=StartReviewResponse)
async def start_review(request: StartReviewRequest):
    """
    启动 Gen 3.0 审查流程

    创建 LangGraph 图实例，初始化状态，开始异步执行。
    图会在 human_approval 节点前自动中断。
    """
    task_id = request.task_id

    # 检查是否已有活跃的图
    if task_id in _active_graphs:
        raise HTTPException(
            status_code=409,
            detail=f"任务 {task_id} 已有活跃的审查流程"
        )

    # 获取领域插件配置
    checklist = []
    if request.domain_id:
        checklist = get_review_checklist(
            request.domain_id, request.domain_subtype
        )

    # 构建图
    graph = build_review_graph()
    config = {"configurable": {"thread_id": task_id}}

    # 初始状态
    initial_state = {
        "task_id": task_id,
        "our_party": "",  # TODO: 从 ReviewTask 中获取
        "material_type": "contract",
        "language": "en",
        "domain_id": request.domain_id,
        "domain_subtype": request.domain_subtype,
        "documents": [],  # TODO: 从 Supabase 加载
        "review_checklist": checklist,
    }

    # 存储图实例
    graph_run_id = f"run_{task_id}"
    _active_graphs[task_id] = {
        "graph": graph,
        "config": config,
        "graph_run_id": graph_run_id,
    }

    # 异步启动图执行（不阻塞请求）
    asyncio.create_task(_run_graph(task_id, graph, initial_state, config))

    return StartReviewResponse(
        task_id=task_id,
        status="reviewing",
        graph_run_id=graph_run_id,
    )


@router.get("/review/{task_id}/status")
async def get_review_status(task_id: str):
    """
    获取审查流程状态

    返回当前图执行的状态快照。
    """
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    graph = entry["graph"]
    config = entry["config"]

    try:
        snapshot = graph.get_state(config)
        return {
            "task_id": task_id,
            "graph_run_id": entry["graph_run_id"],
            "next_nodes": list(snapshot.next) if snapshot.next else [],
            "is_interrupted": bool(snapshot.next),
            "current_clause_id": snapshot.values.get("current_clause_id"),
            "current_clause_index": snapshot.values.get("current_clause_index", 0),
            "total_clauses": len(snapshot.values.get("review_checklist", [])),
            "is_complete": snapshot.values.get("is_complete", False),
            "error": snapshot.values.get("error"),
        }
    except Exception as e:
        return {
            "task_id": task_id,
            "error": str(e),
        }


@router.get("/review/{task_id}/pending-diffs")
async def get_pending_diffs(task_id: str):
    """
    获取等待审批的 Diff 列表

    当图在 human_approval 节点中断时，返回 pending_diffs。
    """
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    graph = entry["graph"]
    config = entry["config"]

    snapshot = graph.get_state(config)
    pending = snapshot.values.get("pending_diffs", [])

    return {
        "task_id": task_id,
        "pending_diffs": pending,
        "clause_id": snapshot.values.get("current_clause_id"),
    }


# ============================================================
# 审批端点
# ============================================================

@router.post("/review/{task_id}/approve", response_model=ApprovalResponse)
async def approve_diff(task_id: str, request: ApprovalRequest):
    """
    单条 Diff 审批

    接收用户对某条 Diff 的 Approve/Reject 决策。
    累积到图状态中，不立即恢复图执行。
    调用 /review/{task_id}/resume 来恢复。
    """
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    graph = entry["graph"]
    config = entry["config"]

    # 获取当前状态
    snapshot = graph.get_state(config)
    decisions = dict(snapshot.values.get("user_decisions", {}))
    feedback = dict(snapshot.values.get("user_feedback", {}))

    # 更新决策
    decisions[request.diff_id] = request.decision
    if request.feedback:
        feedback[request.diff_id] = request.feedback

    # 注入到图状态
    graph.update_state(config, {
        "user_decisions": decisions,
        "user_feedback": feedback,
    })

    new_status = "approved" if request.decision == "approve" else "rejected"
    return ApprovalResponse(
        diff_id=request.diff_id,
        new_status=new_status,
        message=f"Diff {request.diff_id} 已{new_status}",
    )


@router.post("/review/{task_id}/approve-batch")
async def approve_batch(task_id: str, request: BatchApprovalRequest):
    """
    批量 Diff 审批

    一次性提交多条 Diff 的审批决策。
    """
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    graph = entry["graph"]
    config = entry["config"]

    snapshot = graph.get_state(config)
    decisions = dict(snapshot.values.get("user_decisions", {}))
    feedback = dict(snapshot.values.get("user_feedback", {}))

    results = []
    for approval in request.approvals:
        decisions[approval.diff_id] = approval.decision
        if approval.feedback:
            feedback[approval.diff_id] = approval.feedback
        results.append({
            "diff_id": approval.diff_id,
            "new_status": "approved" if approval.decision == "approve" else "rejected",
        })

    graph.update_state(config, {
        "user_decisions": decisions,
        "user_feedback": feedback,
    })

    return {"task_id": task_id, "results": results}


@router.post("/review/{task_id}/resume")
async def resume_review(task_id: str):
    """
    恢复审查流程

    在用户完成审批后调用，恢复 LangGraph 图执行。
    图将从 human_approval 节点继续。
    """
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    graph = entry["graph"]
    config = entry["config"]

    # 异步恢复图执行
    asyncio.create_task(_resume_graph(task_id, graph, config))

    return {"task_id": task_id, "status": "resumed"}


# ============================================================
# 领域插件查询端点
# ============================================================

@router.get("/domains")
async def list_domains():
    """列出所有可用的领域插件"""
    plugins = list_domain_plugins()
    return {
        "domains": [
            {
                "domain_id": p.domain_id,
                "name": p.name,
                "description": p.description,
                "supported_subtypes": p.supported_subtypes,
                "checklist_count": len(p.review_checklist),
                "skills_count": len(p.domain_skills),
            }
            for p in plugins
        ]
    }


@router.get("/domains/{domain_id}")
async def get_domain_detail(domain_id: str):
    """获取领域插件详情"""
    plugin = get_domain_plugin(domain_id)
    if not plugin:
        raise HTTPException(404, f"领域 '{domain_id}' 不存在")

    return {
        "domain_id": plugin.domain_id,
        "name": plugin.name,
        "description": plugin.description,
        "supported_subtypes": plugin.supported_subtypes,
        "review_checklist": [
            item.model_dump() for item in plugin.review_checklist
        ],
        "skills": [
            {"skill_id": s.skill_id, "name": s.name, "backend": s.backend.value}
            for s in plugin.domain_skills
        ],
    }


# ============================================================
# SSE 事件流端点
# ============================================================

@router.get("/review/{task_id}/events")
async def review_events(task_id: str):
    """
    审查事件 SSE 流

    前端通过 EventSource 订阅此端点，接收：
    - diff_proposed: Agent 提出修改建议
    - diff_approved/rejected: 审批结果确认
    - review_progress: 审查进度更新
    - review_complete: 审查完成
    """
    async def event_generator():
        # TODO: 实际实现中从消息队列或状态变更回调中获取事件
        # 当前骨架实现：轮询图状态变化
        last_clause_index = -1

        while True:
            entry = _active_graphs.get(task_id)
            if not entry:
                yield _format_gen3_sse("review_error", {"message": "审查流程不存在"})
                break

            graph = entry["graph"]
            config = entry["config"]

            try:
                snapshot = graph.get_state(config)
                state = snapshot.values

                # 检查进度变化
                current_index = state.get("current_clause_index", 0)
                if current_index != last_clause_index:
                    last_clause_index = current_index
                    checklist = state.get("review_checklist", [])
                    yield _format_gen3_sse("review_progress", {
                        "task_id": task_id,
                        "current_clause_index": current_index,
                        "total_clauses": len(checklist),
                        "current_clause_id": state.get("current_clause_id"),
                        "message": f"正在审查第 {current_index + 1}/{len(checklist)} 个条款",
                    })

                # 检查是否有待审批的 Diffs
                pending = state.get("pending_diffs", [])
                if pending and snapshot.next:
                    for diff in pending:
                        yield _format_gen3_sse("diff_proposed", diff)

                # 检查是否完成
                if state.get("is_complete"):
                    yield _format_gen3_sse("review_complete", {
                        "task_id": task_id,
                        "summary": state.get("summary_notes", ""),
                    })
                    break

            except Exception as e:
                yield _format_gen3_sse("review_error", {"message": str(e)})
                break

            await asyncio.sleep(2)  # 轮询间隔

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 内部辅助函数
# ============================================================

async def _run_graph(task_id: str, graph, initial_state: dict, config: dict):
    """异步执行图（后台任务）"""
    try:
        logger.info(f"开始执行审查图: {task_id}")
        await graph.ainvoke(initial_state, config)
        logger.info(f"审查图执行完成或中断: {task_id}")
    except Exception as e:
        logger.error(f"审查图执行异常: {task_id} — {e}")


async def _resume_graph(task_id: str, graph, config: dict):
    """异步恢复图执行（后台任务）"""
    try:
        logger.info(f"恢复审查图执行: {task_id}")
        await graph.ainvoke(None, config)
        logger.info(f"审查图恢复执行完成或再次中断: {task_id}")
    except Exception as e:
        logger.error(f"审查图恢复执行异常: {task_id} — {e}")


def _format_gen3_sse(event_type: str, data: Any) -> str:
    """格式化 Gen 3.0 SSE 事件"""
    import json
    if isinstance(data, dict):
        data_str = json.dumps(data, ensure_ascii=False, default=str)
    else:
        data_str = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {data_str}\n\n"
```

## 3. 需要修改的文件

### 3.1 `backend/src/contract_review/sse_protocol.py`

在 `SSEEventType` 枚举中追加 Gen 3.0 事件类型。

```python
# === 在 SSEEventType 枚举末尾追加 ===

    # Gen 3.0 新增事件类型
    DIFF_PROPOSED = "diff_proposed"          # Agent 提出修改建议
    DIFF_APPROVED = "diff_approved"          # 用户批准修改
    DIFF_REJECTED = "diff_rejected"          # 用户拒绝修改
    DIFF_REVISED = "diff_revised"            # Agent 修订了 Diff
    REVIEW_PROGRESS = "review_progress"      # 审查进度更新
    REVIEW_COMPLETE = "review_complete"       # 审查完成
    APPROVAL_REQUIRED = "approval_required"  # 需要用户审批（图中断）
```

在文件末尾追加 Gen 3.0 便捷函数：

```python
# === Gen 3.0 SSE 便捷函数 ===

def diff_proposed(diff_data: Dict) -> str:
    """快捷方式：创建 Diff 提议事件"""
    return format_sse_event(SSEEventType.DIFF_PROPOSED, diff_data)


def diff_approved(diff_id: str) -> str:
    """快捷方式：创建 Diff 批准事件"""
    return format_sse_event(
        SSEEventType.DIFF_APPROVED,
        {"diff_id": diff_id, "type": "diff_approved"}
    )


def diff_rejected(diff_id: str, reason: str = "") -> str:
    """快捷方式：创建 Diff 拒绝事件"""
    return format_sse_event(
        SSEEventType.DIFF_REJECTED,
        {"diff_id": diff_id, "reason": reason, "type": "diff_rejected"}
    )


def review_progress(task_id: str, current: int, total: int, message: str = "") -> str:
    """快捷方式：创建审查进度事件"""
    return format_sse_event(
        SSEEventType.REVIEW_PROGRESS,
        {
            "task_id": task_id,
            "current": current,
            "total": total,
            "message": message,
            "type": "review_progress",
        }
    )


def approval_required(task_id: str, diffs: list) -> str:
    """快捷方式：创建审批请求事件"""
    return format_sse_event(
        SSEEventType.APPROVAL_REQUIRED,
        {
            "task_id": task_id,
            "pending_count": len(diffs),
            "type": "approval_required",
        }
    )
```

### 3.2 `backend/api_server.py`

在现有 FastAPI app 中挂载 Gen 3.0 路由。

```python
# === 在 import 区域追加 ===
from contract_review.api_gen3 import router as gen3_router

# === 在 app 创建之后、现有路由之前追加 ===
app.include_router(gen3_router)

# === 在应用启动事件中注册 FIDIC 插件 ===
@app.on_event("startup")
async def register_plugins():
    """启动时注册领域插件"""
    from contract_review.plugins.fidic import register_fidic_plugin
    register_fidic_plugin()
```

## 4. 目录结构（完成后）

```
backend/src/contract_review/
├── api_gen3.py                  # 新建：Gen 3.0 API 端点
├── sse_protocol.py              # 修改：追加 Diff 事件类型
└── ... (其他文件不动)

backend/
├── api_server.py                # 修改：挂载 gen3_router
```

## 5. API 端点总览

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/v3/review/start` | 启动 Gen 3.0 审查流程 |
| GET | `/api/v3/review/{task_id}/status` | 获取审查状态 |
| GET | `/api/v3/review/{task_id}/pending-diffs` | 获取待审批 Diff |
| POST | `/api/v3/review/{task_id}/approve` | 单条 Diff 审批 |
| POST | `/api/v3/review/{task_id}/approve-batch` | 批量 Diff 审批 |
| POST | `/api/v3/review/{task_id}/resume` | 恢复审查流程 |
| GET | `/api/v3/review/{task_id}/events` | SSE 事件流 |
| GET | `/api/v3/domains` | 列出领域插件 |
| GET | `/api/v3/domains/{domain_id}` | 领域插件详情 |

## 6. 前端对接要点

```
前端需要的交互流程：

1. 用户选择领域 → GET /api/v3/domains → 展示可选领域列表
2. 用户启动审查 → POST /api/v3/review/start
3. 前端订阅 SSE → GET /api/v3/review/{task_id}/events
4. 收到 review_progress → 更新进度条
5. 收到 diff_proposed → 在 Canvas 中渲染红线标注
6. 收到 approval_required → 启用 Approve/Reject 按钮
7. 用户逐条审批 → POST /api/v3/review/{task_id}/approve
8. 用户完成审批 → POST /api/v3/review/{task_id}/resume
9. 收到 review_complete → 展示汇总结果
```

## 7. 验收标准

1. `POST /api/v3/review/start` 返回 `StartReviewResponse`，图开始异步执行
2. `GET /api/v3/review/{task_id}/status` 返回当前图状态（含 next_nodes、is_interrupted）
3. `GET /api/v3/review/{task_id}/pending-diffs` 在图中断时返回待审批 Diff 列表
4. `POST /api/v3/review/{task_id}/approve` 正确注入 user_decisions 到图状态
5. `POST /api/v3/review/{task_id}/resume` 恢复图执行
6. `GET /api/v3/review/{task_id}/events` 返回 SSE 流，包含 review_progress 事件
7. `GET /api/v3/domains` 返回已注册的领域列表（含 FIDIC）
8. `SSEEventType` 新增的枚举值不影响现有 SSE 事件的生成和解析
9. 所有新端点使用 `/api/v3/` 前缀，不与现有端点冲突
10. 所有新代码通过 `python -m py_compile` 语法检查

## 8. 验证用测试代码

```python
# tests/test_api_gen3.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock


@pytest.fixture
def app():
    """创建测试用 FastAPI app"""
    from fastapi import FastAPI
    from contract_review.api_gen3 import router, _active_graphs
    from contract_review.plugins.fidic import register_fidic_plugin
    from contract_review.plugins.registry import clear_plugins

    test_app = FastAPI()
    test_app.include_router(router)

    # 注册 FIDIC 插件
    clear_plugins()
    register_fidic_plugin()

    # 清空活跃图
    _active_graphs.clear()

    return test_app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestDomainEndpoints:
    @pytest.mark.asyncio
    async def test_list_domains(self, client):
        """测试列出领域插件"""
        resp = await client.get("/api/v3/domains")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["domains"]) >= 1
        fidic = data["domains"][0]
        assert fidic["domain_id"] == "fidic"

    @pytest.mark.asyncio
    async def test_get_domain_detail(self, client):
        """测试获取领域详情"""
        resp = await client.get("/api/v3/domains/fidic")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["review_checklist"]) >= 12

    @pytest.mark.asyncio
    async def test_get_nonexistent_domain(self, client):
        """测试获取不存在的领域"""
        resp = await client.get("/api/v3/domains/nonexistent")
        assert resp.status_code == 404


class TestReviewEndpoints:
    @pytest.mark.asyncio
    async def test_start_review(self, client):
        """测试启动审查"""
        resp = await client.post("/api/v3/review/start", json={
            "task_id": "test_001",
            "domain_id": "fidic",
            "domain_subtype": "silver_book",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "test_001"
        assert data["status"] == "reviewing"

    @pytest.mark.asyncio
    async def test_duplicate_start(self, client):
        """测试重复启动"""
        await client.post("/api/v3/review/start", json={
            "task_id": "test_dup",
        })
        resp = await client.post("/api/v3/review/start", json={
            "task_id": "test_dup",
        })
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_approve_nonexistent(self, client):
        """测试审批不存在的任务"""
        resp = await client.post("/api/v3/review/nonexistent/approve", json={
            "diff_id": "d1",
            "decision": "approve",
        })
        assert resp.status_code == 404


class TestSSEProtocol:
    def test_new_event_types(self):
        """测试新增 SSE 事件类型"""
        from contract_review.sse_protocol import SSEEventType
        assert SSEEventType.DIFF_PROPOSED.value == "diff_proposed"
        assert SSEEventType.REVIEW_PROGRESS.value == "review_progress"
        assert SSEEventType.APPROVAL_REQUIRED.value == "approval_required"

    def test_existing_events_unchanged(self):
        """确认现有事件类型未被破坏"""
        from contract_review.sse_protocol import SSEEventType
        assert SSEEventType.TOOL_CALL.value == "tool_call"
        assert SSEEventType.MESSAGE_DELTA.value == "message_delta"
        assert SSEEventType.DONE.value == "done"
```

## 9. 注意事项

- 所有新端点使用 `/api/v3/` 前缀，与现有 `/api/` 端点完全隔离
- `_active_graphs` 是进程内存储，重启后丢失。生产环境需替换为持久化方案
- `asyncio.create_task()` 用于非阻塞启动图执行，但需注意异常处理
- SSE 事件流使用轮询实现（2s 间隔），后续可优化为事件驱动
- `api_server.py` 的修改仅追加 2 行（import + include_router），不改动现有逻辑
- `sse_protocol.py` 的修改仅追加枚举值和便捷函数，不改动现有函数签名
- 前端 Canvas 富文本编辑器的实现不在本 Spec 范围内（属于前端重构阶段）
