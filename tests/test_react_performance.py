from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from contract_review.config import LLMSettings, Settings
from contract_review.graph import builder
from contract_review.graph.prompts import build_react_agent_messages
from contract_review.graph.react_agent import react_agent_loop
from contract_review.skills.schema import SkillResult


def _primary_structure() -> dict:
    return {"clauses": [{"clause_id": "4.1", "text": "Clause 4.1 text", "children": []}]}


@pytest.mark.asyncio
async def test_react_clause_timeout_triggers_fallback(monkeypatch):
    class _LLM:
        async def chat_with_tools(self, *args, **kwargs):
            _ = args, kwargs
            return "[]", None

    async def _slow_react(**kwargs):
        _ = kwargs
        await asyncio.sleep(0.05)
        return {"current_skill_context": {"from": "react"}}

    called = {"fallback": 0}

    async def _fallback(**kwargs):
        _ = kwargs
        called["fallback"] += 1
        return {
            "current_clause_id": "4.1",
            "current_clause_text": "fallback text",
            "current_risks": [],
            "current_skill_context": {"fallback": True},
            "current_diffs": [],
            "agent_messages": None,
            "clause_retry_count": 0,
        }

    monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _LLM())
    monkeypatch.setattr(
        "contract_review.graph.builder.get_settings",
        lambda: SimpleNamespace(react_max_iterations=3, react_clause_timeout=0.01, react_temperature=0.1),
    )
    monkeypatch.setattr("contract_review.graph.builder._run_react_branch", _slow_react)
    monkeypatch.setattr("contract_review.graph.builder._deterministic_skill_fallback", _fallback)

    dispatcher = SimpleNamespace(skill_ids={"get_clause_context"})
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

    assert called["fallback"] == 1
    assert result["current_skill_context"] == {"fallback": True}


@pytest.mark.asyncio
async def test_react_tool_calls_concurrent():
    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(
        side_effect=[
            (
                "",
                [
                    {"id": "c1", "function": {"name": "a", "arguments": "{}"}},
                    {"id": "c2", "function": {"name": "b", "arguments": "{}"}},
                ],
            ),
            ("[]", None),
        ]
    )

    dispatcher = MagicMock()
    dispatcher.get_tool_definitions.return_value = [
        {"type": "function", "function": {"name": "a", "description": "Tool a", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "b", "description": "Tool b", "parameters": {"type": "object"}}},
    ]

    async def _prepare(skill_id, clause_id, primary_structure, state, **kwargs):
        _ = clause_id, primary_structure, state, kwargs
        await asyncio.sleep(0.05)
        return SkillResult(skill_id=skill_id, success=True, data={"skill": skill_id})

    dispatcher.prepare_and_call = AsyncMock(side_effect=_prepare)

    start = time.monotonic()
    risks, skill_context, _ = await react_agent_loop(
        llm_client=llm,
        dispatcher=dispatcher,
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        clause_id="4.1",
        primary_structure={},
        state={},
    )
    elapsed = time.monotonic() - start

    assert risks == []
    assert set(skill_context.keys()) == {"a", "b"}
    assert elapsed < 0.12


def test_react_prompt_includes_suggested_skills_and_iteration_limit():
    class _Dispatcher:
        @staticmethod
        def get_registration(skill_id):
            return SimpleNamespace(description=f"desc-{skill_id}")

    msgs = build_react_agent_messages(
        language="zh-CN",
        our_party="甲方",
        clause_id="4.1",
        clause_name="义务",
        description="检查义务范围",
        priority="critical",
        clause_text="The Contractor shall ...",
        suggested_skills=["compare_with_baseline"],
        dispatcher=_Dispatcher(),
        max_iterations=3,
    )
    prompt = msgs[0]["content"]
    assert "必须优先调用" in prompt
    assert "不超过 3 轮" in prompt
    assert "不要重复调用同一工具" in prompt


@pytest.mark.asyncio
async def test_react_iteration_logging_contains_iteration_tools_elapsed(caplog):
    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(
        side_effect=[
            ("", [{"id": "c1", "function": {"name": "a", "arguments": "{}"}}]),
            ("[]", None),
        ]
    )

    dispatcher = MagicMock()
    dispatcher.get_tool_definitions.return_value = [
        {"type": "function", "function": {"name": "a", "description": "Tool a", "parameters": {"type": "object"}}}
    ]
    dispatcher.prepare_and_call = AsyncMock(return_value=SkillResult(skill_id="a", success=True, data={"ok": True}))

    with caplog.at_level(logging.INFO):
        await react_agent_loop(
            llm_client=llm,
            dispatcher=dispatcher,
            messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
            clause_id="4.1",
            primary_structure={},
            state={},
        )

    assert any("ReAct iter=" in rec.message and "tools_called=" in rec.message and "elapsed=" in rec.message for rec in caplog.records)


def test_settings_has_react_clause_timeout_default():
    settings = Settings(llm=LLMSettings(api_key="test"))
    assert settings.react_clause_timeout == 30


@pytest.mark.asyncio
async def test_analyze_gen3_timeout_path_is_resilient(monkeypatch):
    class _LLM:
        async def chat_with_tools(self, *args, **kwargs):
            _ = args, kwargs
            return "[]", None

    async def _slow_react(**kwargs):
        _ = kwargs
        await asyncio.sleep(0.05)
        return {"current_skill_context": {"from": "react"}}

    async def _fallback(**kwargs):
        _ = kwargs
        return {
            "current_clause_id": "4.1",
            "current_clause_text": "fallback text",
            "current_risks": [],
            "current_skill_context": {"fallback": True},
            "current_diffs": [],
            "agent_messages": None,
            "clause_retry_count": 0,
        }

    monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _LLM())
    monkeypatch.setattr(
        "contract_review.graph.builder.get_settings",
        lambda: SimpleNamespace(react_max_iterations=3, react_clause_timeout=0.01, react_temperature=0.1),
    )
    monkeypatch.setattr("contract_review.graph.builder._run_react_branch", _slow_react)
    monkeypatch.setattr("contract_review.graph.builder._deterministic_skill_fallback", _fallback)

    dispatcher = SimpleNamespace(skill_ids={"x"})
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
        required_skills=["x"],
    )

    assert result["current_clause_id"] == "4.1"
    assert result["current_clause_text"] == "fallback text"
    assert result["current_skill_context"] == {"fallback": True}


@pytest.mark.asyncio
async def test_react_concurrent_tools_partial_failure():
    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(
        side_effect=[
            (
                "",
                [
                    {"id": "c1", "function": {"name": "a", "arguments": "{}"}},
                    {"id": "c2", "function": {"name": "b", "arguments": "{}"}},
                ],
            ),
            ("[]", None),
        ]
    )

    dispatcher = MagicMock()
    dispatcher.get_tool_definitions.return_value = [
        {"type": "function", "function": {"name": "a", "description": "Tool a", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "b", "description": "Tool b", "parameters": {"type": "object"}}},
    ]

    async def _prepare(skill_id, clause_id, primary_structure, state, **kwargs):
        _ = clause_id, primary_structure, state, kwargs
        if skill_id == "b":
            raise RuntimeError("boom")
        return SkillResult(skill_id=skill_id, success=True, data={"ok": True})

    dispatcher.prepare_and_call = AsyncMock(side_effect=_prepare)
    _, skill_context, messages = await react_agent_loop(
        llm_client=llm,
        dispatcher=dispatcher,
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        clause_id="4.1",
        primary_structure={},
        state={},
    )

    assert skill_context == {"a": {"ok": True}}
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    assert any("error" in m.get("content", "") for m in tool_messages)
