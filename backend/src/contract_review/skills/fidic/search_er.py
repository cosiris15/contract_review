"""FIDIC ER semantic search wrapper over generic semantic search skill."""

from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, Field

from ..local.semantic_search import SearchReferenceDocInput, search_reference_doc


class SearchErInput(BaseModel):
    clause_id: str
    document_structure: Any
    er_structure: Any = None
    query: str = ""
    top_k: int = 5


class ErSection(BaseModel):
    section_id: str
    text: str
    relevance_score: float


class SearchErOutput(BaseModel):
    clause_id: str
    relevant_sections: List[ErSection] = Field(default_factory=list)
    total_found: int = 0
    search_method: str = "dashscope_embedding"


async def search_er(input_data: SearchErInput) -> SearchErOutput:
    generic_output = await search_reference_doc(
        SearchReferenceDocInput(
            clause_id=input_data.clause_id,
            document_structure=input_data.document_structure,
            reference_structure=input_data.er_structure,
            query=input_data.query,
            top_k=input_data.top_k,
        )
    )
    return SearchErOutput(
        clause_id=generic_output.clause_id,
        relevant_sections=[
            ErSection(
                section_id=section.section_id,
                text=section.text,
                relevance_score=section.relevance_score,
            )
            for section in generic_output.matched_sections
        ],
        total_found=generic_output.total_found,
        search_method=generic_output.search_method,
    )


def prepare_input(clause_id: str, primary_structure: Any, state: dict) -> SearchErInput:
    from ..local._utils import get_clause_text

    clause_text = get_clause_text(primary_structure, clause_id)
    query = " ".join(
        part for part in [clause_text[:500], state.get("material_type", ""), state.get("domain_subtype", "")]
        if part
    )

    er_structure = None
    for doc in state.get("documents", []):
        if isinstance(doc, dict):
            doc_dict = doc
        elif hasattr(doc, "model_dump"):
            doc_dict = doc.model_dump()
        else:
            doc_dict = {}
        role = str(doc_dict.get("role", "") or "").lower()
        filename = str(doc_dict.get("filename", "") or "")
        if role == "reference" and "er" in filename.lower():
            er_structure = doc_dict.get("structure")
            break

    return SearchErInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        er_structure=er_structure,
        query=query or clause_id,
        top_k=5,
    )
