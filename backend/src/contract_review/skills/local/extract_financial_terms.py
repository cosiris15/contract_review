"""Local skill: extract financial terms from clause text."""

from __future__ import annotations

import re
from typing import Any, List

from pydantic import BaseModel, Field

from ._utils import get_clause_text


class ExtractFinancialTermsInput(BaseModel):
    clause_id: str
    document_structure: Any


class FinancialTerm(BaseModel):
    term_type: str
    value: str
    context: str


class ExtractFinancialTermsOutput(BaseModel):
    clause_id: str
    terms: List[FinancialTerm] = Field(default_factory=list)
    total_terms: int = 0


_FINANCIAL_PATTERNS: List[tuple[str, str]] = [
    (r"(\d+(?:\.\d+)?)\s*[%％]", "percentage"),
    (r"(?:USD|EUR|CNY|RMB|GBP|\$|€|£|¥)\s*[\d,]+(?:\.\d+)?", "amount"),
    (r"[\d,]+(?:\.\d+)?\s*(?:万元|亿元|元|美元|欧元|英镑)", "amount"),
    (r"\d+\s*(?:天|日|个月|月|年|days?|months?|years?|weeks?|周)", "duration"),
    (r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?", "date"),
]


async def extract_financial_terms(input_data: ExtractFinancialTermsInput) -> ExtractFinancialTermsOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)

    terms: List[FinancialTerm] = []
    for pattern, term_type in _FINANCIAL_PATTERNS:
        for match in re.finditer(pattern, clause_text):
            start = max(0, match.start() - 30)
            end = min(len(clause_text), match.end() + 30)
            context = clause_text[start:end].strip()
            terms.append(
                FinancialTerm(
                    term_type=term_type,
                    value=match.group(0).strip(),
                    context=context,
                )
            )

    return ExtractFinancialTermsOutput(
        clause_id=input_data.clause_id,
        terms=terms,
        total_terms=len(terms),
    )
