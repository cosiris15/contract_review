"""Gen 3.0 API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .document_loader import load_document
from .models import (
    ApprovalRequest,
    ApprovalResponse,
    BatchApprovalRequest,
    DocumentRole,
    ModificationSuggestion,
    StartReviewRequest,
    StartReviewResponse,
    TaskDocument,
    generate_id,
)
from .plugins.registry import (
    get_all_skills_for_domain,
    get_domain_plugin,
    get_parser_config,
    get_review_checklist,
    list_domain_plugins,
)
from .redline_generator import generate_redline_document
from .structure_parser import StructureParser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["Gen 3.0"])

_active_graphs: Dict[str, Dict[str, Any]] = {}
GRAPH_RETENTION_SECONDS = 3600
ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md", ".xlsx"}
MAX_UPLOAD_SIZE_MB = 10
ALLOWED_ROLES = {"primary", "baseline", "supplement", "reference", "criteria"}


def _role_to_str(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "")


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def _priority_from_risk_level(level: Any) -> str:
    normalized = str(level or "").lower()
    if normalized in {"high", "critical"}:
        return "must"
    if normalized == "medium":
        return "should"
    return "may"


def _diff_to_modification(diff: dict) -> ModificationSuggestion:
    action_type = str(diff.get("action_type", "replace"))
    clause_id = str(diff.get("clause_id", "") or "")
    diff_id = str(diff.get("diff_id", "") or generate_id())
    risk_id = str(diff.get("risk_id", "") or diff_id)
    is_addition = action_type == "insert"
    insertion_point = f"插入到条款 {clause_id} 之后" if is_addition and clause_id else None

    return ModificationSuggestion(
        id=diff_id,
        risk_id=risk_id,
        original_text=str(diff.get("original_text", "") or ""),
        suggested_text=str(diff.get("proposed_text", "") or ""),
        modification_reason=str(diff.get("reason", "") or ""),
        priority=_priority_from_risk_level(diff.get("risk_level")),
        user_confirmed=True,
        is_addition=is_addition,
        insertion_point=insertion_point,
    )


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
        entry = _active_graphs.pop(task_id, None)
        if not entry:
            continue
        tmp_dir = entry.get("tmp_dir")
        if tmp_dir:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception as exc:  # pragma: no cover - defensive cleanup
                logger.warning("清理临时目录失败 [%s]: %s", tmp_dir, exc)


@router.post("/review/start", response_model=StartReviewResponse)
async def start_review(request: StartReviewRequest):
    _prune_inactive_graphs()
    task_id = request.task_id
    if task_id in _active_graphs:
        raise HTTPException(status_code=409, detail=f"任务 {task_id} 已有活跃的审查流程")

    checklist = []
    if request.domain_id:
        checklist = get_review_checklist(request.domain_id, request.domain_subtype)
    checklist_dicts = [item.model_dump() if hasattr(item, "model_dump") else item for item in checklist]

    from .graph.builder import build_review_graph

    graph = build_review_graph(domain_id=request.domain_id)
    config = {"configurable": {"thread_id": task_id}}
    initial_state = {
        "task_id": task_id,
        "our_party": request.our_party,
        "material_type": "contract",
        "language": request.language,
        "domain_id": request.domain_id,
        "domain_subtype": request.domain_subtype,
        "documents": [],
        "review_checklist": checklist_dicts,
        "criteria_data": [],
        "criteria_file_path": "",
    }

    graph_run_id = f"run_{task_id}"
    entry = {
        "graph": graph,
        "config": config,
        "initial_state": initial_state,
        "graph_run_id": graph_run_id,
        "last_access_ts": _now_ts(),
        "completed_ts": None,
        "domain_id": request.domain_id,
        "documents": [],
        "our_party": request.our_party,
        "language": request.language,
        "criteria_data": [],
        "criteria_file_path": "",
    }
    _active_graphs[task_id] = entry

    status = "ready"
    if request.auto_start:
        run_task = asyncio.create_task(_run_graph(task_id, graph, initial_state, config))
        entry["run_task"] = run_task
        status = "reviewing"
    else:
        graph.update_state(config, initial_state)

    return StartReviewResponse(task_id=task_id, status=status, graph_run_id=graph_run_id)


@router.post("/review/{task_id}/run")
async def run_review(task_id: str):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    run_task = entry.get("run_task")
    if run_task and not run_task.done():
        return {"task_id": task_id, "status": "already_running"}

    _touch_entry(entry)
    graph = entry["graph"]
    config = entry["config"]
    snapshot = graph.get_state(config)
    state_for_run = snapshot.values or entry.get("initial_state", {})
    entry["run_task"] = asyncio.create_task(_run_graph(task_id, graph, state_for_run, config))
    return {"task_id": task_id, "status": "started"}


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


@router.post("/review/{task_id}/upload")
async def upload_document(
    task_id: str,
    file: UploadFile = File(...),
    role: str = Form("primary"),
    our_party: str = Form(""),
    language: str = Form("zh-CN"),
):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    role = role.strip().lower()
    if role not in ALLOWED_ROLES:
        raise HTTPException(400, f"不支持的文档角色: {role}")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: {ext or 'unknown'}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"文件大小超过 {MAX_UPLOAD_SIZE_MB}MB 限制")

    tmp_dir = entry.get("tmp_dir")
    if not tmp_dir:
        tmp_dir = tempfile.mkdtemp(prefix=f"cr_{task_id}_")
        entry["tmp_dir"] = tmp_dir

    filename = file.filename or f"document{ext}"
    file_path = Path(tmp_dir) / filename
    file_path.write_bytes(content)

    structure = None
    total_clauses = 0
    structure_type = "criteria_table" if role == "criteria" else ""

    if role == "criteria":
        from .criteria_parser import parse_criteria_excel

        criteria = parse_criteria_excel(file_path)
        entry["criteria_data"] = [row.model_dump() for row in criteria]
        entry["criteria_file_path"] = str(file_path)
    else:
        try:
            loaded = load_document(file_path)
        except Exception as exc:
            raise HTTPException(422, f"文档解析失败: {exc}") from exc

        if not loaded.text.strip():
            raise HTTPException(422, "无法从文档中提取文本内容")

        domain_id = entry.get("domain_id")
        parser_config = get_parser_config(domain_id) if domain_id else None
        parser = StructureParser(config=parser_config)
        structure = parser.parse(loaded)
        total_clauses = structure.total_clauses
        structure_type = structure.structure_type

    doc_id = generate_id()
    task_doc = TaskDocument(
        id=doc_id,
        task_id=task_id,
        role=DocumentRole(role),
        filename=filename,
        storage_name=file_path.name,
        structure=structure,
        metadata=(
            {"total_criteria": len(entry.get("criteria_data", [])), "source": "gen3_upload"}
            if role == "criteria"
            else {"text_length": len(loaded.text), "source": "gen3_upload"}
        ),
    )

    docs = entry.get("documents", [])
    filtered_docs = [d for d in docs if _role_to_str((d or {}).get("role", "")).lower() != role]
    filtered_docs.append(task_doc.model_dump(mode="json"))
    entry["documents"] = filtered_docs

    if our_party:
        entry["our_party"] = our_party
    if language:
        entry["language"] = language
    if role == "primary":
        entry["primary_structure"] = structure.model_dump(mode="json")

    graph = entry.get("graph")
    config = entry.get("config")
    if graph and config:
        try:
            graph.update_state(
                config,
                {
                    "documents": entry["documents"],
                    "primary_structure": (
                        entry.get("primary_structure")
                    ),
                    "criteria_data": entry.get("criteria_data", []),
                    "criteria_file_path": entry.get("criteria_file_path", ""),
                    "our_party": entry.get("our_party", ""),
                    "language": entry.get("language", "zh-CN"),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("注入文档到图状态失败: %s", exc)

    _touch_entry(entry)
    return {
        "task_id": task_id,
        "document_id": doc_id,
        "filename": filename,
        "role": role,
        "total_clauses": total_clauses,
        "total_criteria": len(entry.get("criteria_data", [])) if role == "criteria" else None,
        "structure_type": structure_type,
        "message": "文档上传并解析成功",
    }


@router.get("/review/{task_id}/documents")
async def get_documents(task_id: str):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    _touch_entry(entry)
    docs = entry.get("documents", [])
    return {
        "task_id": task_id,
        "documents": [
            {
                "document_id": d.get("id", ""),
                "filename": d.get("filename", ""),
                "role": _role_to_str(d.get("role", "")),
                "total_clauses": (d.get("structure") or {}).get("total_clauses", 0),
                "uploaded_at": d.get("uploaded_at", ""),
            }
            for d in docs
        ],
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


@router.get("/review/{task_id}/result")
async def get_review_result(task_id: str):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    _touch_entry(entry)
    snapshot = entry["graph"].get_state(entry["config"])
    state = snapshot.values
    all_diffs = [_as_dict(d) for d in state.get("all_diffs", [])]
    approved_count = sum(
        1 for d in all_diffs
        if str(d.get("status", "")).lower() == "approved"
        or str(state.get("user_decisions", {}).get(d.get("diff_id"), "")).lower() == "approve"
    )
    rejected_count = sum(
        1 for v in state.get("user_decisions", {}).values()
        if str(v).lower() == "reject"
    )

    return {
        "task_id": task_id,
        "is_complete": bool(state.get("is_complete", False)),
        "summary_notes": state.get("summary_notes", ""),
        "total_risks": len(state.get("all_risks", [])),
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "findings": state.get("findings", {}),
        "all_risks": state.get("all_risks", []),
    }


@router.post("/review/{task_id}/export")
async def export_redline(task_id: str):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    _touch_entry(entry)
    snapshot = entry["graph"].get_state(entry["config"])
    state = snapshot.values
    if not state.get("is_complete"):
        raise HTTPException(400, "审阅尚未完成，无法导出")

    all_diffs = [_as_dict(d) for d in state.get("all_diffs", [])]
    user_decisions = state.get("user_decisions", {}) or {}
    approved_diffs = [
        d for d in all_diffs
        if str(d.get("status", "")).lower() == "approved"
        or str(user_decisions.get(d.get("diff_id"), "")).lower() == "approve"
    ]
    if not approved_diffs and all_diffs:
        # all_diffs 在当前图中通常只保存已批准修改，兼容无 status 场景
        approved_diffs = all_diffs
    if not approved_diffs:
        raise HTTPException(400, "没有已批准的修改建议")

    docs = entry.get("documents", [])
    primary_doc = next(
        (
            _as_dict(d) for d in docs
            if _role_to_str(_as_dict(d).get("role", "")).lower() == "primary"
        ),
        None,
    )
    if not primary_doc:
        raise HTTPException(400, "未找到 primary 文档")

    tmp_dir = entry.get("tmp_dir")
    if not tmp_dir:
        raise HTTPException(400, "未找到原始文档目录")

    source_name = primary_doc.get("storage_name") or primary_doc.get("filename")
    source_path = Path(tmp_dir) / str(source_name or "")
    if source_path.suffix.lower() != ".docx":
        raise HTTPException(400, "仅支持 .docx 格式的红线导出")
    if not source_path.exists():
        raise HTTPException(400, "原始文档不存在，无法导出")

    modifications = [_diff_to_modification(d) for d in approved_diffs]
    result = generate_redline_document(source_path, modifications, filter_confirmed=False)
    if not result.success or not result.document_bytes:
        reason = "；".join(result.skipped_reasons or []) if result else ""
        raise HTTPException(400, f"红线导出失败{f'：{reason}' if reason else ''}")

    filename = f"redline_{task_id}.docx"
    return StreamingResponse(
        BytesIO(result.document_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _collect_all_skills():
    from .graph.builder import _GENERIC_SKILLS

    merged = {}
    for skill in _GENERIC_SKILLS:
        merged[skill.skill_id] = skill
    for plugin in list_domain_plugins():
        for skill in plugin.domain_skills:
            merged[skill.skill_id] = skill
    return list(merged.values())


def _skill_payload(skill, registered_ids: set[str] | None = None):
    domain = getattr(skill, "domain", "*")
    category = getattr(skill, "category", "general")
    status = getattr(skill, "status", "active")
    backend = skill.backend.value
    payload = {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "backend": backend,
        "domain": domain,
        "category": category,
        "status": status,
    }
    if registered_ids is not None:
        payload["is_registered"] = skill.skill_id in registered_ids
    return payload


@router.get("/skills")
async def list_skills(domain_id: str | None = None):
    all_skills = _collect_all_skills()
    if domain_id:
        all_skills = [s for s in all_skills if getattr(s, "domain", "*") in {domain_id, "*"}]

    registered_ids: set[str] = set()
    try:
        from .graph.builder import _create_dispatcher

        dispatcher = _create_dispatcher(domain_id=domain_id)
        if dispatcher:
            registered_ids = set(dispatcher.skill_ids)
    except Exception:  # pragma: no cover - defensive
        registered_ids = set()

    by_domain: Dict[str, int] = {}
    by_backend: Dict[str, int] = {}
    skills = []
    for skill in all_skills:
        payload = _skill_payload(skill, registered_ids=registered_ids)
        skills.append(payload)
        domain = payload["domain"]
        backend = payload["backend"]
        by_domain[domain] = by_domain.get(domain, 0) + 1
        by_backend[backend] = by_backend.get(backend, 0) + 1

    return {
        "skills": skills,
        "total": len(skills),
        "by_domain": by_domain,
        "by_backend": by_backend,
    }


@router.get("/skills/by-domain/{domain_id}")
async def get_skills_by_domain(domain_id: str):
    from .graph.builder import _GENERIC_SKILLS

    skills = get_all_skills_for_domain(domain_id, generic_skills=_GENERIC_SKILLS)
    unique_by_id = {}
    for skill in skills:
        unique_by_id[skill.skill_id] = skill
    merged = list(unique_by_id.values())

    return {
        "domain_id": domain_id,
        "skills": [_skill_payload(skill) for skill in merged],
        "total": len(merged),
    }


@router.get("/skills/{skill_id}")
async def get_skill_detail(skill_id: str):
    target = None
    for skill in _collect_all_skills():
        if skill.skill_id == skill_id:
            target = skill
            break

    if target is None:
        raise HTTPException(404, f"Skill '{skill_id}' 未找到")

    used_by_checklist_items = []
    for plugin in list_domain_plugins():
        for item in plugin.review_checklist:
            if skill_id in item.required_skills:
                used_by_checklist_items.append(item.clause_id)

    registered_ids: set[str] = set()
    try:
        from .graph.builder import _create_dispatcher

        target_domain = getattr(target, "domain", "*")
        dispatcher = _create_dispatcher(domain_id=None if target_domain == "*" else target_domain)
        if dispatcher:
            registered_ids = set(dispatcher.skill_ids)
    except Exception:  # pragma: no cover - defensive
        registered_ids = set()

    payload = _skill_payload(target, registered_ids=registered_ids)
    payload.update(
        {
            "local_handler": target.local_handler,
            "refly_workflow_id": target.refly_workflow_id,
            "used_by_checklist_items": used_by_checklist_items,
        }
    )
    return payload


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
