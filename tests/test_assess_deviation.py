import pytest

from contract_review.skills.local.assess_deviation import (
    AssessDeviationInput,
    assess_deviation,
    _extract_json,
)


class _MockClient:
    def __init__(self, content: str):
        self._content = content

    async def chat(self, *_args, **_kwargs):
        return self._content


@pytest.mark.asyncio
async def test_assess_deviation_success_structured_json(monkeypatch):
    payload = """
[
  {
    "criterion_id": "RC-1",
    "review_point": "义务范围不应扩张",
    "deviation_level": "major",
    "risk_level": "high",
    "rationale": "新增兜底义务，范围显著扩大",
    "suggested_action": "删除兜底措辞并恢复GC范围",
    "confidence": 0.86
  }
]
"""
    monkeypatch.setattr(
        "contract_review.skills.local.assess_deviation.get_llm_client",
        lambda: _MockClient(payload),
    )
    result = await assess_deviation(
        AssessDeviationInput(
            clause_id="4.1",
            clause_text="The Contractor shall including but not limited to ...",
            baseline_text="The Contractor shall design and execute the Works.",
            review_criteria=[
                {
                    "criterion_id": "RC-1",
                    "review_point": "义务范围不应扩张",
                    "risk_level": "high",
                    "suggested_action": "恢复原文范围",
                }
            ],
            domain_id="fidic",
        )
    )
    assert result.llm_used is True
    assert result.total_assessed == 1
    assert result.deviations[0].deviation_level == "major"
    assert result.deviations[0].risk_level == "high"


@pytest.mark.asyncio
async def test_assess_deviation_invalid_json_fallback(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.assess_deviation.get_llm_client",
        lambda: _MockClient("not json"),
    )
    result = await assess_deviation(
        AssessDeviationInput(
            clause_id="14.1",
            clause_text="Contract Price shall be fixed",
            review_criteria=[{"criterion_id": "RC-2", "review_point": "价格机制清晰"}],
        )
    )
    assert result.llm_used is False
    assert result.has_criteria is True
    assert result.deviations[0].deviation_level == "unknown"


@pytest.mark.asyncio
async def test_assess_deviation_no_llm_client_fallback(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.assess_deviation.get_llm_client",
        lambda: None,
    )
    result = await assess_deviation(
        AssessDeviationInput(
            clause_id="17.6",
            clause_text="Liability shall be unlimited",
            review_criteria=[{"criterion_id": "RC-3", "review_point": "责任上限需明确"}],
        )
    )
    assert result.llm_used is False
    assert result.total_assessed == 1
    assert result.deviations[0].risk_level == "unknown"


def test_extract_json_from_code_fence():
    raw = """```json
[
  {"criterion_id":"RC-1","deviation_level":"minor","risk_level":"medium"}
]
```"""
    parsed = _extract_json(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["criterion_id"] == "RC-1"
