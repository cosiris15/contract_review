"""Skill dispatcher."""

from __future__ import annotations

import importlib
import logging
import time
from typing import Dict, List, Optional

from pydantic import BaseModel

from .schema import SkillBackend, SkillExecutor, SkillRegistration, SkillResult

logger = logging.getLogger(__name__)


class LocalSkillExecutor(SkillExecutor):
    """Local Python executor."""

    def __init__(self, handler_fn):
        self.handler_fn = handler_fn

    async def execute(self, input_data: BaseModel):
        return await self.handler_fn(input_data)


class ReflySkillExecutor(SkillExecutor):
    """Remote Refly executor."""

    def __init__(self, refly_client, workflow_id: str):
        self.refly_client = refly_client
        self.workflow_id = workflow_id

    async def execute(self, input_data: BaseModel):
        task_id = await self.refly_client.call_workflow(
            self.workflow_id, input_data.model_dump() if isinstance(input_data, BaseModel) else input_data
        )
        return await self.refly_client.poll_result(task_id)


def _import_handler(handler_path: str):
    """Dynamically import a local handler."""

    module_path, func_name = handler_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    handler = getattr(module, func_name)
    if not callable(handler):
        raise TypeError(f"{handler_path} 不是可调用对象")
    return handler


class SkillDispatcher:
    """Unified skill calling entry."""

    def __init__(self, refly_client=None):
        self.refly_client = refly_client
        self._executors: Dict[str, SkillExecutor] = {}
        self._registrations: Dict[str, SkillRegistration] = {}

    def register(self, skill: SkillRegistration) -> None:
        if skill.backend == SkillBackend.REFLY:
            if not skill.refly_workflow_id:
                raise ValueError(f"Refly Skill '{skill.skill_id}' 缺少 refly_workflow_id")
            if not self.refly_client:
                raise ValueError(f"注册 Refly Skill '{skill.skill_id}' 时 refly_client 未提供")
            self._executors[skill.skill_id] = ReflySkillExecutor(
                self.refly_client, skill.refly_workflow_id
            )
        elif skill.backend == SkillBackend.LOCAL:
            if not skill.local_handler:
                raise ValueError(f"Local Skill '{skill.skill_id}' 缺少 local_handler")
            handler = _import_handler(skill.local_handler)
            self._executors[skill.skill_id] = LocalSkillExecutor(handler)
        self._registrations[skill.skill_id] = skill
        logger.info("Skill 已注册: %s [backend=%s]", skill.skill_id, skill.backend.value)

    def register_batch(self, skills: List[SkillRegistration]) -> None:
        for skill in skills:
            self.register(skill)

    async def call(self, skill_id: str, input_data: BaseModel) -> SkillResult:
        executor = self._executors.get(skill_id)
        if not executor:
            raise ValueError(f"Skill '{skill_id}' 未注册")

        start = time.monotonic()
        try:
            result = await executor.execute(input_data)
            elapsed = int((time.monotonic() - start) * 1000)
            return SkillResult(
                skill_id=skill_id,
                success=True,
                data=result.model_dump() if isinstance(result, BaseModel) else result,
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.error("Skill '%s' 执行失败 (%sms): %s", skill_id, elapsed, exc)
            return SkillResult(
                skill_id=skill_id,
                success=False,
                error=str(exc),
                execution_time_ms=elapsed,
            )

    def get_registration(self, skill_id: str) -> Optional[SkillRegistration]:
        return self._registrations.get(skill_id)

    def list_skills(self) -> List[SkillRegistration]:
        return list(self._registrations.values())

    @property
    def skill_ids(self) -> List[str]:
        return list(self._registrations.keys())
