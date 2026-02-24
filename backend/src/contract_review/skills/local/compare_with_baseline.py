"""Local skill: compare clause text with baseline text."""

from __future__ import annotations

import difflib
import json
import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ._utils import get_clause_text, get_llm_client


class CompareWithBaselineInput(BaseModel):
    clause_id: str
    document_structure: Any
    baseline_text: str = ""
    state_snapshot: Dict[str, Any] = Field(default_factory=dict)


class KeyChange(BaseModel):
    change_type: str = ""
    description: str = ""
    risk_impact: str = "none"


class CompareWithBaselineOutput(BaseModel):
    clause_id: str
    has_baseline: bool = False
    current_text: str = ""
    baseline_text: str = ""
    is_identical: bool = False
    differences_summary: str = ""
    change_significance: str = ""
    key_changes: List[KeyChange] = Field(default_factory=list)
    overall_risk_delta: str = ""
    semantic_summary: str = ""
    llm_used: bool = False


_CHANGE_SIGNIFICANCE = {"material", "minor", "cosmetic"}
_RISK_DELTA = {"increased", "decreased", "neutral"}
_CHANGE_TYPES = {
    "obligation_weakened",
    "obligation_strengthened",
    "time_changed",
    "amount_changed",
    "scope_changed",
    "party_changed",
    "condition_added",
    "condition_removed",
    "wording_only",
}
_RISK_IMPACT = {"high", "medium", "low", "none"}

COMPARE_SYSTEM_PROMPT = (
    "你是合同条款变更分析专家。请对比基线文本和当前文本，分析修改的法律含义。\n"
    "你必须只输出 JSON 对象，不得输出额外文本。\n"
    "字段说明：\n"
    "- change_significance: material（实质性修改）| minor（措辞微调，不影响权责）| cosmetic（格式/标点调整）\n"
    "- key_changes: 数组，每项包含：\n"
    "  - change_type: obligation_weakened|obligation_strengthened|time_changed|amount_changed|"
    "scope_changed|party_changed|condition_added|condition_removed|wording_only\n"
    "  - description: 一句话描述\n"
    "  - risk_impact: high|medium|low|none\n"
    "- overall_risk_delta: increased|decreased|neutral\n"
    "- summary: 一句话总结所有变更的综合影响"
)


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


def _parse_json(raw_text: str) -> Any:
    payload = (raw_text or "").strip()
    if not payload:
        return None

    candidates = [payload]
    block = re.search(r"```(?:json)?\s*(.*?)```", payload, re.DOTALL | re.IGNORECASE)
    if block:
        candidates.append(block.group(1).strip())

    obj_match = re.search(r"\{.*\}", payload, re.DOTALL)
    if obj_match:
        candidates.append(obj_match.group(0).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _build_compare_prompt(baseline: str, current: str, diff_summary: str) -> List[Dict[str, str]]:
    user_msg = (
        f"基线文本：\n{baseline[:2000]}\n\n"
        f"当前文本：\n{current[:2000]}\n\n"
        f"文本差异摘要：\n{diff_summary}"
    )
    return [
        {"role": "system", "content": COMPARE_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]


def _normalize_semantic_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    change_significance = str(payload.get("change_significance", "") or "").strip().lower()
    if change_significance not in _CHANGE_SIGNIFICANCE:
        change_significance = ""

    overall_risk_delta = str(payload.get("overall_risk_delta", "") or "").strip().lower()
    if overall_risk_delta not in _RISK_DELTA:
        overall_risk_delta = ""

    key_changes_payload = payload.get("key_changes", [])
    key_changes: List[KeyChange] = []
    if isinstance(key_changes_payload, list):
        for row in key_changes_payload:
            if not isinstance(row, dict):
                continue
            change_type = str(row.get("change_type", "") or "").strip()
            if change_type not in _CHANGE_TYPES:
                change_type = ""
            risk_impact = str(row.get("risk_impact", "none") or "none").strip().lower()
            if risk_impact not in _RISK_IMPACT:
                risk_impact = "none"
            key_changes.append(
                KeyChange(
                    change_type=change_type,
                    description=str(row.get("description", "") or "").strip(),
                    risk_impact=risk_impact,
                )
            )

    return {
        "change_significance": change_significance,
        "key_changes": key_changes,
        "overall_risk_delta": overall_risk_delta,
        "semantic_summary": str(payload.get("summary", "") or "").strip(),
    }


async def _llm_semantic_analysis(
    baseline: str,
    current: str,
    diff_summary: str,
) -> tuple[Dict[str, Any], bool]:
    llm_client = get_llm_client()
    if llm_client is None:
        return {}, False
    try:
        response = await llm_client.chat(
            _build_compare_prompt(baseline, current, diff_summary),
            max_output_tokens=1000,
        )
    except Exception:  # pragma: no cover - defensive
        return {}, False

    parsed = _parse_json(str(response))
    if not isinstance(parsed, dict):
        return {}, False
    return _normalize_semantic_payload(parsed), True


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
    semantic: Dict[str, Any] = {}
    llm_used = False
    if not is_identical:
        semantic, llm_used = await _llm_semantic_analysis(baseline, current_text, differences)

    return CompareWithBaselineOutput(
        clause_id=input_data.clause_id,
        has_baseline=True,
        current_text=current_text,
        baseline_text=baseline,
        is_identical=is_identical,
        differences_summary=differences,
        change_significance=semantic.get("change_significance", ""),
        key_changes=semantic.get("key_changes", []),
        overall_risk_delta=semantic.get("overall_risk_delta", ""),
        semantic_summary=semantic.get("semantic_summary", ""),
        llm_used=llm_used,
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
