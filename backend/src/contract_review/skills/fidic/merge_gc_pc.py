"""Local FIDIC skill: merge GC baseline and PC clause text."""

from __future__ import annotations

import difflib
from typing import Any

from pydantic import BaseModel

from ..local._utils import get_clause_text


class MergeGcPcInput(BaseModel):
    clause_id: str
    document_structure: Any
    gc_baseline: str = ""


class MergeGcPcOutput(BaseModel):
    clause_id: str
    gc_text: str
    pc_text: str
    merged_text: str
    modification_type: str
    changes_summary: str


def _normalize(text: str) -> str:
    return " ".join((text or "").split())


def _compute_changes(gc_text: str, pc_text: str) -> str:
    diff = difflib.unified_diff(
        (gc_text or "").splitlines(),
        (pc_text or "").splitlines(),
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


async def merge(input_data: MergeGcPcInput) -> MergeGcPcOutput:
    pc_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    gc_text = input_data.gc_baseline or ""

    if not gc_text:
        modification_type = "no_gc_baseline"
        merged_text = pc_text
        changes_summary = "无 GC 基线文本可供对比"
    elif not pc_text:
        modification_type = "deleted"
        merged_text = ""
        changes_summary = "PC 删除了该条款"
    elif _normalize(pc_text) == _normalize(gc_text):
        modification_type = "unchanged"
        merged_text = gc_text
        changes_summary = "PC 未修改该条款"
    else:
        modification_type = "modified"
        merged_text = pc_text
        changes_summary = _compute_changes(gc_text, pc_text)

    return MergeGcPcOutput(
        clause_id=input_data.clause_id,
        gc_text=gc_text,
        pc_text=pc_text,
        merged_text=merged_text,
        modification_type=modification_type,
        changes_summary=changes_summary,
    )
