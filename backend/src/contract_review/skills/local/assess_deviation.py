"""Local skill: assess clause deviation against matched review criteria."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ...plugins.registry import get_baseline_text
from ._utils import get_llm_client
from ._utils import get_clause_text

logger = logging.getLogger(__name__)

_DEVIATION_LEVELS = {"none", "minor", "major", "critical", "unknown"}
_RISK_LEVELS = {"low", "medium", "high", "critical", "unknown"}


class AssessDeviationInput(BaseModel):
    clause_id: str
    clause_text: str
    baseline_text: str = ""
    review_criteria: List[dict] = Field(default_factory=list)
    domain_id: str = ""


class DeviationItem(BaseModel):
    criterion_id: str
    review_point: str = ""
    deviation_level: str = "unknown"
    risk_level: str = "unknown"
    rationale: str = ""
    suggested_action: str = ""
    confidence: float = 0.0


class AssessDeviationOutput(BaseModel):
    clause_id: str
    deviations: List[DeviationItem] = Field(default_factory=list)
    total_assessed: int = 0
    major_count: int = 0
    has_criteria: bool = False
    llm_used: bool = False
    analysis_method: str = "llm_structured_reasoning"


def _match_criteria_for_clause(criteria_data: Any, clause_id: str) -> list[dict]:
    if not isinstance(criteria_data, list):
        return []
    current = str(clause_id or "").strip()
    if not current:
        return []

    matched: list[dict] = []
    for row in criteria_data:
        if not isinstance(row, dict):
            continue
        candidate = str(row.get("clause_ref", "") or "").strip()
        if not candidate:
            continue
        if candidate == current or current.startswith(f"{candidate}.") or candidate.startswith(f"{current}."):
            matched.append(row)
    return matched


def _normalize_level(value: str, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower()
    return lowered if lowered in allowed else default


def _clamp_confidence(value: Any) -> float:
    try:
        score = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, score))


def _build_prompt(input_data: AssessDeviationInput) -> List[Dict[str, str]]:
    criteria_lines: List[str] = []
    for row in input_data.review_criteria:
        if not isinstance(row, dict):
            continue
        criteria_lines.append(
            "\n".join(
                [
                    f"- criterion_id: {row.get('criterion_id', '')}",
                    f"  review_point: {row.get('review_point', '')}",
                    f"  risk_level: {row.get('risk_level', '')}",
                    f"  baseline_text: {row.get('baseline_text', '')}",
                    f"  suggested_action: {row.get('suggested_action', '')}",
                ]
            )
        )

    system = (
        "你是一位资深合同审查律师。请严格对照审核标准评估条款偏离程度。"
        "你必须只输出 JSON 数组，不得输出额外文本。"
        "每个元素字段：criterion_id, review_point, deviation_level, risk_level, rationale, suggested_action, confidence。"
        "deviation_level 仅可取 none|minor|major|critical|unknown。"
        "risk_level 仅可取 low|medium|high|critical|unknown。"
        "confidence 为 0 到 1 的数字。"
    )
    user = (
        f"domain_id: {input_data.domain_id}\n"
        f"clause_id: {input_data.clause_id}\n"
        f"clause_text:\n{input_data.clause_text}\n\n"
        f"baseline_text:\n{input_data.baseline_text}\n\n"
        f"matched_review_criteria:\n{chr(10).join(criteria_lines)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _extract_json(raw_text: str) -> List[Dict[str, Any]]:
    payload = (raw_text or "").strip()
    if not payload:
        return []

    candidates = [payload]
    block = re.search(r"```(?:json)?\s*(.*?)```", payload, re.DOTALL | re.IGNORECASE)
    if block:
        candidates.append(block.group(1).strip())

    bracket_match = re.search(r"\[.*\]", payload, re.DOTALL)
    if bracket_match:
        candidates.append(bracket_match.group(0).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _fallback_assessment(input_data: AssessDeviationInput, reason: str) -> AssessDeviationOutput:
    deviations: list[DeviationItem] = []
    for row in input_data.review_criteria:
        if not isinstance(row, dict):
            continue
        deviations.append(
            DeviationItem(
                criterion_id=str(row.get("criterion_id", "") or ""),
                review_point=str(row.get("review_point", "") or ""),
                deviation_level="unknown",
                risk_level=_normalize_level(row.get("risk_level", ""), _RISK_LEVELS, "unknown"),
                rationale=reason,
                suggested_action=str(row.get("suggested_action", "") or ""),
                confidence=0.0,
            )
        )
    return AssessDeviationOutput(
        clause_id=input_data.clause_id,
        deviations=deviations,
        total_assessed=len(deviations),
        major_count=0,
        has_criteria=bool(input_data.review_criteria),
        llm_used=False,
    )


async def assess_deviation(input_data: AssessDeviationInput) -> AssessDeviationOutput:
    if not input_data.review_criteria:
        return AssessDeviationOutput(
            clause_id=input_data.clause_id,
            has_criteria=False,
            llm_used=False,
        )
    if not input_data.clause_text.strip():
        return _fallback_assessment(input_data, "条款文本为空，无法评估偏离程度。")

    llm_client = get_llm_client()
    if llm_client is None:
        return _fallback_assessment(input_data, "LLM 客户端不可用，已降级为待人工判断。")

    try:
        response = await llm_client.chat(_build_prompt(input_data), max_output_tokens=1500)
        parsed_rows = _extract_json(response)
    except Exception as exc:
        logger.warning("assess_deviation LLM 调用失败: %s", exc)
        return _fallback_assessment(input_data, "LLM 调用失败，已降级为待人工判断。")

    if not parsed_rows:
        return _fallback_assessment(input_data, "LLM 未返回可解析 JSON，已降级为待人工判断。")

    parsed_by_id: dict[str, dict[str, Any]] = {}
    for row in parsed_rows:
        criterion_id = str(row.get("criterion_id", "") or "").strip()
        if criterion_id:
            parsed_by_id[criterion_id] = row

    deviations: list[DeviationItem] = []
    for criterion in input_data.review_criteria:
        if not isinstance(criterion, dict):
            continue
        criterion_id = str(criterion.get("criterion_id", "") or "")
        parsed = parsed_by_id.get(criterion_id, {})
        deviations.append(
            DeviationItem(
                criterion_id=criterion_id,
                review_point=str(parsed.get("review_point", "") or criterion.get("review_point", "")),
                deviation_level=_normalize_level(
                    parsed.get("deviation_level", ""),
                    _DEVIATION_LEVELS,
                    "unknown",
                ),
                risk_level=_normalize_level(
                    parsed.get("risk_level", ""),
                    _RISK_LEVELS,
                    _normalize_level(criterion.get("risk_level", ""), _RISK_LEVELS, "unknown"),
                ),
                rationale=str(parsed.get("rationale", "") or ""),
                suggested_action=str(
                    parsed.get("suggested_action", "") or criterion.get("suggested_action", "")
                ),
                confidence=_clamp_confidence(parsed.get("confidence", 0.0)),
            )
        )

    major_count = sum(1 for item in deviations if item.deviation_level in {"major", "critical"})
    return AssessDeviationOutput(
        clause_id=input_data.clause_id,
        deviations=deviations,
        total_assessed=len(deviations),
        major_count=major_count,
        has_criteria=True,
        llm_used=True,
    )


def prepare_input(clause_id: str, primary_structure: Any, state: dict) -> AssessDeviationInput:
    return AssessDeviationInput(
        clause_id=clause_id,
        clause_text=get_clause_text(primary_structure, clause_id),
        baseline_text=get_baseline_text(state.get("domain_id", ""), clause_id) or "",
        review_criteria=_match_criteria_for_clause(state.get("criteria_data", []), clause_id),
        domain_id=state.get("domain_id", ""),
    )
