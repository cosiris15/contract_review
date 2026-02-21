"""Load review criteria and match against current clause."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ...criteria_parser import parse_criteria_excel
from ...models import ReviewCriterion
from ._utils import get_clause_text
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


class LoadReviewCriteriaOutput(BaseModel):
    clause_id: str
    matched_criteria: List[MatchedCriterion] = Field(default_factory=list)
    total_matched: int = 0
    has_criteria: bool = False


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
        )

    query = _extract_clause_text(input_data.document_structure, input_data.clause_id)[:300].strip()
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
        )

    scores = _cosine_similarity(vectors[0], vectors[1:])
    if scores.size == 0:
        return LoadReviewCriteriaOutput(
            clause_id=input_data.clause_id,
            matched_criteria=[],
            total_matched=0,
            has_criteria=True,
        )

    ranked = sorted(
        [(float(score), idx) for idx, score in enumerate(scores.tolist())],
        key=lambda x: x[0],
        reverse=True,
    )
    semantic_matches: list[MatchedCriterion] = []
    for score, idx in ranked:
        if score < 0.5:
            continue
        row = criteria_rows[idx]
        semantic_matches.append(
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
        if len(semantic_matches) >= 3:
            break

    return LoadReviewCriteriaOutput(
        clause_id=input_data.clause_id,
        matched_criteria=semantic_matches,
        total_matched=len(semantic_matches),
        has_criteria=True,
    )
