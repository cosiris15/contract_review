"""LangGraph builder for contract review skeleton."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from .state import ReviewGraphState

logger = logging.getLogger(__name__)


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
    primary_docs = [d for d in documents if (d.get("role") if isinstance(d, dict) else d.role) == "primary"]
    if not primary_docs and not state.get("review_checklist"):
        return {"review_checklist": [], "primary_structure": state.get("primary_structure")}

    primary_structure = state.get("primary_structure")
    checklist = state.get("review_checklist", [])
    if not checklist and primary_structure:
        checklist = _generate_generic_checklist(primary_structure)

    return {"primary_structure": primary_structure, "review_checklist": checklist}


async def node_clause_analyze(state: ReviewGraphState) -> Dict[str, Any]:
    checklist = state.get("review_checklist", [])
    index = state.get("current_clause_index", 0)
    if index >= len(checklist):
        return {}

    item = checklist[index]
    clause_id = item["clause_id"] if isinstance(item, dict) else item.clause_id
    logger.info("开始分析条款: %s", clause_id)

    return {
        "current_clause_id": clause_id,
        "current_risks": [],
        "current_diffs": [],
        "clause_retry_count": 0,
    }


async def node_clause_generate_diffs(state: ReviewGraphState) -> Dict[str, Any]:
    _ = state.get("current_risks", [])
    return {"current_diffs": []}


async def node_clause_validate(state: ReviewGraphState) -> Dict[str, Any]:
    validation = "pass"
    retry_count = state.get("clause_retry_count", 0)
    return {
        "validation_result": validation,
        "clause_retry_count": retry_count + 1 if validation == "fail" else retry_count,
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


async def node_summarize(state: ReviewGraphState) -> Dict[str, Any]:
    summary = (
        f"审查完成。共审查 {len(state.get('findings', {}))} 个条款，"
        f"发现 {len(state.get('all_risks', []))} 个风险点，"
        f"生成 {len(state.get('all_diffs', []))} 条修改建议。"
    )
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

    graph = StateGraph(ReviewGraphState)

    graph.add_node("init", node_init)
    graph.add_node("parse_document", node_parse_document)
    graph.add_node("clause_analyze", node_clause_analyze)
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
