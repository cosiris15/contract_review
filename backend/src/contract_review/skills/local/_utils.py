"""Shared helpers for local skills."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ...config import get_settings
from ...llm_client import LLMClient

logger = logging.getLogger(__name__)

_llm_client: LLMClient | None = None
_llm_init_warned = False


def ensure_dict(structure: Any) -> Dict[str, Any]:
    if isinstance(structure, dict):
        return structure
    if hasattr(structure, "model_dump"):
        return structure.model_dump()
    return {}


def _search_clauses(clauses: List[Any], target_id: str) -> str:
    for clause in clauses:
        if not isinstance(clause, dict):
            if hasattr(clause, "model_dump"):
                clause = clause.model_dump()
            else:
                continue

        clause_id = str(clause.get("clause_id", "") or "")
        if clause_id == target_id:
            return str(clause.get("text", "") or "")

        children = clause.get("children", [])
        if isinstance(children, list) and children:
            found = _search_clauses(children, target_id)
            if found:
                return found

        if clause_id and target_id and (
            clause_id.startswith(f"{target_id}.") or target_id.startswith(f"{clause_id}.")
        ):
            text = str(clause.get("text", "") or "")
            if text:
                return text
    return ""


def get_clause_text(structure: Any, clause_id: str) -> str:
    payload = ensure_dict(structure)
    clauses = payload.get("clauses", [])
    if not isinstance(clauses, list):
        return ""
    return _search_clauses(clauses, clause_id)


def get_llm_client() -> LLMClient | None:
    global _llm_client, _llm_init_warned
    if _llm_client is not None:
        return _llm_client

    try:
        settings = get_settings()
        _llm_client = LLMClient(settings.llm)
    except Exception as exc:  # pragma: no cover - defensive
        if not _llm_init_warned:
            logger.warning("无法初始化 LLMClient，assess_deviation 将使用 fallback: %s", exc)
            _llm_init_warned = True
        return None
    return _llm_client
