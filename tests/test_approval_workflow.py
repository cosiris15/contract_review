from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytest.importorskip("langgraph")

from contract_review.graph.builder import node_human_approval, route_after_approval


class TestRouteAfterApproval:
    def test_all_rejected_routes_to_clause_generate_diffs(self):
        state = {
            "pending_diffs": [{"diff_id": "d1"}, {"diff_id": "d2"}],
            "user_decisions": {"d1": "reject", "d2": "reject"},
        }
        assert route_after_approval(state) == "clause_generate_diffs"

    def test_mixed_decisions_routes_to_save_clause(self):
        state = {
            "pending_diffs": [{"diff_id": "d1"}, {"diff_id": "d2"}],
            "user_decisions": {"d1": "approve", "d2": "reject"},
        }
        assert route_after_approval(state) == "save_clause"

    def test_all_approved_routes_to_save_clause(self):
        state = {
            "pending_diffs": [{"diff_id": "d1"}, {"diff_id": "d2"}],
            "user_decisions": {"d1": "approve", "d2": "approve"},
        }
        assert route_after_approval(state) == "save_clause"

    def test_empty_decisions_routes_to_save_clause(self):
        state = {
            "pending_diffs": [{"diff_id": "d1"}],
            "user_decisions": {},
        }
        assert route_after_approval(state) == "save_clause"


class TestNodeHumanApproval:
    @pytest.mark.asyncio
    async def test_with_diffs_clears_decisions_and_feedback(self):
        diffs = [{"diff_id": "d1"}, {"diff_id": "d2"}]
        state = {
            "current_diffs": diffs,
            "user_decisions": {"old": "approve"},
            "user_feedback": {"old": "ok"},
        }
        result = await node_human_approval(state)
        assert result["pending_diffs"] == diffs
        assert result["user_decisions"] == {}
        assert result["user_feedback"] == {}

    @pytest.mark.asyncio
    async def test_without_diffs_still_clears_decisions_and_feedback(self):
        state = {
            "current_diffs": [],
            "user_decisions": {"old": "approve"},
            "user_feedback": {"old": "ok"},
        }
        result = await node_human_approval(state)
        assert result["pending_diffs"] == []
        assert result["user_decisions"] == {}
        assert result["user_feedback"] == {}


class _FakeGraph:
    def __init__(self, values):
        self._values = values

    def get_state(self, config):
        _ = config
        return SimpleNamespace(values=self._values)

    async def ainvoke(self, payload, config):
        _ = payload, config
        return {}


@pytest.fixture
def app():
    from fastapi import FastAPI

    from contract_review.api_gen3 import _active_graphs, router
    from contract_review.plugins.fidic import register_fidic_plugin
    from contract_review.plugins.registry import clear_plugins

    test_app = FastAPI()
    test_app.include_router(router)
    clear_plugins()
    register_fidic_plugin()
    _active_graphs.clear()
    return test_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestResumeValidation:
    @pytest.mark.asyncio
    async def test_resume_returns_400_when_decisions_incomplete(self, client):
        from contract_review.api_gen3 import _active_graphs

        _active_graphs["resume_incomplete"] = {
            "graph": _FakeGraph(
                {
                    "pending_diffs": [{"diff_id": "d1"}, {"diff_id": "d2"}],
                    "user_decisions": {"d1": "approve"},
                }
            ),
            "config": {"configurable": {"thread_id": "resume_incomplete"}},
            "resume_task": None,
            "last_access_ts": 0,
        }

        resp = await client.post("/api/v3/review/resume_incomplete/resume")
        assert resp.status_code == 400
        assert "d2" in resp.json().get("detail", "")

    @pytest.mark.asyncio
    async def test_resume_ok_when_decisions_complete(self, client):
        from contract_review.api_gen3 import _active_graphs

        _active_graphs["resume_complete"] = {
            "graph": _FakeGraph(
                {
                    "pending_diffs": [{"diff_id": "d1"}, {"diff_id": "d2"}],
                    "user_decisions": {"d1": "approve", "d2": "reject"},
                }
            ),
            "config": {"configurable": {"thread_id": "resume_complete"}},
            "resume_task": None,
            "last_access_ts": 0,
        }

        resp = await client.post("/api/v3/review/resume_complete/resume")
        assert resp.status_code == 200
        assert resp.json().get("status") == "resumed"

    @pytest.mark.asyncio
    async def test_resume_ok_when_no_pending(self, client):
        from contract_review.api_gen3 import _active_graphs

        _active_graphs["resume_empty"] = {
            "graph": _FakeGraph({"pending_diffs": [], "user_decisions": {}}),
            "config": {"configurable": {"thread_id": "resume_empty"}},
            "resume_task": None,
            "last_access_ts": 0,
        }

        resp = await client.post("/api/v3/review/resume_empty/resume")
        assert resp.status_code == 200
        assert resp.json().get("status") == "resumed"
