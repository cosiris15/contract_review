"""Refly client (stub)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ReflyClientConfig(BaseModel):
    base_url: str = "https://api.refly.ai"
    api_key: str = ""
    timeout: int = 120
    poll_interval: int = 2
    max_poll_attempts: int = 60


class ReflyClient:
    """Stubbed Refly client for skeleton stage."""

    def __init__(self, config: ReflyClientConfig):
        self.config = config
        self._session = None

    async def call_workflow(self, workflow_id: str, input_data: Dict[str, Any]) -> str:
        logger.warning("[STUB] ReflyClient.call_workflow(%s)", workflow_id)
        _ = input_data
        return f"stub_task_{workflow_id}"

    async def poll_result(self, task_id: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        logger.warning("[STUB] ReflyClient.poll_result(%s)", task_id)
        _ = timeout
        return {"status": "completed", "result": {}, "task_id": task_id}

    async def close(self):
        if self._session:
            await self._session.aclose()
            self._session = None
