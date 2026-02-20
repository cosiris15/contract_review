import pytest

langgraph = pytest.importorskip("langgraph")

from contract_review.graph.builder import build_review_graph


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
        assert "审查完成" in result.get("summary_notes", "")

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
