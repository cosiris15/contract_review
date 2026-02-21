"""Local FIDIC skill: extract and analyze time-bar requirements."""

from __future__ import annotations

import re
from typing import Any, List

from pydantic import BaseModel, Field

from ..local._utils import get_clause_text


class CalculateTimeBarInput(BaseModel):
    clause_id: str
    document_structure: Any


class TimeBarItem(BaseModel):
    trigger_event: str = ""
    deadline_days: int
    deadline_text: str
    action_required: str = ""
    consequence: str = ""
    context: str = ""


class CalculateTimeBarOutput(BaseModel):
    clause_id: str
    time_bars: List[TimeBarItem] = Field(default_factory=list)
    total_time_bars: int = 0
    has_strict_time_bar: bool = False


_TIME_BAR_PATTERNS = [
    (r"within\s+(\d+)\s*(?:calendar\s+)?days?\b", "en"),
    (r"not\s+later\s+than\s+(\d+)\s*days?\b", "en"),
    (r"(\d+)\s*days?\s*(?:after|from|of)\b", "en"),
    (r"(\d+)\s*(?:个工作日|天|日)内", "zh"),
    (r"不迟于.{0,20}?(\d+)\s*(?:天|日)", "zh"),
]

_STRICT_KEYWORDS = [
    "shall not be entitled",
    "deemed to have waived",
    "time-barred",
    "forfeited",
    "丧失权利",
    "视为放弃",
]


def _extract_trigger(context: str) -> str:
    patterns = [
        r"(?:after|from|upon)\s+([^,.;]{5,80})",
        r"(?:自|在).{0,12}?(?:后|起)([^，。；]{2,40})",
    ]
    for pattern in patterns:
        match = re.search(pattern, context, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def _extract_action(context: str) -> str:
    patterns = [
        r"(?:shall|must)\s+([^,.;]{4,80})",
        r"(?:应当|应|须)\s*([^，。；]{2,40})",
    ]
    for pattern in patterns:
        match = re.search(pattern, context, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def _extract_consequence(context: str) -> str:
    patterns = [
        r"(?:otherwise|failing\s+which)\s+([^.;]{4,100})",
        r"(?:否则|逾期).{0,30}",
    ]
    for pattern in patterns:
        match = re.search(pattern, context, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


async def calculate(input_data: CalculateTimeBarInput) -> CalculateTimeBarOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    time_bars: List[TimeBarItem] = []

    for pattern, _lang in _TIME_BAR_PATTERNS:
        for match in re.finditer(pattern, clause_text, re.IGNORECASE):
            days = int(match.group(1))
            start = max(0, match.start() - 80)
            end = min(len(clause_text), match.end() + 80)
            context = clause_text[start:end].strip()

            time_bars.append(
                TimeBarItem(
                    trigger_event=_extract_trigger(context),
                    deadline_days=days,
                    deadline_text=match.group(0),
                    action_required=_extract_action(context),
                    consequence=_extract_consequence(context),
                    context=context,
                )
            )

    lower_text = clause_text.lower()
    has_strict = any(keyword.lower() in lower_text for keyword in _STRICT_KEYWORDS)

    return CalculateTimeBarOutput(
        clause_id=input_data.clause_id,
        time_bars=time_bars,
        total_time_bars=len(time_bars),
        has_strict_time_bar=has_strict,
    )


def prepare_input(clause_id: str, primary_structure: Any, _state: dict) -> CalculateTimeBarInput:
    return CalculateTimeBarInput(
        clause_id=clause_id,
        document_structure=primary_structure,
    )
