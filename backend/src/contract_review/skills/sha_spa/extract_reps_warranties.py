"""Local SHA/SPA skill: extract representations and warranties items."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..local._utils import get_clause_text


class ExtractRepsWarrantiesInput(BaseModel):
    clause_id: str
    document_structure: Any


class RepWarrantyItem(BaseModel):
    rw_id: str
    text: str
    representing_party: str
    has_knowledge_qualifier: bool = False
    has_materiality_qualifier: bool = False
    has_disclosure_exception: bool = False
    subject_matter: str = ""


class ExtractRepsWarrantiesOutput(BaseModel):
    clause_id: str
    reps_warranties: List[RepWarrantyItem] = Field(default_factory=list)
    total_items: int = 0
    seller_reps: int = 0
    buyer_reps: int = 0
    knowledge_qualified_count: int = 0
    materiality_qualified_count: int = 0


_KNOWLEDGE_QUALIFIERS = [
    "to the best of",
    "to the knowledge of",
    "so far as",
    "据其所知",
    "就其所知",
]

_MATERIALITY_QUALIFIERS = [
    "material",
    "in all material respects",
    "materially",
    "重大",
    "实质性",
]

_DISCLOSURE_EXCEPTIONS = [
    "except as disclosed",
    "disclosure",
    "other than as set forth",
    "除披露函",
    "除附件所列",
]

_SUBJECT_KEYWORDS: Dict[str, List[str]] = {
    "financial": ["financial", "accounts", "balance sheet", "财务", "报表"],
    "tax": ["tax", "taxation", "税务", "税收"],
    "legal": ["litigation", "proceeding", "dispute", "诉讼", "争议"],
    "employment": ["employee", "labor", "employment", "员工", "劳动"],
    "ip": ["intellectual property", "patent", "trademark", "知识产权"],
    "compliance": ["compliance", "regulatory", "合规", "监管"],
    "title": ["title", "ownership", "encumbrance", "权属", "产权"],
}


def _has_pattern(text: str, patterns: List[str]) -> bool:
    lowered = (text or "").lower()
    return any(pattern in lowered for pattern in patterns)


def _detect_rep_party(clause_text: str) -> str:
    lowered = clause_text.lower()
    seller_hit = any(token in lowered for token in ["seller represents", "vendor represents", "卖方陈述"])
    buyer_hit = any(token in lowered for token in ["buyer represents", "purchaser represents", "买方陈述"])
    if seller_hit and buyer_hit:
        return "both"
    if buyer_hit:
        return "buyer"
    return "seller"


def _classify_subject(text: str) -> str:
    lowered = text.lower()
    for subject, keywords in _SUBJECT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return subject
    return "other"


async def extract_reps_warranties(
    input_data: ExtractRepsWarrantiesInput,
) -> ExtractRepsWarrantiesOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    if not clause_text.strip():
        return ExtractRepsWarrantiesOutput(clause_id=input_data.clause_id)

    party = _detect_rep_party(clause_text)
    items: List[RepWarrantyItem] = []

    pattern = r"\(([a-z]|\d+)\)\s*(.+?)(?=\([a-z]|\(\d+\)|$)"
    for match in re.finditer(pattern, clause_text, re.IGNORECASE | re.DOTALL):
        text = match.group(0).strip()
        if len(text) < 15:
            continue
        item = RepWarrantyItem(
            rw_id=f"RW-{len(items) + 1}",
            text=text[:500],
            representing_party=party,
            has_knowledge_qualifier=_has_pattern(text, _KNOWLEDGE_QUALIFIERS),
            has_materiality_qualifier=_has_pattern(text, _MATERIALITY_QUALIFIERS),
            has_disclosure_exception=_has_pattern(text, _DISCLOSURE_EXCEPTIONS),
            subject_matter=_classify_subject(text),
        )
        items.append(item)

    return ExtractRepsWarrantiesOutput(
        clause_id=input_data.clause_id,
        reps_warranties=items,
        total_items=len(items),
        seller_reps=sum(1 for item in items if item.representing_party == "seller"),
        buyer_reps=sum(1 for item in items if item.representing_party == "buyer"),
        knowledge_qualified_count=sum(1 for item in items if item.has_knowledge_qualifier),
        materiality_qualified_count=sum(1 for item in items if item.has_materiality_qualifier),
    )


def prepare_input(
    clause_id: str,
    primary_structure: Any,
    _state: dict,
) -> ExtractRepsWarrantiesInput:
    return ExtractRepsWarrantiesInput(
        clause_id=clause_id,
        document_structure=primary_structure,
    )
