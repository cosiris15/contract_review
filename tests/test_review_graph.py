import json

import pytest

langgraph = pytest.importorskip("langgraph")

from contract_review.graph.builder import build_review_graph


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
