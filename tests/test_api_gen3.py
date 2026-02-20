import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytest.importorskip("langgraph")


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


class TestDomainEndpoints:
    @pytest.mark.asyncio
    async def test_list_domains(self, client):
        resp = await client.get("/api/v3/domains")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["domains"]) >= 1
        assert data["domains"][0]["domain_id"] == "fidic"

    @pytest.mark.asyncio
    async def test_get_domain_detail(self, client):
        resp = await client.get("/api/v3/domains/fidic")
        assert resp.status_code == 200
        assert len(resp.json()["review_checklist"]) >= 12

    @pytest.mark.asyncio
    async def test_get_nonexistent_domain(self, client):
        resp = await client.get("/api/v3/domains/nonexistent")
        assert resp.status_code == 404


class TestReviewEndpoints:
    @pytest.mark.asyncio
    async def test_start_review(self, client):
        resp = await client.post(
            "/api/v3/review/start",
            json={"task_id": "test_001", "domain_id": "fidic", "domain_subtype": "silver_book"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "test_001"
        assert data["status"] == "reviewing"

    @pytest.mark.asyncio
    async def test_duplicate_start(self, client):
        await client.post("/api/v3/review/start", json={"task_id": "test_dup"})
        resp = await client.post("/api/v3/review/start", json={"task_id": "test_dup"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_approve_nonexistent(self, client):
        resp = await client.post(
            "/api/v3/review/nonexistent/approve",
            json={"diff_id": "d1", "decision": "approve"},
        )
        assert resp.status_code == 404


class TestSSEProtocol:
    def test_new_event_types(self):
        from contract_review.sse_protocol import SSEEventType

        assert SSEEventType.DIFF_PROPOSED.value == "diff_proposed"
        assert SSEEventType.REVIEW_PROGRESS.value == "review_progress"
        assert SSEEventType.APPROVAL_REQUIRED.value == "approval_required"

    def test_existing_events_unchanged(self):
        from contract_review.sse_protocol import SSEEventType

        assert SSEEventType.TOOL_CALL.value == "tool_call"
        assert SSEEventType.MESSAGE_DELTA.value == "message_delta"
        assert SSEEventType.DONE.value == "done"

    def test_gen3_sse_format_uses_real_newlines(self):
        from contract_review.api_gen3 import _format_gen3_sse

        event = _format_gen3_sse("review_progress", {"ok": True})
        assert "\n" in event
        assert "\\n" not in event
        assert event.startswith("event: review_progress\n")
