import numpy as np
import pytest

from contract_review.skills.local.semantic_search import (
    SearchReferenceDocInput,
    _collect_sections,
    search_reference_doc,
)


def _reference_structure():
    return {
        "clauses": [
            {"clause_id": "R-1", "text": "Contractor shall submit notice for claim events.", "children": []},
            {"clause_id": "R-2", "text": "Quality control and material testing requirements.", "children": []},
            {"clause_id": "R-3", "text": "Payment certification and invoice timing process.", "children": []},
        ]
    }


@pytest.mark.asyncio
async def test_search_reference_doc_basic_match(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.semantic_search._embed_texts",
        lambda _texts: np.array(
            [
                [1.0, 0.0],  # query
                [0.9, 0.1],  # R-1
                [0.1, 0.9],  # R-2
                [0.7, 0.2],  # R-3
            ]
        ),
    )
    result = await search_reference_doc(
        SearchReferenceDocInput(
            clause_id="20.1",
            document_structure={},
            reference_structure=_reference_structure(),
            query="notice claim",
            top_k=2,
        )
    )
    assert result.total_found == 2
    assert result.matched_sections[0].section_id == "R-1"
    assert result.matched_sections[0].relevance_score >= result.matched_sections[1].relevance_score


@pytest.mark.asyncio
async def test_search_reference_doc_no_reference():
    result = await search_reference_doc(
        SearchReferenceDocInput(
            clause_id="20.1",
            document_structure={},
            reference_structure=None,
            query="notice",
            top_k=5,
        )
    )
    assert result.total_found == 0
    assert result.matched_sections == []


@pytest.mark.asyncio
async def test_search_reference_doc_no_match(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.semantic_search._embed_texts",
        lambda _texts: np.array(
            [
                [1.0, 0.0],
                [0.0, 1.0],
                [0.0, 0.8],
                [0.0, 0.6],
            ]
        ),
    )
    result = await search_reference_doc(
        SearchReferenceDocInput(
            clause_id="20.1",
            document_structure={},
            reference_structure=_reference_structure(),
            query="notice",
            top_k=5,
        )
    )
    assert result.total_found == 0
    assert result.matched_sections == []


@pytest.mark.asyncio
async def test_search_reference_doc_top_k_limit(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.semantic_search._embed_texts",
        lambda _texts: np.array(
            [
                [1.0, 0.0],
                [0.95, 0.0],
                [0.9, 0.0],
                [0.85, 0.0],
            ]
        ),
    )
    result = await search_reference_doc(
        SearchReferenceDocInput(
            clause_id="20.1",
            document_structure={},
            reference_structure=_reference_structure(),
            query="notice",
            top_k=1,
        )
    )
    assert result.total_found == 1
    assert len(result.matched_sections) == 1


@pytest.mark.asyncio
async def test_search_reference_doc_custom_min_score(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.semantic_search._embed_texts",
        lambda _texts: np.array(
            [
                [1.0, 0.0],
                [0.55, 0.8],  # ~0.566
                [0.45, 0.9],  # ~0.447
                [0.7, 0.1],   # ~0.7
            ]
        ),
    )
    result = await search_reference_doc(
        SearchReferenceDocInput(
            clause_id="20.1",
            document_structure={},
            reference_structure=_reference_structure(),
            query="notice",
            top_k=5,
            min_score=0.6,
        )
    )
    assert all(item.relevance_score >= 0.6 for item in result.matched_sections)
    assert result.total_found == len(result.matched_sections)


@pytest.mark.asyncio
async def test_search_reference_doc_chinese_text(monkeypatch):
    reference = {
        "clauses": [
            {"clause_id": "R-CN-1", "text": "承包商应在28天内发出索赔通知。", "children": []},
            {"clause_id": "R-CN-2", "text": "保险保额应覆盖施工风险。", "children": []},
        ]
    }
    monkeypatch.setattr(
        "contract_review.skills.local.semantic_search._embed_texts",
        lambda _texts: np.array(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.2, 0.8],
            ]
        ),
    )
    result = await search_reference_doc(
        SearchReferenceDocInput(
            clause_id="20.1",
            document_structure={},
            reference_structure=reference,
            query="索赔通知",
            top_k=3,
        )
    )
    assert result.total_found >= 1
    assert result.matched_sections[0].section_id == "R-CN-1"


def test_collect_sections_nested():
    structure = {
        "clauses": [
            {
                "clause_id": "R-1",
                "text": "Parent",
                "children": [
                    {"clause_id": "R-1.1", "text": "Child A", "children": []},
                    {"clause_id": "R-1.2", "text": "Child B", "children": []},
                ],
            }
        ]
    }
    sections = _collect_sections(structure)
    ids = [row["section_id"] for row in sections]
    assert ids == ["R-1", "R-1.1", "R-1.2"]
