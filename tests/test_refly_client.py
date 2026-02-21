import pytest

from contract_review.skills.refly_client import ReflyClient, ReflyClientConfig, ReflyClientError


class _MockResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            req = httpx.Request("GET", "https://api.refly.ai")
            resp = httpx.Response(self.status_code, request=req, text=self.text or "error")
            raise httpx.HTTPStatusError("error", request=req, response=resp)


class _MockAsyncClient:
    def __init__(self, post_responses=None, get_responses=None, raise_request_error=False, **kwargs):
        _ = kwargs
        self.post_responses = list(post_responses or [])
        self.get_responses = list(get_responses or [])
        self.raise_request_error = raise_request_error
        self.is_closed = False

    async def post(self, *_args, **_kwargs):
        if self.raise_request_error:
            import httpx

            raise httpx.RequestError("network", request=httpx.Request("POST", "https://api.refly.ai"))
        return self.post_responses.pop(0)

    async def get(self, *_args, **_kwargs):
        if self.raise_request_error:
            import httpx

            raise httpx.RequestError("network", request=httpx.Request("GET", "https://api.refly.ai"))
        return self.get_responses.pop(0)

    async def aclose(self):
        self.is_closed = True


@pytest.mark.asyncio
async def test_call_workflow_success(monkeypatch):
    mock = _MockAsyncClient(
        post_responses=[_MockResponse(payload={"success": True, "data": {"executionId": "exe_123"}})]
    )
    monkeypatch.setattr(
        "contract_review.skills.refly_client.httpx.AsyncClient",
        lambda **kwargs: _MockAsyncClient(post_responses=mock.post_responses, **kwargs),
    )

    client = ReflyClient(ReflyClientConfig(api_key="k"))
    task_id = await client.call_workflow("wf_1", {"x": 1})
    assert task_id == "exe_123"


@pytest.mark.asyncio
async def test_call_workflow_not_success(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.refly_client.httpx.AsyncClient",
        lambda **kwargs: _MockAsyncClient(
            post_responses=[_MockResponse(payload={"success": False, "errMsg": "bad request"})],
            **kwargs,
        ),
    )

    client = ReflyClient(ReflyClientConfig(api_key="k"))
    with pytest.raises(ReflyClientError, match="调用失败"):
        await client.call_workflow("wf_1", {})


@pytest.mark.asyncio
async def test_call_workflow_http_error(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.refly_client.httpx.AsyncClient",
        lambda **kwargs: _MockAsyncClient(post_responses=[_MockResponse(status_code=500, text="boom")], **kwargs),
    )

    client = ReflyClient(ReflyClientConfig(api_key="k"))
    with pytest.raises(ReflyClientError):
        await client.call_workflow("wf_1", {})


@pytest.mark.asyncio
async def test_poll_result_completed(monkeypatch):
    responses = [
        _MockResponse(payload={"data": {"status": "executing"}}),
        _MockResponse(payload={"data": {"status": "finish"}}),
    ]
    output_responses = [
        _MockResponse(
            payload={
                "data": {
                    "output": [
                        {"messages": [{"content": "first"}]},
                        {"messages": [{"content": "second"}]},
                    ]
                }
            }
        )
    ]
    get_responses = responses + output_responses
    monkeypatch.setattr(
        "contract_review.skills.refly_client.httpx.AsyncClient",
        lambda **kwargs: _MockAsyncClient(get_responses=get_responses, **kwargs),
    )

    client = ReflyClient(ReflyClientConfig(api_key="k", poll_interval=1, max_poll_attempts=3))
    result = await client.poll_result("task_1", timeout=3)
    assert result["content"] == "first\n\nsecond"
    assert isinstance(result["output"], list)


@pytest.mark.asyncio
async def test_poll_result_failed_status(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.refly_client.httpx.AsyncClient",
        lambda **kwargs: _MockAsyncClient(
            get_responses=[_MockResponse(payload={"data": {"status": "failed", "error": "x"}})],
            **kwargs,
        ),
    )

    client = ReflyClient(ReflyClientConfig(api_key="k", poll_interval=1, max_poll_attempts=2))
    with pytest.raises(ReflyClientError):
        await client.poll_result("task_1", timeout=2)


@pytest.mark.asyncio
async def test_poll_result_timeout(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.refly_client.httpx.AsyncClient",
        lambda **kwargs: _MockAsyncClient(
            get_responses=[_MockResponse(payload={"data": {"status": "executing"}})] * 4,
            **kwargs,
        ),
    )

    client = ReflyClient(ReflyClientConfig(api_key="k", poll_interval=1, max_poll_attempts=2))
    with pytest.raises(ReflyClientError, match="超时"):
        await client.poll_result("task_1", timeout=2)


@pytest.mark.asyncio
async def test_poll_result_task_not_found(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.refly_client.httpx.AsyncClient",
        lambda **kwargs: _MockAsyncClient(get_responses=[_MockResponse(status_code=404, text="not found")], **kwargs),
    )

    client = ReflyClient(ReflyClientConfig(api_key="k", poll_interval=1, max_poll_attempts=1))
    with pytest.raises(ReflyClientError) as exc:
        await client.poll_result("task_404", timeout=1)
    assert exc.value.status_code == 404
