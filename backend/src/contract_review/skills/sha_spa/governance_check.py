"""Input preparation helper for Refly governance check skill."""

from __future__ import annotations

from typing import Any

from ..local._utils import get_clause_text
from ..schema import GenericSkillInput


def prepare_input(clause_id: str, primary_structure: Any, state: dict) -> GenericSkillInput:
    clause_text = get_clause_text(primary_structure, clause_id)
    return GenericSkillInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        state_snapshot={
            "primary_clause": {
                "clause_id": clause_id,
                "text": clause_text,
                "document_type": "SHA",
            },
            "our_party": state.get("our_party", ""),
            "domain_id": state.get("domain_id", ""),
        },
    )
