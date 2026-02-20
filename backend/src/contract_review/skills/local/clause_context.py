"""Local skill: get clause context."""

from __future__ import annotations

from pydantic import BaseModel

from ...models import DocumentStructure
from ...structure_parser import StructureParser


class ClauseContextInput(BaseModel):
    clause_id: str
    document_structure: DocumentStructure


class ClauseContextOutput(BaseModel):
    clause_id: str
    found: bool = False
    context_text: str = ""
    title: str = ""


async def get_clause_context(input_data: ClauseContextInput) -> ClauseContextOutput:
    parser = StructureParser()
    text = parser.get_clause_context(input_data.document_structure, input_data.clause_id)
    if text is None:
        return ClauseContextOutput(clause_id=input_data.clause_id, found=False)

    node = parser._find_clause(input_data.document_structure.clauses, input_data.clause_id)
    title = node.title if node else ""
    return ClauseContextOutput(
        clause_id=input_data.clause_id,
        found=True,
        context_text=text,
        title=title,
    )
