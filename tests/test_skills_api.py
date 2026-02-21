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


@pytest.mark.asyncio
async def test_list_skills(client):
    resp = await client.get("/api/v3/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert "skills" in data
    assert "total" in data
    assert "by_domain" in data
    assert "by_backend" in data
    assert data["total"] >= 1
    assert all("status" in row for row in data["skills"])


@pytest.mark.asyncio
async def test_list_skills_filter_by_domain(client):
    resp = await client.get("/api/v3/skills", params={"domain_id": "fidic"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["skills"], list)
    domains = {row["domain"] for row in data["skills"]}
    assert domains.issubset({"*", "fidic"})


@pytest.mark.asyncio
async def test_get_skill_detail_success(client):
    resp = await client.get("/api/v3/skills/get_clause_context")
    assert resp.status_code == 200
    data = resp.json()
    assert data["skill_id"] == "get_clause_context"
    assert data["backend"] == "local"
    assert "status" in data
    assert "is_registered" in data
    assert "used_by_checklist_items" in data


@pytest.mark.asyncio
async def test_get_skill_detail_used_by_checklist_items(client):
    resp = await client.get("/api/v3/skills/get_clause_context")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["used_by_checklist_items"], list)
    assert "1.1" in data["used_by_checklist_items"]


@pytest.mark.asyncio
async def test_get_skill_detail_not_found(client):
    resp = await client.get("/api/v3/skills/nonexistent_skill")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_skills_by_domain_fidic(client):
    resp = await client.get("/api/v3/skills/by-domain/fidic")
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain_id"] == "fidic"
    assert isinstance(data["skills"], list)
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_skills_by_domain_unknown(client):
    resp = await client.get("/api/v3/skills/by-domain/unknown")
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain_id"] == "unknown"
    assert isinstance(data["skills"], list)
    assert data["total"] >= 0


@pytest.mark.asyncio
async def test_get_skill_detail_preview_status(client):
    resp = await client.get("/api/v3/skills/fidic_search_er")
    assert resp.status_code == 200
    data = resp.json()
    assert data["skill_id"] == "fidic_search_er"
    assert data["status"] == "active"
    assert data["backend"] == "local"
