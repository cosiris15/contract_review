"""Adapter: convert registered skills to OpenAI tool definitions."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .schema import SkillRegistration

logger = logging.getLogger(__name__)

INTERNAL_FIELDS = frozenset(
    {
        "document_structure",
        "state_snapshot",
        "criteria_data",
        "criteria_file_path",
    }
)


def skills_to_tool_definitions(
    skills: List[SkillRegistration],
    *,
    domain_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    exclude_internal_fields: frozenset[str] = INTERNAL_FIELDS,
) -> List[dict]:
    tools: List[dict] = []
    _ = exclude_internal_fields
    for skill in skills:
        if getattr(skill, "status", "active") != "active":
            continue
        if domain_filter and getattr(skill, "domain", "*") not in {"*", domain_filter}:
            continue
        if category_filter and getattr(skill, "category", "general") != category_filter:
            continue

        tools.append(skill.to_tool_definition())
    return tools


def parse_tool_calls(tool_calls: List[dict]) -> List[Dict[str, Any]]:
    parsed: List[Dict[str, Any]] = []
    for row in tool_calls:
        func = row.get("function", {}) if isinstance(row, dict) else {}
        skill_id = str(func.get("name", "") or "")
        raw_args = func.get("arguments", "{}")
        arguments: Dict[str, Any] = {}
        if isinstance(raw_args, dict):
            arguments = raw_args
        elif isinstance(raw_args, str):
            try:
                loaded = json.loads(raw_args or "{}")
                arguments = loaded if isinstance(loaded, dict) else {}
            except (json.JSONDecodeError, TypeError):
                logger.warning("tool_call 参数解析失败: skill=%s", skill_id)
        parsed.append(
            {
                "id": str(row.get("id", "") if isinstance(row, dict) else ""),
                "skill_id": skill_id,
                "arguments": arguments,
            }
        )
    return parsed
