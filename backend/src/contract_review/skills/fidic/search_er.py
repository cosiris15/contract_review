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
