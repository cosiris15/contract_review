"""Load review criteria and match against current clause."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ...criteria_parser import parse_criteria_excel
from ...models import ReviewCriterion
from ._utils import get_clause_text, get_llm_client
from .semantic_search import _cosine_similarity, _embed_texts


class LoadReviewCriteriaInput(BaseModel):
    clause_id: str
    document_structure: Any
    criteria_file_path: str = ""
    criteria_data: List[dict] = Field(default_factory=list)


class MatchedCriterion(BaseModel):
    criterion_id: str
    clause_ref: str
    review_point: str
    risk_level: str
    baseline_text: str
    suggested_action: str
    match_type: str
    match_score: float = 1.0
    applicable: bool = True
    applicability_reason: str = ""


class LoadReviewCriteriaOutput(BaseModel):
    clause_id: str
    matched_criteria: List[MatchedCriterion] = Field(default_factory=list)
    total_matched: int = 0
    has_criteria: bool = False
    llm_filtered: bool = False


FILTER_SYSTEM_PROMPT = (
    "你是合同审查标准匹配专家。请判断以下审查标准是否适用于当前条款。\n"
    "适用 = 该标准的审查角度与条款内容直接相关，可以用来评估条款的合规性或风险。\n"
    "不适用 = 虽然文字相似，但审查角度与条款内容无关。\n"
    "只返回 JSON 数组，不得输出额外文本。\n"
    "每项：{\"criterion_id\": \"...\", \"applicable\": true/false, \"reason\": \"一句话理由\"}"
)


def _as_criterion(row: Dict[str, Any]) -> ReviewCriterion | None:
    try:
        return ReviewCriterion(**row)
    except Exception:
        return None


def _normalize_clause_ref(ref: str) -> str:
    value = (ref or "").strip()
    value = re.sub(r"^(?:sub-?clause|clause|条款|第)\s*", "", value, flags=re.IGNORECASE)
    value = value.replace("款", "").strip()
    return value.rstrip(".").strip()


def _is_exact_clause_match(current: str, candidate: str) -> bool:
    if not current or not candidate:
        return False
    if current == candidate:
        return True
    return current.startswith(f"{candidate}.") or candidate.startswith(f"{current}.")


def _extract_clause_text(document_structure: Any, clause_id: str) -> str:
    return get_clause_text(document_structure, clause_id) or ""


def _build_semantic_candidates(criteria: List[ReviewCriterion]) -> list[str]:
    return [row.review_point for row in criteria]


def _parse_json_array(raw_text: str) -> Any:
    payload = (raw_text or "").strip()
    if not payload:
        return None

    candidates = [payload]
    block = re.search(r"```(?:json)?\s*(.*?)```", payload, re.DOTALL | re.IGNORECASE)
    if block:
        candidates.append(block.group(1).strip())

    bracket_match = re.search(r"\[.*\]", payload, re.DOTALL)
    if bracket_match:
        candidates.append(bracket_match.group(0).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed
    return None


def _build_filter_prompt(clause_text: str, candidates: List[MatchedCriterion]) -> List[Dict[str, str]]:
    criteria_text = "\n".join(
        f"- criterion_id={criterion.criterion_id}, review_point={criterion.review_point}"
        for criterion in candidates
    )
    user_msg = (
        f"条款文本：\n{clause_text[:2000]}\n\n"
        f"候选审查标准：\n{criteria_text}"
    )
    return [
        {"role": "system", "content": FILTER_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]


async def _llm_filter_applicability(
    clause_text: str,
    candidates: List[MatchedCriterion],
) -> tuple[dict[str, tuple[bool, str]], bool]:
    llm_client = get_llm_client()
    if llm_client is None:
        return {}, False
    try:
        response = await llm_client.chat(
            _build_filter_prompt(clause_text, candidates),
            max_output_tokens=600,
        )
    except Exception:  # pragma: no cover - defensive
        return {}, False

    parsed = _parse_json_array(str(response))
    if not isinstance(parsed, list):
        return {}, False

    mapped: dict[str, tuple[bool, str]] = {}
    for row in parsed:
        if not isinstance(row, dict):
            continue
        criterion_id = str(row.get("criterion_id", "") or "").strip()
        if not criterion_id:
            continue
        raw_applicable = row.get("applicable", True)
        if isinstance(raw_applicable, bool):
            applicable = raw_applicable
        elif isinstance(raw_applicable, str):
            applicable = raw_applicable.strip().lower() in {"true", "1", "yes", "y"}
        else:
            applicable = bool(raw_applicable)
        reason = str(row.get("reason", "") or "")
        mapped[criterion_id] = (applicable, reason)
    return mapped, True


async def load_review_criteria(input_data: LoadReviewCriteriaInput) -> LoadReviewCriteriaOutput:
    criteria_rows: list[ReviewCriterion] = []
    for row in input_data.criteria_data:
        item = _as_criterion(row if isinstance(row, dict) else {})
        if item:
            criteria_rows.append(item)

    if not criteria_rows and input_data.criteria_file_path:
        criteria_rows = parse_criteria_excel(input_data.criteria_file_path)

    if not criteria_rows:
        return LoadReviewCriteriaOutput(
            clause_id=input_data.clause_id,
            has_criteria=False,
            llm_filtered=False,
        )

    current_clause = _normalize_clause_ref(input_data.clause_id)
    matched: list[MatchedCriterion] = []
    for row in criteria_rows:
        candidate = _normalize_clause_ref(row.clause_ref)
        if _is_exact_clause_match(current_clause, candidate):
            matched.append(
                MatchedCriterion(
                    criterion_id=row.criterion_id,
                    clause_ref=row.clause_ref,
                    review_point=row.review_point,
                    risk_level=row.risk_level,
                    baseline_text=row.baseline_text,
                    suggested_action=row.suggested_action,
                    match_type="exact",
                    match_score=1.0,
                )
            )

    if matched:
        return LoadReviewCriteriaOutput(
            clause_id=input_data.clause_id,
            matched_criteria=matched,
            total_matched=len(matched),
            has_criteria=True,
            llm_filtered=False,
        )

    clause_text = _extract_clause_text(input_data.document_structure, input_data.clause_id)
    query = clause_text[:300].strip() if clause_text else ""
    if not query:
        query = input_data.clause_id
    candidates = _build_semantic_candidates(criteria_rows)
    vectors = _embed_texts([query] + candidates)
    if vectors.size == 0 or len(vectors) != len(candidates) + 1:
        return LoadReviewCriteriaOutput(
            clause_id=input_data.clause_id,
            matched_criteria=[],
            total_matched=0,
            has_criteria=True,
            llm_filtered=False,
        )

    scores = _cosine_similarity(vectors[0], vectors[1:])
    if scores.size == 0:
        return LoadReviewCriteriaOutput(
            clause_id=input_data.clause_id,
            matched_criteria=[],
            total_matched=0,
            has_criteria=True,
            llm_filtered=False,
        )

    ranked = sorted(
        [(float(score), idx) for idx, score in enumerate(scores.tolist())],
        key=lambda x: x[0],
        reverse=True,
    )
    semantic_candidates: list[MatchedCriterion] = []
    for score, idx in ranked:
        if score < 0.5:
            continue
        row = criteria_rows[idx]
        semantic_candidates.append(
            MatchedCriterion(
                criterion_id=row.criterion_id,
                clause_ref=row.clause_ref,
                review_point=row.review_point,
                risk_level=row.risk_level,
                baseline_text=row.baseline_text,
                suggested_action=row.suggested_action,
                match_type="semantic",
                match_score=round(score, 4),
            )
        )
        if len(semantic_candidates) >= 5:
            break

    if not semantic_candidates:
        return LoadReviewCriteriaOutput(
            clause_id=input_data.clause_id,
            matched_criteria=[],
            total_matched=0,
            has_criteria=True,
            llm_filtered=False,
        )

    applicability_map, llm_filtered = await _llm_filter_applicability(clause_text or query, semantic_candidates)
    if llm_filtered:
        for candidate in semantic_candidates:
            applicable, reason = applicability_map.get(candidate.criterion_id, (True, ""))
            candidate.applicable = applicable
            candidate.applicability_reason = reason
        semantic_matches = [candidate for candidate in semantic_candidates if candidate.applicable]
    else:
        semantic_matches = semantic_candidates

    semantic_matches = sorted(
        semantic_matches,
        key=lambda item: item.match_score,
        reverse=True,
    )[:3]

    return LoadReviewCriteriaOutput(
        clause_id=input_data.clause_id,
        matched_criteria=semantic_matches,
        total_matched=len(semantic_matches),
        has_criteria=True,
        llm_filtered=llm_filtered,
    )


def prepare_input(clause_id: str, primary_structure: Any, state: dict) -> LoadReviewCriteriaInput:
    return LoadReviewCriteriaInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        criteria_data=state.get("criteria_data", []),
        criteria_file_path=state.get("criteria_file_path", ""),
    )
