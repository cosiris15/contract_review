"""Orchestrator planning layer for review graph."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..llm_client import LLMClient
from .llm_utils import parse_json_response

logger = logging.getLogger(__name__)


class ClauseAnalysisPlan(BaseModel):
    clause_id: str
    clause_name: str = ""
    analysis_depth: str = "standard"  # quick|standard|deep
    suggested_tools: List[str] = Field(default_factory=list)
    max_iterations: int = 3
    priority_order: int = 0
    rationale: str = ""
    skip_diffs: bool = False
    skip_validate: bool = False


class ReviewPlan(BaseModel):
    clause_plans: List[ClauseAnalysisPlan] = Field(default_factory=list)
    global_strategy: str = ""
    estimated_depth_distribution: dict = Field(default_factory=dict)
    plan_version: int = 1


class PlanAdjustment(BaseModel):
    adjusted_clauses: List[ClauseAnalysisPlan] = Field(default_factory=list)
    reason: str = ""
    should_adjust: bool = False


PLANNING_SYSTEM = """你是一位资深法务审查项目经理。请为合同条款生成可执行的审查计划。

每个条款需要给出：
1) analysis_depth: quick|standard|deep
2) suggested_tools: 建议工具列表
3) max_iterations: ReAct 循环上限（quick=1, standard=3, deep=5）
4) priority_order: 执行顺序（数字越小越先执行）
5) skip_diffs: 是否跳过修改建议
6) skip_validate: 是否跳过质量校验
7) rationale: 简短理由

决策原则：
- critical 条款优先 deep
- 定义条款通常 quick
- 涉及金额、时效、责任限制通常 standard/deep

输出严格 JSON：
{
  "global_strategy": "...",
  "estimated_depth_distribution": {"quick": 0, "standard": 0, "deep": 0},
  "clause_plans": [...]
}
只输出 JSON。"""


DISPATCH_SYSTEM = """你是法务审查调度器，需要判断是否调整后续审查计划。

仅在这些情况建议调整：
1) 发现 high 风险
2) 中期复盘发现计划与实际偏离

输出 JSON：
{
  "should_adjust": true|false,
  "reason": "...",
  "adjusted_clauses": [{"clause_id":"...","analysis_depth":"...","max_iterations":5,"rationale":"..."}]
}
只输出 JSON。"""


def _normalize_depth(depth: str) -> str:
    return depth if depth in {"quick", "standard", "deep"} else "standard"


def _normalize_iterations(depth: str, max_iterations: int) -> int:
    try:
        value = int(max_iterations)
    except Exception:
        value = 0
    if value <= 0:
        return {"quick": 1, "standard": 3, "deep": 5}.get(depth, 3)
    return max(1, min(value, 8))


def _as_item_dict(item: Any) -> dict:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return {}


def _build_default_plan(checklist: list[dict]) -> ReviewPlan:
    clause_plans: list[ClauseAnalysisPlan] = []
    for i, item in enumerate(checklist):
        row = _as_item_dict(item)
        if not row:
            continue
        priority = str(row.get("priority", "medium") or "medium")
        depth = "deep" if priority == "critical" else "standard"
        clause_plans.append(
            ClauseAnalysisPlan(
                clause_id=str(row.get("clause_id", "") or ""),
                clause_name=str(row.get("clause_name", "") or ""),
                analysis_depth=depth,
                suggested_tools=list(row.get("required_skills", []) or []),
                max_iterations=5 if depth == "deep" else 3,
                priority_order=i,
                rationale=f"默认计划：priority={priority}",
                skip_diffs=False,
                skip_validate=False,
            )
        )
    return ReviewPlan(
        clause_plans=clause_plans,
        global_strategy="默认计划：按 checklist 顺序执行，critical 深度分析",
        estimated_depth_distribution={
            "quick": 0,
            "standard": sum(1 for cp in clause_plans if cp.analysis_depth == "standard"),
            "deep": sum(1 for cp in clause_plans if cp.analysis_depth == "deep"),
        },
        plan_version=1,
    )


async def generate_review_plan(
    llm_client: LLMClient,
    checklist: list[dict],
    *,
    domain_id: str = "",
    material_type: str = "",
    available_tools: list[str] | None = None,
) -> ReviewPlan:
    checklist_summary = []
    for item in checklist:
        row = _as_item_dict(item)
        if not row:
            continue
        checklist_summary.append(
            {
                "clause_id": row.get("clause_id", ""),
                "clause_name": row.get("clause_name", ""),
                "priority": row.get("priority", "medium"),
                "required_skills": row.get("required_skills", []),
                "description": row.get("description", ""),
            }
        )

    messages = [
        {"role": "system", "content": PLANNING_SYSTEM},
        {
            "role": "user",
            "content": (
                f"domain={domain_id or 'generic'}\n"
                f"material_type={material_type or 'contract'}\n"
                f"available_tools={json.dumps(available_tools or [], ensure_ascii=False)}\n"
                f"checklist={json.dumps(checklist_summary, ensure_ascii=False)}"
            ),
        },
    ]

    try:
        response = await llm_client.chat(messages, temperature=0.1)
        data = parse_json_response(response, expect_list=False)
        if not isinstance(data, dict):
            return _build_default_plan(checklist)

        clause_plans: list[ClauseAnalysisPlan] = []
        for cp in data.get("clause_plans", []):
            if not isinstance(cp, dict) or not cp.get("clause_id"):
                continue
            depth = _normalize_depth(str(cp.get("analysis_depth", "standard")))
            clause_plans.append(
                ClauseAnalysisPlan(
                    clause_id=str(cp.get("clause_id", "")),
                    clause_name=str(cp.get("clause_name", "") or ""),
                    analysis_depth=depth,
                    suggested_tools=list(cp.get("suggested_tools", []) or []),
                    max_iterations=_normalize_iterations(depth, cp.get("max_iterations", 3)),
                    priority_order=int(cp.get("priority_order", 0) or 0),
                    rationale=str(cp.get("rationale", "") or ""),
                    skip_diffs=bool(cp.get("skip_diffs", depth == "quick")),
                    skip_validate=bool(cp.get("skip_validate", depth == "quick")),
                )
            )

        planned_ids = {cp.clause_id for cp in clause_plans}
        for item in checklist:
            row = _as_item_dict(item)
            clause_id = str(row.get("clause_id", "") or "")
            if clause_id and clause_id not in planned_ids:
                clause_plans.append(
                    ClauseAnalysisPlan(
                        clause_id=clause_id,
                        clause_name=str(row.get("clause_name", "") or ""),
                        analysis_depth="standard",
                        suggested_tools=list(row.get("required_skills", []) or []),
                        max_iterations=3,
                        priority_order=len(clause_plans),
                        rationale="LLM 漏项补齐",
                    )
                )

        clause_plans.sort(key=lambda x: x.priority_order)
        return ReviewPlan(
            clause_plans=clause_plans,
            global_strategy=str(data.get("global_strategy", "") or ""),
            estimated_depth_distribution=data.get("estimated_depth_distribution", {}) or {},
            plan_version=int(data.get("plan_version", 1) or 1),
        )
    except Exception as exc:
        logger.warning("Orchestrator 规划失败，使用默认计划: %s", exc)
        return _build_default_plan(checklist)


async def maybe_adjust_plan(
    llm_client: LLMClient,
    current_clause_id: str,
    current_risks: list[dict],
    remaining_plan: list[ClauseAnalysisPlan],
    completed_count: int,
    total_count: int,
) -> PlanAdjustment:
    has_high_risk = any(
        isinstance(r, dict) and str(r.get("risk_level", "")).lower() == "high"
        for r in current_risks
    )
    midpoint_floor = total_count // 2
    midpoint_ceil = (total_count + 1) // 2
    is_midpoint = total_count > 4 and completed_count in {midpoint_floor, midpoint_ceil}
    if not has_high_risk and not is_midpoint:
        return PlanAdjustment(should_adjust=False, reason="无触发条件")

    risk_summary = []
    for risk in current_risks[:5]:
        if isinstance(risk, dict):
            risk_summary.append(
                {
                    "risk_level": risk.get("risk_level", ""),
                    "description": str(risk.get("description", ""))[:120],
                }
            )
    remaining_summary = [
        {"clause_id": cp.clause_id, "analysis_depth": cp.analysis_depth}
        for cp in remaining_plan[:10]
    ]

    messages = [
        {"role": "system", "content": DISPATCH_SYSTEM},
        {
            "role": "user",
            "content": (
                f"current_clause={current_clause_id}\n"
                f"progress={completed_count}/{total_count}\n"
                f"risks={json.dumps(risk_summary, ensure_ascii=False)}\n"
                f"remaining={json.dumps(remaining_summary, ensure_ascii=False)}"
            ),
        },
    ]

    try:
        response = await llm_client.chat(messages, temperature=0.1)
        data = parse_json_response(response, expect_list=False)
        if not isinstance(data, dict) or not data.get("should_adjust"):
            return PlanAdjustment(
                should_adjust=False,
                reason=str(data.get("reason", "") if isinstance(data, dict) else ""),
            )

        adjusted = []
        for cp in data.get("adjusted_clauses", []):
            if not isinstance(cp, dict) or not cp.get("clause_id"):
                continue
            depth = _normalize_depth(str(cp.get("analysis_depth", "standard")))
            adjusted.append(
                ClauseAnalysisPlan(
                    clause_id=str(cp.get("clause_id", "")),
                    analysis_depth=depth,
                    max_iterations=_normalize_iterations(depth, cp.get("max_iterations", 3)),
                    rationale=str(cp.get("rationale", "") or ""),
                )
            )
        return PlanAdjustment(
            should_adjust=True,
            reason=str(data.get("reason", "") or ""),
            adjusted_clauses=adjusted,
        )
    except Exception as exc:
        logger.warning("Orchestrator 调度失败: %s", exc)
        return PlanAdjustment(should_adjust=False, reason=f"调度异常: {exc}")


def apply_adjustment(plan: ReviewPlan, adjustment: PlanAdjustment) -> ReviewPlan:
    if not adjustment.should_adjust or not adjustment.adjusted_clauses:
        return plan

    adjusted_map = {cp.clause_id: cp for cp in adjustment.adjusted_clauses if cp.clause_id}
    new_plans: list[ClauseAnalysisPlan] = []
    for cp in plan.clause_plans:
        adj = adjusted_map.get(cp.clause_id)
        if not adj:
            new_plans.append(cp)
            continue
        depth = _normalize_depth(adj.analysis_depth or cp.analysis_depth)
        new_plans.append(
            ClauseAnalysisPlan(
                clause_id=cp.clause_id,
                clause_name=cp.clause_name,
                analysis_depth=depth,
                suggested_tools=adj.suggested_tools or cp.suggested_tools,
                max_iterations=_normalize_iterations(depth, adj.max_iterations),
                priority_order=cp.priority_order,
                rationale=adj.rationale or cp.rationale,
                skip_diffs=depth == "quick",
                skip_validate=depth == "quick",
            )
        )

    return ReviewPlan(
        clause_plans=new_plans,
        global_strategy=plan.global_strategy,
        estimated_depth_distribution=plan.estimated_depth_distribution,
        plan_version=plan.plan_version + 1,
    )
