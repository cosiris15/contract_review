"""LangGraph builder for contract review with LLM-integrated nodes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from ..config import get_settings
from ..llm_client import LLMClient
from ..models import generate_id
from ..skills.dispatcher import SkillDispatcher
from ..skills.schema import SkillBackend, SkillRegistration
from ..skills.local.clause_context import ClauseContextInput, ClauseContextOutput
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


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


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


def _create_dispatcher() -> SkillDispatcher | None:
    try:
        dispatcher = SkillDispatcher()
        dispatcher.register(
            SkillRegistration(
                skill_id="get_clause_context",
                name="获取条款上下文",
                description="从文档结构中提取指定条款文本",
                input_schema=ClauseContextInput,
                output_schema=ClauseContextOutput,
                backend=SkillBackend.LOCAL,
                local_handler="contract_review.skills.local.clause_context.get_clause_context",
            )
        )
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
        "is_complete": False,
        "error": None,
    }


async def node_parse_document(state: ReviewGraphState) -> Dict[str, Any]:
    documents = state.get("documents", [])
    primary_docs = [d for d in documents if (_as_dict(d).get("role") == "primary")]
    if not primary_docs and not state.get("review_checklist"):
        return {"review_checklist": [], "primary_structure": state.get("primary_structure")}

    primary_structure = state.get("primary_structure")
    checklist = state.get("review_checklist", [])
    if not checklist and primary_structure:
        checklist = _generate_generic_checklist(primary_structure)

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

    clause_text = ""
    primary_structure = state.get("primary_structure")
    if dispatcher and primary_structure:
        try:
            skill_input = ClauseContextInput(clause_id=clause_id, document_structure=primary_structure)
            skill_result = await dispatcher.call("get_clause_context", skill_input)
            if skill_result.success and isinstance(skill_result.data, dict):
                clause_text = skill_result.data.get("context_text", "")
        except Exception as exc:
            logger.warning("Skill get_clause_context 调用失败: %s", exc)

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


def build_review_graph(checkpointer=None, interrupt_before: List[str] | None = None):
    if interrupt_before is None:
        interrupt_before = ["human_approval"]

    dispatcher = _create_dispatcher()

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
