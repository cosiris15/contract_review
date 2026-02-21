"""Local skill: compare clause text with baseline text."""

from __future__ import annotations

import difflib
from typing import Any, Dict

from pydantic import BaseModel, Field

from ._utils import get_clause_text


class CompareWithBaselineInput(BaseModel):
    clause_id: str
    document_structure: Any
    baseline_text: str = ""
    state_snapshot: Dict[str, Any] = Field(default_factory=dict)


class CompareWithBaselineOutput(BaseModel):
    clause_id: str
    has_baseline: bool = False
    current_text: str = ""
    baseline_text: str = ""
    is_identical: bool = False
    differences_summary: str = ""


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def _compute_diff_summary(baseline: str, current: str) -> str:
    diff = difflib.unified_diff(
        (baseline or "").splitlines(),
        (current or "").splitlines(),
        lineterm="",
        n=1,
    )

    added = []
    removed = []
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            value = line[1:].strip()
            if value:
                added.append(value)
        elif line.startswith("-") and not line.startswith("---"):
            value = line[1:].strip()
            if value:
                removed.append(value)

    parts = []
    if removed:
        parts.append(f"删除内容：{'; '.join(removed[:5])}")
    if added:
        parts.append(f"新增内容：{'; '.join(added[:5])}")
    if not parts:
        parts.append("文本存在细微差异")
    return "\n".join(parts)


async def compare_with_baseline(input_data: CompareWithBaselineInput) -> CompareWithBaselineOutput:
    current_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    baseline = input_data.baseline_text or ""

    if not baseline:
        return CompareWithBaselineOutput(
            clause_id=input_data.clause_id,
            has_baseline=False,
            current_text=current_text,
        )

    is_identical = _normalize_text(current_text) == _normalize_text(baseline)
    differences = "" if is_identical else _compute_diff_summary(baseline, current_text)

    return CompareWithBaselineOutput(
        clause_id=input_data.clause_id,
        has_baseline=True,
        current_text=current_text,
        baseline_text=baseline,
        is_identical=is_identical,
        differences_summary=differences,
    )


def prepare_input(clause_id: str, primary_structure: Any, state: dict) -> CompareWithBaselineInput:
    from ...plugins.registry import get_baseline_text

    domain_id = state.get("domain_id", "")
    baseline_text = get_baseline_text(domain_id, clause_id) or ""
    return CompareWithBaselineInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        baseline_text=baseline_text,
        state_snapshot={
            "our_party": state.get("our_party", ""),
            "language": state.get("language", "en"),
            "domain_id": domain_id,
        },
    )
