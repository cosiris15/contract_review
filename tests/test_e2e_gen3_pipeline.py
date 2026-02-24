import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("langgraph")

from contract_review.config import ExecutionMode, get_execution_mode
from contract_review.graph.builder import _analyze_gen3, _create_dispatcher, _get_clause_plan, build_review_graph


class _FakeToolLLM:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = 0

    async def chat_with_tools(self, messages, tools, temperature=None, max_output_tokens=None):
        _ = messages, tools, temperature, max_output_tokens
        self.calls += 1
        if self.calls == 1:
            return (
                "",
                [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_clause_context",
                            "arguments": json.dumps({"clause_id": "4.1"}, ensure_ascii=False),
                        },
                    }
                ],
            )
        return self.response_text, None


class TestGen3EndToEnd:
    @pytest.fixture
    def primary_structure(self):
        return {
            "document_id": "d1",
            "structure_type": "generic",
            "definitions": {},
            "cross_references": [],
            "total_clauses": 1,
            "clauses": [
                {
                    "clause_id": "4.1",
                    "title": "承包商的一般义务",
                    "text": "承包商应按照合同规定设计、施工并完成工程。",
                    "children": [],
                }
            ],
        }

    @pytest.fixture
    def base_state(self, primary_structure):
        return {
            "task_id": "e2e_test_001",
            "our_party": "承包商",
            "language": "zh-CN",
            "domain_id": "fidic",
            "domain_subtype": "yellow_book",
            "material_type": "contract",
            "documents": [],
            "findings": {},
            "primary_structure": primary_structure,
            "review_plan": {
                "plan_version": 1,
                "clause_plans": [
                    {
                        "clause_id": "4.1",
                        "suggested_tools": ["get_clause_context"],
                        "max_iterations": 3,
                        "skip_diffs": False,
                    }
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_orchestrator_plan_feeds_react_dispatcher_skill(self, primary_structure, base_state, monkeypatch):
        dispatcher = _create_dispatcher(domain_id="fidic")
        assert dispatcher is not None

        plan = _get_clause_plan(base_state, "4.1")
        assert plan is not None
        assert plan.suggested_tools == ["get_clause_context"]
        assert plan.max_iterations == 3

        fake_llm = _FakeToolLLM(
            response_text=json.dumps(
                [
                    {
                        "risk_level": "low",
                        "risk_type": "信息提示",
                        "description": "无明显风险",
                        "reason": "条款义务描述清晰",
                        "analysis": "保持现状",
                        "original_text": "承包商应按照合同规定设计、施工并完成工程。",
                    }
                ],
                ensure_ascii=False,
            )
        )
        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: fake_llm)
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(execution_mode="gen3", react_max_iterations=5, react_temperature=0.1),
        )

        result = await _analyze_gen3(
            state=base_state,
            dispatcher=dispatcher,
            clause_id="4.1",
            clause_name="承包商的一般义务",
            description="承包商应按照合同规定完成工程",
            priority="high",
            our_party="承包商",
            language="zh-CN",
            primary_structure=primary_structure,
            required_skills=["get_clause_context"],
        )

        assert result["current_clause_id"] == "4.1"
        assert fake_llm.calls >= 2
        assert "get_clause_context" in result["current_skill_context"]
        assert len(result["current_risks"]) == 1

    def test_gen3_graph_includes_plan_review_node(self):
        with patch("contract_review.graph.builder.get_execution_mode", return_value=ExecutionMode.GEN3):
            graph = build_review_graph(domain_id="fidic", interrupt_before=[])
            nodes = set(graph.get_graph().nodes.keys())
            assert "plan_review" in nodes
            assert "clause_analyze" in nodes

    def test_legacy_graph_excludes_plan_review_node(self):
        with patch("contract_review.graph.builder.get_execution_mode", return_value=ExecutionMode.LEGACY):
            graph = build_review_graph(domain_id="fidic", interrupt_before=[])
            nodes = set(graph.get_graph().nodes.keys())
            assert "plan_review" not in nodes
            assert "clause_analyze" in nodes

    @pytest.mark.asyncio
    async def test_gen3_without_plan_still_works(self, primary_structure, monkeypatch):
        dispatcher = _create_dispatcher(domain_id="fidic")
        assert dispatcher is not None

        state_no_plan = {
            "task_id": "e2e_test_002",
            "our_party": "承包商",
            "language": "zh-CN",
            "domain_id": "fidic",
            "primary_structure": primary_structure,
        }

        fake_llm = _FakeToolLLM(response_text="[]")
        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: fake_llm)
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(execution_mode="gen3", react_max_iterations=5, react_temperature=0.1),
        )

        result = await _analyze_gen3(
            state=state_no_plan,
            dispatcher=dispatcher,
            clause_id="4.1",
            clause_name="承包商的一般义务",
            description="测试",
            priority="high",
            our_party="承包商",
            language="zh-CN",
            primary_structure=primary_structure,
            required_skills=["get_clause_context"],
        )
        assert result["current_clause_id"] == "4.1"

    @pytest.mark.asyncio
    async def test_gen3_react_branch_exception_uses_deterministic_fallback(self, primary_structure, base_state, monkeypatch):
        dispatcher = _create_dispatcher(domain_id="fidic")
        assert dispatcher is not None

        class _DummyLLM:
            async def chat_with_tools(self, *args, **kwargs):
                _ = args, kwargs
                return "[]", None

        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _DummyLLM())
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(execution_mode="gen3", react_max_iterations=5, react_temperature=0.1),
        )
        async def _raise_run_react_branch(**kwargs):
            _ = kwargs
            raise RuntimeError("react failed")

        monkeypatch.setattr("contract_review.graph.builder._run_react_branch", _raise_run_react_branch)

        result = await _analyze_gen3(
            state=base_state,
            dispatcher=dispatcher,
            clause_id="4.1",
            clause_name="承包商的一般义务",
            description="测试",
            priority="high",
            our_party="承包商",
            language="zh-CN",
            primary_structure=primary_structure,
            required_skills=["get_clause_context"],
        )
        assert result["current_clause_id"] == "4.1"
        assert "get_clause_context" in result["current_skill_context"]


class TestGetExecutionMode:
    def test_default_is_gen3(self):
        settings = SimpleNamespace(use_orchestrator=False, use_react_agent=False)
        assert get_execution_mode(settings) == ExecutionMode.GEN3

    def test_explicit_legacy(self):
        settings = SimpleNamespace(execution_mode="legacy", use_orchestrator=False, use_react_agent=False)
        assert get_execution_mode(settings) == ExecutionMode.LEGACY

    def test_explicit_gen3(self):
        settings = SimpleNamespace(execution_mode="gen3", use_orchestrator=False, use_react_agent=False)
        assert get_execution_mode(settings) == ExecutionMode.GEN3

    def test_missing_execution_mode_defaults_to_gen3(self):
        settings = SimpleNamespace(use_orchestrator=False, use_react_agent=False)
        assert get_execution_mode(settings) == ExecutionMode.GEN3

    def test_use_orchestrator_infers_gen3(self):
        settings = SimpleNamespace(execution_mode="legacy", use_orchestrator=True, use_react_agent=False)
        assert get_execution_mode(settings) == ExecutionMode.GEN3

    def test_use_react_agent_infers_gen3(self):
        settings = SimpleNamespace(execution_mode="legacy", use_orchestrator=False, use_react_agent=True)
        assert get_execution_mode(settings) == ExecutionMode.GEN3

    def test_legacy_with_old_flags_true_still_infers_gen3(self):
        settings = SimpleNamespace(execution_mode="legacy", use_orchestrator=True, use_react_agent=False)
        assert get_execution_mode(settings) == ExecutionMode.GEN3

    def test_deprecated_bool_logs_warning(self, caplog):
        caplog.set_level(logging.WARNING)
        settings = SimpleNamespace(execution_mode="legacy", use_orchestrator=True, use_react_agent=False)
        assert get_execution_mode(settings) == ExecutionMode.GEN3
        assert "已废弃" in caplog.text
