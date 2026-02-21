"""LangGraph builder for contract review with LLM-integrated nodes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from ..config import get_settings
from ..llm_client import LLMClient
from ..models import generate_id
from ..plugins.registry import get_domain_plugin
from ..skills.dispatcher import SkillDispatcher
from ..skills.local.assess_deviation import AssessDeviationInput
from ..skills.local.clause_context import ClauseContextInput, ClauseContextOutput
from ..skills.local.compare_with_baseline import CompareWithBaselineInput
from ..skills.local.cross_reference_check import CrossReferenceCheckInput
from ..skills.local.extract_financial_terms import ExtractFinancialTermsInput
from ..skills.local.load_review_criteria import LoadReviewCriteriaInput
from ..skills.local.resolve_definition import ResolveDefinitionInput
from ..skills.local.semantic_search import SearchReferenceDocInput
from ..skills.schema import SkillBackend, SkillRegistration
from .llm_utils import parse_json_response
from .orchestrator import (
    ClauseAnalysisPlan,
    PlanAdjustment,
    ReviewPlan,
    apply_adjustment,
    generate_review_plan,
    maybe_adjust_plan,
    _build_default_plan,
)
from .prompts import (
    build_react_agent_messages,
    build_clause_analyze_messages,
    build_clause_generate_diffs_messages,
    build_clause_validate_messages,
    build_summarize_messages,
)
from .react_agent import react_agent_loop
from .state import ReviewGraphState

logger = logging.getLogger(__name__)

_llm_client: Optional[LLMClient] = None
_llm_init_warned = False


def _parameters_schema(input_model: type[BaseModel] | None) -> Dict[str, Any]:
    if input_model is None:
        return {"type": "object", "properties": {}, "required": []}
    try:
        schema = input_model.model_json_schema()
    except Exception:
        return {"type": "object", "properties": {}, "required": []}

    props = dict(schema.get("properties", {}))
    required = list(schema.get("required", []))
    for key in ("document_structure", "state_snapshot", "criteria_data", "criteria_file_path"):
        props.pop(key, None)
        if key in required:
            required.remove(key)
    return {"type": "object", "properties": props, "required": required}

_GENERIC_SKILLS: list[SkillRegistration] = [
    SkillRegistration(
        skill_id="get_clause_context",
        name="获取条款上下文",
        description="从文档结构中提取指定条款文本",
        input_schema=ClauseContextInput,
        output_schema=ClauseContextOutput,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.clause_context.get_clause_context",
        domain="*",
        category="extraction",
        parameters_schema=_parameters_schema(ClauseContextInput),
        prepare_input_fn="contract_review.skills.local.clause_context.prepare_input",
    ),
    SkillRegistration(
        skill_id="resolve_definition",
        name="定义解析",
        description="查找条款中引用的术语定义",
        input_schema=ResolveDefinitionInput,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.resolve_definition.resolve_definition",
        domain="*",
        category="extraction",
        parameters_schema=_parameters_schema(ResolveDefinitionInput),
        prepare_input_fn="contract_review.skills.local.resolve_definition.prepare_input",
    ),
    SkillRegistration(
        skill_id="compare_with_baseline",
        name="基线文本对比",
        description="将条款文本与标准模板进行对比",
        input_schema=CompareWithBaselineInput,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.compare_with_baseline.compare_with_baseline",
        domain="*",
        category="comparison",
        parameters_schema=_parameters_schema(CompareWithBaselineInput),
        prepare_input_fn="contract_review.skills.local.compare_with_baseline.prepare_input",
    ),
    SkillRegistration(
        skill_id="cross_reference_check",
        name="交叉引用检查",
        description="检查条款中的交叉引用是否有效",
        input_schema=CrossReferenceCheckInput,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.cross_reference_check.cross_reference_check",
        domain="*",
        category="validation",
        parameters_schema=_parameters_schema(CrossReferenceCheckInput),
        prepare_input_fn="contract_review.skills.local.cross_reference_check.prepare_input",
    ),
    SkillRegistration(
        skill_id="extract_financial_terms",
        name="财务条款提取",
        description="从条款中提取金额、百分比、期限等数值",
        input_schema=ExtractFinancialTermsInput,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.extract_financial_terms.extract_financial_terms",
        domain="*",
        category="extraction",
        parameters_schema=_parameters_schema(ExtractFinancialTermsInput),
        prepare_input_fn="contract_review.skills.local.extract_financial_terms.prepare_input",
    ),
    SkillRegistration(
        skill_id="search_reference_doc",
        name="参考文档语义检索",
        description="在参考文档中检索与当前条款语义相关的段落",
        input_schema=SearchReferenceDocInput,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.semantic_search.search_reference_doc",
        domain="*",
        category="validation",
        parameters_schema=_parameters_schema(SearchReferenceDocInput),
        prepare_input_fn="contract_review.skills.local.semantic_search.prepare_input",
    ),
    SkillRegistration(
        skill_id="load_review_criteria",
        name="审核标准加载",
        description="加载审核标准并匹配到当前条款",
        input_schema=LoadReviewCriteriaInput,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.load_review_criteria.load_review_criteria",
        domain="*",
        category="validation",
        parameters_schema=_parameters_schema(LoadReviewCriteriaInput),
        prepare_input_fn="contract_review.skills.local.load_review_criteria.prepare_input",
    ),
    SkillRegistration(
        skill_id="assess_deviation",
        name="偏离度评估",
        description="基于审核标准评估条款偏离程度与风险",
        input_schema=AssessDeviationInput,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.assess_deviation.assess_deviation",
        domain="*",
        category="comparison",
        parameters_schema=_parameters_schema(AssessDeviationInput),
        prepare_input_fn="contract_review.skills.local.assess_deviation.prepare_input",
    ),
]


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


def _search_clauses(clauses: list, target_id: str) -> str:
    """Recursively search clause tree and return matched clause text."""
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        clause_id = str(clause.get("clause_id", "") or "")
        if clause_id == target_id:
            return str(clause.get("text", "") or "")
        children = clause.get("children", [])
        if isinstance(children, list) and children:
            found = _search_clauses(children, target_id)
            if found:
                return found
        # Fuzzy prefix match for numbering differences (e.g. 14.2 vs 14.2.1).
        if clause_id and target_id and (
            clause_id.startswith(f"{target_id}.") or target_id.startswith(f"{clause_id}.")
        ):
            text = str(clause.get("text", "") or "")
            if text:
                return text
    return ""


def _extract_clause_text(structure: Any, clause_id: str) -> str:
    """Extract clause text directly from structure dict as dispatcher fallback."""
    if not structure:
        return ""
    if not isinstance(structure, dict):
        if hasattr(structure, "model_dump"):
            structure = structure.model_dump()
        else:
            return ""
    clauses = structure.get("clauses", [])
    if not isinstance(clauses, list):
        return ""
    return _search_clauses(clauses, clause_id)


def _normalize_risk_level(level: str | None) -> str:
    if level in {"high", "medium", "low"}:
        return level
    return "medium"


def _get_llm_client() -> LLMClient | None:
    global _llm_client, _llm_init_warned
    if _llm_client is not None:
        return _llm_client

    try:
        settings = get_settings()
        _llm_client = LLMClient(settings.llm)
    except Exception as exc:  # pragma: no cover - exercised in integration tests
        if not _llm_init_warned:
            logger.warning("无法初始化 LLMClient，节点将使用 fallback 模式: %s", exc)
            _llm_init_warned = True
        return None
    return _llm_client


def _create_dispatcher(domain_id: str | None = None) -> SkillDispatcher | None:
    try:
        settings = get_settings()
        refly_client = None
        if settings.refly.enabled and settings.refly.api_key:
            from ..skills.refly_client import ReflyClient, ReflyClientConfig

            refly_client = ReflyClient(
                ReflyClientConfig(
                    base_url=settings.refly.base_url,
                    api_key=settings.refly.api_key,
                    timeout=settings.refly.timeout,
                    poll_interval=settings.refly.poll_interval,
                    max_poll_attempts=settings.refly.max_poll_attempts,
                )
            )

        dispatcher = SkillDispatcher(refly_client=refly_client)
        for skill in _GENERIC_SKILLS:
            try:
                dispatcher.register(skill)
            except Exception as exc:
                logger.warning("注册通用 Skill '%s' 失败: %s", skill.skill_id, exc)

        if domain_id:
            plugin = get_domain_plugin(domain_id)
            if plugin and plugin.domain_skills:
                for skill in plugin.domain_skills:
                    if skill.backend == SkillBackend.REFLY and not refly_client:
                        logger.debug("跳过 Refly Skill '%s'（Refly 未启用）", skill.skill_id)
                        continue
                    try:
                        dispatcher.register(skill)
                    except Exception as exc:
                        logger.warning("注册领域 Skill '%s' 失败（已跳过）: %s", skill.skill_id, exc)
        return dispatcher
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("创建 SkillDispatcher 失败，将跳过技能调用: %s", exc)
        return None


async def node_init(state: ReviewGraphState) -> Dict[str, Any]:
    return {
        "current_clause_index": 0,
        "findings": {},
        "global_issues": [],
        "all_risks": [],
        "all_diffs": [],
        "all_actions": [],
        "clause_retry_count": 0,
        "max_retries": state.get("max_retries", 2),
        "review_plan": state.get("review_plan"),
        "plan_version": int(state.get("plan_version", 1) or 1),
        "is_complete": False,
        "error": None,
    }


async def node_parse_document(state: ReviewGraphState) -> Dict[str, Any]:
    documents = state.get("documents", [])
    primary_docs = [d for d in documents if (_as_dict(d).get("role") == "primary")]
    primary_structure = state.get("primary_structure")
    if primary_docs and not primary_structure:
        doc = _as_dict(primary_docs[0])
        structure_data = doc.get("structure")
        if structure_data:
            primary_structure = structure_data

    checklist = state.get("review_checklist", [])
    if not checklist and primary_structure:
        checklist = _generate_generic_checklist(primary_structure)

    if not primary_docs and not checklist:
        return {"review_checklist": [], "primary_structure": primary_structure}

    return {"primary_structure": primary_structure, "review_checklist": checklist}


def _get_clause_plan(state: ReviewGraphState, clause_id: str) -> ClauseAnalysisPlan | None:
    review_plan = state.get("review_plan")
    if not isinstance(review_plan, dict):
        return None
    clause_plans = review_plan.get("clause_plans", [])
    if not isinstance(clause_plans, list):
        return None
    for raw in clause_plans:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("clause_id", "") or "") == str(clause_id or ""):
            try:
                return ClauseAnalysisPlan.model_validate(raw)
            except Exception:
                return None
    return None


async def node_plan_review(state: ReviewGraphState, dispatcher: SkillDispatcher | None = None) -> Dict[str, Any]:
    settings = get_settings()
    use_orchestrator = bool(getattr(settings, "use_orchestrator", False))
    checklist = state.get("review_checklist", [])
    if not checklist:
        return {"review_plan": {"clause_plans": [], "plan_version": 1}, "plan_version": 1}
    if not use_orchestrator:
        # Defensive fallback: node_plan_review is normally not mounted when orchestrator is disabled.
        plan = _build_default_plan(checklist)
        return {"review_plan": plan.model_dump(), "plan_version": plan.plan_version}

    llm_client = _get_llm_client()
    tools = dispatcher.get_tool_definitions(domain_filter=state.get("domain_id")) if dispatcher else []
    tool_names = []
    for tool in tools:
        function = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = function.get("name")
        if isinstance(name, str) and name:
            tool_names.append(name)

    if not llm_client:
        plan = _build_default_plan(checklist)
    else:
        plan = await generate_review_plan(
            llm_client,
            checklist,
            domain_id=state.get("domain_id") or "",
            material_type=state.get("material_type") or "",
            available_tools=tool_names,
        )

    ordered_ids = [cp.clause_id for cp in sorted(plan.clause_plans, key=lambda x: x.priority_order) if cp.clause_id]
    if ordered_ids:
        item_map = {str(_as_dict(item).get("clause_id", "") or ""): item for item in checklist}
        reordered = [item_map[cid] for cid in ordered_ids if cid in item_map]
        for item in checklist:
            cid = str(_as_dict(item).get("clause_id", "") or "")
            if cid not in ordered_ids:
                reordered.append(item)
        checklist = reordered

    return {
        "review_plan": plan.model_dump(),
        "plan_version": int(plan.plan_version or 1),
        "review_checklist": checklist,
    }


async def _run_react_branch(
    *,
    llm_client: LLMClient,
    dispatcher: SkillDispatcher,
    clause_id: str,
    clause_name: str,
    description: str,
    priority: str,
    our_party: str,
    language: str,
    primary_structure: Any,
    state: ReviewGraphState,
    suggested_skills: list[str] | None = None,
    max_iterations: int = 5,
    temperature: float = 0.1,
) -> Dict[str, Any]:
    clause_text = _extract_clause_text(primary_structure, clause_id)
    if not clause_text:
        clause_text = f"{clause_name}\n{description}".strip() or clause_id

    messages = build_react_agent_messages(
        language=language,
        our_party=our_party,
        clause_id=clause_id,
        clause_name=clause_name,
        description=description,
        priority=priority,
        clause_text=clause_text,
        domain_id=state.get("domain_id"),
        suggested_skills=suggested_skills,
        dispatcher=dispatcher,
    )

    risks_raw, skill_context, final_messages = await react_agent_loop(
        llm_client=llm_client,
        dispatcher=dispatcher,
        messages=messages,
        clause_id=clause_id,
        primary_structure=primary_structure,
        state=dict(state),
        max_iterations=max(1, int(max_iterations or 5)),
        temperature=float(temperature or 0.1),
    )

    risks: List[Dict[str, Any]] = []
    for raw in risks_raw:
        row = _as_dict(raw)
        original_text = row.get("original_text", "")
        risks.append(
            {
                "id": generate_id(),
                "risk_level": _normalize_risk_level(row.get("risk_level")),
                "risk_type": row.get("risk_type", "未分类风险"),
                "description": row.get("description", ""),
                "reason": row.get("reason", ""),
                "analysis": row.get("analysis", ""),
                "location": {"original_text": original_text} if original_text else None,
            }
        )

    return {
        "current_clause_id": clause_id,
        "current_clause_text": clause_text,
        "current_risks": risks,
        "current_diffs": [],
        "current_skill_context": skill_context,
        "agent_messages": final_messages,
        "clause_retry_count": 0,
    }


async def node_clause_analyze(
    state: ReviewGraphState, dispatcher: SkillDispatcher | None = None
) -> Dict[str, Any]:
    checklist = state.get("review_checklist", [])
    index = state.get("current_clause_index", 0)
    if index >= len(checklist):
        return {}

    item = _as_dict(checklist[index])
    clause_id = item.get("clause_id", "")
    clause_name = item.get("clause_name", "")
    description = item.get("description", "")
    priority = item.get("priority", "medium")
    our_party = state.get("our_party", "")
    language = state.get("language", "en")
    required_skills = list(item.get("required_skills", []) or [])
    clause_plan = _get_clause_plan(state, clause_id)
    suggested_skills = clause_plan.suggested_tools if clause_plan and clause_plan.suggested_tools else required_skills

    primary_structure = state.get("primary_structure")
    settings = get_settings()
    use_react = bool(getattr(settings, "use_react_agent", False))
    react_max_iterations = int(getattr(settings, "react_max_iterations", 5) or 5)
    max_iterations = clause_plan.max_iterations if clause_plan else react_max_iterations
    llm_client = _get_llm_client()

    if use_react and llm_client and dispatcher and primary_structure:
        try:
            return await _run_react_branch(
                llm_client=llm_client,
                dispatcher=dispatcher,
                clause_id=clause_id,
                clause_name=clause_name,
                description=description,
                priority=priority,
                our_party=our_party,
                language=language,
                primary_structure=primary_structure,
                state=state,
                suggested_skills=suggested_skills,
                max_iterations=max_iterations,
                temperature=float(getattr(settings, "react_temperature", 0.1) or 0.1),
            )
        except Exception as exc:
            logger.warning("ReAct Agent 失败 (clause=%s)，回退到硬编码模式: %s", clause_id, exc)

    skill_context: Dict[str, Any] = {}

    if dispatcher and primary_structure:
        for skill_id in required_skills:
            if skill_id not in dispatcher.skill_ids:
                logger.debug("Skill '%s' 未注册，跳过", skill_id)
                continue
            try:
                skill_result = await dispatcher.prepare_and_call(
                    skill_id,
                    clause_id,
                    primary_structure,
                    dict(state),
                )
                if skill_result.success and skill_result.data:
                    skill_context[skill_id] = skill_result.data
            except Exception as exc:
                logger.warning("Skill '%s' 调用失败: %s", skill_id, exc)

    clause_text = ""
    context = skill_context.get("get_clause_context")
    if isinstance(context, dict):
        clause_text = str(context.get("context_text", "") or "")

    if not clause_text and primary_structure:
        clause_text = _extract_clause_text(primary_structure, clause_id)

    if not clause_text:
        clause_text = f"{clause_name}\n{description}".strip() or clause_id

    risks: List[Dict[str, Any]] = []
    if llm_client:
        try:
            messages = build_clause_analyze_messages(
                language=language,
                our_party=our_party,
                clause_id=clause_id,
                clause_name=clause_name,
                description=description,
                priority=priority,
                clause_text=clause_text,
                skill_context=skill_context,
                domain_id=state.get("domain_id"),
            )
            response = await llm_client.chat(messages)
            raw_risks = parse_json_response(response, expect_list=True)

            for raw in raw_risks:
                row = _as_dict(raw)
                original_text = row.get("original_text", "")
                risks.append(
                    {
                        "id": generate_id(),
                        "risk_level": _normalize_risk_level(row.get("risk_level")),
                        "risk_type": row.get("risk_type", "未分类风险"),
                        "description": row.get("description", ""),
                        "reason": row.get("reason", ""),
                        "analysis": row.get("analysis", ""),
                        "location": {"original_text": original_text} if original_text else None,
                    }
                )
        except Exception as exc:
            logger.warning("条款分析 LLM 调用失败，使用空风险回退: %s", exc)

    return {
        "current_clause_id": clause_id,
        "current_clause_text": clause_text,
        "current_risks": risks,
        "current_diffs": [],
        "current_skill_context": skill_context,
        "agent_messages": None,
        "clause_retry_count": 0,
    }


async def node_clause_generate_diffs(state: ReviewGraphState) -> Dict[str, Any]:
    risks = state.get("current_risks", [])
    clause_id = state.get("current_clause_id", "")
    clause_text = state.get("current_clause_text", "")

    if not risks:
        return {"current_diffs": []}

    diffs: List[Dict[str, Any]] = []
    llm_client = _get_llm_client()
    if llm_client:
        try:
            messages = build_clause_generate_diffs_messages(
                clause_id=clause_id,
                clause_text=clause_text,
                risks=[_as_dict(r) for r in risks],
            )
            response = await llm_client.chat(messages)
            raw_diffs = parse_json_response(response, expect_list=True)
            for raw in raw_diffs:
                row = _as_dict(raw)
                raw_risk_id = str(row.get("risk_id", "")).strip()
                mapped_risk_id = None
                if raw_risk_id.isdigit():
                    idx = int(raw_risk_id)
                    if 0 <= idx < len(risks):
                        mapped_risk_id = _as_dict(risks[idx]).get("id")
                if not mapped_risk_id and risks:
                    mapped_risk_id = _as_dict(risks[0]).get("id")

                action_type = row.get("action_type", "replace")
                if action_type not in {"replace", "delete", "insert"}:
                    action_type = "replace"

                original_text = row.get("original_text", "")
                proposed_text = row.get("proposed_text", "")
                metadata = dict(row.get("metadata", {}))
                if original_text and clause_text and original_text not in clause_text:
                    metadata["text_match"] = False
                elif original_text:
                    metadata["text_match"] = True

                diffs.append(
                    {
                        "diff_id": generate_id(),
                        "risk_id": mapped_risk_id,
                        "clause_id": clause_id,
                        "action_type": action_type,
                        "original_text": original_text,
                        "proposed_text": proposed_text,
                        "status": "pending",
                        "reason": row.get("reason", ""),
                        "risk_level": _normalize_risk_level(row.get("risk_level")),
                        "metadata": metadata,
                    }
                )
        except Exception as exc:
            logger.warning("修改建议 LLM 调用失败，使用空 diff 回退: %s", exc)

    return {"current_diffs": diffs}


async def node_clause_validate(state: ReviewGraphState) -> Dict[str, Any]:
    risks = state.get("current_risks", [])
    diffs = state.get("current_diffs", [])
    retry_count = state.get("clause_retry_count", 0)

    if not risks and not diffs:
        return {"validation_result": "pass", "clause_retry_count": retry_count}

    result = "pass"
    llm_client = _get_llm_client()
    if llm_client:
        try:
            messages = build_clause_validate_messages(
                clause_id=state.get("current_clause_id", ""),
                clause_text=state.get("current_clause_text", ""),
                risks=[_as_dict(r) for r in risks],
                diffs=[_as_dict(d) for d in diffs],
            )
            response = await llm_client.chat(messages)
            parsed = parse_json_response(response, expect_list=False)
            candidate = str(_as_dict(parsed).get("result", "pass")).lower().strip()
            result = candidate if candidate in {"pass", "fail"} else "pass"
        except Exception as exc:
            logger.warning("质量校验 LLM 调用失败，默认放行: %s", exc)
            result = "pass"

    return {
        "validation_result": result,
        "clause_retry_count": retry_count + 1 if result == "fail" else retry_count,
    }


async def node_human_approval(state: ReviewGraphState) -> Dict[str, Any]:
    diffs = state.get("current_diffs", [])
    if not diffs:
        return {"pending_diffs": [], "user_decisions": {}}
    return {"pending_diffs": diffs}


async def node_save_clause(state: ReviewGraphState) -> Dict[str, Any]:
    clause_id = state.get("current_clause_id", "")
    risks = state.get("current_risks", [])
    diffs = state.get("current_diffs", [])
    skill_context = state.get("current_skill_context", {})
    user_decisions = state.get("user_decisions", {})

    approved_diffs = []
    for diff in diffs:
        diff_id = diff.get("diff_id") if isinstance(diff, dict) else diff.diff_id
        decision = user_decisions.get(diff_id, "approve")
        if decision == "approve":
            approved_diffs.append(diff)

    findings = dict(state.get("findings", {}))
    findings[clause_id] = {
        "clause_id": clause_id,
        "risks": risks,
        "diffs": approved_diffs,
        "skill_context": skill_context,
        "completed": True,
    }

    all_risks = list(state.get("all_risks", []))
    all_risks.extend(risks)
    all_diffs = list(state.get("all_diffs", []))
    all_diffs.extend(approved_diffs)
    payload: Dict[str, Any] = {
        "findings": findings,
        "all_risks": all_risks,
        "all_diffs": all_diffs,
        "current_clause_index": state.get("current_clause_index", 0) + 1,
    }

    settings = get_settings()
    use_orchestrator = bool(getattr(settings, "use_orchestrator", False))
    review_plan_raw = state.get("review_plan")
    if use_orchestrator and isinstance(review_plan_raw, dict):
        llm_client = _get_llm_client()
        try:
            plan = ReviewPlan.model_validate(review_plan_raw)
            completed_count = int(payload["current_clause_index"])
            total_count = len(state.get("review_checklist", []))
            remaining_plan = []
            completed_ids = set(findings.keys())
            for cp in plan.clause_plans:
                if cp.clause_id and cp.clause_id not in completed_ids:
                    remaining_plan.append(cp)

            adjustment = PlanAdjustment(should_adjust=False, reason="无 LLM 客户端")
            if llm_client:
                adjustment = await maybe_adjust_plan(
                    llm_client,
                    clause_id,
                    [_as_dict(r) for r in risks],
                    remaining_plan,
                    completed_count,
                    total_count,
                )

            if adjustment.should_adjust:
                updated_plan = apply_adjustment(plan, adjustment)
                payload["review_plan"] = updated_plan.model_dump()
                payload["plan_version"] = updated_plan.plan_version
        except Exception as exc:
            logger.warning("Orchestrator 计划调整失败，继续主流程: %s", exc)

    return payload


def _fallback_summary(state: ReviewGraphState) -> str:
    return (
        f"审查完成。共审查 {len(state.get('findings', {}))} 个条款，"
        f"发现 {len(state.get('all_risks', []))} 个风险点，"
        f"生成 {len(state.get('all_diffs', []))} 条修改建议。"
    )


async def node_summarize(state: ReviewGraphState) -> Dict[str, Any]:
    all_risks = [_as_dict(r) for r in state.get("all_risks", [])]
    all_diffs = state.get("all_diffs", [])
    findings = state.get("findings", {})

    high_risks = sum(1 for r in all_risks if _normalize_risk_level(r.get("risk_level")) == "high")
    medium_risks = sum(1 for r in all_risks if _normalize_risk_level(r.get("risk_level")) == "medium")
    low_risks = sum(1 for r in all_risks if _normalize_risk_level(r.get("risk_level")) == "low")

    finding_lines = []
    for clause_id, raw in findings.items():
        row = _as_dict(raw)
        clause_risks = row.get("risks", [])
        clause_diffs = row.get("diffs", [])
        finding_lines.append(
            f"- 条款 {clause_id}: 风险 {len(clause_risks)} 项，修改建议 {len(clause_diffs)} 项"
        )

    summary = _fallback_summary(state)
    llm_client = _get_llm_client()
    if llm_client:
        try:
            messages = build_summarize_messages(
                total_clauses=len(state.get("review_checklist", [])),
                total_risks=len(all_risks),
                high_risks=high_risks,
                medium_risks=medium_risks,
                low_risks=low_risks,
                total_diffs=len(all_diffs),
                findings_detail="\n".join(finding_lines) if finding_lines else "无",
            )
            llm_summary = (await llm_client.chat(messages)).strip()
            if llm_summary:
                summary = llm_summary
        except Exception as exc:
            logger.warning("总结节点 LLM 调用失败，使用回退摘要: %s", exc)

    return {"summary_notes": summary, "is_complete": True}


def route_next_clause_or_end(state: ReviewGraphState) -> str:
    checklist = state.get("review_checklist", [])
    index = state.get("current_clause_index", 0)
    if state.get("error"):
        return "summarize"
    return "clause_analyze" if index < len(checklist) else "summarize"


def route_validation(state: ReviewGraphState) -> str:
    validation = state.get("validation_result", "pass")
    retry_count = state.get("clause_retry_count", 0)
    max_retries = state.get("max_retries", 2)
    if validation == "pass":
        return "human_approval"
    if retry_count < max_retries:
        return "clause_generate_diffs"
    return "save_clause"


def route_after_analyze(state: ReviewGraphState) -> str:
    clause_id = state.get("current_clause_id") or ""
    if not clause_id:
        return "clause_generate_diffs"
    clause_plan = _get_clause_plan(state, str(clause_id))
    if clause_plan and clause_plan.skip_diffs:
        return "save_clause"
    return "clause_generate_diffs"


def route_after_approval(state: ReviewGraphState) -> str:
    _ = state
    return "save_clause"


def _generate_generic_checklist(structure) -> List[Dict[str, Any]]:
    checklist: List[Dict[str, Any]] = []
    clauses = structure.get("clauses", []) if isinstance(structure, dict) else structure.clauses
    for clause in clauses:
        clause_id = clause.get("clause_id") if isinstance(clause, dict) else clause.clause_id
        title = clause.get("title", "") if isinstance(clause, dict) else clause.title
        checklist.append(
            {
                "clause_id": clause_id,
                "clause_name": title,
                "priority": "medium",
                "required_skills": ["get_clause_context"],
                "description": f"审查条款 {clause_id}",
            }
        )
    return checklist


def build_review_graph(
    checkpointer=None,
    interrupt_before: List[str] | None = None,
    domain_id: str | None = None,
):
    if interrupt_before is None:
        interrupt_before = ["human_approval"]

    dispatcher = _create_dispatcher(domain_id=domain_id)
    settings = get_settings()
    use_orchestrator = bool(getattr(settings, "use_orchestrator", False))

    async def _node_clause_analyze(state: ReviewGraphState):
        return await node_clause_analyze(state, dispatcher=dispatcher)

    async def _node_plan_review(state: ReviewGraphState):
        return await node_plan_review(state, dispatcher=dispatcher)

    graph = StateGraph(ReviewGraphState)

    graph.add_node("init", node_init)
    graph.add_node("parse_document", node_parse_document)
    if use_orchestrator:
        graph.add_node("plan_review", _node_plan_review)
    graph.add_node("clause_analyze", _node_clause_analyze)
    graph.add_node("clause_generate_diffs", node_clause_generate_diffs)
    graph.add_node("clause_validate", node_clause_validate)
    graph.add_node("human_approval", node_human_approval)
    graph.add_node("save_clause", node_save_clause)
    graph.add_node("summarize", node_summarize)

    graph.set_entry_point("init")
    graph.add_edge("init", "parse_document")
    if use_orchestrator:
        graph.add_edge("parse_document", "plan_review")
        graph.add_conditional_edges(
            "plan_review",
            route_next_clause_or_end,
            {"clause_analyze": "clause_analyze", "summarize": "summarize"},
        )
    else:
        graph.add_conditional_edges(
            "parse_document",
            route_next_clause_or_end,
            {"clause_analyze": "clause_analyze", "summarize": "summarize"},
        )
    if use_orchestrator:
        graph.add_conditional_edges(
            "clause_analyze",
            route_after_analyze,
            {"clause_generate_diffs": "clause_generate_diffs", "save_clause": "save_clause"},
        )
    else:
        graph.add_edge("clause_analyze", "clause_generate_diffs")
    graph.add_edge("clause_generate_diffs", "clause_validate")
    graph.add_conditional_edges(
        "clause_validate",
        route_validation,
        {
            "human_approval": "human_approval",
            "clause_generate_diffs": "clause_generate_diffs",
            "save_clause": "save_clause",
        },
    )
    graph.add_conditional_edges("human_approval", route_after_approval, {"save_clause": "save_clause"})
    graph.add_conditional_edges(
        "save_clause",
        route_next_clause_or_end,
        {"clause_analyze": "clause_analyze", "summarize": "summarize"},
    )
    graph.add_edge("summarize", END)

    memory = checkpointer or MemorySaver()
    return graph.compile(checkpointer=memory, interrupt_before=interrupt_before)
