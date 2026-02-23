import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytest.importorskip("langgraph")

from contract_review.api_gen3 import _find_clause_in_dict


class TestFindClauseInDict:
    def test_find_top_level_clause(self):
        clauses = [
            {"clause_id": "1.1", "title": "Definitions", "text": "A", "children": []},
            {"clause_id": "1.2", "title": "Scope", "text": "B", "children": []},
        ]
        result = _find_clause_in_dict(clauses, "1.2")
        assert result is not None
        assert result.get("title") == "Scope"

    def test_find_nested_clause(self):
        clauses = [
            {
                "clause_id": "1",
                "title": "General",
                "text": "",
                "children": [
                    {"clause_id": "1.1", "title": "Child", "text": "Nested text", "children": []}
                ],
            }
        ]
        result = _find_clause_in_dict(clauses, "1.1")
        assert result is not None
        assert result.get("text") == "Nested text"

    def test_find_clause_not_found(self):
        clauses = [{"clause_id": "1.1", "children": []}]
        result = _find_clause_in_dict(clauses, "9.9")
        assert result is None


@pytest.fixture
def app():
    from fastapi import FastAPI

    from contract_review.api_gen3 import _active_graphs, router

    test_app = FastAPI()
    test_app.include_router(router)
    _active_graphs.clear()
    return test_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestClauseContextEndpoint:
    @pytest.mark.asyncio
    async def test_get_clause_context_success(self, client):
        from contract_review.api_gen3 import _active_graphs

        _active_graphs["ctx_ok"] = {
            "graph": None,
            "config": {},
            "last_access_ts": 0,
            "primary_structure": {
                "clauses": [
                    {
                        "clause_id": "1.1",
                        "title": "Definitions",
                        "text": "Top text",
                        "level": 1,
                        "start_offset": 10,
                        "end_offset": 30,
                        "children": [
                            {
                                "clause_id": "1.1.1",
                                "title": "Nested",
                                "text": "Nested clause text",
                                "level": 2,
                                "start_offset": 31,
                                "end_offset": 60,
                                "children": [],
                            }
                        ],
                    }
                ]
            },
            "documents": [],
        }

        resp = await client.get("/api/v3/review/ctx_ok/clause/1.1.1/context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["clause_id"] == "1.1.1"
        assert data["title"] == "Nested"
        assert data["text"] == "Nested clause text"
        assert data["level"] == 2

    @pytest.mark.asyncio
    async def test_get_clause_context_clause_not_found(self, client):
        from contract_review.api_gen3 import _active_graphs

        _active_graphs["ctx_missing_clause"] = {
            "graph": None,
            "config": {},
            "last_access_ts": 0,
            "primary_structure": {"clauses": [{"clause_id": "1.1", "children": []}]},
            "documents": [],
        }

        resp = await client.get("/api/v3/review/ctx_missing_clause/clause/9.9/context")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_clause_context_task_not_found(self, client):
        resp = await client.get("/api/v3/review/ctx_missing_task/clause/1.1/context")
        assert resp.status_code == 404
