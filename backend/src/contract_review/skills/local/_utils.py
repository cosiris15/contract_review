"""Shared helpers for local skills."""

from __future__ import annotations

from typing import Any, Dict, List


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
