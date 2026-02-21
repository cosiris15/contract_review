"""Skill dispatcher."""

from __future__ import annotations

import importlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .schema import GenericSkillInput, SkillBackend, SkillExecutor, SkillRegistration, SkillResult

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
        raw_result = await self.refly_client.poll_result(task_id)
        # poll_result 返回 {"content": "JSON文本", "output": [...]}
        # 下游期望的是解析后的 dict（如 {"relevant_sections": [...]}）
        content = raw_result.get("content", "")
        if content:
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Refly workflow %s 输出非 JSON，原样返回", self.workflow_id)
        return raw_result


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

    def get_tool_definitions(
        self,
        *,
        domain_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
    ) -> List[dict]:
        from .tool_adapter import skills_to_tool_definitions

        return skills_to_tool_definitions(
            self.list_skills(),
            domain_filter=domain_filter,
            category_filter=category_filter,
        )

    async def prepare_and_call(
        self,
        skill_id: str,
        clause_id: str,
        primary_structure: Any,
        state: dict,
        *,
        llm_arguments: Optional[dict] = None,
    ) -> SkillResult:
        registration = self.get_registration(skill_id)
        if registration is None:
            return SkillResult(skill_id=skill_id, success=False, error=f"Skill '{skill_id}' 未注册")

        input_data: BaseModel | None = None

        if registration.prepare_input_fn:
            try:
                prepare_fn = _import_handler(registration.prepare_input_fn)
                prepared = prepare_fn(clause_id, primary_structure, state)
                if isinstance(prepared, BaseModel):
                    if llm_arguments:
                        payload = prepared.model_dump()
                        for key, value in llm_arguments.items():
                            if key in payload:
                                payload[key] = value
                        input_data = prepared.__class__(**payload)
                    else:
                        input_data = prepared
            except Exception as exc:
                logger.warning("prepare_input 调用失败 (skill=%s): %s", skill_id, exc)

        if input_data is None:
            input_data = GenericSkillInput(
                clause_id=clause_id,
                document_structure=primary_structure,
                state_snapshot=llm_arguments or {},
            )

        return await self.call(skill_id, input_data)

    def get_registration(self, skill_id: str) -> Optional[SkillRegistration]:
        return self._registrations.get(skill_id)

    def list_skills(self) -> List[SkillRegistration]:
        return list(self._registrations.values())

    @property
    def skill_ids(self) -> List[str]:
        return list(self._registrations.keys())
