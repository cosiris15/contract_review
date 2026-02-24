"""Local FIDIC skill: extract and analyze time-bar requirements."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..local._utils import get_clause_text, get_llm_client


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
    source: str = "regex"
    strictness_level: str = ""
    risk_assessment: str = ""


class CalculateTimeBarOutput(BaseModel):
    clause_id: str
    time_bars: List[TimeBarItem] = Field(default_factory=list)
    total_time_bars: int = 0
    has_strict_time_bar: bool = False
    llm_used: bool = False


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
_STRICTNESS_LEVELS = {"hard_bar", "soft_bar", "advisory"}

TIME_BAR_SYSTEM_PROMPT = (
    "你是 FIDIC 合同时限条款分析专家。请分析以下条款中的所有时限要求。\n"
    "已由规则引擎提取的时限会提供给你。请：\n"
    "1. 对已提取的时限补充缺失信息（触发条件、行动要求、后果）\n"
    "2. 发现规则遗漏的时限要求（包括文字表述的时限如'a reasonable period'）\n"
    "3. 对每个时限判断严格程度\n\n"
    "只返回 JSON 对象，不得输出额外文本。格式：\n"
    "{\n"
    '  "enrichments": [\n'
    '    {"deadline_days": 28, "trigger_event": "...", "action_required": "...", '
    '"consequence": "...", "strictness_level": "hard_bar|soft_bar|advisory", '
    '"risk_assessment": "..."}\n'
    "  ],\n"
    '  "discoveries": [\n'
    '    {"deadline_days": 0, "deadline_text": "a reasonable period", '
    '"trigger_event": "...", "action_required": "...", "consequence": "...", '
    '"strictness_level": "...", "risk_assessment": "..."}\n'
    "  ]\n"
    "}\n"
    "enrichments 按 deadline_days 与已提取项对应。\n"
    "discoveries 中 deadline_days 为 0 表示非数字时限。"
)


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


def _normalize_strictness(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in _STRICTNESS_LEVELS else ""


def _parse_json_object(raw_text: str) -> Any:
    payload = (raw_text or "").strip()
    if not payload:
        return None

    candidates = [payload]
    block = re.search(r"```(?:json)?\s*(.*?)```", payload, re.DOTALL | re.IGNORECASE)
    if block:
        candidates.append(block.group(1).strip())

    object_match = re.search(r"\{.*\}", payload, re.DOTALL)
    if object_match:
        candidates.append(object_match.group(0).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _build_time_bar_prompt(clause_text: str, regex_items: List[TimeBarItem]) -> List[Dict[str, str]]:
    existing = "\n".join(
        f"- {item.deadline_text} (days={item.deadline_days}), "
        f"trigger={item.trigger_event or '未知'}, "
        f"consequence={item.consequence or '未知'}"
        for item in regex_items
    ) or "（无）"
    user_msg = (
        f"条款文本：\n{clause_text[:3000]}\n\n"
        f"已提取的时限：\n{existing}"
    )
    return [
        {"role": "system", "content": TIME_BAR_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]


def _extract_time_bars_regex(clause_text: str) -> List[TimeBarItem]:
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
                    source="regex",
                )
            )
    return time_bars


async def _llm_enrich_and_discover(
    clause_text: str,
    regex_items: List[TimeBarItem],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    llm_client = get_llm_client()
    if llm_client is None:
        return [], [], False
    try:
        response = await llm_client.chat(
            _build_time_bar_prompt(clause_text, regex_items),
            max_output_tokens=1000,
        )
    except Exception:  # pragma: no cover - defensive
        return [], [], False

    parsed = _parse_json_object(str(response))
    if not isinstance(parsed, dict):
        return [], [], False

    enrichments = parsed.get("enrichments", [])
    discoveries = parsed.get("discoveries", [])
    if not isinstance(enrichments, list):
        enrichments = []
    if not isinstance(discoveries, list):
        discoveries = []
    return [e for e in enrichments if isinstance(e, dict)], [d for d in discoveries if isinstance(d, dict)], True


def _apply_enrichments(regex_items: List[TimeBarItem], enrichments: List[Dict[str, Any]]) -> None:
    enrich_by_days: dict[int, Dict[str, Any]] = {}
    for enrichment in enrichments:
        try:
            days = int(enrichment.get("deadline_days"))
        except Exception:
            continue
        if days not in enrich_by_days:
            enrich_by_days[days] = enrichment

    for item in regex_items:
        enrichment = enrich_by_days.get(item.deadline_days)
        if not enrichment:
            continue
        if not item.trigger_event:
            item.trigger_event = str(enrichment.get("trigger_event", "") or "")
        if not item.action_required:
            item.action_required = str(enrichment.get("action_required", "") or "")
        if not item.consequence:
            item.consequence = str(enrichment.get("consequence", "") or "")
        item.strictness_level = _normalize_strictness(enrichment.get("strictness_level", ""))
        item.risk_assessment = str(enrichment.get("risk_assessment", "") or "")


def _merge_discoveries(regex_items: List[TimeBarItem], discoveries: List[Dict[str, Any]]) -> List[TimeBarItem]:
    existing_days = {item.deadline_days for item in regex_items}
    merged = list(regex_items)
    for discovery in discoveries:
        try:
            days = int(discovery.get("deadline_days", 0))
        except Exception:
            days = 0
        if days != 0 and days in existing_days:
            continue
        merged.append(
            TimeBarItem(
                trigger_event=str(discovery.get("trigger_event", "") or ""),
                deadline_days=days,
                deadline_text=str(discovery.get("deadline_text", "") or ""),
                action_required=str(discovery.get("action_required", "") or ""),
                consequence=str(discovery.get("consequence", "") or ""),
                context="",
                source="llm",
                strictness_level=_normalize_strictness(discovery.get("strictness_level", "")),
                risk_assessment=str(discovery.get("risk_assessment", "") or ""),
            )
        )
        existing_days.add(days)
    return merged


async def calculate(input_data: CalculateTimeBarInput) -> CalculateTimeBarOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    time_bars = _extract_time_bars_regex(clause_text)
    enrichments, discoveries, llm_used = await _llm_enrich_and_discover(clause_text, time_bars)
    if llm_used:
        _apply_enrichments(time_bars, enrichments)
        time_bars = _merge_discoveries(time_bars, discoveries)

    lower_text = clause_text.lower()
    has_strict = any(keyword.lower() in lower_text for keyword in _STRICT_KEYWORDS) or any(
        item.strictness_level == "hard_bar" for item in time_bars
    )

    return CalculateTimeBarOutput(
        clause_id=input_data.clause_id,
        time_bars=time_bars,
        total_time_bars=len(time_bars),
        has_strict_time_bar=has_strict,
        llm_used=llm_used,
    )


def prepare_input(clause_id: str, primary_structure: Any, _state: dict) -> CalculateTimeBarInput:
    return CalculateTimeBarInput(
        clause_id=clause_id,
        document_structure=primary_structure,
    )
