import json

import pytest

from contract_review.graph.orchestrator import (
    ClauseAnalysisPlan,
    PlanAdjustment,
    ReviewPlan,
    _build_default_plan,
    apply_adjustment,
    generate_review_plan,
    maybe_adjust_plan,
)


class _MockLLM:
    def __init__(self, response: str = "{}", fail: bool = False):
        self.response = response
        self.fail = fail
        self.calls = 0

    async def chat(self, messages, **kwargs):
        _ = messages, kwargs
        self.calls += 1
        if self.fail:
            raise RuntimeError("llm error")
        return self.response


@pytest.fixture
def checklist():
    return [
        {
            "clause_id": "1.1",
            "clause_name": "定义",
            "priority": "medium",
            "required_skills": ["resolve_definition"],
            "description": "检查定义",
        },
        {
            "clause_id": "17.6",
            "clause_name": "责任限制",
            "priority": "critical",
            "required_skills": ["compare_with_baseline", "assess_deviation"],
            "description": "检查责任上限",
        },
    ]


@pytest.mark.asyncio
async def test_generate_review_plan_success(checklist):
    llm = _MockLLM(
        response=json.dumps(
            {
                "global_strategy": "critical first",
                "estimated_depth_distribution": {"quick": 0, "standard": 1, "deep": 1},
                "clause_plans": [
                    {
                        "clause_id": "17.6",
                        "analysis_depth": "deep",
                        "suggested_tools": ["compare_with_baseline", "assess_deviation"],
                        "max_iterations": 5,
                        "priority_order": 0,
                        "rationale": "critical",
                    },
                    {
                        "clause_id": "1.1",
                        "analysis_depth": "quick",
                        "suggested_tools": ["resolve_definition"],
                        "max_iterations": 1,
                        "priority_order": 1,
                        "rationale": "definition",
                    },
                ],
            },
            ensure_ascii=False,
        )
    )
    plan = await generate_review_plan(llm, checklist, domain_id="fidic", material_type="contract")
    assert isinstance(plan, ReviewPlan)
    assert len(plan.clause_plans) == 2
    assert plan.clause_plans[0].clause_id == "17.6"
    assert plan.clause_plans[0].analysis_depth == "deep"


@pytest.mark.asyncio
async def test_generate_review_plan_autofills_missing_clause(checklist):
    llm = _MockLLM(
        response=json.dumps(
            {
                "global_strategy": "only one",
                "clause_plans": [
                    {
                        "clause_id": "1.1",
                        "analysis_depth": "standard",
                        "max_iterations": 3,
                        "priority_order": 0,
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    plan = await generate_review_plan(llm, checklist)
    clause_ids = {cp.clause_id for cp in plan.clause_plans}
    assert "1.1" in clause_ids
    assert "17.6" in clause_ids


@pytest.mark.asyncio
async def test_generate_review_plan_invalid_depth_normalized(checklist):
    llm = _MockLLM(
        response=json.dumps(
            {
                "clause_plans": [
                    {
                        "clause_id": "1.1",
                        "analysis_depth": "invalid",
                        "max_iterations": 0,
                        "priority_order": 0,
                    },
                    {
                        "clause_id": "17.6",
                        "analysis_depth": "deep",
                        "max_iterations": 99,
                        "priority_order": 1,
                    },
                ]
            },
            ensure_ascii=False,
        )
    )
    plan = await generate_review_plan(llm, checklist)
    p1 = next(cp for cp in plan.clause_plans if cp.clause_id == "1.1")
    p2 = next(cp for cp in plan.clause_plans if cp.clause_id == "17.6")
    assert p1.analysis_depth == "standard"
    assert p1.max_iterations == 3
    assert p2.max_iterations == 8


@pytest.mark.asyncio
async def test_generate_review_plan_llm_failure_fallback(checklist):
    plan = await generate_review_plan(_MockLLM(fail=True), checklist)
    assert len(plan.clause_plans) == 2
    critical = next(cp for cp in plan.clause_plans if cp.clause_id == "17.6")
    assert critical.analysis_depth == "deep"
    assert critical.max_iterations == 5


def test_build_default_plan(checklist):
    plan = _build_default_plan(checklist)
    assert len(plan.clause_plans) == 2
    medium = next(cp for cp in plan.clause_plans if cp.clause_id == "1.1")
    critical = next(cp for cp in plan.clause_plans if cp.clause_id == "17.6")
    assert medium.analysis_depth == "standard"
    assert critical.analysis_depth == "deep"


@pytest.mark.asyncio
async def test_maybe_adjust_plan_no_trigger_no_llm_call():
    llm = _MockLLM(response=json.dumps({"should_adjust": True}, ensure_ascii=False))
    adjustment = await maybe_adjust_plan(
        llm,
        "1.1",
        [{"risk_level": "low", "description": "x"}],
        [ClauseAnalysisPlan(clause_id="2", analysis_depth="standard")],
        completed_count=1,
        total_count=3,
    )
    assert adjustment.should_adjust is False
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_maybe_adjust_plan_high_risk_trigger():
    llm = _MockLLM(
        response=json.dumps(
            {
                "should_adjust": True,
                "reason": "high risk",
                "adjusted_clauses": [
                    {
                        "clause_id": "2",
                        "analysis_depth": "deep",
                        "max_iterations": 5,
                        "rationale": "upgrade",
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    adjustment = await maybe_adjust_plan(
        llm,
        "1.1",
        [{"risk_level": "high", "description": "重大风险"}],
        [ClauseAnalysisPlan(clause_id="2", analysis_depth="standard")],
        completed_count=1,
        total_count=6,
    )
    assert adjustment.should_adjust is True
    assert adjustment.adjusted_clauses[0].analysis_depth == "deep"


@pytest.mark.asyncio
async def test_maybe_adjust_plan_midpoint_trigger():
    llm = _MockLLM(response=json.dumps({"should_adjust": False, "reason": "no"}, ensure_ascii=False))
    adjustment = await maybe_adjust_plan(
        llm,
        "3.1",
        [{"risk_level": "medium", "description": "x"}],
        [ClauseAnalysisPlan(clause_id="4", analysis_depth="standard")],
        completed_count=3,
        total_count=6,
    )
    assert llm.calls == 1
    assert adjustment.should_adjust is False


def test_apply_adjustment_noop():
    plan = ReviewPlan(clause_plans=[ClauseAnalysisPlan(clause_id="1", analysis_depth="standard")], plan_version=2)
    updated = apply_adjustment(plan, PlanAdjustment(should_adjust=False, adjusted_clauses=[]))
    assert updated is plan


def test_apply_adjustment_updates_clause_and_version():
    plan = ReviewPlan(
        clause_plans=[
            ClauseAnalysisPlan(clause_id="1", analysis_depth="standard", max_iterations=3),
            ClauseAnalysisPlan(clause_id="2", analysis_depth="standard", max_iterations=3),
        ],
        plan_version=1,
    )
    adjustment = PlanAdjustment(
        should_adjust=True,
        adjusted_clauses=[
            ClauseAnalysisPlan(clause_id="2", analysis_depth="deep", max_iterations=5, rationale="upgrade")
        ],
    )
    updated = apply_adjustment(plan, adjustment)
    assert updated.plan_version == 2
    c1 = next(cp for cp in updated.clause_plans if cp.clause_id == "1")
    c2 = next(cp for cp in updated.clause_plans if cp.clause_id == "2")
    assert c1.analysis_depth == "standard"
    assert c2.analysis_depth == "deep"
    assert c2.max_iterations == 5
