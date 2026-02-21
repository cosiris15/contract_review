"""LangGraph state type definitions."""

from __future__ import annotations

from typing import Dict, List, Optional
from typing_extensions import TypedDict

from ..models import (
    ActionRecommendation,
    ClauseFindings,
    DocumentDiff,
    DocumentStructure,
    ReviewChecklistItem,
    RiskPoint,
    TaskDocument,
)


class ReviewGraphState(TypedDict, total=False):
    task_id: str
    our_party: str
    material_type: str
    language: str
    domain_id: Optional[str]
    domain_subtype: Optional[str]

    documents: List[TaskDocument]
    primary_structure: Optional[DocumentStructure]

    review_checklist: List[ReviewChecklistItem]
    current_clause_index: int

    findings: Dict[str, ClauseFindings]
    global_issues: List[str]

    current_clause_id: Optional[str]
    current_clause_text: Optional[str]
    current_risks: List[RiskPoint]
    current_diffs: List[DocumentDiff]
    current_skill_context: Dict[str, dict]

    validation_result: Optional[str]
    clause_retry_count: int
    max_retries: int

    pending_diffs: List[DocumentDiff]
    user_decisions: Dict[str, str]
    user_feedback: Dict[str, str]

    all_risks: List[RiskPoint]
    all_diffs: List[DocumentDiff]
    all_actions: List[ActionRecommendation]
    summary_notes: str

    error: Optional[str]
    is_complete: bool
