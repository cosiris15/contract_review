import asyncio
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytest.importorskip("langgraph")


class _MockLLMClient:
    async def chat(self, messages, **kwargs):
        _ = kwargs
        system_prompt = messages[0]["content"] if messages else ""

        if "识别风险点" in system_prompt or "identify risk" in system_prompt.lower():
            return json.dumps(
                [
                    {
                        "risk_level": "high",
                        "risk_type": "付款条件",
                        "description": "预付款比例过高",
                        "reason": "预付款达到合同总价30%",
                        "analysis": "建议降低",
                        "original_text": "预付款为合同总价的30%",
                    }
                ],
                ensure_ascii=False,
            )

        if "文本修改建议" in system_prompt or "modification" in system_prompt.lower():
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

        if "质量检查员" in system_prompt or "quality" in system_prompt.lower():
            return json.dumps({"result": "pass", "issues": []}, ensure_ascii=False)

        if "结构化总结" in system_prompt or "summary" in system_prompt.lower():
            return "审查完成：发现1个高风险，已生成修改建议。"

        return "[]"


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setattr(
        "contract_review.graph.builder._get_llm_client",
        lambda: _MockLLMClient(),
    )


@pytest.fixture
def app(mock_llm):
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


async def _wait_for_interrupt_or_complete(client, task_id: str, timeout_steps: int = 40):
    for _ in range(timeout_steps):
        await asyncio.sleep(0.25)
        resp = await client.get(f"/api/v3/review/{task_id}/status")
        assert resp.status_code == 200
        status = resp.json()
        if status.get("is_complete") or status.get("is_interrupted"):
            return status
    pytest.fail(f"任务 {task_id} 超时未进入中断/完成状态")


async def _run_flow_and_complete(client, task_id: str):
    start = await client.post(
        "/api/v3/review/start",
        json={
            "task_id": task_id,
            "domain_id": "fidic",
            "auto_start": False,
            "our_party": "承包商",
            "language": "zh-CN",
        },
    )
    assert start.status_code == 200
    assert start.json()["status"] == "ready"

    contract_text = (
        "14.1 Contract Price\n"
        "The Contract Price shall be the lump sum amount.\n\n"
        "14.2 Advance Payment\n"
        "预付款为合同总价的30%，应在开工后14天内支付。\n\n"
        "17.6 Limitation of Liability\n"
        "The total liability shall not exceed the Contract Price.\n"
    ).encode("utf-8")
    files = {"file": ("contract.txt", contract_text, "text/plain")}
    upload = await client.post(
        f"/api/v3/review/{task_id}/upload",
        files=files,
        data={"role": "primary", "our_party": "承包商", "language": "zh-CN"},
    )
    assert upload.status_code == 200

    run = await client.post(f"/api/v3/review/{task_id}/run")
    assert run.status_code == 200

    for _ in range(40):
        status = await _wait_for_interrupt_or_complete(client, task_id, timeout_steps=1)
        if status.get("is_complete"):
            return
        pending_resp = await client.get(f"/api/v3/review/{task_id}/pending-diffs")
        assert pending_resp.status_code == 200
        pending = pending_resp.json().get("pending_diffs", [])
        if pending:
            approvals = [{"diff_id": d["diff_id"], "decision": "approve"} for d in pending]
            batch = await client.post(
                f"/api/v3/review/{task_id}/approve-batch",
                json={"approvals": approvals},
            )
            assert batch.status_code == 200
        resume = await client.post(f"/api/v3/review/{task_id}/resume")
        assert resume.status_code == 200

    final_status = await client.get(f"/api/v3/review/{task_id}/status")
    assert final_status.status_code == 200
    assert final_status.json().get("is_complete") is True


@pytest.mark.asyncio
async def test_full_review_flow_with_document(client):
    task_id = "e2e_001"
    await _run_flow_and_complete(client, task_id)

    status_resp = await client.get(f"/api/v3/review/{task_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["is_complete"] is True

    result_resp = await client.get(f"/api/v3/review/{task_id}/result")
    assert result_resp.status_code == 200
    result = result_resp.json()
    assert result["is_complete"] is True
    assert result["summary_notes"]
    assert result["total_risks"] >= 0


@pytest.mark.asyncio
async def test_clause_text_extraction_from_structure(client):
    task_id = "e2e_text"
    await client.post(
        "/api/v3/review/start",
        json={"task_id": task_id, "auto_start": False, "our_party": "承包商", "language": "zh-CN"},
    )
    contract_text = (
        "1.1 Definitions\n"
        "The Employer means the party named in the Contract Data.\n"
        "The Contractor means the party named in the Contract Data.\n"
    ).encode("utf-8")
    files = {"file": ("contract.txt", contract_text, "text/plain")}
    upload = await client.post(f"/api/v3/review/{task_id}/upload", files=files, data={"role": "primary"})
    assert upload.status_code == 200

    await client.post(f"/api/v3/review/{task_id}/run")
    status = await _wait_for_interrupt_or_complete(client, task_id)
    assert status["is_interrupted"] or status["is_complete"]

    pending_resp = await client.get(f"/api/v3/review/{task_id}/pending-diffs")
    assert pending_resp.status_code == 200
    pending = pending_resp.json().get("pending_diffs", [])
    if pending:
        sample = pending[0]
        assert sample.get("original_text") or sample.get("proposed_text")


def test_clause_text_helpers():
    from contract_review.graph.builder import _extract_clause_text, _search_clauses

    structure = {
        "clauses": [
            {"clause_id": "14.1", "text": "A", "children": []},
            {
                "clause_id": "14.2",
                "text": "Advance Payment parent",
                "children": [{"clause_id": "14.2.1", "text": "Advance Payment child", "children": []}],
            },
        ]
    }

    assert _search_clauses(structure["clauses"], "14.1") == "A"
    assert _search_clauses(structure["clauses"], "14.2.1") == "Advance Payment child"
    assert _search_clauses(structure["clauses"], "14.2") == "Advance Payment parent"
    assert _search_clauses(structure["clauses"], "14") in {"A", "Advance Payment parent"}
    assert _search_clauses(structure["clauses"], "99.9") == ""
    assert _extract_clause_text(None, "1.1") == ""
    assert _extract_clause_text(structure, "14.2.1") == "Advance Payment child"
    assert _extract_clause_text(structure, "88.1") == ""


@pytest.mark.asyncio
async def test_export_endpoint_after_completion(client):
    task_id = "e2e_export"
    await _run_flow_and_complete(client, task_id)
    resp = await client.post(f"/api/v3/review/{task_id}/export")
    # txt 源文档不支持 Word 红线导出，返回 400 为符合当前实现的行为
    assert resp.status_code == 400
    assert "docx" in resp.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_result_endpoint_fields(client):
    task_id = "e2e_result"
    await _run_flow_and_complete(client, task_id)

    resp = await client.get(f"/api/v3/review/{task_id}/result")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == task_id
    assert "is_complete" in data
    assert "summary_notes" in data
    assert "total_risks" in data
    assert "approved_count" in data
    assert "rejected_count" in data
