from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from contract_review.graph import builder


@dataclass
class _SkillResult:
    success: bool
    data: dict
    error: str = ""


class _FakeDispatcher:
    def __init__(self, registered: list[str], payloads: dict[str, dict] | None = None):
        self.skill_ids = set(registered)
        self.calls: list[str] = []
        self._payloads = payloads or {}

    async def prepare_and_call(self, skill_id, clause_id, primary_structure, state, llm_arguments=None):
        _ = clause_id, primary_structure, state, llm_arguments
        self.calls.append(skill_id)
        payload = self._payloads.get(skill_id, {"ok": True, "skill_id": skill_id})
        return _SkillResult(success=True, data=payload)


def _primary_structure() -> dict:
    return {
        "clauses": [
            {"clause_id": "4.1", "text": "Clause text 4.1", "children": []},
        ]
    }


@pytest.mark.asyncio
async def test_gen3_fallback_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: None)

    dispatcher = _FakeDispatcher(
        ["get_clause_context"],
        payloads={"get_clause_context": {"context_text": "ctx from deterministic"}},
    )
    result = await builder._analyze_gen3(
        state={},
        dispatcher=dispatcher,
        clause_id="4.1",
        clause_name="Clause 4.1",
        description="desc",
        priority="high",
        our_party="A",
        language="zh-CN",
        primary_structure=_primary_structure(),
        required_skills=["get_clause_context"],
    )

    assert result["current_skill_context"]
    assert "get_clause_context" in result["current_skill_context"]
    assert result["current_clause_text"] == "ctx from deterministic"


@pytest.mark.asyncio
async def test_gen3_fallback_when_react_fails(monkeypatch):
    class _LLM:
        async def chat_with_tools(self, *args, **kwargs):
            _ = args, kwargs
            return "[]", None

    async def _raise_react(**kwargs):
        _ = kwargs
        raise RuntimeError("react down")

    monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _LLM())
    monkeypatch.setattr(
        "contract_review.graph.builder.get_settings",
        lambda: SimpleNamespace(react_max_iterations=3, react_temperature=0.1),
    )
    monkeypatch.setattr("contract_review.graph.builder._run_react_branch", _raise_react)

    dispatcher = _FakeDispatcher(["extract_financial_terms"])
    result = await builder._analyze_gen3(
        state={},
        dispatcher=dispatcher,
        clause_id="4.1",
        clause_name="Clause 4.1",
        description="desc",
        priority="high",
        our_party="A",
        language="zh-CN",
        primary_structure=_primary_structure(),
        required_skills=["extract_financial_terms"],
    )

    assert "extract_financial_terms" in result["current_skill_context"]
    assert result["current_risks"] == []


@pytest.mark.asyncio
async def test_gen3_fallback_when_react_returns_empty_context(monkeypatch):
    class _LLM:
        async def chat_with_tools(self, *args, **kwargs):
            _ = args, kwargs
            return "[]", None

    async def _empty_react(**kwargs):
        _ = kwargs
        return {
            "current_clause_id": "4.1",
            "current_clause_text": "",
            "current_risks": [],
            "current_diffs": [],
            "current_skill_context": {},
            "agent_messages": [],
            "clause_retry_count": 0,
        }

    monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _LLM())
    monkeypatch.setattr(
        "contract_review.graph.builder.get_settings",
        lambda: SimpleNamespace(react_max_iterations=3, react_temperature=0.1),
    )
    monkeypatch.setattr("contract_review.graph.builder._run_react_branch", _empty_react)

    dispatcher = _FakeDispatcher(["cross_reference_check"])
    result = await builder._analyze_gen3(
        state={},
        dispatcher=dispatcher,
        clause_id="4.1",
        clause_name="Clause 4.1",
        description="desc",
        priority="high",
        our_party="A",
        language="zh-CN",
        primary_structure=_primary_structure(),
        required_skills=["cross_reference_check"],
    )

    assert "cross_reference_check" in result["current_skill_context"]


@pytest.mark.asyncio
async def test_gen3_normal_path_when_llm_available(monkeypatch):
    class _LLM:
        async def chat_with_tools(self, *args, **kwargs):
            _ = args, kwargs
            return "[]", None

    async def _react_ok(**kwargs):
        _ = kwargs
        return {
            "current_clause_id": "4.1",
            "current_clause_text": "from react",
            "current_risks": [{"id": "r1"}],
            "current_diffs": [],
            "current_skill_context": {"get_clause_context": {"context_text": "from react"}},
            "agent_messages": [],
            "clause_retry_count": 0,
        }

    called = {"fallback": False}

    async def _fallback(**kwargs):
        _ = kwargs
        called["fallback"] = True
        return {"current_skill_context": {"fallback": True}}

    monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _LLM())
    monkeypatch.setattr(
        "contract_review.graph.builder.get_settings",
        lambda: SimpleNamespace(react_max_iterations=3, react_temperature=0.1),
    )
    monkeypatch.setattr("contract_review.graph.builder._run_react_branch", _react_ok)
    monkeypatch.setattr("contract_review.graph.builder._deterministic_skill_fallback", _fallback)

    dispatcher = _FakeDispatcher(["get_clause_context"])
    result = await builder._analyze_gen3(
        state={},
        dispatcher=dispatcher,
        clause_id="4.1",
        clause_name="Clause 4.1",
        description="desc",
        priority="high",
        our_party="A",
        language="zh-CN",
        primary_structure=_primary_structure(),
        required_skills=["get_clause_context"],
    )

    assert result["current_clause_text"] == "from react"
    assert called["fallback"] is False


@pytest.mark.asyncio
async def test_deterministic_fallback_calls_all_required_skills():
    dispatcher = _FakeDispatcher(["s1", "s2"])
    result = await builder._deterministic_skill_fallback(
        state={},
        dispatcher=dispatcher,
        clause_id="4.1",
        clause_name="Clause 4.1",
        description="desc",
        primary_structure=_primary_structure(),
        required_skills=["s1", "s2"],
    )

    assert dispatcher.calls == ["s1", "s2"]
    assert set(result["current_skill_context"].keys()) == {"s1", "s2"}


@pytest.mark.asyncio
async def test_deterministic_fallback_skips_unregistered_skills():
    dispatcher = _FakeDispatcher(["s1", "s2"])
    result = await builder._deterministic_skill_fallback(
        state={},
        dispatcher=dispatcher,
        clause_id="4.1",
        clause_name="Clause 4.1",
        description="desc",
        primary_structure=_primary_structure(),
        required_skills=["s1", "missing", "s2"],
    )

    assert dispatcher.calls == ["s1", "s2"]
    assert "missing" not in result["current_skill_context"]
