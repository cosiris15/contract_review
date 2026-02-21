import pytest
from unittest.mock import AsyncMock, MagicMock

from contract_review.graph.react_agent import (
    MAX_TOOL_RESULT_CHARS,
    _parse_final_response,
    _serialize_tool_result,
    _truncate,
    react_agent_loop,
)
from contract_review.skills.schema import SkillResult


def _make_fake_llm(responses):
    client = AsyncMock()
    client.chat_with_tools = AsyncMock(side_effect=responses)
    return client


def _make_fake_dispatcher(skill_ids, results=None, failed=None):
    dispatcher = MagicMock()
    dispatcher.get_tool_definitions.return_value = [
        {
            "type": "function",
            "function": {
                "name": sid,
                "description": f"Tool {sid}",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
        for sid in skill_ids
    ]
    result_map = results or {}
    failed = failed or set()

    async def _prepare_and_call(skill_id, clause_id, primary_structure, state, **kwargs):
        _ = clause_id, primary_structure, state, kwargs
        if skill_id in failed:
            return SkillResult(skill_id=skill_id, success=False, error="failed")
        return SkillResult(skill_id=skill_id, success=True, data=result_map.get(skill_id, {"ok": True}))

    dispatcher.prepare_and_call = AsyncMock(side_effect=_prepare_and_call)
    return dispatcher


@pytest.mark.asyncio
async def test_single_iteration_no_tools():
    llm = _make_fake_llm([('[{"risk_level":"high","risk_type":"x","description":"d","reason":"r","analysis":"a","original_text":"o"}]', None)])
    dispatcher = _make_fake_dispatcher(["get_clause_context"])
    risks, skill_ctx, final_msgs = await react_agent_loop(
        llm,
        dispatcher,
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "1.1",
        {},
        {},
    )
    assert len(risks) == 1
    assert skill_ctx == {}
    assert final_msgs[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_tool_call_then_final_response():
    llm = _make_fake_llm(
        [
            ("", [{"id": "c1", "function": {"name": "get_clause_context", "arguments": '{"clause_id":"1.1"}'}}]),
            ('[{"risk_level":"medium","risk_type":"x","description":"d","reason":"r","analysis":"a","original_text":"o"}]', None),
        ]
    )
    dispatcher = _make_fake_dispatcher(["get_clause_context"], results={"get_clause_context": {"context_text": "abc"}})
    risks, skill_ctx, final_msgs = await react_agent_loop(
        llm,
        dispatcher,
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "1.1",
        {},
        {},
    )
    assert len(risks) == 1
    assert "get_clause_context" in skill_ctx
    assert any(m.get("role") == "tool" for m in final_msgs)


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_round():
    llm = _make_fake_llm(
        [
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
    dispatcher = _make_fake_dispatcher(["a", "b"], results={"a": {"x": 1}, "b": {"y": 2}})
    risks, skill_ctx, _ = await react_agent_loop(
        llm,
        dispatcher,
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "1.1",
        {},
        {},
    )
    assert risks == []
    assert set(skill_ctx.keys()) == {"a", "b"}


@pytest.mark.asyncio
async def test_max_iterations_reached():
    llm = _make_fake_llm([("", [{"id": "c1", "function": {"name": "a", "arguments": "{}"}}])] * 5)
    dispatcher = _make_fake_dispatcher(["a"], results={"a": {"x": 1}})
    risks, skill_ctx, _ = await react_agent_loop(
        llm,
        dispatcher,
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "1.1",
        {},
        {},
        max_iterations=3,
    )
    assert risks == []
    assert "a" in skill_ctx


@pytest.mark.asyncio
async def test_llm_failure_breaks_loop():
    llm = _make_fake_llm([RuntimeError("boom")])
    dispatcher = _make_fake_dispatcher(["a"])
    risks, skill_ctx, _ = await react_agent_loop(
        llm,
        dispatcher,
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "1.1",
        {},
        {},
    )
    assert risks == []
    assert skill_ctx == {}


@pytest.mark.asyncio
async def test_tool_execution_failure_continues():
    llm = _make_fake_llm(
        [
            ("", [{"id": "c1", "function": {"name": "a", "arguments": "{}"}}]),
            ("[]", None),
        ]
    )
    dispatcher = _make_fake_dispatcher(["a"], failed={"a"})
    risks, skill_ctx, final_msgs = await react_agent_loop(
        llm,
        dispatcher,
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "1.1",
        {},
        {},
    )
    assert risks == []
    assert skill_ctx == {}
    assert any(m.get("role") == "tool" for m in final_msgs)


@pytest.mark.asyncio
async def test_no_tools_available():
    llm = _make_fake_llm([("[]", None)])
    dispatcher = MagicMock()
    dispatcher.get_tool_definitions.return_value = []
    risks, skill_ctx, _ = await react_agent_loop(
        llm,
        dispatcher,
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "1.1",
        {},
        {},
    )
    assert risks == []
    assert skill_ctx == {}


def test_parse_final_response_helpers():
    assert len(_parse_final_response('[{"a":1}]')) == 1
    assert _parse_final_response("[]") == []
    assert _parse_final_response("") == []
    assert _parse_final_response("not-json") == []
    assert _parse_final_response('[{"a":1}, 2, "x"]') == [{"a": 1}]


def test_truncate_helper():
    assert _truncate("abc", max_chars=10) == "abc"
    long_text = "x" * (MAX_TOOL_RESULT_CHARS + 10)
    assert "... (截断" in _truncate(long_text)


def test_serialize_helper():
    assert _serialize_tool_result(None) == "{}"
    assert _serialize_tool_result({"a": 1}).startswith("{")
    assert _serialize_tool_result("abc") == "abc"
