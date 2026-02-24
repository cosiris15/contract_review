"""Local skill: extract financial terms from clause text."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ._utils import get_clause_text, get_llm_client


class ExtractFinancialTermsInput(BaseModel):
    clause_id: str
    document_structure: Any


class FinancialTerm(BaseModel):
    term_type: str
    value: str
    context: str
    source: str = "regex"
    semantic_meaning: str = ""


class ExtractFinancialTermsOutput(BaseModel):
    clause_id: str
    terms: List[FinancialTerm] = Field(default_factory=list)
    total_terms: int = 0
    llm_used: bool = False


_FINANCIAL_PATTERNS: List[tuple[str, str]] = [
    (r"(\d+(?:\.\d+)?)\s*[%％]", "percentage"),
    (r"(?:USD|EUR|CNY|RMB|GBP|\$|€|£|¥)\s*[\d,]+(?:\.\d+)?", "amount"),
    (r"[\d,]+(?:\.\d+)?\s*(?:万元|亿元|元|美元|欧元|英镑)", "amount"),
    (r"\d+\s*(?:天|日|个月|月|年|days?|months?|years?|weeks?|周)", "duration"),
    (r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?", "date"),
]


def _extract_json(raw_text: str) -> List[Dict[str, Any]]:
    parsed = _parse_json_array(raw_text)
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _parse_json_array(raw_text: str) -> Any:
    payload = (raw_text or "").strip()
    if not payload:
        return None

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
            return parsed
    return None


def _regex_extract(clause_text: str) -> List[FinancialTerm]:
    terms: List[FinancialTerm] = []
    for pattern, term_type in _FINANCIAL_PATTERNS:
        for match in re.finditer(pattern, clause_text):
            start = max(0, match.start() - 30)
            end = min(len(clause_text), match.end() + 30)
            context = clause_text[start:end].strip()
            terms.append(
                FinancialTerm(
                    term_type=term_type,
                    value=match.group(0).strip(),
                    context=context,
                    source="regex",
                )
            )
    return terms


def _build_prompt(clause_text: str, regex_terms: List[FinancialTerm]) -> List[Dict[str, str]]:
    existing = "\n".join(f"- [{t.term_type}] {t.value}" for t in regex_terms) or "（无）"
    system = (
        "你是合同财务条款分析专家。请从条款文本中提取所有财务相关条款。"
        "已由规则引擎提取的条款会提供给你，请勿重复这些条款。"
        "请重点关注："
        "1. 用文字表述的金额或比例（如'合同总价的百分之五'、'twice the Contract Price'）；"
        "2. 隐含的财务上限/下限/计算公式；"
        "3. 非数字时限表述（如'a reasonable period'、'合理期限'）；"
        "4. 金额与条件的关联关系。"
        "只返回 JSON 数组，不得输出额外文本。"
        "每项字段：term_type（percentage/amount/duration/date/formula）, value, context, semantic_meaning。"
    )
    user_msg = (
        f"条款文本：\n{clause_text[:3000]}\n\n"
        f"已提取的财务条款（请勿重复）：\n{existing}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]


def _normalize_llm_terms(parsed_rows: List[Dict[str, Any]]) -> List[FinancialTerm]:
    terms: List[FinancialTerm] = []
    for row in parsed_rows:
        value = str(row.get("value", "") or "").strip()
        if not value:
            continue
        terms.append(
            FinancialTerm(
                term_type=str(row.get("term_type", "") or "amount"),
                value=value,
                context=str(row.get("context", "") or ""),
                source="llm",
                semantic_meaning=str(row.get("semantic_meaning", "") or ""),
            )
        )
    return terms


async def _llm_extract(
    clause_text: str, regex_terms: List[FinancialTerm]
) -> tuple[List[FinancialTerm], bool]:
    llm_client = get_llm_client()
    if llm_client is None:
        return [], False

    try:
        response = await llm_client.chat(_build_prompt(clause_text, regex_terms), max_output_tokens=800)
    except Exception:  # pragma: no cover - defensive
        return [], False

    parsed_payload = _parse_json_array(str(response))
    if not isinstance(parsed_payload, list):
        return [], False

    parsed_rows = [row for row in parsed_payload if isinstance(row, dict)]
    return _normalize_llm_terms(parsed_rows), True


def _merge_results(regex_terms: List[FinancialTerm], llm_terms: List[FinancialTerm]) -> List[FinancialTerm]:
    seen_values = {term.value.strip() for term in regex_terms}
    merged = list(regex_terms)
    for term in llm_terms:
        normalized = term.value.strip()
        if not normalized or normalized in seen_values:
            continue
        merged.append(term)
        seen_values.add(normalized)
    return merged


async def extract_financial_terms(input_data: ExtractFinancialTermsInput) -> ExtractFinancialTermsOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    if not clause_text.strip():
        return ExtractFinancialTermsOutput(clause_id=input_data.clause_id)

    regex_terms = _regex_extract(clause_text)
    llm_terms, llm_used = await _llm_extract(clause_text, regex_terms)
    terms = _merge_results(regex_terms, llm_terms)

    return ExtractFinancialTermsOutput(
        clause_id=input_data.clause_id,
        terms=terms,
        total_terms=len(terms),
        llm_used=llm_used,
    )


def prepare_input(clause_id: str, primary_structure: Any, _state: dict) -> ExtractFinancialTermsInput:
    return ExtractFinancialTermsInput(
        clause_id=clause_id,
        document_structure=primary_structure,
    )
