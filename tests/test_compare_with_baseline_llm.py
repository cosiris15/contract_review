import pytest

from contract_review.skills.local.compare_with_baseline import (
    CompareWithBaselineInput,
    compare_with_baseline,
)


class _MockClient:
    def __init__(self, content: str):
        self._content = content

    async def chat(self, *_args, **_kwargs):
        return self._content


class _FailClient:
    async def chat(self, *_args, **_kwargs):
        raise RuntimeError("llm failed")


def _input(current_text: str, baseline_text: str) -> CompareWithBaselineInput:
    return CompareWithBaselineInput(
        clause_id="14.1",
        document_structure={"clauses": [{"clause_id": "14.1", "text": current_text, "children": []}]},
        baseline_text=baseline_text,
    )


@pytest.mark.asyncio
async def test_identical_text_no_llm(monkeypatch):
    def _should_not_call_llm():
        raise AssertionError("LLM should not be called for identical text")

    monkeypatch.setattr(
        "contract_review.skills.local.compare_with_baseline.get_llm_client",
        _should_not_call_llm,
    )

    result = await compare_with_baseline(_input("The Contract Price is fixed.", "The Contract Price is fixed."))

    assert result.is_identical is True
    assert result.llm_used is False
    assert result.change_significance == ""
    assert result.key_changes == []
    assert result.overall_risk_delta == ""
    assert result.semantic_summary == ""


@pytest.mark.asyncio
async def test_shall_to_may_material(monkeypatch):
    payload = (
        '{"change_significance":"material","key_changes":[{"change_type":"obligation_weakened",'
        '"description":"shall 改为 may", "risk_impact":"high"}],'
        '"overall_risk_delta":"increased","summary":"义务强度下降"}'
    )
    monkeypatch.setattr(
        "contract_review.skills.local.compare_with_baseline.get_llm_client",
        lambda: _MockClient(payload),
    )

    result = await compare_with_baseline(
        _input(
            "The Contractor may complete the works within 28 days.",
            "The Contractor shall complete the works within 28 days.",
        )
    )

    assert result.is_identical is False
    assert result.llm_used is True
    assert result.change_significance == "material"
    assert result.overall_risk_delta == "increased"
    assert result.key_changes[0].change_type == "obligation_weakened"


@pytest.mark.asyncio
async def test_cosmetic_change(monkeypatch):
    payload = (
        '{"change_significance":"cosmetic","key_changes":[{"change_type":"wording_only",'
        '"description":"标点调整", "risk_impact":"none"}],'
        '"overall_risk_delta":"neutral","summary":"仅格式调整"}'
    )
    monkeypatch.setattr(
        "contract_review.skills.local.compare_with_baseline.get_llm_client",
        lambda: _MockClient(payload),
    )

    result = await compare_with_baseline(
        _input(
            "The Contract Price is fixed, and final.",
            "The Contract Price is fixed and final.",
        )
    )

    assert result.change_significance == "cosmetic"
    assert result.key_changes[0].risk_impact == "none"


@pytest.mark.asyncio
async def test_time_reduction(monkeypatch):
    payload = (
        '{"change_significance":"material","key_changes":[{"change_type":"time_changed",'
        '"description":"时限从28天缩短到14天", "risk_impact":"high"}],'
        '"overall_risk_delta":"increased","summary":"履约压力增加"}'
    )
    monkeypatch.setattr(
        "contract_review.skills.local.compare_with_baseline.get_llm_client",
        lambda: _MockClient(payload),
    )

    result = await compare_with_baseline(
        _input("The notice shall be submitted within 14 days.", "The notice shall be submitted within 28 days.")
    )

    assert result.key_changes
    assert result.key_changes[0].change_type == "time_changed"
    assert result.key_changes[0].risk_impact == "high"


@pytest.mark.asyncio
async def test_llm_unavailable_fallback(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.compare_with_baseline.get_llm_client",
        lambda: None,
    )

    result = await compare_with_baseline(
        _input("The Contract Price is adjustable.", "The Contract Price is fixed.")
    )

    assert result.is_identical is False
    assert result.differences_summary
    assert result.llm_used is False
    assert result.change_significance == ""
    assert result.key_changes == []
    assert result.overall_risk_delta == ""
    assert result.semantic_summary == ""


@pytest.mark.asyncio
async def test_llm_failure_fallback(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.compare_with_baseline.get_llm_client",
        lambda: _FailClient(),
    )

    result = await compare_with_baseline(
        _input("The Contract Price is adjustable.", "The Contract Price is fixed.")
    )

    assert result.differences_summary
    assert result.llm_used is False
    assert result.change_significance == ""
    assert result.key_changes == []
    assert result.overall_risk_delta == ""
    assert result.semantic_summary == ""


@pytest.mark.asyncio
async def test_no_baseline(monkeypatch):
    def _should_not_call_llm():
        raise AssertionError("LLM should not be called when baseline is missing")

    monkeypatch.setattr(
        "contract_review.skills.local.compare_with_baseline.get_llm_client",
        _should_not_call_llm,
    )

    result = await compare_with_baseline(_input("Current text only", ""))

    assert result.has_baseline is False
    assert result.llm_used is False


@pytest.mark.asyncio
async def test_semantic_summary_populated(monkeypatch):
    payload = (
        '{"change_significance":"minor","key_changes":[{"change_type":"wording_only",'
        '"description":"措辞优化", "risk_impact":"low"}],'
        '"overall_risk_delta":"neutral","summary":"措辞更清晰，权责基本不变"}'
    )
    monkeypatch.setattr(
        "contract_review.skills.local.compare_with_baseline.get_llm_client",
        lambda: _MockClient(payload),
    )

    result = await compare_with_baseline(_input("The Contractor shall promptly notify.", "The Contractor shall notify."))

    assert result.llm_used is True
    assert result.semantic_summary == "措辞更清晰，权责基本不变"
