"""Local FIDIC skill: rule-based consistency checks across modified PC clauses."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from pydantic import BaseModel, Field


class PcClause(BaseModel):
    clause_id: str
    text: str
    modification_type: str


class CheckPcConsistencyInput(BaseModel):
    clause_id: str
    document_structure: Any
    pc_clauses: List[PcClause] = Field(default_factory=list)
    focus_clause_id: str = ""


class ConsistencyIssue(BaseModel):
    clause_a: str
    clause_b: str
    issue: str
    severity: str
    rule_id: str


class CheckPcConsistencyOutput(BaseModel):
    clause_id: str
    consistency_issues: List[ConsistencyIssue] = Field(default_factory=list)
    total_issues: int = 0
    clauses_checked: int = 0


CheckFn = Callable[[str, str, str, str], Optional[str]]


@dataclass(frozen=True)
class ConsistencyRule:
    rule_id: str
    clause_pairs: list[tuple[str, str]]
    severity: str
    check_fn: CheckFn


def _contains_any(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in patterns)


def _short_days(text: str) -> bool:
    for m in re.finditer(r"(\d+)\s*(?:days?|天|日)", text, flags=re.IGNORECASE):
        try:
            if int(m.group(1)) <= 28:
                return True
        except Exception:
            continue
    return False


def check_obligation_vs_liability(a: str, b: str, _aid: str, _bid: str) -> Optional[str]:
    expansion = [
        "shall be responsible for",
        "including but not limited to",
        "承包商应负责",
        "包括但不限于",
        "全部责任",
        "entire responsibility",
    ]
    cap_patterns = [
        r"\d+%\s*of\s*the\s*contract\s*price",
        r"合同价格的\s*\d+%",
        r"shall not exceed",
        r"不超过",
    ]
    if not _contains_any(a, expansion):
        return None
    has_cap = any(re.search(pattern, b, flags=re.IGNORECASE) for pattern in cap_patterns)
    if has_cap:
        return "义务范围明显扩大，但责任上限条款看起来未联动调整"
    return None


def check_time_bar_vs_procedure(a: str, b: str, _aid: str, _bid: str) -> Optional[str]:
    if not _short_days(a):
        return None
    heavy_procedure = [
        "supporting documents",
        "fully detailed claim",
        "further particulars",
        "详细资料",
        "完整索赔资料",
        "证明文件",
    ]
    if _contains_any(b, heavy_procedure):
        return "索赔时效较短，但程序性材料要求仍较重，可能导致履约落地困难"
    return None


def check_payment_vs_schedule(a: str, b: str, _aid: str, _bid: str) -> Optional[str]:
    schedule_tight = _contains_any(
        a,
        ["提前竣工", "accelerate", "shortened", "压缩工期", "提前完成"],
    )
    payment_cycle_slow = _contains_any(
        b,
        ["monthly", "每月", "56 days", "56天", "60 days", "60天"],
    )
    if schedule_tight and payment_cycle_slow:
        return "工期或履约节奏趋紧，但付款周期看起来未同步优化"
    return None


def check_risk_vs_insurance(a: str, b: str, _aid: str, _bid: str) -> Optional[str]:
    transferred = _contains_any(
        a,
        ["contractor bears all risks", "承包商承担全部风险", "sole risk", "全部由承包商承担"],
    )
    insurance_weak = not _contains_any(
        b,
        ["insurance", "insurer", "保单", "保险", "coverage", "insured"],
    )
    if transferred and insurance_weak:
        return "风险向承包商转移较重，但保险保障描述偏弱"
    return None


def check_rights_vs_obligations(a: str, b: str, _aid: str, _bid: str) -> Optional[str]:
    rights_cut = _contains_any(
        a,
        ["not entitled", "not be entitled", "waived", "forfeit", "无权", "视为放弃", "丧失"],
    )
    obligations_keep = _contains_any(
        b,
        ["shall", "must", "应", "须", "必须"],
    )
    if rights_cut and obligations_keep:
        return "权利侧被削减，但义务侧仍较重，可能出现权责不对等"
    return None


def check_cross_reference_stale(a: str, _b: str, _aid: str, bid: str) -> Optional[str]:
    ref_patterns = [
        rf"\b{re.escape(bid)}\b",
        rf"clause\s+{re.escape(bid)}",
        rf"条款\s*{re.escape(bid)}",
    ]
    mentioned = any(re.search(pattern, a, flags=re.IGNORECASE) for pattern in ref_patterns)
    if not mentioned:
        return None
    synced_markers = ["amended", "revised", "as updated", "已修订", "修订后", "更新后"]
    if _contains_any(a, synced_markers):
        return None
    return f"引用了条款 {bid}，但未体现联动更新痕迹，可能存在交叉引用失效"


CONSISTENCY_RULES: list[ConsistencyRule] = [
    ConsistencyRule(
        rule_id="obligation_vs_liability_cap",
        clause_pairs=[("4.1", "17.6"), ("4.12", "17.6")],
        severity="high",
        check_fn=check_obligation_vs_liability,
    ),
    ConsistencyRule(
        rule_id="time_bar_vs_procedure",
        clause_pairs=[("20.1", "20.2")],
        severity="high",
        check_fn=check_time_bar_vs_procedure,
    ),
    ConsistencyRule(
        rule_id="payment_vs_schedule",
        clause_pairs=[("8.2", "14.7"), ("8.2", "14.1")],
        severity="medium",
        check_fn=check_payment_vs_schedule,
    ),
    ConsistencyRule(
        rule_id="risk_transfer_vs_insurance",
        clause_pairs=[("4.1", "18.1"), ("4.12", "18.1")],
        severity="medium",
        check_fn=check_risk_vs_insurance,
    ),
    ConsistencyRule(
        rule_id="rights_vs_obligations",
        clause_pairs=[("20.1", "4.1")],
        severity="medium",
        check_fn=check_rights_vs_obligations,
    ),
    ConsistencyRule(
        rule_id="cross_reference_stale",
        clause_pairs=[],
        severity="low",
        check_fn=check_cross_reference_stale,
    ),
]


def _pair_matches(focus_id: str, other_id: str, pair: tuple[str, str]) -> bool:
    return (focus_id == pair[0] and other_id == pair[1]) or (focus_id == pair[1] and other_id == pair[0])


async def check_pc_consistency(input_data: CheckPcConsistencyInput) -> CheckPcConsistencyOutput:
    clauses = [c for c in input_data.pc_clauses if c.modification_type in {"modified", "added"}]
    if len(clauses) <= 1:
        return CheckPcConsistencyOutput(clause_id=input_data.clause_id, clauses_checked=len(clauses))

    by_id = {c.clause_id: c for c in clauses if c.clause_id}
    focus_id = input_data.focus_clause_id or input_data.clause_id
    focus = by_id.get(focus_id)
    if focus is None:
        return CheckPcConsistencyOutput(clause_id=input_data.clause_id, clauses_checked=len(clauses))

    issues: list[ConsistencyIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for other in clauses:
        if other.clause_id == focus.clause_id:
            continue
        for rule in CONSISTENCY_RULES:
            if rule.clause_pairs and not any(_pair_matches(focus.clause_id, other.clause_id, p) for p in rule.clause_pairs):
                continue
            detail = rule.check_fn(focus.text or "", other.text or "", focus.clause_id, other.clause_id)
            if not detail:
                continue
            sig = (rule.rule_id, focus.clause_id, other.clause_id)
            if sig in seen:
                continue
            seen.add(sig)
            issues.append(
                ConsistencyIssue(
                    clause_a=focus.clause_id,
                    clause_b=other.clause_id,
                    issue=detail,
                    severity=rule.severity,
                    rule_id=rule.rule_id,
                )
            )

    return CheckPcConsistencyOutput(
        clause_id=input_data.clause_id,
        consistency_issues=issues,
        total_issues=len(issues),
        clauses_checked=len(clauses),
    )


def prepare_input(clause_id: str, primary_structure: Any, state: dict) -> CheckPcConsistencyInput:
    findings = state.get("findings", {})
    pc_clauses: list[PcClause] = []
    for cid, finding in findings.items():
        if isinstance(finding, dict):
            row = finding
        elif hasattr(finding, "model_dump"):
            row = finding.model_dump()
        else:
            row = {}
        skills_data = row.get("skill_context", {})
        merge_data = skills_data.get("fidic_merge_gc_pc", {})
        if not isinstance(merge_data, dict):
            merge_data = {}
        mod_type = merge_data.get("modification_type", "")
        if mod_type in {"modified", "added"}:
            pc_clauses.append(
                PcClause(
                    clause_id=str(cid),
                    text=str(merge_data.get("pc_text", "") or ""),
                    modification_type=mod_type,
                )
            )
    return CheckPcConsistencyInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        pc_clauses=pc_clauses,
        focus_clause_id=clause_id,
    )
