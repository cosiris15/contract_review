"""
Skill framework core types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel, Field


class SkillBackend(str, Enum):
    """Skill execution backend."""

    REFLY = "refly"
    LOCAL = "local"


class SkillRegistration(BaseModel):
    """Skill registration payload."""

    skill_id: str
    name: str
    description: str = ""
    input_schema: Optional[Type[BaseModel]] = None
    output_schema: Optional[Type[BaseModel]] = None
    backend: SkillBackend
    refly_workflow_id: Optional[str] = None
    local_handler: Optional[str] = None
    domain: str = "*"
    category: str = "general"
    status: str = "active"
    parameters_schema: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )
    prepare_input_fn: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    def to_tool_definition(self) -> dict:
        internal_fields = {"document_structure", "state_snapshot", "criteria_data", "criteria_file_path"}

        parameters = self.parameters_schema if isinstance(self.parameters_schema, dict) else {}
        if not isinstance(parameters.get("properties"), dict):
            parameters = {}
        if parameters:
            parameters = {
                "type": str(parameters.get("type", "object") or "object"),
                "properties": dict(parameters.get("properties", {})),
                "required": list(parameters.get("required", [])),
            }
        elif self.input_schema is not None:
            try:
                schema = self.input_schema.model_json_schema()
                parameters = {
                    "type": "object",
                    "properties": dict(schema.get("properties", {})),
                    "required": list(schema.get("required", [])),
                }
            except Exception:
                parameters = {"type": "object", "properties": {}, "required": []}
        else:
            parameters = {"type": "object", "properties": {}, "required": []}

        props = parameters.get("properties", {})
        required = parameters.get("required", [])
        for field_name in internal_fields:
            props.pop(field_name, None)
            if field_name in required:
                required.remove(field_name)

        return {
            "type": "function",
            "function": {
                "name": self.skill_id,
                "description": self.description,
                "parameters": parameters,
            },
        }


class SkillExecutor(ABC):
    """Abstract executor contract."""

    @abstractmethod
    async def execute(self, input_data: BaseModel) -> Any:
        ...


class SkillResult(BaseModel):
    """Unified skill execution result."""

    skill_id: str
    success: bool = True
    data: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: Optional[int] = None


class GenericSkillInput(BaseModel):
    """Generic input payload for skills without dedicated schema."""

    clause_id: str
    document_structure: Any = None
    state_snapshot: Dict[str, Any] = Field(default_factory=dict)
