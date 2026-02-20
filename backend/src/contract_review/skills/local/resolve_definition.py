"""Local skill: resolve definition references from document structure."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ._utils import ensure_dict, get_clause_text


class ResolveDefinitionInput(BaseModel):
    clause_id: str
    document_structure: Any
    terms: List[str] = Field(default_factory=list)


class ResolveDefinitionOutput(BaseModel):
    clause_id: str
    definitions_found: Dict[str, str] = Field(default_factory=dict)
    terms_not_found: List[str] = Field(default_factory=list)


def _normalize_term(term: str) -> str:
    value = term.strip().strip('"').strip("'")
    value = value.replace("\u201c", "").replace("\u201d", "")
    return value.lower()


def _extract_quoted_terms(text: str) -> List[str]:
    patterns = [r'"([^"]+)"', r"'([^']+)'", r"\u201c([^\u201d]+)\u201d"]
    terms: List[str] = []
    for pattern in patterns:
        terms.extend([m.strip() for m in re.findall(pattern, text or "") if m.strip()])

    unique: List[str] = []
    seen = set()
    for term in terms:
        key = _normalize_term(term)
        if key and key not in seen:
            seen.add(key)
            unique.append(term)
    return unique


def _find_term(term: str, definitions: Dict[str, str]) -> str | None:
    exact = definitions.get(term)
    if exact is not None:
        return exact

    target = _normalize_term(term)
    for key, value in definitions.items():
        if _normalize_term(str(key)) == target:
            return str(value)
    return None


async def resolve_definition(input_data: ResolveDefinitionInput) -> ResolveDefinitionOutput:
    structure = ensure_dict(input_data.document_structure)
    raw_definitions = structure.get("definitions", {})
    definitions = raw_definitions if isinstance(raw_definitions, dict) else {}

    terms = input_data.terms
    if not terms:
        terms = _extract_quoted_terms(get_clause_text(structure, input_data.clause_id))

    found: Dict[str, str] = {}
    not_found: List[str] = []
    for term in terms:
        matched = _find_term(term, definitions)
        if matched is not None:
            found[term] = matched
        else:
            not_found.append(term)

    return ResolveDefinitionOutput(
        clause_id=input_data.clause_id,
        definitions_found=found,
        terms_not_found=not_found,
    )
