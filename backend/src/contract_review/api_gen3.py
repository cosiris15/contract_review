"""Gen 3.0 API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .models import (
    ApprovalRequest,
    ApprovalResponse,
    BatchApprovalRequest,
    StartReviewRequest,
    StartReviewResponse,
)
from .plugins.registry import get_domain_plugin, get_review_checklist, list_domain_plugins

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["Gen 3.0"])

_active_graphs: Dict[str, Dict[str, Any]] = {}
GRAPH_RETENTION_SECONDS = 3600


def _now_ts() -> float:
    return time.time()


def _touch_entry(entry: Dict[str, Any]) -> None:
    entry["last_access_ts"] = _now_ts()


def _prune_inactive_graphs() -> None:
    now = _now_ts()
    stale_task_ids = []
    for task_id, entry in _active_graphs.items():
        completed_ts = entry.get("completed_ts")
        if not completed_ts:
            continue
        if now - completed_ts > GRAPH_RETENTION_SECONDS:
            stale_task_ids.append(task_id)

    for task_id in stale_task_ids:
        _active_graphs.pop(task_id, None)


@router.post("/review/start", response_model=StartReviewResponse)
async def start_review(request: StartReviewRequest):
    _prune_inactive_graphs()
    task_id = request.task_id
    if task_id in _active_graphs:
        raise HTTPException(status_code=409, detail=f"任务 {task_id} 已有活跃的审查流程")

    checklist = []
    if request.domain_id:
        checklist = get_review_checklist(request.domain_id, request.domain_subtype)

    from .graph.builder import build_review_graph

    graph = build_review_graph()
    config = {"configurable": {"thread_id": task_id}}
    initial_state = {
        "task_id": task_id,
        "our_party": "",
        "material_type": "contract",
        "language": "en",
        "domain_id": request.domain_id,
        "domain_subtype": request.domain_subtype,
        "documents": [],
        "review_checklist": checklist,
    }

    graph_run_id = f"run_{task_id}"
    run_task = asyncio.create_task(_run_graph(task_id, graph, initial_state, config))
    _active_graphs[task_id] = {
        "graph": graph,
        "config": config,
        "graph_run_id": graph_run_id,
        "run_task": run_task,
        "last_access_ts": _now_ts(),
        "completed_ts": None,
    }

    return StartReviewResponse(task_id=task_id, status="reviewing", graph_run_id=graph_run_id)


@router.get("/review/{task_id}/status")
async def get_review_status(task_id: str):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    _touch_entry(entry)
    graph = entry["graph"]
    config = entry["config"]
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


@router.get("/review/{task_id}/pending-diffs")
async def get_pending_diffs(task_id: str):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    _touch_entry(entry)
    snapshot = entry["graph"].get_state(entry["config"])
    return {
        "task_id": task_id,
        "pending_diffs": snapshot.values.get("pending_diffs", []),
        "clause_id": snapshot.values.get("current_clause_id"),
    }


@router.post("/review/{task_id}/approve", response_model=ApprovalResponse)
async def approve_diff(task_id: str, request: ApprovalRequest):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    _touch_entry(entry)
    graph = entry["graph"]
    config = entry["config"]
    snapshot = graph.get_state(config)
    decisions = dict(snapshot.values.get("user_decisions", {}))
    feedback = dict(snapshot.values.get("user_feedback", {}))

    decisions[request.diff_id] = request.decision
    if request.feedback:
        feedback[request.diff_id] = request.feedback

    graph.update_state(config, {"user_decisions": decisions, "user_feedback": feedback})
    new_status = "approved" if request.decision == "approve" else "rejected"
    return ApprovalResponse(diff_id=request.diff_id, new_status=new_status, message=f"Diff {request.diff_id} 已{new_status}")


@router.post("/review/{task_id}/approve-batch")
async def approve_batch(task_id: str, request: BatchApprovalRequest):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    _touch_entry(entry)
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
        results.append({"diff_id": approval.diff_id, "new_status": "approved" if approval.decision == "approve" else "rejected"})

    graph.update_state(config, {"user_decisions": decisions, "user_feedback": feedback})
    return {"task_id": task_id, "results": results}


@router.post("/review/{task_id}/resume")
async def resume_review(task_id: str):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    resume_task = entry.get("resume_task")
    if resume_task and not resume_task.done():
        return {"task_id": task_id, "status": "resuming"}

    _touch_entry(entry)
    entry["resume_task"] = asyncio.create_task(
        _resume_graph(task_id, entry["graph"], entry["config"])
    )
    return {"task_id": task_id, "status": "resumed"}


@router.get("/domains")
async def list_domains():
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
    plugin = get_domain_plugin(domain_id)
    if not plugin:
        raise HTTPException(404, f"领域 '{domain_id}' 不存在")
    return {
        "domain_id": plugin.domain_id,
        "name": plugin.name,
        "description": plugin.description,
        "supported_subtypes": plugin.supported_subtypes,
        "review_checklist": [item.model_dump() for item in plugin.review_checklist],
        "skills": [{"skill_id": s.skill_id, "name": s.name, "backend": s.backend.value} for s in plugin.domain_skills],
    }


@router.get("/domains/{domain_id}/checklist")
async def get_domain_checklist(domain_id: str):
    plugin = get_domain_plugin(domain_id)
    if not plugin:
        raise HTTPException(404, f"领域 '{domain_id}' 不存在")
    return {
        "domain_id": domain_id,
        "checklist": [item.model_dump() for item in plugin.review_checklist],
    }


@router.get("/review/{task_id}/events")
async def review_events(task_id: str):
    async def event_generator():
        _prune_inactive_graphs()
        last_clause_index = -1
        pushed_diff_ids = set()
        while True:
            entry = _active_graphs.get(task_id)
            if not entry:
                yield _format_gen3_sse("review_error", {"message": "审查流程不存在"})
                break

            _touch_entry(entry)
            snapshot = entry["graph"].get_state(entry["config"])
            state = snapshot.values
            current_index = state.get("current_clause_index", 0)
            if current_index != last_clause_index:
                last_clause_index = current_index
                checklist = state.get("review_checklist", [])
                yield _format_gen3_sse(
                    "review_progress",
                    {
                        "task_id": task_id,
                        "current_clause_index": current_index,
                        "total_clauses": len(checklist),
                        "current_clause_id": state.get("current_clause_id"),
                        "message": f"正在审查第 {current_index + 1}/{max(len(checklist), 1)} 个条款",
                    },
                )

            pending = state.get("pending_diffs", [])
            if pending and snapshot.next:
                for diff in pending:
                    if hasattr(diff, "model_dump"):
                        payload = diff.model_dump()
                        diff_id = payload.get("diff_id")
                    else:
                        payload = diff
                        diff_id = payload.get("diff_id") if isinstance(payload, dict) else None
                    if diff_id and diff_id in pushed_diff_ids:
                        continue
                    if diff_id:
                        pushed_diff_ids.add(diff_id)
                    yield _format_gen3_sse("diff_proposed", payload)

            if state.get("is_complete"):
                yield _format_gen3_sse("review_complete", {"task_id": task_id, "summary": state.get("summary_notes", "")})
                break

            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def _run_graph(task_id: str, graph, initial_state: dict, config: dict):
    try:
        logger.info("开始执行审查图: %s", task_id)
        await graph.ainvoke(initial_state, config)
        logger.info("审查图执行完成或中断: %s", task_id)
    except Exception as exc:
        logger.error("审查图执行异常: %s — %s", task_id, exc)
    finally:
        entry = _active_graphs.get(task_id)
        if entry:
            _touch_entry(entry)
            entry.pop("run_task", None)
            try:
                snapshot = graph.get_state(config)
                if snapshot.values.get("is_complete"):
                    entry["completed_ts"] = _now_ts()
            except Exception:
                pass


async def _resume_graph(task_id: str, graph, config: dict):
    try:
        logger.info("恢复审查图执行: %s", task_id)
        await graph.ainvoke(None, config)
        logger.info("审查图恢复执行完成或再次中断: %s", task_id)
    except Exception as exc:
        logger.error("审查图恢复执行异常: %s — %s", task_id, exc)
    finally:
        entry = _active_graphs.get(task_id)
        if entry:
            _touch_entry(entry)
            entry.pop("resume_task", None)
            try:
                snapshot = graph.get_state(config)
                if snapshot.values.get("is_complete"):
                    entry["completed_ts"] = _now_ts()
            except Exception:
                pass


def _format_gen3_sse(event_type: str, data: Any) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
