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
        if isinstance(data, dict):
            parts.append(f"[{skill_id}]\n{json.dumps(data, ensure_ascii=False, indent=2)}")
            continue
        if isinstance(data, str):
            parts.append(f"[{skill_id}]\n{data}")
            continue
        parts.append(f"[{skill_id}]\n{str(data)}")
    return "\n\n".join(parts)


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
) -> List[Dict[str, str]]:
    system = CLAUSE_ANALYZE_SYSTEM.format(
        anti_injection=_anti_injection_instruction(language, our_party),
        jurisdiction_instruction=_jurisdiction_instruction(language),
        our_party=our_party,
    )
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
