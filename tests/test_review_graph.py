import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

langgraph = pytest.importorskip("langgraph")

from contract_review.config import ExecutionMode, get_execution_mode
from contract_review.graph.builder import build_review_graph, route_after_analyze
from contract_review.graph.orchestrator import ClauseAnalysisPlan, ReviewPlan


class _MockLLMClient:
    def __init__(self, mode: str = "normal"):
        self.mode = mode

    async def chat(self, messages, **kwargs):
        _ = kwargs
        if self.mode == "fail":
            raise RuntimeError("API timeout")

        system_prompt = messages[0]["content"] if messages else ""

        if "识别风险点" in system_prompt:
            return json.dumps(
                [
                    {
                        "risk_level": "high",
                        "risk_type": "付款条件",
                        "description": "预付款比例过高",
                        "reason": "预付款达到合同总价30%，超出行业惯例",
                        "analysis": "建议降低至10%-15%",
                        "original_text": "预付款为合同总价的30%",
                    }
                ],
                ensure_ascii=False,
            )

        if "文本修改建议" in system_prompt:
            return json.dumps(
                [
                    {
                        "risk_id": "0",
                        "action_type": "replace",
                        "original_text": "预付款为合同总价的30%",
                        "proposed_text": "预付款为合同总价的10%",
                        "reason": "降低预付款风险",
                        "risk_level": "high",
                    }
                ],
                ensure_ascii=False,
            )

        if "质量检查员" in system_prompt:
            if self.mode == "validate_fail":
                return json.dumps({"result": "fail", "issues": ["文本匹配不足"]}, ensure_ascii=False)
            return json.dumps({"result": "pass", "issues": []}, ensure_ascii=False)

        if "结构化总结" in system_prompt:
            return "审查完成：核心风险集中在预付款与责任条款。"

        return "[]"


@pytest.fixture
def mock_llm_client(monkeypatch):
    monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _MockLLMClient())
    monkeypatch.setattr(
        "contract_review.graph.builder.get_settings",
        lambda: SimpleNamespace(
            execution_mode="legacy",
            react_max_iterations=5,
            react_temperature=0.1,
            refly=SimpleNamespace(enabled=False, api_key="", base_url="", timeout=30, poll_interval=1, max_poll_attempts=3),
        ),
    )


class TestReviewGraph:
    def test_build_graph(self):
        graph = build_review_graph()
        assert graph is not None

    @pytest.mark.asyncio
    async def test_empty_checklist(self):
        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_001",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "en",
            "documents": [],
            "review_checklist": [],
        }
        config = {"configurable": {"thread_id": "test_empty"}}
        result = await graph.ainvoke(initial_state, config)
        assert result["is_complete"] is True
        assert result.get("summary_notes", "").strip()

    @pytest.mark.asyncio
    async def test_single_clause_no_interrupt(self):
        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_002",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "en",
            "documents": [],
            "review_checklist": [
                {
                    "clause_id": "14.2",
                    "clause_name": "预付款",
                    "priority": "high",
                    "required_skills": ["get_clause_context"],
                    "description": "核查预付款条款",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_single"}}
        result = await graph.ainvoke(initial_state, config)
        assert result["is_complete"] is True
        assert result["current_clause_index"] == 1
        assert "14.2" in result.get("findings", {})

    @pytest.mark.asyncio
    async def test_interrupt_and_resume(self):
        graph = build_review_graph(interrupt_before=["human_approval"])
        initial_state = {
            "task_id": "test_003",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "en",
            "documents": [],
            "review_checklist": [
                {
                    "clause_id": "17.6",
                    "clause_name": "责任限制",
                    "priority": "critical",
                    "required_skills": [],
                    "description": "核查赔偿上限",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_interrupt"}}
        await graph.ainvoke(initial_state, config)
        snapshot = graph.get_state(config)
        assert snapshot.next
        graph.update_state(config, {"user_decisions": {}, "user_feedback": {}})
        result = await graph.ainvoke(None, config)
        assert result["is_complete"] is True


class TestLLMIntegration:
    @pytest.mark.asyncio
    async def test_single_clause_with_llm_outputs_risks_and_diffs(self, mock_llm_client):
        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_llm_001",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "review_checklist": [
                {
                    "clause_id": "14.2",
                    "clause_name": "预付款",
                    "priority": "high",
                    "required_skills": [],
                    "description": "核查预付款条款",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_llm"}}
        result = await graph.ainvoke(initial_state, config)

        assert result["is_complete"] is True
        assert len(result["all_risks"]) >= 1
        assert result["all_risks"][0]["risk_level"] == "high"
        assert len(result["all_diffs"]) >= 1
        assert result["all_diffs"][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_llm_failure_graceful_degradation(self, monkeypatch):
        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _MockLLMClient(mode="fail"))

        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_fail_001",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "review_checklist": [
                {
                    "clause_id": "1.1",
                    "clause_name": "定义",
                    "priority": "medium",
                    "required_skills": [],
                    "description": "检查定义条款",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_fail"}}
        result = await graph.ainvoke(initial_state, config)

        assert result["is_complete"] is True

    @pytest.mark.asyncio
    async def test_validate_fail_increments_retry_count(self, monkeypatch):
        monkeypatch.setattr(
            "contract_review.graph.builder._get_llm_client",
            lambda: _MockLLMClient(mode="validate_fail"),
        )
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(
                execution_mode="legacy",
                react_max_iterations=5,
                react_temperature=0.1,
                refly=SimpleNamespace(enabled=False, api_key="", base_url="", timeout=30, poll_interval=1, max_poll_attempts=3),
            ),
        )

        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_validate_001",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "review_checklist": [
                {
                    "clause_id": "14.2",
                    "clause_name": "预付款",
                    "priority": "high",
                    "required_skills": [],
                    "description": "核查预付款条款",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_validate"}}
        result = await graph.ainvoke(initial_state, config)

        assert result["is_complete"] is True
        assert result.get("clause_retry_count", 0) >= 1

    @pytest.mark.asyncio
    async def test_react_disabled_uses_hardcoded(self, monkeypatch):
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(
                execution_mode="legacy",
                react_max_iterations=5,
                react_temperature=0.1,
                refly=SimpleNamespace(enabled=False, api_key="", base_url="", timeout=30, poll_interval=1, max_poll_attempts=3),
            ),
        )
        called = {"react": False}

        async def _fake_run(**kwargs):
            _ = kwargs
            called["react"] = True
            return {}

        monkeypatch.setattr("contract_review.graph.builder._run_react_branch", _fake_run)
        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _MockLLMClient())

        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_react_off",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "review_checklist": [
                {
                    "clause_id": "14.2",
                    "clause_name": "预付款",
                    "priority": "high",
                    "required_skills": [],
                    "description": "核查预付款条款",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_react_off"}}
        result = await graph.ainvoke(initial_state, config)
        assert result["is_complete"] is True
        assert called["react"] is False

    @pytest.mark.asyncio
    async def test_gen3_react_failure_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(
                execution_mode="gen3",
                react_max_iterations=5,
                react_temperature=0.1,
                refly=SimpleNamespace(enabled=False, api_key="", base_url="", timeout=30, poll_interval=1, max_poll_attempts=3),
            ),
        )
        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _MockLLMClient())

        async def _fake_run(**kwargs):
            _ = kwargs
            raise RuntimeError("react failed")

        monkeypatch.setattr("contract_review.graph.builder._run_react_branch", _fake_run)

        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_react_fallback",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "primary_structure": {
                "document_id": "d1",
                "structure_type": "generic",
                "definitions": {},
                "cross_references": [],
                "total_clauses": 1,
                "clauses": [
                    {
                        "clause_id": "14.2",
                        "title": "预付款",
                        "text": "预付款为合同总价的30%",
                        "children": [],
                    }
                ],
            },
            "review_checklist": [
                {
                    "clause_id": "14.2",
                    "clause_name": "预付款",
                    "priority": "high",
                    "required_skills": [],
                    "description": "核查预付款条款",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_gen3_react_error"}}
        result = await graph.ainvoke(initial_state, config)
        assert result["is_complete"] is True
        assert "ReAct Agent 失败" in result.get("error", "")


class TestOrchestratorGraph:
    def _settings(self, *, execution_mode: str):
        return SimpleNamespace(
            execution_mode=execution_mode,
            react_max_iterations=5,
            react_temperature=0.1,
            refly=SimpleNamespace(
                enabled=False,
                api_key="",
                base_url="https://api.refly.ai",
                timeout=30,
                poll_interval=1,
                max_poll_attempts=3,
            ),
        )

    @pytest.mark.asyncio
    async def test_orchestrator_disabled_keeps_existing_behavior(self, monkeypatch):
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: self._settings(execution_mode="legacy"),
        )
        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _MockLLMClient())

        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_orch_off",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "review_plan": {
                "clause_plans": [
                    {
                        "clause_id": "14.2",
                        "analysis_depth": "quick",
                        "skip_diffs": True,
                        "max_iterations": 1,
                        "priority_order": 0,
                    }
                ],
                "plan_version": 1,
            },
            "review_checklist": [
                {
                    "clause_id": "14.2",
                    "clause_name": "预付款",
                    "priority": "high",
                    "required_skills": [],
                    "description": "核查预付款条款",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_orch_off"}}
        result = await graph.ainvoke(initial_state, config)
        assert result["is_complete"] is True
        assert len(result.get("all_diffs", [])) >= 1

    @pytest.mark.asyncio
    async def test_orchestrator_enabled_plan_fallback(self, monkeypatch):
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: self._settings(execution_mode="gen3"),
        )
        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _MockLLMClient(mode="fail"))

        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_orch_fallback",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "review_checklist": [
                {
                    "clause_id": "17.6",
                    "clause_name": "责任限制",
                    "priority": "critical",
                    "required_skills": [],
                    "description": "核查责任限制",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_orch_fallback"}}
        result = await graph.ainvoke(initial_state, config)
        assert result["is_complete"] is True
        assert isinstance(result.get("review_plan"), dict)
        assert result.get("plan_version", 0) >= 1

    @pytest.mark.asyncio
    async def test_orchestrator_route_skip_diffs(self, monkeypatch):
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: self._settings(execution_mode="gen3"),
        )
        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _MockLLMClient())

        async def _fake_generate_review_plan(*args, **kwargs):
            _ = args, kwargs
            return ReviewPlan(
                clause_plans=[
                    ClauseAnalysisPlan(
                        clause_id="14.2",
                        analysis_depth="quick",
                        suggested_tools=[],
                        max_iterations=1,
                        priority_order=0,
                        skip_diffs=True,
                    )
                ],
                plan_version=1,
            )

        monkeypatch.setattr("contract_review.graph.builder.generate_review_plan", _fake_generate_review_plan)

        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_orch_skip_diffs",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "review_checklist": [
                {
                    "clause_id": "14.2",
                    "clause_name": "预付款",
                    "priority": "high",
                    "required_skills": [],
                    "description": "核查预付款条款",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_orch_skip_diffs"}}
        result = await graph.ainvoke(initial_state, config)
        assert result["is_complete"] is True
        assert result.get("all_diffs", []) == []

    @pytest.mark.asyncio
    async def test_orchestrator_and_react_enabled(self, monkeypatch):
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: self._settings(execution_mode="gen3"),
        )
        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: _MockLLMClient())
        called = {"react": False}

        async def _fake_run(**kwargs):
            _ = kwargs
            called["react"] = True
            return {
                "current_clause_id": "14.2",
                "current_clause_text": "预付款为合同总价的30%",
                "current_risks": [],
                "current_diffs": [],
                "current_skill_context": {},
                "agent_messages": [],
                "clause_retry_count": 0,
            }

        monkeypatch.setattr("contract_review.graph.builder._run_react_branch", _fake_run)

        graph = build_review_graph(interrupt_before=[])
        initial_state = {
            "task_id": "test_orch_react",
            "our_party": "承包商",
            "material_type": "contract",
            "language": "zh-CN",
            "documents": [],
            "primary_structure": {
                "clauses": [
                    {
                        "clause_id": "14.2",
                        "title": "预付款",
                        "text": "预付款为合同总价的30%",
                        "children": [],
                    }
                ]
            },
            "review_checklist": [
                {
                    "clause_id": "14.2",
                    "clause_name": "预付款",
                    "priority": "high",
                    "required_skills": [],
                    "description": "核查预付款条款",
                }
            ],
        }
        config = {"configurable": {"thread_id": "test_orch_react"}}
        result = await graph.ainvoke(initial_state, config)
        assert result["is_complete"] is True
        assert called["react"] is True


class TestRouteAfterAnalyze:
    def test_route_skip_diffs_true(self):
        state = {
            "current_clause_id": "1.1",
            "review_plan": {
                "clause_plans": [
                    {
                        "clause_id": "1.1",
                        "analysis_depth": "quick",
                        "skip_diffs": True,
                        "max_iterations": 1,
                        "priority_order": 0,
                    }
                ]
            },
        }
        assert route_after_analyze(state) == "save_clause"

    def test_route_skip_diffs_false(self):
        state = {
            "current_clause_id": "1.1",
            "review_plan": {
                "clause_plans": [
                    {
                        "clause_id": "1.1",
                        "analysis_depth": "standard",
                        "skip_diffs": False,
                        "max_iterations": 3,
                        "priority_order": 0,
                    }
                ]
            },
        }
        assert route_after_analyze(state) == "clause_generate_diffs"

    def test_route_no_plan_defaults_to_diffs(self):
        state = {"current_clause_id": "1.1"}
        assert route_after_analyze(state) == "clause_generate_diffs"


class TestClauseAnalyzeDispatcher:
    @pytest.mark.asyncio
    async def test_non_react_path_uses_prepare_and_call(self, monkeypatch):
        from contract_review.graph.builder import node_clause_analyze

        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(execution_mode="legacy", react_max_iterations=5, react_temperature=0.1),
        )
        monkeypatch.setattr("contract_review.graph.builder._get_llm_client", lambda: None)

        class _Dispatcher:
            def __init__(self):
                self.skill_ids = ["get_clause_context", "resolve_definition"]
                self.prepare_and_call = AsyncMock(
                    side_effect=[
                        SimpleNamespace(success=True, data={"context_text": "Clause text from skill"}),
                        SimpleNamespace(success=True, data={"resolved_terms": []}),
                    ]
                )

        dispatcher = _Dispatcher()
        state = {
            "review_checklist": [
                {
                    "clause_id": "4.1",
                    "clause_name": "承包商义务",
                    "description": "核查义务范围",
                    "priority": "high",
                    "required_skills": ["get_clause_context", "resolve_definition"],
                }
            ],
            "current_clause_index": 0,
            "our_party": "承包商",
            "language": "zh-CN",
            "primary_structure": {
                "clauses": [{"clause_id": "4.1", "text": "contractor obligations", "children": []}]
            },
        }

        result = await node_clause_analyze(state, dispatcher=dispatcher)
        assert dispatcher.prepare_and_call.await_count == 2
        dispatcher.prepare_and_call.assert_any_await(
            "get_clause_context",
            "4.1",
            state["primary_structure"],
            dict(state),
        )
        assert result["current_skill_context"]["get_clause_context"]["context_text"] == "Clause text from skill"


class TestExecutionModeSwitch:
    @pytest.mark.asyncio
    async def test_legacy_mode_dispatches_to_analyze_legacy(self, monkeypatch):
        from contract_review.graph.builder import node_clause_analyze

        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(execution_mode="legacy", react_max_iterations=5, react_temperature=0.1),
        )
        called = {"legacy": 0}

        async def _fake_legacy(**kwargs):
            _ = kwargs
            called["legacy"] += 1
            return {
                "current_clause_id": "4.1",
                "current_clause_text": "x",
                "current_risks": [],
                "current_diffs": [],
                "current_skill_context": {},
                "agent_messages": None,
                "clause_retry_count": 0,
            }

        monkeypatch.setattr("contract_review.graph.builder._analyze_legacy", _fake_legacy)
        state = {
            "review_checklist": [
                {"clause_id": "4.1", "clause_name": "x", "description": "x", "priority": "high", "required_skills": []}
            ],
            "current_clause_index": 0,
            "primary_structure": {"clauses": []},
        }
        result = await node_clause_analyze(state, dispatcher=None)
        assert result["current_clause_id"] == "4.1"
        assert called["legacy"] == 1

    @pytest.mark.asyncio
    async def test_gen3_mode_dispatches_to_analyze_gen3(self, monkeypatch):
        from contract_review.graph.builder import node_clause_analyze

        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(execution_mode="gen3", react_max_iterations=5, react_temperature=0.1),
        )
        called = {"gen3": 0}

        async def _fake_gen3(**kwargs):
            _ = kwargs
            called["gen3"] += 1
            return {
                "current_clause_id": "4.1",
                "current_clause_text": "x",
                "current_risks": [],
                "current_diffs": [],
                "current_skill_context": {},
                "agent_messages": [],
                "clause_retry_count": 0,
            }

        monkeypatch.setattr("contract_review.graph.builder._analyze_gen3", _fake_gen3)
        state = {
            "review_checklist": [
                {"clause_id": "4.1", "clause_name": "x", "description": "x", "priority": "high", "required_skills": []}
            ],
            "current_clause_index": 0,
            "primary_structure": {"clauses": []},
        }
        result = await node_clause_analyze(state, dispatcher=object())
        assert result["current_clause_id"] == "4.1"
        assert called["gen3"] == 1

    def test_explicit_mode_overrides_old_bools(self):
        settings = SimpleNamespace(execution_mode="gen3", use_orchestrator=False, use_react_agent=False)
        assert get_execution_mode(settings) == ExecutionMode.GEN3


class TestForceMode:
    def test_force_gen3_overrides_legacy_config(self, monkeypatch):
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(execution_mode="legacy"),
        )
        graph = build_review_graph(interrupt_before=[], force_mode=ExecutionMode.GEN3)
        nodes = set(graph.get_graph().nodes.keys())
        assert "plan_review" in nodes

    def test_force_legacy_overrides_gen3_config(self, monkeypatch):
        monkeypatch.setattr(
            "contract_review.graph.builder.get_settings",
            lambda: SimpleNamespace(execution_mode="gen3"),
        )
        graph = build_review_graph(interrupt_before=[], force_mode=ExecutionMode.LEGACY)
        nodes = set(graph.get_graph().nodes.keys())
        assert "plan_review" not in nodes
