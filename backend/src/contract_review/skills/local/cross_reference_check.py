"""Local skill: validate clause cross references."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ._utils import ensure_dict


class CrossReferenceCheckInput(BaseModel):
    clause_id: str
    document_structure: Any


class CrossReferenceCheckOutput(BaseModel):
    clause_id: str
    references: List[Dict[str, Any]] = Field(default_factory=list)
    invalid_references: List[Dict[str, Any]] = Field(default_factory=list)
    total_references: int = 0
    total_invalid: int = 0


def _as_ref_dict(ref: Any) -> Dict[str, Any]:
    if isinstance(ref, dict):
        return ref
    if hasattr(ref, "model_dump"):
        return ref.model_dump()
    return {}


async def cross_reference_check(input_data: CrossReferenceCheckInput) -> CrossReferenceCheckOutput:
    structure = ensure_dict(input_data.document_structure)
    raw_refs = structure.get("cross_references", [])
    cross_refs = raw_refs if isinstance(raw_refs, list) else []

    clause_refs = []
    for ref in cross_refs:
        ref_dict = _as_ref_dict(ref)
        if ref_dict.get("source_clause_id") == input_data.clause_id:
            clause_refs.append(ref_dict)

    references: List[Dict[str, Any]] = []
    invalid_references: List[Dict[str, Any]] = []

    for ref in clause_refs:
        entry = {
            "target_clause_id": str(ref.get("target_clause_id", "") or ""),
            "reference_text": str(ref.get("reference_text", "") or ""),
            "is_valid": bool(ref.get("is_valid", False)),
        }
        references.append(entry)
        if not entry["is_valid"]:
            invalid_references.append(entry)

    return CrossReferenceCheckOutput(
        clause_id=input_data.clause_id,
        references=references,
        invalid_references=invalid_references,
        total_references=len(references),
        total_invalid=len(invalid_references),
    )


def prepare_input(clause_id: str, primary_structure: Any, _state: dict) -> CrossReferenceCheckInput:
    return CrossReferenceCheckInput(
        clause_id=clause_id,
        document_structure=primary_structure,
    )
