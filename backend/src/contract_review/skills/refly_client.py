"""Refly API client."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ReflyClientConfig(BaseModel):
    base_url: str = "https://api.refly.ai"
    api_key: str = ""
    timeout: int = 120
    poll_interval: int = 2
    max_poll_attempts: int = 60


class ReflyClientError(Exception):
    """Refly API exception."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ReflyClient:
    """Real Refly client with workflow execution and polling."""

    def __init__(self, config: ReflyClientConfig):
        self.config = config
        self._session: httpx.AsyncClient | None = None

    def _get_session(self) -> httpx.AsyncClient:
        if self._session is None or self._session.is_closed:
            self._session = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.config.timeout),
            )
        return self._session

    async def call_workflow(self, workflow_id: str, input_data: Dict[str, Any]) -> str:
        session = self._get_session()
        try:
            response = await session.post(
                f"/v1/workflows/{workflow_id}/run",
                json={"input": input_data},
            )
            response.raise_for_status()
            data = response.json()
            task_id = data.get("task_id") or data.get("id", "")
            if not task_id:
                raise ReflyClientError("Refly 返回中缺少 task_id")
            logger.info("Refly workflow %s 已触发，task_id=%s", workflow_id, task_id)
            return task_id
        except httpx.HTTPStatusError as exc:
            raise ReflyClientError(
                f"Refly API 错误: {exc.response.status_code} {exc.response.text[:200]}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise ReflyClientError(f"Refly 网络错误: {exc}") from exc

    async def poll_result(self, task_id: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        session = self._get_session()
        max_attempts = (timeout or self.config.timeout) // self.config.poll_interval
        max_attempts = min(max_attempts, self.config.max_poll_attempts)
        consecutive_network_errors = 0

        for attempt in range(max_attempts):
            try:
                response = await session.get(f"/v1/tasks/{task_id}")
                response.raise_for_status()
                data = response.json()
                status = str(data.get("status", "")).lower()
                consecutive_network_errors = 0

                if status == "completed":
                    logger.info("Refly task %s 完成", task_id)
                    return data.get("result", {})
                if status in {"failed", "error", "cancelled"}:
                    error_message = data.get("error", "未知错误")
                    raise ReflyClientError(f"Refly task 失败: {error_message}")

                await asyncio.sleep(self.config.poll_interval)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise ReflyClientError(f"Task {task_id} 不存在", status_code=404) from exc
                raise ReflyClientError(
                    f"轮询错误: {exc.response.status_code}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.RequestError as exc:
                consecutive_network_errors += 1
                if consecutive_network_errors >= 3:
                    raise ReflyClientError(
                        f"连续 {consecutive_network_errors} 次网络错误: {exc}"
                    ) from exc
                logger.warning("轮询网络错误（第 %d 次）: %s", attempt + 1, exc)
                await asyncio.sleep(self.config.poll_interval)

        raise ReflyClientError(f"Refly task {task_id} 轮询超时（{max_attempts} 次）")

    async def close(self):
        if self._session and not self._session.is_closed:
            await self._session.aclose()
            self._session = None
