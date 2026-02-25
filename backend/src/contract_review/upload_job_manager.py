"""Upload job persistence helpers for Gen3 async uploads."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .models import generate_id
from .supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

UPLOAD_JOB_STATUSES = {"queued", "running", "succeeded", "failed"}
_MEMORY_JOBS: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class UploadJobManager:
    """CRUD helper around upload_jobs table."""

    def __init__(self):
        try:
            self.client = get_supabase_client()
        except Exception as exc:
            logger.warning("upload_jobs 使用内存后备存储: %s", exc)
            self.client = None

    def create_job(
        self,
        *,
        task_id: str,
        role: str,
        filename: str,
        storage_key: str,
        our_party: str = "",
        language: str = "zh-CN",
    ) -> dict[str, Any]:
        job = {
            "job_id": generate_id(),
            "task_id": task_id,
            "role": role,
            "filename": filename,
            "status": "queued",
            "stage": "uploaded",
            "progress": 0,
            "error_message": None,
            "storage_key": storage_key,
            "result_meta": None,
            "our_party": our_party or "",
            "language": language or "zh-CN",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
        }
        if self.client is None:
            _MEMORY_JOBS[job["job_id"]] = dict(job)
            return dict(job)
        resp = self.client.table("upload_jobs").insert(job).execute()
        return (resp.data or [job])[0]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        if self.client is None:
            row = _MEMORY_JOBS.get(job_id)
            return dict(row) if row else None
        resp = self.client.table("upload_jobs").select("*").eq("job_id", job_id).limit(1).execute()
        rows = resp.data or []
        return rows[0] if rows else None

    def get_jobs_by_task(self, task_id: str) -> list[dict[str, Any]]:
        if self.client is None:
            rows = [dict(v) for v in _MEMORY_JOBS.values() if v.get("task_id") == task_id]
            rows.sort(key=lambda x: str(x.get("created_at", "")))
            return rows
        resp = self.client.table("upload_jobs").select("*").eq("task_id", task_id).order("created_at").execute()
        return resp.data or []

    def get_recoverable_jobs(self) -> list[dict[str, Any]]:
        if self.client is None:
            return [dict(v) for v in _MEMORY_JOBS.values() if v.get("status") in {"queued", "running"}]
        resp = self.client.table("upload_jobs").select("*").in_("status", ["queued", "running"]).execute()
        return resp.data or []

    def mark_job_running(self, job_id: str) -> None:
        current = self.get_job(job_id)
        if not current:
            return
        updates: dict[str, Any] = {
            "status": "running",
            "updated_at": _now_iso(),
            "stage": current.get("stage") or "loading",
        }
        if not current.get("started_at"):
            updates["started_at"] = _now_iso()
        if self.client is None:
            _MEMORY_JOBS[job_id] = {**current, **updates}
            return
        self.client.table("upload_jobs").update(updates).eq("job_id", job_id).execute()

    def mark_job_queued(self, job_id: str) -> None:
        """Reset a failed job to queued status for retry."""
        updates = {
            "status": "queued",
            "stage": "uploaded",
            "progress": 0,
            "error_message": None,
            "result_meta": None,
            "updated_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
        }
        if self.client is None:
            current = _MEMORY_JOBS.get(job_id) or {}
            _MEMORY_JOBS[job_id] = {**current, **updates}
            return
        self.client.table("upload_jobs").update(updates).eq("job_id", job_id).execute()

    def update_job_stage(self, job_id: str, stage: str, progress: int) -> None:
        progress = max(0, min(100, int(progress)))
        updates = {
            "status": "running",
            "stage": stage,
            "progress": progress,
            "updated_at": _now_iso(),
        }
        if self.client is None:
            current = _MEMORY_JOBS.get(job_id) or {}
            _MEMORY_JOBS[job_id] = {**current, **updates}
            return
        self.client.table("upload_jobs").update(updates).eq("job_id", job_id).execute()

    def mark_job_succeeded(self, job_id: str, result_meta: dict[str, Any]) -> None:
        updates = {
            "status": "succeeded",
            "stage": "finished",
            "progress": 100,
            "result_meta": result_meta,
            "error_message": None,
            "updated_at": _now_iso(),
            "finished_at": _now_iso(),
        }
        if self.client is None:
            current = _MEMORY_JOBS.get(job_id) or {}
            _MEMORY_JOBS[job_id] = {**current, **updates}
            return
        self.client.table("upload_jobs").update(updates).eq("job_id", job_id).execute()

    def mark_job_failed(self, job_id: str, error_message: str) -> None:
        updates = {
            "status": "failed",
            "stage": "failed",
            "error_message": str(error_message)[:2000],
            "updated_at": _now_iso(),
            "finished_at": _now_iso(),
        }
        if self.client is None:
            current = _MEMORY_JOBS.get(job_id) or {}
            _MEMORY_JOBS[job_id] = {**current, **updates}
            return
        self.client.table("upload_jobs").update(updates).eq("job_id", job_id).execute()


_manager: UploadJobManager | None = None


def get_upload_job_manager() -> UploadJobManager:
    global _manager
    if _manager is None:
        _manager = UploadJobManager()
    return _manager
