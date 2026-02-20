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

    class Config:
        arbitrary_types_allowed = True


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
