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
from ..plugins.registry import get_baseline_text, get_domain_plugin
from ..skills.dispatcher import SkillDispatcher
from ..skills.local.clause_context import ClauseContextInput, ClauseContextOutput
from ..skills.schema import GenericSkillInput, SkillBackend, SkillRegistration
from .llm_utils import parse_json_response
from .prompts import (
    build_clause_analyze_messages,
    build_clause_generate_diffs_messages,
    build_clause_validate_messages,
    build_summarize_messages,
)
from .state import ReviewGraphState

logger = logging.getLogger(__name__)

_llm_client: Optional[LLMClient] = None
_llm_init_warned = False

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
    ),
    SkillRegistration(
        skill_id="resolve_definition",
        name="定义解析",
        description="查找条款中引用的术语定义",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.resolve_definition.resolve_definition",
        domain="*",
        category="extraction",
    ),
    SkillRegistration(
        skill_id="compare_with_baseline",
        name="基线文本对比",
        description="将条款文本与标准模板进行对比",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.compare_with_baseline.compare_with_baseline",
        domain="*",
        category="comparison",
    ),
    SkillRegistration(
        skill_id="cross_reference_check",
        name="交叉引用检查",
        description="检查条款中的交叉引用是否有效",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.cross_reference_check.cross_reference_check",
        domain="*",
        category="validation",
    ),
    SkillRegistration(
        skill_id="extract_financial_terms",
        name="财务条款提取",
        description="从条款中提取金额、百分比、期限等数值",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.extract_financial_terms.extract_financial_terms",
        domain="*",
        category="extraction",
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


def _build_skill_input(
    skill_id: str,
    clause_id: str,
    primary_structure: Any,
    state: ReviewGraphState,
) -> BaseModel | None:
    """Build per-skill input payload. Return None if input cannot be constructed."""
    if skill_id == "get_clause_context":
        try:
            return ClauseContextInput(
                clause_id=clause_id,
                document_structure=primary_structure,
            )
        except Exception:
            return None

    if skill_id == "resolve_definition":
        from ..skills.local.resolve_definition import ResolveDefinitionInput

        return ResolveDefinitionInput(
            clause_id=clause_id,
            document_structure=primary_structure,
        )

    if skill_id == "compare_with_baseline":
        from ..skills.local.compare_with_baseline import CompareWithBaselineInput

        baseline_text = get_baseline_text(state.get("domain_id", ""), clause_id) or ""
        return CompareWithBaselineInput(
            clause_id=clause_id,
            document_structure=primary_structure,
            baseline_text=baseline_text,
            state_snapshot={
                "our_party": state.get("our_party", ""),
                "language": state.get("language", "en"),
                "domain_id": state.get("domain_id", ""),
            },
        )

    if skill_id == "cross_reference_check":
        from ..skills.local.cross_reference_check import CrossReferenceCheckInput

        return CrossReferenceCheckInput(
            clause_id=clause_id,
            document_structure=primary_structure,
        )

    if skill_id == "extract_financial_terms":
        from ..skills.local.extract_financial_terms import ExtractFinancialTermsInput

        return ExtractFinancialTermsInput(
            clause_id=clause_id,
            document_structure=primary_structure,
        )

    if skill_id == "fidic_merge_gc_pc":
        from ..skills.fidic.merge_gc_pc import MergeGcPcInput

        gc_baseline = get_baseline_text(state.get("domain_id", ""), clause_id) or ""
        return MergeGcPcInput(
            clause_id=clause_id,
            document_structure=primary_structure,
            gc_baseline=gc_baseline,
        )

    if skill_id == "fidic_calculate_time_bar":
        from ..skills.fidic.time_bar import CalculateTimeBarInput

        return CalculateTimeBarInput(
            clause_id=clause_id,
            document_structure=primary_structure,
        )

    if skill_id == "fidic_check_pc_consistency":
        findings = state.get("findings", {})
        pc_clauses = []
        for cid, finding in findings.items():
            row = _as_dict(finding)
            skills_data = row.get("skill_context", {})
            merge_data = _as_dict(skills_data.get("fidic_merge_gc_pc"))
            mod_type = merge_data.get("modification_type", "")
            if mod_type in {"modified", "added"}:
                pc_clauses.append(
                    {
                        "clause_id": cid,
                        "text": merge_data.get("pc_text", ""),
                        "modification_type": mod_type,
                    }
                )
        return GenericSkillInput(
            clause_id=clause_id,
            document_structure=primary_structure,
            state_snapshot={
                "pc_clauses": pc_clauses,
                "focus_clause_id": clause_id,
                "domain_id": state.get("domain_id", ""),
            },
        )

    if skill_id == "fidic_search_er":
        clause_text = _extract_clause_text(primary_structure, clause_id)
        query = " ".join(
            part for part in [clause_text[:500], state.get("material_type", ""), state.get("domain_subtype", "")]
            if part
        )
        return GenericSkillInput(
            clause_id=clause_id,
            document_structure=primary_structure,
            state_snapshot={
                "query": query or clause_id,
                "top_k": 5,
                "domain_id": state.get("domain_id", ""),
            },
        )

    if skill_id == "spa_extract_conditions":
        from ..skills.sha_spa.extract_conditions import ExtractConditionsInput

        return ExtractConditionsInput(
            clause_id=clause_id,
            document_structure=primary_structure,
        )

    if skill_id == "spa_extract_reps_warranties":
        from ..skills.sha_spa.extract_reps_warranties import ExtractRepsWarrantiesInput

        return ExtractRepsWarrantiesInput(
            clause_id=clause_id,
            document_structure=primary_structure,
        )

    if skill_id == "spa_indemnity_analysis":
        from ..skills.sha_spa.indemnity_analysis import IndemnityAnalysisInput

        return IndemnityAnalysisInput(
            clause_id=clause_id,
            document_structure=primary_structure,
        )

    if skill_id == "sha_governance_check":
        clause_text = _extract_clause_text(primary_structure, clause_id)
        return GenericSkillInput(
            clause_id=clause_id,
            document_structure=primary_structure,
            state_snapshot={
                "primary_clause": {
                    "clause_id": clause_id,
                    "text": clause_text,
                    "document_type": "SHA",
                },
                "our_party": state.get("our_party", ""),
                "domain_id": state.get("domain_id", ""),
            },
        )

    if skill_id == "transaction_doc_cross_check":
        clause_text = _extract_clause_text(primary_structure, clause_id)
        return GenericSkillInput(
            clause_id=clause_id,
            document_structure=primary_structure,
            state_snapshot={
                "primary_clause": {
                    "clause_id": clause_id,
                    "text": clause_text,
                    "document_type": state.get("domain_subtype", "SPA").upper(),
                },
                "check_type": "rw_vs_disclosure",
                "domain_id": state.get("domain_id", ""),
            },
        )

    return GenericSkillInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        state_snapshot={
            "our_party": state.get("our_party", ""),
            "language": state.get("language", "en"),
            "domain_id": state.get("domain_id", ""),
        },
    )


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
    required_skills = item.get("required_skills", [])

    primary_structure = state.get("primary_structure")
    skill_context: Dict[str, Any] = {}

    if dispatcher and primary_structure:
        for skill_id in required_skills:
            if skill_id not in dispatcher.skill_ids:
                logger.debug("Skill '%s' 未注册，跳过", skill_id)
                continue
            try:
                skill_input = _build_skill_input(skill_id, clause_id, primary_structure, state)
                if skill_input is None:
                    continue
                skill_result = await dispatcher.call(skill_id, skill_input)
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
    llm_client = _get_llm_client()
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

    return {
        "findings": findings,
        "all_risks": all_risks,
        "all_diffs": all_diffs,
        "current_clause_index": state.get("current_clause_index", 0) + 1,
    }


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

    async def _node_clause_analyze(state: ReviewGraphState):
        return await node_clause_analyze(state, dispatcher=dispatcher)

    graph = StateGraph(ReviewGraphState)

    graph.add_node("init", node_init)
    graph.add_node("parse_document", node_parse_document)
    graph.add_node("clause_analyze", _node_clause_analyze)
    graph.add_node("clause_generate_diffs", node_clause_generate_diffs)
    graph.add_node("clause_validate", node_clause_validate)
    graph.add_node("human_approval", node_human_approval)
    graph.add_node("save_clause", node_save_clause)
    graph.add_node("summarize", node_summarize)

    graph.set_entry_point("init")
    graph.add_edge("init", "parse_document")
    graph.add_conditional_edges(
        "parse_document",
        route_next_clause_or_end,
        {"clause_analyze": "clause_analyze", "summarize": "summarize"},
    )
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
