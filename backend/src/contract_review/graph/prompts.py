"""Prompt templates for Gen3 LangGraph nodes."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..prompts import ANTI_INJECTION_INSTRUCTION, JURISDICTION_INSTRUCTIONS

CLAUSE_ANALYZE_SYSTEM = """你是一位资深法务审阅专家，正在逐条审查合同条款。

{anti_injection}

{jurisdiction_instruction}

【任务】
分析以下条款，从我方（{our_party}）的角度识别风险点。

【输出要求】
以 JSON 数组格式输出风险点列表，字段必须包含：
- risk_level: high|medium|low
- risk_type
- description
- reason
- analysis
- original_text

如果该条款无风险，返回 []。
只输出 JSON，不要输出其他内容。"""

CLAUSE_GENERATE_DIFFS_SYSTEM = """你是一位资深法务审阅专家，需要根据已识别风险点生成可执行的文本修改建议。

【输出要求】
以 JSON 数组格式输出，字段必须包含：
- risk_id
- action_type: replace|delete|insert
- original_text
- proposed_text
- reason
- risk_level

只输出 JSON，不要输出其他内容。"""

CLAUSE_VALIDATE_SYSTEM = """你是一位法务审阅质量检查员，请检查风险分析与修改建议质量。

【输出要求】
只输出 JSON 对象：
{
  "result": "pass|fail",
  "issues": ["..."]
}

只输出 JSON，不要输出其他内容。"""

SUMMARIZE_SYSTEM = """你是一位法务审阅专家，请基于审查结果生成结构化总结。

要求包含：
1. 总体风险评估
2. 关键风险提示
3. 优先修改建议
4. 后续建议
"""

FIDIC_DOMAIN_INSTRUCTION = """
【FIDIC 专项审查指引】
请重点关注：
1. PC 是否删除或弱化 GC 中对我方有利条款；
2. 时效（Time Bar）是否过短、是否存在逾期丧权；
3. 风险分配是否明显向我方转移；
4. 付款、索赔、责任限制与争议条款是否形成不利联动。

{merge_context}
{time_bar_context}
{er_context}
"""

SHA_SPA_DOMAIN_INSTRUCTION = """
【SHA/SPA 专项审查指引】
请重点关注：
1. 先决条件是否可控，是否包含不合理 MAC 门槛；
2. 陈述与保证是否被过度限定（knowledge/materiality/disclosure）；
3. 赔偿机制（cap、basket、survival）是否显著不利；
4. 治理结构与退出机制是否保障我方核心权利。

{conditions_context}
{rw_context}
{indemnity_context}
"""


def _jurisdiction_instruction(language: str) -> str:
    return JURISDICTION_INSTRUCTIONS.get(language, JURISDICTION_INSTRUCTIONS.get("en", ""))


def _anti_injection_instruction(language: str, our_party: str) -> str:
    template = ANTI_INJECTION_INSTRUCTION.get(language, ANTI_INJECTION_INSTRUCTION.get("en", ""))
    return template.format(our_party=our_party)


def _format_skill_context(skill_context: Dict[str, Any]) -> str:
    """Format skill outputs into LLM-readable text blocks."""
    parts: List[str] = []
    for skill_id, data in skill_context.items():
        if skill_id == "get_clause_context":
            continue
        if skill_id == "load_review_criteria":
            if not isinstance(data, dict):
                continue
            if not data.get("has_criteria"):
                continue
            criteria = data.get("matched_criteria", [])
            if not criteria:
                parts.append("[审核标准] 未找到与本条款匹配的审核要点。")
                continue
            lines = ["[审核标准] 以下是与本条款匹配的审核要点："]
            for row in criteria:
                if not isinstance(row, dict):
                    continue
                lines.append(f"- 【{row.get('risk_level', '')}】{row.get('review_point', '')}")
                if row.get("baseline_text"):
                    lines.append(f"  基准：{row.get('baseline_text', '')}")
                if row.get("suggested_action"):
                    lines.append(f"  建议：{row.get('suggested_action', '')}")
                lines.append(f"  匹配方式：{row.get('match_type', '')}（{row.get('match_score', '')}）")
            parts.append("\n".join(lines))
            continue
        if skill_id == "assess_deviation":
            if not isinstance(data, dict):
                continue
            deviations = data.get("deviations", [])
            if not isinstance(deviations, list) or not deviations:
                continue
            lines = ["[偏离度评估] 以下是按审核标准生成的偏离评估："]
            for row in deviations:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    f"- [{row.get('criterion_id', '')}] 偏离等级={row.get('deviation_level', 'unknown')} "
                    f"风险等级={row.get('risk_level', 'unknown')}"
                )
                if row.get("rationale"):
                    lines.append(f"  依据：{row.get('rationale', '')}")
                if row.get("suggested_action"):
                    lines.append(f"  建议：{row.get('suggested_action', '')}")
            parts.append("\n".join(lines))
            continue
        if isinstance(data, dict):
            parts.append(f"[{skill_id}]\n{json.dumps(data, ensure_ascii=False, indent=2)}")
            continue
        if isinstance(data, str):
            parts.append(f"[{skill_id}]\n{data}")
            continue
        parts.append(f"[{skill_id}]\n{str(data)}")
    return "\n\n".join(parts)


def _build_fidic_instruction(skill_context: Dict[str, Any]) -> str:
    merge_data = skill_context.get("fidic_merge_gc_pc", {})
    time_bar_data = skill_context.get("fidic_calculate_time_bar", {})
    er_data = skill_context.get("fidic_search_er", {})

    merge_context = ""
    if isinstance(merge_data, dict):
        modification_type = merge_data.get("modification_type", "")
        if modification_type == "modified":
            merge_context = (
                "【GC/PC 对比】该条款已被 PC 修改。"
                f"变更摘要：{merge_data.get('changes_summary', '')}"
            )
        elif modification_type == "deleted":
            merge_context = "【GC/PC 对比】该条款在 PC 中被删除。"

    time_bar_context = ""
    if isinstance(time_bar_data, dict) and time_bar_data.get("total_time_bars", 0) > 0:
        has_strict = "⚠️ 检出严格时效（逾期丧权）" if time_bar_data.get("has_strict_time_bar") else ""
        time_bar_context = (
            f"【时效分析】共识别 {time_bar_data.get('total_time_bars', 0)} 个时效要求。{has_strict}"
        )

    er_context = ""
    if isinstance(er_data, dict) and er_data.get("relevant_sections"):
        er_context = f"【ER 检索】关联段落数量：{len(er_data.get('relevant_sections', []))}"

    return FIDIC_DOMAIN_INSTRUCTION.format(
        merge_context=merge_context,
        time_bar_context=time_bar_context,
        er_context=er_context,
    ).strip()


def _build_sha_spa_instruction(skill_context: Dict[str, Any]) -> str:
    conditions_data = skill_context.get("spa_extract_conditions", {})
    rw_data = skill_context.get("spa_extract_reps_warranties", {})
    indemnity_data = skill_context.get("spa_indemnity_analysis", {})

    conditions_context = ""
    if isinstance(conditions_data, dict) and conditions_data.get("total_conditions", 0) > 0:
        conditions_context = (
            "【先决条件】"
            f"总计 {conditions_data.get('total_conditions', 0)} 项，"
            f"买方 {conditions_data.get('buyer_conditions', 0)} 项，"
            f"卖方 {conditions_data.get('seller_conditions', 0)} 项。"
        )

    rw_context = ""
    if isinstance(rw_data, dict) and rw_data.get("total_items", 0) > 0:
        rw_context = (
            "【R&W】"
            f"共 {rw_data.get('total_items', 0)} 项，"
            f"knowledge 限定 {rw_data.get('knowledge_qualified_count', 0)} 项，"
            f"materiality 限定 {rw_data.get('materiality_qualified_count', 0)} 项。"
        )

    indemnity_context = ""
    if isinstance(indemnity_data, dict):
        parts = []
        if indemnity_data.get("has_cap"):
            cap = indemnity_data.get("cap_amount") or indemnity_data.get("cap_percentage", "")
            parts.append(f"cap={cap}")
        if indemnity_data.get("has_basket"):
            parts.append(
                f"basket={indemnity_data.get('basket_amount', '')}({indemnity_data.get('basket_type', '')})"
            )
        if indemnity_data.get("survival_period"):
            parts.append(f"survival={indemnity_data.get('survival_period', '')}")
        if parts:
            indemnity_context = f"【赔偿参数】{'；'.join(parts)}"

    return SHA_SPA_DOMAIN_INSTRUCTION.format(
        conditions_context=conditions_context,
        rw_context=rw_context,
        indemnity_context=indemnity_context,
    ).strip()


def build_clause_analyze_messages(
    *,
    language: str,
    our_party: str,
    clause_id: str,
    clause_name: str,
    description: str,
    priority: str,
    clause_text: str,
    skill_context: Dict[str, Any] | None = None,
    domain_id: str | None = None,
) -> List[Dict[str, str]]:
    system = CLAUSE_ANALYZE_SYSTEM.format(
        anti_injection=_anti_injection_instruction(language, our_party),
        jurisdiction_instruction=_jurisdiction_instruction(language),
        our_party=our_party,
    )
    if domain_id == "fidic":
        system = f"{system}\n\n{_build_fidic_instruction(skill_context or {})}"
    elif domain_id == "sha_spa":
        system = f"{system}\n\n{_build_sha_spa_instruction(skill_context or {})}"
    user = (
        f"【条款信息】\n"
        f"- 条款编号：{clause_id}\n"
        f"- 条款名称：{clause_name}\n"
        f"- 审查重点：{description}\n"
        f"- 优先级：{priority}\n\n"
        f"【条款原文】\n<<<CLAUSE_START>>>\n{clause_text}\n<<<CLAUSE_END>>>"
    )
    if skill_context:
        extra_context = _format_skill_context(skill_context)
        if extra_context:
            user += f"\n\n【辅助分析信息】\n{extra_context}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_clause_generate_diffs_messages(
    *,
    clause_id: str,
    clause_text: str,
    risks: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    user = (
        f"【条款编号】{clause_id}\n"
        f"【条款原文】\n<<<CLAUSE_START>>>\n{clause_text}\n<<<CLAUSE_END>>>\n\n"
        f"【已识别风险点】\n{json.dumps(risks, ensure_ascii=False)}"
    )
    return [{"role": "system", "content": CLAUSE_GENERATE_DIFFS_SYSTEM}, {"role": "user", "content": user}]


def build_clause_validate_messages(
    *,
    clause_id: str,
    clause_text: str,
    risks: List[Dict[str, Any]],
    diffs: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    user = (
        f"【条款编号】{clause_id}\n"
        f"【条款原文】\n<<<CLAUSE_START>>>\n{clause_text}\n<<<CLAUSE_END>>>\n\n"
        f"【风险分析结果】\n{json.dumps(risks, ensure_ascii=False)}\n\n"
        f"【修改建议】\n{json.dumps(diffs, ensure_ascii=False)}"
    )
    return [{"role": "system", "content": CLAUSE_VALIDATE_SYSTEM}, {"role": "user", "content": user}]


def build_summarize_messages(
    *,
    total_clauses: int,
    total_risks: int,
    high_risks: int,
    medium_risks: int,
    low_risks: int,
    total_diffs: int,
    findings_detail: str,
) -> List[Dict[str, str]]:
    user = (
        f"【审查概况】\n"
        f"- 共审查 {total_clauses} 个条款\n"
        f"- 发现 {total_risks} 个风险点（高：{high_risks}，中：{medium_risks}，低：{low_risks}）\n"
        f"- 生成 {total_diffs} 条修改建议\n\n"
        f"【各条款审查发现】\n{findings_detail}"
    )
    return [{"role": "system", "content": SUMMARIZE_SYSTEM}, {"role": "user", "content": user}]
