import asyncio
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytest.importorskip("langgraph")


async def _wait_job(client, task_id: str, job_id: str, timeout_steps: int = 120):
    for _ in range(timeout_steps):
        resp = await client.get(f"/api/v3/review/{task_id}/uploads")
        assert resp.status_code == 200
        jobs = resp.json().get("jobs", [])
        target = next((j for j in jobs if j.get("job_id") == job_id), None)
        if target and target.get("status") in {"succeeded", "failed"}:
            return target
        await asyncio.sleep(0.1)
    pytest.fail(f"job timeout: {job_id}")


@pytest.fixture
def app(monkeypatch):
    from fastapi import FastAPI

    from contract_review import upload_job_manager
    from contract_review.api_gen3 import _LOCAL_UPLOAD_BLOBS, _active_graphs, router
    from contract_review.plugins.fidic import register_fidic_plugin
    from contract_review.plugins.registry import clear_plugins

    upload_job_manager._MEMORY_JOBS.clear()
    upload_job_manager._manager = None
    _LOCAL_UPLOAD_BLOBS.clear()

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


@pytest.mark.asyncio
async def test_upload_returns_quick_with_job_id(client):
    await client.post("/api/v3/review/start", json={"task_id": "au_quick"})
    files = {"file": ("contract.txt", b"1.1 Terms\nBody", "text/plain")}

    started = time.monotonic()
    resp = await client.post("/api/v3/review/au_quick/upload", files=files, data={"role": "primary"})
    elapsed = time.monotonic() - started

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"]
    assert data["status"] == "queued"
    assert data["document_id"] is None
    assert elapsed < 3


@pytest.mark.asyncio
async def test_upload_job_lifecycle_succeeds(client):
    await client.post("/api/v3/review/start", json={"task_id": "au_lifecycle"})
    files = {"file": ("contract.txt", b"1.1 Terms\nBody", "text/plain")}
    resp = await client.post("/api/v3/review/au_lifecycle/upload", files=files, data={"role": "primary"})
    assert resp.status_code == 200
    job = await _wait_job(client, "au_lifecycle", resp.json()["job_id"])
    assert job["status"] == "succeeded"
    assert (job.get("result_meta") or {}).get("document_id")


@pytest.mark.asyncio
async def test_upload_job_failed_path(client, monkeypatch):
    await client.post("/api/v3/review/start", json={"task_id": "au_fail"})

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("contract_review.api_gen3.load_document", _raise)
    files = {"file": ("contract.txt", b"1.1 Terms\nBody", "text/plain")}
    resp = await client.post("/api/v3/review/au_fail/upload", files=files, data={"role": "primary"})
    assert resp.status_code == 200
    job = await _wait_job(client, "au_fail", resp.json()["job_id"])
    assert job["status"] == "failed"
    assert "boom" in (job.get("error_message") or "")


@pytest.mark.asyncio
async def test_retry_only_failed_allowed(client, monkeypatch):
    await client.post("/api/v3/review/start", json={"task_id": "au_retry"})

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("contract_review.api_gen3.load_document", _raise)
    files = {"file": ("contract.txt", b"1.1 Terms\nBody", "text/plain")}
    upload = await client.post("/api/v3/review/au_retry/upload", files=files, data={"role": "primary"})
    job_id = upload.json()["job_id"]
    await _wait_job(client, "au_retry", job_id)

    ok_retry = await client.post(f"/api/v3/review/au_retry/uploads/{job_id}/retry")
    assert ok_retry.status_code == 200

    bad_retry = await client.post(f"/api/v3/review/au_retry/uploads/{job_id}/retry")
    assert bad_retry.status_code == 400


@pytest.mark.asyncio
async def test_list_upload_jobs_endpoint(client):
    await client.post("/api/v3/review/start", json={"task_id": "au_list"})
    files = {"file": ("contract.txt", b"1.1 Terms\nBody", "text/plain")}
    upload = await client.post("/api/v3/review/au_list/upload", files=files, data={"role": "primary"})
    assert upload.status_code == 200

    resp = await client.get("/api/v3/review/au_list/uploads")
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert len(jobs) >= 1
    assert jobs[0]["job_id"]


@pytest.mark.asyncio
async def test_upload_events_written_to_sse_cache(client):
    from contract_review.api_gen3 import _active_graphs

    await client.post("/api/v3/review/start", json={"task_id": "au_sse"})
    files = {"file": ("contract.txt", b"1.1 Terms\nBody", "text/plain")}
    upload = await client.post("/api/v3/review/au_sse/upload", files=files, data={"role": "primary"})
    job_id = upload.json()["job_id"]
    await _wait_job(client, "au_sse", job_id)

    cache = _active_graphs["au_sse"].get("sse_cache", [])
    payload = "\n".join(item.get("payload", "") for item in cache)
    assert "event: upload_progress" in payload
    assert "event: upload_complete" in payload


@pytest.mark.asyncio
async def test_recover_upload_jobs_with_active_task(client):
    from contract_review.api_gen3 import _schedule_upload_job, recover_upload_jobs
    from contract_review.upload_job_manager import get_upload_job_manager

    await client.post("/api/v3/review/start", json={"task_id": "au_recover"})
    files = {"file": ("contract.txt", b"1.1 Terms\nBody", "text/plain")}
    upload = await client.post("/api/v3/review/au_recover/upload", files=files, data={"role": "primary"})
    job_id = upload.json()["job_id"]

    # Force recover path by marking queued and re-scheduling through recover function.
    mgr = get_upload_job_manager()
    mgr.mark_job_queued(job_id)
    _schedule_upload_job("au_recover", job_id)
    recover_upload_jobs()

    job = await _wait_job(client, "au_recover", job_id)
    assert job["status"] in {"succeeded", "failed"}


@pytest.mark.asyncio
async def test_recover_upload_jobs_without_active_task_marks_failed():
    from contract_review.api_gen3 import recover_upload_jobs
    from contract_review.upload_job_manager import get_upload_job_manager

    mgr = get_upload_job_manager()
    job = mgr.create_job(
        task_id="missing_task",
        role="primary",
        filename="missing.txt",
        storage_key="gen3_uploads/missing_task/x/missing.txt",
    )

    recover_upload_jobs()
    failed = mgr.get_job(job["job_id"])
    assert failed["status"] == "failed"
