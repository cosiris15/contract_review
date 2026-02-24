import pytest

from contract_review.skills.fidic.time_bar import CalculateTimeBarInput, calculate


class _MockClient:
    def __init__(self, content: str):
        self._content = content

    async def chat(self, *_args, **_kwargs):
        return self._content


class _FailClient:
    async def chat(self, *_args, **_kwargs):
        raise RuntimeError("llm failed")


def _input(clause_text: str) -> CalculateTimeBarInput:
    return CalculateTimeBarInput(
        clause_id="20.1",
        document_structure={
            "clauses": [{"clause_id": "20.1", "text": clause_text, "children": []}],
        },
    )


@pytest.mark.asyncio
async def test_regex_only_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.fidic.time_bar.get_llm_client",
        lambda: None,
    )

    result = await calculate(_input("The Contractor shall give notice within 28 days after becoming aware."))

    assert result.llm_used is False
    assert result.total_time_bars >= 1
    assert any(item.deadline_days == 28 for item in result.time_bars)
    assert all(item.source == "regex" for item in result.time_bars)


@pytest.mark.asyncio
async def test_llm_enriches_trigger(monkeypatch):
    payload = (
        '{"enrichments":[{"deadline_days":28,"trigger_event":"after becoming aware of the event",'
        '"action_required":"submit notice","consequence":"","strictness_level":"soft_bar",'
        '"risk_assessment":"deadline may be contested"}],"discoveries":[]}'
    )
    monkeypatch.setattr(
        "contract_review.skills.fidic.time_bar.get_llm_client",
        lambda: _MockClient(payload),
    )

    result = await calculate(_input("The Contractor shall submit notice within 28 days."))

    item = next(i for i in result.time_bars if i.deadline_days == 28)
    assert result.llm_used is True
    assert item.source == "regex"
    assert item.trigger_event == "after becoming aware of the event"
    assert item.strictness_level == "soft_bar"


@pytest.mark.asyncio
async def test_llm_does_not_overwrite_regex(monkeypatch):
    payload = (
        '{"enrichments":[{"deadline_days":28,"trigger_event":"after project handover",'
        '"action_required":"submit notice","consequence":"","strictness_level":"advisory",'
        '"risk_assessment":"low"}],"discoveries":[]}'
    )
    monkeypatch.setattr(
        "contract_review.skills.fidic.time_bar.get_llm_client",
        lambda: _MockClient(payload),
    )

    result = await calculate(_input("The Contractor shall submit notice within 28 days after completion."))

    item = next(i for i in result.time_bars if i.deadline_days == 28)
    assert item.trigger_event != "after project handover"
    assert item.trigger_event


@pytest.mark.asyncio
async def test_llm_discovers_text_deadline(monkeypatch):
    payload = (
        '{"enrichments":[],"discoveries":[{"deadline_days":0,"deadline_text":"a reasonable period",'
        '"trigger_event":"after notice","action_required":"provide details",'
        '"consequence":"","strictness_level":"advisory","risk_assessment":"timing uncertainty"}]}'
    )
    monkeypatch.setattr(
        "contract_review.skills.fidic.time_bar.get_llm_client",
        lambda: _MockClient(payload),
    )

    result = await calculate(_input("The Contractor shall provide further particulars within a reasonable period."))

    discovered = next(i for i in result.time_bars if i.deadline_days == 0)
    assert result.llm_used is True
    assert discovered.source == "llm"
    assert discovered.deadline_text == "a reasonable period"


@pytest.mark.asyncio
async def test_strictness_level_classification(monkeypatch):
    payload = (
        '{"enrichments":[{"deadline_days":28,"trigger_event":"","action_required":"",'
        '"consequence":"deemed to have waived","strictness_level":"hard_bar",'
        '"risk_assessment":"high forfeiture risk"}],"discoveries":[]}'
    )
    monkeypatch.setattr(
        "contract_review.skills.fidic.time_bar.get_llm_client",
        lambda: _MockClient(payload),
    )

    result = await calculate(_input("The Contractor shall submit notice within 28 days."))

    item = next(i for i in result.time_bars if i.deadline_days == 28)
    assert item.strictness_level == "hard_bar"
    assert result.has_strict_time_bar is True


@pytest.mark.asyncio
async def test_llm_failure_fallback(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.fidic.time_bar.get_llm_client",
        lambda: _FailClient(),
    )

    result = await calculate(_input("The Contractor shall give notice within 28 days after becoming aware."))

    assert result.llm_used is False
    assert result.total_time_bars >= 1
    assert all(item.source == "regex" for item in result.time_bars)


@pytest.mark.asyncio
async def test_dedup_discoveries(monkeypatch):
    payload = (
        '{"enrichments":[],"discoveries":[{"deadline_days":28,"deadline_text":"within 28 days",'
        '"trigger_event":"after event","action_required":"notify",'
        '"consequence":"","strictness_level":"soft_bar","risk_assessment":""},'
        '{"deadline_days":0,"deadline_text":"a reasonable period",'
        '"trigger_event":"after event","action_required":"provide details",'
        '"consequence":"","strictness_level":"advisory","risk_assessment":""}]}'
    )
    monkeypatch.setattr(
        "contract_review.skills.fidic.time_bar.get_llm_client",
        lambda: _MockClient(payload),
    )

    result = await calculate(_input("The Contractor shall give notice within 28 days after event."))

    llm_with_28 = [i for i in result.time_bars if i.deadline_days == 28 and i.source == "llm"]
    llm_with_0 = [i for i in result.time_bars if i.deadline_days == 0 and i.source == "llm"]
    assert llm_with_28 == []
    assert len(llm_with_0) == 1
