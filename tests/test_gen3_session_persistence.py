import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytest.importorskip("langgraph")


@pytest.fixture
def app(monkeypatch):
    from fastapi import FastAPI

    from contract_review import session_manager, upload_job_manager
    from contract_review.api_gen3 import _LOCAL_UPLOAD_BLOBS, _active_graphs, router
    from contract_review.plugins.fidic import register_fidic_plugin
    from contract_review.plugins.registry import clear_plugins

    session_manager._MEMORY_SESSIONS.clear()
    session_manager._manager = None
    upload_job_manager._MEMORY_JOBS.clear()
    upload_job_manager._manager = None
    _LOCAL_UPLOAD_BLOBS.clear()
    _active_graphs.clear()

    test_app = FastAPI()
    test_app.include_router(router)
    clear_plugins()
    register_fidic_plugin()
    return test_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_start_review_persists_session(client):
    from contract_review.session_manager import load_session

    resp = await client.post("/api/v3/review/start", json={"task_id": "sp_start", "domain_id": "fidic", "auto_start": False})
    assert resp.status_code == 200

    session = load_session("sp_start")
    assert session is not None
    assert session["task_id"] == "sp_start"


@pytest.mark.asyncio
async def test_checkpoint_event_triggers_save(monkeypatch, client):
    from contract_review.api_gen3 import _active_graphs, _push_sse_event

    await client.post("/api/v3/review/start", json={"task_id": "sp_cp", "domain_id": "fidic", "auto_start": False})
    entry = _active_graphs["sp_cp"]

    calls = {"n": 0}

    def _spy(*args, **kwargs):
        calls["n"] += 1

    monkeypatch.setattr("contract_review.api_gen3.save_session", _spy)
    _push_sse_event(entry, "review_progress", {"task_id": "sp_cp", "current_clause_index": 0})
    assert calls["n"] >= 1


@pytest.mark.asyncio
async def test_approve_persists_decision(client):
    from contract_review.api_gen3 import _active_graphs
    from contract_review.session_manager import load_session

    await client.post("/api/v3/review/start", json={"task_id": "sp_approve", "domain_id": "fidic", "auto_start": False})
    entry = _active_graphs["sp_approve"]
    entry["graph"].update_state(entry["config"], {
        "pending_diffs": [{"diff_id": "d1", "clause_id": "4.1"}],
        "user_decisions": {},
        "user_feedback": {},
    })

    resp = await client.post("/api/v3/review/sp_approve/approve", json={"diff_id": "d1", "decision": "approve"})
    assert resp.status_code == 200

    session = load_session("sp_approve")
    graph_state = session.get("graph_state") or {}
    assert (graph_state.get("user_decisions") or {}).get("d1") == "approve"


@pytest.mark.asyncio
async def test_rehydrate_endpoint_rebuilds_active_graph(client):
    from contract_review.api_gen3 import _active_graphs

    await client.post("/api/v3/review/start", json={"task_id": "sp_rehydrate", "domain_id": "fidic", "auto_start": False})
    _active_graphs.pop("sp_rehydrate", None)

    resp = await client.post("/api/v3/review/sp_rehydrate/rehydrate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rehydrated"
    assert "sp_rehydrate" in _active_graphs


@pytest.mark.asyncio
async def test_status_auto_rehydrate(client):
    from contract_review.api_gen3 import _active_graphs

    await client.post("/api/v3/review/start", json={"task_id": "sp_status", "domain_id": "fidic", "auto_start": False})
    _active_graphs.pop("sp_status", None)

    status = await client.get("/api/v3/review/sp_status/status")
    assert status.status_code == 200
    assert status.json()["task_id"] == "sp_status"


@pytest.mark.asyncio
async def test_completed_or_failed_cannot_rehydrate(client):
    from contract_review.api_gen3 import _active_graphs
    from contract_review.session_manager import update_session_status

    await client.post("/api/v3/review/start", json={"task_id": "sp_done", "domain_id": "fidic", "auto_start": False})
    update_session_status("sp_done", "completed", is_complete=True)
    _active_graphs.pop("sp_done", None)

    completed = await client.post("/api/v3/review/sp_done/rehydrate")
    assert completed.status_code == 400

    await client.post("/api/v3/review/start", json={"task_id": "sp_failed", "domain_id": "fidic", "auto_start": False})
    update_session_status("sp_failed", "failed", error="boom")
    _active_graphs.pop("sp_failed", None)

    failed = await client.post("/api/v3/review/sp_failed/rehydrate")
    assert failed.status_code == 400


@pytest.mark.asyncio
async def test_missing_session_rehydrate_404(client):
    resp = await client.post("/api/v3/review/sp_missing/rehydrate")
    assert resp.status_code == 404


def test_graph_state_size_guard_compression():
    from contract_review import session_manager
    from contract_review.session_manager import save_session

    session_manager._MEMORY_SESSIONS.clear()
    huge = {"task_id": "sp_size", "blob": "x" * (6 * 1024 * 1024)}
    entry = {"domain_id": "fidic", "graph_run_id": "run_sp_size", "our_party": "", "language": "zh-CN"}
    save_session("sp_size", entry, huge, status="reviewing")

    stored = session_manager._MEMORY_SESSIONS["sp_size"]["graph_state"]
    raw = json.dumps(stored, ensure_ascii=False, default=str).encode("utf-8")
    assert len(raw) <= 5 * 1024 * 1024


@pytest.mark.asyncio
async def test_persistence_failure_does_not_block_start(monkeypatch, client):
    def _boom(*args, **kwargs):
        raise RuntimeError("save failed")

    monkeypatch.setattr("contract_review.api_gen3.save_session", _boom)
    resp = await client.post("/api/v3/review/start", json={"task_id": "sp_no_block", "domain_id": "fidic", "auto_start": False})
    assert resp.status_code == 200
