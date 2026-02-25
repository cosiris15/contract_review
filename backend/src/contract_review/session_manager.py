"""Review session persistence helpers for Gen3 rehydration."""

from __future__ import annotations

import base64
import copy
import gzip
import json
import logging
from datetime import UTC, datetime
from typing import Any

from .supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

_MAX_GRAPH_STATE_BYTES = 5 * 1024 * 1024
_ACTIVE_STATUSES = {"reviewing", "interrupted"}
_MEMORY_SESSIONS: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _as_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _as_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_as_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_as_jsonable(v) for v in value]
    if isinstance(value, set):
        return [_as_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return _as_jsonable(value.model_dump(mode="json"))
        except Exception:
            return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")


def _prune_state(state: dict[str, Any]) -> dict[str, Any]:
    pruned = copy.deepcopy(state)
    for key in [
        "messages",
        "raw_messages",
        "llm_messages",
        "tool_messages",
        "trace",
        "logs",
        "debug",
    ]:
        pruned.pop(key, None)
    return pruned


def _pack_graph_state(graph_state: dict[str, Any]) -> dict[str, Any]:
    payload = _as_jsonable(graph_state)
    raw = _json_bytes(payload)
    if len(raw) <= _MAX_GRAPH_STATE_BYTES:
        return payload

    pruned = _prune_state(payload)
    pruned_raw = _json_bytes(pruned)
    if len(pruned_raw) <= _MAX_GRAPH_STATE_BYTES:
        return pruned

    compressed = gzip.compress(pruned_raw)
    compressed_payload = {
        "__compressed__": True,
        "encoding": "gzip+base64",
        "payload": base64.b64encode(compressed).decode("ascii"),
    }
    compressed_raw = _json_bytes(compressed_payload)
    if len(compressed_raw) <= _MAX_GRAPH_STATE_BYTES:
        return compressed_payload

    minimal = {
        "__compressed__": False,
        "__truncated__": True,
        "error": "graph_state too large",
        "task_id": payload.get("task_id", ""),
        "current_clause_id": payload.get("current_clause_id", ""),
        "current_clause_index": payload.get("current_clause_index", 0),
        "is_complete": bool(payload.get("is_complete", False)),
        "review_checklist": payload.get("review_checklist", []),
        "documents": payload.get("documents", []),
        "pending_diffs": payload.get("pending_diffs", []),
        "user_decisions": payload.get("user_decisions", {}),
    }
    return minimal


def _unpack_graph_state(graph_state: Any) -> dict[str, Any]:
    if not isinstance(graph_state, dict):
        return {}
    if not graph_state.get("__compressed__"):
        return graph_state
    if graph_state.get("encoding") != "gzip+base64":
        return {}
    payload = graph_state.get("payload")
    if not isinstance(payload, str):
        return {}
    try:
        binary = base64.b64decode(payload.encode("ascii"))
        data = gzip.decompress(binary)
        restored = json.loads(data.decode("utf-8"))
        return restored if isinstance(restored, dict) else {}
    except Exception:
        logger.warning("解压 review session graph_state 失败", exc_info=True)
        return {}


class SessionManager:
    """CRUD helper around review_sessions table."""

    def __init__(self):
        try:
            self.client = get_supabase_client()
        except Exception as exc:
            logger.warning("review_sessions 使用内存后备存储: %s", exc)
            self.client = None

    def save_session(self, task_id: str, entry: dict[str, Any], graph_snapshot: dict[str, Any], status: str | None = None) -> None:
        state = _pack_graph_state(graph_snapshot or {})
        current_clause_index = int((graph_snapshot or {}).get("current_clause_index", 0) or 0)
        review_checklist = (graph_snapshot or {}).get("review_checklist", [])
        total_clauses = len(review_checklist) if isinstance(review_checklist, list) else 0
        is_complete = bool((graph_snapshot or {}).get("is_complete", False))
        is_interrupted = bool((graph_snapshot or {}).get("pending_diffs", []))
        session_status = status or ("completed" if is_complete else ("interrupted" if is_interrupted else "reviewing"))

        row = {
            "task_id": task_id,
            "status": session_status,
            "domain_id": str(entry.get("domain_id") or (graph_snapshot or {}).get("domain_id") or ""),
            "domain_subtype": str((graph_snapshot or {}).get("domain_subtype") or ""),
            "our_party": str(entry.get("our_party") or (graph_snapshot or {}).get("our_party") or ""),
            "language": str(entry.get("language") or (graph_snapshot or {}).get("language") or "zh-CN"),
            "current_clause_index": current_clause_index,
            "current_clause_id": str((graph_snapshot or {}).get("current_clause_id") or ""),
            "total_clauses": total_clauses,
            "is_complete": is_complete,
            "is_interrupted": is_interrupted,
            "error": (graph_snapshot or {}).get("error"),
            "graph_state": state,
            "graph_run_id": str(entry.get("graph_run_id") or ""),
            "updated_at": _now_iso(),
        }
        if session_status == "completed":
            row["completed_at"] = _now_iso()

        if self.client is None:
            existing = _MEMORY_SESSIONS.get(task_id, {})
            merged = {**existing, **row}
            if not merged.get("created_at"):
                merged["created_at"] = _now_iso()
            _MEMORY_SESSIONS[task_id] = merged
            return

        self.client.table("review_sessions").upsert(row).execute()

    def load_session(self, task_id: str) -> dict[str, Any] | None:
        if self.client is None:
            row = _MEMORY_SESSIONS.get(task_id)
            if not row:
                return None
            copied = dict(row)
            copied["graph_state"] = _unpack_graph_state(copied.get("graph_state"))
            return copied

        resp = self.client.table("review_sessions").select("*").eq("task_id", task_id).limit(1).execute()
        rows = resp.data or []
        if not rows:
            return None
        row = rows[0]
        row["graph_state"] = _unpack_graph_state(row.get("graph_state"))
        return row

    def update_session_status(self, task_id: str, status: str, **kwargs: Any) -> None:
        updates = {
            "status": status,
            "updated_at": _now_iso(),
            **kwargs,
        }
        if status == "completed":
            updates["completed_at"] = _now_iso()

        if self.client is None:
            current = _MEMORY_SESSIONS.get(task_id, {"task_id": task_id, "created_at": _now_iso()})
            _MEMORY_SESSIONS[task_id] = {**current, **updates}
            return

        self.client.table("review_sessions").update(updates).eq("task_id", task_id).execute()

    def mark_session_completed(self, task_id: str) -> None:
        self.update_session_status(task_id, "completed", is_complete=True, is_interrupted=False)

    def mark_session_failed(self, task_id: str, error: str) -> None:
        self.update_session_status(task_id, "failed", error=str(error)[:2000])

    def list_active_sessions(self) -> list[dict[str, Any]]:
        if self.client is None:
            rows = [dict(v) for v in _MEMORY_SESSIONS.values() if v.get("status") in _ACTIVE_STATUSES]
            for row in rows:
                row["graph_state"] = _unpack_graph_state(row.get("graph_state"))
            return rows

        resp = self.client.table("review_sessions").select("*").in_("status", list(_ACTIVE_STATUSES)).execute()
        rows = resp.data or []
        for row in rows:
            row["graph_state"] = _unpack_graph_state(row.get("graph_state"))
        return rows


_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


def save_session(task_id: str, entry: dict[str, Any], graph_snapshot: dict[str, Any], status: str | None = None) -> None:
    get_session_manager().save_session(task_id, entry, graph_snapshot, status=status)


def load_session(task_id: str) -> dict[str, Any] | None:
    return get_session_manager().load_session(task_id)


def update_session_status(task_id: str, status: str, **kwargs: Any) -> None:
    get_session_manager().update_session_status(task_id, status, **kwargs)


def mark_session_completed(task_id: str) -> None:
    get_session_manager().mark_session_completed(task_id)


def mark_session_failed(task_id: str, error: str) -> None:
    get_session_manager().mark_session_failed(task_id, error)


def list_active_sessions() -> list[dict[str, Any]]:
    return get_session_manager().list_active_sessions()
