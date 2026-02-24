import numpy as np
import pytest

from contract_review.skills.local.load_review_criteria import (
    LoadReviewCriteriaInput,
    load_review_criteria,
)


class _MockClient:
    def __init__(self, content: str):
        self._content = content

    async def chat(self, *_args, **_kwargs):
        return self._content


class _FailClient:
    async def chat(self, *_args, **_kwargs):
        raise RuntimeError("llm failed")


def _criteria_rows() -> list[dict]:
    return [
        {
            "criterion_id": f"RC-{i}",
            "clause_ref": f"9.{i}",
            "review_point": f"付款条款审查要点 {i}",
            "risk_level": "high" if i <= 2 else "medium",
            "baseline_text": f"baseline {i}",
            "suggested_action": f"action {i}",
        }
        for i in range(1, 7)
    ]


def _mock_embeddings(_texts):
    return np.array(
        [
            [1.0, 0.0],
            [0.99, 0.01],
            [0.95, 0.05],
            [0.9, 0.1],
            [0.85, 0.15],
            [0.8, 0.2],
            [0.2, 0.98],
        ]
    )


def _input(clause_id: str = "8.8", text: str = "付款期限应明确") -> LoadReviewCriteriaInput:
    return LoadReviewCriteriaInput(
        clause_id=clause_id,
        document_structure={"clauses": [{"clause_id": clause_id, "text": text, "children": []}]},
        criteria_data=_criteria_rows(),
    )


@pytest.mark.asyncio
async def test_exact_match_bypasses_llm(monkeypatch):
    criteria = _criteria_rows()
    criteria[0]["clause_ref"] = "4.1"

    def _should_not_call_llm():
        raise AssertionError("LLM should not be called for exact matches")

    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria.get_llm_client",
        _should_not_call_llm,
    )

    result = await load_review_criteria(
        LoadReviewCriteriaInput(
            clause_id="4.1",
            document_structure={"clauses": [{"clause_id": "4.1", "text": "义务范围", "children": []}]},
            criteria_data=criteria,
        )
    )

    assert result.total_matched >= 1
    assert result.llm_filtered is False
    assert all(item.match_type == "exact" for item in result.matched_criteria)
    assert all(item.applicable is True for item in result.matched_criteria)


@pytest.mark.asyncio
async def test_llm_filters_inapplicable(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria._embed_texts",
        _mock_embeddings,
    )
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria.get_llm_client",
        lambda: _MockClient(
            '[{"criterion_id":"RC-4","applicable":false,"reason":"角度不相关"},'
            '{"criterion_id":"RC-5","applicable":false,"reason":"角度不相关"}]'
        ),
    )

    result = await load_review_criteria(_input())

    assert result.llm_filtered is True
    assert result.total_matched == 3
    ids = [item.criterion_id for item in result.matched_criteria]
    assert ids == ["RC-1", "RC-2", "RC-3"]


@pytest.mark.asyncio
async def test_llm_reason_populated(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria._embed_texts",
        _mock_embeddings,
    )
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria.get_llm_client",
        lambda: _MockClient(
            '[{"criterion_id":"RC-1","applicable":true,'
            '"reason":"该标准直接约束本条款付款期限"}]'
        ),
    )

    result = await load_review_criteria(_input())

    assert result.llm_filtered is True
    rc1 = next(item for item in result.matched_criteria if item.criterion_id == "RC-1")
    assert rc1.applicability_reason == "该标准直接约束本条款付款期限"


@pytest.mark.asyncio
async def test_llm_unavailable_keeps_all(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria._embed_texts",
        _mock_embeddings,
    )
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria.get_llm_client",
        lambda: None,
    )

    result = await load_review_criteria(_input())

    assert result.llm_filtered is False
    assert result.total_matched == 3
    assert [item.criterion_id for item in result.matched_criteria] == ["RC-1", "RC-2", "RC-3"]


@pytest.mark.asyncio
async def test_llm_failure_keeps_all(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria._embed_texts",
        _mock_embeddings,
    )
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria.get_llm_client",
        lambda: _FailClient(),
    )

    result = await load_review_criteria(_input())

    assert result.llm_filtered is False
    assert result.total_matched == 3
    assert [item.criterion_id for item in result.matched_criteria] == ["RC-1", "RC-2", "RC-3"]


@pytest.mark.asyncio
async def test_all_filtered_out(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria._embed_texts",
        _mock_embeddings,
    )
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria.get_llm_client",
        lambda: _MockClient(
            '[{"criterion_id":"RC-1","applicable":false,"reason":"不适用"},'
            '{"criterion_id":"RC-2","applicable":false,"reason":"不适用"},'
            '{"criterion_id":"RC-3","applicable":false,"reason":"不适用"},'
            '{"criterion_id":"RC-4","applicable":false,"reason":"不适用"},'
            '{"criterion_id":"RC-5","applicable":false,"reason":"不适用"}]'
        ),
    )

    result = await load_review_criteria(_input())

    assert result.llm_filtered is True
    assert result.total_matched == 0
    assert result.matched_criteria == []


@pytest.mark.asyncio
async def test_missing_criterion_id_defaults_true(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria._embed_texts",
        _mock_embeddings,
    )
    monkeypatch.setattr(
        "contract_review.skills.local.load_review_criteria.get_llm_client",
        lambda: _MockClient(
            '[{"criterion_id":"RC-1","applicable":false,"reason":"不适用"}]'
        ),
    )

    result = await load_review_criteria(_input())

    assert result.llm_filtered is True
    ids = [item.criterion_id for item in result.matched_criteria]
    assert ids == ["RC-2", "RC-3", "RC-4"]
    rc2 = next(item for item in result.matched_criteria if item.criterion_id == "RC-2")
    assert rc2.applicable is True
    assert rc2.applicability_reason == ""
