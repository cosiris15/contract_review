import numpy as np
import pytest

from contract_review.skills.fidic.search_er import SearchErInput, search_er


def _build_er_structure():
    return {
        "clauses": [
            {"clause_id": "ER-1", "text": "Contractor shall submit notice for delay events.", "children": []},
            {"clause_id": "ER-2", "text": "Quality control and testing procedures for materials.", "children": []},
            {"clause_id": "ER-3", "text": "Payment certification process and invoice timing.", "children": []},
        ]
    }


@pytest.mark.asyncio
async def test_search_er_basic_match(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.semantic_search._embed_texts",
        lambda _texts: np.array(
            [
                [1.0, 0.0],  # query
                [0.9, 0.1],  # ER-1
                [0.1, 0.9],  # ER-2
                [0.7, 0.2],  # ER-3
            ]
        ),
    )
    result = await search_er(
        SearchErInput(clause_id="20.1", document_structure={}, er_structure=_build_er_structure(), query="notice claim", top_k=2)
    )
    assert result.total_found == 2
    assert result.relevant_sections[0].section_id == "ER-1"
    assert result.relevant_sections[0].relevance_score >= result.relevant_sections[1].relevance_score


@pytest.mark.asyncio
async def test_search_er_no_er_document():
    result = await search_er(
        SearchErInput(clause_id="20.1", document_structure={}, er_structure=None, query="notice", top_k=5)
    )
    assert result.total_found == 0
    assert result.relevant_sections == []


@pytest.mark.asyncio
async def test_search_er_no_match(monkeypatch):
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
    result = await search_er(
        SearchErInput(clause_id="20.1", document_structure={}, er_structure=_build_er_structure(), query="notice", top_k=3)
    )
    assert result.total_found == 0
    assert result.relevant_sections == []


@pytest.mark.asyncio
async def test_search_er_top_k_limit(monkeypatch):
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
    result = await search_er(
        SearchErInput(clause_id="20.1", document_structure={}, er_structure=_build_er_structure(), query="notice", top_k=1)
    )
    assert result.total_found == 1
    assert len(result.relevant_sections) == 1


@pytest.mark.asyncio
async def test_search_er_relevance_threshold(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.semantic_search._embed_texts",
        lambda _texts: np.array(
            [
                [1.0, 0.0],
                [0.31, 0.95],  # about 0.31, pass threshold
                [0.29, 0.95],  # about 0.29, filtered
                [0.8, 0.0],    # pass
            ]
        ),
    )
    result = await search_er(
        SearchErInput(clause_id="20.1", document_structure={}, er_structure=_build_er_structure(), query="notice", top_k=5)
    )
    ids = [row.section_id for row in result.relevant_sections]
    assert "ER-2" not in ids
    assert result.total_found == len(result.relevant_sections)


@pytest.mark.asyncio
async def test_search_er_chinese_text(monkeypatch):
    er = {
        "clauses": [
            {"clause_id": "ER-CN-1", "text": "承包商应在28天内发出索赔通知。", "children": []},
            {"clause_id": "ER-CN-2", "text": "保险保额应覆盖施工风险。", "children": []},
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
    result = await search_er(
        SearchErInput(clause_id="20.1", document_structure={}, er_structure=er, query="索赔通知", top_k=3)
    )
    assert result.total_found >= 1
    assert result.relevant_sections[0].section_id == "ER-CN-1"
