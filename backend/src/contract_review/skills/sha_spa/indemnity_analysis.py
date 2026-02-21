"""Local SHA/SPA skill: analyze indemnity clause parameters."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..local._utils import get_clause_text


class IndemnityAnalysisInput(BaseModel):
    clause_id: str
    document_structure: Any


class IndemnityAnalysisOutput(BaseModel):
    clause_id: str
    has_cap: bool = False
    cap_amount: str = ""
    cap_percentage: str = ""
    has_basket: bool = False
    basket_type: str = ""
    basket_amount: str = ""
    has_de_minimis: bool = False
    de_minimis_amount: str = ""
    survival_period: str = ""
    survival_exceptions: List[str] = Field(default_factory=list)
    has_special_indemnity: bool = False
    special_indemnity_items: List[str] = Field(default_factory=list)
    key_excerpts: Dict[str, str] = Field(default_factory=dict)


_CAP_PATTERNS = [
    r"(?i)(?:aggregate|total|maximum)\s+(?:liability|amount).*?(?:shall\s+not\s+exceed|limited\s+to|capped\s+at)\s+(.+?)(?:\.|;)",
    r"(?i)(?:cap|上限|赔偿限额).*?(\$[\d,]+(?:\.\d+)?|\d+%)",
]

_BASKET_PATTERNS = [
    r"(?i)(?:basket|threshold|deductible|免赔额|起赔点).*?((?:USD|EUR|CNY|RMB|GBP)?\s*\$?[\d,]+(?:\.\d+)?|\d+%)",
]

_DE_MINIMIS_PATTERNS = [
    r"(?i)(?:de\s+minimis|minimum\s+claim|最低索赔金额).*?(\$[\d,]+(?:\.\d+)?|\d+%)",
    r"(?i)(?:单项最低|最小索赔).*?(\d+[\d,]*(?:\.\d+)?\s*(?:元|美元|万|%))",
]

_SURVIVAL_PATTERNS = [
    r"(?i)(?:surviv\w+|有效期|时效).*?(\d+\s*(?:months?|years?|个月|年).{0,40})",
]

_SPECIAL_INDEMNITY_KEYWORDS = [
    "tax indemnity",
    "environmental indemnity",
    "specific indemnity",
    "税务赔偿",
    "环境赔偿",
    "特别赔偿",
]


async def analyze_indemnity(input_data: IndemnityAnalysisInput) -> IndemnityAnalysisOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    result = IndemnityAnalysisOutput(clause_id=input_data.clause_id)

    for pattern in _CAP_PATTERNS:
        match = re.search(pattern, clause_text)
        if not match:
            continue
        result.has_cap = True
        cap_text = match.group(1).strip()
        if "%" in cap_text:
            result.cap_percentage = cap_text
        else:
            result.cap_amount = cap_text
        result.key_excerpts["cap"] = match.group(0)[:220]
        break

    for pattern in _BASKET_PATTERNS:
        match = re.search(pattern, clause_text)
        if not match:
            continue
        result.has_basket = True
        result.basket_amount = match.group(1).strip()
        hit_text = match.group(0).lower()
        result.basket_type = "deductible" if "deductible" in hit_text else "tipping"
        result.key_excerpts["basket"] = match.group(0)[:220]
        break

    for pattern in _DE_MINIMIS_PATTERNS:
        match = re.search(pattern, clause_text)
        if not match:
            continue
        result.has_de_minimis = True
        result.de_minimis_amount = match.group(1).strip()
        result.key_excerpts["de_minimis"] = match.group(0)[:220]
        break

    for pattern in _SURVIVAL_PATTERNS:
        match = re.search(pattern, clause_text)
        if not match:
            continue
        result.survival_period = match.group(1).strip()
        result.key_excerpts["survival"] = match.group(0)[:220]
        break

    lowered = clause_text.lower()
    for keyword in _SPECIAL_INDEMNITY_KEYWORDS:
        if keyword.lower() in lowered:
            result.has_special_indemnity = True
            result.special_indemnity_items.append(keyword)

    return result


def prepare_input(clause_id: str, primary_structure: Any, _state: dict) -> IndemnityAnalysisInput:
    return IndemnityAnalysisInput(
        clause_id=clause_id,
        document_structure=primary_structure,
    )
